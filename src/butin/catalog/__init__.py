"""Catalogue d'objets français, normalisation et reconnaissance."""

from .catalog import ItemCatalog
from .icons import IconStore
from .matcher import ItemMatcher, Match, MatchMethod, Scope
from .models import LOCALE_EN, LOCALE_FR, Item
from .normalize import fold, fold_digits, is_meaningful, strip_accents
from .source import CatalogError
from .zones import detect_spot, known_loot_ids, known_zones, load_zone_translations, load_zones

__all__ = [
    "LOCALE_EN",
    "LOCALE_FR",
    "CatalogError",
    "IconStore",
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
    "known_loot_ids",
    "known_zones",
    "load_zone_translations",
    "load_zones",
    "strip_accents",
]
