"""Tests de l'application de bureau.

Aucune vraie fenêtre ici : l'ouvrir demande une session graphique, que
l'intégration continue n'a pas. `run` prend donc l'ouverture de fenêtre en
paramètre, et le test fournit une fonction qui interroge le serveur puis rend la
main, exactement comme le ferait une fenêtre qu'on referme.
"""

from __future__ import annotations

import builtins
import json
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


class TestOuverture:
    def test_la_fenetre_recoit_une_adresse_qui_sert_la_page(self, store: SessionStore) -> None:
        """La fenêtre affiche l'interface, pas une page d'erreur."""
        vu: dict[str, str] = {}

        def fenetre(url: str) -> None:
            vu["url"] = url
            vu["page"] = urllib.request.urlopen(url).read().decode("utf-8")  # noqa: S310

        assert app.run(store=store, window=fenetre) == 0
        assert vu["url"].startswith("http://127.0.0.1:")
        assert "bouton-session" in vu["page"]
        assert "bouton-calibrer" in vu["page"]

    def test_le_port_est_choisi_par_le_systeme(self, store: SessionStore) -> None:
        """L'utilisateur n'a rien à savoir d'un numéro de port.

        Et deux lancements simultanés ne se disputent plus le même : c'est ce
        que `port=0` demande au système.
        """
        ports: list[int] = []

        def fenetre(url: str) -> None:
            ports.append(int(url.rsplit(":", 1)[1].rstrip("/")))

        app.run(store=store, window=fenetre)
        app.run(store=store, window=fenetre)

        assert all(port > 0 for port in ports)
        assert ports[0] != ports[1]

    def test_le_serveur_est_arrete_a_la_fermeture(self, store: SessionStore) -> None:
        """Un serveur laissé derrière garderait le port et le fil vivants."""
        adresses: list[str] = []

        def fenetre(url: str) -> None:
            adresses.append(url)

        app.run(store=store, window=fenetre)

        with pytest.raises(OSError):
            urllib.request.urlopen(adresses[0], timeout=2)  # noqa: S310


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

        app.run(state=etat, window=fenetre)

        ouvertes = [session for session in store.sessions() if session.is_open]
        assert ouvertes == [], "fermer la fenêtre doit refermer la session"

    def test_le_serveur_est_arrete_meme_si_la_fenetre_leve(self, store: SessionStore) -> None:
        """Une fenêtre qui plante ne doit pas laisser le port occupé."""

        def fenetre(url: str) -> None:
            raise RuntimeError("la vue système a refusé de démarrer")

        with pytest.raises(RuntimeError):
            app.run(store=store, window=fenetre)


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
