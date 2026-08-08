"""Tests de l'application de bureau.

Aucune vraie fenêtre ici : l'ouvrir demande une session graphique, que
l'intégration continue n'a pas. `run` prend donc l'ouverture de fenêtre en
paramètre, et le test fournit une fonction qui interroge le serveur puis rend la
main, exactement comme le ferait une fenêtre qu'on referme.
"""

from __future__ import annotations

import builtins
import json
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from butin import app
from butin.market import PriceBook
from butin.store import SessionStore
from butin.ui.server import AppState


@pytest.fixture
def store(tmp_path: Path) -> SessionStore:
    return SessionStore(tmp_path / "sessions.sqlite3")


def lancer(**kwargs: object) -> int:
    """`app.run` sans préchargement d'images.

    ⭐ Ce n'est pas une commodité, c'est une correction. Le préchargement tourne
    dans un fil de fond qui **survit à `run`** : dans l'application il est démon
    et meurt avec le processus, mais dans une suite de tests le processus
    continue. Le fil écrivait alors dans le dossier de cache pendant qu'un AUTRE
    test vérifiait le contenu du sien, et ce test échouait sur un dossier qu'il
    n'avait pas créé. Attrapé par l'intégration continue, sur un seul des trois
    jobs : l'ordre décidait.
    """
    kwargs.setdefault("preload", lambda: 0)
    # Même raison que le préchargement : sans ce défaut, chaque test lancerait
    # une vraie requête réseau vers GitHub dans un fil qui survit au test.
    kwargs.setdefault("check_update", lambda: None)
    return app.run(**kwargs)  # type: ignore[arg-type]


class TestOuverture:
    def test_la_fenetre_recoit_une_adresse_qui_sert_la_page(self, store: SessionStore) -> None:
        """La fenêtre affiche l'interface, pas une page d'erreur."""
        vu: dict[str, str] = {}

        def fenetre(url: str) -> None:
            vu["url"] = url
            vu["page"] = urllib.request.urlopen(url).read().decode("utf-8")  # noqa: S310

        assert lancer(store=store, window=fenetre) == 0
        assert vu["url"].startswith("http://127.0.0.1:")
        assert "bouton-session" in vu["page"]
        # ⚠️ « bouton-calibrer » a disparu le 08/08/2026 : le calibrage n'est
        # plus un geste à part, il fait partie du parcours guidé lancé par
        # « Commencer le grind ». On vérifie donc le parcours, qui est ce qui
        # doit maintenant se trouver dans la page servie.
        assert "parcours" in vu["page"]

    def test_le_port_est_choisi_par_le_systeme(self, store: SessionStore) -> None:
        """L'utilisateur n'a rien à savoir d'un numéro de port.

        Et deux lancements simultanés ne se disputent plus le même : c'est ce
        que `port=0` demande au système.
        """
        ports: list[int] = []

        def fenetre(url: str) -> None:
            ports.append(int(url.rsplit(":", 1)[1].rstrip("/")))

        lancer(store=store, window=fenetre)
        lancer(store=store, window=fenetre)

        assert all(port > 0 for port in ports)
        assert ports[0] != ports[1]

    def test_le_serveur_est_arrete_a_la_fermeture(self, store: SessionStore) -> None:
        """Un serveur laissé derrière garderait le port et le fil vivants."""
        adresses: list[str] = []

        def fenetre(url: str) -> None:
            adresses.append(url)

        lancer(store=store, window=fenetre)

        with pytest.raises(OSError):
            urllib.request.urlopen(adresses[0], timeout=2)  # noqa: S310


class TestPrechargementDesImages:
    def test_il_est_lance_au_demarrage(self, store: SessionStore) -> None:
        """Sinon la première heure de farm affiche un récap sans images.

        Le lancement est le seul moment où l'on peut payer quelques centaines
        d'allers-retours réseau sans que personne ne les attende.
        """
        appele = threading.Event()

        def fenetre(url: str) -> None:
            # La fenêtre bloque jusqu'à sa fermeture : c'est pendant ce temps
            # que le fil de fond travaille, dans l'application comme ici.
            appele.wait(timeout=3.0)

        app.run(store=store, window=fenetre, preload=appele.set, check_update=lambda: None)

        assert appele.is_set()

    def test_il_ne_bloque_pas_l_ouverture_de_la_fenetre(self, store: SessionStore) -> None:
        """⚠️ Le préchargement dure. La fenêtre, elle, doit s'ouvrir tout de suite.

        Un préchargement au premier plan ferait attendre le joueur devant un
        écran vide, pour un gain purement cosmétique.
        """
        ouverte = threading.Event()
        libere = threading.Event()

        def fenetre(url: str) -> None:
            ouverte.set()

        def prechargement() -> int:
            libere.wait(timeout=3.0)
            return 0

        app.run(store=store, window=fenetre, preload=prechargement, check_update=lambda: None)
        libere.set()

        assert ouverte.is_set(), "la fenêtre a attendu le préchargement"


class TestVerificationDeMiseAJour:
    def test_elle_est_lancee_au_demarrage(self, store: SessionStore) -> None:
        appele = threading.Event()

        def fenetre(url: str) -> None:
            appele.wait(timeout=3.0)

        app.run(store=store, window=fenetre, preload=lambda: 0, check_update=appele.set)

        assert appele.is_set()

    def test_elle_ne_bloque_pas_l_ouverture_de_la_fenetre(self, store: SessionStore) -> None:
        """Même piège que le préchargement des images : un aller-retour réseau
        au premier plan ferait attendre le joueur devant un écran vide."""
        ouverte = threading.Event()
        libere = threading.Event()

        def fenetre(url: str) -> None:
            ouverte.set()

        def verification() -> None:
            libere.wait(timeout=3.0)

        app.run(store=store, window=fenetre, preload=lambda: 0, check_update=verification)
        libere.set()

        assert ouverte.is_set(), "la fenêtre a attendu la vérification de mise à jour"

    def test_elle_se_repete_tant_que_la_fenetre_reste_ouverte(self, store: SessionStore) -> None:
        """Demandé par Maxime le 06/08/2026 : une seule vérification au
        lancement ne suffit pas sur une session de farm de plusieurs heures,
        une Release publiée entre-temps ne serait jamais signalée.

        État fourni directement (catalogue `None`), comme dans
        `TestFermeture` : `build_state` ferait un vrai appel réseau pour
        charger le catalogue (isolation `BUTIN_HOME` de `conftest.py` oblige,
        aucun cache local à trouver), bien trop lent pour un intervalle de
        vérification de 0,02 s.
        """
        etat = AppState(store, PriceBook(), None, None)
        appels: list[int] = []
        ouverte = threading.Event()
        fermer = threading.Event()

        def fenetre(url: str) -> None:
            ouverte.set()
            fermer.wait(timeout=3.0)

        def verification() -> None:
            appels.append(1)

        fil = threading.Thread(
            target=app.run,
            kwargs={
                "state": etat,
                "window": fenetre,
                "preload": lambda: 0,
                "check_update": verification,
                "check_update_interval_s": 0.02,
            },
        )
        fil.start()
        assert ouverte.wait(timeout=3.0), "la fenêtre n'a jamais ouvert"
        time.sleep(0.3)
        fermer.set()
        fil.join(timeout=3.0)

        assert len(appels) >= 3, f"seulement {len(appels)} appel(s) en 0,3 s à 0,02 s d'intervalle"

    def test_elle_s_arrete_quand_la_fenetre_se_ferme(self, store: SessionStore) -> None:
        """⭐ Régression à ne pas réintroduire : un fil de fond qui survit à
        `run()`. Attrapé une première fois sur le préchargement des images
        (#37) — même piège possible ici avec un intervalle court."""
        etat = AppState(store, PriceBook(), None, None)
        appels: list[int] = []

        def fenetre(url: str) -> None:
            pass

        def verification() -> None:
            appels.append(1)

        app.run(
            state=etat,
            window=fenetre,
            preload=lambda: 0,
            check_update=verification,
            check_update_interval_s=0.02,
        )
        apres_fermeture = len(appels)
        time.sleep(0.3)

        assert len(appels) == apres_fermeture, "un fil de fond a survécu à la fermeture"


class TestFermeture:
    def test_fermer_la_fenetre_referme_la_session(self, store: SessionStore) -> None:
        """⭐ Régression à ne pas introduire : une session ouverte pour toujours.

        Sa durée continuerait de grandir tant que la base existe, et la
        prochaine ouverture afficherait un silver par heure calculé sur des
        heures qui n'ont jamais été farmées.

        L'état est fourni sans fil de capture : ce qui est en jeu ici est la
        fermeture de la session, pas la lecture de l'écran.
        """
        etat = AppState(store, PriceBook(), None, None)

        def fenetre(url: str) -> None:
            requete = urllib.request.Request(  # noqa: S310
                url + "api/session/demarrer",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            reponse = json.loads(urllib.request.urlopen(requete).read())  # noqa: S310
            assert reponse["session"]["en_cours"] is True

        lancer(state=etat, window=fenetre)

        ouvertes = [session for session in store.sessions() if session.is_open]
        assert ouvertes == [], "fermer la fenêtre doit refermer la session"

    def test_le_serveur_est_arrete_meme_si_la_fenetre_leve(self, store: SessionStore) -> None:
        """Une fenêtre qui plante ne doit pas laisser le port occupé."""

        def fenetre(url: str) -> None:
            raise RuntimeError("la vue système a refusé de démarrer")

        with pytest.raises(RuntimeError):
            lancer(store=store, window=fenetre)


class TestSansVueSysteme:
    def test_l_absence_de_pywebview_explique_quoi_faire(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Un logiciel qui ne démarre pas doit dire par quoi le remplacer.

        La vue système peut manquer sur une installation ancienne. Se contenter
        d'une trace d'import laisserait l'utilisateur sans savoir que la même
        interface est disponible dans un navigateur.
        """
        vrai_import = builtins.__import__

        def refuser(nom: str, *args: object, **kwargs: object):
            if nom == "webview":
                raise ImportError("pas de webview")
            return vrai_import(nom, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", refuser)

        with pytest.raises(SystemExit, match="butin interface"):
            app._open_window("http://127.0.0.1:1234/")
