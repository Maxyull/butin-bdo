"""Tests de la politique de version.

La politique complète est dans `docs/versionnage.md`. Ces tests figent ce qui
peut se casser en silence : deux numéros de version qui divergent, ou un numéro
qui cesse d'être valide au sens de PEP 440.
"""

from __future__ import annotations

import re
from importlib.metadata import version as installed_version

import pytest

import butin

# Sous-ensemble de PEP 440 que ce projet s'autorise : trois nombres, avec un
# suffixe facultatif de pré-version ou de développement. Volontairement plus
# strict que PEP 440, qui accepte aussi les versions époque (« 1!2.0 ») et les
# publications postérieures (« 1.0.post1 ») dont on n'a aucun usage et qui
# passeraient inaperçues si elles arrivaient par erreur.
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?(?:\.dev\d+)?$")


class TestCoherence:
    def test_le_paquet_et_les_metadonnees_declarent_la_meme_version(self) -> None:
        """Régression : deux sources de vérité qui divergent en silence.

        `pyproject.toml` alimente les métadonnées d'installation, et
        `butin.__version__` alimente `butin --version`. Rien ne les relie
        automatiquement. Si elles divergent, le logiciel annonce un numéro et
        le gestionnaire de paquets en connaît un autre, ce que personne ne
        remarque avant un rapport de bogue impossible à situer.
        """
        assert butin.__version__ == installed_version("butin")


class TestFormat:
    def test_la_version_respecte_le_format_retenu(self) -> None:
        assert _VERSION_RE.match(butin.__version__), (
            f"« {butin.__version__} » ne suit pas le format retenu, voir docs/versionnage.md"
        )

    @pytest.mark.parametrize(
        "valide", ["0.1.0", "0.1.0.dev0", "1.0.0", "1.2.3rc1", "2.0.0a1", "0.4.12.dev7"]
    )
    def test_formes_acceptees(self, valide: str) -> None:
        assert _VERSION_RE.match(valide)

    @pytest.mark.parametrize(
        "invalide",
        [
            "1.0",  # deux nombres seulement
            "v1.0.0",  # le « v » appartient à l'étiquette git, pas à la version
            "1.0.0-alpha.1",  # syntaxe Semantic Versioning, refusée par PEP 440
            "1.0.0.post1",  # publication postérieure, sans usage ici
            "1!2.0.0",  # version époque, sans usage ici
        ],
    )
    def test_formes_refusees(self, invalide: str) -> None:
        """Régression : la forme Semantic Versioning n'est PAS valide en Python.

        « 1.0.0-alpha.1 » est correct au sens de Semantic Versioning et refusé
        par PEP 440, qui écrit « 1.0.0a1 ». Écrire la première dans
        `pyproject.toml` casse l'installation. Les deux conventions coexistent
        dans ce projet, et c'est exactement le genre de détail qui se confond.
        """
        assert not _VERSION_RE.match(invalide)


class TestPhaseDeDeveloppement:
    def test_la_version_zero_ne_promet_aucune_stabilite(self) -> None:
        """Garde-fou : passer en 1.0.0 est une promesse, pas un incrément.

        Semantic Versioning donne un sens précis à la version majeure zéro :
        tout peut changer à tout moment. Franchir le 1.0.0 engage sur la
        compatibilité de la ligne de commande, du calibrage et de la base de
        sessions. Ce test échouera à ce moment-là, et c'est voulu : il oblige à
        relire les critères de `docs/versionnage.md` plutôt qu'à incrémenter
        machinalement.
        """
        majeur = int(butin.__version__.split(".")[0])
        assert majeur == 0, (
            "la version majeure a changé : vérifier que TOUS les critères de "
            "passage en 1.0.0 de docs/versionnage.md sont remplis, puis mettre "
            "ce test à jour en connaissance de cause"
        )
