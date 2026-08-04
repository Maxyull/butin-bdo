"""Noms d'objets depuis bdocodex, la base complète.

Pourquoi remplacer veliainn comme source de noms
-------------------------------------------------

Mesuré sur une vraie capture, chaîne complète : avec veliainn seul, sur 16
lignes de gain lues à l'écran, **9 justes, 5 non reconnues, et 2 FAUSSES**.

Les deux fausses sont le vrai sujet. « Boucle d'oreille de Tuvala » était
attribué à « Boucle d'oreille de Talis ». L'objet Tuvala est lié au personnage,
donc absent d'un catalogue de marché ; le score flou est allé chercher le voisin
le plus proche au lieu de refuser, et la marge d'ambiguïté n'a rien vu passer
puisqu'il n'y avait qu'un seul candidat plausible.

C'est la pire erreur possible : un objet faux attribué en silence, avec un prix
qui n'a rien à voir. Le trou de couverture ne cause donc pas seulement des
oublis, il cause des **attributions fausses**.

bdocodex publie 68 714 objets contre 8 344. Avec le bon nom présent, la
correspondance devient **exacte** et le score flou n'entre même pas en jeu.

Le cache compact, et pourquoi il existe
----------------------------------------

L'export brut fait 35 Mo par langue, avec du HTML de rendu autour de chaque nom.
L'analyser à chaque démarrage prendrait plusieurs secondes pour un résultat
constant. Le premier passage produit donc un cache compact `identifiant -> noms`,
et c'est lui qui est relu ensuite.
"""

from __future__ import annotations

import html
import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .. import paths
from .source import CatalogError, write_cache

_log = logging.getLogger(__name__)

BASE_URL = "https://bdocodex.com/query.php?a=items&l={lang}"

ALLOWED_HOSTS = frozenset({"bdocodex.com", "www.bdocodex.com"})

# bdocodex nomme l'anglais « us », comme veliainn : pas de table de
# correspondance à maintenir entre les deux.
LANGS = ("fr", "us")

TIMEOUTS = (10, 300)

# L'export fait environ 35 Mo par langue. 256 Mo laisse de la marge pour des
# années de contenu tout en restant très loin de ce qui saturerait un disque.
MAX_BYTES = 256 * 1024 * 1024

_CHUNK = 1024 * 1024

# En dessous, l'export est tronqué. Le vrai fichier contient près de 69 000
# objets ; 10 000 est un plancher qui n'exclut aucun cas réel.
MIN_ITEMS = 10_000

# Le nom utile est dans la troisième colonne, enveloppé de balises destinées au
# rendu du site. Le `<span></span>` vide n'apparaît pas toujours.
_NAME_RE = re.compile(r"<b>(?:<span[^>]*>\s*</span>)?(.*?)</b>", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def compact_path() -> Path:
    """Cache compact, celui que le programme relit au démarrage."""
    return paths.cache_dir() / "noms-bdocodex.json"


def raw_path(lang: str) -> Path:
    """Export brut d'une langue, gardé pour pouvoir régénérer sans réseau."""
    return paths.cache_dir() / f"bdocodex-items-{lang}.json"


def _check_host(url: str, *, stage: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise CatalogError(f"{stage} : schéma non https ({parsed.scheme!r})")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise CatalogError(f"{stage} : hôte non autorisé ({parsed.hostname!r})")


def download(lang: str, *, session: requests.Session | None = None) -> bytes:
    """Télécharge l'export d'une langue, avec les mêmes protections que le
    catalogue de marché : hôte en liste blanche revalidé après redirection,
    plafond sur les octets réellement lus, délais d'attente."""
    url = BASE_URL.format(lang=lang)
    _check_host(url, stage="URL demandée")
    http = session or requests.Session()
    try:
        response = http.get(
            url,
            timeout=TIMEOUTS,
            stream=True,
            headers={"User-Agent": "butin-bdo (+https://github.com/Maxyull/butin-bdo)"},
        )
        _check_host(response.url, stage="URL finale après redirection")
        response.raise_for_status()
        morceaux: list[bytes] = []
        total = 0
        for morceau in response.iter_content(chunk_size=_CHUNK):
            if not morceau:
                continue
            total += len(morceau)
            if total > MAX_BYTES:
                raise CatalogError(f"export {lang} trop volumineux : plus de {MAX_BYTES} octets")
            morceaux.append(morceau)
        return b"".join(morceaux)
    except requests.RequestException as exc:
        raise CatalogError(f"export bdocodex {lang} indisponible : {exc}") from exc
    finally:
        if session is None:
            http.close()


def extract(payload: bytes) -> dict[int, str]:
    """Extrait `identifiant -> nom` d'un export brut.

    Le nom arrive habillé de HTML de rendu. On le déshabille plutôt que de
    demander une autre forme : c'est le seul point d'entrée public, et ce
    balisage y est stable depuis longtemps.
    """
    try:
        brut = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"export bdocodex illisible : {exc}") from exc

    lignes = brut.get("aaData") if isinstance(brut, dict) else None
    if not isinstance(lignes, list):
        raise CatalogError("export bdocodex : champ « aaData » manquant ou mal formé")

    noms: dict[int, str] = {}
    for ligne in lignes:
        if not isinstance(ligne, list) or len(ligne) < 3:
            continue
        try:
            item_id = int(ligne[0])
        except (TypeError, ValueError):
            continue
        trouve = _NAME_RE.search(str(ligne[2]))
        if trouve is None:
            continue
        nom = html.unescape(_TAG_RE.sub("", trouve.group(1))).strip()
        if nom:
            noms[item_id] = nom

    if len(noms) < MIN_ITEMS:
        raise CatalogError(
            f"export bdocodex anormalement court ({len(noms)} noms, minimum {MIN_ITEMS})"
        )
    return noms


def build_compact(par_langue: dict[str, dict[int, str]]) -> dict[str, dict[str, str]]:
    """Fusionne les langues en `identifiant -> {locale: nom}`."""
    compact: dict[str, dict[str, str]] = {}
    for lang, noms in par_langue.items():
        for item_id, nom in noms.items():
            compact.setdefault(str(item_id), {})[lang] = nom
    return compact


def refresh(*, session: requests.Session | None = None) -> dict[str, dict[str, str]]:
    """Télécharge les deux langues et écrit le cache compact."""
    par_langue: dict[str, dict[int, str]] = {}
    for lang in LANGS:
        payload = download(lang, session=session)
        write_cache(payload, raw_path(lang))
        par_langue[lang] = extract(payload)

    compact = build_compact(par_langue)
    write_cache(json.dumps(compact, ensure_ascii=False).encode("utf-8"), compact_path())
    _log.info("bdocodex : %d objets mis en cache", len(compact))
    return compact


def load(
    *, allow_download: bool = True, session: requests.Session | None = None
) -> dict[str, dict[str, str]]:
    """Charge les noms bdocodex, depuis le cache compact si possible.

    Trois niveaux, du moins cher au plus cher : le cache compact, la
    reconstruction depuis les exports bruts déjà là, puis le réseau. Le niveau
    intermédiaire évite de retélécharger 70 Mo quand seul le format compact a
    changé.
    """
    chemin = compact_path()
    if chemin.exists():
        try:
            data = json.loads(chemin.read_text(encoding="utf-8"))
            if isinstance(data, dict) and len(data) >= MIN_ITEMS:
                return {k: v for k, v in data.items() if isinstance(v, dict)}
            _log.warning("cache compact bdocodex anormalement court, reconstruction")
        except (OSError, json.JSONDecodeError) as exc:
            _log.warning("cache compact bdocodex illisible (%s), reconstruction", exc)

    bruts = {lang: raw_path(lang) for lang in LANGS}
    if all(chemin_brut.exists() for chemin_brut in bruts.values()):
        try:
            par_langue = {
                lang: extract(chemin_brut.read_bytes()) for lang, chemin_brut in bruts.items()
            }
        except (CatalogError, OSError) as exc:
            _log.warning("exports bruts bdocodex inexploitables (%s)", exc)
        else:
            compact = build_compact(par_langue)
            write_cache(json.dumps(compact, ensure_ascii=False).encode("utf-8"), compact_path())
            return compact

    if not allow_download:
        raise CatalogError("aucun cache bdocodex et téléchargement désactivé")
    return refresh(session=session)


def to_catalog_payload(compact: dict[str, dict[str, str]]) -> dict[str, Any]:
    """Met les noms bdocodex à la forme attendue par `ItemCatalog.from_raw`.

    Passer par la même forme que le catalogue de marché évite un second chemin
    de construction, donc un second endroit où les règles d'indexation
    pourraient diverger sans qu'on le voie.
    """
    return {item_id: {"id": int(item_id), "locale_name": noms} for item_id, noms in compact.items()}
