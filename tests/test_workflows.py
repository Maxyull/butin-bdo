"""Tests de l'épinglage des actions GitHub dans les workflows d'intégration.

Ce dépôt est public : les workflows tournent sur du code proposé de
l'extérieur, et une action référencée par une étiquette mobile (`@v4`) exécute
ce que son auteur y met le jour où il le remet. Tout est donc épinglé sur un
SHA de commit, avec la version écrite en commentaire pour rester relisible.

Ces tests figent l'invariant, qui n'est vérifié par rien d'autre : ni ruff, ni
mypy, ni la suite d'intégration ne lisent ces fichiers.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import pytest

_WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"

# `uses: proprietaire/action@ref  # commentaire`, le sous-chemin d'une action
# composite compris (`github/codeql-action/init`).
_USES_RE = re.compile(
    r"^\s*(?:-\s*)?uses:\s*(?P<action>[^@\s]+)@(?P<ref>\S+)(?:\s*#\s*(?P<version>\S+))?\s*$"
)
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _references() -> list[tuple[Path, int, str, str, str | None]]:
    """Toutes les références d'action des workflows, fichier et ligne compris."""
    trouvees: list[tuple[Path, int, str, str, str | None]] = []
    for fichier in sorted(_WORKFLOWS.glob("*.yml")):
        for numero, ligne in enumerate(fichier.read_text(encoding="utf-8").splitlines(), 1):
            correspondance = _USES_RE.match(ligne)
            if correspondance is not None:
                trouvees.append(
                    (
                        fichier,
                        numero,
                        correspondance["action"],
                        correspondance["ref"],
                        correspondance["version"],
                    )
                )
    return trouvees


REFERENCES = _references()


def test_les_workflows_referencent_bien_des_actions() -> None:
    """Garde-fou sur le test lui-même : une regex qui ne trouve rien passe.

    Sans ça, une évolution du format des workflows viderait silencieusement
    tous les autres tests de ce fichier, qui continueraient de passer au vert
    en ne vérifiant plus rien.
    """
    assert len(REFERENCES) >= 4


@pytest.mark.parametrize(
    ("fichier", "ligne", "action", "ref", "version"),
    REFERENCES,
    ids=[f"{f.name}:{n}" for f, n, _, _, _ in REFERENCES],
)
def test_chaque_action_est_epinglee_sur_un_sha(
    fichier: Path, ligne: int, action: str, ref: str, version: str | None
) -> None:
    """Une étiquette mobile laisse l'auteur de l'action changer ce qui s'exécute."""
    assert _SHA_RE.match(ref), (
        f"{fichier.name}:{ligne} — « {action}@{ref} » n'est pas un SHA de commit. "
        "Épingler sur le SHA, jamais sur une étiquette."
    )


@pytest.mark.parametrize(
    ("fichier", "ligne", "action", "ref", "version"),
    REFERENCES,
    ids=[f"{f.name}:{n}" for f, n, _, _, _ in REFERENCES],
)
def test_chaque_epinglage_porte_sa_version_en_commentaire(
    fichier: Path, ligne: int, action: str, ref: str, version: str | None
) -> None:
    """Un SHA nu est illisible : personne ne sait quelle version tourne."""
    assert version is not None, (
        f"{fichier.name}:{ligne} — « {action}@{ref} » n'a pas de commentaire de version."
    )
    assert re.match(r"^v\d", version), (
        f"{fichier.name}:{ligne} — le commentaire « {version} » ne ressemble pas à une version."
    )


class TestCoherenceEntreFichiers:
    """La même action apparaît dans plusieurs workflows, jamais dans deux états."""

    def test_une_action_n_a_qu_un_seul_sha(self) -> None:
        """Régression : une mise à jour appliquée à un fichier sur quatre.

        `actions/checkout` est référencé dans `ci.yml` (deux fois), `codeql.yml`
        et `gitleaks.yml`. Le 06/08/2026, quatre PR dependabot séparées
        proposaient chacune la montée d'une action ; en fusionner une partie
        seulement, ou retoucher un seul fichier à la main, laisse le dépôt avec
        deux versions de la même action selon le workflow. Rien ne le signale :
        les deux tournent, simplement pas le même code.
        """
        par_action: dict[str, set[str]] = defaultdict(set)
        for _, _, action, ref, _ in REFERENCES:
            par_action[action.split("/")[0] + "/" + action.split("/")[1]].add(ref)
        divergentes = {a: shas for a, shas in par_action.items() if len(shas) > 1}
        assert not divergentes, f"actions épinglées sur plusieurs SHA : {divergentes}"

    def test_un_sha_porte_toujours_le_meme_commentaire(self) -> None:
        """Régression : le SHA monte, le commentaire reste en arrière.

        Le 06/08/2026, les diffs proposés par dependabot remplaçaient le SHA de
        `actions/checkout` par celui de la v7.0.1 en **conservant** le
        commentaire « # v4 » d'origine, et de même « # v3 » sur un SHA de
        codeql-action v4.37.4. Fusionné tel quel, le fichier aurait annoncé une
        version et exécuté l'autre — un commentaire faux est pire qu'un
        commentaire absent, parce qu'on s'y fie.
        """
        par_sha: dict[str, set[str]] = defaultdict(set)
        for _, _, _, ref, version in REFERENCES:
            if version is not None:
                par_sha[ref].add(version)
        incoherents = {sha: v for sha, v in par_sha.items() if len(v) > 1}
        assert not incoherents, f"un même SHA porte plusieurs versions annoncées : {incoherents}"
