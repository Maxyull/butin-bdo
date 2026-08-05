"""Tests de la boucle de capture à deux vitesses.

Le temps est **injecté** dans `tick(now)` plutôt que lu par la boucle. Sans ça,
tout test de cadence dépendrait du temps réel, donc serait lent et deviendrait
instable selon la charge de la machine, ce qui est la façon la plus sûre de
rendre une suite de tests inutile.
"""

from __future__ import annotations

import numpy as np
import pytest

from butin.capture.loop import CaptureLoop, LoopConfig
from butin.capture.screen import Region
from butin.catalog import ItemCatalog, ItemMatcher

ROW = 21
WIDTH = 300
RULER = 90
ROWS = 12

REGION = Region(left=0, top=0, width=WIDTH, height=ROW * ROWS)


def rendu(decalage_lignes: int) -> np.ndarray:
    """Fabrique une image dont la colonne de pastilles a défilé.

    Seule la colonne de gauche porte un motif contrasté, comme les vraies
    pastilles de canal. Le reste imite le fond transparent : du bruit qui
    n'aide en rien.
    """
    image = np.zeros((ROW * ROWS, WIDTH), dtype=np.uint8)
    for index in range(ROWS):
        valeur = (index + decalage_lignes) * 17 % 200 + 40
        image[index * ROW : index * ROW + 16, 0:RULER] = valeur
    return image


class SourceFactice:
    """Source d'images dont on pilote le défilement."""

    def __init__(self) -> None:
        self.decalage = 0

    def grab(self, region: Region) -> np.ndarray:
        return rendu(self.decalage)


class LecteurFactice:
    """Lecteur de texte qui rend des lignes prédéfinies.

    Le vrai moteur n'est jamais lancé en test : il coûte 336 ms par appel et
    la CI n'a ni écran ni captures.
    """

    def __init__(self, fenetres: list[list[str]]) -> None:
        self.fenetres = fenetres
        self.appels = 0

    def read_text(self, image: np.ndarray) -> list[str]:
        fenetre = self.fenetres[min(self.appels, len(self.fenetres) - 1)]
        self.appels += 1
        return list(fenetre)


def gain(nom: str, qty: int = 1) -> str:
    suffixe = f" x{qty}" if qty > 1 else "."
    return f"Système Vous avez obtenu : [{nom}]{suffixe} (21:54)"


@pytest.fixture
def matcher(catalog: ItemCatalog) -> ItemMatcher:
    return ItemMatcher(catalog)


def construire(fenetres: list[list[str]], matcher: ItemMatcher, **reglages: object):
    source = SourceFactice()
    lecteur = LecteurFactice(fenetres)
    config = LoopConfig(min_sightings=2, **reglages)  # type: ignore[arg-type]
    return source, lecteur, CaptureLoop(source, lecteur, matcher, REGION, config=config)


def test_le_lecteur_reel_satisfait_le_contrat_de_la_boucle() -> None:
    """Régression : ils ne se branchaient PAS, et rien ne le disait.

    Le protocole de la boucle déclarait `read_lines`, le vrai lecteur expose
    `read_text`. Tous les tests passaient, parce qu'ils utilisaient un lecteur
    simulé qui suivait le protocole au lieu de suivre le vrai lecteur. Le
    défaut ne serait apparu qu'au premier lancement réel.

    L'annotation ci-dessous est le garde-fou : mypy vérifie l'accord entre les
    deux à chaque analyse, ce qu'aucun test simulé ne peut faire.
    """
    from butin.capture.loop import LineSource
    from butin.capture.ocr import TextReader

    lecteur: LineSource = TextReader()
    assert hasattr(lecteur, "read_text")


class TestCadence:
    def test_l_ocr_ne_tourne_pas_a_chaque_tour(self, matcher: ItemMatcher) -> None:
        """Tout l'intérêt du découplage.

        La capture et la mesure de défilement coûtent moins de dix
        millisecondes, la reconnaissance en coûte 336. Les faire tourner
        ensemble reviendrait à mesurer le défilement trois fois moins souvent
        que nécessaire, pour rien.
        """
        _, lecteur, boucle = construire([[gain("Pierre noire (arme)")]], matcher)

        for pas in range(5):
            boucle.tick(now=pas * 0.10)

        assert lecteur.appels == 1, "seul le tout premier tour doit lire"

    def test_l_ocr_repart_quand_ca_defile(self, matcher: ItemMatcher) -> None:
        source, lecteur, boucle = construire(
            [[gain("Pierre noire (arme)")], [gain("Trace de sauvagerie")]], matcher
        )
        boucle.tick(now=0.0)

        source.decalage = 1
        boucle.tick(now=0.10)
        resultat = boucle.tick(now=0.50)

        assert resultat.ocr_ran
        assert lecteur.appels == 2

    def test_l_ocr_repart_apres_un_long_silence(self, matcher: ItemMatcher) -> None:
        """Régression : une ligne peut apparaître SANS défilement.

        Tant que la fenêtre du journal n'est pas pleine, ce qui est le cas au
        début d'une session, une nouvelle ligne s'ajoute en bas sans rien faire
        remonter. Sans ce filet, ces premières lignes ne seraient jamais lues.
        """
        _, lecteur, boucle = construire(
            [[gain("Pierre noire (arme)")]], matcher, ocr_max_idle_s=1.0
        )
        boucle.tick(now=0.0)

        boucle.tick(now=0.5)
        assert lecteur.appels == 1

        boucle.tick(now=1.5)
        assert lecteur.appels == 2


class TestAmorce:
    def test_le_butin_deja_a_l_ecran_n_est_pas_compte(self, matcher: ItemMatcher) -> None:
        """Sinon lancer le suivi crédite d'un coup les lignes du passé."""
        fenetre = [gain("Pierre noire (arme)"), gain("Trace de sauvagerie")]
        _, _, boucle = construire([fenetre, fenetre], matcher)

        premier = boucle.tick(now=0.0)
        assert premier.ocr_ran
        assert premier.events == []
        assert boucle.flush() == []


class TestDefilementAccumule:
    def test_le_defilement_s_accumule_entre_deux_lectures(self, matcher: ItemMatcher) -> None:
        """C'est le gain de finesse du découplage.

        Un défilement rapide vu d'un bloc à 350 ms est ici vu en plusieurs
        mesures à 100 ms, donc mesuré au lieu d'être deviné.
        """
        source, _, boucle = construire([[gain("Pierre noire (arme)")]] * 3, matcher)
        boucle.tick(now=0.0)

        source.decalage = 1
        boucle.tick(now=0.10)
        source.decalage = 2
        resultat = boucle.tick(now=0.20)

        assert resultat.pending_shift_px == pytest.approx(2 * ROW, abs=2)

    def test_une_mesure_non_sure_annule_la_prediction(self, matcher: ItemMatcher) -> None:
        """Régression : mieux vaut aucune prédiction qu'une fausse.

        Une prédiction fausse écarterait le bon recouvrement au profit d'un
        mauvais, ce qui recompterait du butin. L'alignement textuel seul reste
        correct, il est juste moins précis.
        """
        source, _, boucle = construire([[gain("Pierre noire (arme)")]] * 3, matcher)
        boucle.tick(now=0.0)

        # Une image de taille incompatible rend la mesure impossible.
        source.grab = lambda region: np.zeros((10, WIDTH), dtype=np.uint8)  # type: ignore[method-assign]
        boucle.tick(now=0.10)

        resultat = boucle.tick(now=0.50)
        assert resultat.expected_new is None


class TestComptage:
    def test_un_drop_est_compte_une_seule_fois(self, matcher: ItemMatcher) -> None:
        """Le test qui compte vraiment.

        La même fenêtre est relue plusieurs fois, comme dans la réalité où une
        ligne reste affichée une quinzaine de secondes.
        """
        avant = [gain("Pierre noire (arme)")]
        apres = [gain("Pierre noire (arme)"), gain("Trace de sauvagerie")]
        _, _, boucle = construire([avant] + [apres] * 6, matcher, ocr_max_idle_s=0.1)

        total = []
        for pas in range(1, 8):
            total += boucle.tick(now=pas * 0.4).events
        total += boucle.flush()

        identifiants = [event.item.item_id for event in total]
        assert identifiants.count(5956) == 1, "Trace de sauvagerie comptée une seule fois"

    def test_le_silver_est_accumule_a_part(self, matcher: ItemMatcher) -> None:
        """« Pièces » ne passe jamais par une recherche de prix."""
        avant = [gain("Pierre noire (arme)")]
        apres = [gain("Pierre noire (arme)"), "Système Vous avez obtenu : [Pièces] x1,000 (21:54)"]
        _, _, boucle = construire([avant, apres], matcher, ocr_max_idle_s=0.1)

        boucle.tick(now=0.0)
        resultat = boucle.tick(now=0.5)

        assert resultat.silver == 1000
        assert boucle.total_silver == 1000

    def test_le_silver_n_est_compte_que_sur_les_lignes_nouvelles(
        self, matcher: ItemMatcher
    ) -> None:
        """Une ligne de silver relue six fois ne vaut pas six fois son montant.

        Une ligne reste affichée une dizaine de secondes, donc se retrouve dans
        toutes les lectures de cet intervalle. Seule sa première apparition est
        un gain ; les suivantes sont la même ligne, toujours là.
        """
        avant = [gain("Pierre noire (arme)")]
        apres = [gain("Pierre noire (arme)"), "Système Vous avez obtenu : [Pièces] x1,000 (21:54)"]
        _, _, boucle = construire([avant] + [apres] * 6, matcher, ocr_max_idle_s=0.1)

        totaux = [boucle.tick(now=pas * 0.4).silver for pas in range(1, 8)]

        assert boucle.total_silver == 1000
        assert sum(totaux) == 1000

    def test_le_silver_ne_recompte_pas_la_fenetre_entiere(self, matcher: ItemMatcher) -> None:
        """Régression : le silver était cumulé sur toute la fenêtre à chaque lecture.

        Trouvé par le banc d'essai le 05/08/2026 sur 300 images de vrai farm.
        `CaptureLoop._read` additionnait `sum(ligne.silver for ligne in parsed)`,
        où `parsed` est la fenêtre entière et non les lignes nouvelles. Mesuré :
        **123 409 silver comptés pour 93 161 réels, soit +32,5 %**, et encore,
        avec seulement 6 lectures exploitées sur 300 images. C'était le seul
        défaut du lot qui fasse **inventer** du gain plutôt qu'en rater.

        Le motif reproduit ici est celui de la vraie rafale : le journal alterne
        une ligne de silver et une ligne d'objet, et la fenêtre en contient donc
        plusieurs en permanence.
        """
        montants = (1845, 2146, 2009, 1825)
        pieces = [
            f"Système Vous avez obtenu : [Pièces] x{montant:,} (21:54)" for montant in montants
        ]
        depart = [pieces[0], gain("Pierre noire (arme)"), pieces[1]]
        suite = [*depart, pieces[2], pieces[3]]
        _, _, boucle = construire([depart] + [suite] * 5, matcher, ocr_max_idle_s=0.1)

        for pas in range(1, 7):
            boucle.tick(now=pas * 0.4)

        # Seuls les deux montants apparus après l'amorce sont des gains. Avant
        # correction, la boucle rendait 1845 + 2146 + 2009 + 1825 par lecture
        # retenue, soit plus de sept fois ce total.
        assert boucle.total_silver == montants[2] + montants[3]


class TestImagesEcartees:
    def test_une_image_aberrante_est_ecartee_avec_son_motif(self, matcher: ItemMatcher) -> None:
        """Une image écartée sans trace serait indiscernable d'une sans butin.

        L'utilisateur voit un chiffre, jamais le raisonnement qui l'a produit :
        le motif du rejet est la seule chose qui rende un comptage faux
        diagnosticable après coup.
        """
        depart = [
            gain("Pierre noire (arme)"),
            gain("Trace de sauvagerie"),
            gain("Pierre de Caphras"),
        ]
        rupture = [gain("Fragment de mémoire")] * 3
        _, _, boucle = construire([depart, rupture], matcher, ocr_max_idle_s=0.1)

        boucle.tick(now=0.0)
        resultat = boucle.tick(now=0.5)

        assert resultat.ocr_ran
        assert resultat.skipped_reason
        assert resultat.events == []
