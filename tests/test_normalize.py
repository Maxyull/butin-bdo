"""Tests de la normalisation française.

Chaque cas correspond à une déformation que l'OCR produit réellement sur le
client français, pas à une variation théorique.
"""

from __future__ import annotations

import pytest

from butin.catalog.normalize import (
    fold,
    fold_digits,
    is_meaningful,
    strip_accents,
)


class TestStripAccents:
    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("Épée longue de Kzarka", "Epee longue de Kzarka"),
            ("Éclat de cristal noir tranchant", "Eclat de cristal noir tranchant"),
            ("Trace de sauvagerie", "Trace de sauvagerie"),
            ("Potion d'énergie", "Potion d'energie"),
            ("à â ä è é ê ë î ï ô ö ù û ü ÿ ç", "a a a e e e e i i o o u u u y c"),
        ],
    )
    def test_retire_les_diacritiques(self, source: str, expected: str) -> None:
        assert strip_accents(source) == expected

    def test_deplie_la_ligature_oe(self) -> None:
        """Régression : « Nœud d'arbre ensanglanté » est un vrai drop.

        NFKD ne décompose pas « œ », qui est une lettre à part entière en
        Unicode. Sans dépliage explicite, ce nom et tous ceux contenant « œ »
        (« Cœur transmuté de Garmoth », « Peau de bœuf ») sont structurellement
        impossibles à reconnaître, quel que soit le seuil du score flou.
        """
        assert strip_accents("Nœud d'arbre ensanglanté") == "Noeud d'arbre ensanglante"
        assert strip_accents("Cœur transmuté de Garmoth") == "Coeur transmute de Garmoth"
        assert strip_accents("Œuf") == "OEuf"

    def test_deplie_la_ligature_ae(self) -> None:
        assert strip_accents("Cæsar") == "Caesar"


class TestFold:
    def test_forme_canonique_complete(self) -> None:
        assert fold("Épée longue de Kzarka") == "epee longue de kzarka"

    @pytest.mark.parametrize(
        "variante",
        [
            "Potion d'énergie",
            "Potion d’énergie",  # apostrophe typographique U+2019
            "Potion d‘énergie",  # guillemet simple ouvrant U+2018
            "Potion d`énergie",  # accent grave
            "Potion d´énergie",  # accent aigu isolé
        ],
    )
    def test_toutes_les_apostrophes_convergent(self, variante: str) -> None:
        """Régression : l'OCR alterne entre cinq glyphes pour la même apostrophe.

        Chacun donnerait une chaîne différente, donc quatre échecs de
        correspondance sur cinq lectures du même objet.
        """
        assert fold(variante) == "potion denergie"

    @pytest.mark.parametrize(
        "variante",
        ["Cristal noir-tranchant", "Cristal noir–tranchant", "Cristal noir—tranchant"],
    )
    def test_les_tirets_deviennent_des_espaces(self, variante: str) -> None:
        assert fold(variante) == "cristal noir tranchant"

    def test_le_tiret_ne_colle_pas_les_mots(self) -> None:
        """Régression : l'ordre des opérations dans fold() est significatif.

        Supprimer la ponctuation avant de traiter les tirets produirait
        « noirtranchant », qui ne correspond plus à la forme espacée du
        catalogue. Ce test fige l'ordre.
        """
        assert "noirtranchant" not in fold("Cristal noir-tranchant")

    def test_compacte_les_espaces(self) -> None:
        assert fold("  Pierre   noire   (arme)  ") == "pierre noire arme"

    def test_retire_les_parentheses(self) -> None:
        assert fold("Pierre noire (arme)") == "pierre noire arme"

    def test_conserve_les_chiffres(self) -> None:
        assert fold("Élixir de vie x3") == "elixir de vie x3"

    def test_chaine_vide(self) -> None:
        assert fold("") == ""
        assert fold("   ") == ""
        assert fold("!!!") == ""

    def test_idempotent(self) -> None:
        """Replier une forme déjà repliée ne doit rien changer.

        Le catalogue replie ses noms à l'indexation et le matcher replie la
        ligne OCR. Si fold() n'était pas idempotent, un texte replié deux fois
        quelque part dans la chaîne ne correspondrait plus.
        """
        once = fold("Nœud d'arbre ensanglanté")
        assert fold(once) == once


class TestFoldDigits:
    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("1O", "10"),
            ("l2", "12"),
            ("I5", "15"),
            ("|00", "100"),
            ("S", "5"),
            ("B", "8"),
            ("2O0", "200"),
        ],
    )
    def test_force_les_glyphes_vers_des_chiffres(self, source: str, expected: str) -> None:
        assert fold_digits(source) == expected

    def test_ne_doit_jamais_etre_applique_a_un_nom(self) -> None:
        """Documente pourquoi les deux chemins sont séparés.

        Ce test ne vérifie pas un comportement souhaitable, il fige la raison
        d'être de la séparation : appliqué à un nom, fold_digits le détruit.
        Si quelqu'un fusionne un jour les deux fonctions, ce test le rappelle.
        """
        assert fold_digits("Poudre") == "P0udre"
        assert fold_digits("Pierre") == "P1erre"


class TestIsMeaningful:
    @pytest.mark.parametrize("bruit", ["", "ll", "x", "1", "  ", "x3", "]["])
    def test_rejette_le_bruit(self, bruit: str) -> None:
        """Régression : sans ce filtre, le score flou invente des drops.

        Sur un dictionnaire de plusieurs milliers de noms, n'importe quel
        fragment de deux lettres finit par ressembler assez à un objet court
        pour franchir le seuil. Le tracker compte alors des drops qui n'ont
        jamais eu lieu.
        """
        assert not is_meaningful(fold(bruit))

    @pytest.mark.parametrize("texte", ["Pierre noire", "Épée", "Œuf dur", "Trace"])
    def test_accepte_un_vrai_nom(self, texte: str) -> None:
        assert is_meaningful(fold(texte))

    def test_seuil_configurable(self) -> None:
        assert is_meaningful("abc", min_letters=3)
        assert not is_meaningful("abc", min_letters=4)
