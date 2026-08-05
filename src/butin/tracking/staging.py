"""Validation d'un drop après accord de plusieurs images.

Observation vue une fois, puis en attente, puis drop confirmé. Une ligne n'est
jamais comptée à sa première apparition.

**Pourquoi attendre.** Le journal affiche une quinzaine de lignes et la capture
tourne une dizaine de fois par seconde. Une vraie ligne est donc relue des
dizaines de fois avant de défiler hors de l'écran. Attendre deux lectures
concordantes coûte un dixième de seconde de latence et rend le total insensible
aux ratés ponctuels de l'OCR. C'est un échange très favorable.

**Le modèle.** Chaque ligne physique du journal est un emplacement qui
accumule ses observations en remontant à l'écran. Un emplacement est validé une
fois et une seule, après `min_sightings` observations, et son objet comme sa
quantité sont tranchés au vote sur toutes les observations récoltées.

Dérivé de `core/staging.py` de janhnguyen/BDO-Loot-Tracker (MIT). Deux
différences : le vote porte sur des identifiants d'objet et non sur des noms,
et les lectures dont la quantité était douteuse pèsent moins au vote.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from ..catalog.models import Item
from .models import LootEvent, ObservedLine

# Poids d'une observation dont le marqueur de quantité était présent mais
# illisible. Elle compte encore, parce qu'elle atteste la présence de la ligne,
# mais elle ne doit pas peser autant qu'une lecture nette au moment de choisir
# la quantité finale.
UNCERTAIN_WEIGHT = 0.4


@dataclass(slots=True)
class Slot:
    """Une ligne physique du journal, suivie image après image."""

    sightings: list[ObservedLine] = field(default_factory=list)
    committed: bool = False

    @property
    def count(self) -> int:
        return len(self.sightings)

    def add(self, line: ObservedLine) -> None:
        self.sightings.append(line)

    @property
    def resolved(self) -> bool:
        """Vrai si au moins une observation a été résolue à un objet connu."""
        return any(s.resolved for s in self.sightings)

    @property
    def is_silver(self) -> bool:
        """Vrai si cette ligne annonce du silver plutôt qu'un objet."""
        return any(s.silver for s in self.sightings)

    def vote_silver(self) -> int:
        """Montant tranché au vote sur toutes les lectures de la ligne.

        ⚠️ C'est le correctif, et il tient à ce que le montant est un **nombre
        à quatre chiffres**, donc bien plus fragile à l'OCR qu'un nom d'objet
        que la reconnaissance floue rattrape. Mesuré par le banc d'essai le
        05/08/2026 sur 300 images de vrai farm : **13,6 % des lectures de
        lignes de silver ont un montant illisible**, contre 4 lignes sur 45
        dans une référence qui tranche chaque position au vote.

        Le montant était jusque-là lu **une seule fois**, à la première
        apparition de la ligne, alors que les objets bénéficiaient déjà du
        vote. Une lecture ratée coûtait donc environ deux mille silver, sans
        aucun rattrapage possible.

        Le vote est le même que pour les quantités d'objets, pondération des
        lectures douteuses comprise : une lecture dont le marqueur était
        illisible atteste la présence de la ligne mais ne doit pas peser autant
        qu'une lecture nette au moment de choisir le montant.
        """
        return _vote_quantity([s for s in self.sightings if s.silver])

    def best_raw(self) -> str:
        """Texte brut le plus représentatif, pour le diagnostic.

        Privilégie l'observation résolue la plus sûre. À défaut, la première.
        """
        if not self.sightings:
            return ""
        named = [s for s in self.sightings if s.resolved]
        pool = named or self.sightings
        return max(pool, key=lambda s: s.name_confidence).raw

    def vote(self) -> LootEvent | None:
        """Tranche les observations en un drop confirmé.

        Renvoie None si aucune observation n'a jamais été résolue : la ligne
        existait bien à l'écran, mais on n'a jamais su de quel objet il
        s'agissait. Compter un drop inconnu serait pire que ne rien compter.
        """
        named = [s for s in self.sightings if s.item is not None]
        if not named:
            return None

        item = _majority_item(named)
        relevant = [s for s in named if s.item_id == item.item_id]
        qty = _vote_quantity(relevant)
        confidence = sum(s.name_confidence for s in relevant) / len(relevant)

        return LootEvent(
            item=item,
            qty=qty,
            confidence=confidence,
            sightings=len(self.sightings),
        )


def _majority_item(sightings: list[ObservedLine]) -> Item:
    """Objet le plus souvent lu. Départage par confiance cumulée.

    L'appelant garantit qu'au moins une observation est résolue.
    """
    counts: Counter[int] = Counter()
    by_id: dict[int, Item] = {}
    for sighting in sightings:
        if sighting.item is None:
            continue
        counts[sighting.item.item_id] += 1
        by_id[sighting.item.item_id] = sighting.item

    top = counts.most_common(1)[0][1]
    tied = [item_id for item_id, count in counts.items() if count == top]
    if len(tied) == 1:
        return by_id[tied[0]]

    # À égalité de voix, la somme des confiances départage : deux lectures
    # incertaines ne valent pas deux lectures nettes. À confiance égale aussi,
    # le plus petit identifiant, pour rester reproductible d'une exécution à
    # l'autre.
    best = max(
        tied,
        key=lambda item_id: (
            sum(s.name_confidence for s in sightings if s.item_id == item_id),
            -item_id,
        ),
    )
    return by_id[best]


def _vote_quantity(sightings: list[ObservedLine]) -> int:
    """Quantité retenue, par vote pondéré.

    Le départage évite volontairement de préférer la plus grande valeur. Sous
    un bruit de lecture symétrique (6 lu 8 aussi souvent que 8 lu 6), préférer
    systématiquement la plus grande gonflerait les totaux de façon régulière,
    ce qui est exactement l'erreur qu'un tracker ne doit pas commettre.
    """
    weights: dict[int, float] = {}
    for sighting in sightings:
        weight = UNCERTAIN_WEIGHT if sighting.quantity_uncertain else 1.0
        weights[sighting.qty] = weights.get(sighting.qty, 0.0) + weight

    best_weight = max(weights.values())
    tied = [qty for qty, weight in weights.items() if weight == best_weight]
    if len(tied) == 1:
        return tied[0]

    # Égalité parfaite : on retient la valeur la plus proche de la moyenne des
    # lectures, puis la plus petite. Neutre, et reproductible.
    mean_qty = sum(s.qty for s in sightings) / len(sightings)
    return min(tied, key=lambda qty: (abs(qty - mean_qty), qty))


class LootStager:
    """Transforme des captures alignées en drops confirmés."""

    def __init__(self, min_sightings: int = 2) -> None:
        self._min_sightings = max(1, min_sightings)
        self._slots: list[Slot] = []
        self._dropped_unconfirmed = 0
        self._lost_resolved = 0
        self._lost_silver = 0
        self._unresolved_finalized = 0
        self._silver_ready = 0
        self._silver_lines = 0
        self._dropped_records: list[tuple[str, bool]] = []

    # -- état ------------------------------------------------------------

    @property
    def pending_count(self) -> int:
        return sum(1 for s in self._slots if not s.committed)

    @property
    def dropped_unconfirmed(self) -> int:
        """Emplacements sortis de l'écran avant d'avoir été validés."""
        return self._dropped_unconfirmed

    @property
    def lost_resolved(self) -> int:
        """Parmi eux, ceux qui avaient pourtant été résolus à un objet connu.

        C'est le compteur qui mesure ce que le tracker a raté. Une valeur non
        nulle veut dire que du vrai butin n'a pas été compté, typiquement parce
        que la capture est trop lente pour le rythme du journal.
        """
        return self._lost_resolved

    @property
    def lost_silver(self) -> int:
        """Montant des lignes de silver sorties de l'écran sans validation.

        Compté à part de `lost_resolved`, qui ne parle que d'objets. C'est le
        prix payé pour faire voter les montants : une ligne de silver doit
        maintenant être vue plusieurs fois avant d'être créditée, alors qu'elle
        l'était dès sa première apparition. Sans ce compteur, l'échange serait
        invérifiable.
        """
        return self._lost_silver

    @property
    def silver_lines(self) -> int:
        """Nombre de LIGNES de silver validées, distinct du montant cumulé.

        C'est ce nombre que le banc d'essai compare aux empreintes de montants,
        qui les comptent sans jamais recaler quoi que ce soit. Sans lui, un
        écart sur le total ne dit pas s'il vient de lignes manquées ou de
        montants mal lus, et les deux ne se corrigent pas au même endroit.
        """
        return self._silver_lines

    @property
    def unresolved_finalized(self) -> int:
        """Emplacements confirmés comme persistants, mais jamais reconnus."""
        return self._unresolved_finalized

    def drain_silver(self) -> int:
        """Rend et remet à zéro le silver validé depuis le dernier appel.

        Un incrément, jamais un cumul : l'appelant l'additionne à son total.
        Même forme que `drain_dropped`, pour la même raison.
        """
        montant, self._silver_ready = self._silver_ready, 0
        return montant

    def reset(self) -> None:
        self._slots = []
        self._dropped_unconfirmed = 0
        self._lost_resolved = 0
        self._lost_silver = 0
        self._unresolved_finalized = 0
        self._silver_ready = 0
        self._silver_lines = 0
        self._dropped_records = []

    def seed(self, lines: list[ObservedLine]) -> None:
        """Établit la ligne de base au démarrage.

        Marque tout ce qui est déjà à l'écran comme validé, donc jamais compté.
        Sans cela, lancer le suivi au milieu d'une session compterait d'un coup
        les quinze dernières lignes du journal, qui appartiennent au passé.
        """
        self._slots = [Slot(sightings=[line], committed=True) for line in lines]

    def drain_dropped(self) -> list[tuple[str, bool]]:
        """Rend et vide les traces des emplacements sortis sans validation.

        Chaque entrée est (texte brut, était résolu). Permet à l'appelant de
        journaliser ce qui n'est jamais devenu un drop.
        """
        records, self._dropped_records = self._dropped_records, []
        return records

    # -- cycle de vie ----------------------------------------------------

    def observe(self, overlap: int, current_lines: list[ObservedLine]) -> list[LootEvent]:
        """Réconcilie les emplacements avec la capture courante.

        Renvoie les drops qui franchissent le seuil de validation sur CETTE
        image, jamais ceux déjà rendus auparavant.
        """
        carried_count = min(overlap, len(self._slots), len(current_lines))
        scrolled_off = len(self._slots) - carried_count

        for slot in self._slots[:scrolled_off]:
            if slot.committed:
                continue
            self._dropped_unconfirmed += 1
            was_resolved = slot.resolved
            if was_resolved:
                self._lost_resolved += 1
            elif slot.is_silver:
                self._lost_silver += slot.vote_silver()
            self._dropped_records.append((slot.best_raw(), was_resolved))

        carried = self._slots[scrolled_off:]
        # strict=True : les deux séquences font exactement carried_count entrées
        # par construction. Une troncature silencieuse ici ferait perdre des
        # observations sans le moindre signe, donc un drop validé sur moins de
        # preuves que prévu.
        for slot, line in zip(carried, current_lines[:carried_count], strict=True):
            slot.add(line)

        self._slots = carried + [Slot(sightings=[line]) for line in current_lines[carried_count:]]

        return self._commit_ready()

    def flush(self) -> list[LootEvent]:
        """Valide tout ce qui est encore en attente.

        Appelé à l'arrêt d'une session, pour ne pas perdre les derniers drops
        qui n'ont pas eu le temps d'être vus deux fois. Chaque emplacement ne
        peut toujours être validé qu'une seule fois.
        """
        events: list[LootEvent] = []
        for slot in self._slots:
            if slot.committed:
                continue
            slot.committed = True
            self._valider(slot, events, compter_inconnu=False)
        return events

    def _commit_ready(self) -> list[LootEvent]:
        events: list[LootEvent] = []
        for slot in self._slots:
            if slot.committed or slot.count < self._min_sightings:
                continue
            # Marqué validé quoi qu'il arrive : un emplacement jamais reconnu
            # ne doit pas être réexaminé à chaque image jusqu'à sa sortie.
            slot.committed = True
            self._valider(slot, events, compter_inconnu=True)
        return events

    def _valider(self, slot: Slot, events: list[LootEvent], *, compter_inconnu: bool) -> None:
        """Transforme un emplacement validé en drop, en silver, ou en rien.

        Les trois cas sont exclusifs et il faut les distinguer : une ligne de
        silver n'est pas une ligne non reconnue, même si toutes deux n'ont pas
        d'objet. Les confondre ferait passer chaque gain de pièces pour un trou
        de couverture du catalogue.
        """
        if slot.is_silver:
            self._silver_ready += slot.vote_silver()
            self._silver_lines += 1
            return
        event = slot.vote()
        if event is not None:
            events.append(event)
        elif compter_inconnu:
            self._unresolved_finalized += 1
            self._dropped_records.append((slot.best_raw(), False))
