"""Tests du pont entre la boucle de capture et la base des sessions.

C'est ici que la chaîne entière se vérifie de bout en bout : des lignes de texte
lues à l'écran jusqu'à un total en base, en passant par la reconnaissance,
l'anti-double-comptage et la validation multi-images.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from butin.capture.loop import CaptureLoop, LoopConfig
from butin.capture.screen import Region
from butin.catalog import ItemCatalog, ItemMatcher
from butin.recorder import SessionRecorder
from butin.store import SessionStore

ROW, WIDTH, RULER, ROWS = 21, 300, 90, 12
REGION = Region(left=0, top=0, width=WIDTH, height=ROW * ROWS)


def rendu(decalage: int) -> np.ndarray:
    image = np.zeros((ROW * ROWS, WIDTH), dtype=np.uint8)
    for index in range(ROWS):
        image[index * ROW : index * ROW + 16, 0:RULER] = (index + decalage) * 17 % 200 + 40
    return image


class Source:
    def __init__(self) -> None:
        self.decalage = 0

    def grab(self, region: Region) -> np.ndarray:
        return rendu(self.decalage)


class Lecteur:
    def __init__(self, fenetres: list[list[str]]) -> None:
        self.fenetres = fenetres
        self.appels = 0

    def read_text(self, image: np.ndarray) -> list[str]:
        fenetre = self.fenetres[min(self.appels, len(self.fenetres) - 1)]
        self.appels += 1
        return list(fenetre)


def gain(nom: str, qty: int = 1) -> str:
    return f"Système Vous avez obtenu : [{nom}]{f' x{qty}' if qty > 1 else '.'} (21:54)"


@pytest.fixture
def monte(tmp_path: Path, catalog: ItemCatalog):
    store = SessionStore(tmp_path / "sessions.sqlite3")

    def construire(fenetres: list[list[str]], **reglages: object) -> SessionRecorder:
        defauts: dict[str, object] = {"min_sightings": 2, "ocr_max_idle_s": 0.1}
        defauts.update(reglages)
        boucle = CaptureLoop(
            Source(),
            Lecteur(fenetres),
            ItemMatcher(catalog),
            REGION,
            config=LoopConfig(**defauts),  # type: ignore[arg-type]
        )
        session = store.start_session(started_at=0.0, spot="Sausan")
        return SessionRecorder(boucle, store, session.id)

    yield construire, store
    store.close()


class TestEnregistrement:
    def test_un_drop_confirme_arrive_en_base(self, monte) -> None:
        construire, store = monte
        base = [gain("Pierre noire (arme)")]
        suite = [gain("Pierre noire (arme)"), gain("Trace de sauvagerie")]
        enregistreur = construire([base] + [suite] * 5)

        for pas in range(6):
            enregistreur.tick(now=pas * 0.5)
        enregistreur.flush(now=10.0)

        quantites = store.quantities(enregistreur.session_id)
        assert quantites.get((5956, 0)) == 1

    def test_l_ecriture_est_immediate_et_pas_differee(self, monte) -> None:
        """Régression : accumuler en mémoire perdrait toute la session.

        Une session dure des heures. Un plantage, une coupure ou un arrêt
        brutal du jeu ne doit pas effacer ce qui est déjà tombé, alors que
        c'est exactement ce que ferait un enregistrement groupé à l'arrêt.
        """
        construire, store = monte
        base = [gain("Pierre noire (arme)")]
        suite = [gain("Pierre noire (arme)"), gain("Trace de sauvagerie")]
        enregistreur = construire([base] + [suite] * 5)

        for pas in range(5):
            enregistreur.tick(now=pas * 0.5)

        # Sans flush : ce qui est confirmé doit déjà être en base.
        assert store.loot_count(enregistreur.session_id) > 0

    def test_le_butin_deja_a_l_ecran_n_est_pas_enregistre(self, monte) -> None:
        """L'amorce de la boucle vaut aussi pour la base.

        Sinon lancer le suivi crediterait d'un coup les dernières lignes du
        journal, qui appartiennent au passé.
        """
        construire, store = monte
        fenetre = [gain("Pierre noire (arme)"), gain("Trace de sauvagerie")]
        enregistreur = construire([fenetre, fenetre])

        enregistreur.tick(now=0.0)

        assert store.loot_count(enregistreur.session_id) == 0

    def test_un_drop_n_est_enregistre_qu_une_fois(self, monte) -> None:
        """Le test qui compte : la fenêtre est relue des dizaines de fois."""
        construire, store = monte
        base = [gain("Pierre noire (arme)")]
        suite = [gain("Pierre noire (arme)"), gain("Trace de sauvagerie")]
        enregistreur = construire([base] + [suite] * 20)

        for pas in range(20):
            enregistreur.tick(now=pas * 0.5)
        enregistreur.flush(now=100.0)

        assert store.quantities(enregistreur.session_id).get((5956, 0)) == 1

    def test_le_silver_suit_un_chemin_separe(self, monte) -> None:
        """Il est déjà exprimé dans l'unité finale et ne passe jamais par une
        recherche de prix."""
        construire, store = monte
        base = [gain("Pierre noire (arme)")]
        suite = [
            gain("Pierre noire (arme)"),
            "Système Vous avez obtenu : [Pièces] x2,500 (21:54)",
        ]
        enregistreur = construire([base] + [suite] * 4)

        for pas in range(4):
            enregistreur.tick(now=pas * 0.5)

        session = store.get_session(enregistreur.session_id)
        assert session.silver_direct == enregistreur.recorded_silver
        assert session.silver_direct > 0

    def test_le_flush_recupere_le_butin_de_fin_de_session(self, monte) -> None:
        """Sans lui, le butin vu une seule fois au moment de l'arrêt serait
        perdu alors qu'il est bien tombé."""
        construire, store = monte
        base = [gain("Pierre noire (arme)")]
        suite = [gain("Pierre noire (arme)"), gain("Fragment de mémoire")]
        enregistreur = construire([base, suite], min_sightings=9)

        enregistreur.tick(now=0.0)
        enregistreur.tick(now=0.5)
        avant = store.loot_count(enregistreur.session_id)

        enregistreur.flush(now=1.0)

        assert store.loot_count(enregistreur.session_id) > avant


class TestDiagnostic:
    def test_les_images_ecartees_sont_comptees(self, monte) -> None:
        """Un compteur qui grimpe signale un problème de CALIBRAGE, pas une
        absence de butin. C'est la seule façon de distinguer les deux depuis
        l'extérieur, où l'on ne voit qu'un total qui ne bouge pas.
        """
        construire, _ = monte
        depart = [
            gain("Pierre noire (arme)"),
            gain("Trace de sauvagerie"),
            gain("Pierre de Caphras"),
        ]
        rupture = [gain("Fragment de mémoire")] * 3
        enregistreur = construire([depart, rupture])

        enregistreur.tick(now=0.0)
        enregistreur.tick(now=0.5)

        assert enregistreur.skipped_frames == 1

    def test_les_compteurs_suivent_la_base(self, monte) -> None:
        construire, store = monte
        base = [gain("Pierre noire (arme)")]
        suite = [gain("Pierre noire (arme)"), gain("Trace de sauvagerie")]
        enregistreur = construire([base] + [suite] * 5)

        for pas in range(5):
            enregistreur.tick(now=pas * 0.5)
        enregistreur.flush(now=10.0)

        assert enregistreur.recorded_events == store.loot_count(enregistreur.session_id)


class TestSessionsSeparees:
    def test_deux_sessions_ne_se_melangent_pas(self, monte) -> None:
        construire, store = monte
        base = [gain("Pierre noire (arme)")]
        suite = [gain("Pierre noire (arme)"), gain("Trace de sauvagerie")]

        une = construire([base] + [suite] * 5)
        deux = construire([base] + [suite] * 5)

        for pas in range(5):
            une.tick(now=pas * 0.5)
        une.flush(now=10.0)

        assert store.loot_count(une.session_id) > 0
        assert store.loot_count(deux.session_id) == 0


class TestSpotDetecteEnFrancais:
    """detect_spot() rend un nom anglais (clé de regroupement de zones.py) ;
    detected_spot doit le traduire avant de nommer une session, sinon un
    produit pensé pour le client français en jeu depuis la première ligne
    nommerait ses sessions en anglais.

    Manipule `_seen_ids`/`_zones`/`_zone_translations` directement plutôt que
    de faire vraiment tomber un objet : ce qui est en jeu ici est la
    traduction, pas la détection elle-même, déjà couverte par test_zones.py.
    """

    def test_le_spot_detecte_est_traduit(self, monte) -> None:
        construire, _ = monte
        enregistreur = construire([["rien"]])
        enregistreur._zones = {43984: ("Abandoned Iron Mine",)}
        enregistreur._zone_translations = {"Abandoned Iron Mine": "Mine de fer abandonnée"}
        enregistreur._seen_ids = {43984}

        assert enregistreur.detected_spot == "Mine de fer abandonnée"

    def test_une_zone_sans_traduction_connue_reste_en_anglais(self, monte) -> None:
        """Un nom anglais reste plus utile qu'aucun nom : voir la docstring
        de `detected_spot`."""
        construire, _ = monte
        enregistreur = construire([["rien"]])
        enregistreur._zones = {43984: ("Zone Toute Neuve",)}
        enregistreur._zone_translations = {}
        enregistreur._seen_ids = {43984}

        assert enregistreur.detected_spot == "Zone Toute Neuve"
