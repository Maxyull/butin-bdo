"""Prix du marché central, et ce qu'on fait quand ils manquent.

L'API est instable par nature, et ce n'est pas notre faute
----------------------------------------------------------

Le marché central n'a pas d'API publique officielle. Les relais communautaires,
dont `api.arsha.io`, interrogent l'API du jeu pour nous. Or celle-ci est
protégée par un pare-feu applicatif qui bloque ces relais **par intermittence**.
Le message d'erreur le dit lui-même :

    One or more requests returned invalid data (probably blocked by Imperva).

Constaté en le mesurant : une même requête réussit, puis la suivante échoue en
500, puis la première remarche parce qu'elle est servie depuis le cache de 30
minutes du relais. Ce n'est ni une limitation de débit qu'on nous imposerait, ni
quelque chose qu'on puisse corriger en ralentissant.

**Conséquence de conception : le cache local n'est pas une optimisation, c'est
le mécanisme principal.** Le chemin réseau est le chemin de secours, pas
l'inverse.

Dégrader sans mentir
--------------------

Une session de farm ne doit jamais s'arrêter parce qu'un prix manque. La chaîne
de repli, du meilleur au pire :

1. **prix du marché frais**, tel que lu à l'instant ;
2. **prix du marché périmé**, gardé du dernier appel réussi ;
3. **valeur au marchand**, fixe, issue de la liste curée (`butin-connu.json`).
   C'est la seule valeur qui existe pour le trash loot, qui ne s'échange pas ;
4. **inconnu**, valeur zéro.

Chaque prix porte **d'où il vient et son âge**. C'est la partie qui compte : un
total calculé sur des prix vieux de six heures reste utile, mais le présenter
comme un cours du jour serait faux. L'interface doit pouvoir le dire.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .. import paths

_log = logging.getLogger(__name__)

BASE_URL = "https://api.arsha.io/v2/{region}/item"

# Hôtes autorisés à servir des prix. Même politique que le catalogue : une
# configuration modifiée ne doit pas pouvoir rediriger vers un serveur
# arbitraire.
ALLOWED_HOSTS = frozenset({"api.arsha.io"})

# (connexion, lecture). Court : un prix qui tarde n'a aucune valeur pendant une
# session, et le repli sur le cache est immédiat.
TIMEOUTS = (5, 15)

# Plafond de taille. Une fiche de prix fait quelques centaines d'octets.
MAX_BYTES = 1024 * 1024

# Durée au bout de laquelle un prix en cache est tenu pour périmé. Aligné sur
# le cache de 30 minutes du relais : redemander plus souvent ne rendrait pas
# une valeur plus fraîche, seulement plus de charge pour lui.
FRESH_FOR_S = 30 * 60


class Region(str, Enum):
    """Régions du marché. Le prix d'un même objet y diffère du simple au double."""

    EU = "eu"
    NA = "na"
    SEA = "sea"
    MENA = "mena"
    KR = "kr"
    RU = "ru"
    JP = "jp"
    TH = "th"
    TW = "tw"
    SA = "sa"
    CONSOLE_EU = "console_eu"
    CONSOLE_NA = "console_na"
    CONSOLE_ASIA = "console_asia"


class PriceSource(str, Enum):
    """D'où vient une valeur. Jamais deviné, toujours porté par le prix."""

    MARKET = "marche"
    MARKET_STALE = "marche-perime"
    VENDOR = "vendeur"
    UNKNOWN = "inconnu"


@dataclass(frozen=True, slots=True)
class Price:
    """Une valeur unitaire, avec sa provenance et son âge."""

    item_id: int
    value: int
    source: PriceSource
    fetched_at: float = 0.0
    sid: int = 0
    """Niveau d'amélioration. 0 pour un objet de base.

    Nécessaire parce que le niveau n'est **pas** une identité d'objet dans le
    jeu : un accessoire et son PRI partagent leur identifiant et n'ont pas du
    tout le même prix.
    """

    @property
    def is_known(self) -> bool:
        return self.source is not PriceSource.UNKNOWN

    def age_s(self, now: float) -> float:
        return max(0.0, now - self.fetched_at) if self.fetched_at else float("inf")


class MarketError(RuntimeError):
    """Le prix n'a pas pu être récupéré. Jamais fatal, toujours rattrapé."""


def _check_host(url: str, *, stage: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise MarketError(f"{stage} : schéma non https ({parsed.scheme!r})")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise MarketError(f"{stage} : hôte non autorisé ({parsed.hostname!r})")


class MarketClient:
    """Accès réseau au relais de marché. Ne connaît ni cache ni repli."""

    def __init__(
        self,
        region: Region = Region.EU,
        *,
        session: requests.Session | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        self.region = region
        self.base_url = base_url
        self._session = session or requests.Session()

    def fetch(self, item_id: int, *, sid: int = 0) -> Price:
        """Interroge le relais pour un objet. Lève `MarketError` sinon.

        Un seul identifiant par requête, délibérément. Le groupage existe mais
        oblige le relais à enchaîner plusieurs appels vers l'API du jeu, donc
        multiplie les chances qu'un seul blocage fasse échouer l'ensemble.
        Mesuré : la requête groupée échoue là où la requête simple passe.
        """
        url = self.base_url.format(region=self.region.value)
        _check_host(url, stage="URL demandée")
        try:
            response = self._session.get(
                url,
                params={"id": str(item_id), "sid": str(sid), "lang": "fr"},
                timeout=TIMEOUTS,
                headers={"User-Agent": "butin-bdo (+https://github.com/Maxyull/butin-bdo)"},
            )
            _check_host(response.url, stage="URL finale après redirection")
            response.raise_for_status()
            payload = response.content[: MAX_BYTES + 1]
        except requests.RequestException as exc:
            raise MarketError(f"prix indisponible pour {item_id} : {exc}") from exc

        if len(payload) > MAX_BYTES:
            raise MarketError(f"réponse anormalement volumineuse pour {item_id}")

        return _parse(payload, item_id=item_id, sid=sid)


def _parse(payload: bytes, *, item_id: int, sid: int) -> Price:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MarketError(f"réponse illisible pour {item_id} : {exc}") from exc

    if isinstance(data, list):
        # Le relais rend une liste quand plusieurs niveaux existent.
        entries = [entry for entry in data if isinstance(entry, dict)]
        data = next((e for e in entries if e.get("sid") == sid), entries[0] if entries else {})
    if not isinstance(data, dict):
        raise MarketError(f"réponse inattendue pour {item_id}")

    # `basePrice` est le prix affiché au marché. `lastSoldPrice` est le dernier
    # échange réel, qui peut être très au-dessus sur un objet rare peu liquide.
    # On retient le prix affiché : c'est celui auquel on peut vendre maintenant,
    # donc le seul honnête pour estimer un revenu horaire.
    raw = data.get("basePrice")
    if not isinstance(raw, int) or raw < 0:
        raise MarketError(f"prix manquant ou invalide pour {item_id}")

    return Price(
        item_id=item_id,
        value=raw,
        source=PriceSource.MARKET,
        fetched_at=time.time(),
        sid=sid,
    )


class PriceCache:
    """Cache de prix sur disque, qui survit à un redémarrage.

    Sur disque et non en mémoire : l'API est indisponible par moments, et une
    session lancée pendant une de ces fenêtres n'aurait aucun prix du tout si le
    cache disparaissait à chaque fermeture.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (paths.cache_dir() / "prix.json")
        self._entries: dict[str, dict[str, Any]] = {}
        self._load()

    @staticmethod
    def _key(item_id: int, sid: int) -> str:
        return f"{item_id}:{sid}"

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            # Un cache cassé est traité comme un cache vide : le programme sait
            # le reconstruire, bloquer dessus serait une panne inventée.
            _log.warning("cache de prix illisible (%s), ignoré", exc)
            return
        if isinstance(data, dict):
            self._entries = {k: v for k, v in data.items() if isinstance(v, dict)}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._entries, ensure_ascii=False), encoding="utf-8")

    def get(self, item_id: int, sid: int = 0) -> Price | None:
        entry = self._entries.get(self._key(item_id, sid))
        if entry is None:
            return None
        try:
            return Price(
                item_id=item_id,
                value=int(entry["value"]),
                source=PriceSource.MARKET,
                fetched_at=float(entry["fetched_at"]),
                sid=sid,
            )
        except (KeyError, TypeError, ValueError):
            return None

    def put(self, price: Price) -> None:
        self._entries[self._key(price.item_id, price.sid)] = {
            "value": price.value,
            "fetched_at": price.fetched_at,
        }
