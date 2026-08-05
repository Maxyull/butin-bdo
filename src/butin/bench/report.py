"""Le verdict : des nombres indépendants, et ce qu'ils autorisent à dire.

L'ordre de lecture est important, et le rapport le suit :

1. **La référence est-elle croyable ?** `assembly.py` compte les lignes de
   silver passées en recalant le texte image par image, `fingerprints.py` les
   compte par leurs montants tirés au hasard, sans jamais recaler quoi que ce
   soit. S'ils divergent, le banc **ne conclut rien** et le dit : mieux vaut pas
   de chiffre qu'un chiffre invérifiable.
2. **Le compteur s'en écarte de combien ?** C'est le pourcentage qu'on a le
   droit d'annoncer, une fois seulement l'étape 1 franchie.
3. **Qu'est-ce qui explique l'écart ?** Perte avouée par le compteur, images
   écartées, lignes hors catalogue. Un écart expliqué se corrige ; un écart
   constaté ne se corrige pas.

Le rapport ne connaît aucun seuil de réussite : ce n'est pas à lui de décider
qu'un écart de trois pour cent est acceptable pour un joueur. Il rend les
nombres et l'accord des méthodes, la décision est humaine et se prend une fois,
pas à chaque exécution.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..capture.lines import DEFAULT_FORMAT, ChatLineFormat, parse_line
from ..catalog.matcher import ItemMatcher, Scope
from ..tracking.models import LootEvent
from .assembly import Assembly
from .fingerprints import Fingerprints
from .pixels import PixelScroll
from .replay import Replay


@dataclass(frozen=True, slots=True)
class Tally:
    """Un total de butin, quel que soit le chemin qui l'a produit.

    Les quantités sont additionnées et non seulement les événements, parce que
    **c'est la quantité qui est perdue quand une ligne est ratée** : le journal
    n'affiche aucun cumul permettant de la retrouver ensuite.
    """

    events: int
    quantity: int
    silver: int
    per_item: tuple[tuple[str, int, int], ...]
    """(nom français, événements, quantité), du plus gros au plus petit."""

    unresolved: int = 0
    """Lignes de gain non reconnues par le catalogue. Comptées à part : elles ne
    sont ni du bruit ni du butin compté, elles sont un trou de couverture."""

    silver_lines: int = 0
    """Nombre de LIGNES de silver, distinct du montant cumulé. C'est ce nombre,
    et pas le montant, que les empreintes de `fingerprints.py` corroborent."""


def _tally(
    couples: Sequence[tuple[int, str, int]],
    *,
    silver: int,
    unresolved: int = 0,
    silver_lines: int = 0,
) -> Tally:
    """Assemble un total à partir de (item_id, nom, quantité)."""
    par_objet: dict[int, tuple[str, int, int]] = {}
    for item_id, nom, qty in couples:
        precedent = par_objet.get(item_id, (nom, 0, 0))
        par_objet[item_id] = (nom, precedent[1] + 1, precedent[2] + qty)
    ordonne = sorted(par_objet.values(), key=lambda ligne: (-ligne[2], -ligne[1], ligne[0]))
    return Tally(
        events=len(couples),
        quantity=sum(qty for _, _, qty in couples),
        silver=silver,
        per_item=tuple(ordonne),
        unresolved=unresolved,
        silver_lines=silver_lines,
    )


def tally_events(events: Sequence[LootEvent], *, silver: int = 0, silver_lines: int = 0) -> Tally:
    """Total du côté du compteur."""
    return _tally(
        [(event.item.item_id, event.item.name(), event.qty) for event in events],
        silver=silver,
        silver_lines=silver_lines,
    )


def tally_lines(
    raw_lines: Sequence[str],
    matcher: ItemMatcher,
    *,
    fmt: ChatLineFormat = DEFAULT_FORMAT,
    scope: Scope | None = None,
) -> Tally:
    """Total du côté de la référence, à partir de lignes brutes.

    Passe par le MÊME découpage de ligne que le compteur, et c'est assumé :
    réécrire un analyseur de ligne pour le banc reviendrait à mesurer l'accord
    de deux expressions régulières, pas celui de deux façons de compter. Ce que
    le banc compare, c'est **l'anti-double-comptage**, et lui seul.
    """
    couples: list[tuple[int, str, int]] = []
    argent = 0
    lignes_argent = 0
    inconnues = 0
    for brut in raw_lines:
        analysee = parse_line(brut, matcher, fmt=fmt, scope=scope)
        if analysee is None:
            continue
        if analysee.is_silver:
            argent += analysee.silver
            lignes_argent += 1
            continue
        objet = analysee.observed.item
        if objet is None:
            inconnues += 1
            continue
        couples.append((objet.item_id, objet.name(), analysee.observed.qty))
    return _tally(couples, silver=argent, unresolved=inconnues, silver_lines=lignes_argent)


def _ecart(mesure: float, reference: float) -> float | None:
    """Écart relatif signé, ou None quand la référence est nulle.

    Diviser par zéro rendrait « infini » là où la bonne réponse est « la
    question ne se pose pas ».
    """
    if reference == 0:
        return None
    return (mesure - reference) / reference


@dataclass(frozen=True, slots=True)
class BenchReport:
    """Tout ce que le banc a mesuré, et rien de plus."""

    counted: Tally
    reference: Tally
    replay: Replay
    assembly: Assembly
    scroll: PixelScroll
    fingerprints: Fingerprints
    frames: int
    interval_s: float

    # -- la référence est-elle croyable ? --------------------------------

    @property
    def reference_lines(self) -> int:
        """Lignes de chat passées, comptées par le recalage du texte."""
        return len(self.assembly.stream)

    @property
    def corroboration(self) -> float | None:
        """Écart entre les lignes de silver recalées et leurs empreintes.

        Proche de zéro : deux méthodes qui ne partagent que le découpage d'une
        ligne tombent d'accord, la référence tient. Loin de zéro : l'une des
        deux se trompe, rien ne dit laquelle, et le banc s'arrête là.

        ⚠️ Ce n'est pas un encadrement strict, et il ne faut pas le lire comme
        tel. Les empreintes sous-comptent par collision de montants, mais elles
        **sur-comptent** quand la première image a été mal lue : un montant que
        l'OCR a raté sur cette image-là n'entre pas dans le passé et se retrouve
        compté comme nouveau. Les deux effets jouent en sens contraire.

        Mesuré sur la rafale du 05/08/2026 : 45 lignes de silver par recalage
        contre 44 par empreinte. Le reste de l'écart tient à la première image,
        où le lecteur n'a retrouvé que 10 des 12 lignes de silver visibles.
        C'est cet ordre de grandeur qui rend la référence utilisable, pas une
        égalité qu'aucune des deux méthodes ne promet.
        """
        return _ecart(self.reference.silver_lines, self.fingerprints.kept)

    @property
    def pixels_usable(self) -> bool:
        """Faux quand la mesure en pixels n'a rien détecté du tout.

        Sur la rafale du 05/08/2026 elle ne détecte rien, et le banc doit le
        dire au lieu de présenter « 0 ligne défilée » comme une mesure. Voir
        `pixels.py` : la colonne des pastilles est périodique, un défilement
        d'exactement une ligne y est invisible.
        """
        return self.scroll.detections > 0

    # -- de combien le compteur s'en écarte ------------------------------

    @property
    def event_gap(self) -> float | None:
        return _ecart(self.counted.events, self.reference.events)

    @property
    def quantity_gap(self) -> float | None:
        return _ecart(self.counted.quantity, self.reference.quantity)

    @property
    def silver_gap(self) -> float | None:
        """Écart du montant de silver, mesuré contre les EMPREINTES.

        Et non contre le recalage du texte, délibérément. Sur le nombre de
        lignes le recalage fait autorité ; sur les montants il ne vaut pas mieux
        que le compteur, puisqu'il lit les mêmes chiffres avec le même moteur.
        Mesuré : 4 de ses 45 lignes portent un montant illisible, donc comptées
        1 au lieu de deux mille, ce qui le rend 5 % trop bas. Comparer deux
        mesures de qualité égale n'apprend rien.

        Les empreintes, elles, ne retiennent un montant qu'après l'avoir vu au
        moins trois fois. Elles sont donc la seule des trois à pouvoir arbitrer
        ici.
        """
        return _ecart(self.counted.silver, self.fingerprints.total)

    @property
    def silver_line_gap(self) -> float | None:
        """Écart sur le NOMBRE de lignes de silver, pas sur le montant.

        Les deux séparés, parce qu'ils ne se corrigent pas au même endroit :
        rater une ligne est un problème de cadence ou d'alignement, mal lire un
        montant est un problème de vote.
        """
        return _ecart(self.counted.silver_lines, self.reference.silver_lines)

    @property
    def within_ceiling(self) -> bool:
        """Vrai si le compteur reste sous le nombre total de lignes passées.

        Une ligne de butin est une ligne de chat, donc compter plus de drops que
        de lignes apparues est impossible. La dépasser prouve un double
        comptage sans avoir à discuter de la référence.
        """
        return self.counted.events <= self.reference_lines

    # -- rendu -----------------------------------------------------------

    def render(self) -> str:
        """Rapport lisible, en français, destiné à être collé dans une PR."""
        lignes = [
            f"Banc d'essai — {self.frames} images à {self.interval_s * 1000:.0f} ms "
            f"({self.frames * self.interval_s:.1f} s de jeu)",
            "",
            "1. La référence est-elle croyable ?",
            f"   lignes passées, par recalage   : {self.reference_lines}",
            f"   dont lignes de silver          : {self.reference.silver_lines}",
            f"   lignes de silver, par empreinte : {self.fingerprints.kept}"
            f"   (+{self.fingerprints.dropped} sans support, "
            f"collisions attendues : {self.fingerprints.expected_collisions:.1f})",
            f"   accord des deux méthodes       : {_pourcent(self.corroboration)}",
            f"   lectures par empreinte, médiane : {self.fingerprints.median_support:.0f}",
            f"   lignes vues une seule fois     : {self.assembly.fragile_count}",
            f"   images sans aucun recouvrement : {len(self.assembly.replaced)}",
            "   défilement en pixels           : "
            + (
                f"{self.scroll.rows:.1f} lignes ({self.scroll.detections} détections)"
                if self.pixels_usable
                else f"INOPÉRANT, aucune détection sur {max(0, self.frames - 1)} transitions"
            ),
            "",
            "2. De combien le compteur s'en écarte",
            f"   drops comptés / référence      : {self.counted.events} / "
            f"{self.reference.events}   ({_pourcent(self.event_gap)})",
            f"   quantité cumulée               : {self.counted.quantity} / "
            f"{self.reference.quantity}   ({_pourcent(self.quantity_gap)})",
            f"   silver, contre empreintes      : {self.counted.silver} / "
            f"{self.fingerprints.total}   ({_pourcent(self.silver_gap)})",
            f"   pour mémoire, par recalage     : {self.reference.silver}",
            f"   lignes de silver               : {self.counted.silver_lines} / "
            f"{self.reference.silver_lines}   ({_pourcent(self.silver_line_gap)})",
            f"   sous le plafond des lignes     : {'oui' if self.within_ceiling else 'NON'}",
            "",
            "3. Ce qui explique l'écart",
            f"   images vraiment lues           : {len(self.replay.read_frames)} / {self.frames}",
            f"   images écartées par un garde-fou : {len(self.replay.skipped)}",
            f"   butin reconnu puis perdu       : {self.replay.lost_resolved}",
            f"   lignes hors catalogue          : {self.reference.unresolved}",
            "",
            "Détail par objet (compteur / référence) :",
        ]
        reference_par_nom = {nom: (n, qty) for nom, n, qty in self.reference.per_item}
        compteur_par_nom = {nom: (n, qty) for nom, n, qty in self.counted.per_item}
        for nom in sorted(set(reference_par_nom) | set(compteur_par_nom)):
            c_n, c_q = compteur_par_nom.get(nom, (0, 0))
            r_n, r_q = reference_par_nom.get(nom, (0, 0))
            lignes.append(f"   {nom:<45} {c_n:>4} / {r_n:<4}   x{c_q:<6} / x{r_q}")
        return "\n".join(lignes)


def _pourcent(valeur: float | None) -> str:
    if valeur is None:
        return "sans objet"
    return f"{valeur:+.1%}"


def build_report(
    replay_result: Replay,
    assembly: Assembly,
    scroll: PixelScroll,
    fingerprints: Fingerprints,
    matcher: ItemMatcher,
    *,
    frames: int,
    interval_s: float,
    fmt: ChatLineFormat = DEFAULT_FORMAT,
    scope: Scope | None = None,
) -> BenchReport:
    """Rassemble les mesures indépendantes en un rapport."""
    return BenchReport(
        counted=tally_events(
            replay_result.events,
            silver=replay_result.silver,
            silver_lines=replay_result.silver_lines,
        ),
        reference=tally_lines(
            [ligne.text for ligne in assembly.stream], matcher, fmt=fmt, scope=scope
        ),
        replay=replay_result,
        assembly=assembly,
        scroll=scroll,
        fingerprints=fingerprints,
        frames=frames,
        interval_s=interval_s,
    )
