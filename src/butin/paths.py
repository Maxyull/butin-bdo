"""Emplacements sur disque utilisés par Butin.

Tout ce que le programme écrit vit sous les dossiers standards de l'utilisateur
(via `platformdirs`), jamais à côté de l'exécutable ni dans le dossier du jeu.
Deux raisons :

1. Une installation dans « Program Files » n'est pas inscriptible par un compte
   non administrateur. Écrire la base de sessions à côté du binaire marcherait
   en développement puis échouerait chez l'utilisateur.
2. Butin ne doit jamais écrire dans le répertoire de Black Desert. Le jeu
   surveille son propre dossier, et un fichier inconnu déposé dedans est
   exactement le genre de chose qui ressemble à une modification du client.

Sous Windows, cela donne :
    cache   : %LOCALAPPDATA%\\Butin\\Cache
    données : %LOCALAPPDATA%\\Butin

`BUTIN_HOME` permet de tout rediriger, ce dont les tests se servent pour ne
jamais toucher aux vrais dossiers de l'utilisateur.
"""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_cache_path, user_data_path

APP_NAME = "Butin"

_ENV_HOME = "BUTIN_HOME"


def _override() -> Path | None:
    raw = os.environ.get(_ENV_HOME)
    return Path(raw) if raw else None


def data_dir() -> Path:
    """Dossier des données persistantes (base de sessions, configuration)."""
    root = _override()
    path = root / "data" if root else user_data_path(APP_NAME, appauthor=False)
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    """Dossier des données reconstructibles (catalogue, prix du marché).

    Tout ce qui est ici doit pouvoir être supprimé sans perte : le programme le
    retélécharge. Rien de ce que l'utilisateur a produit ne va dans ce dossier.
    """
    root = _override()
    path = root / "cache" if root else user_cache_path(APP_NAME, appauthor=False)
    path.mkdir(parents=True, exist_ok=True)
    return path


def catalog_path() -> Path:
    """Fichier du catalogue d'objets mis en cache."""
    return cache_dir() / "items.json"


def database_path() -> Path:
    """Base SQLite des sessions de farm."""
    return data_dir() / "sessions.sqlite3"
