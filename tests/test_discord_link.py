"""Tests du rattachement du compte Discord.

⛔ Le fil rouge de ce fichier est une seule question : **d'où vient le
pseudonyme affiché ?** S'il peut venir du joueur, ce n'est plus une connexion,
c'est une déclaration, et n'importe qui peut signaler un bogue sous le nom d'un
autre dans un salon public. La moitié des tests ci-dessous ne servent qu'à
empêcher qu'on brouille cette frontière un jour par commodité.

⭐ Le contrat du relais n'est pas invente : il a ete releve le 07/08/2026 sur
`https://rubin.maxyull.fr/openapi.json`, et les reponses ci-dessous sont celles
que le serveur rend vraiment (verifiees par appel reel avant d'ecrire ces
tests).
"""

from __future__ import annotations

import logging

import pytest
import requests

from butin import discord_link
from butin.discord_link import Compte, depuis_reponse, fetch_account, login_url, open_login


class _Reponse:
    """Une réponse HTTP minimale, sans réseau."""

    def __init__(self, status_code: int, donnees: object = None, url: str = discord_link.ACCOUNT_URL):
        self.status_code = status_code
        self.url = url
        self._donnees = donnees

    def json(self) -> object:
        if isinstance(self._donnees, Exception):
            raise self._donnees
        return self._donnees


class _Session:
    def __init__(self, reponse: object):
        self._reponse = reponse
        self.appels: list[dict] = []

    def get(self, url, **kwargs):
        self.appels.append({"url": url, **kwargs})
        if isinstance(self._reponse, Exception):
            raise self._reponse
        return self._reponse


class TestLeNomVientDuRelais:
    def test_aucune_fonction_ne_permet_de_POSER_un_nom(self) -> None:
        """⛔ Le test qui porte toute la conception.

        Le module lit un pseudonyme, il n'en enregistre jamais un. Ajouter une
        fonction qui en accepte un transformerait l'authentification en
        déclaration **sans que rien à l'écran ne change** : l'interface
        afficherait toujours « Connecté en tant que … », mais la phrase serait
        devenue fausse.
        """
        interdits = [
            nom
            for nom in dir(discord_link)
            if not nom.startswith("_")
            and any(v in nom.lower() for v in ("set_", "save", "store", "enregistr", "poser"))
        ]
        assert not interdits, f"ces fonctions permettraient de poser un nom : {interdits}"

    def test_la_page_n_a_aucun_champ_de_saisie_pour_le_pseudonyme(self) -> None:
        """Régression : le même défaut, mais côté interface.

        Le module aurait beau être irréprochable, un `<input>` dans l'en-tête
        suffirait à rétablir exactement ce que ce projet refuse ici.
        """
        from pathlib import Path

        page = (
            Path(__file__).resolve().parents[1] / "src" / "butin" / "ui" / "static" / "index.html"
        ).read_text(encoding="utf-8")
        entete = page[page.index('id="discord-connexion"') - 2000 : page.index("</div>\n\n<div class=")]
        assert "<input" not in entete, "un champ de saisie est apparu à côté du compte Discord"


class TestLectureDeLaReponse:
    def test_un_compte_rattache_rend_son_nom(self) -> None:
        assert depuis_reponse({"rattache": True, "nom": "maxyull"}) == Compte(True, "maxyull")

    def test_un_compte_non_rattache_ne_rend_aucun_nom(self) -> None:
        """Relevé réel : le relais rend `{"rattache":false,"nom":null}`."""
        assert depuis_reponse({"rattache": False, "nom": None}) == Compte(False, None)

    def test_un_nom_SANS_rattachement_est_traite_comme_non_rattache(self) -> None:
        """⛔ Régression : les deux champs peuvent se contredire.

        Ils sont indépendants dans le JSON. Faire confiance au nom seul
        afficherait « Connecté en tant que … » à quelqu'un qui ne l'est pas,
        c'est-à-dire précisément le mensonge que la connexion doit empêcher.
        """
        assert depuis_reponse({"rattache": False, "nom": "quelqu-un"}) == Compte(False, None)

    def test_un_rattachement_sans_nom_lisible_reste_un_rattachement(self) -> None:
        """On ne fabrique pas de pseudonyme, mais on ne nie pas le compte.

        L'interface a un repli (« Compte Discord connecté ») : mieux vaut une
        phrase sans nom qu'un nom inventé.
        """
        for vide in (None, "", "   ", 42):
            assert depuis_reponse({"rattache": True, "nom": vide}) == Compte(True, None)

    def test_le_nom_est_deshabille_de_ses_espaces(self) -> None:
        assert depuis_reponse({"rattache": True, "nom": "  maxyull  "}).nom == "maxyull"

    def test_une_reponse_qui_n_est_pas_un_objet_rend_INCONNU(self) -> None:
        for informe in ([], "rattache", None, 3):
            assert depuis_reponse(informe).inconnu is True


class TestInconnuNEstPasNonRattache:
    """⛔ La distinction la plus facile à perdre, et la plus visible à l'écran."""

    def test_une_panne_reseau_rend_INCONNU(self) -> None:
        """Et surtout pas `rattache=False`.

        Afficher « Se connecter » à quelqu'un de déjà rattaché lui ferait
        refaire une autorisation pour rien, et lui laisserait croire que le
        rattachement ne tient pas d'une fois sur l'autre.
        """
        compte = fetch_account("0" * 32, session=_Session(requests.ConnectionError("coupé")))
        assert compte.inconnu is True
        assert compte.rattache is False

    @pytest.mark.parametrize("code", [400, 404, 500, 502, 503])
    def test_un_code_d_erreur_rend_INCONNU(self, code: int) -> None:
        compte = fetch_account("0" * 32, session=_Session(_Reponse(code)))
        assert compte.inconnu is True

    def test_un_corps_illisible_rend_INCONNU(self) -> None:
        reponse = _Reponse(200, ValueError("ce n'est pas du JSON"))
        assert fetch_account("0" * 32, session=_Session(reponse)).inconnu is True

    def test_une_reponse_valide_n_est_PAS_inconnue(self) -> None:
        reponse = _Reponse(200, {"rattache": True, "nom": "maxyull"})
        compte = fetch_account("0" * 32, session=_Session(reponse))
        assert compte == Compte(True, "maxyull", inconnu=False)


class TestGardeDHote:
    """Même politique que `report.py` et `update.py` : un seul hôte."""

    def test_l_hote_est_verifie_APRES_redirection(self) -> None:
        """⛔ Une redirection sortante ne doit pas emporter l'identifiant.

        L'identifiant du contributeur EST la clé du rattachement : le relais
        signe un état qui le contient. Le laisser partir vers un autre hôte
        parce qu'un 302 l'a demandé donnerait à ce tiers de quoi rattacher son
        propre compte Discord au numéro du joueur.
        """
        reponse = _Reponse(200, {"rattache": True, "nom": "x"}, url="https://ailleurs.example/v1")
        assert fetch_account("0" * 32, session=_Session(reponse)).inconnu is True

    def test_l_url_de_connexion_reste_sur_le_relais(self) -> None:
        assert login_url("abc").startswith("https://rubin.maxyull.fr/v1/discord/connexion?")

    def test_un_identifiant_special_est_encode(self) -> None:
        """Sans encodage, un `&` couperait la requête en deux.

        Le relais verrait alors un identifiant tronqué, qu'il refuserait sans
        que personne ne comprenne pourquoi.
        """
        assert "player=a%26b%3Dc" in login_url("a&b=c")


class TestOuvertureDuNavigateur:
    def test_elle_passe_par_le_navigateur_du_SYSTEME(self) -> None:
        """Pas la fenêtre de Butin.

        Une page d'autorisation affichée sans barre d'adresse est exactement ce
        qu'on apprend aux gens à ne pas remplir. Là, la personne voit
        `discord.com` et son cadenas.
        """
        vues: list[str] = []
        assert open_login("0" * 32, opener=lambda url: vues.append(url) or True) is True
        assert vues == [login_url("0" * 32)]

    def test_un_navigateur_absent_ne_leve_pas(self, caplog: pytest.LogCaptureFixture) -> None:
        """Régression : signaler un bogue ne doit jamais planter l'application.

        Même garantie que `send_report`. Une machine sans navigateur par défaut
        existe, et l'exception remonterait jusque dans la fenêtre.
        """

        def casse(_url: str) -> bool:
            raise OSError("aucun navigateur")

        with caplog.at_level(logging.WARNING):
            assert open_login("0" * 32, opener=casse) is False

    def test_un_navigateur_qui_rend_faux_est_rapporte_comme_un_echec(self) -> None:
        """`webbrowser.open` rend `False` sans lever quand rien ne s'ouvre.

        Le prendre pour un succès afficherait « Autorise dans ton navigateur »
        devant une fenêtre qui ne s'est jamais ouverte.
        """
        assert open_login("0" * 32, opener=lambda _url: False) is False
