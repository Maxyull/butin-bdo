"""Récupération du catalogue d'objets depuis la source publique.

Butin ne maintient pas sa propre liste d'objets. Il consomme le jeu de données
public `veliainn-market-resources`, qui publie chaque jour un `items.json`
contenant les identifiants et les noms dans quatorze langues, dont le français.
C'est ce fichier qui rend le projet possible : sans lui, il faudrait traduire
plusieurs milliers de noms à la main et les tenir à jour à chaque patch.

Le fichier fait environ 6 Mo et est mis en cache localement. Le
téléchargement est le seul moment où Butin lit une donnée qu'il ne contrôle
pas, donc c'est le seul endroit où une donnée hostile pourrait entrer. Les
protections en place, et ce que chacune empêche concrètement :

* HTTPS obligatoire, et hôte comparé à une liste blanche. Empêche une
  configuration modifiée de faire pointer le téléchargement vers un serveur
  arbitraire.
* Redirections suivies mais l'hôte final est revalidé. Sans cela, la liste
  blanche ne protège que le premier saut, ce qui ne protège rien.
* Lecture en flux avec plafond de taille. Empêche qu'une réponse sans fin
  remplisse le disque. Le plafond est vérifié sur les octets réellement lus,
  pas sur l'en-tête `Content-Length`, qui est déclaratif et donc mensongeable.
* Délai d'attente sur connexion et sur lecture. Sans le second, un serveur qui
  envoie un octet par minute bloque le programme indéfiniment.
* Analyse en JSON strict. Pas de `pickle`, pas de `eval`, pas de YAML : aucun
  de ces formats ne peut être désérialisé sans exécuter du code.
* Validation de forme avant d'écrire le cache. Un fichier tronqué ou d'une
  autre nature n'écrase jamais un cache valide.
* Écriture atomique. Une coupure en cours d'écriture laisse l'ancien cache
  intact plutôt qu'un fichier à moitié écrit qui échouera silencieusement au
  prochain démarrage.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

_log = logging.getLogger(__name__)

CATALOG_URL = (
    "https://raw.githubusercontent.com/andreivreja/veliainn-market-resources/main/data/items.json"
)

# Hôtes autorisés à servir le catalogue. Volontairement minimal.
ALLOWED_HOSTS = frozenset({"raw.githubusercontent.com"})

# Plafond de taille. Le fichier réel fait ~6,5 Mo début août 2026 ; 64 Mo laisse
# de la marge pour des années de croissance tout en restant très loin de ce qui
# pourrait saturer un disque.
MAX_BYTES = 64 * 1024 * 1024

# (connexion, lecture). Le second est celui qui compte : il se réarme à chaque
# paquet reçu, donc il ne coupe pas un téléchargement lent mais vivant.
TIMEOUTS = (10, 60)

_CHUNK = 64 * 1024

# En dessous, un catalogue est considéré comme tronqué. Le vrai fichier contient
# plus de 8000 objets ; 1000 est un plancher qui n'exclut aucun cas réel.
MIN_ITEMS = 1000


class CatalogError(RuntimeError):
    """Le catalogue n'a pas pu être récupéré ou n'est pas exploitable."""


def _check_host(url: str, *, stage: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise CatalogError(f"{stage} : schéma non https ({parsed.scheme!r}) pour {url!r}")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise CatalogError(f"{stage} : hôte non autorisé ({parsed.hostname!r})")


def _read_capped(response: requests.Response) -> bytes:
    """Lit le corps de la réponse en refusant de dépasser MAX_BYTES."""
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=_CHUNK):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_BYTES:
            raise CatalogError(f"réponse trop volumineuse : plus de {MAX_BYTES} octets reçus")
        chunks.append(chunk)
    return b"".join(chunks)


def fetch_raw(url: str = CATALOG_URL, *, session: requests.Session | None = None) -> bytes:
    """Télécharge le catalogue brut et renvoie ses octets.

    Ne touche pas au disque : la validation puis l'écriture sont faites par
    `refresh`, pour qu'un téléchargement invalide n'écrase jamais le cache.
    """
    _check_host(url, stage="URL demandée")
    http = session or requests.Session()
    try:
        response = http.get(url, timeout=TIMEOUTS, stream=True)
        # L'hôte de départ était sur la liste blanche, mais une redirection a pu
        # emmener ailleurs. C'est l'URL finale qui a servi la donnée.
        _check_host(response.url, stage="URL finale après redirection")
        response.raise_for_status()
        return _read_capped(response)
    except requests.RequestException as exc:
        raise CatalogError(f"échec du téléchargement du catalogue : {exc}") from exc
    finally:
        if session is None:
            http.close()


def parse(payload: bytes) -> dict[str, Any]:
    """Analyse et valide la forme du catalogue.

    Lève `CatalogError` plutôt que de renvoyer une structure douteuse : un
    catalogue à moitié valide produirait des correspondances silencieusement
    fausses, ce qui est pire qu'un échec net au démarrage.
    """
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"catalogue illisible : {exc}") from exc

    if not isinstance(data, dict):
        raise CatalogError(f"catalogue attendu sous forme d'objet, reçu {type(data).__name__}")
    if len(data) < MIN_ITEMS:
        raise CatalogError(
            f"catalogue anormalement court ({len(data)} objets, minimum attendu {MIN_ITEMS})"
        )

    # Échantillonnage de forme plutôt que validation exhaustive : parcourir
    # 8000 entrées à chaque démarrage coûte cher pour un gain nul, et une
    # troncature ou un changement de format se voit dès les premières entrées.
    for key, entry in _sample(data, 25):
        if not isinstance(entry, dict):
            raise CatalogError(f"entrée {key!r} : objet attendu, reçu {type(entry).__name__}")
        if "id" not in entry:
            raise CatalogError(f"entrée {key!r} : champ « id » manquant")
        if not isinstance(entry.get("locale_name"), dict):
            raise CatalogError(f"entrée {key!r} : champ « locale_name » manquant ou mal formé")

    return data


def _sample(data: dict[str, Any], count: int) -> Iterator[tuple[str, Any]]:
    """Rend les `count` premières entrées, dans l'ordre d'itération du dict."""
    for index, item in enumerate(data.items()):
        if index >= count:
            return
        yield item


def write_cache(payload: bytes, path: Path) -> None:
    """Écrit le cache de façon atomique.

    Le fichier temporaire est créé dans le dossier de destination et non dans
    le dossier temporaire du système : `os.replace` n'est atomique qu'à
    l'intérieur d'un même volume, et rien ne garantit que %TEMP% soit sur le
    même disque que %LOCALAPPDATA%.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".items-", suffix=".tmp")
    temp_path = Path(temp_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # os.replace plutôt que Path.replace, qui est pourtant le même appel :
        # le test de régression « l'ancien cache survit à un échec » remplace
        # cette fonction pour simuler un disque plein. La forme module.fonction
        # se remplace pour ce seul module, là où patcher Path.replace
        # l'échangerait pour tous les chemins du processus, y compris ceux de
        # pytest lui-même.
        os.replace(temp_path, path)  # noqa: PTH105
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def refresh(
    path: Path,
    *,
    url: str = CATALOG_URL,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Télécharge, valide, met en cache et renvoie le catalogue."""
    payload = fetch_raw(url, session=session)
    data = parse(payload)
    write_cache(payload, path)
    _log.info("catalogue rafraîchi : %d objets écrits dans %s", len(data), path)
    return data


def load_cached(path: Path) -> dict[str, Any] | None:
    """Charge le cache local, ou renvoie None s'il est absent ou inexploitable.

    Un cache corrompu est traité comme un cache absent, pas comme une erreur :
    l'appelant retéléchargera. Écouler l'erreur ici évite de bloquer le
    démarrage sur un fichier que le programme sait reconstruire tout seul.
    """
    if not path.exists():
        return None
    try:
        return parse(path.read_bytes())
    except (CatalogError, OSError) as exc:
        _log.warning("cache du catalogue inexploitable (%s), il sera retéléchargé", exc)
        return None
