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
from butin.tracking.scroll import estimate_text_scroll_px, rows_scrolled
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


ENCRE = 230
"""Niveau du texte du journal, peint en clair."""


def render_texte(lignes: list[int], *, decor: int = 0, pas: int = ROW_HEIGHT) -> np.ndarray:
    """Fabrique un journal : un décor sombre, et des marques claires par ligne.

    C'est la forme que le journal a vraiment. Son fond est **transparent sur le
    monde du jeu**, donc le décor derrière change tout le temps et pour des
    raisons qui n'ont rien à voir avec le défilement, tandis que le texte, lui,
    est peint en clair et défile avec les lignes.

    `decor` déplace le fond sans toucher au texte, ce qui est exactement la
    situation que la mesure doit traverser sans broncher.
    """
    image = np.zeros((len(lignes) * pas, WIDTH), dtype=np.uint8)
    for index, graine in enumerate(lignes):
        haut = index * pas
        # Un fond sombre mais pas uniforme, sous le seuil de clarté.
        fond = (np.arange(WIDTH, dtype=np.int64) * 3 + decor * 7) % 100
        image[haut : haut + pas, :] = fond.astype(np.uint8)
        # Des marques claires, à des colonnes propres à la ligne : deux lignes
        # du journal ne portent jamais les mêmes lettres aux mêmes endroits.
        colonnes = np.random.default_rng(graine).choice(WIDTH, size=WIDTH // 6, replace=False)
        image[haut + 4 : haut + pas - 4, colonnes] = ENCRE
    return image


class TestDefilementDuTexte:
    def test_defilement_d_une_ligne(self) -> None:
        previous = render_texte([1, 2, 3, 4, 5, 6])
        current = render_texte([2, 3, 4, 5, 6, 7])

        result = estimate_text_scroll_px(previous, current)

        assert result.shift_px == ROW_HEIGHT
        assert result.confident

    def test_le_decor_qui_bouge_derriere_ne_fausse_pas_la_mesure(self) -> None:
        """Régression : c'est tout le problème du journal, et il est mesuré.

        Le fond du chat est transparent sur le monde du jeu. En niveaux de gris,
        ce décor occupe toute la surface et pèse donc plus lourd que les
        lettres : la mesure suit le monde qui bouge au lieu du texte qui défile.

        Mesuré par le banc d'essai le 05/08/2026 sur 300 images de vrai farm :
        **0 détection juste sur 37** avec la colonne des pastilles en niveaux de
        gris, 17 sur 37 avec la colonne du texte en niveaux de gris, et
        **32 sur 37** avec le masque de pixels clairs. Le masque fait disparaître
        le décor, et il ne reste que les lettres.

        Ici le texte défile d'une ligne pendant que le décor change dessous.
        """
        previous = render_texte([1, 2, 3, 4, 5, 6], decor=0)
        current = render_texte([2, 3, 4, 5, 6, 7], decor=9)

        clair = estimate_text_scroll_px(previous, current)
        gris = estimate_scroll_px(previous, current)

        assert clair.shift_px == ROW_HEIGHT
        assert clair.confident
        # La mesure en gris peut tomber sur le bon décalage, mais le décor
        # l'empêche de franchir son critère de sûreté : elle ne rend donc
        # aucune prédiction. C'est exactement ce que le banc a observé, avec
        # zéro détection sûre sur les 299 transitions de la rafale réelle.
        assert not gris.confident

    def test_des_lignes_toutes_identiques_sont_invisibles(self) -> None:
        """⛔ Pourquoi la colonne des pastilles de canal ne peut pas servir.

        Les pastilles `Système` sont toutes identiques et espacées d'exactement
        un pas de ligne. Un défilement d'une ligne superpose donc la pastille
        `n` sur la pastille `n+1` et ne change **rien** à l'image. C'est
        précisément la colonne aveugle à ce qu'on lui demanderait de voir.

        Ce n'est pas un défaut de la mesure, c'est une propriété de ce qu'on lui
        donne à mesurer : aucune méthode ne peut détecter le décalage d'un motif
        strictement périodique. La règle est donc la colonne du texte, où deux
        lignes ne se ressemblent jamais.
        """
        motif = [7, 7, 7, 7, 7, 7]
        previous = render_texte(motif)
        current = render_texte(motif)

        result = estimate_text_scroll_px(previous, current)

        assert result.shift_px == 0

    def test_deux_contenus_sans_rapport_ne_donnent_aucun_decalage(self) -> None:
        """Régression : un gain relatif seul laissait passer n'importe quoi.

        Sur deux contenus sans rapport, il existe toujours un décalage qui
        améliore un peu le recouvrement par pur hasard. Le premier critère ne
        regardait que ce gain, et déclarait donc un défilement entre deux images
        étrangères l'une à l'autre. Une prédiction fausse est pire que pas de
        prédiction : elle ferait écarter le bon recouvrement au profit d'un faux.

        Le recouvrement absolu tranche : les 32 décalages justes de la rafale
        réelle atteignent 0,433 au minimum, deux contenus sans rapport plafonnent
        autour de 0,1.
        """
        previous = render_texte([1, 2, 3, 4, 5, 6])
        current = render_texte([50, 51, 52, 53, 54, 55])

        result = estimate_text_scroll_px(previous, current)

        assert not result.confident

    def test_images_identiques_aucun_defilement(self) -> None:
        """Régression : « rien n'a bougé » doit être une réponse, pas un doute.

        C'est le cas le plus fréquent en jeu : la capture tourne dix fois par
        seconde et le journal reçoit trois lignes par seconde. Si l'absence de
        défilement était rendue comme une incertitude, chaque tour immobile
        marquerait l'accumulation comme non fiable et la boucle ne prédirait
        plus jamais rien.
        """
        frame = render_texte([1, 2, 3, 4, 5])
        result = estimate_text_scroll_px(frame, frame)

        assert result.shift_px == 0
        assert result.confident

    def test_images_de_tailles_differentes(self) -> None:
        """Un redimensionnement de la fenêtre du jeu produit exactement ce cas."""
        result = estimate_text_scroll_px(render_texte([1, 2]), render_texte([1, 2, 3]))

        assert result.shift_px == 0
        assert not result.confident

    def test_image_non_bidimensionnelle(self) -> None:
        """Une image couleur passée par erreur ne doit pas planter le suivi."""
        couleur = np.zeros((40, WIDTH, 3), dtype=np.uint8)
        result = estimate_text_scroll_px(couleur, couleur)
        assert not result.confident

    def test_le_defilement_alimente_la_prediction_de_lignes(self) -> None:
        """Le seul usage de cette mesure : dire combien de lignes sont nouvelles."""
        previous = render_texte([1, 2, 3, 4, 5, 6])
        current = render_texte([3, 4, 5, 6, 7, 8])

        result = estimate_text_scroll_px(previous, current)

        assert expected_new_lines(result, ROW_HEIGHT, max_lines=10) == 2


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
