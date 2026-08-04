"""Tests de la détection de défilement et du garde-fou de stabilité.

Les images de test sont fabriquées par le code, jamais des captures réelles du
jeu : une capture de Black Desert contient le pseudonyme, la guilde et le chat
de la personne qui l'a prise, et ce dépôt est public et son historique
permanent.
"""

from __future__ import annotations

import numpy as np
import pytest

from butin.tracking import StabilityGate, estimate_scroll_px, expected_new_lines
from butin.tracking.scroll import rows_scrolled
from butin.tracking.stability import frame_difference

ROW_HEIGHT = 20
WIDTH = 120


def render(rows: list[int], row_height: int = ROW_HEIGHT) -> np.ndarray:
    """Fabrique une image en niveaux de gris imitant un journal.

    Chaque ligne est une bande d'une valeur propre, avec un léger dégradé
    horizontal pour éviter des bandes parfaitement uniformes, qui rendraient
    plusieurs décalages indiscernables et ne ressembleraient pas à du texte.
    """
    image = np.zeros((len(rows) * row_height, WIDTH), dtype=np.float32)
    gradient = np.linspace(0, 15, WIDTH, dtype=np.float32)
    for index, value in enumerate(rows):
        band = float(value) + gradient
        image[index * row_height : (index + 1) * row_height, :] = band
    return image


class TestDetectionDeDefilement:
    def test_images_identiques_aucun_defilement(self) -> None:
        frame = render([10, 60, 110, 160, 210])
        result = estimate_scroll_px(frame, frame)

        assert result.shift_px == 0
        assert result.confident, "l'absence de mouvement est une information, pas un doute"

    def test_defilement_d_une_ligne(self) -> None:
        previous = render([10, 60, 110, 160, 210])
        current = render([60, 110, 160, 210, 250])

        result = estimate_scroll_px(previous, current)

        assert result.shift_px == ROW_HEIGHT
        assert result.confident
        assert result.score < result.baseline_score

    def test_defilement_de_trois_lignes(self) -> None:
        previous = render([10, 45, 80, 115, 150, 185, 220, 250])
        current = render([115, 150, 185, 220, 250, 20, 55, 90])

        result = estimate_scroll_px(previous, current)

        assert result.shift_px == 3 * ROW_HEIGHT
        assert result.confident

    def test_un_defilement_de_plus_de_la_moitie_de_la_fenetre_est_hors_de_portee(
        self,
    ) -> None:
        """Limite structurelle de la méthode, documentée plutôt que subie.

        La recherche s'arrête à la moitié de la hauteur : au-delà, il ne reste
        pas assez de recouvrement entre les deux images pour qu'une
        correspondance veuille dire quoi que ce soit. Un défilement de 4 lignes
        sur 5 n'est donc pas détectable, et c'est voulu.

        Ce n'est pas un problème en pratique : c'est le cas où l'alignement
        textuel reprend seul la main, et il ne reçoit alors aucune prédiction
        trompeuse.
        """
        previous = render([10, 60, 110, 160, 210])
        current = render([210, 250, 30, 80, 130])

        result = estimate_scroll_px(previous, current)

        assert result.shift_px <= previous.shape[0] // 2

    def test_images_de_tailles_differentes(self) -> None:
        """Ne doit jamais lever : la zone de capture peut changer de taille.

        Un redimensionnement de la fenêtre du jeu produit exactement ce cas. La
        détection doit simplement se déclarer incapable.
        """
        result = estimate_scroll_px(render([10, 60]), render([10, 60, 110]))

        assert result.shift_px == 0
        assert not result.confident

    def test_image_trop_petite(self) -> None:
        result = estimate_scroll_px(np.zeros((2, 5)), np.zeros((2, 5)))
        assert not result.confident

    def test_image_non_bidimensionnelle(self) -> None:
        """Une image couleur passée par erreur ne doit pas planter le suivi."""
        colour = np.zeros((40, WIDTH, 3), dtype=np.float32)
        result = estimate_scroll_px(colour, colour)
        assert not result.confident


class TestConversionEnLignes:
    def test_conversion_simple(self) -> None:
        assert rows_scrolled(40, 20.0) == pytest.approx(2.0)

    def test_hauteur_de_ligne_inconnue(self) -> None:
        """Zéro ou négatif signifie calibrage non fait, pas division par zéro."""
        assert rows_scrolled(40, 0.0) == 0.0
        assert rows_scrolled(40, -5.0) == 0.0


class TestNouvellesLignesAttendues:
    def _resultat(self, previous: list[int], current: list[int]):
        return estimate_scroll_px(render(previous), render(current))

    def test_une_ligne(self) -> None:
        result = self._resultat([10, 60, 110, 160, 210], [60, 110, 160, 210, 250])
        assert expected_new_lines(result, ROW_HEIGHT, max_lines=10) == 1

    def test_aucun_defilement(self) -> None:
        frame = [10, 60, 110, 160, 210]
        result = self._resultat(frame, frame)
        assert expected_new_lines(result, ROW_HEIGHT, max_lines=10) == 0

    def test_detection_incertaine_donne_none(self) -> None:
        """En cas de doute, aucune prédiction plutôt qu'une mauvaise.

        Une prédiction fausse ferait écarter le bon recouvrement au profit d'un
        faux, ce qui est pire que laisser l'alignement textuel travailler seul.
        """
        result = estimate_scroll_px(render([10, 60]), render([10, 60, 110]))
        assert expected_new_lines(result, ROW_HEIGHT, max_lines=10) is None

    def test_hauteur_de_ligne_inconnue_donne_none(self) -> None:
        result = self._resultat([10, 60, 110, 160, 210], [60, 110, 160, 210, 250])
        assert expected_new_lines(result, 0.0, max_lines=10) is None

    def test_estimation_entre_deux_lignes_rejetee(self) -> None:
        """Régression : un défilement de 1,5 ligne n'existe pas physiquement.

        Soit la hauteur de ligne calibrée est fausse, soit la détection s'est
        trompée. Arrondir donnerait une prédiction fausse présentée comme sûre.
        """
        result = self._resultat([10, 60, 110, 160, 210], [60, 110, 160, 210, 250])
        # Hauteur de ligne délibérément fausse : 20 px lus comme 1,54 ligne.
        assert expected_new_lines(result, 13.0, max_lines=10) is None

    def test_plafonne_au_nombre_de_lignes_visibles(self) -> None:
        result = self._resultat(
            [10, 45, 80, 115, 150, 185, 220, 250],
            [115, 150, 185, 220, 250, 20, 55, 90],
        )
        assert expected_new_lines(result, ROW_HEIGHT, max_lines=10) == 3
        assert expected_new_lines(result, ROW_HEIGHT, max_lines=2) == 2


class TestDifferenceEntreImages:
    def test_images_identiques(self) -> None:
        frame = render([10, 60])
        assert frame_difference(frame, frame) == 0.0

    def test_tailles_incompatibles_donnent_l_infini(self) -> None:
        """L'infini ne franchit aucun seuil, donc l'image est jugée instable.

        C'est le bon repli : une image de taille inattendue ne doit surtout pas
        être prise pour identique à la précédente.
        """
        assert frame_difference(render([10]), render([10, 60])) == float("inf")


class TestGardeFouDeStabilite:
    def test_la_premiere_image_n_est_jamais_stable(self) -> None:
        """Rien à quoi la comparer, donc aucune affirmation possible."""
        gate = StabilityGate(min_stable_frames=1)
        assert gate.update(render([10, 60])) is False

    def test_deux_images_identiques_donnent_la_stabilite(self) -> None:
        gate = StabilityGate(min_stable_frames=1)
        frame = render([10, 60])
        gate.update(frame)
        assert gate.update(frame) is True

    def test_un_changement_remet_le_compteur_a_zero(self) -> None:
        """L'animation d'apparition d'une ligne doit retarder l'OCR.

        Une reconnaissance lancée en plein fondu lit du texte à moitié
        transparent et produit des résultats aberrants, qui polluent ensuite
        l'alignement et le vote.
        """
        gate = StabilityGate(min_stable_frames=2)
        stable = render([10, 60])
        gate.update(stable)
        gate.update(stable)
        assert gate.update(stable) is True

        assert gate.update(render([200, 250])) is False
        assert gate.stable_run == 0

    def test_plusieurs_images_calmes_exigees(self) -> None:
        gate = StabilityGate(min_stable_frames=3)
        frame = render([10, 60])
        gate.update(frame)
        assert gate.update(frame) is False
        assert gate.update(frame) is False
        assert gate.update(frame) is True

    def test_remise_a_zero(self) -> None:
        gate = StabilityGate(min_stable_frames=1)
        frame = render([10, 60])
        gate.update(frame)
        gate.update(frame)
        gate.reset()

        assert gate.update(frame) is False, "après remise à zéro, plus de référence"
