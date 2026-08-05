"""Types de la couche de suivi.

Une `ObservedLine` est une ligne du journal d'acquisition telle qu'elle a été
lue sur UNE image. Ce n'est pas encore un drop : le journal affiche une
quinzaine de lignes en permanence, et la même ligne est relue à chaque capture
tant qu'elle n'a pas défilé. Transformer ces observations répétées en une liste
de drops sans doublon est tout le travail de ce paquet.

Une ligne non résolue (`item is None`) est conservée au lieu d'être jetée. Elle
ne deviendra jamais un drop, mais elle occupe une place à l'écran, et
l'alignement de deux images repose sur la position des lignes. Jeter les lignes
illisibles décalerait tout ce qui suit et ferait recompter des drops déjà
comptés.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..catalog.models import Item


@dataclass(frozen=True, slots=True)
class ObservedLine:
    """Une ligne du journal telle que lue sur une seule image."""

    raw: str
    """Texte brut renvoyé par l'OCR, conservé pour le diagnostic et pour
    comparer les lignes que la reconnaissance n'a pas résolues."""

    item: Item | None = None
    """Objet reconnu, ou None si la ligne n'a pas pu être résolue."""

    qty: int = 1
    """Quantité lue. Vaut 1 quand aucune quantité n'est écrite, ce qui est le
    cas normal d'un drop unitaire."""

    name_confidence: float = 0.0
    """Confiance de la reconnaissance du nom, de 0 à 1."""

    quantity_uncertain: bool = False
    """Vrai quand un marqueur de quantité était présent mais illisible.

    Distinct d'une absence de quantité. « x3 » lu comme « xB » n'est pas la
    même chose que pas de « x » du tout : le premier cas doit peser moins lourd
    au moment du vote, le second est un drop unitaire parfaitement normal.
    """

    silver: bool = False
    """Vrai quand la ligne annonce du silver, `qty` portant alors le montant.

    Indispensable pour distinguer deux cas que `item is None` confond : une
    ligne de silver, qui est un gain parfaitement connu, et une ligne dont
    l'objet n'a pas été reconnu, qui ne deviendra jamais un drop. Sans cette
    distinction, la couche de suivi ne peut pas faire voter les montants comme
    elle fait voter les quantités.
    """

    @property
    def item_id(self) -> int | None:
        return self.item.item_id if self.item is not None else None

    @property
    def resolved(self) -> bool:
        return self.item is not None


@dataclass(frozen=True, slots=True)
class LootEvent:
    """Un drop confirmé, prêt à être compté.

    Produit seulement après qu'une ligne a été vue sur plusieurs images
    consécutives et que ses lectures ont été départagées au vote.
    """

    item: Item
    qty: int
    confidence: float
    sightings: int
    """Nombre d'observations ayant alimenté la décision. Une valeur basse
    signale un drop confirmé de justesse, utile pour le diagnostic."""
