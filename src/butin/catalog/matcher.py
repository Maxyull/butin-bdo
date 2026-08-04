"""Résolution d'une ligne OCR vers un objet du catalogue.

Deux chemins, dans cet ordre :

1. Correspondance exacte sur la forme repliée. Sur une capture nette, c'est la
   très grande majorité des lignes, et le résultat est certain.
2. Correspondance floue, uniquement quand l'exacte échoue. C'est le rattrapage
   des lectures abîmées (« Fragrnent d'âme » pour « Fragment d'âme »).

Le score flou est le composant le plus dangereux du projet. Il trouve toujours
quelque chose : sur 8000 noms, n'importe quel bruit ressemble à au moins un
objet. Deux garde-fous encadrent donc son usage.

**Le seuil.** En dessous, aucun résultat n'est rendu. Réglé haut par défaut :
rater un drop est un chiffre légèrement bas, inventer un drop est un chiffre
faux. Les deux erreurs ne coûtent pas la même chose, le réglage n'est donc pas
symétrique.

**La marge d'ambiguïté.** Si les deux meilleurs candidats sont à quelques
points l'un de l'autre, la ligne est rejetée même quand le meilleur dépasse le
seuil. Le français rend ce cas fréquent : beaucoup de noms ne diffèrent que par
un qualificatif final (« Cristal noir tranchant » contre « Cristal noir dur »).
Sans cette marge, une lecture abîmée de l'un se résout silencieusement en
l'autre, et l'écart de prix entre les deux peut être d'un ordre de grandeur.

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
from enum import Enum

from rapidfuzz import fuzz, process

from .catalog import ItemCatalog
from .models import Item
from .normalize import fold, is_meaningful

_log = logging.getLogger(__name__)

# Seuil par défaut, sur 100. Mesuré comme un bon compromis sur des noms
# français longs : en dessous de 88, les paires ne différant que par leur
# dernier mot commencent à se confondre.
DEFAULT_THRESHOLD = 88.0

# Écart minimal entre le meilleur et le deuxième candidat pour accepter un
# résultat flou.
DEFAULT_AMBIGUITY_MARGIN = 4.0

# Seuil abaissé quand les candidats sont restreints à une zone : sur quelques
# dizaines de noms, le risque de collision s'effondre.
SCOPED_THRESHOLD = 80.0


class MatchMethod(str, Enum):
    """Comment la correspondance a été obtenue."""

    EXACT = "exact"
    FUZZY = "flou"


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

        choices: Sequence[str]
        threshold: float
        if scope:
            choices = scope.folded_names
            threshold = self.scoped_threshold
        else:
            choices = self.catalog.folded_names
            threshold = self.threshold

        if not choices:
            return None

        # limit=2 : le deuxième candidat sert uniquement au contrôle
        # d'ambiguïté ci-dessous, il n'est jamais retenu comme résultat.
        results = process.extract(
            folded,
            choices,
            scorer=fuzz.WRatio,
            limit=2,
            score_cutoff=threshold,
        )
        if not results:
            return None

        best_name, best_score, _ = results[0]
        if len(results) > 1:
            second_score = results[1][1]
            if best_score - second_score < self.ambiguity_margin:
                _log.debug(
                    "ligne rejetée pour ambiguïté : %r entre %r (%.1f) et %r (%.1f)",
                    text,
                    best_name,
                    best_score,
                    results[1][0],
                    second_score,
                )
                return None

        item = self.catalog.item_for_folded(best_name)
        if item is None:
            return None
        return Match(item=item, score=float(best_score), method=MatchMethod.FUZZY)
