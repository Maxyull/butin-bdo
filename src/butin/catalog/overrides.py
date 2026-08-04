"""Noms français vérifiés à la main, prioritaires sur le catalogue amont.

Le catalogue amont (`source.py`) couvre plusieurs milliers d'objets et c'est ce
qui rend Butin possible. Mais c'est une source unique, et une source unique ne
se contrôle pas elle-même : une faute de frappe, une traduction automatique ou
un décalage avec le client français en jeu ne se voient nulle part. Or un nom
faux dans le catalogue produit une non-reconnaissance permanente et silencieuse
de l'objet concerné, que l'utilisateur ne peut pas diagnostiquer depuis
l'interface.

Ce module apporte la contre-vérification. Chaque entrée porte le nom retenu,
les sites qui l'attestent, et la date du contrôle.

Règle de vérification, dans cet ordre :

1. **bdocodex** et **garmoth** servent de références. Ce sont les deux bases
   d'objets francophones les plus complètes et les plus suivies.
2. D'autres sites servent à confirmer quand les deux références divergent ou
   qu'une seule couvre l'objet.
3. Une entrée attestée par une seule source n'est pas considérée comme
   vérifiée. `audit_sources` les remonte, et un test de la suite échoue tant
   qu'il en reste, pour qu'un recoupement à moitié fait ne se fasse pas oublier.

Le fichier de données est volontairement séparé du code : le recoupement se
fait objet par objet, sur la durée, et ne doit demander aucune modification de
code pour être enrichi.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# Sites faisant autorité. Une entrée doit citer au moins l'un des deux.
REFERENCE_SOURCES = frozenset({"bdocodex", "garmoth"})

# Nombre minimal de sites distincts pour qu'un nom compte comme vérifié.
MIN_SOURCES = 2

SCHEMA_VERSION = 1


class OverrideError(ValueError):
    """Le fichier de noms vérifiés est mal formé."""


@dataclass(frozen=True, slots=True)
class VerifiedName:
    """Un nom français attesté par une ou plusieurs sources externes."""

    item_id: int
    name: str
    sources: tuple[str, ...]
    checked_on: date | None = None

    @property
    def is_verified(self) -> bool:
        """Vrai si le recoupement satisfait la règle de vérification."""
        return len(set(self.sources)) >= MIN_SOURCES and bool(REFERENCE_SOURCES & set(self.sources))


def parse(data: Mapping[str, Any]) -> dict[int, VerifiedName]:
    """Analyse le contenu du fichier de noms vérifiés.

    Strict par conception : ce fichier est écrit à la main, donc c'est
    exactement le genre de fichier où une virgule oubliée ou un identifiant
    saisi en texte passe inaperçue. Mieux vaut un échec net au démarrage qu'un
    nom silencieusement ignoré.
    """
    version = data.get("version")
    if version != SCHEMA_VERSION:
        raise OverrideError(f"version de schéma {version!r} non gérée (attendu {SCHEMA_VERSION})")

    items = data.get("items")
    if not isinstance(items, dict):
        raise OverrideError("champ « items » manquant ou n'est pas un objet")

    result: dict[int, VerifiedName] = {}
    for raw_id, entry in items.items():
        try:
            item_id = int(raw_id)
        except (TypeError, ValueError) as exc:
            raise OverrideError(f"identifiant d'objet non numérique : {raw_id!r}") from exc

        if not isinstance(entry, dict):
            raise OverrideError(f"objet {item_id} : entrée mal formée")

        name = entry.get("nom")
        if not isinstance(name, str) or not name.strip():
            raise OverrideError(f"objet {item_id} : champ « nom » manquant ou vide")

        sources = entry.get("sources")
        if not isinstance(sources, list) or not sources:
            raise OverrideError(f"objet {item_id} : champ « sources » manquant ou vide")
        if not all(isinstance(s, str) and s.strip() for s in sources):
            raise OverrideError(f"objet {item_id} : « sources » doit lister des chaînes")

        checked_on = _parse_date(entry.get("verifie_le"), item_id)

        result[item_id] = VerifiedName(
            item_id=item_id,
            name=name.strip(),
            sources=tuple(dict.fromkeys(s.strip() for s in sources)),
            checked_on=checked_on,
        )
    return result


def _parse_date(value: Any, item_id: int) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise OverrideError(f"objet {item_id} : « verifie_le » doit être une date ISO")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise OverrideError(
            f"objet {item_id} : date « {value} » illisible, format attendu AAAA-MM-JJ"
        ) from exc


def load(path: Path) -> dict[int, VerifiedName]:
    """Charge le fichier de noms vérifiés.

    Un fichier absent est normal (aucun recoupement fait encore) et renvoie un
    dictionnaire vide. Un fichier présent mais illisible est une erreur : il a
    été écrit intentionnellement, l'ignorer masquerait le travail de
    vérification déjà accompli.
    """
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OverrideError(f"fichier de noms vérifiés illisible ({path}) : {exc}") from exc
    return parse(raw)


def audit_sources(overrides: Mapping[int, VerifiedName]) -> list[VerifiedName]:
    """Renvoie les entrées qui ne satisfont pas la règle de vérification.

    Utilisé par la suite de tests pour empêcher qu'un recoupement commencé et
    non terminé finisse par être pris pour un fait acquis.
    """
    return [entry for entry in overrides.values() if not entry.is_verified]


def default_path() -> Path:
    """Emplacement du fichier de noms vérifiés livré avec le projet."""
    return Path(__file__).resolve().parents[3] / "data" / "noms-verifies.json"
