"""Types du catalogue d'objets.

Le point structurant : un objet est identifié par son `item_id` numérique, pas
par son nom. Les noms sont des étiquettes localisées attachées à cet identifiant.

Ça peut sembler évident, mais c'est précisément ce que les trackers existants
ne font pas : ils indexent tout par nom anglais, ce qui rend le multilingue
impossible à greffer après coup. Deux objets peuvent partager un nom français,
un objet change de nom entre deux patchs, et le prix du marché s'interroge par
identifiant. L'identifiant est la seule clé stable.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

# Code de langue du catalogue amont pour le français. Les données publient les
# locales sous des codes courts non standards (« us » et non « en », « fr »
# pour le français), on ne les invente pas ici.
LOCALE_FR = "fr"
LOCALE_EN = "us"


@dataclass(frozen=True, slots=True)
class Item:
    """Un objet du jeu, avec ses noms localisés."""

    item_id: int
    names: Mapping[str, str] = field(default_factory=dict)
    grade: int = 0
    category_primary: int = 0
    category_secondary: int = 0

    def name(self, locale: str = LOCALE_FR, fallback: str = LOCALE_EN) -> str:
        """Nom dans la locale demandée, avec repli.

        Le repli sur l'anglais est volontaire et visible : un objet dont la
        traduction française manque doit s'afficher en anglais plutôt que de
        disparaître de l'interface. Un trou de traduction est un défaut
        cosmétique, un objet manquant est un drop non compté.
        """
        value = self.names.get(locale)
        if value:
            return value
        return self.names.get(fallback, f"#{self.item_id}")

    def has_locale(self, locale: str) -> bool:
        return bool(self.names.get(locale))
