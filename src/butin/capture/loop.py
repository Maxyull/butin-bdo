"""Boucle de capture, avec l'OCR découplé du reste.

Pourquoi découpler
------------------

Mesuré : la reconnaissance de texte coûte **336 ms par image** sur une zone de
520 x 385, et **1 100 ms** sur une zone de 780 x 575 (banc du 05/08/2026), alors
que la capture et la mesure de défilement en coûtent moins de dix à elles deux.
Le coût suit la surface, donc `ocr_min_interval_s` ci-dessous promet une cadence
que la machine ne tient pas dès que la zone du chat est grande. Faire
tourner toute la chaîne au rythme de l'OCR reviendrait à mesurer le défilement
trois fois moins souvent que nécessaire, pour rien.

La boucle tourne donc à deux vitesses :

* **toutes les 100 ms** : capture, mesure du défilement, accumulation ;
* **quand il y a quelque chose à lire** : reconnaissance de texte, alignement,
  validation.

Le défilement accumulé entre deux passages d'OCR est exactement ce que
`tracking/alignment.py` attend comme `expected_new`. Le découplage n'est donc
pas seulement moins coûteux, il rend la prédiction **plus fine** : un défilement
rapide qui aurait été vu d'un bloc à 350 ms est vu en trois mesures à 100 ms.

⛔ La règle de mesure retenue ici ne fonctionne pas
---------------------------------------------------

📕 `docs/banc-essai.md`, partie 4 B. Le banc l'a mesuré le 05/08/2026 sur 300
images de vrai farm : **zéro détection de défilement sûre sur 299 transitions**,
et la colonne des pastilles est la **pire** des quatre bandes testées, avec 0
décalage juste sur 20 alors que 92 lignes sont réellement passées.

La raison est structurelle : les pastilles `Système` sont toutes identiques et
espacées de 21 px. Un défilement d'exactement une ligne superpose la pastille
`n` sur la pastille `n+1`, donc ne change rien. C'est précisément la colonne qui
ne peut pas voir ce qu'on lui demande de voir.

Le chiffre de 3,9 contre 11,3 qui l'avait fait retenir comparait deux captures
de scènes **différentes** : il mesurait le bruit du décor, pas un défilement.

Conséquence, et elle est lourde : `expected_new` vaut toujours `None`,
l'alignement travaille sur le texte seul, et surtout `_should_read` retombe en
permanence sur son minuteur de repli. La boucle ne lit alors que **15 images sur
300**, là où le seul coût de l'OCR en autoriserait 27.

Le code est laissé tel quel, sans réglage bricolé : trouver où mesurer le
défilement est le même problème que le calibrage de la zone, et les deux se
tranchent ensemble.

⚠️ Le garde-fou de stabilité n'est PAS utilisé pour conditionner l'OCR, et c'est
délibéré. Il a été écrit pour un fond fixe, où l'immobilité signifie que
l'animation d'apparition est terminée. Avec un fond transparent sur un monde qui
bouge en permanence, il ne se déclencherait jamais, ou tout le temps selon le
seuil, sans jamais rien dire du texte. La vraie défense contre une lecture prise
en pleine animation reste le **vote sur plusieurs images** de `staging.py`, qui
n'a pas ce défaut.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
from ..tracking.staging import LootStager
from .lines import DEFAULT_FORMAT, ChatLineFormat, parse_frame
from .screen import GrayImage, Region


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

    min_sightings: int = 3
    """Observations concordantes avant de valider un drop. Ne pas augmenter
    « par prudence » : mesuré, ça fait perdre du butin."""


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
    ) -> None:
        self.source = source
        self.reader = reader
        self.matcher = matcher
        self.region = region
        self.config = config or LoopConfig()
        self.fmt = fmt
        self.scope = scope

        self.stager = LootStager(min_sightings=self.config.min_sightings)
        self.total_silver = 0

        self._previous_ruler: GrayImage | None = None
        self._previous_lines: list[ObservedLine] = []
        self._pending_shift_px = 0.0
        self._shift_trustworthy = True
        self._last_ocr_at: float | None = None
        self._consecutive_skips = 0
        self._seeded = False

    # -- boucle rapide ---------------------------------------------------

    def tick(self, now: float) -> TickResult:
        """Un tour de boucle. `now` est injecté pour que les tests ne dorment pas.

        Faire lire l'horloge à la boucle elle-même rendrait tout test de cadence
        dépendant du temps réel, donc lent et instable selon la charge machine.
        """
        image = self.source.grab(self.region)
        self._accumulate_scroll(image)

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
        parsed = parse_frame(
            self.reader.read_text(image), self.matcher, fmt=self.fmt, scope=self.scope
        )
        current = [ligne.observed for ligne in parsed]

        expected = self._expected_new(len(current))
        self._pending_shift_px = 0.0
        self._shift_trustworthy = True

        if not self._seeded:
            # Le butin déjà à l'écran appartient au passé et ne doit pas être
            # compté. Sans cette amorce, lancer le suivi crediterait d'un coup
            # les vingt dernières lignes du journal.
            self.stager.seed(current)
            self._previous_lines = current
            self._seeded = True
            return TickResult(ocr_ran=True, expected_new=expected)

        result = align(self._previous_lines, current, expected_new=expected)

        motif = self._rejection_reason(result, expected, depuis)
        if motif:
            self._consecutive_skips += 1
            return TickResult(ocr_ran=True, expected_new=expected, skipped_reason=motif)

        self._consecutive_skips = 0
        self._previous_lines = current
        evenements = self.stager.observe(result.overlap, current)

        # ⚠️ Sur les lignes NOUVELLES seulement, jamais sur la fenêtre entière.
        # Une ligne de silver reste affichée une dizaine de secondes et se
        # retrouve donc dans toutes les lectures de cet intervalle : la
        # réadditionner à chaque fois compte le même gain autant de fois qu'il
        # a été vu. Mesuré par le banc le 05/08/2026, avec seulement 6 lectures
        # exploitées sur 300 images : 123 409 silver comptés pour 93 161 réels,
        # soit +32,5 %. À cadence normale l'erreur serait bien plus grosse.
        #
        # Le découpage `result.overlap:` est exactement celui qui définit
        # `result.new_lines`, donc le silver suit la même règle que les objets
        # et ne peut pas s'en désynchroniser.
        silver = sum(ligne.silver for ligne in parsed[result.overlap :])
        self.total_silver += silver
        return TickResult(ocr_ran=True, events=evenements, silver=silver, expected_new=expected)

    def _expected_new(self, visible: int) -> int | None:
        """Convertit le défilement accumulé en nombre de lignes attendues.

        None dès qu'il y a le moindre doute : l'alignement travaille alors sur
        le texte seul, ce qui reste correct. Une prédiction fausse serait pire
        que pas de prédiction, puisqu'elle écarterait le bon recouvrement.
        """
        if not self._shift_trustworthy or self._pending_shift_px <= 0:
            return None
        mesure = ScrollResult(
            shift_px=round(self._pending_shift_px),
            score=0.0,
            baseline_score=0.0,
            confident=True,
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
        """Valide les drops encore en attente, à l'arrêt de la session."""
        return self.stager.flush()
