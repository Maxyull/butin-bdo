"""Tests de l'envoi d'un rapport de bogue vers le relais.

Aucun test ne touche le réseau : le relais est remplacé par une fausse session
`requests`. Ce qui compte ici n'est pas que la requête parte, c'est qu'aucune
panne ne remonte au joueur sous forme d'exception, et que le webhook Discord
ne soit jamais dans cette application.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import requests

from butin import report


class FausseReponse:
    def __init__(self, status_code: int, url: str = report.RELAY_URL) -> None:
        self.status_code = status_code
        self.url = url


class FausseSession:
    """Note ce qu'on lui a demandé, et rend ce qu'on lui a dit de rendre."""

    def __init__(self, reponse: object) -> None:
        self._reponse = reponse
        self.appels: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> Any:
        self.appels.append({"url": url, **kwargs})
        if isinstance(self._reponse, Exception):
            raise self._reponse
        return self._reponse


class TestIdentifiantDeContributeur:
    def test_il_est_cree_une_fois_puis_relu(self, tmp_path: Path) -> None:
        premier = report.contributor_id(tmp_path)
        second = report.contributor_id(tmp_path)
        assert premier == second
        assert report.contributor_path(tmp_path).exists()

    def test_il_respecte_le_format_impose_par_le_relais(self, tmp_path: Path) -> None:
        """Régression : le relais refuse en 422 hors de `[0-9A-Za-z_-]{8,64}`.

        Le format est décidé par `PLAYER_PATTERN` dans `rubin-bdo`, pas ici. Un
        identifiant hors format ferait échouer tous les envois avec un message
        que le joueur ne pourrait pas interpréter.
        """
        identifiant = report.contributor_id(tmp_path)
        assert 8 <= len(identifiant) <= 64
        assert all(c.isalnum() or c in "_-" for c in identifiant)

    def test_un_identifiant_illisible_est_remplace(self, tmp_path: Path) -> None:
        """Mieux vaut un identifiant neuf qu'un envoi refusé sans explication."""
        report.contributor_path(tmp_path).write_text("trop court", encoding="utf-8")
        remplace = report.contributor_id(tmp_path)
        assert remplace != "trop court"
        assert all(c.isalnum() or c in "_-" for c in remplace)

    def test_il_ne_contient_rien_de_la_machine(self, tmp_path: Path) -> None:
        """Il distingue deux rapports, il n'identifie pas une personne."""
        import getpass
        import platform

        identifiant = report.contributor_id(tmp_path).lower()
        for indice in (getpass.getuser(), platform.node()):
            if indice:
                assert indice.lower() not in identifiant

    def test_deux_dossiers_donnent_deux_identifiants(self, tmp_path: Path) -> None:
        a = report.contributor_id(tmp_path / "a")
        b = report.contributor_id(tmp_path / "b")
        assert a != b


class TestComposition:
    def test_le_contexte_est_joint_au_message(self) -> None:
        corps = report.compose("ça ne compte rien", {"version": "0.4.0", "zone": "476x567"})
        assert "ça ne compte rien" in corps
        assert "version : 0.4.0" in corps
        assert "zone : 476x567" in corps

    def test_le_message_est_coupe_au_plafond_du_relais(self) -> None:
        """Régression : couper ici, pas se faire refuser en 413 après coup.

        Le plafond appartient au relais (`MAX_REPORT_LENGTH` vaut 1800). Le
        dépasser fait perdre le rapport entier, alors que le tronquer en garde
        le début, qui est la partie que le joueur a écrite lui-même.
        """
        corps = report.compose("x" * 5000)
        assert len(corps) <= report.MAX_MESSAGE
        assert corps.endswith("…")

    def test_sans_contexte_le_corps_reste_le_message(self) -> None:
        assert report.compose("  bonjour  ") == "bonjour"


class TestEnvoi:
    def test_un_envoi_accepte_est_annonce_comme_tel(self, tmp_path: Path) -> None:
        session = FausseSession(FausseReponse(202))
        resultat = report.send_report("ça plante", session=session, root=tmp_path)
        assert resultat.envoye
        assert session.appels[0]["url"] == report.RELAY_URL

    def test_le_paquet_porte_l_application_et_l_identifiant(self, tmp_path: Path) -> None:
        """`app` permet au relais de viser le bon salon.

        Le relais ne le gère pas encore (demande laissée dans COORDINATION.md) ;
        un champ inconnu est ignoré, donc l'envoyer dès maintenant ne casse
        rien et évite une seconde version du client plus tard.
        """
        session = FausseSession(FausseReponse(202))
        report.send_report("ça plante", session=session, root=tmp_path)
        corps = session.appels[0]["json"]
        assert corps["app"] == "butin"
        assert corps["joueur"] == report.contributor_id(tmp_path)
        assert "ça plante" in corps["contenu"]

    @pytest.mark.parametrize(
        ("code", "extrait"),
        [
            (503, "pas encore activé"),
            (413, "trop long"),
            (422, "vide ou mal formé"),
            (500, "500"),
        ],
    )
    def test_chaque_refus_a_son_message(self, tmp_path: Path, code: int, extrait: str) -> None:
        """Ces codes veulent dire des choses très différentes pour le joueur.

        Un 503 n'est pas sa faute et il ne doit pas réessayer ; un 413 se
        corrige en raccourcissant. Les confondre en « échec » ferait réessayer
        indéfiniment le seul cas qui ne peut pas marcher.
        """
        session = FausseSession(FausseReponse(code))
        resultat = report.send_report("bonjour", session=session, root=tmp_path)
        assert not resultat.envoye
        assert extrait in resultat.raison

    def test_une_panne_reseau_ne_leve_jamais(self, tmp_path: Path) -> None:
        """Régression : planter en signalant un bogue serait une plaisanterie."""
        session = FausseSession(requests.ConnectionError("pas de réseau"))
        resultat = report.send_report("bonjour", session=session, root=tmp_path)
        assert not resultat.envoye
        assert "connexion" in resultat.raison

    def test_un_rapport_vide_ne_part_pas(self, tmp_path: Path) -> None:
        session = FausseSession(FausseReponse(202))
        resultat = report.send_report("   ", session=session, root=tmp_path)
        assert not resultat.envoye
        assert session.appels == []

    def test_un_hote_non_autorise_est_refuse_avant_la_requete(self, tmp_path: Path) -> None:
        """Régression : la liste blanche vaut aussi pour l'URL demandée.

        Même politique que `update.py` et `MarketClient`. Sans elle, un réglage
        ou un correctif maladroit enverrait le rapport, donc le contexte de la
        machine, à un hôte quelconque.
        """
        session = FausseSession(FausseReponse(202))
        resultat = report.send_report(
            "bonjour", url="https://exemple.invalide/v1/rapport", session=session, root=tmp_path
        )
        assert not resultat.envoye
        assert session.appels == []

    def test_une_redirection_hors_liste_blanche_est_refusee(self, tmp_path: Path) -> None:
        """L'hôte est revalidé APRÈS redirection, pas seulement avant."""
        session = FausseSession(FausseReponse(202, url="https://ailleurs.invalide/x"))
        resultat = report.send_report("bonjour", session=session, root=tmp_path)
        assert not resultat.envoye

    def test_le_schema_doit_etre_https(self, tmp_path: Path) -> None:
        session = FausseSession(FausseReponse(202))
        resultat = report.send_report(
            "bonjour", url="http://rubin.maxyull.fr/v1/rapport", session=session, root=tmp_path
        )
        assert not resultat.envoye


class TestAucunSecretDansCetteApplication:
    def test_aucune_url_de_webhook_discord_n_est_embarquee(self) -> None:
        """⛔ Le point qui justifie tout ce module.

        Butin est distribué publiquement : une URL de webhook dans l'installeur
        serait lisible par n'importe quel joueur, le salon deviendrait
        spammable, et l'URL ne serait pas révocable sans republier
        l'application. Le webhook vit sur le relais, jamais ici.
        """
        source = Path(report.__file__).read_text(encoding="utf-8")
        assert "discord.com/api/webhooks" not in source
        assert {"rubin.maxyull.fr"} == report.ALLOWED_HOSTS
