"""Tests du CÂBLAGE entre l'interface et les modules de rapport et de mise à jour.

`test_report.py` et `test_autoupdate.py` couvrent les modules eux-mêmes. Ce
fichier couvre ce qui les relie à la page : les routes, le contexte assemblé,
et le type des fichiers servis.

⭐ C'est là qu'étaient les deux défauts réels de la journée : un `className`
réécrit qui effaçait la mise en forme, et un type MIME manquant qui empêchait
une image de s'afficher. Aucun n'était dans un module pur, les deux étaient
dans le câblage. Un module testé et bien branché n'est pas un module testé.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from butin.market import PriceBook, PriceCache
from butin.store import SessionStore
from butin.ui.server import HOST, AppState, build_server
from butin.update import UpdateInfo


@pytest.fixture
def app(tmp_path: Path):
    store = SessionStore(tmp_path / "sessions.sqlite3")
    book = PriceBook(client=None, cache=PriceCache(tmp_path / "prix.json"), vendor_values={})
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


def poster(base: str, chemin: str, corps: dict[str, Any] | None = None) -> Any:
    donnees = json.dumps(corps or {}).encode("utf-8")
    requete = urllib.request.Request(  # noqa: S310
        base + chemin, data=donnees, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(requete, timeout=5) as reponse:  # noqa: S310
        return json.loads(reponse.read())


def brut(base: str, chemin: str) -> tuple[int, str, bytes]:
    with urllib.request.urlopen(base + chemin, timeout=5) as reponse:  # noqa: S310
        return reponse.status, reponse.headers.get("Content-Type", ""), reponse.read()


class TestRouteRapport:
    def test_un_rapport_vide_est_refuse_sans_toucher_au_reseau(self, app) -> None:
        _, base = app
        corps = poster(base, "/api/rapport", {"message": "   "})
        assert corps["envoye"] is False
        assert "vide" in corps["message"].lower()

    def test_l_echec_reste_un_200(self, app, monkeypatch: Any) -> None:
        """Régression : un code HTTP d'erreur ferait mentir la page.

        Le serveur local a parfaitement fait son travail même quand le relais
        distant refuse. Répondre 502 ferait afficher « erreur serveur » alors
        que la cause est ailleurs, et la page perdrait le message explicatif
        que le corps transporte.
        """
        from butin.ui import server as module

        monkeypatch.setattr(
            module, "_envoyer_rapport", lambda *a, **k: _Resultat(False, "relais injoignable")
        )
        _, base = app
        corps = poster(base, "/api/rapport", {"message": "ça plante"})
        assert corps == {"envoye": False, "message": "relais injoignable"}


class _Resultat:
    def __init__(self, envoye: bool, raison: str) -> None:
        self.envoye = envoye
        self.raison = raison


class TestContexteDuRapport:
    def test_le_contexte_porte_ce_qu_il_faut_pour_reproduire(self, app, monkeypatch: Any) -> None:
        """Un rapport sans version ni zone oblige à un aller-retour.

        Et un joueur qui vient de perdre une session de farm ne le fera pas.
        Ce test fige les quatre informations sans lesquelles un bogue de
        comptage n'est pas reproductible.
        """
        from butin.ui import server as module

        vus: dict[str, Any] = {}

        def espion(message: str, *, contexte: dict[str, object] | None = None) -> _Resultat:
            vus["message"] = message
            vus["contexte"] = contexte or {}
            return _Resultat(True, "envoyé")

        monkeypatch.setattr(module, "_envoyer_rapport", espion)
        _, base = app
        poster(base, "/api/rapport", {"message": "rien n'est compté"})

        assert vus["message"] == "rien n'est compté"
        for cle in ("version", "zone calibrée", "session en cours", "panne de capture"):
            assert cle in vus["contexte"], f"« {cle} » manque au contexte"

    def test_sans_calibrage_le_contexte_le_dit_au_lieu_de_se_taire(
        self, app, monkeypatch: Any
    ) -> None:
        """« aucune » est une information ; une chaîne vide n'en est pas une.

        Une zone jamais calibrée est LA première cause d'un compteur qui ne
        compte rien. Le rapport doit la nommer, pas laisser un blanc que le
        lecteur interprétera comme « non renseigné ».
        """
        from butin.ui import server as module

        vus: dict[str, Any] = {}
        monkeypatch.setattr(
            module,
            "_envoyer_rapport",
            lambda m, *, contexte=None: vus.update(contexte or {}) or _Resultat(True, "ok"),
        )
        _, base = app
        poster(base, "/api/rapport", {"message": "bonjour"})
        assert vus["zone calibrée"] == "aucune"


class TestRouteMiseAJour:
    def test_sans_mise_a_jour_disponible_rien_n_est_telecharge(self, app) -> None:
        """Régression : cliquer alors qu'on est à jour ne doit rien lancer.

        Le bouton est masqué dans ce cas, mais la route reste joignable — et
        une route qui lancerait un installeur sans vérifier serait un chemin
        d'exécution ouvert à qui appelle l'API locale.
        """
        _, base = app
        corps = poster(base, "/api/maj")
        assert corps["lance"] is False
        assert "Aucune" in corps["message"]

    def test_une_mise_a_jour_disponible_declenche_l_installation(
        self, app, monkeypatch: Any
    ) -> None:
        from butin.ui import server as module

        etat, base = app
        etat.update_info = UpdateInfo(disponible=True, version="9.9.9", url="https://exemple")
        vus: list[str] = []
        monkeypatch.setattr(
            module, "install_update", lambda v: vus.append(v) or (True, "Mise à jour lancée.")
        )
        corps = poster(base, "/api/maj")
        assert vus == ["9.9.9"]
        assert corps["lance"] is True

    def test_un_echec_d_installation_reste_un_200(self, app, monkeypatch: Any) -> None:
        """Même raison que pour le rapport : le corps porte le message."""
        from butin.ui import server as module

        etat, base = app
        etat.update_info = UpdateInfo(disponible=True, version="9.9.9", url="https://exemple")
        monkeypatch.setattr(
            module, "install_update", lambda v: (False, "Téléchargement impossible.")
        )
        corps = poster(base, "/api/maj")
        assert corps["lance"] is False
        assert "impossible" in corps["message"]


class TestFichiersServis:
    def test_la_marque_est_servie_avec_le_bon_type(self, app) -> None:
        """⛔ Régression : sans type déclaré, l'image se télécharge au lieu de s'afficher.

        Le serveur envoie `X-Content-Type-Options: nosniff`, ce qui est le bon
        réglage — le navigateur ne devine pas. Conséquence : un format absent
        de la table part en `application/octet-stream` et n'est JAMAIS rendu.
        Le défaut est purement visuel, donc invisible pour un test qui se
        contente de vérifier un code 200.
        """
        _, base = app
        statut, type_mime, corps = brut(base, "/butin.png")
        assert statut == 200
        assert type_mime == "image/png"
        # Signature PNG : le fichier servi est bien une image, pas une page
        # d'erreur rendue avec le bon en-tête.
        assert corps.startswith(b"\x89PNG\r\n\x1a\n")

    def test_les_deux_pages_sont_servies_en_html(self, app) -> None:
        _, base = app
        for chemin in ("/", "/overlay"):
            statut, type_mime, corps = brut(base, chemin)
            assert statut == 200
            assert type_mime.startswith("text/html")
            # `overlay.html` n'a pas de doctype : c'est une page enveloppee
            # par une fenetre native, pas un document servi a un navigateur
            # quelconque. On verifie donc ce que les deux ont vraiment en
            # commun : un titre et un bloc de script.
            assert b"<title>" in corps.lower()
            assert b"<script>" in corps.lower()

    def test_une_route_inconnue_reste_un_404(self, app) -> None:
        _, base = app
        with pytest.raises(urllib.error.HTTPError) as erreur:
            brut(base, "/nimporte-quoi.png")
        assert erreur.value.code == 404
