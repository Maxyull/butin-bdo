"""Fixtures partagées.

Les noms utilisés dans les tests sont de VRAIS noms français extraits du
catalogue amont, avec leurs vrais identifiants. Un jeu de test inventé
passerait à côté des cas qui cassent réellement : la ligature de « Nœud », le
couple « tranchant » / « dur » qui ne diffère que par un mot, les cinq objets
qui partagent le nom « Jeune dragon écarlate ».
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from butin.catalog import ItemCatalog, ItemMatcher
from butin.catalog.models import Item

# Extrait réel du catalogue. Identifiants et libellés vérifiés le 2026-08-04
# contre data/items.json de veliainn-market-resources.
REAL_ITEMS: tuple[tuple[int, str, str], ...] = (
    (16001, "Pierre noire (arme)", "Black Stone (Weapon)"),
    (16002, "Pierre noire (armure)", "Black Stone (Armor)"),
    (4998, "Éclat de cristal noir tranchant", "Sharp Black Crystal Shard"),
    (4997, "Éclat de cristal noir dur", "Hard Black Crystal Shard"),
    (721003, "Pierre de Caphras", "Caphras Stone"),
    (5956, "Trace de sauvagerie", "Trace of Savagery"),
    (44195, "Fragment de mémoire", "Memory Fragment"),
    (5005, "Nœud d'arbre ensanglanté", "Bloody Tree Knot"),
    (9771, "Cœur transmuté de Garmoth", "Inverted Heart of Garmoth"),
    (10010, "Épée longue de Kzarka", "Kzarka Longsword"),
    (586, "Potion d'énergie (petite)", "Energy Potion (Small)"),
)

# Cinq identifiants réels partageant exactement le même nom français.
DRAGON_IDS: tuple[int, ...] = (18480, 18482, 18483, 18484, 18485)
DRAGON_NAME = "Jeune dragon écarlate"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirige tous les chemins de l'application vers un dossier jetable.

    Automatique, pour qu'aucun test ne puisse écrire dans le vrai
    %LOCALAPPDATA% de la personne qui lance la suite, même par accident dans un
    test futur qui oublierait de le demander.
    """
    monkeypatch.setenv("BUTIN_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def raw_catalog() -> dict[str, dict[str, object]]:
    """Catalogue au format brut de la source amont."""
    data: dict[str, dict[str, object]] = {}
    for item_id, name_fr, name_en in REAL_ITEMS:
        data[str(item_id)] = {
            "id": item_id,
            "locale_default": "us",
            "locale_name": {"us": name_en, "fr": name_fr},
            "grade": 0,
            "category_primary": 1,
            "category_secondary": 1,
        }
    for item_id in DRAGON_IDS:
        data[str(item_id)] = {
            "id": item_id,
            "locale_default": "us",
            "locale_name": {"us": "Juvenile Scarlet Dragon", "fr": DRAGON_NAME},
            "grade": 0,
            "category_primary": 1,
            "category_secondary": 1,
        }
    return data


@pytest.fixture
def catalog(raw_catalog: dict[str, dict[str, object]]) -> ItemCatalog:
    return ItemCatalog.from_raw(raw_catalog)


@pytest.fixture
def matcher(catalog: ItemCatalog) -> ItemMatcher:
    return ItemMatcher(catalog)


@pytest.fixture
def item_factory():
    def make(item_id: int, name_fr: str, name_en: str = "") -> Item:
        return Item(item_id=item_id, names={"fr": name_fr, "us": name_en or name_fr})

    return make


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fait échouer bruyamment tout accès réseau involontaire.

    Un test qui télécharge vraiment le catalogue serait lent, dépendrait
    d'internet, et masquerait le fait que le cache ne fonctionne pas.
    """
    import requests

    def refuse(*args: object, **kwargs: object):
        raise AssertionError("accès réseau interdit dans les tests")

    monkeypatch.setattr(requests.Session, "get", refuse)
    monkeypatch.setattr(requests, "get", refuse)
    assert os.environ.get("BUTIN_HOME"), "isolated_home doit être actif"
