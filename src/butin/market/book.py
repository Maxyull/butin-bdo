"""Chaîne de repli qui donne toujours une valeur, et dit toujours laquelle.

`PriceBook` est le seul point que le reste du programme interroge. Il masque le
fait que le prix vient tantôt du marché, tantôt d'un cache vieux de six heures,
tantôt d'une valeur au marchand figée à la main.

Il ne masque **jamais** de quelle source il vient. C'est toute la différence
entre un chiffre approximatif et un chiffre faux : le premier reste utilisable
si on sait ce qu'il vaut.

L'ordre de repli, et pourquoi celui-là
--------------------------------------

1. **Cache frais.** Le relais met lui-même en cache trente minutes : redemander
   plus souvent ne rendrait pas une valeur plus récente, seulement plus de
   charge pour un service gratuit.
2. **Réseau.** Chemin de secours et non chemin principal, parce que l'API est
   bloquée par intermittence par le pare-feu du jeu.
3. **Cache périmé.** Un prix de ce matin vaut infiniment mieux que zéro. Il est
   marqué comme périmé, avec son âge.
4. **Valeur au marchand.** Pour le trash loot, c'est la SEULE valeur qui existe :
   il ne s'échange pas à l'hôtel des ventes, il se vend au PNJ à prix fixe. Ce
   n'est donc pas un repli dégradé mais la bonne réponse.
5. **Inconnu, zéro.** Compté comme tel et signalé, jamais deviné.

Le réseau ne bloque jamais une session : un échec descend d'un cran, il
n'interrompt rien.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from .client import (
    FRESH_FOR_S,
    MarketClient,
    MarketError,
    Price,
    PriceCache,
    PriceSource,
)

_log = logging.getLogger(__name__)


def default_vendor_path() -> Path:
    """Emplacement de la liste de butin livrée avec le projet."""
    return Path(__file__).resolve().parents[3] / "data" / "butin-connu.json"


def load_vendor_values(path: Path | None = None) -> dict[int, dict[str, int]]:
    """Charge les valeurs au marchand, rangées par niveau d'amélioration.

    Un fichier absent renvoie un dictionnaire vide plutôt qu'une erreur : le
    programme fonctionne sans, simplement avec moins d'objets valorisés.
    """
    chemin = path or default_vendor_path()
    if not chemin.exists():
        return {}
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _log.warning("liste de butin illisible (%s), ignorée", exc)
        return {}

    valeurs: dict[int, dict[str, int]] = {}
    for cle, fiche in (brut.get("items") or {}).items():
        try:
            item_id = int(cle)
        except (TypeError, ValueError):
            continue
        if not isinstance(fiche, dict):
            continue
        par_niveau = fiche.get("valeurs")
        if isinstance(par_niveau, dict):
            valeurs[item_id] = {str(k): int(v) for k, v in par_niveau.items() if isinstance(v, int)}
    return valeurs


# Correspondance entre le niveau numérique du marché et l'étiquette de la liste
# curée. Le marché compte en entiers, la liste écrit les noms du jeu.
_SID_TO_LEVEL = {0: "base", 1: "PRI", 2: "DUO", 3: "TRI", 4: "TET", 5: "PEN"}


class PriceBook:
    """Donne une valeur pour tout objet, et dit d'où elle vient."""

    def __init__(
        self,
        client: MarketClient | None = None,
        *,
        cache: PriceCache | None = None,
        vendor_values: dict[int, dict[str, int]] | None = None,
        fresh_for_s: float = FRESH_FOR_S,
    ) -> None:
        self.client = client
        self.cache = cache if cache is not None else PriceCache()
        self.vendor_values = vendor_values if vendor_values is not None else load_vendor_values()
        self.fresh_for_s = fresh_for_s
        self.network_failures = 0
        """Compteur d'échecs réseau. Une session entière servie depuis le cache
        est un fait que l'interface doit pouvoir montrer, pas un détail."""

    def price(self, item_id: int, *, sid: int = 0, now: float | None = None) -> Price:
        """Valeur unitaire d'un objet. Ne lève jamais."""
        maintenant = time.time() if now is None else now

        en_cache = self.cache.get(item_id, sid)
        if en_cache is not None and en_cache.age_s(maintenant) <= self.fresh_for_s:
            return en_cache

        frais = self._try_network(item_id, sid)
        if frais is not None:
            self.cache.put(frais)
            return frais

        if en_cache is not None:
            return Price(
                item_id=item_id,
                value=en_cache.value,
                source=PriceSource.MARKET_STALE,
                fetched_at=en_cache.fetched_at,
                sid=sid,
            )

        marchand = self._vendor_value(item_id, sid)
        if marchand is not None:
            return Price(item_id=item_id, value=marchand, source=PriceSource.VENDOR, sid=sid)

        return Price(item_id=item_id, value=0, source=PriceSource.UNKNOWN, sid=sid)

    def _try_network(self, item_id: int, sid: int) -> Price | None:
        if self.client is None:
            return None
        try:
            return self.client.fetch(item_id, sid=sid)
        except MarketError as exc:
            # Un échec réseau descend d'un cran, il n'interrompt jamais une
            # session de farm en cours.
            self.network_failures += 1
            _log.debug("prix marché indisponible pour %d : %s", item_id, exc)
            return None

    def _vendor_value(self, item_id: int, sid: int) -> int | None:
        par_niveau = self.vendor_values.get(item_id)
        if not par_niveau:
            return None
        niveau = _SID_TO_LEVEL.get(sid, "base")
        valeur = par_niveau.get(niveau)
        if valeur is None and niveau != "base":
            # Un accessoire amélioré dont seul le niveau de base est renseigné
            # vaut au moins celui-ci. Sous-estimer est le bon sens de l'erreur.
            valeur = par_niveau.get("base")
        return valeur

    def total(self, quantities: dict[int, int], *, now: float | None = None) -> int:
        """Valeur totale d'un ensemble d'objets, identifiant vers quantité."""
        return sum(self.price(item_id, now=now).value * qty for item_id, qty in quantities.items())

    def save(self) -> None:
        self.cache.save()
