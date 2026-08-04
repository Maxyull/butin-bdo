"""Tests de l'alignement de deux captures.

L'invariant testé partout : les lignes communes forment un suffixe de l'ancienne
capture et un préfixe de la nouvelle, donc les lignes nouvelles sont
`current[recouvrement:]`.
"""

from __future__ import annotations

from butin.catalog import ItemCatalog
from butin.tracking import align, is_glitch_frame, is_implausible_jump
from butin.tracking.alignment import GLITCH_MAX_SKIPS, PLAUSIBLE_MAX_NEW
from butin.tracking.models import ObservedLine


def ligne(catalog: ItemCatalog, item_id: int, qty: int = 1) -> ObservedLine:
    item = catalog.get(item_id)
    return ObservedLine(raw=item.name() if item else "?", item=item, qty=qty)


# Quatre objets distincts, pour composer des fenêtres lisibles.
A, B, C, D = 16001, 16002, 4998, 721003


class TestCasNominal:
    def test_defilement_d_une_ligne(self, catalog: ItemCatalog) -> None:
        previous = [ligne(catalog, A), ligne(catalog, B), ligne(catalog, C)]
        current = [ligne(catalog, B), ligne(catalog, C), ligne(catalog, D)]

        result = align(previous, current)

        assert result.overlap == 2
        assert [line.item_id for line in result.new_lines] == [D]
        assert not result.zero_overlap

    def test_aucun_defilement(self, catalog: ItemCatalog) -> None:
        window = [ligne(catalog, A), ligne(catalog, B), ligne(catalog, C)]
        result = align(window, list(window))
        assert result.overlap == 3
        assert result.new_lines == []

    def test_defilement_de_plusieurs_lignes(self, catalog: ItemCatalog) -> None:
        previous = [ligne(catalog, A), ligne(catalog, B), ligne(catalog, C)]
        current = [ligne(catalog, C), ligne(catalog, D), ligne(catalog, A)]
        result = align(previous, current)
        assert result.overlap == 1
        assert len(result.new_lines) == 2

    def test_premiere_capture_tout_est_nouveau(self, catalog: ItemCatalog) -> None:
        current = [ligne(catalog, A), ligne(catalog, B)]
        result = align([], current)
        assert result.overlap == 0
        assert len(result.new_lines) == 2
        assert not result.zero_overlap, "aucune image précédente n'est pas un cas suspect"

    def test_deux_captures_vides(self, catalog: ItemCatalog) -> None:
        result = align([], [])
        assert result.overlap == 0
        assert result.new_lines == []
        assert not result.zero_overlap


class TestPlusGrandRecouvrement:
    def test_le_plus_grand_recouvrement_est_retenu(self, catalog: ItemCatalog) -> None:
        """Choisir le plus grand recouvrement déclare le moins de nouveautés.

        C'est ce qui protège du recomptage : à choisir entre deux lectures
        possibles, on prend celle qui compte le moins de drops.
        """
        previous = [ligne(catalog, A), ligne(catalog, A), ligne(catalog, A)]
        current = [ligne(catalog, A), ligne(catalog, A), ligne(catalog, A)]
        result = align(previous, current)
        assert result.overlap == 3
        assert result.new_lines == []


class TestMurDeLignesIdentiques:
    """Le cas que le texte seul ne peut pas trancher.

    Dix « Pierre noire (arme) x1 » d'affilée est la situation normale en farm,
    pas un cas limite. Plusieurs recouvrements sont alors valides, et le texte
    n'a aucun moyen de choisir. Seuls les pixels le peuvent.
    """

    def test_sans_indice_pixel_le_texte_surestime_le_recouvrement(
        self, catalog: ItemCatalog
    ) -> None:
        """Régression : documente le point aveugle de l'alignement textuel.

        Cinq lignes identiques dont une a réellement défilé. Le texte retient
        le recouvrement maximal et conclut à zéro nouveauté, donc rate le drop.
        Ce test fige le comportement pour que le suivant montre le rattrapage.
        """
        previous = [ligne(catalog, A) for _ in range(5)]
        current = [ligne(catalog, A) for _ in range(5)]

        result = align(previous, current)

        assert result.overlap == 5
        assert result.new_lines == []

    def test_l_indice_pixel_tranche(self, catalog: ItemCatalog) -> None:
        """Les pixels disent qu'une ligne a défilé, l'alignement s'y range."""
        previous = [ligne(catalog, A) for _ in range(5)]
        current = [ligne(catalog, A) for _ in range(5)]

        result = align(previous, current, expected_new=1)

        assert result.overlap == 4
        assert len(result.new_lines) == 1
        assert result.diagnostics["disagreement"] is True

    def test_le_desaccord_est_trace_pas_masque(self, catalog: ItemCatalog) -> None:
        """Un désaccord texte/pixels doit rester visible dans le diagnostic.

        Un tracker qui se trompe sans laisser de trace n'est pas
        diagnosticable : l'utilisateur voit un chiffre, jamais le raisonnement.
        """
        previous = [ligne(catalog, A) for _ in range(4)]
        current = [ligne(catalog, A) for _ in range(4)]

        result = align(previous, current, expected_new=2)

        assert result.diagnostics["largest_valid"] == 4
        assert result.diagnostics["target_overlap"] == 2
        assert result.diagnostics["disagreement"] is True

    def test_l_indice_pixel_ne_cree_pas_un_recouvrement_invalide(
        self, catalog: ItemCatalog
    ) -> None:
        """Les pixels orientent le choix, ils ne l'imposent pas.

        Seuls les recouvrements textuellement valides sont candidats. Une
        prédiction fausse ne peut donc pas fabriquer un alignement absurde.
        """
        previous = [ligne(catalog, A), ligne(catalog, B), ligne(catalog, C)]
        current = [ligne(catalog, B), ligne(catalog, C), ligne(catalog, D)]

        result = align(previous, current, expected_new=0)

        assert result.overlap in result.diagnostics["valid_overlaps"]
        assert [line.item_id for line in result.new_lines] == [D]


class TestBruitDeLecture:
    def test_un_chiffre_mal_lu_ne_casse_pas_l_alignement(self, catalog: ItemCatalog) -> None:
        """Régression : sinon le drop mal lu est recompté.

        Si la ligne portée à 68 puis relue 88 était vue comme une autre ligne,
        l'alignement conclurait qu'une ligne a disparu et qu'une nouvelle est
        apparue, donc compterait le drop deux fois.
        """
        previous = [ligne(catalog, A), ligne(catalog, B, qty=68)]
        current = [ligne(catalog, A), ligne(catalog, B, qty=88)]

        result = align(previous, current)

        assert result.overlap == 2
        assert result.new_lines == []


class TestImageAberrante:
    def test_perte_totale_de_recouvrement_signalee(self, catalog: ItemCatalog) -> None:
        previous = [ligne(catalog, A), ligne(catalog, B), ligne(catalog, C)]
        current = [ligne(catalog, D), ligne(catalog, D), ligne(catalog, D)]

        result = align(previous, current)

        assert result.overlap == 0
        assert result.zero_overlap
        assert "reason" in result.diagnostics

    def test_image_aberrante_ignoree(self, catalog: ItemCatalog) -> None:
        previous = [ligne(catalog, A), ligne(catalog, B), ligne(catalog, C)]
        current = [ligne(catalog, D), ligne(catalog, D), ligne(catalog, D)]
        result = align(previous, current)

        assert is_glitch_frame(result, previous_length=3, consecutive_skips=0)

    def test_on_finit_par_ceder(self, catalog: ItemCatalog) -> None:
        """Régression : sans borne, le tracker se figerait pour de bon.

        Un vrai changement d'écran (changement de spot, redémarrage du jeu)
        produit une perte totale de recouvrement légitime. S'entêter à
        l'ignorer bloquerait le suivi jusqu'à la fin de la session.
        """
        previous = [ligne(catalog, A), ligne(catalog, B), ligne(catalog, C)]
        current = [ligne(catalog, D), ligne(catalog, D), ligne(catalog, D)]
        result = align(previous, current)

        assert not is_glitch_frame(result, 3, consecutive_skips=GLITCH_MAX_SKIPS)

    def test_pas_de_garde_fou_sans_base_credible(self, catalog: ItemCatalog) -> None:
        """Perdre le recouvrement d'une fenêtre d'une seule ligne est normal."""
        previous = [ligne(catalog, A)]
        current = [ligne(catalog, D)]
        result = align(previous, current)

        assert not is_glitch_frame(result, previous_length=1, consecutive_skips=0)


class TestSautInvraisemblable:
    def _resultat_avec(self, catalog: ItemCatalog, nouvelles: int):
        previous = [ligne(catalog, A)]
        current = [ligne(catalog, D) for _ in range(nouvelles)]
        return align(previous, current)

    def test_saut_normal_accepte(self, catalog: ItemCatalog) -> None:
        result = self._resultat_avec(catalog, 3)
        assert not is_implausible_jump(result, consecutive_skips=0)

    def test_saut_enorme_rejete(self, catalog: ItemCatalog) -> None:
        """Le journal ne défile pas de vingt lignes en un dixième de seconde."""
        result = self._resultat_avec(catalog, PLAUSIBLE_MAX_NEW + 10)
        assert is_implausible_jump(result, consecutive_skips=0)

    def test_les_pixels_autorisent_le_saut(self, catalog: ItemCatalog) -> None:
        """Deux signaux indépendants qui concordent priment sur notre plafond.

        Le plafond est une supposition sur ce qui est plausible. Une mesure de
        défilement qui confirme le saut vaut mieux qu'une supposition.
        """
        nouvelles = PLAUSIBLE_MAX_NEW + 10
        result = self._resultat_avec(catalog, nouvelles)
        assert not is_implausible_jump(result, 0, expected_new=nouvelles)

    def test_on_finit_par_ceder(self, catalog: ItemCatalog) -> None:
        result = self._resultat_avec(catalog, PLAUSIBLE_MAX_NEW + 10)
        assert not is_implausible_jump(result, consecutive_skips=GLITCH_MAX_SKIPS)
