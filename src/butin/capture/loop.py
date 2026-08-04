"""Boucle de capture, avec l'OCR découplé du reste.

Pourquoi découpler
------------------

Mesuré : la reconnaissance de texte coûte **336 ms par image**, alors que la
capture et la mesure de défilement en coûtent moins de dix à elles deux. Faire
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

La règle de mesure : les pastilles de canal
-------------------------------------------

Le fond du journal est **transparent sur le monde du jeu**. Mesurer le
défilement sur la zone entière reviendrait donc à mesurer surtout le décor qui
bouge, pas le texte qui défile.

Les pastilles de canal (`Système`, `Général`) sont la solution : elles sont
**opaques**, contrastées, et elles défilent exactement avec les lignes. Mesuré
sur de vraies captures, entre deux images :

| Zone mesurée | Écart entre deux images | Contraste interne |
| --- | --- | --- |
| chat entier | 11,3 | 35,2 |
| colonne des pastilles | **3,9** | 37,5 |

Trois fois moins de bruit pour un contraste équivalent. C'est cette colonne, et
elle seule, qui sert de règle.

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
from ..tracking.alignment import AlignmentResult, align, is_glitch_frame, is_implausible_jump
from ..tracking.models import LootEvent, ObservedLine
from ..tracking.scroll import ScrollResult, estimate_scroll_px, expected_new_lines
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

    ruler_left: int = 0
    ruler_width: int = 90
    """Colonne servant de règle de mesure, en pixels depuis le bord gauche de la
    zone capturée. Doit couvrir les pastilles de canal et rien d'autre : y
    inclure du texte transparent réintroduirait le bruit du décor."""

    row_height_px: float = 21.0
    """Pas vertical entre deux lignes. Mesuré à 21 px en 2560 x 1440, à
    recalibrer par résolution et par échelle d'interface."""

    min_sightings: int = 3
    """Observations concordantes avant de valider un drop. Ne pas augmenter
    « par prudence » : mesuré, ça fait perdre du butin."""


@dataclass(slots=True)
class TickResult:
    """Ce qui s'est passé pendant un tour de boucle."""

    ocr_ran: bool = False
    events: list[LootEvent] = field(default_factory=list)
    silver: int = 0
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

        scroll = estimate_scroll_px(previous, ruler)
        if scroll.confident:
            self._pending_shift_px += scroll.shift_px
        else:
            self._shift_trustworthy = False

    def _ruler(self, image: GrayImage) -> GrayImage:
        gauche = self.config.ruler_left
        droite = gauche + self.config.ruler_width
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
        self._last_ocr_at = now
        parsed = parse_frame(
            self.reader.read_text(image), self.matcher, fmt=self.fmt, scope=self.scope
        )
        current = [ligne.observed for ligne in parsed]
        silver = sum(ligne.silver for ligne in parsed)

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

        motif = self._rejection_reason(result, expected)
        if motif:
            self._consecutive_skips += 1
            return TickResult(ocr_ran=True, expected_new=expected, skipped_reason=motif)

        self._consecutive_skips = 0
        self._previous_lines = current
        evenements = self.stager.observe(result.overlap, current)
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

    def _rejection_reason(self, result: AlignmentResult, expected: int | None) -> str:
        if is_glitch_frame(result, len(self._previous_lines), self._consecutive_skips):
            return "image aberrante : recouvrement perdu d'un coup"
        if is_implausible_jump(result, self._consecutive_skips, expected):
            return f"saut invraisemblable : {len(result.new_lines)} lignes annoncées"
        return ""

    # -- fin de session --------------------------------------------------

    def flush(self) -> list[LootEvent]:
        """Valide les drops encore en attente, à l'arrêt de la session."""
        return self.stager.flush()
