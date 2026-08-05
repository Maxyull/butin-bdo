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
RULER = 60
TEXTE = 90
ROWS = 12

REGION = Region(left=0, top=0, width=WIDTH, height=ROW * ROWS)


def rendu(decalage_lignes: int) -> np.ndarray:
    """Fabrique une image du journal telle que la boucle la reçoit.

    Trois éléments, et chacun a son rôle dans ce que la mesure de défilement
    doit savoir faire :

    * un **décor sombre** sur toute la largeur, parce que le fond du chat est
      transparent sur le monde du jeu ;
    * une **pastille de canal** à gauche, identique sur toutes les rangées.
      C'est ce qui la rend inutilisable comme règle de mesure : un défilement
      d'une ligne la superpose à sa voisine et n'y change rien ;
    * des **marques claires propres à chaque ligne** dans la colonne du texte,
      qui sont le seul signal où un défilement se voit.
    """
    image = np.full((ROW * ROWS, WIDTH), 20, dtype=np.uint8)
    for index in range(ROWS):
        haut = index * ROW
        image[haut + 3 : haut + 17, 5:RULER] = 200
        colonnes = np.random.default_rng(index + decalage_lignes).choice(
            WIDTH - TEXTE, size=(WIDTH - TEXTE) // 6, replace=False
        )
        image[haut + 4 : haut + 16, TEXTE + colonnes] = 230
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
    # Le seuil par défaut du produit est déjà 2 ; le répéter ici permet à un
    # test de le surcharger sans que l'argument arrive deux fois.
    config = LoopConfig(**{"min_sightings": 2, **reglages})  # type: ignore[arg-type]
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


class TestJournalPerime:
    """⭐ LE défaut trouvé au premier vrai farm, le 05/08/2026.

    Ce qui s'est passé, relevé sur 600 images de Thornwood Forest :

    * l'image 0 rend **0 ligne** — le chat était estompé et réapparaissait ;
    * l'amorce s'est donc faite sur une lecture **partielle**, 4 lignes ;
    * les quatre alignements suivants ont rendu **recouvrement 0** contre ces
      4 lignes, donc **23 lignes déclarées neuves**, quatre fois de suite ;
    * ces 23 lignes dataient de **16:40 à 17:14**, la session ayant commencé à
      **17:19**. Trente-neuf minutes de butin déjà ramassé, recompté.

    Le compteur a ainsi inventé cinq objets que le joueur n'avait pas eus.
    Mesuré sur la rafale : 104 drops / 305 unités sans le filtre, 96 / 253 avec,
    et zéro objet fantôme.

    ⚠️ L'amorce ne suffit pas et ne pouvait pas suffire : elle suppose que la
    première lecture montre la fenêtre entière. Le filtre sur l'heure ne suppose
    rien, il lit ce que le jeu écrit.
    """

    DEPART = 17 * 60 + 19

    @staticmethod
    def _ligne(nom: str, heure: str, qty: int = 1) -> str:
        suffixe = f" x{qty}" if qty > 1 else "."
        return f"Système Vous avez obtenu : [{nom}]{suffixe} ({heure})"

    def test_le_vieux_journal_n_est_pas_compte_meme_sans_amorce_utile(
        self, matcher: ItemMatcher
    ) -> None:
        """Le scénario réel, reproduit : amorce sur une lecture partielle, puis
        la fenêtre entière du passé qui réapparaît."""
        partielle = [self._ligne("Pierre noire (arme)", "17:19")]
        ancienne = [
            self._ligne("Trace de sauvagerie", "16:40"),
            self._ligne("Fragment de mémoire", "17:07"),
            self._ligne("Pierre de Caphras", "17:10"),
            self._ligne("Pierre noire (arme)", "17:19"),
        ]
        source = SourceFactice()
        lecteur = LecteurFactice([partielle] + [ancienne] * 8)
        boucle = CaptureLoop(
            source,
            lecteur,
            matcher,
            REGION,
            config=LoopConfig(min_sightings=2),
            session_start_min=self.DEPART,
        )

        comptes: list[str] = []
        for tour in range(9):
            comptes += [e.item.name("fr") for e in boucle.tick(now=tour * 0.5).events]
        comptes += [e.item.name("fr") for e in boucle.flush()]

        assert "Trace de sauvagerie" not in comptes
        assert "Fragment de mémoire" not in comptes
        assert "Pierre de Caphras" not in comptes

    def test_sans_le_filtre_le_meme_scenario_invente_des_drops(self, matcher: ItemMatcher) -> None:
        """La contre-épreuve. Un garde-fou qui ne peut pas échouer ne garde rien.

        Sans `session_start_min`, exactement le même enchaînement crédite le
        butin du passé : c'est le comportement qu'on vient de corriger.
        """
        partielle = [self._ligne("Pierre noire (arme)", "17:19")]
        ancienne = [
            self._ligne("Trace de sauvagerie", "16:40"),
            self._ligne("Fragment de mémoire", "17:07"),
            self._ligne("Pierre de Caphras", "17:10"),
            self._ligne("Pierre noire (arme)", "17:19"),
        ]
        _, _, boucle = construire([partielle] + [ancienne] * 8, matcher)

        comptes: list[str] = []
        for tour in range(9):
            comptes += [e.item.name("fr") for e in boucle.tick(now=tour * 0.5).events]
        comptes += [e.item.name("fr") for e in boucle.flush()]

        assert "Trace de sauvagerie" in comptes, "le scénario ne reproduit plus le défaut"

    def test_le_butin_du_farm_est_toujours_compte(self, matcher: ItemMatcher) -> None:
        """⚠️ Le filtre ne doit pas manger ce qui tombe vraiment.

        Une correction qui supprimerait le sur-comptage en cessant de compter
        serait pire que le défaut : elle serait invisible.
        """
        depart = [self._ligne("Trace de sauvagerie", "16:40")]
        apres = [
            self._ligne("Trace de sauvagerie", "16:40"),
            self._ligne("Pierre noire (arme)", "17:20"),
            self._ligne("Fragment de mémoire", "17:20"),
        ]
        source = SourceFactice()
        lecteur = LecteurFactice([depart] + [apres] * 8)
        boucle = CaptureLoop(
            source,
            lecteur,
            matcher,
            REGION,
            config=LoopConfig(min_sightings=2),
            session_start_min=self.DEPART,
        )

        comptes: list[str] = []
        for tour in range(9):
            comptes += [e.item.name("fr") for e in boucle.tick(now=tour * 0.5).events]
        comptes += [e.item.name("fr") for e in boucle.flush()]

        assert "Pierre noire (arme)" in comptes
        assert "Fragment de mémoire" in comptes
        assert "Trace de sauvagerie" not in comptes

    def test_sans_heure_de_depart_rien_n_est_filtre(self, matcher: ItemMatcher) -> None:
        """Le banc d'essai rejoue des rafales dont il ignore l'heure de départ.

        Il doit continuer de mesurer la boucle, et non ce filtre.
        """
        fenetre = [self._ligne("Trace de sauvagerie", "16:40")]
        _, _, boucle = construire([fenetre] * 4, matcher)

        assert boucle.session_start_min is None

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

    def test_le_defilement_mesure_devient_une_prediction(self, matcher: ItemMatcher) -> None:
        """Régression : la mesure ne détectait plus rien, donc ne prédisait rien.

        La règle de mesure était la colonne des pastilles de canal. Mesuré par
        le banc d'essai le 05/08/2026 sur 300 images de vrai farm : **zéro
        détection sûre sur 299 transitions**. `expected_new` valait donc
        toujours None, l'alignement travaillait sur le texte seul, et la boucle
        ne déclenchait plus la reconnaissance que sur son minuteur de repli de
        deux secondes, soit 15 images lues sur 300.

        La règle est maintenant la colonne du **texte**, comparée sur un masque
        de pixels clairs : 32 détections justes sur 37, et 22 images lues.
        """
        # Une fenêtre de plusieurs lignes : la prédiction est bornée par le
        # nombre de lignes visibles, et deux lignes nouvelles dans une fenêtre
        # d'une seule n'a pas de sens.
        fenetre = [gain("Pierre noire (arme)", qty) for qty in range(1, 5)]
        source, _, boucle = construire([fenetre] * 3, matcher)
        boucle.tick(now=0.0)

        source.decalage = 2
        boucle.tick(now=0.10)
        resultat = boucle.tick(now=0.50)

        assert resultat.expected_new == 2

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
        """« Pièces » ne passe jamais par une recherche de prix.

        Le montant est crédité au vote, comme la quantité d'un objet, donc
        après plusieurs lectures concordantes et non à la première apparition.
        """
        avant = [gain("Pierre noire (arme)")]
        apres = [gain("Pierre noire (arme)"), "Système Vous avez obtenu : [Pièces] x1,000 (21:54)"]
        _, _, boucle = construire([avant] + [apres] * 2, matcher, ocr_max_idle_s=0.1)

        boucle.tick(now=0.0)
        boucle.tick(now=0.5)
        resultat = boucle.tick(now=1.0)

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


class TestSeuilDeValidation:
    """Combien de fois une ligne doit être vue avant d'être comptée.

    La fenêtre fait 8 lignes et le journal reçoit une ligne par capture, donc
    une ligne reste huit captures à l'écran. La boucle n'en lit qu'une sur
    quatre : chaque ligne est donc vue **exactement deux fois**. C'est le régime
    réel, mesuré au banc, et c'est là que le seuil se joue.
    """

    def _compte(self, matcher: ItemMatcher, seuil: int) -> tuple[int, int]:
        flux = [gain("Pierre noire (arme)", (index % 3) + 1) for index in range(60)]
        fenetres = [flux[debut : debut + 8] for debut in range(len(flux) - 7)]
        source, _, boucle = construire(fenetres, matcher, min_sightings=seuil)

        evenements = []
        for pas, _ in enumerate(fenetres):
            # Les pixels défilent avec le texte, sinon la boucle ne déclenche
            # jamais de lecture anticipée et le régime testé n'existe pas.
            source.decalage = pas
            evenements += boucle.tick(now=pas * 0.1).events
        evenements += boucle.flush()
        return len(evenements), sum(event.qty for event in evenements)

    def test_deux_observations_comptent_tout_le_butin(self, matcher: ItemMatcher) -> None:
        """Le vote ne coûte aucun drop tant que la ligne est vue deux fois."""
        assert self._compte(matcher, 2) == (52, 105)

    def test_en_attendre_une_de_plus_fait_perdre_du_butin(self, matcher: ItemMatcher) -> None:
        """Régression : monter le seuil « par prudence » dégrade le résultat.

        Contre-intuitif, et mesuré. Ici la ligne est vue exactement deux fois
        avant de sortir de l'écran : en exiger trois ne les rend pas plus sûres,
        ça les fait disparaître. La chute est brutale, de 52 drops à 8.

        Le balayage du 05/08/2026 sur la rafale du banc donne le même verdict à
        quatre cadences de lecture différentes : 47 drops sur 47 avec un seuil
        de 2, 46 à 3, 41 à 4, et seulement 20 à 4 quand la lecture ralentit.
        2 est le meilleur des quatre valeurs à **chacune** des quatre cadences,
        ce qui en fait un choix mesuré et non un point de chance.
        """
        drops_a_deux, _ = self._compte(matcher, 2)
        drops_a_trois, _ = self._compte(matcher, 3)

        assert drops_a_trois < drops_a_deux / 2


class TestSilverAuVote:
    def test_un_montant_illisible_est_corrige_par_les_autres_lectures(
        self, matcher: ItemMatcher
    ) -> None:
        """Régression : le montant était lu une seule fois, sans rattrapage.

        Le montant de silver est un **nombre à quatre chiffres**, donc bien
        plus fragile à l'OCR qu'un nom d'objet, que la reconnaissance floue
        rattrape. Mesuré par le banc d'essai le 05/08/2026 sur 300 images de
        vrai farm : **13,6 % des lectures de lignes de silver ont un montant
        illisible** (470 sur 3 456), contre 4 lignes sur 45 dans une référence
        qui tranche chaque position au vote.

        Une lecture ratée coûtait donc environ deux mille silver, définitivement.
        Ici la ligne est lue trois fois, dont une fois avec le « x » mangé, et
        le vote doit rendre le vrai montant.
        """
        avant = [gain("Pierre noire (arme)")]
        nette = "Système Vous avez obtenu : [Pièces] x1,845 (21:54)"
        abimee = "Système Vous avez obtenu : [Pièces] x?,84S (21:54)"
        _, _, boucle = construire(
            [avant, [*avant, abimee], [*avant, nette], [*avant, nette]],
            matcher,
            ocr_max_idle_s=0.1,
        )

        for pas in range(4):
            boucle.tick(now=pas * 0.5)

        assert boucle.total_silver == 1845

    def test_le_silver_encore_a_l_ecran_est_credite_a_l_arret(self, matcher: ItemMatcher) -> None:
        """Sinon faire voter les montants perdrait une fenêtre entière.

        Une ligne vue une seule fois n'a pas atteint le seuil de validation. À
        l'arrêt de la session il n'y aura pas d'autre lecture : ce qui attend
        doit être crédité, exactement comme les drops le sont déjà.
        """
        avant = [gain("Pierre noire (arme)")]
        apres = [*avant, "Système Vous avez obtenu : [Pièces] x2,146 (21:54)"]
        _, _, boucle = construire([avant, apres], matcher, ocr_max_idle_s=0.1)

        boucle.tick(now=0.0)
        boucle.tick(now=0.5)
        assert boucle.total_silver == 0, "une seule lecture ne suffit pas à trancher"

        boucle.flush()

        assert boucle.total_silver == 2146


class TestPlafondDeVraisemblance:
    def test_une_lecture_espacee_de_deux_secondes_n_est_pas_jetee(
        self, matcher: ItemMatcher
    ) -> None:
        """Régression : le plafond supposait une cadence que la boucle n'a pas.

        La boucle capture toutes les 100 ms mais ne fait lire le texte qu'une
        fois par seconde au mieux, et jusqu'à une fois toutes les deux secondes
        quand aucun défilement ne déclenche de lecture anticipée. Le plafond de
        dix nouvelles lignes, justifié par « pas dix lignes en un dixième de
        seconde », s'appliquait pourtant tel quel.

        Mesuré par le banc d'essai le 05/08/2026 : une lecture portant
        **14 lignes réellement nouvelles** après deux secondes était rejetée
        comme un saut invraisemblable, donc quatorze lignes de journal perdues
        d'un seul coup.
        """
        depart = [gain("Pierre noire (arme)", qty) for qty in range(1, 17)]
        apres = [*depart[-2:], *[gain("Pierre de Caphras", qty) for qty in range(1, 15)]]
        _, _, boucle = construire([depart, apres], matcher, ocr_max_idle_s=0.1)

        boucle.tick(now=0.0)
        resultat = boucle.tick(now=2.0)

        assert resultat.skipped_reason == ""
        assert resultat.ocr_ran

    def test_le_meme_saut_en_un_dixieme_de_seconde_reste_refuse(self, matcher: ItemMatcher) -> None:
        """L'autre bord : quatorze lignes en 100 ms restent invraisemblables.

        Le plafond suit l'intervalle, il ne disparaît pas. Le supprimer
        laisserait passer une estimation de recouvrement aberrante, qui est
        exactement la façon dont des doublons se glissent dans le total.
        """
        depart = [gain("Pierre noire (arme)", qty) for qty in range(1, 17)]
        apres = [*depart[-2:], *[gain("Pierre de Caphras", qty) for qty in range(1, 15)]]
        _, _, boucle = construire(
            [depart, apres], matcher, ocr_min_interval_s=0.0, ocr_max_idle_s=0.0
        )

        boucle.tick(now=0.0)
        resultat = boucle.tick(now=0.1)

        assert "saut invraisemblable" in resultat.skipped_reason


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
