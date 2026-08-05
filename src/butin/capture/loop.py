"""Boucle de capture, à deux vitesses.

Pourquoi découpler
------------------

Mesuré : la reconnaissance de texte coûte **336 ms par image** sur une zone de
520 x 385, et **1 100 ms** sur une zone de 780 x 575 (banc du 05/08/2026), alors
que la capture et la mesure de défilement en coûtent moins de dix à elles deux.
Le coût suit la surface, donc `ocr_min_interval_s` ci-dessous promet une cadence
que la machine ne tient pas dès que la zone du chat est grande. Faire
tourner toute la chaîne au rythme de l'OCR reviendrait à mesurer le défilement
trois fois moins souvent que nécessaire, pour rien.

La boucle vise donc deux vitesses :

* **toutes les 100 ms** : capture, mesure du défilement, accumulation ;
* **quand il y a quelque chose à lire** : reconnaissance de texte, alignement,
  validation.

Le défilement accumulé entre deux passages d'OCR est exactement ce que
`tracking/alignment.py` attend comme `expected_new`. Le découplage n'est donc
pas seulement moins coûteux, il rend la prédiction **plus fine** : un défilement
rapide qui aurait été vu d'un bloc à 350 ms est vu en trois mesures à 100 ms.

⚠️ **« Vise » et non « fait », par défaut.** Tant que `LoopConfig.async_ocr` vaut
`False` (le défaut), les deux vitesses restent conceptuelles : `tick()` capture,
mesure le défilement, PUIS attend l'OCR en bloquant le même fil avant de rendre
la main. C'est mesuré et documenté depuis le 05/08 : en conditions réelles, le
défilement n'est alors mesuré qu'une fois par seconde environ au lieu de dix.

Un vrai découplage — un fil à part pour la reconnaissance — existe derrière
`async_ocr=True`, et il a été mesuré en temps réel sur une vraie rafale : il
lit MOINS souvent que le mode synchrone (32 lectures sur 600 images contre 52)
et compte moins bien (−8,8 % contre +2,0 %). Contre-intuitif, réfléchi, mesuré
deux fois, et laissé à `False` en conséquence. Voir la docstring du réglage
pour le détail et ce qui reste à comprendre.

La règle de mesure : la colonne du texte, sur un masque de pixels clairs
------------------------------------------------------------------------

📕 `docs/banc-essai.md`, partie 4 B. La règle d'origine était la **colonne des
pastilles de canal**, et le banc l'a réfutée le 05/08/2026 sur 300 images de
vrai farm : **zéro décalage juste sur les 37 transitions** où une ligne apparaît
réellement, la pire des bandes essayées.

La raison est structurelle : les pastilles `Système` sont toutes identiques et
espacées d'exactement un pas de ligne. Un défilement d'une ligne superpose la
pastille `n` sur la pastille `n+1`, donc ne change rien. C'était précisément la
colonne aveugle à ce qu'on lui demandait de voir. Le chiffre de 3,9 contre 11,3
qui l'avait fait retenir comparait deux captures de scènes **différentes** : il
mesurait le bruit du décor, pas un défilement.

Ce qui marche : la colonne du **texte**, comparée sur un **masque de pixels
clairs**. Le texte du journal est peint en clair, le monde du jeu est sombre
(médiane 21 sur 255) : le masque le fait disparaître, et il ne reste que les
lettres, qui elles défilent. **32 décalages justes sur 37**, aucune fausse
détection sur 262 transitions immobiles, et jamais de décalage faux.

⚠️ Le garde-fou de stabilité n'est PAS utilisé pour conditionner l'OCR, et c'est
délibéré. Il a été écrit pour un fond fixe, où l'immobilité signifie que
l'animation d'apparition est terminée. Avec un fond transparent sur un monde qui
bouge en permanence, il ne se déclencherait jamais, ou tout le temps selon le
seuil, sans jamais rien dire du texte. La vraie défense contre une lecture prise
en pleine animation reste le **vote sur plusieurs images** de `staging.py`, qui
n'a pas ce défaut.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field, replace
from typing import Protocol

from ..catalog.matcher import ItemMatcher, Scope
from ..tracking.alignment import (
    AlignmentResult,
    align,
    is_glitch_frame,
    is_implausible_jump,
    plausible_max_new,
)
from ..tracking.models import LootEvent, ObservedLine
from ..tracking.scroll import (
    BRIGHT_THRESHOLD,
    ScrollResult,
    estimate_text_scroll_px,
    expected_new_lines,
)
from ..tracking.similarity import MatchConfig
from ..tracking.staging import LootStager
from .calibrate import Calibration
from .lines import DEFAULT_FORMAT, ChatLineFormat, ParsedLine, is_stale, parse_frame
from .screen import GrayImage, Region

_log = logging.getLogger(__name__)


_FLUSH_OCR_TIMEOUT_S = 5.0
"""Attente maximale d'un travail de reconnaissance encore en vol à l'arrêt.

Le même ordre de grandeur que `CaptureWorker.stop`'s délai par défaut, et pour
la même raison : au-delà, le fil est probablement bloqué ailleurs, et attendre
indéfiniment retiendrait le bouton Arrêter pour une seule lecture perdue."""


class FrameSource(Protocol):
    """Ce que la boucle attend d'une source d'images."""

    def grab(self, region: Region) -> GrayImage: ...


class LineSource(Protocol):
    """Ce que la boucle attend d'un lecteur de texte."""

    def read_text(self, image: GrayImage) -> list[str]: ...


@dataclass(frozen=True, slots=True)
class LoopConfig:
    """Réglages de cadence et de géométrie."""

    capture_interval_s: float = 0.10
    """Période de la boucle rapide. Capture plus mesure de défilement."""

    ocr_min_interval_s: float = 0.35
    """Délai minimal entre deux reconnaissances de texte.

    Calé sur le coût mesuré de 336 ms : demander l'OCR plus souvent ne ferait
    qu'empiler du retard, la boucle ne pouvant pas aller plus vite que son
    maillon le plus lent.
    """

    ocr_max_idle_s: float = 2.0
    """Délai au bout duquel on relit même sans défilement détecté.

    Nécessaire : une nouvelle ligne peut apparaître **sans** défilement tant que
    la fenêtre n'est pas pleine, ce qui est le cas au début d'une session. Sans
    ce filet, ces premières lignes ne seraient jamais lues.
    """

    ruler_left_ratio: float = 0.19
    ruler_right_ratio: float = 0.92
    """Bande servant de règle de mesure, en fraction de la largeur de la zone.

    ⚠️ C'est la colonne du **texte**, pas celle des pastilles de canal. Les
    pastilles sont toutes identiques et espacées d'exactement un pas de ligne :
    un défilement d'une ligne superpose la pastille `n` sur la `n+1` et n'y
    change rien. Mesuré par le banc : 0 détection juste sur 37 avec les
    pastilles, 32 sur 37 avec le texte.

    En fraction et non en pixels, pour que la valeur par défaut tienne quelle
    que soit la largeur du chat. La gauche écarte la colonne des pastilles, la
    droite écarte le bord de la fenêtre. Le calibrage de la zone affinera.
    """

    row_height_px: float = 21.6
    """Pas vertical entre deux lignes.

    Mesuré à **21,6 px** en 2560 x 1440 par le banc d'essai, sur les décalages
    réellement observés : 22, 43, 65, 86 et 108 px pour une à cinq lignes,
    parfaitement linéaires. La valeur de 21 relevée à l'œil sur les pastilles
    était basse de 3 %. À recalibrer par résolution et par échelle d'interface.
    """

    bright_threshold: int = BRIGHT_THRESHOLD
    """Niveau au-dessus duquel un pixel est tenu pour du texte du journal.

    C'est ce masque qui fait disparaître le décor du jeu, visible à travers le
    fond transparent. Voir `tracking/scroll.py` pour la mesure.
    """

    max_scroll_lines: int = 8
    """Défilement maximal cherché entre deux captures, en lignes.

    Borne la recherche de décalage, qui coûte proportionnellement au nombre de
    positions essayées. Huit lignes en 100 ms, soit 80 par seconde, est très
    au-dessus de tout ce qu'un journal produit : mesuré 3 lignes par seconde en
    farm actif. Au-delà, la mesure se tait et l'alignement textuel reprend seul.
    """

    match: MatchConfig = field(default_factory=MatchConfig)
    """Tolérance de la comparaison de deux lignes, et part des paires qui
    doivent s'accorder pour qu'un recouvrement soit valide.

    Exposée ici plutôt que laissée implicite : c'est le réglage qui décide de
    ce qu'on accepte comme « la même ligne », donc celui qu'il faut pouvoir
    faire varier pour le mesurer au banc. Un réglage qu'on ne peut pas balayer
    est un réglage qu'on ne peut pas justifier.
    """

    min_sightings: int = 2
    """Observations concordantes avant de valider un drop.

    ⚠️ Ne pas augmenter « par prudence » : c'est contre-intuitif et c'est
    mesuré. Balayage du 05/08/2026 sur la rafale du banc, à quatre cadences de
    lecture, drops comptés sur 47 et écart sur la quantité cumulée :

    | seuil | OCR 0,7 s | OCR 1,1 s | OCR 1,5 s | OCR 2,2 s |
    | --- | --- | --- | --- | --- |
    | 1 | 44, −14,7 % | 47, −13,2 % | 47, −6,2 % | 44, −3,1 % |
    | **2** | **43, −5,4 %** | **47, +0,0 %** | **47, −0,8 %** | **43, −3,9 %** |
    | 3 | 43, −5,4 % | 46, −1,6 % | 43, −7,0 % | 35, −15,5 % |
    | 4 | 43, −5,4 % | 41, −9,3 % | 40, −10,1 % | 20, −57,4 % |

    Deux choses se lisent dans ce tableau, et elles vont en sens contraire.
    Attendre **une** observation de plus protège des ratés de lecture : à 1, tous
    les drops sont trouvés mais leurs quantités sont fausses de 13 %, faute de
    vote. Attendre **davantage** fait sortir la ligne de l'écran avant qu'elle
    n'atteigne le seuil, et c'est une perte sèche.

    2 est le meilleur des quatre valeurs à **chacune** des quatre cadences, ce
    qui en fait un choix mesuré et non un point de chance. Il a aussi le bon
    sens d'erreur : il sous-compte le silver là où 3 le sur-compte.
    """

    async_ocr: bool = False
    """Fait tourner la reconnaissance sur un fil à part, sans bloquer le fil qui
    mesure le défilement.

    ⛔ **Faux par défaut, et MESURÉ PIRE que le mode synchrone le 05/08/2026.**
    Ce n'est pas une prudence en attendant une mesure : la mesure a eu lieu,
    **deux fois**, en temps réel sur la vraie rafale de Thornwood Forest
    (`scripts/banc_essai.py --rafale _farmzone-20260805-171935 --async-ocr`,
    `bench/replay.py::replay_realtime`) :

    | | images vraiment lues | drops / référence | quantité / référence |
    | --- | --- | --- | --- |
    | synchrone (comme aujourd'hui) | 52 / 600 | 104 / 102 (+2,0 %) | 305 / 291 (+4,8 %) |
    | **asynchrone** | **32 / 600** | **93 / 102 (−8,8 %)** | **246 / 291 (−15,5 %)** |

    Contre-intuitif, et c'est justement pour ça qu'il fallait mesurer plutôt
    que de faire confiance au mécanisme : découpler LIT MOINS SOUVENT, pas
    plus. Deux hypothèses ont été essayées pour expliquer pourquoi, l'une
    réfutée, l'autre non encore confirmée :

    1. **Contention du GIL entre les deux fils, réfutée.** Un test isolé (le
       fil de fond fait tourner `estimate_text_scroll_px` toutes les 100 ms
       pendant qu'on chronomètre l'OCR sur l'autre) ne montre AUCUN
       ralentissement mesurable : ~500-600 ms avec ou sans le fil concurrent.
       Ce n'est donc pas ça.
    2. **`_should_read` gate la resoumission sur `pending_shift_px > 0`, retombé
       à zéro à chaque soumission.** Une seconde mesure, en supprimant tout
       `ocr_min_interval_s` (`--ocr-ms 1`), donne EXACTEMENT le même nombre
       d'images lues (32/600) — ce paramètre n'était donc pas non plus la
       cause. Reste l'hypothèse, non confirmée par une mesure isolée : quand
       rien n'a défilé pendant le temps qu'un travail met à revenir, la
       prochaine soumission attend `ocr_max_idle_s` (2 s) au lieu de repartir
       aussitôt, ce qui n'arrive presque jamais en mode synchrone puisque ses
       lectures s'enchaînent sans le moindre répit entre elles.

    **Le code reste, correct et testé** (`TestModeAsynchrone`, zéro régression
    sur le chemin synchrone, aucun événement inventé sur la vraie rafale). Ce
    qui manque n'est pas une preuve de sécurité, c'est une preuve de gain — et
    tant qu'elle n'existe pas, l'allumer par défaut inventerait une amélioration
    au lieu de la mesurer, ce que ce projet refuse pour la même raison qu'il
    refuse d'inventer un drop.
    """


def config_from_calibration(calibration: Calibration, base: LoopConfig | None = None) -> LoopConfig:
    """Applique un calibrage à un réglage de boucle.

    Trois valeurs sur quatre viennent de l'écran de la personne et non d'une
    constante : le pas de ligne, et la bande où mesurer le défilement. Les
    laisser codées en dur, comme elles l'étaient, rendait le produit
    inutilisable par quelqu'un d'autre **sans qu'aucune erreur ne le dise** : la
    zone tombait à côté, le journal ressortait vide, et le compteur affichait
    zéro drop comme s'il n'y avait rien eu à compter.

    La région, elle, ne vit pas ici : c'est un argument de `CaptureLoop`, parce
    qu'elle dit *où capturer* et non *comment interpréter*.
    """
    reglage = base or LoopConfig()
    return replace(
        reglage,
        row_height_px=calibration.row_height_px,
        ruler_left_ratio=calibration.ruler_left_ratio,
        ruler_right_ratio=calibration.ruler_right_ratio,
    )


@dataclass(slots=True)
class _OcrJob:
    """Une reconnaissance en cours sur le fil de fond, ou son résultat en
    attente d'être traité par le fil principal.

    Trois champs sont écrits UNIQUEMENT par `_run_ocr`, sur le fil de fond :
    `lines`, `error`, `done`. Les trois autres sont écrits UNE FOIS à la
    création, sur le fil principal, et ne bougent plus ensuite : c'est cette
    séparation qui rend l'objet sûr à partager entre les deux fils sans verrou.
    """

    started_at: float
    """`now` au moment où l'IMAGE a été capturée, pas au moment où son résultat
    sera traité. C'est cet écart entre deux images comparées, et non le temps
    que l'OCR a mis à répondre, qui borne le nombre de lignes plausibles."""

    pending_shift_px: float
    shift_trustworthy: bool

    done: threading.Event = field(default_factory=threading.Event)
    lines: list[str] | None = None
    error: BaseException | None = None


@dataclass(slots=True)
class TickResult:
    """Ce qui s'est passé pendant un tour de boucle."""

    ocr_ran: bool = False
    events: list[LootEvent] = field(default_factory=list)

    silver: int = 0
    """Silver des lignes NOUVELLES de ce tour, pas de la fenêtre entière.

    C'est bien un incrément, jamais un état : l'appelant l'additionne, donc y
    mettre le contenu de la fenêtre recompterait chaque gain autant de fois
    qu'il reste affiché.
    """

    pending_shift_px: float = 0.0
    expected_new: int | None = None
    skipped_reason: str = ""
    """Renseigné quand une image a été écartée. Une image écartée sans trace
    serait indiscernable d'une image sans butin."""


class CaptureLoop:
    """Assemble capture, défilement, reconnaissance et validation."""

    def __init__(
        self,
        source: FrameSource,
        reader: LineSource,
        matcher: ItemMatcher,
        region: Region,
        *,
        config: LoopConfig | None = None,
        fmt: ChatLineFormat = DEFAULT_FORMAT,
        scope: Scope | None = None,
        session_start_min: int | None = None,
    ) -> None:
        self.source = source
        self.reader = reader
        self.matcher = matcher
        self.region = region
        self.config = config or LoopConfig()
        self.fmt = fmt
        self.scope = scope
        self.session_start_min = session_start_min
        """Minute du jour où la session a commencé, ou None pour tout accepter.

        ⭐ Sert à refuser le journal DÉJÀ À L'ÉCRAN au démarrage. Le chat garde
        des dizaines de minutes de butin antérieur, et rien ne distingue « le
        journal défile parce qu'il tombe du butin » de « le vieux journal
        réapparaît ». Mesuré sur une vraie session : 39 minutes d'historique
        affiché, et des drops inventés en conséquence.

        None n'est pas un défaut : le banc d'essai rejoue des rafales dont on
        ne connaît pas l'heure de départ, et il doit continuer de mesurer la
        boucle et non ce filtre."""

        self.stager = LootStager(min_sightings=self.config.min_sightings)
        self.total_silver = 0

        self._previous_ruler: GrayImage | None = None
        self._previous_lines: list[ObservedLine] = []
        self._pending_shift_px = 0.0
        self._shift_trustworthy = True
        self._last_ocr_at: float | None = None
        self._consecutive_skips = 0
        self._seeded = False
        self._ocr_job: _OcrJob | None = None
        """Le travail de reconnaissance en cours, mode asynchrone seulement.
        `None` tout le temps en mode synchrone : rien de ce qui suit n'existe."""

    # -- boucle rapide ---------------------------------------------------

    def tick(self, now: float) -> TickResult:
        """Un tour de boucle. `now` est injecté pour que les tests ne dorment pas.

        Faire lire l'horloge à la boucle elle-même rendrait tout test de cadence
        dépendant du temps réel, donc lent et instable selon la charge machine.
        """
        image = self.source.grab(self.region)
        self._accumulate_scroll(image)

        if self.config.async_ocr:
            return self._tick_async(image, now)

        if not self._should_read(now):
            return TickResult(pending_shift_px=self._pending_shift_px)

        return self._read(image, now)

    def _accumulate_scroll(self, image: GrayImage) -> None:
        """Mesure le défilement sur la colonne des pastilles et l'accumule.

        Une mesure non sûre ne remet pas l'accumulation à zéro, elle la marque
        comme non fiable : le défilement a bien eu lieu, on ne sait juste plus
        de combien. Prétendre à zéro serait affirmer quelque chose de faux.
        """
        ruler = self._ruler(image)
        previous, self._previous_ruler = self._previous_ruler, ruler
        if previous is None:
            return

        scroll = estimate_text_scroll_px(
            previous, ruler, max_shift=self._max_shift_px, threshold=self.config.bright_threshold
        )
        if scroll.confident:
            self._pending_shift_px += scroll.shift_px
        else:
            self._shift_trustworthy = False

    @property
    def _max_shift_px(self) -> int:
        return max(1, round(self.config.max_scroll_lines * self.config.row_height_px))

    def _ruler(self, image: GrayImage) -> GrayImage:
        largeur = image.shape[1]
        gauche = max(0, min(largeur - 1, round(largeur * self.config.ruler_left_ratio)))
        droite = max(gauche + 1, min(largeur, round(largeur * self.config.ruler_right_ratio)))
        decoupe: GrayImage = image[:, gauche:droite]
        return decoupe

    def _should_read(self, now: float) -> bool:
        if self._last_ocr_at is None:
            return True
        depuis = now - self._last_ocr_at
        if depuis < self.config.ocr_min_interval_s:
            return False
        if self._pending_shift_px > 0:
            return True
        # Rien n'a défilé, mais une ligne peut être apparue sans défilement
        # tant que la fenêtre n'est pas pleine.
        return depuis >= self.config.ocr_max_idle_s

    # -- boucle lente ----------------------------------------------------

    def _read(self, image: GrayImage, now: float) -> TickResult:
        # Écart avec la lecture précédente, mesuré AVANT de le remplacer. C'est
        # lui, et non la cadence de capture, qui borne le nombre de lignes qui
        # ont pu apparaître entre les deux images comparées.
        depuis = now - self._last_ocr_at if self._last_ocr_at is not None else 0.0
        self._last_ocr_at = now
        # ⭐ Le vieux journal est retiré AVANT tout le reste, y compris avant
        # l'amorce. L'amorce seule ne suffit pas : mesuré sur une vraie session,
        # elle s'était faite sur une lecture partielle de 4 lignes pendant que
        # le chat réapparaissait, et les lectures suivantes n'avaient donc plus
        # aucun recouvrement avec elle. Les 23 lignes déjà à l'écran, vieilles
        # de 39 minutes, sont alors passées pour neuves.
        parsed = self._sans_le_vieux_journal(
            parse_frame(self.reader.read_text(image), self.matcher, fmt=self.fmt, scope=self.scope)
        )
        current = [ligne.observed for ligne in parsed]

        expected = self._expected_new(len(current), self._pending_shift_px, self._shift_trustworthy)
        self._pending_shift_px = 0.0
        self._shift_trustworthy = True

        return self._align_and_stage(current, expected, depuis)

    def _align_and_stage(
        self, current: list[ObservedLine], expected: int | None, elapsed_s: float
    ) -> TickResult:
        """La part commune aux deux modes : amorce, alignement, vote.

        Extraite pour que les modes synchrone et asynchrone passent
        **exactement** par le même chemin une fois l'OCR obtenu. Diverger ici
        entre les deux reviendrait à maintenir deux compteurs différents sous le
        même nom, ce que ce projet ne peut pas se permettre sur le chemin qui
        décide d'un drop.
        """
        if not self._seeded:
            # Le butin déjà à l'écran appartient au passé et ne doit pas être
            # compté. Sans cette amorce, lancer le suivi crediterait d'un coup
            # les vingt dernières lignes du journal.
            self.stager.seed(current)
            self._previous_lines = current
            self._seeded = True
            return TickResult(ocr_ran=True, expected_new=expected)

        result = align(self._previous_lines, current, cfg=self.config.match, expected_new=expected)

        motif = self._rejection_reason(result, expected, elapsed_s)
        if motif:
            self._consecutive_skips += 1
            return TickResult(ocr_ran=True, expected_new=expected, skipped_reason=motif)

        self._consecutive_skips = 0
        self._previous_lines = current
        evenements = self.stager.observe(result.overlap, current)

        # ⚠️ Le silver vient du VOTE de la couche de suivi, exactement comme les
        # objets, et non d'une lecture. Deux défauts mesurés par le banc d'essai
        # ont conduit ici, dans cet ordre :
        #
        # 1. il était additionné sur la fenêtre entière à chaque lecture, donc
        #    autant de fois qu'une ligne restait affichée : +32,5 % ;
        # 2. corrigé en ne comptant que les lignes nouvelles, il était alors lu
        #    **une seule fois**. Or le montant est un nombre à quatre chiffres,
        #    et 13,6 % des lectures de lignes de silver en ont un d'illisible.
        #
        # Le suivi ne rend donc un montant qu'une fois la ligne vue plusieurs
        # fois, et le tranche au vote pondéré sur toutes ses lectures.
        silver = self.stager.drain_silver()
        self.total_silver += silver
        return TickResult(ocr_ran=True, events=evenements, silver=silver, expected_new=expected)

    # -- mode asynchrone ---------------------------------------------------

    def _tick_async(self, image: GrayImage, now: float) -> TickResult:
        """Équivalent de `tick` quand `LoopConfig.async_ocr` est vrai.

        `_accumulate_scroll` a déjà tourné sur CETTE image dans `tick()`, avant
        qu'on sache s'il y a un travail en cours : c'est précisément ce qui
        manque au mode synchrone, où rien ne mesure le défilement tant que
        l'OCR n'a pas rendu la main.
        """
        if self._ocr_job is not None:
            return self._poll_ocr_job()

        if not self._should_read(now):
            return TickResult(pending_shift_px=self._pending_shift_px)

        # Le défilement accumulé JUSQU'ICI part avec le travail : ce qui
        # s'accumulera pendant que l'OCR tourne appartient à la PROCHAINE
        # lecture, pas à celle-ci, qui porte sur l'image capturée maintenant.
        job = _OcrJob(
            started_at=now,
            pending_shift_px=self._pending_shift_px,
            shift_trustworthy=self._shift_trustworthy,
        )
        self._pending_shift_px = 0.0
        self._shift_trustworthy = True
        self._ocr_job = job
        threading.Thread(
            target=self._run_ocr, args=(job, image), daemon=True, name="butin-ocr"
        ).start()
        return TickResult(ocr_ran=True, pending_shift_px=0.0)

    def _run_ocr(self, job: _OcrJob, image: GrayImage) -> None:
        """Tourne sur un fil à part. Ne touche à AUCUN état partagé de la boucle.

        Seuls `job.lines`/`job.error` sont écrits ici, et `job.done` les publie.
        L'alignement, le vote et `_previous_lines` restent entièrement sur le
        fil appelant de `tick()` : c'est cette séparation, et elle seule, qui
        rend le découplage sûr sans le moindre verrou sur `LootStager`.
        """
        try:
            job.lines = self.reader.read_text(image)
        except Exception as exc:  # repris et exposé sur le fil principal, voir _consume_ocr_job
            job.error = exc
        finally:
            job.done.set()

    def _poll_ocr_job(self) -> TickResult:
        job = self._ocr_job
        if job is None or not job.done.is_set():
            return TickResult(pending_shift_px=self._pending_shift_px)
        self._ocr_job = None
        return self._consume_ocr_job(job)

    def _consume_ocr_job(self, job: _OcrJob) -> TickResult:
        """Traite le résultat d'un travail terminé, sur le fil appelant.

        ⚠️ Si la reconnaissance a levé, l'exception est RELEVÉE ici, sur le fil
        de capture, exactement comme elle l'aurait fait en mode synchrone : un
        fil qui avale ses erreurs est le pire des cas (`capture/worker.py`), et
        le découplage ne doit pas devenir un moyen de les perdre en route.
        """
        if job.error is not None:
            raise job.error

        # Écart entre les deux IMAGES comparées, pas entre leurs traitements :
        # l'OCR peut avoir pris deux secondes, ça ne change rien au nombre de
        # lignes qui ont pu apparaître entre les deux captures.
        depuis = job.started_at - self._last_ocr_at if self._last_ocr_at is not None else 0.0
        self._last_ocr_at = job.started_at

        parsed = self._sans_le_vieux_journal(
            parse_frame(job.lines or [], self.matcher, fmt=self.fmt, scope=self.scope)
        )
        current = [ligne.observed for ligne in parsed]
        expected = self._expected_new(len(current), job.pending_shift_px, job.shift_trustworthy)
        return self._align_and_stage(current, expected, depuis)

    def _sans_le_vieux_journal(self, lignes: list[ParsedLine]) -> list[ParsedLine]:
        """Retire les lignes datées d'avant le début de la session.

        Le jeu horodate chaque ligne du journal. Une ligne de 16:40 pendant une
        session ouverte à 17:19 n'est pas un drop, c'est de l'historique
        affiché : aucune incertitude à trancher, le jeu le dit lui-même.

        ⚠️ Le filtrage se fait sur `ParsedLine` et non sur `ObservedLine`, parce
        que c'est la première qui porte l'heure. La seconde ne la connaît pas,
        et la lui ajouter mêlerait le format du client français à une couche qui
        en est aveugle.
        """
        if self.session_start_min is None:
            return lignes
        return [ligne for ligne in lignes if not is_stale(ligne.stamp, self.session_start_min)]

    def _expected_new(
        self, visible: int, pending_shift_px: float, shift_trustworthy: bool
    ) -> int | None:
        """Convertit un défilement accumulé en nombre de lignes attendues.

        None dès qu'il y a le moindre doute : l'alignement travaille alors sur
        le texte seul, ce qui reste correct. Une prédiction fausse serait pire
        que pas de prédiction, puisqu'elle écarterait le bon recouvrement.

        ⚠️ Prend le défilement en PARAMÈTRE et ne lit plus `self._pending_shift_px`
        directement. En mode asynchrone, la lecture qu'on traite peut dater de
        plusieurs tours : ce n'est pas le défilement accumulé maintenant qu'il
        faut convertir, c'est celui qui avait été accumulé au moment où l'image
        de CETTE lecture a été capturée, capturé dans le travail de fond avant
        qu'il ne reparte de zéro pour la lecture suivante.
        """
        if not shift_trustworthy or pending_shift_px <= 0:
            return None
        mesure = ScrollResult(
            shift_px=round(pending_shift_px), score=0.0, baseline_score=0.0, confident=True
        )
        return expected_new_lines(mesure, self.config.row_height_px, max(visible, 1))

    def _rejection_reason(
        self, result: AlignmentResult, expected: int | None, elapsed_s: float
    ) -> str:
        if is_glitch_frame(result, len(self._previous_lines), self._consecutive_skips):
            return "image aberrante : recouvrement perdu d'un coup"
        plafond = plausible_max_new(elapsed_s)
        if is_implausible_jump(result, self._consecutive_skips, expected, max_new=plafond):
            return (
                f"saut invraisemblable : {len(result.new_lines)} lignes annoncées "
                f"en {elapsed_s:.1f} s, plafond {plafond}"
            )
        return ""

    # -- fin de session --------------------------------------------------

    def flush(self) -> list[LootEvent]:
        """Valide les drops encore en attente, à l'arrêt de la session.

        Le silver en attente est crédité au passage. Sans ça, faire voter les
        montants ferait perdre toutes les lignes de pièces encore à l'écran au
        moment de l'arrêt, c'est-à-dire une fenêtre entière.

        ⚠️ En mode asynchrone, une reconnaissance encore en vol est ATTENDUE
        avant de fermer, bornée à `_FLUSH_OCR_TIMEOUT_S`. En mode synchrone,
        arrêter la session attend déjà la fin du tour en cours
        (`CaptureWorker.stop` rejoint le fil de capture) : ce n'est pas une
        raison de perdre cette garantie parce que le fil, lui, ne bloque plus.
        Sans cette attente, le tout dernier passage de l'OCR — potentiellement
        le seul témoin d'un drop qui vient de tomber — serait perdu en silence.
        """
        evenements = self._await_pending_ocr()
        evenements += self.stager.flush()
        self.total_silver += self.stager.drain_silver()
        return evenements

    def _await_pending_ocr(self) -> list[LootEvent]:
        job = self._ocr_job
        if job is None:
            return []
        self._ocr_job = None
        if not job.done.wait(_FLUSH_OCR_TIMEOUT_S):
            # Le même choix qu'à l'arrêt du fil de capture : au-delà d'un délai
            # raisonnable, mieux vaut perdre cette dernière lecture que bloquer
            # l'arrêt indéfiniment. Voir `CaptureWorker.stop`.
            _log.warning(
                "reconnaissance encore en cours après %.0f s à l'arrêt, dernière lecture perdue",
                _FLUSH_OCR_TIMEOUT_S,
            )
            return []
        if job.error is not None:
            # Ne PAS relever ici. `flush` est appelé depuis l'arrêt, sans le
            # filet d'exception qui entoure `tick()` dans le fil de capture : la
            # relever ferait planter le bouton Arrêter au pire moment possible.
            _log.warning("la dernière reconnaissance a échoué à l'arrêt : %s", job.error)
            return []
        return self._consume_ocr_job(job).events
