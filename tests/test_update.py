"""Tests de la vérification de mise à jour.

Aucun test ne touche au réseau, même politique que `test_market.py` :
`api.github.com` est indisponible par moments comme n'importe quelle API, un
test qui l'appellerait vraiment échouerait au hasard.
"""

from __future__ import annotations

import json

import requests

from butin.update import UpdateInfo, check_for_update

# Réponse réelle de l'API GitHub Releases (champs utiles seulement), forme
# rendue par `GET /repos/<owner>/<repo>/releases/latest`.
REPONSE_RELEASE = json.dumps(
    {
        "tag_name": "v0.2.0",
        "name": "0.2.0",
        "html_url": "https://github.com/Maxyull/butin-bdo/releases/tag/v0.2.0",
        "published_at": "2026-09-01T10:00:00Z",
    }
).encode("utf-8")


class ReponseFactice:
    def __init__(self, contenu: bytes, *, statut: int = 200, url: str = "") -> None:
        self.content = contenu
        self.status_code = statut
        self.url = url or "https://api.github.com/repos/Maxyull/butin-bdo/releases/latest"

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"statut {self.status_code}")


class SessionFactice:
    def __init__(self, reponse: ReponseFactice | Exception) -> None:
        self.reponse = reponse
        self.appels = 0

    def get(self, url: str, **kwargs: object) -> ReponseFactice:
        self.appels += 1
        if isinstance(self.reponse, Exception):
            raise self.reponse
        return self.reponse


class TestCheckForUpdate:
    def test_detecte_une_version_plus_recente(self) -> None:
        session = SessionFactice(ReponseFactice(REPONSE_RELEASE))
        info = check_for_update("0.1.0", session=session)

        assert info == UpdateInfo(
            disponible=True,
            version="0.2.0",
            url="https://github.com/Maxyull/butin-bdo/releases/tag/v0.2.0",
        )

    def test_pas_de_mise_a_jour_sur_la_meme_version(self) -> None:
        session = SessionFactice(ReponseFactice(REPONSE_RELEASE))
        info = check_for_update("0.2.0", session=session)

        assert info is not None
        assert info.disponible is False

    def test_pas_de_mise_a_jour_sur_une_version_locale_plus_recente(self) -> None:
        """Une session qui tourne sur un checkout en avance sur la dernière
        Release (travail en cours non publié) ne doit pas s'affoler."""
        session = SessionFactice(ReponseFactice(REPONSE_RELEASE))
        info = check_for_update("0.3.0", session=session)

        assert info is not None
        assert info.disponible is False

    def test_dev_local_contre_la_premiere_version_publiee(self) -> None:
        """Régression : c'était la situation réelle de Butin avant le 06/08/2026.

        Avant la publication de `0.1.0`, la version locale était `0.1.0.dev0`
        (voir docs/versionnage.md) et la Release à venir serait `0.1.0` tout
        court. `.dev0` doit trier AVANT la version publiée du même numéro,
        sinon le bandeau ne se serait jamais affiché sur la version qui en
        avait le plus besoin : celle qui précédait la toute première
        publication. Le même cas se reproduira au prochain cycle de
        développement.
        """
        reponse = ReponseFactice(
            json.dumps(
                {
                    "tag_name": "v0.1.0",
                    "html_url": "https://github.com/Maxyull/butin-bdo/releases/tag/v0.1.0",
                }
            ).encode("utf-8")
        )
        info = check_for_update("0.1.0.dev0", session=SessionFactice(reponse))

        assert info is not None
        assert info.disponible is True
        assert info.version == "0.1.0"

    def test_rend_none_sur_erreur_reseau(self) -> None:
        session = SessionFactice(requests.ConnectionError("réseau coupé"))

        assert check_for_update("0.1.0", session=session) is None

    def test_rend_none_sur_statut_erreur(self) -> None:
        session = SessionFactice(ReponseFactice(b"", statut=500))

        assert check_for_update("0.1.0", session=session) is None

    def test_rend_none_sur_reponse_illisible(self) -> None:
        session = SessionFactice(ReponseFactice(b"pas du json"))

        assert check_for_update("0.1.0", session=session) is None

    def test_rend_none_si_tag_absent(self) -> None:
        session = SessionFactice(ReponseFactice(json.dumps({"name": "sans tag"}).encode("utf-8")))

        assert check_for_update("0.1.0", session=session) is None

    def test_rend_none_sur_hote_apres_redirection(self) -> None:
        """Même garde-fou que `MarketClient` : l'URL finale, pas seulement
        celle demandée, doit rester sur l'hôte autorisé."""
        session = SessionFactice(
            ReponseFactice(REPONSE_RELEASE, url="https://exemple.invalide/leurre")
        )

        assert check_for_update("0.1.0", session=session) is None

    def test_rejette_une_reponse_anormalement_volumineuse(self) -> None:
        enorme = json.dumps({"tag_name": "v9.9.9", "html_url": "x" * (64 * 1024)}).encode("utf-8")
        session = SessionFactice(ReponseFactice(enorme))

        assert check_for_update("0.1.0", session=session) is None
