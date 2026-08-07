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
from ..diagnostic import SessionJournal
from ..recorder import SessionRecorder
from ..store import SessionStore
from .calibrate import Calibration
from .lines import DEFAULT_FORMAT, ChatLineFormat
from .loop import CaptureLoop, LoopConfig, config_from_calibration
from .priorite import abaisser_le_fil_courant

_log = logging.getLogger(__name__)


def _minute_du_jour() -> int:
    """Minute du jour à l'heure locale, celle qu'affiche le journal du jeu."""
    maintenant = time.localtime()
    return maintenant.tm_hour * 60 + maintenant.tm_min


class CaptureUnavailable(RuntimeError):
    """La capture ne peut pas démarrer, et on dit pourquoi.

    Levée AVANT qu'une session soit ouverte. Une session ouverte que rien
    n'alimente est pire qu'un refus : elle ressemble à une session normale dont
    le farm n'aurait rien donné.
    """


SECONDES_AVANT_ALERTE = 30.0
"""Silence de la zone calibrée au-delà duquel on prévient le joueur.

⛔ Tiré des données, pas posé au jugé. Sur la session 0014 du 07/08/2026, la
seule de plus de mille secondes avec un calibrage impeccable (force 0,61), il
n'existe que **deux** plages sans la moindre ligne :

    4,9 s   au démarrage, le chat était encore vide
    247,0 s pendant que le menu Échap couvrait le chat

Trente secondes séparent ces deux populations avec un facteur six en dessous et
huit au-dessus. Le vrai aveuglement dure des minutes ; les creux normaux, des
secondes.

⚠️ On avertit, on n'arrête rien. Couper la session parce qu'on ne voit plus le
chat ferait perdre ce qui a déjà été compté, alors que le joueur n'a peut-être
ouvert sa carte que dix secondes.
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

    secondes_sans_texte: float = 0.0
    """Depuis combien de temps la zone calibrée ne rend plus une seule ligne.

    ⛔ Zéro tant que la zone n'a jamais rien rendu : un chat encore vide au
    démarrage n'est pas une panne. Voir `_Compteurs.a_deja_vu_du_texte`.
    """

    @property
    def chat_masque(self) -> bool:
        """Vrai quand la zone ne rend plus rien depuis assez longtemps.

        C'est ce que l'interface affiche, et c'est **la** information qui
        manquait : un compteur qui ne compte rien ressemble à un farm pauvre.
        """
        return self.secondes_sans_texte >= SECONDES_AVANT_ALERTE

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
            "secondes_sans_texte": round(self.secondes_sans_texte, 1),
            "chat_masque": self.chat_masque,
        }


@dataclass(slots=True)
class _Compteurs:
    ticks: int = 0
    ocr_reads: int = 0
    error: str = ""
    texte_vu_a: float | None = None
    """Horloge monotone de la dernière lecture qui a rendu au moins une ligne.

    `None` tant qu'aucune reconnaissance n'a eu lieu : on ne peut pas dire
    « ça fait dix secondes que je ne vois rien » avant d'avoir regardé une
    seule fois."""

    a_deja_vu_du_texte: bool = False
    """⛔ Sans lui, une session lancée devant un chat vide crierait aussitôt.

    On ne prévient que si la zone a **déjà** rendu des lignes puis n'en rend
    plus : c'est ça, être masqué. Un chat encore vide au démarrage n'est pas
    une panne, c'est un début de session."""

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
        clock_of_day: Callable[[], int] | None = None,
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
        self._clock_of_day = clock_of_day or _minute_du_jour
        """Minute du jour, à l'heure LOCALE. Injectable pour les tests, qui ne
        peuvent pas dépendre de l'heure qu'il est quand ils tournent.

        ⚠️ Heure locale et non UTC : c'est celle que le client du jeu affiche
        dans son journal, et c'est à elle qu'on compare."""

        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._recorder: SessionRecorder | None = None
        self._journal = SessionJournal(session_id=0)
        """Journal de la tranche en cours. Un journal « vide » (sans chemin)
        avale tout ce qu'on lui donne, ce qui évite un test de nullité à
        chaque tour de boucle sur le chemin le plus chaud."""
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
            # ⛔ Le silence ne compte QUE si la zone a déjà rendu des lignes,
            # et QUE si le fil tourne encore. Sinon une session arrêtée
            # afficherait « je ne vois plus le chat » pour l'éternité, alors
            # que personne ne regarde plus.
            silence = 0.0
            if self._compteurs.a_deja_vu_du_texte and self._compteurs.texte_vu_a is not None:
                silence = max(0.0, self._clock() - self._compteurs.texte_vu_a)

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
            # Seulement quand le fil tourne : à l'arrêt, plus personne ne
            # regarde et l'alerte n'aurait plus de sens.
            secondes_sans_texte=silence if self.running else 0.0,
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
        # ⭐ L'heure du DÉMARRAGE, relue à chaque appel, reprise comprise. Sur
        # une reprise c'est même exactement ce qu'il faut : tout ce qui date
        # d'avant la pause est déjà compté, et le refuser évite de le recompter.
        boucle = self._construire(calibrage, reglage, self._clock_of_day())
        self._recorder = SessionRecorder(boucle, self._store, session_id)
        # ⭐ Un journal de diagnostic par tranche de capture. Ouvert ici et pas
        # plus tôt : c'est le seul point où le calibrage est connu ET où la
        # capture est certaine de démarrer. Une reprise après pause ouvre un
        # nouveau fichier, ce qui est voulu — chaque tranche a ses conditions,
        # et une zone recalibrée entre les deux ne se lit pas dans le même
        # fichier que celle d'avant.
        self._journal = SessionJournal.ouvrir(
            session_id,
            entete={
                "reprise": reprise,
                "zone": calibrage.describe(),
                "cadence_s": reglage.capture_interval_s,
                "ocr_min_interval_s": reglage.ocr_min_interval_s,
            },
        )
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
        # ⛔ Le journal se ferme ICI et pas dans `_reporter` : celui-ci n'est
        # appelé que sur une PAUSE, donc un arrêt normal laissait le fichier
        # sans son bilan — c'est-à-dire sans les totaux, qui sont la première
        # chose qu'on lit. Trouvé par le test de bout en bout, pas en relisant.
        self._fermer_le_journal(enregistreur)
        if garder_les_compteurs:
            self._reporter(enregistreur)
        return ecrites

    def _fermer_le_journal(self, enregistreur: SessionRecorder) -> None:
        with self._compteurs.lock:
            tours, lectures = self._compteurs.ticks, self._compteurs.ocr_reads
            panne = self._compteurs.error
        self._journal.fermer(
            {
                "tours": tours,
                "lectures_ocr": lectures,
                "images_ecartees": enregistreur.skipped_frames,
                "drops_enregistres": enregistreur.recorded_events,
                "silver_enregistre": enregistreur.recorded_silver,
                "lignes_perdues": enregistreur.loop.stager.lost_resolved,
                "panne": panne,
            }
        )
        self._journal = SessionJournal(session_id=0)

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

    def _construire(
        self, calibration: Calibration, config: LoopConfig, session_start_min: int
    ) -> CaptureLoop:
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
            session_start_min=session_start_min,
        )

    def _noter_la_visibilite(self, trace: dict[str, Any] | None, maintenant: float) -> None:
        """Retient depuis quand la zone calibrée ne rend plus une seule ligne.

        ⛔ À appeler SOUS le verrou des compteurs, comme le reste.

        ⭐ Le signal n'est pas « aucun drop », c'est **aucune ligne du tout**
        après en avoir vu. Le journal du jeu reste affiché plusieurs secondes :
        passer brutalement de vingt-trois lignes à zéro veut dire que la zone
        est masquée, pas que le farm est calme.

        Mesuré sur la session 0014 du 07/08/2026, celle où Maxime a ouvert le
        menu Échap : **247 secondes d'affilée sans une seule ligne**, sur une
        session de 1 127 s au calibrage impeccable (force 0,61). Butin a
        continué d'afficher son total et son silver par heure comme si de rien
        n'était, et il manquait 560 objets sur 4 080.
        """
        lues = (trace or {}).get("lues")
        if lues:
            self._compteurs.texte_vu_a = maintenant
            self._compteurs.a_deja_vu_du_texte = True
        elif self._compteurs.texte_vu_a is None:
            # Première lecture, et elle est vide : on démarre le compte à
            # partir de maintenant plutôt que depuis l'époque Unix.
            self._compteurs.texte_vu_a = maintenant

    def _tourner(self, interval_s: float) -> None:
        """Boucle du fil de fond. Ne laisse jamais une exception disparaître."""
        # ⭐ Le jeu passe devant. Demandé ICI, dans le fil lui-même, parce que
        # la priorité est une propriété du fil courant : la poser depuis
        # `start()` la poserait sur le fil de l'interface, c'est-à-dire sur
        # exactement celui qu'il ne faut pas ralentir.
        #
        # Ça ne change AUCUN calcul, seulement l'ordre de passage. Voir
        # `priorite.py` pour la piste concurrente (borner les threads
        # d'onnxruntime), mesurée et refusée parce qu'elle perd des lignes.
        abaisser_le_fil_courant()

        enregistreur = self._recorder
        if enregistreur is None:
            return
        journal = self._journal
        try:
            while not self._stop.is_set():
                debut = self._clock()
                resultat = enregistreur.tick(debut)
                # Écrit AVANT les compteurs : si le fil meurt sur le tour
                # suivant, la dernière lecture est déjà sur le disque. C'est
                # justement celle-là qu'on voudra lire.
                journal.lecture(resultat.trace)
                with self._compteurs.lock:
                    self._compteurs.ticks += 1
                    if resultat.ocr_ran:
                        self._compteurs.ocr_reads += 1
                        self._noter_la_visibilite(resultat.trace, debut)
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
