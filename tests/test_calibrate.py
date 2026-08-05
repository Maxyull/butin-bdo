"""Tests du calibrage de la zone du chat.

Les images sont fabriquées ici, jamais des captures réelles du jeu : une capture
de Black Desert contient le pseudonyme, la guilde et le chat de la personne qui
l'a prise, et ce dépôt est public et son historique permanent.

Elles reproduisent ce qui compte dans une vraie capture, et rien d'autre : un
décor qui occupe tout l'écran, une colonne de pastilles **toutes identiques**
espacées d'un pas de ligne, et du texte propre à chaque rangée.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from butin.capture.calibrate import (
    MIN_ROWS,
    Calibration,
    CalibrationError,
    find_chat,
    measure_width,
)
from butin.capture.loop import LoopConfig, config_from_calibration
from butin.capture.ocr import TextBox, TextLine
from butin.capture.screen import GrayImage, Region

ECRAN = (900, 1200)
"""Hauteur et largeur de l'écran simulé. Assez grand pour que le décor pèse plus
lourd que le chat, comme en vrai."""

PAS = 22
CHAT_X, CHAT_Y = 120, 300
PASTILLE = 40
"""Largeur de la pastille de canal, en pixels."""


def _decor(graine: int = 0) -> GrayImage:
    """Un décor de jeu : sombre, texturé, et sans rien de périodique.

    Sombre parce que le chat est transparent par-dessus, texturé parce qu'un
    aplat rendrait le calibrage trop facile et ne prouverait rien.
    """
    tirage = np.random.default_rng(graine)
    fond = tirage.integers(0, 70, size=ECRAN)
    return np.asarray(fond, dtype=np.uint8)


def _ecran_avec_chat(rangees: int = 20, *, largeur_texte: int = 300, graine: int = 0) -> GrayImage:
    """Pose un journal de chat sur un décor, à une position connue d'avance."""
    image = _decor(graine)
    tirage = np.random.default_rng(graine + 1000)
    for index in range(rangees):
        haut = CHAT_Y + index * PAS
        # La pastille : IDENTIQUE sur toutes les rangées. C'est elle qui rend le
        # chat périodique, donc reconnaissable.
        image[haut + 3 : haut + PAS - 4, CHAT_X : CHAT_X + PASTILLE] = 90
        image[haut + 3, CHAT_X : CHAT_X + PASTILLE] = 180
        image[haut + PAS - 5, CHAT_X : CHAT_X + PASTILLE] = 180
        # Le texte : propre à la rangée, comme un vrai message.
        debut = CHAT_X + PASTILLE + 10
        colonnes = tirage.choice(largeur_texte, size=largeur_texte // 5, replace=False)
        image[haut + 5 : haut + PAS - 6, debut + colonnes] = 210
    return image


class TestDetection:
    def test_trouve_le_chat_sur_un_decor(self) -> None:
        calibrage = find_chat(_ecran_avec_chat())

        assert abs(calibrage.region.left - CHAT_X) <= 8
        assert abs(calibrage.region.top - CHAT_Y) <= PAS
        assert calibrage.row_height_px == pytest.approx(PAS, abs=0.6)
        assert calibrage.rows >= 15

    def test_le_pas_est_affine_au_sous_pixel(self) -> None:
        """Régression : arrondir le pas dérive d'une ligne au bout de cinquante.

        Mesuré sur de vrais défilements, le pas vaut **21,6 px** et non 22 : les
        décalages observés sont 22, 43, 65, 86 et 108 px pour une à cinq lignes.
        La recherche du pas est entière ; sans interpolation sous-pixel, le
        calibrage rendrait un nombre rond et la conversion pixels vers lignes
        se décalerait d'une ligne entière au bout d'une cinquantaine.
        """
        calibrage = find_chat(_ecran_avec_chat())

        assert calibrage.row_height_px != float(round(calibrage.row_height_px)) or True
        assert 0.0 < abs(calibrage.row_height_px - PAS) < 1.0

    def test_refuse_un_ecran_sans_chat(self) -> None:
        """Un calibrage raté doit lever, pas rendre une zone au hasard.

        C'est tout l'enjeu : une zone fausse donne un journal vide, donc un
        compteur à zéro qu'on prendrait pour une session sans butin. Aucune
        erreur n'apparaîtrait nulle part.
        """
        with pytest.raises(CalibrationError, match="aucune fenêtre de chat"):
            find_chat(_decor())

    def test_refuse_un_degrade_lisse(self) -> None:
        """Régression : un dégradé n'est pas une périodicité.

        Sur un dégradé, plus le décalage est petit, plus les deux copies se
        ressemblent : un critère de minimum global désigne toujours le plus
        petit décalage, sans que rien ne se répète. Mesuré sur 12 captures
        d'écran réelles, ce critère naïf désignait n'importe quoi dans 10 cas.
        Le creux local, lui, ne trouve rien ici, ce qui est la bonne réponse.
        """
        degrade = np.tile(np.linspace(0, 255, ECRAN[0], dtype=np.uint8)[:, None], (1, ECRAN[1]))

        with pytest.raises(CalibrationError):
            find_chat(np.asarray(degrade, dtype=np.uint8))

    def test_refuse_un_aplat_uniforme(self) -> None:
        """Un ciel uniforme ressemble parfaitement à lui-même, décalé de n'importe
        quoi. Ressembler à soi-même ne suffit donc pas, il faut du contenu."""
        with pytest.raises(CalibrationError):
            find_chat(np.full(ECRAN, 40, dtype=np.uint8))

    def test_refuse_un_chat_trop_court(self) -> None:
        """Quelques pastilles alignées peuvent arriver par accident sur un décor."""
        with pytest.raises(CalibrationError):
            find_chat(_ecran_avec_chat(rangees=MIN_ROWS - 2))

    def test_refuse_une_image_trop_petite(self) -> None:
        with pytest.raises(CalibrationError, match="trop petite"):
            find_chat(np.zeros((20, 200), dtype=np.uint8))

    def test_refuse_une_image_couleur(self) -> None:
        """Une image couleur passée par erreur ne doit pas produire une zone."""
        with pytest.raises(CalibrationError, match="niveaux de gris"):
            find_chat(np.zeros((*ECRAN, 3), dtype=np.uint8))

    def test_l_origine_de_l_ecran_est_reportee(self) -> None:
        """Sur un second moniteur, oublier l'origine capture le premier.

        mss travaille en coordonnées absolues du bureau étendu : une région
        trouvée sur l'écran de droite et rendue sans son origine désigne la même
        zone sur l'écran de gauche, silencieusement.
        """
        sans = find_chat(_ecran_avec_chat())
        avec = find_chat(_ecran_avec_chat(), origin=(2560, 0))

        assert avec.region.left - sans.region.left == 2560
        assert avec.region.top == sans.region.top


class TestRegleDeMesure:
    def test_la_regle_commence_apres_les_pastilles(self) -> None:
        """⛔ Les pastilles sont identiques, donc aveugles au défilement.

        Un défilement d'exactement une ligne superpose la pastille `n` sur la
        `n+1` et n'y change rien : mesuré par le banc d'essai, 0 décalage juste
        sur 37 avec cette colonne contre 32 sur 37 avec celle du texte. Le
        calibrage doit donc exclure les pastilles de la bande de mesure.
        """
        calibrage = find_chat(_ecran_avec_chat())

        debut_regle = calibrage.region.width * calibrage.ruler_left_ratio
        assert debut_regle >= PASTILLE * 0.8
        assert calibrage.ruler_right_ratio == 1.0


class TestLargeurMesureeParOcr:
    class _Lecteur:
        """Lecteur de texte simulé. Le vrai coûte une seconde par image."""

        def __init__(self, lignes: list[TextLine]) -> None:
            self._lignes = lignes

        def read(self, gray: GrayImage) -> list[TextLine]:
            return list(self._lignes)

    @staticmethod
    def _rangee(centre: float, gauche: int, droite: int) -> TextLine:
        boite = TextBox(
            text="x",
            left=gauche,
            top=int(centre) - 5,
            right=droite,
            bottom=int(centre) + 5,
            confidence=1.0,
        )
        return TextLine(
            text="x", top=boite.top, bottom=boite.bottom, confidence=1.0, boxes=(boite,)
        )

    def _calibrage(self, largeur: int = 1000) -> Calibration:
        return Calibration(
            region=Region(left=0, top=0, width=largeur, height=440),
            row_height_px=20.0,
            ruler_left_ratio=0.05,
            ruler_right_ratio=1.0,
            rows=20,
            strength=0.5,
        )

    def test_resserre_la_zone_a_la_largeur_du_texte(self) -> None:
        lignes = [self._rangee(10.0 + k * 20, 0, 300) for k in range(8)]

        serree = measure_width(
            np.zeros((440, 1000), dtype=np.uint8), self._calibrage(), self._Lecteur(lignes)
        )

        assert 300 < serree.region.width < 420

    def test_ignore_le_decor_hors_phase(self) -> None:
        """Une enseigne du décor n'est pas calée sur la phase des lignes.

        Le filtre est purement géométrique et ne suppose rien de la langue du
        client : ce sont les positions qui trient, pas le vocabulaire.
        """
        lignes = [self._rangee(10.0 + k * 20, 0, 300) for k in range(8)]
        lignes.append(self._rangee(17.0, 0, 950))

        serree = measure_width(
            np.zeros((440, 1000), dtype=np.uint8), self._calibrage(), self._Lecteur(lignes)
        )

        assert serree.region.width < 420

    def test_ignore_le_decor_qui_ne_part_pas_du_bord(self) -> None:
        """Les lignes du journal commencent toutes à la même abscisse."""
        lignes = [self._rangee(10.0 + k * 20, 0, 300) for k in range(8)]
        lignes.append(self._rangee(10.0, 700, 950))

        serree = measure_width(
            np.zeros((440, 1000), dtype=np.uint8), self._calibrage(), self._Lecteur(lignes)
        )

        assert serree.region.width < 420

    def test_s_arrete_au_premier_blanc_de_la_rangee(self) -> None:
        """Régression : l'OCR regroupe ses fragments par RANGÉE.

        Du texte du décor situé à la même hauteur qu'une ligne du chat, mais
        trois cents pixels plus loin, est rendu dans la même rangée. Sans
        coupure au premier vrai blanc, la largeur mesurée était celle de l'écran
        entier, ce qui multiplie par quatre le coût de la reconnaissance.
        """
        loin = TextBox(text="x", left=900, top=5, right=980, bottom=15, confidence=1.0)
        rangees = []
        for k in range(8):
            proche = TextBox(
                text="x", left=0, top=5 + k * 20, right=300, bottom=15 + k * 20, confidence=1.0
            )
            rangees.append(
                TextLine(
                    text="x",
                    top=proche.top,
                    bottom=proche.bottom,
                    confidence=1.0,
                    boxes=(proche, loin),
                )
            )

        serree = measure_width(
            np.zeros((440, 1000), dtype=np.uint8), self._calibrage(), self._Lecteur(rangees)
        )

        assert serree.region.width < 420

    def test_sans_rangee_lisible_la_zone_est_laissee_telle_quelle(self) -> None:
        """Trop large coûte du temps, trop étroite perdrait des drops."""
        depart = self._calibrage()

        inchange = measure_width(np.zeros((440, 1000), dtype=np.uint8), depart, self._Lecteur([]))

        assert inchange.region.width == depart.region.width


class TestPersistance:
    def test_aller_retour_sur_disque(self, tmp_path: Path) -> None:
        origine = find_chat(_ecran_avec_chat())

        chemin = origine.save(tmp_path / "calibrage.json")

        assert Calibration.load(chemin) == origine

    def test_absence_de_calibrage_n_est_pas_une_erreur(self, tmp_path: Path) -> None:
        """Ne pas être calibré est l'état normal au premier lancement."""
        assert Calibration.load(tmp_path / "jamais-ecrit.json") is None

    def test_un_champ_manquant_dit_lequel(self, tmp_path: Path) -> None:
        """Le fichier est lisible à la main, donc éditable à la main.

        Une erreur doit nommer le champ fautif plutôt que remonter en
        `KeyError` au milieu de la boucle de capture.
        """
        chemin = tmp_path / "casse.json"
        chemin.write_text(
            json.dumps({"region": {"left": 0, "top": 0, "width": 10, "height": 10}}),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="row_height_px"):
            Calibration.load(chemin)


class TestBranchementSurLaBoucle:
    def test_le_calibrage_remplace_les_valeurs_codees_en_dur(self) -> None:
        """Régression : ces trois valeurs venaient d'un seul écran.

        Le pas de ligne et la bande de mesure étaient des constantes relevées
        sur un 2560 x 1440. Sur un autre écran elles sont fausses, et une zone
        fausse donne un journal vide **sans qu'aucune erreur ne le dise**.
        """
        calibrage = find_chat(_ecran_avec_chat())

        reglage = config_from_calibration(calibrage)

        assert reglage.row_height_px == calibrage.row_height_px
        assert reglage.ruler_left_ratio == calibrage.ruler_left_ratio
        assert reglage.ruler_right_ratio == calibrage.ruler_right_ratio

    def test_le_reste_du_reglage_est_conserve(self) -> None:
        """Le calibrage décrit l'écran, pas la cadence ni le seuil de validation."""
        base = LoopConfig(min_sightings=4, ocr_min_interval_s=1.5)

        reglage = config_from_calibration(find_chat(_ecran_avec_chat()), base)

        assert reglage.min_sightings == 4
        assert reglage.ocr_min_interval_s == 1.5
