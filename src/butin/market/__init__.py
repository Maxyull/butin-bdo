"""Prix du marché central, avec repli quand ils manquent.

L'API du marché est bloquée par intermittence par le pare-feu du jeu. Le cache
local est donc le mécanisme principal et le réseau le chemin de secours, pas
l'inverse. Voir `client.py` pour la mesure qui a conduit là.

`PriceBook` est le seul point à interroger : il donne toujours une valeur, et
dit toujours d'où elle vient.
"""

from .book import PriceBook, load_vendor_values
from .client import (
    MarketClient,
    MarketError,
    Price,
    PriceCache,
    PriceSource,
    Region,
)

__all__ = [
    "MarketClient",
    "MarketError",
    "Price",
    "PriceBook",
    "PriceCache",
    "PriceSource",
    "Region",
    "load_vendor_values",
]
