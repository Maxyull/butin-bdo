"""Résolution d'une ligne OCR vers un objet du catalogue.

Deux chemins, dans cet ordre :

1. Correspondance exacte sur la forme repliée. Sur une capture nette, c'est la
   très grande majorité des lignes, et le résultat est certain.
2. Correspondance floue, uniquement quand l'exacte échoue. C'est le rattrapage
   des lectures abîmées (« Fragrnent d'âme » pour « Fragment d'âme »).

Le score flou est le composant le plus dangereux du projet. Il trouve toujours
quelque chose : sur 8000 noms, n'importe quel bruit ressemble à au moins un
objet. Deux garde-fous encadrent donc son usage, portés par
`bdo_ocr_core.matcher.fuzzy_resolve` depuis le 06/08/2026 (politique de
décision extraite, partagée avec rubin-bdo — voir ATTRIBUTION.md) : ce module
ne fait plus que la brancher sur `ItemCatalog`.

**Le seuil.** En dessous, aucun résultat n'est rendu. Réglé haut par défaut :
rater un drop est un chiffre légèrement bas, inventer un drop est un chiffre
faux. Les deux erreurs ne coûtent pas la même chose, le réglage n'est donc pas
symétrique.

**La marge d'ambiguïté.** Si les deux meilleurs candidats sont à quelques
points l'un de l'autre, la ligne est rejetée même quand le meilleur dépasse
le seuil. Le français rend ce cas fréquent : beaucoup de noms ne diffèrent
que par un qualificatif final (« Cristal noir tranchant » contre « Cristal
noir dur »). Sans cette marge, une lecture abîmée de l'un se résout
silencieusement en l'autre, et l'écart de prix entre les deux peut être d'un
ordre de grandeur.

**La restriction par zone** (`scope`) est le levier de précision le plus
efficace du projet. Un spot de farm fait tomber quelques dizaines d'objets
distincts, pas huit mille. Restreindre les candidats à cette liste supprime
d'un coup la quasi-totalité des faux positifs possibles, et permet même
d'abaisser le seuil sans perdre en sûreté.

Par défaut, le périmètre ne contraint QUE le score flou : une correspondance
exacte reste acceptée même hors périmètre. C'est délibéré. Les listes de drops
par spot sont saisies à la main, donc incomplètes par nature, alors qu'une
correspondance exacte signifie que le texte lu se replie caractère pour
caractère sur un vrai nom du catalogue. Refuser une lecture certaine parce que
notre table de drops est en retard perdrait de vrais drops pour ne rien gagner
en précision. `strict=True` durcit ce comportement pour qui préfère l'inverse.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from bdo_ocr_core.matcher import (
    DEFAULT_AMBIGUITY_MARGIN,
    DEFAULT_THRESHOLD,
    SCOPED_THRESHOLD,
    MatchMethod,
    fuzzy_resolve,
)

from .catalog import ItemCatalog
from .models import Item
from .normalize import fold, is_meaningful

_log = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_AMBIGUITY_MARGIN",
    "DEFAULT_THRESHOLD",
    "SCOPED_THRESHOLD",
    "ItemMatcher",
    "Match",
    "MatchMethod",
    "Scope",
]


@dataclass(frozen=True, slots=True)
class Match:
    """Un objet reconnu, avec la confiance et la méthode employée."""

    item: Item
    score: float
    method: MatchMethod

    @property
    def is_certain(self) -> bool:
        return self.method is MatchMethod.EXACT


class Scope:
    """Sous-ensemble d'objets attendus, typiquement les drops d'un spot.

    Construit une fois par session de farm et réutilisé à chaque image. Le
    construire à chaque image annulerait le gain de performance recherché.
    """

    def __init__(
        self,
        catalog: ItemCatalog,
        item_ids: Iterable[int],
        *,
        strict: bool = False,
    ) -> None:
        self.catalog = catalog
        self.strict = strict
        names: list[str] = []
        self.item_ids: tuple[int, ...] = tuple(item_ids)
        for item_id in self.item_ids:
            item = catalog.get(item_id)
            if item is None:
                _log.warning("identifiant %d absent du catalogue, ignoré du périmètre", item_id)
                continue
            folded = fold(item.name(catalog.locale))
            if folded:
                names.append(folded)
        self.folded_names: tuple[str, ...] = tuple(dict.fromkeys(names))

    def __len__(self) -> int:
        return len(self.folded_names)

    def __bool__(self) -> bool:
        return bool(self.folded_names)

    def contains(self, item_id: int) -> bool:
        return item_id in self.item_ids


class ItemMatcher:
    """Résout un texte OCR vers un objet du catalogue."""

    def __init__(
        self,
        catalog: ItemCatalog,
        *,
        threshold: float = DEFAULT_THRESHOLD,
        scoped_threshold: float = SCOPED_THRESHOLD,
        ambiguity_margin: float = DEFAULT_AMBIGUITY_MARGIN,
        min_letters: int = 3,
    ) -> None:
        self.catalog = catalog
        self.threshold = threshold
        self.scoped_threshold = scoped_threshold
        self.ambiguity_margin = ambiguity_margin
        self.min_letters = min_letters

    def resolve(self, text: str, *, scope: Scope | None = None) -> Match | None:
        """Renvoie l'objet correspondant, ou None si rien de sûr n'est trouvé.

        Renvoyer None est un résultat normal et fréquent, pas une erreur : le
        journal d'acquisition contient des lignes qui ne sont pas des drops
        (messages système, restes de bordure lus comme du texte).
        """
        folded = fold(text)
        if not is_meaningful(folded, self.min_letters):
            return None

        exact = self.catalog.by_exact_name(folded)
        if exact is not None:
            # Hors périmètre, une correspondance exacte reste acceptée sauf en
            # mode strict : voir l'explication en tête de module.
            if scope is None or not scope.strict or scope.contains(exact.item_id):
                return Match(item=exact, score=100.0, method=MatchMethod.EXACT)
            return None

        # ⭐ Deuxième clé exacte, avant le score flou : espaces retirés et
        # glyphes verticaux unifiés. Elle rattrape les deux défauts d'OCR
        # mesurés sur une vraie session (« Sceau del'Agent », « Sceau de
        # I'Agent »), que le flou ne rattrape PAS — deux mots recollés font un
        # mot différent, pas un mot abîmé.
        #
        # Placée ici et pas avant l'exacte : tant qu'une correspondance stricte
        # existe, elle gagne. Placée avant le flou parce qu'elle est exacte,
        # donc elle ne peut pas se tromper « un peu » ; le flou, si.
        #
        # Voir `ItemCatalog.by_compact_name` pour la mesure et son coût.
        compact = self.catalog.by_compact_name(text)
        if compact is not None and (
            scope is None or not scope.strict or scope.contains(compact.item_id)
        ):
            return Match(item=compact, score=100.0, method=MatchMethod.EXACT)

        choices: Sequence[str]
        threshold: float
        if scope:
            choices = scope.folded_names
            threshold = self.scoped_threshold
        else:
            choices = self.catalog.folded_names
            threshold = self.threshold

        resolved = fuzzy_resolve(
            folded, choices, threshold=threshold, ambiguity_margin=self.ambiguity_margin
        )
        if resolved is None:
            return None
        best_name, best_score = resolved

        item = self.catalog.item_for_folded(best_name)
        if item is None:
            return None
        return Match(item=item, score=best_score, method=MatchMethod.FUZZY)
