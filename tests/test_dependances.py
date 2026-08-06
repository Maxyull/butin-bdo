"""Tests de l'épinglage des dépendances installées depuis git.

`bdo-ocr-core` ne vit pas sur PyPI mais sur GitHub, donc il arrive par une URL
git. Une URL git désigne une **révision**, et toutes les révisions ne se valent
pas : une branche bouge à chaque poussée, une étiquette peut être déplacée
(`git tag -f` puis `push -f`), seul un SHA de commit est immuable.

Ce fichier fige la règle. Elle n'est vérifiée par rien d'autre : ni ruff, ni
mypy, ni la suite d'intégration ne lisent `pyproject.toml`, et `pip` installe
sans broncher ce qu'on lui donne.

Le raisonnement est le même que pour `tests/test_workflows.py`, qui impose déjà
le SHA aux actions GitHub. Un dépôt qui exige l'immuabilité de ses outils et
l'accorde à son propre code se contredit.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

# `"nom @ git+https://…@revision",  # commentaire`
_GIT_DEP_RE = re.compile(
    r'^\s*"(?P<nom>[^"@\s]+)\s*@\s*(?P<url>git\+[^"@\s]+)@(?P<revision>[^"\s]+)"\s*,'
    r"(?:\s*#\s*(?P<version>\S+))?"
)
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _dependances_git() -> list[tuple[int, str, str, str, str | None]]:
    """Toutes les dépendances en URL git de `pyproject.toml`, ligne comprise."""
    trouvees: list[tuple[int, str, str, str, str | None]] = []
    for numero, ligne in enumerate(_PYPROJECT.read_text(encoding="utf-8").splitlines(), 1):
        correspondance = _GIT_DEP_RE.match(ligne)
        if correspondance is not None:
            trouvees.append(
                (
                    numero,
                    correspondance["nom"],
                    correspondance["url"],
                    correspondance["revision"],
                    correspondance["version"],
                )
            )
    return trouvees


DEPENDANCES_GIT = _dependances_git()


def test_la_lecture_du_pyproject_trouve_bien_les_dependances_git() -> None:
    """Garde-fou sur le test lui-même : une regex qui ne trouve rien passe.

    Sans ça, un simple reformatage de `pyproject.toml` viderait silencieusement
    tous les autres tests de ce fichier, qui resteraient au vert en ne
    vérifiant plus rien. Le projet en compte au moins une, `bdo-ocr-core`.
    """
    noms = {nom for _, nom, _, _, _ in DEPENDANCES_GIT}
    assert "bdo-ocr-core" in noms, (
        f"aucune dépendance git reconnue dans {_PYPROJECT.name} : "
        "la regex ne correspond plus au format du fichier"
    )


@pytest.mark.parametrize(
    ("ligne", "nom", "url", "revision", "version"),
    DEPENDANCES_GIT,
    ids=[nom for _, nom, _, _, _ in DEPENDANCES_GIT],
)
def test_chaque_dependance_git_est_epinglee_sur_un_sha(
    ligne: int, nom: str, url: str, revision: str, version: str | None
) -> None:
    """Régression : une étiquette dit ce qu'on voulait, pas ce qu'on obtient.

    `bdo-ocr-core` a d'abord été épinglé sur `@v0.1.0` (PR #58). Le README du
    socle justifiait « étiquette plutôt que branche », ce qui est juste mais
    incomplet : une étiquette git reste déplaçable. Le code réellement installé
    pouvait donc changer sans qu'aucune ligne d'ici ne bouge, et sans que rien
    ne le signale — le mode de défaillance silencieux que ce projet refuse.

    Tranché le 06/08/2026 par Maxime : SHA partout.
    """
    assert _SHA_RE.match(revision), (
        f"{_PYPROJECT.name}:{ligne} — « {nom} » est épinglé sur « {revision} », "
        "qui n'est pas un SHA de commit sur 40 caractères. Une branche bouge à "
        "chaque poussée, une étiquette peut être déplacée. Déréférencer "
        "l'étiquette jusqu'au commit et épingler dessus."
    )


@pytest.mark.parametrize(
    ("ligne", "nom", "url", "revision", "version"),
    DEPENDANCES_GIT,
    ids=[nom for _, nom, _, _, _ in DEPENDANCES_GIT],
)
def test_chaque_dependance_git_annonce_sa_version_en_commentaire(
    ligne: int, nom: str, url: str, revision: str, version: str | None
) -> None:
    """Un SHA nu est illisible : personne ne sait quelle version est installée.

    Même exigence que pour les actions GitHub, et pour la même raison : le SHA
    garantit ce qui s'exécute, le commentaire dit ce que c'est. Il faut les
    deux, l'immuabilité ne doit pas se payer en lisibilité.
    """
    assert version is not None, (
        f"{_PYPROJECT.name}:{ligne} — « {nom} » est épinglé sur un SHA sans "
        "commentaire de version. Ajouter « # vX.Y.Z » en fin de ligne."
    )
    assert re.match(r"^v\d", version), (
        f"{_PYPROJECT.name}:{ligne} — le commentaire « {version} » ne ressemble pas à une version."
    )


@pytest.mark.parametrize(
    ("ligne", "nom", "url", "revision", "version"),
    DEPENDANCES_GIT,
    ids=[nom for _, nom, _, _, _ in DEPENDANCES_GIT],
)
def test_chaque_dependance_git_passe_par_https(
    ligne: int, nom: str, url: str, revision: str, version: str | None
) -> None:
    """`git+ssh` ou `git+git` casserait l'intégration continue et les tiers.

    L'intégration continue n'a pas de clé SSH, et le dépôt est public : un
    contributeur doit pouvoir installer sans compte GitHub configuré.
    """
    assert url.startswith("git+https://"), (
        f"{_PYPROJECT.name}:{ligne} — « {nom} » est tiré depuis « {url} », "
        "qui n'est pas du HTTPS anonyme."
    )
