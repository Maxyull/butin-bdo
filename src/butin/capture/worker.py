"""Faire tourner la capture pendant qu'on regarde l'interface.

Le dernier maillon manquant. `CaptureLoop` sait lire l'écran, `SessionRecorder`
sait ranger ce qu'elle confirme, l'interface sait afficher la base : personne ne
faisait tourner la boucle. Le bouton « Démarrer une session » ouvrait une ligne
dans la base et **rien ne l'alimentait**, ce qui donnait un compteur à zéro
impossible à distinguer d'une session sans butin.

Un fil, et pourquoi
--------------------

La reconnaissance de texte coûte une seconde par image. La faire tourner dans le
fil du serveur figerait l'interface pendant tout ce temps, à chaque tour. Elle
tourne donc dans un fil à part, et l'interface se contente de lire son état.

Ce qui compte dans un fil de fond, c'est **ce qu'il fait quand il rate**
-------------------------------------------------------------------------

Un fil qui meurt sur une exception disparaît sans bruit. L'interface continuerait
d'afficher « session en cours », la base ne recevrait plus rien, et l'utilisateur
verrait un total qui n'augmente pas sans savoir si c'est la faute du jeu, du
calibrage ou du programme. C'est très exactement le mode de défaillance que ce
projet refuse.

Donc : toute exception est **retenue et exposée**, la session est marquée en
échec, et `status()` dit laquelle. Rien n'est avalé.

Ce qui est vérifié AVANT d'ouvrir une session
-----------------------------------------------

Le calibrage. Sans lui on ne sait pas où regarder, et capturer une zone au
hasard donne un journal vide, donc zéro drop, donc une session qui a l'air
d'avoir marché. Refuser de démarrer est la seule réponse honnête.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..catalog.matcher import ItemMatcher, Scope
from ..recorder import SessionRecorder
from ..store import SessionStore
from .calibrate import Calibration
from .lines import DEFAULT_FORMAT, ChatLineFormat
from .loop import CaptureLoop, LoopConfig, config_from_calibration

_log = logging.getLogger(__name__)


class CaptureUnavailable(RuntimeError):
    """La capture ne peut pas démarrer, et on dit pourquoi.

    Levée AVANT qu'une session soit ouverte. Une session ouverte que rien
    n'alimente est pire qu'un refus : elle ressemble à une session normale dont
    le farm n'aurait rien donné.
    """


@dataclass(frozen=True, slots=True)
class CaptureStatus:
    """Ce que l'interface a besoin de savoir de la capture en cours."""

    running: bool
    ticks: int
    ocr_reads: int
    skipped_frames: int
    lost_resolved: int
    recorded_events: int
    recorded_silver: int
    error: str = ""
    """Message de l'exception qui a tué le fil, vide s'il tourne encore.

    Exposé jusque dans l'interface : un fil mort en silence laisserait un total
    qui n'augmente plus, sans rien pour distinguer la panne du farm calme.
    """

    def to_dict(self) -> dict[str, Any]:
        return {
            "en_cours": self.running,
            "tours": self.ticks,
            "lectures": self.ocr_reads,
            "images_ecartees": self.skipped_frames,
            "butin_perdu": self.lost_resolved,
            "drops_enregistres": self.recorded_events,
            "silver_enregistre": self.recorded_silver,
            "erreur": self.error,
        }


@dataclass(slots=True)
class _Compteurs:
    ticks: int = 0
    ocr_reads: int = 0
    error: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass(slots=True)
class _Acquis:
    """Ce qu'ont compté les tranches de capture déjà terminées.

    Une pause construit une boucle et un enregistreur neufs à la reprise, dont
    les compteurs repartent de zéro. Sans ce report, l'interface afficherait
    « 0 drop » après une pause sur une session qui en a enregistré trois cents :
    un compteur qui **recule** est pire qu'un compteur qui stagne, puisqu'il
    ressemble à une perte de données alors que la base, elle, a tout gardé.
    """

    ticks: int = 0
    ocr_reads: int = 0
    skipped_frames: int = 0
    lost_resolved: int = 0
    recorded_events: int = 0
    recorded_silver: int = 0


class CaptureWorker:
    """Fait tourner la boucle dans un fil, et rend compte de ce qu'elle fait.

    `loop_factory` est injectable pour que les tests ne touchent ni à l'écran ni
    au moteur de reconnaissance : l'un demande un affichage, l'autre coûte une
    seconde par appel, et l'intégration continue n'a ni l'un ni l'autre.
    """

    def __init__(
        self,
        store: SessionStore,
        *,
        matcher: ItemMatcher | None = None,
        config: LoopConfig | None = None,
        fmt: ChatLineFormat = DEFAULT_FORMAT,
        scope: Scope | None = None,
        loop_factory: Callable[[Calibration, LoopConfig], CaptureLoop] | None = None,
        calibration_loader: Callable[[], Calibration | None] = Calibration.load,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._store = store
        self._matcher = matcher
        self._config = config
        self._fmt = fmt
        self._scope = scope
        self._loop_factory = loop_factory
        self._calibration_loader = calibration_loader
        self._clock = clock
        self._sleep = sleep

        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._recorder: SessionRecorder | None = None
        self._compteurs = _Compteurs()
        self._acquis = _Acquis()

    # -- état ------------------------------------------------------------

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def status(self) -> CaptureStatus:
        enregistreur = self._recorder
        acquis = self._acquis
        with self._compteurs.lock:
            tours, lectures, erreur = (
                self._compteurs.ticks,
                self._compteurs.ocr_reads,
                self._compteurs.error,
            )
        if enregistreur is None:
            return CaptureStatus(
                running=False,
                ticks=acquis.ticks + tours,
                ocr_reads=acquis.ocr_reads + lectures,
                skipped_frames=acquis.skipped_frames,
                lost_resolved=acquis.lost_resolved,
                recorded_events=acquis.recorded_events,
                recorded_silver=acquis.recorded_silver,
                error=erreur,
            )
        return CaptureStatus(
            running=self.running,
            ticks=acquis.ticks + tours,
            ocr_reads=acquis.ocr_reads + lectures,
            skipped_frames=acquis.skipped_frames + enregistreur.skipped_frames,
            lost_resolved=acquis.lost_resolved + enregistreur.loop.stager.lost_resolved,
            recorded_events=acquis.recorded_events + enregistreur.recorded_events,
            recorded_silver=acquis.recorded_silver + enregistreur.recorded_silver,
            error=erreur,
        )

    # -- cycle de vie ----------------------------------------------------

    def start(self, session_id: int, *, reprise: bool = False) -> None:
        """Démarre la capture, ou refuse en disant pourquoi.

        ⚠️ Tout ce qui peut échouer est fait ICI, dans le fil de l'appelant :
        lire le calibrage, construire la boucle. Repousser ces échecs dans le
        fil de fond les rendrait invisibles au moment où l'utilisateur clique,
        et il verrait une session démarrer puis ne rien compter.

        ⭐ `reprise` ne change qu'une chose : les compteurs déjà acquis sont
        conservés au lieu d'être remis à zéro. La boucle, elle, est **neuve dans
        les deux cas**, et c'est ce qui rend la reprise sûre : sa première
        lecture amorce le suivi avec ce qui est à l'écran sans rien compter (voir
        `_seeded` dans `loop.py`). Reprendre en gardant l'ancienne boucle
        recompterait les dix-sept lignes encore affichées, c'est-à-dire
        inventerait des drops, l'erreur que ce projet refuse.
        """
        if self.running:
            raise CaptureUnavailable("une capture tourne déjà")
        if not reprise:
            self._acquis = _Acquis()

        calibrage = self._calibration_loader()
        if calibrage is None:
            raise CaptureUnavailable(
                "zone du chat non calibrée : lancer « butin calibrer » devant le jeu, "
                "journal d'acquisition visible"
            )

        reglage = config_from_calibration(calibrage, self._config)
        boucle = self._construire(calibrage, reglage)
        self._recorder = SessionRecorder(boucle, self._store, session_id)
        self._compteurs = _Compteurs()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._tourner,
            args=(reglage.capture_interval_s,),
            daemon=True,
            name="butin-capture",
        )
        self._thread.start()

    def stop(self, *, timeout: float = 5.0, garder_les_compteurs: bool = False) -> int:
        """Arrête la capture et enregistre ce qui attendait encore.

        Le `flush` n'est pas une politesse : le butin vu une seule fois au
        moment de l'arrêt est bien tombé, et le perdre serait une erreur dans le
        mauvais sens. Il vaut aussi pour une pause, pour la même raison.
        """
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
            if thread.is_alive():
                # Le fil est bloqué, sans doute dans une reconnaissance en
                # cours. On le dit plutôt que d'attendre indéfiniment, et on
                # n'écrit rien : deux écrivains sur la même session mélangeraient
                # leurs lignes.
                _log.warning("le fil de capture ne s'est pas arrêté en %.0f s", timeout)
                return 0
        self._thread = None

        enregistreur = self._recorder
        if enregistreur is None:
            return 0
        ecrites = enregistreur.flush(time.time())
        if garder_les_compteurs:
            self._reporter(enregistreur)
        return ecrites

    def pause(self, *, timeout: float = 5.0) -> int:
        """Arrête la capture sans perdre ce que la session a déjà compté.

        Exactement `stop`, à ceci près que les compteurs affichés survivent :
        c'est la même session, elle reprendra. Rend le nombre de drops encore en
        attente qui ont été enregistrés au passage.
        """
        return self.stop(timeout=timeout, garder_les_compteurs=True)

    def _reporter(self, enregistreur: SessionRecorder) -> None:
        """Verse les compteurs de la tranche qui s'achève dans le total acquis."""
        with self._compteurs.lock:
            tours, lectures = self._compteurs.ticks, self._compteurs.ocr_reads
        self._acquis = _Acquis(
            ticks=self._acquis.ticks + tours,
            ocr_reads=self._acquis.ocr_reads + lectures,
            skipped_frames=self._acquis.skipped_frames + enregistreur.skipped_frames,
            lost_resolved=self._acquis.lost_resolved + enregistreur.loop.stager.lost_resolved,
            recorded_events=self._acquis.recorded_events + enregistreur.recorded_events,
            recorded_silver=self._acquis.recorded_silver + enregistreur.recorded_silver,
        )
        self._recorder = None
        self._compteurs = _Compteurs()

    # -- interne ---------------------------------------------------------

    def _construire(self, calibration: Calibration, config: LoopConfig) -> CaptureLoop:
        if self._loop_factory is not None:
            return self._loop_factory(calibration, config)

        # Importés ici et pas en tête de module : `mss` demande un affichage et
        # `rapidocr` charge une trentaine de mégaoctets de modèles. Rien de tout
        # ça ne doit être payé pour construire l'objet, ni pour l'analyser.
        from .ocr import TextReader
        from .screen import ScreenCapture

        if self._matcher is None:
            raise CaptureUnavailable(
                "catalogue d'objets indisponible : sans lui aucun drop ne peut être nommé"
            )
        lecteur = TextReader()
        lecteur.warmup()
        return CaptureLoop(
            ScreenCapture(),
            lecteur,
            self._matcher,
            calibration.region,
            config=config,
            fmt=self._fmt,
            scope=self._scope,
        )

    def _tourner(self, interval_s: float) -> None:
        """Boucle du fil de fond. Ne laisse jamais une exception disparaître."""
        enregistreur = self._recorder
        if enregistreur is None:
            return
        try:
            while not self._stop.is_set():
                debut = self._clock()
                resultat = enregistreur.tick(debut)
                with self._compteurs.lock:
                    self._compteurs.ticks += 1
                    if resultat.ocr_ran:
                        self._compteurs.ocr_reads += 1
                # Le pas est compté depuis le DÉBUT du tour : sinon le coût de
                # la reconnaissance s'ajoute à l'intervalle et la cadence dérive
                # d'autant, ce qui fausserait la mesure de défilement.
                reste = interval_s - (self._clock() - debut)
                if reste > 0:
                    self._sleep(reste)
        except Exception as exc:
            # Volontairement large. Un fil qui meurt sans laisser de trace est
            # pire que n'importe quelle exception : l'interface continuerait
            # d'afficher « session en cours » sur un total qui n'augmente plus.
            _log.exception("le fil de capture s'est arrêté sur une erreur")
            with self._compteurs.lock:
                self._compteurs.error = f"{type(exc).__name__} : {exc}"
