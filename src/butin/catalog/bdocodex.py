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

_GRADE_RE = re.compile(r"item_grade_(\d)")
"""Rareté de l'objet, lue dans la classe de rendu de bdocodex.

C'est le code couleur du jeu lui-même : blanc, vert, bleu, jaune, orange. La
classe et la sixième colonne de l'export portent la même valeur, vérifié sur
8 000 lignes sans un seul désaccord ; la classe est retenue parce qu'elle est
nommée, là où un indice de colonne se décale en silence le jour où l'export
gagne un champ.
"""

_ICON_RE = re.compile(r'src="(/items/[^"]+?\.webp)"')
"""Chemin de l'image de l'objet, dans la deuxième colonne de l'export.

⚠️ La balise y est écrite `[img src="…"` et non `<img`, ce qui n'a l'air de rien
mais interdit de chercher `<img`. On vise donc l'attribut, pas la balise.
Mesuré sur l'export du 05/08/2026 : **68 747 icônes sur 68 747 objets**."""

COMPACT_NAMES = "n"
COMPACT_GRADE = "g"
COMPACT_ICON = "i"
"""Clés du cache compact. Courtes parce que le fichier contient 68 000 entrées
et qu'il est relu à chaque démarrage."""


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


def _rows(payload: bytes) -> list[Any]:
    """Lignes de l'export, ou une erreur qui dit ce qui manque.

    Mis en commun entre les noms et les raretés : deux copies de cette
    validation divergeraient le jour où bdocodex changera d'enveloppe, et l'une
    des deux accepterait alors ce que l'autre refuse.
    """
    try:
        brut = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"export bdocodex illisible : {exc}") from exc

    lignes = brut.get("aaData") if isinstance(brut, dict) else None
    if not isinstance(lignes, list):
        raise CatalogError("export bdocodex : champ « aaData » manquant ou mal formé")
    return lignes


def extract(payload: bytes) -> dict[int, str]:
    """Extrait `identifiant -> nom` d'un export brut.

    Le nom arrive habillé de HTML de rendu. On le déshabille plutôt que de
    demander une autre forme : c'est le seul point d'entrée public, et ce
    balisage y est stable depuis longtemps.
    """
    lignes = _rows(payload)
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


def extract_grades(payload: bytes) -> dict[int, int]:
    """Extrait `identifiant -> rareté` d'un export brut.

    Séparé de `extract` parce que ce n'est pas la même question, et surtout
    parce que la rareté **ne dépend pas de la langue** : une seule des deux
    langues téléchargées suffit à la relever, là où les noms demandent les deux.

    Une ligne sans classe de rareté est ignorée plutôt que comptée zéro : zéro
    est une vraie rareté, celle des objets communs, et la confondre avec
    « inconnu » afficherait en blanc des objets dont on ne sait rien.
    """
    lignes = _rows(payload)
    grades: dict[int, int] = {}
    for ligne in lignes:
        if not isinstance(ligne, list) or len(ligne) < 3:
            continue
        try:
            item_id = int(ligne[0])
        except (TypeError, ValueError):
            continue
        trouve = _GRADE_RE.search(str(ligne[2]))
        if trouve is not None:
            grades[item_id] = int(trouve.group(1))
    return grades


def extract_icons(payload: bytes) -> dict[int, str]:
    """Extrait `identifiant -> chemin de l'image` d'un export brut.

    Comme la rareté, l'image **ne dépend pas de la langue** : une seule des deux
    langues téléchargées suffit à la relever.

    Un objet sans image est simplement absent du résultat, pas présent avec une
    chaîne vide : l'affichage sait se passer d'une icône, et prétendre en
    connaître une qui n'existe pas ferait tenter un téléchargement voué à
    échouer à chaque drop de cet objet.
    """
    icones: dict[int, str] = {}
    for ligne in _rows(payload):
        if not isinstance(ligne, list) or len(ligne) < 2:
            continue
        try:
            item_id = int(ligne[0])
        except (TypeError, ValueError):
            continue
        trouve = _ICON_RE.search(str(ligne[1]))
        if trouve is not None:
            icones[item_id] = trouve.group(1)
    return icones


def build_compact(
    par_langue: dict[str, dict[int, str]],
    grades: dict[int, int] | None = None,
    icones: dict[int, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Fusionne les langues et les raretés en `identifiant -> {noms, rareté}`.

    ⚠️ Le format a changé : les noms sont désormais sous une clé au lieu d'être
    à la racine. Un cache écrit par la version précédente est donc rejeté par
    `load`, qui le reconstruit **depuis les exports bruts déjà sur le disque**,
    sans retélécharger 70 Mo. C'est exactement ce pour quoi ce niveau
    intermédiaire existe.
    """
    grades = grades or {}
    icones = icones or {}
    compact: dict[str, dict[str, Any]] = {}
    for lang, noms in par_langue.items():
        for item_id, nom in noms.items():
            entree = compact.setdefault(str(item_id), {COMPACT_NAMES: {}})
            entree[COMPACT_NAMES][lang] = nom
    for item_id, grade in grades.items():
        connue = compact.get(str(item_id))
        if connue is not None:
            connue[COMPACT_GRADE] = grade
    for item_id, icone in icones.items():
        connue = compact.get(str(item_id))
        if connue is not None:
            connue[COMPACT_ICON] = icone
    return compact


def refresh(*, session: requests.Session | None = None) -> dict[str, dict[str, Any]]:
    """Télécharge les deux langues et écrit le cache compact."""
    par_langue: dict[str, dict[int, str]] = {}
    grades: dict[int, int] = {}
    icones: dict[int, str] = {}
    for lang in LANGS:
        payload = download(lang, session=session)
        write_cache(payload, raw_path(lang))
        par_langue[lang] = extract(payload)
        if not grades:
            # Ni la rareté ni l'image ne dépendent de la langue : les relever
            # une fois suffit.
            grades = extract_grades(payload)
            icones = extract_icons(payload)

    compact = build_compact(par_langue, grades, icones)
    write_cache(json.dumps(compact, ensure_ascii=False).encode("utf-8"), compact_path())
    _log.info("bdocodex : %d objets mis en cache", len(compact))
    return compact


_ECHANTILLON_FORMAT = 50
"""Entrées inspectées pour reconnaître le format du cache.

Une seule ne suffit pas : depuis que l'image en fait partie, un objet exotique
tombé en tête du fichier ferait reconstruire 70 Mo à **chaque lancement**. Un
échantillon distingue « format d'avant, aucune image » de « format courant, une
image manquante », qui est le cas normal.
"""


def _compact_valide(data: object) -> bool:
    """Vrai si le cache est au format courant : noms, et images.

    Un cache d'une version antérieure mettait les noms à la racine, puis n'avait
    pas les images. Le reconnaître explicitement vaut mieux que de le charger à
    moitié : les objets s'afficheraient sans nom ou sans image, ce qui ressemble
    à un défaut de catalogue alors que c'est un format périmé qu'une
    reconstruction depuis les exports bruts règle toute seule, sans réseau.
    """
    if not isinstance(data, dict) or len(data) < MIN_ITEMS:
        return False
    echantillon = [
        entree
        for _, entree in zip(range(_ECHANTILLON_FORMAT), data.values(), strict=False)
        if isinstance(entree, dict)
    ]
    if not echantillon:
        return False
    return all(COMPACT_NAMES in entree for entree in echantillon) and any(
        COMPACT_ICON in entree for entree in echantillon
    )


def load(
    *, allow_download: bool = True, session: requests.Session | None = None
) -> dict[str, dict[str, Any]]:
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
            if _compact_valide(data):
                return {k: v for k, v in data.items() if isinstance(v, dict)}
            _log.warning("cache compact bdocodex périmé ou trop court, reconstruction")
        except (OSError, json.JSONDecodeError) as exc:
            _log.warning("cache compact bdocodex illisible (%s), reconstruction", exc)

    bruts = {lang: raw_path(lang) for lang in LANGS}
    if all(chemin_brut.exists() for chemin_brut in bruts.values()):
        try:
            octets = {lang: chemin_brut.read_bytes() for lang, chemin_brut in bruts.items()}
            par_langue = {lang: extract(brut) for lang, brut in octets.items()}
            premier = next(iter(octets.values()))
            grades = extract_grades(premier)
            icones = extract_icons(premier)
        except (CatalogError, OSError, StopIteration) as exc:
            _log.warning("exports bruts bdocodex inexploitables (%s)", exc)
        else:
            compact = build_compact(par_langue, grades, icones)
            write_cache(json.dumps(compact, ensure_ascii=False).encode("utf-8"), compact_path())
            return compact

    if not allow_download:
        raise CatalogError("aucun cache bdocodex et téléchargement désactivé")
    return refresh(session=session)


def to_catalog_payload(compact: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Met les noms bdocodex à la forme attendue par `ItemCatalog.from_raw`.

    Passer par la même forme que le catalogue de marché évite un second chemin
    de construction, donc un second endroit où les règles d'indexation
    pourraient diverger sans qu'on le voie.
    """
    return {
        item_id: {
            "id": int(item_id),
            "locale_name": entree.get(COMPACT_NAMES, {}),
            "grade": entree.get(COMPACT_GRADE, 0),
            "icon": entree.get(COMPACT_ICON, ""),
        }
        for item_id, entree in compact.items()
    }
