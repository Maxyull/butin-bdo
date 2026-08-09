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
from typing import ClassVar

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
        par-dessus le chat 247 secondes, et perdu 560 objets sur 4 080.

        ⚠️ Les schémas ont été REDESSINÉS le 08/08/2026 d'après quatre captures
        du vrai écran de Maxime. Le précédent accusait l'inventaire, qui chez
        lui s'ouvre à DROITE et ne recouvre rien : les coupables sont les
        fenêtres de gauche, menu Échap, Mes informations, boîte aux lettres.
        Un schéma qui accuse la mauvaise fenêtre apprend à surveiller la
        mauvaise chose.
        """
        bloc = _bloc_du_schema(page("index.html"))

        assert "menu Échap" in bloc
        assert "Mes informations" in bloc
        assert "boîte aux lettres" in bloc
        assert bloc.count("<figure") == 3

    def test_l_obstruction_PARTIELLE_est_montree(self) -> None:
        """⭐ Le cas le plus dangereux, et il manquait aux trois schémas.

        Vu sur une capture réelle : « Mes informations » ne couvre que le HAUT
        de la zone, deux lignes restent visibles en dessous. Butin continue donc
        de lire et de compter, sur un tiers de ce qui passe.

        C'est pire qu'un recouvrement total, pour la raison qui revient partout
        dans ce projet : un compteur arrêté finit par se voir, un compteur qui
        compte à moitié ressemble à un farm calme. Et l'alerte « je ne vois plus
        le chat » de la 0.8.1 se tait, puisqu'il reste des lignes.
        """
        bloc = _bloc_du_schema(page("index.html"))

        assert "haut" in bloc.lower()
        assert "farm calme" in bloc


class TestLesBarresDeDefilementSuiventLeTheme:
    """⚠️ Elles restaient au thème CLAIR du système sur deux pages sombres.

    Rien dans la palette ne les atteignait : le moteur les dessine lui-même
    tant qu'on ne lui dit pas que la page est sombre. Signalé par Maxime le
    08/08/2026.
    """

    @pytest.mark.parametrize("nom", PAGES)
    def test_la_page_se_declare_sombre(self, nom: str) -> None:
        """`color-scheme: dark` est le vrai correctif : il reteint la barre et
        tout ce que le système dessine lui-même. À lui seul, il suffirait."""
        assert "color-scheme: dark" in page(nom)

    @pytest.mark.parametrize("nom", PAGES)
    def test_scrollbar_color_n_est_PAS_pose(self, nom: str) -> None:
        """⛔ Régression mesurée, et parfaitement contre-intuitive.

        `scrollbar-color` est la propriété standard, donc l'ajouter « en plus »
        pour couvrir plus de moteurs semble prudent. C'est l'inverse : dès
        qu'elle est posée, Chromium **ignore** toutes les règles
        `::-webkit-scrollbar`. Mesuré dans un navigateur, la barre du fil
        restait à 15 px alors que la règle en demandait 10, et la piste du
        panneau redevenait opaque par-dessus le jeu.

        Ce n'était pas une ceinture avec des bretelles, c'était une ceinture
        qui coupait les bretelles. Le repli reste sain sans elle :
        `color-scheme` donne déjà une barre sombre.

        ⚠️ Le test vise `scrollbar-color:` **avec son deux-points**, donc la
        déclaration et pas la mention. Les deux pages en parlent en commentaire
        pour expliquer pourquoi elles ne la posent pas, et une règle qui
        interdirait d'en parler ferait disparaître l'explication en même temps
        que le piège.
        """
        assert "scrollbar-color:" not in page(nom)

    @pytest.mark.parametrize("nom", PAGES)
    def test_la_piste_reste_transparente(self, nom: str) -> None:
        """⛔ Vital sur le panneau, qui est posé PAR-DESSUS le jeu : une piste
        peinte serait un rectangle opaque de plus, visible en permanence même
        quand la liste tient entièrement."""
        source = page(nom)
        _, marque, apres = source.partition("::-webkit-scrollbar-track")
        assert marque, f"{nom} : aucune règle de piste, la barre garde celle du système"
        assert "transparent" in apres.partition("}")[0]


class TestLeParcoursGuide:
    """⭐ Le parcours demandé par Maxime le 08/08/2026 : un seul bouton, une
    étape à la fois.

    ⛔ « Calibrer la zone » a disparu, et c'est le cœur de la demande. Le
    calibrage se faisait à part, donc il s'oubliait — et une zone non calibrée
    donne un compteur à zéro qui ressemble à un farm pauvre. Une session réelle
    a tourné 462 secondes pour zéro objet compté.
    """

    #: L'ordre des étapes, tel que le parcours doit les enchaîner.
    ETAPES: ClassVar[list[str]] = [
        "parcoursCalibrer",
        "parcoursDemarrer",
        "parcoursInventaire",
        "parcoursVerifier",
        "parcoursArreter",
        "parcoursSignaler",
    ]

    def test_le_bouton_calibrer_a_disparu_partout(self) -> None:
        """⛔ Retirer le bouton sans retirer son `$()` arrête le
        rafraîchissement : page présentable et morte, défaut #34."""
        source = page("index.html")

        assert "bouton-calibrer" not in identifiants_declares(source)
        assert "bouton-calibrer" not in identifiants_demandes(source)

    @pytest.mark.parametrize("etape", ETAPES)
    def test_chaque_etape_du_parcours_existe(self, etape: str) -> None:
        assert f"function {etape}(" in page("index.html").replace("async ", "")

    def test_le_parcours_a_son_bloc_et_il_est_masque_au_depart(self) -> None:
        """Il ne doit pas occuper l'écran tant que rien n'a commencé."""
        source = page("index.html")
        declares = identifiants_declares(source)

        for identifiant in ("parcours", "parcours-titre", "parcours-texte", "parcours-boutons"):
            assert identifiant in declares
        bloc = source[source.index('<div id="parcours"') :][:120]
        assert "hidden" in bloc

    def test_la_session_demarre_AVANT_la_photo_de_depart(self) -> None:
        """⚠️ L'ordre réel n'est pas celui qu'on décrirait à voix haute.

        Une capture d'inventaire se range par session, et il n'y en a pas encore
        avant le démarrage. La photo de départ vient donc après, et les quelques
        secondes qui passent comptent pour le compteur et pas pour l'inventaire.
        C'est dit à l'écran plutôt que découvert dans les chiffres.
        """
        source = page("index.html")
        corps = source[source.index("async function parcoursDemarrer") :]
        corps = corps[: corps.index("\n}\n")]

        assert "/api/session/demarrer" in corps
        assert 'parcoursInventaire("avant")' in corps
        assert corps.index("/api/session/demarrer") < corps.index('parcoursInventaire("avant")')

    def test_un_calibrage_rate_ARRETE_le_parcours(self) -> None:
        """⛔ Démarrer sur un calibrage raté donnerait une session qui ne compte
        rien, et rien à l'écran ne le dirait. Le parcours s'arrête et propose de
        recommencer."""
        source = page("index.html")
        corps = source[source.index("async function parcoursCalibrer") :]
        corps = corps[: corps.index("\nasync function parcoursDemarrer")]

        assert "Calibrage impossible" in corps
        assert "Réessayer" in corps
        # ⛔ Et un calibrage DOUTEUX est montré, pas avalé : le calibrage
        # automatique a déjà rendu 448 px là où il en fallait 662.
        assert "Calibrage douteux" in corps

    def test_le_signalement_prepare_l_archive_sans_l_envoyer(self) -> None:
        """⛔ « Prête à envoyer » n'est pas « envoyée ».

        L'archive contient les messages des AUTRES joueurs et des captures
        d'écran entier. Elle reste sur le disque, le dossier s'ouvre dessus, et
        c'est le joueur qui dépose. Seul le rapport texte part tout seul.
        """
        source = page("index.html")
        corps = source[source.index("async function parcoursSignaler") :]
        corps = corps[: corps.index("\n// L'affichage du résultat")]

        assert "/api/rapport" in corps
        assert "/api/archive" in corps
        assert "n'est envoyée à personne" in corps


class TestLePanneauNeCourtCircuitePlusLeParcours:
    """⛔ Le bouton « Arrêter » du panneau sautait la photo d'arrivée.

    Trouvé par Maxime **à l'usage** le 09/08/2026, et c'était un angle mort
    complet : le panneau posé sur le jeu a son propre bouton « Arrêter », qui
    appelle `/api/session/arreter` en direct. Le parcours guidé ne couvrait que
    le bouton de la fenêtre principale, donc la photo d'inventaire d'ARRIVÉE
    n'était jamais demandée — et c'est évidemment le bouton du panneau qu'on
    clique, puisque c'est le seul écran qu'on regarde en farmant.

    ⛔ Ce que ça coûte : sans les deux bouts, une session ne peut plus être
    comparée qu'à elle-même. L'inventaire est la seule vérité de ce logiciel qui
    ne passe par aucune reconnaissance d'écran.

    ⭐ Le correctif ne touche NI au panneau NI au serveur : la fenêtre
    principale s'aperçoit toute seule qu'une session vient de finir sans photo
    d'arrivée. Ces tests figent les trois pièces qui le rendent possible.
    """

    def test_le_panneau_arrete_toujours_en_direct(self) -> None:
        """⚠️ Le cas gardé, et il n'est pas hypothétique : c'est le comportement
        du panneau, laissé tel quel EXPRÈS.

        Le panneau est la fenêtre la plus délicate du produit — elle est posée
        par-dessus le jeu — et le correctif a été choisi pour ne pas y toucher.
        Si ce test tombe un jour parce que le panneau est passé par le parcours,
        la surveillance de la fenêtre principale devient inutile : c'est le
        moment de la retirer, pas de la garder par précaution.
        """
        assert "/api/session/arreter" in page("overlay.html")

    def test_la_fenetre_principale_surveille_la_fin_de_session(self) -> None:
        source = page("index.html")

        assert "function surveillerLaFinDeSession(" in source
        # Appelée depuis `afficher`, donc à chaque rafraîchissement d'une
        # seconde : c'est le seul endroit qui voit passer l'état du serveur.
        corps = source[source.index("function afficher(etat)") :]
        corps = corps[: corps.index("\n}\n")]
        assert "surveillerLaFinDeSession(etat)" in corps

    def test_la_surveillance_pose_l_etape_manquante(self) -> None:
        """Une session vue en cours, puis plus de session : la photo d'arrivée
        est demandée pour celle qui vient de finir."""
        source = page("index.html")
        corps = source[source.index("function surveillerLaFinDeSession(") :]
        corps = corps[: corps.index("\n}\n")]

        assert 'parcoursInventaire("apres", finie, true)' in corps

    def test_la_surveillance_ne_repose_pas_une_etape_deja_posee(self) -> None:
        """⛔ Sans ce garde, le parcours se déclencherait sur son PROPRE arrêt.

        Le bouton de la fenêtre principale demande la photo, prend la photo,
        puis arrête la session — et cet arrêt-là est exactement ce que la
        surveillance guette. Elle reposerait la question du compte par-dessus sa
        propre réponse.
        """
        source = page("index.html")
        corps = source[source.index("function surveillerLaFinDeSession(") :]
        corps = corps[: corps.index("\n}\n")]

        assert "finie === arriveeDemandee" in corps

    def test_une_session_deja_arretee_n_est_pas_rearretee(self) -> None:
        """⛔ Repasser par `/api/session/arreter` ne fermerait rien — le serveur
        sort tout de suite s'il n'y a pas de session — mais donnerait
        l'illusion que le parcours maîtrise l'arrêt alors qu'il le rattrape."""
        source = page("index.html")
        corps = source[source.index("async function photographier(") :]
        corps = corps[: corps.index("\n}\n")]

        assert "} else if (arretee) {" in corps
        assert "parcoursLeCompteEstBon(session)" in corps
        # L'arrêt reste le chemin normal quand la session tourne encore.
        assert "parcoursArreter(session)" in corps

    def test_la_question_du_compte_est_separee_de_l_arret(self) -> None:
        """C'est ce qui rend le rattrapage possible : le même écran doit être
        posé après un arrêt venu du panneau, où il n'y a plus rien à arrêter."""
        source = page("index.html")

        assert "function parcoursLeCompteEstBon(session)" in source
        assert "Le compte est bon ?" in source

    def test_l_identifiant_de_session_ne_vient_PAS_de_la_reponse_d_arret(self) -> None:
        """⛔ Défaut réel, présent depuis #112 et invisible à l'écran.

        `/api/session/arreter` rend l'état d'APRÈS l'arrêt, donc `session` y
        vaut `null`. `corps.session ? corps.session.id : null` rendait donc
        toujours `null`, et « Oui, c'est juste » ne rouvrait jamais la session
        dans l'Historique. La promesse était affichée, le geste manquait.
        """
        source = page("index.html")
        corps = source[source.index("async function parcoursArreter(") :]
        corps = corps[: corps.index("\n}\n")]

        assert "corps.session" not in corps
        assert "parcoursLeCompteEstBon(session)" in corps


class TestLaSourisTraverseLePanneau:
    """⭐ Demandé par Maxime le 09/08/2026 : « je passe dessus et ça affiche la
    souris, c'est chiant ».

    Le panneau laisse maintenant passer la souris. ⛔ Le prix est qu'il ne
    reçoit plus AUCUN clic, et c'est ce que ces tests gardent : la case existe
    du côté où elle reste cliquable, et le panneau ne montre pas des boutons
    qui ne peuvent plus rien faire.
    """

    def test_la_case_est_dans_les_reglages_et_pas_dans_le_panneau(self) -> None:
        """⛔ Elle ne peut pas vivre dans le panneau : quand elle est cochée,
        le panneau ne reçoit plus de clic, donc plus moyen de la décocher.
        Le réglage qui rend une fenêtre inerte ne peut pas habiter dedans."""
        assert "souris-traversante" in identifiants_declares(page("index.html"))
        assert "souris-traversante" not in identifiants_declares(page("overlay.html"))

    def test_la_case_dit_ce_qu_elle_coute(self) -> None:
        """Un bouton qui ne répond plus se lit comme un logiciel cassé. La page
        doit donc annoncer la contrepartie avant qu'on la découvre."""
        source = page("index.html")
        bloc = source[source.index('id="souris-traversante"') :][:700]

        assert "répond plus à rien" in bloc
        assert "Recalibrer" in bloc

    def test_le_panneau_retire_ses_boutons_quand_la_souris_le_traverse(self) -> None:
        source = page("overlay.html")
        corps = source[source.index("function afficher(etat)") :]
        corps = corps[: corps.index("\n}\n")]

        assert "reglages.souris_traversante" in corps
        for bouton in ("recalibrer", "pause", "fermer"):
            assert bouton in corps

    def test_le_panneau_dit_pourquoi_ses_boutons_ont_disparu(self) -> None:
        """Trois boutons qui disparaissent sans un mot, c'est une panne ; avec
        un mot, c'est un réglage."""
        source = page("overlay.html")

        assert "sans-clic" in identifiants_declares(source)
        assert "pilote depuis la fenêtre Butin" in source


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


class TestHiddenCacheVraiment:
    """⛔ `hidden` ne cachait RIEN sur deux éléments, dont un bouton VIDE.

    Trouvé le 08/08/2026 par Maxime, à l'œil : « c'est quoi le truc jaune qui
    sert à rien ». C'était le bouton de mise à jour, affiché en permanence,
    vide, y compris sur la dernière version.

    La règle `[hidden] { display: none }` vient de la feuille du **navigateur**.
    N'importe quelle règle d'auteur qui pose un `display` la bat, sans le moindre
    avertissement. `.bouton-maj` était en `inline-block` ; `.identite-discord`,
    posée le jour même, avait le même défaut au même endroit.

    ⚠️ **Et le contrôle au navigateur ne pouvait pas le voir** : il lisait
    `element.hidden`, qui dit que l'ATTRIBUT est posé, pas que l'élément est
    invisible. Deux questions différentes, et une seule des deux compte.
    """

    _DISPLAY = re.compile(r"\.([a-z-]+)\s*\{([^}]*)\}")
    _BALISE = re.compile(r"<[a-z]+[^>]*>")

    def _classes_qui_posent_un_display(self, source: str) -> set[str]:
        return {
            m.group(1)
            for m in self._DISPLAY.finditer(source)
            if re.search(r"(^|[;\s])display\s*:", m.group(2))
        }

    @pytest.mark.parametrize("nom", PAGES)
    def test_la_regle_globale_est_posee(self, nom: str) -> None:
        """Une seule ligne rend la classe d'erreur impossible, et `!important`
        est délibéré : c'est une règle qui doit gagner contre celles qu'on
        écrira demain."""
        assert "[hidden] { display: none !important; }" in page(nom)

    @pytest.mark.parametrize("nom", PAGES)
    def test_aucun_element_masque_ne_porte_une_classe_qui_le_reaffiche(self, nom: str) -> None:
        """La règle globale suffit, mais ce test dit CE QU'ELLE GARDE.

        Sans lui, on pourrait la retirer un jour en la croyant décorative. Il
        nomme les éléments qui redeviendraient visibles.
        """
        source = page(nom)
        avec_display = self._classes_qui_posent_un_display(source)

        coupables = []
        for m in self._BALISE.finditer(source):
            balise = m.group(0)
            if "hidden" not in balise:
                continue
            classes = re.search(r'class="([^"]+)"', balise)
            if not classes:
                continue
            touchees = avec_display & set(classes.group(1).split())
            if touchees:
                ident = re.search(r'id="([^"]+)"', balise)
                coupables.append((ident.group(1) if ident else "?", sorted(touchees)))

        # ⚠️ On n'exige PAS zéro coupable : la règle globale les neutralise, et
        # interdire la combinaison obligerait à contorsionner le style. Ce qui
        # est exigé, c'est que la règle globale soit là quand il y en a.
        if coupables:
            assert "[hidden] { display: none !important; }" in source, (
                f"{nom} : {coupables} redeviennent visibles sans la règle globale"
            )
