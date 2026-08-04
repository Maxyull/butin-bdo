"""Catalogue d'objets français, normalisation et reconnaissance."""

from .catalog import ItemCatalog
from .matcher import ItemMatcher, Match, MatchMethod, Scope
from .models import LOCALE_EN, LOCALE_FR, Item
from .normalize import fold, fold_digits, is_meaningful, strip_accents
from .source import CatalogError
from .zones import detect_spot, known_zones, load_zones

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
    "detect_spot",
    "fold",
    "fold_digits",
    "is_meaningful",
    "known_zones",
    "load_zones",
    "strip_accents",
]
