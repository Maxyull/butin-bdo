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
from butin.catalog import ItemCatalog
from butin.market import Price, PriceBook, PriceCache, PriceSource
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


class TestProfilDeTaxe:
    """Le taux de taxe se règle enfin, et il tient.

    C'est le seul réglage qui multiplie tout le reste : il s'applique à chaque
    objet vendable de chaque session. Le laisser au défaut sous-estime de 23 %
    le butin de quelqu'un qui a un abonnement, et rien à l'écran ne distingue
    ça d'un farm pauvre.
    """

    def test_le_profil_est_dans_l_etat(self, app) -> None:
        _, base = app
        reglages = get(base, "/api/etat")["reglages"]

        assert reglages["taxe"] == {
            "abonnement": False,
            "anneau_marchand": False,
            "renommee": 0,
        }
        assert reglages["taux_marche"] == pytest.approx(0.65)

    def test_cocher_l_abonnement_change_le_taux(self, app) -> None:
        _, base = app
        etat = post(base, "/api/reglages", {"taxe": {"abonnement": True}})

        assert etat["reglages"]["taxe"]["abonnement"] is True
        assert etat["reglages"]["taux_marche"] == pytest.approx(0.845)

    def test_le_profil_reel_de_maxime(self, app) -> None:
        """Le point de mesure qui valide toute la chaîne, de la page au calcul.

        Relevé sur le calculateur de garmoth le 05/08/2026 : abonnement oui,
        anneau non, renommée familiale 11952, taux affiché **85,47 %**.
        """
        _, base = app
        etat = post(
            base,
            "/api/reglages",
            {"taxe": {"abonnement": True, "anneau_marchand": False, "renommee": 11952}},
        )

        assert etat["reglages"]["taux_marche"] == pytest.approx(0.8547, abs=0.0001)

    def test_le_taux_ne_se_regle_pas_a_la_main(self, app) -> None:
        """Régression : deux façons de régler la même chose est un réglage qui ment.

        L'API acceptait `taux_marche` en écriture. Avec les cases à cocher, la
        prochaine case cliquée recalculerait le taux et écraserait sans rien
        dire le pourcentage saisi à la main. Le taux est donc rendu, jamais reçu.
        """
        _, base = app
        etat = post(base, "/api/reglages", {"taux_marche": 0.9})

        assert etat["reglages"]["taux_marche"] == pytest.approx(0.65)

    def test_le_profil_change_le_total_de_la_session(self, app) -> None:
        """Le réglage n'est pas décoratif : il change le chiffre affiché.

        Un million de silver de prix affiché, avec un abonnement : 845 000 dans
        la poche, pas 650 000.
        """
        state, base = app
        state.book.cache.put(
            Price(item_id=16001, value=1_000_000, source=PriceSource.MARKET, fetched_at=1000.0)
        )
        session_id = state.start("Gyfin", now=1000.0)
        state.store.add_loot(session_id, [LootRow(item_id=16001, qty=1, at=1001.0)])

        avant = state.snapshot(now=1100.0)["stats"]["net_marche"]
        post(base, "/api/reglages", {"taxe": {"abonnement": True}})
        apres = state.snapshot(now=1100.0)["stats"]["net_marche"]

        assert avant == 650_000
        assert apres == 845_000

    def test_le_profil_survit_au_relancement(self, app) -> None:
        """Régression : le réglage ne vivait que dans la mémoire du serveur.

        Le cas réel : on coche « abonnement », on ferme l'application, on la
        rouvre, et elle est revenue à 0,65 sans le dire. Un réglage qu'il faut
        ressaisir à chaque lancement est un réglage silencieusement faux la
        plupart du temps.
        """
        state, base = app
        post(base, "/api/reglages", {"taxe": {"abonnement": True, "renommee": 11952}})

        # Un second AppState sur le même dossier : c'est ce que fait le
        # prochain lancement de l'application.
        rallume = AppState(state.store, state.book)

        assert rallume.settings.market_rate == pytest.approx(0.8547, abs=0.0001)

    def test_une_renommee_invalide_ne_perd_pas_l_abonnement(self, app) -> None:
        """Régression : rejeter le lot entier pour un champ ferait perdre un
        réglage juste à cause d'un réglage faux."""
        _, base = app
        etat = post(base, "/api/reglages", {"taxe": {"abonnement": True, "renommee": "beaucoup"}})

        assert etat["reglages"]["taxe"]["abonnement"] is True
        assert etat["reglages"]["taxe"]["renommee"] == 0

    def test_les_champs_de_la_taxe_sont_dans_la_page(self, app) -> None:
        _, base = app
        with urllib.request.urlopen(base + "/", timeout=5) as reponse:  # noqa: S310
            corps = reponse.read().decode("utf-8")

        assert 'id="abonnement"' in corps
        assert 'id="anneau-marchand"' in corps
        assert 'id="renommee"' in corps


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


class TestFilDesDrops:
    """Le fil qui s'écrit pendant qu'on farme.

    Le total cumulé ne montre pas ce qui vient d'arriver : il grandit, c'est
    tout. Ce fil est la seule chose qui dise « ça, c'est tombé il y a trois
    secondes », et c'est ce qu'on regarde en jouant.
    """

    def test_les_derniers_drops_apparaissent_du_plus_recent_au_plus_ancien(self, app) -> None:
        state, _ = app
        session_id = state.start("Gyfin", now=1000.0)
        state.store.add_loot(
            session_id,
            [
                LootRow(item_id=16001, qty=1, at=1001.0),
                LootRow(item_id=4998, qty=3, at=1005.0),
            ],
        )

        derniers = state.snapshot(now=1010.0)["derniers"]

        assert [ligne["item_id"] for ligne in derniers] == [4998, 16001]
        assert derniers[0]["quantite"] == 3
        assert derniers[0]["il_y_a_s"] == pytest.approx(5.0)
        assert derniers[1]["il_y_a_s"] == pytest.approx(9.0)

    def test_la_rarete_accompagne_chaque_drop(self, app) -> None:
        """C'est le code couleur du jeu, et il était déjà dans le catalogue.

        Un joueur reconnaît un drop rare à sa couleur avant d'avoir lu son nom.
        La donnée existait sans être utilisée nulle part.
        """
        state, _ = app
        state.catalog = ItemCatalog.from_raw(
            {
                "16001": {
                    "id": 16001,
                    "locale_default": "us",
                    "locale_name": {"us": "Black Stone", "fr": "Pierre noire"},
                    "grade": 3,
                    "category_primary": 1,
                    "category_secondary": 1,
                }
            }
        )
        session_id = state.start("Gyfin", now=0.0)
        state.store.add_loot(session_id, [LootRow(item_id=16001, qty=1, at=1.0)])

        derniers = state.snapshot(now=2.0)["derniers"]

        assert derniers[0]["rarete"] == 3

    def test_sans_session_le_fil_est_vide_et_non_absent(self, app) -> None:
        """La page lit toujours la même forme : un champ absent la ferait
        planter là où une liste vide se rend toute seule."""
        state, _ = app

        assert state.snapshot()["derniers"] == []


class TestPanneauEnSurimpression:
    """Le panneau posé par-dessus le jeu, ouvert avec la session.

    C'est le seul écran que le joueur regarde en farmant : la fenêtre
    principale est derrière le jeu, ou sur un autre écran.
    """

    class _Overlay:
        def __init__(self) -> None:
            self.trace: list[str] = []

        def open(self) -> None:
            self.trace.append("ouvert")

        def close(self) -> None:
            self.trace.append("ferme")

    def test_il_s_ouvre_avec_la_session_et_se_ferme_avec_elle(self, store: SessionStore) -> None:
        panneau = self._Overlay()
        etat = AppState(store, PriceBook(), None, None, panneau)

        etat.start("Gyfin")
        etat.stop()

        assert panneau.trace == ["ouvert", "ferme"]

    def test_un_demarrage_refuse_n_ouvre_pas_le_panneau(self, store: SessionStore) -> None:
        """Un panneau vide posé sur le jeu, sans session derrière, ferait croire
        que ça tourne."""

        class Refuse:
            def start(self, session_id: int) -> None:
                raise CaptureUnavailable("zone non calibrée")

            def stop(self, *, timeout: float = 5.0) -> int:
                return 0

            def status(self) -> CaptureStatus:
                return CaptureStatus(False, 0, 0, 0, 0, 0, 0)

        panneau = self._Overlay()
        etat = AppState(store, PriceBook(), None, Refuse(), panneau)

        with pytest.raises(CaptureUnavailable):
            etat.start("Gyfin")

        assert panneau.trace == []

    def test_la_page_du_panneau_est_servie(self, app) -> None:
        _, base = app

        page = urllib.request.urlopen(f"{base}/overlay").read().decode("utf-8")  # noqa: S310

        assert "background: transparent" in page

    def test_l_application_reste_utilisable_sans_panneau(self, store: SessionStore) -> None:
        """Sans lui, la fenêtre principale montre les mêmes chiffres."""
        etat = AppState(store, PriceBook(), None, None, None)

        etat.start("Gyfin")
        etat.stop()

        assert etat.session_id is None


class TestDossierDesSessions:
    def test_le_dossier_est_visible_dans_les_reglages(self, app) -> None:
        """Sinon personne ne sait où sont ses sessions, et « quelque part sur le
        disque » n'est pas une réponse."""
        state, _ = app

        reglages = state.snapshot()["reglages"]

        assert reglages["dossier"]
        assert reglages["dossier_defaut"].endswith("BDO Tracker")

    def test_changer_de_dossier_le_retient(
        self, app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        state, _ = app
        monkeypatch.setenv("BUTIN_HOME", str(tmp_path))
        cible = tmp_path / "ailleurs"

        reponse = state.set_storage(str(cible))

        assert reponse["redemarrage"] is True
        assert cible.is_dir()

    def test_un_dossier_vide_est_refuse(self, app) -> None:
        state, _ = app

        with pytest.raises(ValueError):
            state.set_storage("   ")


class TestPageHistorique:
    """La seconde page. Sans elle, une session fermée disparaissait pour de bon.

    Le butin était enregistré, la durée aussi, et rien ne les montrait jamais :
    on farmait, on fermait, et on ne pouvait plus savoir ce qu'on avait fait.
    """

    def _session_close(self, store: SessionStore, spot: str, debut: float, fin: float) -> int:
        session = store.start_session(started_at=debut, spot=spot, region="eu")
        store.add_loot(session.id, [LootRow(item_id=43984, qty=4, at=debut + 10)])
        store.end_session(session.id, ended_at=fin)
        return session.id

    def test_les_sessions_passees_sont_listees_de_la_plus_recente(self, app) -> None:
        state, _ = app
        self._session_close(state.store, "Aakman", 0.0, 3600.0)
        self._session_close(state.store, "Gyfin", 7200.0, 10800.0)

        historique = state.history()

        assert [ligne["spot"] for ligne in historique] == ["Gyfin", "Aakman"]
        assert historique[0]["duree_s"] == pytest.approx(3600.0)
        assert historique[0]["objets"] == 4

    def test_la_valeur_de_la_session_est_calculee(self, app) -> None:
        """Le tableau ne sert à rien s'il n'affiche que des durées."""
        state, _ = app
        self._session_close(state.store, "Gyfin", 0.0, 3600.0)

        ligne = state.history()[0]

        assert ligne["total"] > 0
        assert ligne["par_heure"] > 0

    def test_une_session_en_cours_est_signalee(self, app) -> None:
        """Sa durée grandit encore : la confondre avec une session finie
        laisserait croire à un silver par heure figé."""
        state, _ = app
        state.start("Gyfin")

        assert state.history()[0]["en_cours"] is True

    def test_le_detail_rend_le_butin_de_la_session(self, app) -> None:
        state, _ = app
        session_id = self._session_close(state.store, "Gyfin", 0.0, 3600.0)

        detail = state.session_detail(session_id)

        assert detail is not None
        assert detail["spot"] == "Gyfin"
        assert [ligne["quantite"] for ligne in detail["butin"]] == [4]

    def test_une_session_inconnue_rend_none_et_non_un_detail_vide(self, app) -> None:
        """« Cette session n'existe pas » et « cette session n'a rien rapporté »
        sont deux réponses différentes.

        Les confondre ferait passer une erreur d'adressage pour une soirée sans
        butin, ce qui est exactement le genre de silence que ce projet refuse.
        """
        state, _ = app

        assert state.session_detail(9999) is None


class TestRoutesHistorique:
    def test_un_identifiant_inconnu_rend_404(self, app) -> None:
        _, base = app

        with pytest.raises(urllib.error.HTTPError) as echec:
            urllib.request.urlopen(f"{base}/api/historique/9999")  # noqa: S310

        assert echec.value.code == 404

    def test_un_identifiant_qui_n_en_est_pas_un_rend_400(self, app) -> None:
        """Le chemin vient du réseau : le convertir sans vérifier laisserait
        remonter une erreur serveur là où la bonne réponse est « cette adresse
        n'existe pas »."""
        _, base = app

        with pytest.raises(urllib.error.HTTPError) as echec:
            urllib.request.urlopen(f"{base}/api/historique/abc")  # noqa: S310

        assert echec.value.code == 400


class TestCapture:
    """La capture, vue depuis l'interface. Le dernier maillon du produit."""

    class _Travailleur:
        """Faux fil de capture, piloté par le test."""

        def __init__(self, *, refuse: str = "") -> None:
            self.refuse = refuse
            self.demarre: list[int] = []
            self.reprises: list[int] = []
            self.arrets = 0
            self.pauses = 0
            self.running = False

        def start(self, session_id: int, *, reprise: bool = False) -> None:
            if self.refuse:
                raise CaptureUnavailable(self.refuse)
            (self.reprises if reprise else self.demarre).append(session_id)
            self.running = True

        def stop(self, *, timeout: float = 5.0) -> int:
            self.arrets += 1
            self.running = False
            return 0

        def pause(self, *, timeout: float = 5.0) -> int:
            self.pauses += 1
            self.running = False
            return 0

        def status(self) -> CaptureStatus:
            return CaptureStatus(
                running=self.running,
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


class TestPause:
    """Mettre en pause depuis l'interface, sans fausser le chiffre affiché."""

    def _etat(self, store: SessionStore) -> tuple[AppState, TestCapture._Travailleur]:
        travailleur = TestCapture._Travailleur()
        return AppState(store, PriceBook(), None, travailleur), travailleur

    def test_la_pause_suspend_la_capture_et_le_temps(self, store: SessionStore) -> None:
        etat, travailleur = self._etat(store)
        etat.start("Gyfin", now=0.0)

        etat.pause(now=600.0)

        assert travailleur.pauses == 1
        vue = etat.snapshot(now=1800.0)
        assert vue["session"]["en_pause"] is True
        # 1800 s se sont écoulées, mais la session n'a farmé que les 600
        # premières : le reste est de la pause.
        assert vue["session"]["duree_s"] == pytest.approx(600.0)

    def test_la_reprise_relance_la_capture_en_gardant_la_session(self, store: SessionStore) -> None:
        """⭐ `reprise=True` est ce qui empêche d'inventer des drops.

        La boucle repart neuve dans les deux cas, donc sa première lecture
        amorce le suivi avec les dix-sept lignes encore à l'écran sans rien
        compter. Le drapeau ne sert qu'à garder les compteurs déjà acquis.
        """
        etat, travailleur = self._etat(store)
        session_id = etat.start("Gyfin", now=0.0)
        etat.pause(now=600.0)

        etat.resume(now=1200.0)

        assert travailleur.reprises == [session_id]
        assert travailleur.demarre == [session_id]
        vue = etat.snapshot(now=1800.0)
        assert vue["session"]["en_pause"] is False
        assert vue["session"]["id"] == session_id
        # 1800 s écoulées moins 600 s de pause.
        assert vue["session"]["duree_s"] == pytest.approx(1200.0)

    def test_une_reprise_refusee_laisse_la_session_en_pause(self, store: SessionStore) -> None:
        """⭐ Régression : le pire des deux mondes serait de recompter le temps
        sans que rien n'alimente la session.

        C'est la même règle qu'au démarrage : une session qui avance sans
        capture ressemble à un farm qui n'aurait rien donné.
        """
        etat, travailleur = self._etat(store)
        etat.start("Gyfin", now=0.0)
        etat.pause(now=600.0)
        travailleur.refuse = "zone du chat non calibrée"

        with pytest.raises(CaptureUnavailable):
            etat.resume(now=1200.0)

        vue = etat.snapshot(now=1800.0)
        assert vue["session"]["en_pause"] is True
        assert vue["session"]["duree_s"] == pytest.approx(600.0)

    def test_le_silver_par_heure_ignore_la_pause(self, store: SessionStore) -> None:
        """Le chiffre sur lequel tout le logiciel est jugé.

        Une heure de farm puis une heure de pause : le résultat par heure doit
        être celui d'une heure de farm, pas la moitié.
        """
        livre_de_prix = PriceBook(client=None, cache=None, vendor_values={43984: {"base": 1000}})
        travailleur = TestCapture._Travailleur()
        etat = AppState(store, livre_de_prix, None, travailleur)
        session_id = etat.start("Gyfin", now=0.0)
        etat.store.add_loot(session_id, [LootRow(item_id=43984, qty=100, at=10.0)])

        etat.pause(now=3600.0)

        assert etat.snapshot(now=7200.0)["stats"]["par_heure"] == pytest.approx(100_000)

    def test_arreter_pendant_une_pause_fige_la_duree(self, store: SessionStore) -> None:
        """Régression : la session qui rétrécit toute seule dans l'historique."""
        etat, _ = self._etat(store)
        etat.start("Gyfin", now=0.0)
        etat.pause(now=600.0)

        etat.stop(now=900.0)

        session = store.sessions()[0]
        assert not session.is_paused
        assert session.duration_s(now=900.0 + 30 * 86400) == pytest.approx(600.0)

    def test_le_panneau_reste_ouvert_pendant_la_pause(self, store: SessionStore) -> None:
        """⚠️ Le fermer laisserait le joueur devant son jeu sans rien qui dise
        que le suivi est suspendu. Une reprise oubliée est du farm perdu."""
        panneau = TestPanneauEnSurimpression._Overlay()
        etat = AppState(store, PriceBook(), None, TestCapture._Travailleur(), panneau)
        etat.start("Gyfin", now=0.0)

        etat.pause(now=600.0)

        assert panneau.trace == ["ouvert"]

    def test_pause_sans_session_ne_plante_pas(self, store: SessionStore) -> None:
        etat, travailleur = self._etat(store)

        etat.pause()
        etat.resume()

        assert travailleur.pauses == 0
        assert travailleur.reprises == []

    def test_les_routes_repondent(self, app) -> None:
        """Le trajet complet, depuis la page : pause puis reprise."""
        _, base = app
        post(base, "/api/session/demarrer", {"spot": "Gyfin"})

        en_pause = post(base, "/api/session/pause")
        assert en_pause["session"]["en_pause"] is True

        repris = post(base, "/api/session/reprendre")
        assert repris["session"]["en_pause"] is False


class TestImagesDesObjets:
    """L'image de l'objet dans le récap, à côté du nom et de la quantité.

    Un joueur reconnaît son butin à l'image avant d'avoir lu le nom. Mais une
    image n'est que cosmétique : rien de ce qui la concerne ne doit empêcher
    d'afficher un drop.
    """

    class _Magasin:
        """Faux magasin d'images, piloté par le test."""

        def __init__(self, connues: dict[int, Path] | None = None) -> None:
            self.connues = connues or {}
            self.demandes: list[tuple[int, str]] = []

        def get(self, item_id: int, remote: str) -> Path | None:
            self.demandes.append((item_id, remote))
            return self.connues.get(item_id)

        def preload(self, entries) -> int:
            return len(dict(entries))

    def _serveur(self, etat: AppState):
        serveur = build_server(etat, port=0)
        fil = threading.Thread(target=serveur.serve_forever, daemon=True)
        fil.start()
        return serveur, f"http://{HOST}:{serveur.server_address[1]}"

    def test_l_image_est_servie_avec_son_type(self, store: SessionStore, tmp_path: Path) -> None:
        image = tmp_path / "16001.webp"
        image.write_bytes(b"RIFF\x00\x00\x00\x00WEBP")
        etat = AppState(store, PriceBook(), None, None, icons=self._Magasin({16001: image}))
        serveur, base = self._serveur(etat)
        try:
            with urllib.request.urlopen(base + "/icone/16001", timeout=5) as reponse:  # noqa: S310
                assert reponse.headers["Content-Type"] == "image/webp"
                assert reponse.headers["X-Content-Type-Options"] == "nosniff"
                assert reponse.read() == b"RIFF\x00\x00\x00\x00WEBP"
        finally:
            serveur.shutdown()
            serveur.server_close()

    def test_une_image_absente_rend_404(self, store: SessionStore) -> None:
        """404 et non 500 : la page cache une image qui ne charge pas.

        Une icône manquante ne signale pas une panne et n'interrompt rien.
        """
        etat = AppState(store, PriceBook(), None, None, icons=self._Magasin())
        serveur, base = self._serveur(etat)
        try:
            with pytest.raises(urllib.error.HTTPError) as erreur:
                get(base, "/icone/16001")
            assert erreur.value.code == 404
        finally:
            serveur.shutdown()
            serveur.server_close()

    def test_un_identifiant_qui_n_en_est_pas_un_rend_400(self, store: SessionStore) -> None:
        """Régression : le chemin vient du réseau.

        Le convertir sans vérifier laisserait remonter une `ValueError` jusqu'au
        gestionnaire, qui rendrait une erreur serveur là où la bonne réponse est
        « cette adresse n'existe pas ».
        """
        etat = AppState(store, PriceBook(), None, None, icons=self._Magasin())
        serveur, base = self._serveur(etat)
        try:
            with pytest.raises(urllib.error.HTTPError) as erreur:
                get(base, "/icone/pas-un-nombre")
            assert erreur.value.code == 400
        finally:
            serveur.shutdown()
            serveur.server_close()

    def test_le_chemin_distant_vient_du_catalogue(self, store: SessionStore) -> None:
        """C'est le catalogue qui sait où est l'image, pas la page."""
        catalogue = ItemCatalog.from_raw(
            {
                "16001": {
                    "id": 16001,
                    "locale_default": "us",
                    "locale_name": {"us": "Black Stone", "fr": "Pierre noire"},
                    "grade": 4,
                    "icon": "/items/new_icon/03_etc/00016001.webp",
                }
            }
        )
        magasin = self._Magasin()
        etat = AppState(store, PriceBook(), catalogue, None, icons=magasin)

        etat.icon(16001)

        assert magasin.demandes == [(16001, "/items/new_icon/03_etc/00016001.webp")]

    def test_sans_catalogue_on_sert_ce_qui_est_deja_la(self, store: SessionStore) -> None:
        """Une machine sans réseau doit rester consultable : le catalogue peut
        manquer, les images déjà téléchargées sont toujours là."""
        magasin = self._Magasin()
        etat = AppState(store, PriceBook(), None, None, icons=magasin)

        etat.icon(16001)

        assert magasin.demandes == [(16001, "")]

    def test_le_prechargement_ne_prend_que_le_butin_connu(self, store: SessionStore) -> None:
        """362 objets et non 68 747 : ce sont ceux qui tombent réellement.

        ⚠️ « Pierre noire » n'en fait PAS partie, et c'est normal : la table est
        celle du trash loot, pas celle des objets de marché. Son image sera
        téléchargée au moment où elle tombe, comme n'importe quel objet hors
        table.
        """
        catalogue = ItemCatalog.from_raw(
            {
                # Elkarr, identifiant 6393, présent dans data/butin-connu.json.
                "6393": {
                    "id": 6393,
                    "locale_default": "us",
                    "locale_name": {"us": "Elkarr", "fr": "Elkarr"},
                    "icon": "/items/a.webp",
                },
                "16001": {
                    "id": 16001,
                    "locale_default": "us",
                    "locale_name": {"us": "Black Stone", "fr": "Pierre noire"},
                    "icon": "/items/b.webp",
                },
            }
        )
        etat = AppState(store, PriceBook(), catalogue, None, icons=self._Magasin())

        assert etat.preload_icons() == 1

    def test_sans_catalogue_le_prechargement_ne_fait_rien(self, store: SessionStore) -> None:
        etat = AppState(store, PriceBook(), None, None, icons=self._Magasin())

        assert etat.preload_icons() == 0

    def test_la_page_demande_les_images(self, app) -> None:
        _, base = app
        with urllib.request.urlopen(base + "/", timeout=5) as reponse:  # noqa: S310
            corps = reponse.read().decode("utf-8")

        assert "/icone/" in corps


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
