"""Tests de l'interface web locale.

Le serveur est lancé pour de vrai sur un port libre de la boucle locale, puis
interrogé. C'est un vrai serveur mais pas un vrai navigateur : ce qui est
vérifié ici, c'est le contrat de l'API et l'adresse d'écoute.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from butin import paths
from butin.capture.calibrate import Calibration
from butin.capture.screen import Region
from butin.capture.worker import CaptureStatus, CaptureUnavailable
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
def store(tmp_path: Path) -> SessionStore:
    return SessionStore(tmp_path / "sessions.sqlite3")


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


class TestCapture:
    """La capture, vue depuis l'interface. Le dernier maillon du produit."""

    class _Travailleur:
        """Faux fil de capture, piloté par le test."""

        def __init__(self, *, refuse: str = "") -> None:
            self.refuse = refuse
            self.demarre: list[int] = []
            self.arrets = 0

        def start(self, session_id: int) -> None:
            if self.refuse:
                raise CaptureUnavailable(self.refuse)
            self.demarre.append(session_id)

        def stop(self, *, timeout: float = 5.0) -> int:
            self.arrets += 1
            return 0

        def status(self) -> CaptureStatus:
            return CaptureStatus(
                running=bool(self.demarre) and not self.arrets,
                ticks=12,
                ocr_reads=3,
                skipped_frames=0,
                lost_resolved=0,
                recorded_events=2,
                recorded_silver=500,
            )

    def test_demarrer_lance_la_capture(self, store: SessionStore) -> None:
        """Régression : le bouton ouvrait une session que RIEN n'alimentait.

        La chaîne était complète sauf ce maillon. Le compteur restait à zéro,
        ce qui est impossible à distinguer d'une session sans butin.
        """
        travailleur = self._Travailleur()
        etat = AppState(store, PriceBook(), None, travailleur)

        session_id = etat.start("Gyfin")

        assert travailleur.demarre == [session_id]
        assert etat.snapshot()["capture"]["en_cours"] is True

    def test_un_refus_de_capture_ne_laisse_pas_de_session_ouverte(
        self, store: SessionStore
    ) -> None:
        """⭐ Le test qui compte. Une session vide ressemble à une vraie.

        Si la capture refuse de démarrer, typiquement faute de calibrage, et
        qu'on laisse la session ouverte, l'utilisateur voit une session en cours
        dont le total n'augmente jamais. C'est exactement le mode de défaillance
        que ce projet refuse, et le laisser ici l'introduirait à l'endroit le
        plus visible du produit.
        """
        travailleur = self._Travailleur(refuse="zone du chat non calibrée")
        etat = AppState(store, PriceBook(), None, travailleur)

        with pytest.raises(CaptureUnavailable):
            etat.start("Gyfin")

        assert etat.session_id is None
        assert etat.snapshot()["session"] is None
        ouvertes = [session for session in store.sessions() if session.is_open]
        assert ouvertes == [], "une session ouverte que rien n'alimente reste dans la base"

    def test_l_arret_precede_la_fermeture_de_la_session(self, store: SessionStore) -> None:
        """Dans cet ordre : l'arrêt enregistre le butin encore en attente.

        L'écrire après la fermeture le rattacherait à une session dont la durée
        est déjà figée.
        """
        travailleur = self._Travailleur()
        etat = AppState(store, PriceBook(), None, travailleur)
        etat.start("Gyfin")

        etat.stop()

        assert travailleur.arrets == 1
        assert etat.session_id is None

    def test_le_refus_est_rendu_en_409_avec_son_motif(self, store: SessionStore) -> None:
        """409 et non 500 : l'utilisateur peut lever la condition lui-même.

        Encore faut-il qu'il sache laquelle, donc le message passe entier.
        """
        travailleur = self._Travailleur(refuse="zone du chat non calibrée")
        serveur = build_server(AppState(store, PriceBook(), None, travailleur), port=0)
        fil = threading.Thread(target=serveur.serve_forever, daemon=True)
        fil.start()
        try:
            port = serveur.server_address[1]
            requete = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/session/demarrer",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as echec:
                urllib.request.urlopen(requete)  # noqa: S310
            assert echec.value.code == 409
            assert "calibr" in json.loads(echec.value.read())["erreur"]
        finally:
            serveur.shutdown()
            serveur.server_close()

    def test_sans_travailleur_l_interface_reste_consultable(self, store: SessionStore) -> None:
        """Une machine sans écran doit pouvoir relire ses sessions passées."""
        etat = AppState(store, PriceBook(), None, None)

        etat.start("Gyfin")

        assert etat.snapshot()["capture"] is None


class TestCalibrageDepuisLInterface:
    """Le calibrage sans terminal. Sinon le produit reste un outil de dev."""

    def test_l_etat_dit_si_la_zone_est_calibree(self, store: SessionStore) -> None:
        """Sans ça, l'utilisateur clique « Démarrer » et se prend un refus.

        Savoir avant de cliquer que la zone n'est pas calibrée est ce qui
        transforme une erreur en étape.
        """
        etat = AppState(store, PriceBook(), None, None)

        assert etat.snapshot()["reglages"]["calibrage"] == ""

    def test_un_calibrage_enregistre_apparait_dans_l_etat(
        self, store: SessionStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BUTIN_HOME", str(tmp_path))
        Calibration(
            region=Region(left=0, top=0, width=400, height=500),
            row_height_px=21.6,
            ruler_left_ratio=0.2,
            ruler_right_ratio=1.0,
            rows=20,
            strength=0.5,
        ).save()

        etat = AppState(store, PriceBook(), None, None)

        assert "400x500" in etat.snapshot()["reglages"]["calibrage"]

    def test_un_calibrage_illisible_ne_casse_pas_la_page(
        self, store: SessionStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le fichier est éditable à la main, donc cassable à la main.

        Une page qui refuse de s'afficher parce qu'un champ manque dans un
        fichier de réglage laisserait l'utilisateur sans aucun moyen de
        comprendre, ni de relancer un calibrage.
        """
        monkeypatch.setenv("BUTIN_HOME", str(tmp_path))
        chemin = paths.calibration_path()
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps({"region": {"left": 0, "top": 0, "width": 9, "height": 9}}))

        etat = AppState(store, PriceBook(), None, None)

        assert etat.snapshot()["reglages"]["calibrage"] == ""


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
