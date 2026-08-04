"""Tests de l'interface web locale.

Le serveur est lancé pour de vrai sur un port libre de la boucle locale, puis
interrogé. C'est un vrai serveur mais pas un vrai navigateur : ce qui est
vérifié ici, c'est le contrat de l'API et l'adresse d'écoute.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from butin.market import PriceBook, PriceCache
from butin.store import LootRow, SessionStore
from butin.ui.server import HOST, AppState, build_server

# Le projet transforme tout avertissement en erreur, ce qui est voulu partout
# ailleurs. Ici, arrêter un vrai serveur HTTP pendant qu'une connexion vient
# d'être servie fait remonter un avertissement de socket au ramasse-miettes,
# depuis un fil de travail. C'est un artefact du démontage du serveur de test,
# pas un défaut du code testé, et il n'existe que parce que ces tests lancent
# un serveur réel plutôt que de le simuler, ce qui reste le bon choix.
pytestmark = pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")


@pytest.fixture
def app(tmp_path: Path):
    store = SessionStore(tmp_path / "sessions.sqlite3")
    book = PriceBook(
        client=None,
        cache=PriceCache(tmp_path / "prix.json"),
        vendor_values={43984: {"base": 500}},
    )
    state = AppState(store, book)
    serveur = build_server(state, port=0)
    fil = threading.Thread(target=serveur.serve_forever, daemon=True)
    fil.start()
    try:
        yield state, f"http://{HOST}:{serveur.server_address[1]}"
    finally:
        serveur.shutdown()
        serveur.server_close()
        store.close()


def get(base: str, chemin: str) -> Any:
    with urllib.request.urlopen(base + chemin, timeout=5) as reponse:  # noqa: S310
        return json.loads(reponse.read())


def post(base: str, chemin: str, corps: dict[str, Any] | None = None) -> Any:
    # L'URL est construite par le test à partir du port que le serveur vient
    # d'ouvrir sur la boucle locale, jamais d'une entrée externe.
    requete = urllib.request.Request(  # noqa: S310
        base + chemin,
        data=json.dumps(corps or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(requete, timeout=5) as reponse:  # noqa: S310
        return json.loads(reponse.read())


class TestSecurite:
    def test_ecoute_uniquement_sur_la_boucle_locale(self, app) -> None:
        """Régression : la différence n'est pas cosmétique.

        Écouter sur 0.0.0.0 exposerait l'historique de farm à tout le réseau
        local, donc à un réseau partagé ou à un point d'accès public, sans que
        rien ne le signale à l'utilisateur. Et il n'y a ni authentification ni
        jeton, ce qui n'est acceptable QUE parce que rien d'extérieur ne peut
        atteindre le port.
        """
        assert HOST == "127.0.0.1"

    def test_pas_d_en_tete_cors(self, app) -> None:
        """Sans en-tête CORS, la politique de même origine du navigateur
        empêche une page quelconque ouverte dans un autre onglet d'interroger
        ce serveur à l'insu de l'utilisateur."""
        _, base = app
        with urllib.request.urlopen(base + "/api/etat", timeout=5) as reponse:  # noqa: S310
            assert "Access-Control-Allow-Origin" not in reponse.headers

    def test_traversee_de_repertoire_refusee(self, app) -> None:
        """Sans garde-fou, une requête vers un chemin relatif se servirait
        ailleurs sur le disque."""
        _, base = app
        with pytest.raises(urllib.error.HTTPError) as erreur:
            get(base, "/../../pyproject.toml")
        assert erreur.value.code == 404

    def test_route_inconnue(self, app) -> None:
        _, base = app
        with pytest.raises(urllib.error.HTTPError) as erreur:
            get(base, "/api/inexistant")
        assert erreur.value.code == 404


class TestPage:
    def test_la_page_se_sert(self, app) -> None:
        _, base = app
        with urllib.request.urlopen(base + "/", timeout=5) as reponse:  # noqa: S310
            corps = reponse.read().decode("utf-8")
        assert "Butin" in corps
        assert 'id="langue"' in corps
        assert 'id="region"' in corps


class TestSliders:
    def test_les_deux_sliders_sont_dans_l_etat(self, app) -> None:
        _, base = app
        reglages = get(base, "/api/etat")["reglages"]
        assert reglages["langue"] == "fr"
        assert reglages["region"] == "eu"

    def test_changer_de_region(self, app) -> None:
        _, base = app
        etat = post(base, "/api/reglages", {"region": "na"})
        assert etat["reglages"]["region"] == "na"

    def test_changer_de_langue(self, app) -> None:
        _, base = app
        etat = post(base, "/api/reglages", {"langue": "us"})
        assert etat["reglages"]["langue"] == "us"

    def test_une_valeur_refusee_ne_change_rien(self, app) -> None:
        """Régression : le serveur est la source de vérité, pas le clic.

        Une valeur invalide doit laisser l'état intact plutôt que d'écrire
        n'importe quoi, sans quoi une région inexistante ferait échouer toutes
        les requêtes de prix ensuite.
        """
        _, base = app
        etat = post(base, "/api/reglages", {"region": "lune", "langue": "klingon"})
        assert etat["reglages"]["region"] == "eu"
        assert etat["reglages"]["langue"] == "fr"

    def test_un_taux_de_taxe_absurde_est_refuse(self, app) -> None:
        _, base = app
        for absurde in (0, -1, 2.5):
            etat = post(base, "/api/reglages", {"taux_marche": absurde})
            assert etat["reglages"]["taux_marche"] != absurde


class TestSession:
    def test_demarrer_et_arreter(self, app) -> None:
        _, base = app
        etat = post(base, "/api/session/demarrer", {"spot": "Sausan"})
        assert etat["session"]["en_cours"]
        assert etat["session"]["spot"] == "Sausan"

        etat = post(base, "/api/session/arreter")
        assert etat["session"] is None

    def test_demarrer_deux_fois_ne_cree_qu_une_session(self, app) -> None:
        """Régression : la seconde laisserait la première ouverte pour
        toujours, donc une durée qui gonfle sans fin dans la base."""
        state, base = app
        premier = post(base, "/api/session/demarrer")["session"]["id"]
        second = post(base, "/api/session/demarrer")["session"]["id"]

        assert premier == second
        assert len(state.store.sessions()) == 1

    def test_arreter_sans_session_ne_plante_pas(self, app) -> None:
        _, base = app
        assert post(base, "/api/session/arreter")["session"] is None


class TestButin:
    def test_le_butin_apparait_avec_sa_provenance(self, app) -> None:
        state, base = app
        session_id = post(base, "/api/session/demarrer")["session"]["id"]
        state.store.add_loot(session_id, [LootRow(item_id=43984, qty=4, at=1.0)])

        etat = get(base, "/api/etat")
        ligne = etat["butin"][0]

        assert ligne["quantite"] == 4
        assert ligne["valeur_totale"] == 2000
        assert ligne["source"] == "vendeur"

    def test_un_objet_sans_catalogue_reste_identifiable(self, app) -> None:
        """Repli sur l'identifiant plutôt que sur une chaîne vide.

        Une ligne sans nom serait indistinguable des autres dans le tableau,
        alors qu'un « #43984 » se cherche et se corrige.
        """
        state, base = app
        session_id = post(base, "/api/session/demarrer")["session"]["id"]
        state.store.add_loot(session_id, [LootRow(item_id=43984, qty=1, at=1.0)])

        assert get(base, "/api/etat")["butin"][0]["nom"] == "#43984"

    def test_les_lignes_sont_triees_par_valeur(self, app) -> None:
        """Ce qui rapporte le plus doit être en haut, pas ce qui est tombé en
        premier : c'est la question que l'utilisateur se pose."""
        state, base = app
        session_id = post(base, "/api/session/demarrer")["session"]["id"]
        state.book.vendor_values[44069] = {"base": 6200}
        state.store.add_loot(
            session_id,
            [LootRow(item_id=43984, qty=1, at=1.0), LootRow(item_id=44069, qty=1, at=2.0)],
        )

        valeurs = [ligne["valeur_totale"] for ligne in get(base, "/api/etat")["butin"]]
        assert valeurs == sorted(valeurs, reverse=True)

    def test_sans_session_l_etat_reste_valide(self, app) -> None:
        _, base = app
        etat = get(base, "/api/etat")
        assert etat["session"] is None
        assert etat["butin"] == []
