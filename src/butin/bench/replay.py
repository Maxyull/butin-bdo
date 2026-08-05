"""Rejeu de la vraie boucle de capture sur une rafale enregistrée.

Le point essentiel : **c'est `capture.loop.CaptureLoop` qui tourne ici**, pas
une imitation écrite pour le banc. Un banc qui réimplémenterait le compteur
mesurerait sa propre réimplémentation, et se tairait précisément sur les bogues
qui n'existent que dans le vrai chemin.

Seules deux choses sont remplacées, et ni l'une ni l'autre ne touche à la
logique :

* **la source d'images**, qui déroule la rafale au lieu d'interroger l'écran ;
* **le lecteur de texte**, qui rend la transcription au lieu de payer 336 ms
  d'OCR par image.

L'horloge est **fabriquée** à partir du pas de la rafale, jamais lue. La boucle
prend déjà `now` en paramètre pour cette raison : un banc dont le résultat
dépendrait de la charge de la machine ne serait pas reproductible, et un banc
non reproductible ne prouve rien.

Conséquence à garder en tête en lisant les chiffres : la boucle ne lit pas les
300 images. Elle respecte son propre `ocr_min_interval_s`, donc en lit environ
une sur quatre, exactement comme en jeu. La référence de `assembly.py`, elle,
les lit toutes. **Cet écart d'information est voulu** : il fait partie de ce
qu'on mesure, puisque c'est une des façons dont le compteur peut perdre du
butin.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from ..capture.lines import DEFAULT_FORMAT, ChatLineFormat
from ..capture.loop import CaptureLoop, LoopConfig
from ..capture.screen import GrayImage, Region
from ..catalog.matcher import ItemMatcher, Scope
from ..tracking.models import LootEvent
from .transcript import BenchFrame


class _RafaleSource:
    """Déroule les images de la rafale, dans l'ordre.

    Retient l'index de la dernière image rendue : c'est ce qui permet au
    lecteur de texte de savoir quelle transcription rendre, sans que la boucle
    n'ait à transporter la moindre information supplémentaire.
    """

    def __init__(self, frames: Sequence[BenchFrame]) -> None:
        self._frames = frames
        self.position = -1

    def grab(self, region: Region) -> GrayImage:
        self.position += 1
        return self._frames[self.position].image


class _RafaleReader:
    """Rend le texte déjà lu pour l'image en cours."""

    def __init__(self, frames: Sequence[BenchFrame], source: _RafaleSource) -> None:
        self._frames = frames
        self._source = source
        self.read_indices: list[int] = []

    def read_text(self, image: GrayImage) -> list[str]:
        index = self._source.position
        self.read_indices.append(index)
        return list(self._frames[index].lines)


@dataclass(frozen=True, slots=True)
class Replay:
    """Ce que le compteur a produit sur la rafale."""

    events: tuple[LootEvent, ...]
    silver: int
    silver_lines: int

    read_frames: tuple[int, ...]
    """Images que la boucle a vraiment fait lire. Sa cadence réelle, mesurée
    plutôt que supposée."""

    skipped: tuple[tuple[int, str], ...]
    """Images écartées par un garde-fou, avec le motif. Une image écartée est
    du butin potentiellement perdu : le banc doit la voir passer."""

    lost_resolved: int
    """Lignes reconnues comme du butin connu, sorties de l'écran sans avoir été
    validées. **Perte sèche, mesurée sans aucune référence extérieure** : le
    compteur sait lui-même qu'il est passé à côté."""

    dropped_unconfirmed: int
    unresolved_finalized: int
    """Lignes de gain restées inconnues du catalogue. Ni perdues ni comptées :
    c'est un défaut de couverture du catalogue, pas du compteur."""

    @property
    def read_ratio(self) -> float:
        return len(self.read_frames) / max(1, len(self.read_frames) + len(self.skipped))


def replay(
    frames: Sequence[BenchFrame],
    matcher: ItemMatcher,
    *,
    config: LoopConfig | None = None,
    fmt: ChatLineFormat = DEFAULT_FORMAT,
    scope: Scope | None = None,
    interval_s: float = 0.10,
) -> Replay:
    """Fait tourner la boucle sur la rafale et rend ce qu'elle a compté.

    `interval_s` est le pas réel entre deux images de la rafale, qui n'est pas
    forcément celui de `LoopConfig.capture_interval_s` : on peut vouloir mesurer
    ce que donne une rafale prise à 200 ms sur une boucle réglée pour 100. Les
    confondre ferait croire la boucle deux fois plus rapide qu'elle ne l'est.
    """
    if not frames:
        raise ValueError("rafale vide : rien à rejouer")

    reglage = config or LoopConfig()
    hauteur, largeur = frames[0].image.shape[:2]
    region = Region(left=0, top=0, width=int(largeur), height=int(hauteur))

    source = _RafaleSource(frames)
    reader = _RafaleReader(frames, source)
    boucle = CaptureLoop(source, reader, matcher, region, config=reglage, fmt=fmt, scope=scope)

    evenements: list[LootEvent] = []
    ecartees: list[tuple[int, str]] = []
    for index in range(len(frames)):
        resultat = boucle.tick(index * interval_s)
        evenements.extend(resultat.events)
        if resultat.skipped_reason:
            ecartees.append((index, resultat.skipped_reason))

    # La fin de rafale est une fin de session : ce qui attendait encore une
    # confirmation doit être validé, sinon le banc compterait comme une perte
    # du compteur ce qui n'est qu'un arrêt de l'enregistrement.
    evenements.extend(boucle.flush())

    return Replay(
        events=tuple(evenements),
        silver=boucle.total_silver,
        silver_lines=boucle.stager.silver_lines,
        read_frames=tuple(reader.read_indices),
        skipped=tuple(ecartees),
        lost_resolved=boucle.stager.lost_resolved,
        dropped_unconfirmed=boucle.stager.dropped_unconfirmed,
        unresolved_finalized=boucle.stager.unresolved_finalized,
    )


class _RealReader(Protocol):
    """Un lecteur qui coûte du VRAI temps, contrairement à `_RafaleReader`."""

    def read_text(self, image: GrayImage) -> list[str]: ...


class _RealtimeReader:
    """Enveloppe un lecteur réel pour lui faire lire l'image courante de la
    rafale, et pour se souvenir de quelles images ont vraiment été lues."""

    def __init__(self, source: _RafaleSource, reader: _RealReader) -> None:
        self._source = source
        self._reader = reader
        self.read_indices: list[int] = []

    def read_text(self, image: GrayImage) -> list[str]:
        self.read_indices.append(self._source.position)
        return self._reader.read_text(image)


def replay_realtime(
    frames: Sequence[BenchFrame],
    matcher: ItemMatcher,
    reader: _RealReader,
    *,
    config: LoopConfig | None = None,
    fmt: ChatLineFormat = DEFAULT_FORMAT,
    scope: Scope | None = None,
    interval_s: float = 0.10,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Replay:
    """Comme `replay`, mais paie le coût RÉEL de la reconnaissance au lieu de
    rejouer une transcription instantanée.

    Indispensable pour mesurer `LoopConfig.async_ocr` : un fil de fond n'a
    quelque chose à découpler QUE s'il coûte du temps réel pendant qu'il
    travaille. `replay()` avance un horodatage simulé sans jamais dormir en
    vrai ; un fil de fond y termine en un instant quelle que soit la valeur
    simulée qu'on lui passe, et les deux horloges divergeraient sans que la
    mesure dise rien du monde réel.

    ⚠️ **Coûte donc réellement `len(frames) * interval_s` secondes d'horloge
    murale**, comme la vraie capture. Sur 600 images à 100 ms, une minute — et
    davantage en mode synchrone, puisque chaque reconnaissance retarde d'autant
    la suite : c'est précisément la différence qu'on cherche à mesurer.

    `reader` est donné, pas construit ici : c'est un `TextReader` déjà
    préchauffé (`warmup()`), pour que la toute première image ne paie pas seule
    le coût de l'allocation des arènes mémoire d'onnxruntime.

    Le rythme est celui d'un vrai fil de capture (`CaptureWorker._tourner`) :
    la cible du tour `i` est `i * interval_s` après le départ, on ne dort que
    s'il reste du temps avant elle, et `now` est l'écart RÉEL au départ, pas la
    cible elle-même. En mode synchrone, une reconnaissance qui déborde du tour
    ne se rattrape pas : le tour suivant part immédiatement, sans dormir,
    exactement ce que fait la boucle en jeu.
    """
    if not frames:
        raise ValueError("rafale vide : rien à rejouer")

    reglage = config or LoopConfig()
    hauteur, largeur = frames[0].image.shape[:2]
    region = Region(left=0, top=0, width=int(largeur), height=int(hauteur))

    source = _RafaleSource(frames)
    lecteur = _RealtimeReader(source, reader)
    boucle = CaptureLoop(source, lecteur, matcher, region, config=reglage, fmt=fmt, scope=scope)

    evenements: list[LootEvent] = []
    ecartees: list[tuple[int, str]] = []
    depart = clock()
    for index in range(len(frames)):
        cible = depart + index * interval_s
        reste = cible - clock()
        if reste > 0:
            sleep(reste)
        resultat = boucle.tick(clock() - depart)
        evenements.extend(resultat.events)
        if resultat.skipped_reason:
            ecartees.append((index, resultat.skipped_reason))

    # Comme `replay` : la fin de rafale est une fin de session, ce qui
    # attendait encore une confirmation doit être validé. En mode asynchrone,
    # `flush()` attend au passage le dernier travail encore en vol.
    evenements.extend(boucle.flush())

    return Replay(
        events=tuple(evenements),
        silver=boucle.total_silver,
        silver_lines=boucle.stager.silver_lines,
        read_frames=tuple(lecteur.read_indices),
        skipped=tuple(ecartees),
        lost_resolved=boucle.stager.lost_resolved,
        dropped_unconfirmed=boucle.stager.dropped_unconfirmed,
        unresolved_finalized=boucle.stager.unresolved_finalized,
    )
