"""Tests du contrôle objet par objet, contre l'inventaire du joueur.

⭐ C'est la seule mesure de ce logiciel qui ne passe par AUCUNE reconnaissance
d'écran. Le compteur et le banc d'essai lisent les mêmes pixels avec le même
moteur : ils peuvent se tromper ensemble, et seul un inventaire compté à la
main peut les contredire tous les deux.

⛔ Le fil rouge de ce fichier est le troisième état. « Pas vérifié » n'est pas
« exact », et la moitié des tests ci-dessous ne servent qu'à empêcher qu'on les
confonde un jour par commodité.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from butin.store import SessionStore
from butin.store.db import LootRow


@pytest.fixture
def store(tmp_path: Path) -> SessionStore:
    return SessionStore(tmp_path / "sessions.sqlite3")


def _session_avec_butin(store: SessionStore) -> int:
    """Une session terminée, avec trois objets de vraies quantités.

    Les chiffres viennent de la session réelle du 05/08/2026 documentée dans le
    guide : 97 Poudres comptées pour 84 réelles, l'écart de +15 % qui a lancé
    toute cette recherche.
    """
    session = store.start_session(started_at=time.time())
    store.add_loot(
        session.id,
        [
            LootRow(item_id=44451, qty=97, at=time.time()),
            LootRow(item_id=16001, qty=13, at=time.time()),
            LootRow(item_id=721003, qty=9, at=time.time()),
        ],
    )
    store.end_session(session.id, ended_at=time.time())
    return session.id


class TestPasVerifieEstUnEtat:
    def test_un_objet_non_saisi_n_a_PAS_de_ligne(self, store: SessionStore) -> None:
        """⛔ Le test qui porte toute la conception.

        Raison donnée par Maxime : certains objets partent dans un autre
        inventaire (monture, serviteur) et personne n'ira les compter. Écrire
        une ligne pour eux — même à zéro, même égale au compte — les ferait
        passer pour vérifiés. Ne rien écrire est la seule façon honnête de dire
        qu'on ne sait pas.
        """
        session_id = _session_avec_butin(store)
        store.set_item_controls(session_id, {44451: (97, 84), 16001: (13, 13)})
        controles = store.item_controls(session_id)
        assert 721003 not in controles, "un objet non vérifié a quand même une ligne"
        assert set(controles) == {44451, 16001}

    def test_une_session_sans_controle_ne_rend_rien(self, store: SessionStore) -> None:
        session_id = _session_avec_butin(store)
        assert store.item_controls(session_id) == {}


class TestEcartCalcule:
    def test_l_ecart_est_la_somme_signee_des_objets_verifies(self, store: SessionStore) -> None:
        """Positif quand le compteur a annoncé PLUS que la réalité.

        C'est le sens qui compte : un écart positif veut dire qu'il a inventé,
        et c'est l'erreur que ce projet refuse en premier. L'inverser rendrait
        chaque relevé illisible sans en changer une valeur.
        """
        session_id = _session_avec_butin(store)
        ecart = store.set_item_controls(session_id, {44451: (97, 84), 16001: (13, 13)})
        assert ecart == 13

    def test_un_sous_comptage_donne_un_ecart_NEGATIF(self, store: SessionStore) -> None:
        session_id = _session_avec_butin(store)
        assert store.set_item_controls(session_id, {44451: (97, 100)}) == -3

    def test_l_objet_non_verifie_ne_compte_pas_dans_l_ecart(self, store: SessionStore) -> None:
        """Sinon un contrôle partiel se lirait comme un contrôle complet.

        Compter les objets non regardés comme exacts gonflerait artificiellement
        la part de « juste », et ferait passer pour mesuré ce qui ne l'est pas.
        """
        session_id = _session_avec_butin(store)
        ecart = store.set_item_controls(session_id, {44451: (97, 84)})
        assert ecart == 13, "l'objet laissé de côté a été compté comme exact"


class TestRefaireUnControle:
    def test_un_second_controle_REMPLACE_le_premier(self, store: SessionStore) -> None:
        """⛔ Régression : deux constats empilés rendraient le total faux.

        Un joueur qui refait son contrôle corrige ce qu'il avait dit, il n'en
        ajoute pas un second. Compléter au lieu de remplacer ferait dépendre
        l'écart de l'ordre des saisies, donc du hasard.
        """
        session_id = _session_avec_butin(store)
        store.set_item_controls(session_id, {44451: (97, 84), 16001: (13, 13)})
        ecart = store.set_item_controls(session_id, {44451: (97, 97)})
        assert ecart == 0
        assert set(store.item_controls(session_id)) == {44451}


class TestMigration:
    def test_une_base_v3_se_relit_sans_perdre_son_historique(self, tmp_path: Path) -> None:
        """⛔ La perte qu'on ne pardonne pas à un outil dont le rôle est de compter.

        La table du contrôle est ajoutée par `CREATE TABLE IF NOT EXISTS`, donc
        une base d'avant la garde intacte. Ce test le vérifie au lieu de le
        supposer : les deux migrations précédentes ont dû ajouter des colonnes
        à la main pour cette raison exacte.
        """
        chemin = tmp_path / "sessions.sqlite3"
        premiere = SessionStore(chemin)
        session_id = _session_avec_butin(premiere)
        premiere.close()

        seconde = SessionStore(chemin)
        try:
            assert seconde.get_session(session_id) is not None
            assert sum(seconde.quantities(session_id).values()) == 97 + 13 + 9
            assert seconde.item_controls(session_id) == {}
        finally:
            seconde.close()
