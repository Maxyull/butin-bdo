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

    def __init__(
        self, status_code: int, donnees: object = None, url: str = discord_link.ACCOUNT_URL
    ):
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
        entete = page[
            page.index('id="discord-connexion"') - 2000 : page.index("</div>\n\n<div class=")
        ]
        assert "<input" not in entete, "un champ de saisie est apparu à côté du compte Discord"


class TestLaPagePrevientAvantDOuvrirLeNavigateur:
    """⛔ Une justification écrite et non implémentée est pire qu'une absence.

    L'en-tête de `discord_link.py` affirmait que « l'interface le dit avant
    d'ouvrir le navigateur ». Le mot « Rubin » n'apparaissait nulle part dans
    la page. Constaté le 07/08/2026 quand Maxime a cliqué sur le bouton et vu
    Discord lui demander d'autoriser un logiciel qu'il n'avait pas installé.

    Une docstring qui promet ce que le code ne fait pas empêche quiconque relit
    de voir le trou : elle répond à la question avant qu'on la pose.
    """

    def _page(self) -> str:
        from pathlib import Path

        return (
            Path(__file__).resolve().parents[1] / "src" / "butin" / "ui" / "static" / "index.html"
        ).read_text(encoding="utf-8")

    def test_la_page_previent_que_discord_affiche_rubin(self) -> None:
        page = self._page()
        assert 'id="discord-avertissement"' in page, "l'avertissement a disparu de la page"
        debut = page.index('id="discord-avertissement"')
        assert "Rubin" in page[debut : debut + 500], (
            "l'avertissement ne nomme plus l'application que Discord affichera"
        )

    def test_l_avertissement_est_masque_par_defaut(self) -> None:
        """Il ne doit pas s'afficher à quelqu'un de déjà rattaché.

        Une phrase qui survit à ce qu'elle explique dit quelque chose de faux :
        c'est le défaut déjà corrigé sur l'en-tête de mise à jour.
        """
        page = self._page()
        debut = page.index('id="discord-avertissement"')
        assert "hidden" in page[debut : debut + 60]

    def _corps_de_la_fonction(self, page: str, nom: str) -> str:
        """Le corps de la fonction, borné par son ACCOLADE, pas par un budget.

        ⚠️ La première version prenait « les 1 600 caractères qui suivent ». Elle
        a échoué le 08/08/2026 sur un ajout parfaitement correct de six lignes
        dans la fonction : la seconde moitié du test était sortie de la fenêtre,
        et le test annonçait un câblage manquant qui était là.

        Un test qui casse quand on allonge la fonction qu'il surveille ne
        surveille pas ce qu'il croit.
        """
        debut = page.index(f"function {nom}")
        fin = page.index("\n}", debut)
        return page[debut:fin]

    def test_le_script_le_masque_quand_le_compte_est_rattache(self) -> None:
        """Régression de câblage : l'élément peut exister et ne jamais bouger."""
        corps = self._corps_de_la_fonction(self._page(), "afficherLeCompteDiscord")

        assert "avertissement.hidden = true" in corps
        assert "avertissement.hidden = false" in corps

    def test_l_identite_de_l_en_tete_suit_les_deux_etats(self) -> None:
        """⭐ Même exigence pour la pastille posée dans l'en-tête le 08/08/2026.

        Elle affiche le pseudonyme Discord à côté du titre. Un élément qui
        apparaît et ne disparaît jamais annoncerait « connecté » à quelqu'un qui
        vient de se déconnecter — c'est le même défaut que l'avertissement
        ci-dessus, à l'autre bout.
        """
        page = self._page()
        corps = self._corps_de_la_fonction(page, "afficherLeCompteDiscord")

        assert 'id="identite-discord"' in page
        assert "identite.hidden = false" in corps
        assert "identite.hidden = true" in corps

    def test_le_pseudonyme_de_l_en_tete_n_est_jamais_injecte_en_HTML(self) -> None:
        """⛔ Il vient du relais, donc de Discord, donc de l'extérieur.

        `textContent` et jamais `innerHTML` : c'est la règle tenue partout
        ailleurs pour les noms d'objets, et elle vaut d'autant plus ici que
        celui-ci est choisi par une personne.
        """
        corps = self._corps_de_la_fonction(self._page(), "afficherLeCompteDiscord")

        assert '$("identite-discord-nom").textContent' in corps
        assert 'identite-discord-nom").innerHTML' not in corps


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
