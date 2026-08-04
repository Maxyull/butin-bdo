"""Tests de la capture d'écran et de la conversion en niveaux de gris.

**Aucun test ne capture un vrai écran.** L'intégration continue tourne sur
Linux sans serveur graphique : un seul test qui construirait réellement mss y
échouerait à chaque exécution, et un test rouge en permanence finit par être
ignoré, ce qui coûte plus cher que la couverture qu'il apporte. mss est donc
remplacé par un double, ce qui permet en prime de simuler des configurations
multi-écran qu'aucune machine de développement n'a sous la main.

Les images sont fabriquées par le code, jamais des captures réelles du jeu :
une capture de Black Desert contient le pseudonyme, la guilde et le chat de la
personne qui l'a prise, et ce dépôt est public et son historique permanent.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pytest

from butin.capture.screen import CaptureError, Region, ScreenCapture, bgra_to_gray

# Un bureau à deux écrans : le second est posé à droite du premier, donc ses
# coordonnées absolues commencent à 1920. C'est la disposition qui piège tout
# code raisonnant en coordonnées relatives à l'écran.
BUREAU = [
    {"left": 0, "top": 0, "width": 3520, "height": 1080},
    {"left": 0, "top": 0, "width": 1920, "height": 1080},
    {"left": 1920, "top": 0, "width": 1600, "height": 900},
]


class FauxMss:
    """Double de l'objet rendu par `mss.mss()`.

    Ne reproduit que ce dont ce module se sert : `monitors`, `grab` et `close`.
    `grab` rend un tableau BGRA parce que le vrai objet `ScreenShot` expose
    `__array_interface__`, donc `np.asarray` en tire exactement cela.
    """

    def __init__(self, monitors: list[dict[str, int]]) -> None:
        self.monitors = monitors
        self.grabs: list[dict[str, int]] = []
        self.close_calls = 0

    def grab(self, monitor: dict[str, int]) -> np.ndarray[Any, np.dtype[np.uint8]]:
        self.grabs.append(dict(monitor))
        shape = (monitor["height"], monitor["width"], 4)
        return np.full(shape, 200, dtype=np.uint8)

    def close(self) -> None:
        self.close_calls += 1


class UsineMss:
    """Remplace `mss.mss` et compte les instances créées."""

    def __init__(self, monitors: list[dict[str, int]] | None = None) -> None:
        self._monitors = monitors if monitors is not None else BUREAU
        self.instances: list[FauxMss] = []

    def __call__(self) -> FauxMss:
        instance = FauxMss([dict(entry) for entry in self._monitors])
        self.instances.append(instance)
        return instance


@pytest.fixture
def usine(monkeypatch: pytest.MonkeyPatch) -> UsineMss:
    """Neutralise `mss.mss` pour toute la durée du test."""
    fabrique = UsineMss()
    monkeypatch.setattr("mss.mss", fabrique)
    return fabrique


class TestRegion:
    def test_region_valide(self) -> None:
        region = Region(left=10, top=20, width=300, height=120)

        assert region.right == 310
        assert region.bottom == 140

    def test_refuse_une_largeur_nulle(self) -> None:
        with pytest.raises(ValueError, match="strictement positives"):
            Region(left=0, top=0, width=0, height=100)

    def test_refuse_une_hauteur_nulle(self) -> None:
        with pytest.raises(ValueError, match="strictement positives"):
            Region(left=0, top=0, width=100, height=0)

    def test_refuse_des_dimensions_negatives(self) -> None:
        """mss lève sur une taille négative, mais bien plus loin dans la boucle.

        Régression : un calibrage fait en tirant un rectangle de bas en haut
        produit naturellement une hauteur négative. Attraper cela à la
        construction dit quelle valeur est fausse ; laisser passer donne une
        erreur mss au bout de plusieurs images, sans rapport visible avec le
        calibrage.
        """
        with pytest.raises(ValueError):
            Region(left=0, top=0, width=-300, height=-120)

    def test_conversion_vers_le_format_mss(self) -> None:
        region = Region(left=10, top=20, width=300, height=120)

        assert region.to_mss() == {"left": 10, "top": 20, "width": 300, "height": 120}

    def test_relecture_d_une_entree_mss(self) -> None:
        region = Region.from_mss(BUREAU[2])

        assert region == Region(left=1920, top=0, width=1600, height=900)

    def test_aller_retour_json(self) -> None:
        """Le calibrage est sauvegardé puis relu : il doit revenir identique.

        Régression : c'est le seul chemin par lequel une région survit à un
        redémarrage. Une intervertion largeur/hauteur à l'écriture ou à la
        lecture ne se verrait pas dans la même session, seulement à la
        suivante, sous la forme d'une zone de journal fausse sans explication.
        """
        region = Region(left=1920, top=140, width=460, height=320)

        relue = Region.from_dict(json.loads(json.dumps(region.to_dict())))

        assert relue == region

    def test_champ_manquant_refuse(self) -> None:
        with pytest.raises(ValueError, match="height"):
            Region.from_dict({"left": 0, "top": 0, "width": 100})

    def test_valeur_non_entiere_refusee(self) -> None:
        with pytest.raises(ValueError, match="entier"):
            Region.from_dict({"left": 0, "top": 0, "width": "100", "height": 50})

    def test_un_booleen_n_est_pas_une_largeur(self) -> None:
        """Régression : `True` est un entier pour Python, pas pour un calibrage.

        Un fichier édité à la main ou écrit par une version antérieure peut
        contenir `true`. Sans refus explicite, la largeur vaudrait 1 pixel :
        capture valide au sens du type, journal vide au sens du produit.
        """
        with pytest.raises(ValueError, match="entier"):
            Region.from_dict({"left": 0, "top": 0, "width": True, "height": 50})

    def test_contient_une_sous_region(self) -> None:
        ecran = Region(left=0, top=0, width=1920, height=1080)

        assert ecran.contains(Region(left=100, top=100, width=400, height=200))
        assert ecran.contains(ecran)

    def test_ne_contient_pas_ce_qui_depasse(self) -> None:
        ecran = Region(left=0, top=0, width=1920, height=1080)

        assert not ecran.contains(Region(left=1800, top=0, width=200, height=100))
        assert not ecran.contains(Region(left=0, top=1000, width=100, height=200))
        assert not ecran.contains(Region(left=-10, top=0, width=100, height=100))

    def test_le_second_ecran_ne_commence_pas_a_zero(self) -> None:
        """Régression : les coordonnées sont celles du bureau, pas de l'écran.

        Une région calibrée sur le second écran a un `left` de 1920. Un test
        qui la comparerait au rectangle du second écran ramené à l'origine la
        déclarerait hors écran, et la capture serait refusée alors qu'elle est
        parfaitement valide.
        """
        second = Region.from_mss(BUREAU[2])

        assert second.contains(Region(left=2000, top=100, width=400, height=200))
        assert not second.contains(Region(left=100, top=100, width=400, height=200))


class TestConversionEnNiveauxDeGris:
    def test_utilise_les_coefficients_de_luminance(self) -> None:
        pixel = np.array([[[10, 20, 30, 255]]], dtype=np.uint8)

        # 0,114*10 + 0,587*20 + 0,299*30 = 21,85
        assert bgra_to_gray(pixel)[0, 0] == 22

    def test_l_ordre_des_canaux_est_bgra(self) -> None:
        """Régression : mss rend du BGRA, pas du RGBA.

        Un rouge pur vaut (0, 0, 255) en BGRA. Lu comme du RGBA il donnerait
        29 au lieu de 76 : l'image reste plausible à l'œil, mais le contraste
        de tous les noms d'objets colorés est faussé, et rien ne le signale.
        """
        rouge_pur = np.array([[[0, 0, 255, 255]]], dtype=np.uint8)

        assert bgra_to_gray(rouge_pur)[0, 0] == 76

    def test_deux_couleurs_de_rarete_restent_distinctes(self) -> None:
        """Régression : la moyenne naïve des canaux confond vert et bleu.

        Les deux tombent sur 85, donc sur le même gris, alors que le jeu s'en
        sert pour distinguer deux raretés. La luminance les sépare nettement,
        ce qui préserve le contraste dont l'OCR et la détection de défilement
        dépendent.
        """
        vert = np.array([[[0, 255, 0, 255]]], dtype=np.uint8)
        bleu = np.array([[[255, 0, 0, 255]]], dtype=np.uint8)

        assert bgra_to_gray(vert)[0, 0] == 150
        assert bgra_to_gray(bleu)[0, 0] == 29

    def test_le_canal_alpha_est_ignore(self) -> None:
        """Régression : mss remplit l'alpha sans garantie.

        Un alpha nul pris pour de la transparence noircirait toute l'image, et
        le journal deviendrait illisible sans qu'aucune erreur ne soit levée.
        """
        opaque = np.array([[[10, 20, 30, 255]]], dtype=np.uint8)
        transparent = np.array([[[10, 20, 30, 0]]], dtype=np.uint8)

        assert bgra_to_gray(opaque)[0, 0] == bgra_to_gray(transparent)[0, 0]

    def test_accepte_le_bgr_sans_alpha(self) -> None:
        sans_alpha = np.array([[[10, 20, 30]]], dtype=np.uint8)

        assert bgra_to_gray(sans_alpha)[0, 0] == 22

    def test_sortie_bidimensionnelle_en_uint8(self) -> None:
        image = np.zeros((12, 30, 4), dtype=np.uint8)

        gris = bgra_to_gray(image)

        assert gris.shape == (12, 30)
        assert gris.dtype == np.uint8

    def test_refuse_une_image_deja_en_niveaux_de_gris(self) -> None:
        """Convertir deux fois doit échouer fort plutôt que rendre n'importe quoi."""
        with pytest.raises(ValueError, match="BGRA"):
            bgra_to_gray(np.zeros((12, 30), dtype=np.uint8))

    def test_refuse_un_nombre_de_canaux_inattendu(self) -> None:
        with pytest.raises(ValueError, match="BGRA"):
            bgra_to_gray(np.zeros((12, 30, 2), dtype=np.uint8))


class TestScreenCapture:
    def test_capture_une_image_en_niveaux_de_gris(self, usine: UsineMss) -> None:
        region = Region(left=100, top=100, width=400, height=200)

        with ScreenCapture() as capture:
            image = capture.grab(region)

        assert image.shape == (200, 400)
        assert image.dtype == np.uint8

    def test_transmet_la_region_au_format_mss(self, usine: UsineMss) -> None:
        region = Region(left=100, top=140, width=400, height=200)

        with ScreenCapture() as capture:
            capture.grab(region)

        assert usine.instances[0].grabs == [{"left": 100, "top": 140, "width": 400, "height": 200}]

    def test_l_instance_mss_est_reutilisee(self, usine: UsineMss) -> None:
        """Régression : une instance mss par image, à dix images par seconde.

        C'est la faute qui coûte le plus cher dans ce module. Chaque
        construction ouvre une connexion d'affichage et un contexte de
        périphérique, soit un travail système répété six cents fois par minute
        pour un résultat identique, et sous Windows des ressources graphiques
        retenues tant que l'objet n'est pas fermé.
        """
        region = Region(left=0, top=0, width=400, height=200)

        with ScreenCapture() as capture:
            for _ in range(10):
                capture.grab(region)

        assert len(usine.instances) == 1
        assert len(usine.instances[0].grabs) == 10

    def test_le_contexte_ferme_la_session(self, usine: UsineMss) -> None:
        with ScreenCapture() as capture:
            capture.grab(Region(left=0, top=0, width=400, height=200))

        assert usine.instances[0].close_calls == 1
        assert capture.closed

    def test_la_fermeture_est_idempotente(self, usine: UsineMss) -> None:
        capture = ScreenCapture()
        capture.grab(Region(left=0, top=0, width=400, height=200))

        capture.close()
        capture.close()

        assert usine.instances[0].close_calls == 1

    def test_capturer_apres_fermeture_est_refuse(self, usine: UsineMss) -> None:
        """Régression : rouvrir en silence masquerait une fuite.

        Un objet utilisé après sa portée recréerait une session mss à chaque
        capture, soit exactement le comportement que ce module existe pour
        éviter, mais sans plus rien pour le signaler.
        """
        capture = ScreenCapture()
        capture.close()

        with pytest.raises(CaptureError, match="fermée"):
            capture.grab(Region(left=0, top=0, width=400, height=200))

    def test_construire_n_ouvre_pas_de_session(self, usine: UsineMss) -> None:
        """Instancier doit rester possible là où il n'y a pas d'affichage."""
        ScreenCapture()

        assert usine.instances == []

    def test_liste_les_ecrans(self, usine: UsineMss) -> None:
        with ScreenCapture() as capture:
            ecrans = capture.monitors()

        assert len(ecrans) == 3
        assert ecrans[0] == Region(left=0, top=0, width=3520, height=1080)
        assert ecrans[2] == Region(left=1920, top=0, width=1600, height=900)

    def test_une_region_hors_ecran_leve_une_erreur(self, usine: UsineMss) -> None:
        """Régression : mss rendrait du noir sans se plaindre.

        Un calibrage fait sur un écran 2560 de large puis rejoué sur un 1920
        donne ce cas. Sans garde-fou, le journal capturé est entièrement noir,
        l'OCR ne lit rien, et le tracker affiche zéro drop en silence, ce que
        l'utilisateur ne peut attribuer à rien.
        """
        trop_a_droite = Region(left=1800, top=0, width=400, height=200)

        with ScreenCapture(monitor=1) as capture, pytest.raises(CaptureError, match="déborde"):
            capture.grab(trop_a_droite)

        assert usine.instances[0].grabs == [], "aucune capture ne doit avoir été tentée"

    def test_capture_sur_le_second_ecran(self, usine: UsineMss) -> None:
        """Le jeu peut tourner sur l'écran secondaire, cas courant en double écran."""
        region = Region(left=2000, top=100, width=400, height=200)

        with ScreenCapture(monitor=2) as capture:
            image = capture.grab(region)

        assert image.shape == (200, 400)
        assert usine.instances[0].grabs[0]["left"] == 2000

    def test_une_region_du_premier_ecran_est_refusee_sur_le_second(self, usine: UsineMss) -> None:
        """Régression : un calibrage refait après avoir changé d'écran de jeu.

        La région reste valide en soi, mais elle ne tombe plus sur l'écran
        visé. Sans le garde-fou, mss capture la zone demandée sur le bureau
        étendu, donc le mauvais écran, et le tracker lit un journal qui n'est
        pas celui du jeu.
        """
        region = Region(left=100, top=100, width=400, height=200)

        with ScreenCapture(monitor=2) as capture, pytest.raises(CaptureError, match="déborde"):
            capture.grab(region)

    def test_ecran_inexistant(self, usine: UsineMss) -> None:
        with ScreenCapture(monitor=7) as capture, pytest.raises(CaptureError, match="inexistant"):
            capture.grab(Region(left=0, top=0, width=400, height=200))

    def test_indice_d_ecran_negatif_refuse(self, usine: UsineMss) -> None:
        """Régression : l'indexation Python accepterait -1 sans rien dire.

        `monitors[-1]` désigne le dernier écran branché, donc un indice fautif
        capturerait un écran plausible mais faux, qui change en plus dès qu'un
        écran est ajouté.
        """
        with ScreenCapture(monitor=-1) as capture, pytest.raises(CaptureError, match="inexistant"):
            capture.grab(Region(left=0, top=0, width=400, height=200))
