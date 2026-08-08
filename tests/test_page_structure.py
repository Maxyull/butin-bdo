"""Ce que la fenêtre principale doit contenir, et ce qu'elle ne doit plus.

Pourquoi ce fichier existe
---------------------------

⛔ **Le mode de défaillance de ce projet est une page qui s'affiche
normalement et ne réagit plus à rien.** C'est arrivé une fois pour de vrai
(#34, six PR écrites au-dessus d'une page morte), et la cause était toujours la
même forme : le bloc de script tombe en entier, sans que rien ne se voie.

`test_page_script.py` couvre **une** cause de chute : une chaîne coupée par une
fin de ligne. Il en existe une seconde, plus banale et pas couverte : le script
demande un élément qui n'existe plus dans le HTML. `$("par-heure").textContent`
sur un `null` lève un `TypeError` dans `afficher`, donc arrête le
rafraîchissement d'une seconde — et la page reste affichée avec ses tableaux
vides, exactement comme une application qui vient de démarrer.

Le cas s'est présenté le 08/08/2026 en retirant les quatre chiffres de
l'en-tête : quatre `$()` pointaient dessus. Le retrait était propre, mais rien
n'aurait dit le contraire.

⚠️ Ce fichier lit le HTML, il n'exécute rien. Il ne remplace pas la
vérification dans un vrai navigateur, qui reste obligatoire pour toute
modification des deux pages.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PAGES = ("index.html", "overlay.html")

STATIC = Path(__file__).resolve().parents[1] / "src" / "butin" / "ui" / "static"

#: Les quatre onglets, dans l'ordre demandé par Maxime le 08/08/2026.
ONGLETS = ("session", "historique", "reglages", "rapport")

_APPEL_DOLLAR = re.compile(r"""\$\(\s*["']([A-Za-z0-9_-]+)["']\s*\)""")
_IDENTIFIANT = re.compile(r"""\bid=["']([A-Za-z0-9_-]+)["']""")


def page(nom: str) -> str:
    return (STATIC / nom).read_text(encoding="utf-8")


def identifiants_declares(source: str) -> set[str]:
    return set(_IDENTIFIANT.findall(source))


def identifiants_demandes(source: str) -> set[str]:
    """Les identifiants que le script demande par un littéral.

    ⚠️ Ne voit **que** les littéraux. `$("onglet-" + nom)` est invisible ici,
    et c'est assumé : ce test attrape la classe d'erreur qui a mordu, pas
    toutes celles qu'on pourrait imaginer. Prétendre le contraire serait la
    justification écrite et non implémentée que ce dépôt refuse.

    ⚠️ Il ne suit pas les commentaires non plus, donc un `$("truc")` **cité
    dans un commentaire** compte. C'est le bon sens de l'erreur pour un
    garde-fou — il échoue bruyamment au lieu de laisser passer — et c'est
    arrivé une fois, en écrivant le commentaire qui explique ce test.
    """
    return set(_APPEL_DOLLAR.findall(source))


class TestLeScriptNeDemandeQueCeQuiExiste:
    """⭐ Régression : retirer un élément sans retirer son `$()` tue la page.

    Le 08/08/2026, les quatre chiffres de l'en-tête (silver/heure, total,
    durée, objets valorisés) ont été retirés à la demande de Maxime. Quatre
    lignes d'`afficher` les écrivaient encore. Laissées en place, elles
    auraient levé `TypeError: Cannot set properties of null` à la première
    seconde, ce qui arrête `afficher`, donc le rafraîchissement, donc tout —
    en laissant une page parfaitement présentable à l'écran.
    """

    @pytest.mark.parametrize("nom", PAGES)
    def test_chaque_identifiant_demande_est_declare(self, nom: str) -> None:
        source = page(nom)
        manquants = sorted(identifiants_demandes(source) - identifiants_declares(source))

        assert manquants == [], (
            f"{nom} : le script demande {manquants}, qui n'existe(nt) pas dans le HTML. "
            "Un seul suffit à arrêter le rafraîchissement sans que la page change d'allure."
        )

    def test_le_detecteur_voit_le_cas_qu_il_garde(self) -> None:
        """⛔ Un garde-fou qui ne peut pas échouer ne garde rien.

        Le cas exact évité : l'élément est parti du HTML, le `$()` est resté.
        """
        casse = '<div id="reste"></div>\n$("reste"); $("par-heure").textContent = "0";'

        assert identifiants_demandes(casse) - identifiants_declares(casse) == {"par-heure"}


class TestLesQuatreOngletsExistent:
    """⚠️ Le mécanisme était codé en dur pour DEUX onglets.

    `basculer` portait un booléen `surSession` et écrivait chaque ligne deux
    fois, en niant l'autre. Passer à quatre de cette façon aurait demandé une
    condition par onglet dans chaque ligne : seize endroits où oublier le
    nouveau. Ce test fige la correspondance onglet ↔ page, quel que soit le
    nombre.
    """

    @pytest.mark.parametrize("onglet", ONGLETS)
    def test_chaque_onglet_a_sa_page(self, onglet: str) -> None:
        declares = identifiants_declares(page("index.html"))

        assert f"onglet-{onglet}" in declares
        assert f"page-{onglet}" in declares

    def test_aucun_onglet_orphelin(self) -> None:
        """Un onglet ajouté au HTML sans entrer dans la liste du script ne
        répondrait à aucun clic : le bouton est là, il ne fait rien."""
        source = page("index.html")
        boutons = {
            i.removeprefix("onglet-")
            for i in identifiants_declares(source)
            if i.startswith("onglet-")
        }

        assert boutons == set(ONGLETS)

    def test_la_liste_du_script_porte_les_quatre(self) -> None:
        """La liste est la seule chose à tenir à jour, donc elle est vérifiée."""
        source = page("index.html")
        declaration = re.search(r"const ONGLETS = \[(.*?)\];", source, re.S)

        assert declaration is not None, "la liste ONGLETS a disparu du script"
        assert set(re.findall(r'"([a-z]+)"', declaration.group(1))) == set(ONGLETS)


class TestLEnTeteEstAllege:
    """Les quatre chiffres sont partis, et de partout.

    Demandé par Maxime le 08/08/2026 : ils sont déjà dans le panneau posé sur
    le jeu — le seul écran regardé en farmant — et dans l'Historique, qui est
    l'écran regardé après. Les tenir à trois endroits n'ajoutait pas une
    information, ça allongeait la page.
    """

    @pytest.mark.parametrize("chiffre", ["par-heure", "total", "duree", "couverture"])
    def test_le_chiffre_n_est_plus_ni_dans_le_html_ni_dans_le_script(self, chiffre: str) -> None:
        source = page("index.html")

        assert chiffre not in identifiants_declares(source)
        assert chiffre not in identifiants_demandes(source)


class TestCeQuIlFautVoir:
    """Les deux boutons demandés le 08/08/2026, et ce qu'ils montrent."""

    def test_les_deux_boutons_sont_la(self) -> None:
        declares = identifiants_declares(page("index.html"))

        assert "bouton-schema" in declares
        assert "bouton-mon-ecran" in declares

    def test_le_schema_est_DESSINE_jamais_une_capture(self) -> None:
        """⛔ Décision explicite, et elle tient à la vie privée de tiers.

        Toutes les captures d'écran disponibles contiennent le chat de guilde,
        donc les pseudonymes d'autres joueurs, et ce dépôt est **public**. Le
        schéma est du SVG dessiné à la main : il dit la même chose sans
        exposer personne, et il ne pèse rien dans la distribution.
        """
        bloc = _bloc_du_schema(page("index.html"))

        assert "<svg" in bloc
        assert "<img" not in bloc, (
            "une image dans le schéma : ce doit être un dessin, pas une capture"
        )

    def test_les_trois_erreurs_sont_montrees(self) -> None:
        """⛔ Ce n'est pas décoratif : la session 0014 a laissé le menu Échap
        par-dessus le chat 247 secondes, et perdu 560 objets sur 4 080."""
        bloc = _bloc_du_schema(page("index.html"))

        assert "inventaire" in bloc.lower()
        assert "menu Échap" in bloc
        assert bloc.count("<figure") == 3


def _bloc_du_schema(source: str) -> str:
    """Le contenu de `#schema-zone`, découpé sur ses balises littérales.

    Pas d'expression régulière sur des balises HTML : CodeQL la refuse
    (`py/bad-tag-filter`, sévérité haute) parce qu'un motif de ce genre ne
    reconnaît pas les variantes en majuscules, et le découpage littéral fait le
    même travail sur un fichier qui est le nôtre.
    """
    _, marque, reste = source.partition('id="schema-zone"')
    assert marque, "le bloc du schéma a disparu de la page"
    # Jusqu'à la ligne d'état de « Mon écran », qui suit immédiatement le bloc.
    # ⚠️ Un premier découpage allait jusqu'à `extrait-calibrage`, plus bas : il
    # emportait l'aperçu de « Mon écran », qui est une vraie balise `img`, et
    # faisait échouer le test sur une image parfaitement légitime. Un délimiteur
    # trop large ne mesure plus ce qu'il annonce.
    bloc, fin, _ = reste.partition('<div id="mon-ecran-etat"')
    assert fin, "impossible de délimiter le bloc du schéma"
    return bloc
