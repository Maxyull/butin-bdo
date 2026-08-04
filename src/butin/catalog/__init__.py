"""Catalogue d'objets français, normalisation et reconnaissance."""

from .catalog import ItemCatalog
from .matcher import ItemMatcher, Match, MatchMethod, Scope
from .models import LOCALE_EN, LOCALE_FR, Item
from .normalize import fold, fold_digits, is_meaningful, strip_accents
from .source import CatalogError

__all__ = [
    "LOCALE_EN",
    "LOCALE_FR",
    "CatalogError",
    "Item",
    "ItemCatalog",
    "ItemMatcher",
    "Match",
    "MatchMethod",
    "Scope",
    "fold",
    "fold_digits",
    "is_meaningful",
    "strip_accents",
]
