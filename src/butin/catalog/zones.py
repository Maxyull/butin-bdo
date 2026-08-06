"""Reconnaissance du spot de farm à partir du butin qui tombe.

L'idée, et pourquoi ce n'est PAS un périmètre de reconnaissance
----------------------------------------------------------------

`data/butin-connu.json` associe une centaine d'objets à leur zone de farm. La
tentation évidente est d'en faire un `Scope` (`catalog/matcher.py`) pour
restreindre les candidats du score flou au spot en cours.

**C'est une mauvaise idée, et la mesure le montre :** 102 objets répartis sur
94 zones, donc environ **un seul objet par zone**. Un périmètre à un candidat
ne restreint rien, il force : une lecture abîmée de n'importe quel autre objet
se collerait sur l'unique candidat dès qu'elle atteint le seuil.

Ce serait exactement recréer l'attribution fausse qu'on vient de supprimer en
branchant bdocodex, mais par un autre chemin. Un périmètre n'a de sens que
rempli d'une liste de drops réellement complète, ce que ces données ne sont
pas.

Ce à quoi ces données servent vraiment
---------------------------------------

Ces objets ne sont pas une liste de drops, ce sont des **indicateurs**. Le trash
loot est propre à son spot : voir tomber des « Chaînes brisées » veut dire qu'on
est à la mine de fer abandonnée, et nulle part ailleurs.

Ça permet de **remplir tout seul le nom du spot d'une session**, que
l'utilisateur devrait sinon saisir à la main à chaque fois, donc oublier.

L'ambiguïté est traitée explicitement
--------------------------------------

Un même objet peut tomber dans plusieurs zones. Dans ce cas on ne devine pas :
on rend l'ensemble des zones possibles et l'appelant décide. Choisir au hasard
étiquetterait des sessions avec un spot faux, et une étiquette fausse est pire
qu'une étiquette absente, puisqu'elle se compare ensuite à d'autres sessions.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path

from .. import paths

_log = logging.getLogger(__name__)


def default_path() -> Path:
    """Fichier de butin connu livré avec le projet.

    Voir `paths.bundled_data_dir` : ce n'est pas un `Path(__file__)` codé en
    dur, parce que ce calcul se casse silencieusement dans une application
    figée par PyInstaller.
    """
    return paths.bundled_data_dir() / "butin-connu.json"


def load_zones(path: Path | None = None) -> dict[int, tuple[str, ...]]:
    """Charge `identifiant -> zones où cet objet tombe`.

    Un fichier absent renvoie un dictionnaire vide : la détection de spot est un
    confort, pas une condition de fonctionnement.
    """
    chemin = path or default_path()
    if not chemin.exists():
        return {}
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _log.warning("butin connu illisible (%s), détection de spot désactivée", exc)
        return {}

    par_objet: dict[int, list[str]] = {}
    for cle, fiche in (brut.get("items") or {}).items():
        if not isinstance(fiche, dict):
            continue
        zone = fiche.get("zone_en")
        if not isinstance(zone, str) or not zone:
            continue
        try:
            item_id = int(cle)
        except (TypeError, ValueError):
            continue
        par_objet.setdefault(item_id, []).append(zone)

    return {item_id: tuple(sorted(set(zones))) for item_id, zones in par_objet.items()}


def known_loot_ids(path: Path | None = None) -> tuple[int, ...]:
    """Identifiants de TOUT le butin connu, zone renseignée ou non.

    Distinct de `load_zones`, qui ne garde que les objets rattachés à une zone
    parce que c'est ce que la détection de spot demande. Ici on veut la liste
    complète : un objet sans zone tombe quand même, et son image sera quand même
    affichée.

    Un fichier absent rend un tuple vide, comme ailleurs : rien de ce qui
    dépend de ce fichier n'est une condition de fonctionnement.
    """
    chemin = path or default_path()
    if not chemin.exists():
        return ()
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _log.warning("butin connu illisible (%s)", exc)
        return ()

    identifiants: list[int] = []
    for cle in brut.get("items") or {}:
        try:
            identifiants.append(int(cle))
        except (TypeError, ValueError):
            continue
    return tuple(sorted(set(identifiants)))


def zones_for(item_ids: Iterable[int], zones: dict[int, tuple[str, ...]]) -> dict[str, int]:
    """Compte, pour chaque zone, combien d'objets observés la désignent."""
    scores: dict[str, int] = {}
    for item_id in item_ids:
        for zone in zones.get(item_id, ()):
            scores[zone] = scores.get(zone, 0) + 1
    return scores


def detect_spot(
    item_ids: Iterable[int], zones: dict[int, tuple[str, ...]] | None = None
) -> str | None:
    """Devine le spot de farm, ou renvoie None si ce n'est pas net.

    Renvoie None dans deux cas, et c'est voulu dans les deux :

    * aucun objet observé n'est un indicateur de zone ;
    * **deux zones sont à égalité.** Trancher au hasard étiquetterait la session
      avec un spot faux, et une étiquette fausse est pire qu'une étiquette
      absente puisqu'elle sera comparée à d'autres sessions ensuite.
    """
    table = load_zones() if zones is None else zones
    scores = zones_for(item_ids, table)
    if not scores:
        return None

    meilleur = max(scores.values())
    candidats = [zone for zone, score in scores.items() if score == meilleur]
    if len(candidats) > 1:
        _log.debug("spot indéterminé, %d zones à égalité : %s", len(candidats), candidats)
        return None
    return candidats[0]


def known_zones(zones: dict[int, tuple[str, ...]] | None = None) -> tuple[str, ...]:
    """Toutes les zones connues, triées. Sert à peupler un choix dans l'interface."""
    table = load_zones() if zones is None else zones
    return tuple(sorted({zone for liste in table.values() for zone in liste}))


def load_zone_translations(path: Path | None = None) -> dict[str, str]:
    """Charge `zone anglaise -> zone française`, pour traduire ce que
    `detect_spot` rend avant de nommer une session.

    Séparée de `load_zones()` plutôt que fusionnée : `load_zones()` reste la
    clé de regroupement interne (zone_en, invariante), traduite seulement au
    moment d'être montrée à l'utilisateur. Mélanger les deux forcerait à
    retoucher `detect_spot`, `zones_for` et leurs tests, qui n'ont aucune
    raison de connaître une langue.

    Une zone sans traduction connue est absente du résultat plutôt que
    mappée sur elle-même : à l'appelant de décider du repli (garder
    l'anglais plutôt que de planter est le bon choix pour un confort, pas
    une condition de fonctionnement — voir `load_zones`).
    """
    chemin = path or default_path()
    if not chemin.exists():
        return {}
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _log.warning("butin connu illisible (%s), traduction de zone désactivée", exc)
        return {}

    traductions: dict[str, str] = {}
    for fiche in (brut.get("items") or {}).values():
        if not isinstance(fiche, dict):
            continue
        zone_en = fiche.get("zone_en")
        zone_fr = fiche.get("zone_fr")
        if isinstance(zone_en, str) and zone_en and isinstance(zone_fr, str) and zone_fr:
            traductions[zone_en] = zone_fr

    return traductions
