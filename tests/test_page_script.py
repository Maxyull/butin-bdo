"""Le script des deux pages doit au moins être analysable par un navigateur.

Pourquoi ce test existe
------------------------

Le 05/08/2026, la fenêtre principale a été ouverte dans un vrai navigateur pour
la première fois. Son script ne se chargeait pas du tout : une vraie fin de
ligne s'était glissée dans une chaîne de caractères JavaScript, ce qui est une
erreur de syntaxe, et une erreur de syntaxe fait tomber **tout le bloc**
`<script>`.

Conséquence : plus de rafraîchissement, plus de bouton, plus de calibrage, plus
de fil des drops. La page s'affichait normalement, avec ses titres, ses tableaux
vides et ses zéros — c'est-à-dire exactement comme une application qui vient de
démarrer et n'a rien à montrer.

Rien ne l'avait vu, parce que `test_ui.py` interroge un vrai serveur mais pas un
vrai navigateur : il vérifie le contrat de l'API et la présence des identifiants
dans le HTML, ce que le texte de la page satisfait même quand son script est
mort.

Ce que ce test est, et ce qu'il n'est pas
------------------------------------------

Ce n'est **pas** un analyseur JavaScript. C'est un détecteur pour une classe
d'erreur précise : une fin de ligne brute dans une chaîne entre apostrophes ou
guillemets. Il suit les états qui peuvent la masquer — commentaires de ligne et
de bloc, chaînes, gabarits entre accents graves, où une fin de ligne est
légitime.

Il ne connaît pas les littéraux d'expression régulière. Un motif contenant une
apostrophe ou un guillemet le ferait dérailler, et il échouerait bruyamment
plutôt que de laisser passer : c'est le bon sens de l'erreur pour un garde-fou.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PAGES = ("index.html", "overlay.html")

STATIC = Path(__file__).resolve().parents[1] / "src" / "butin" / "ui" / "static"

# Les trois façons d'ouvrir une chaîne, et le caractère qui la referme. Seul le
# gabarit entre accents graves accepte une vraie fin de ligne.
_OUVERTURES = {"'": "apostrophe", '"': "guillemet", "`": "gabarit"}
_FERMETURES = {etat: car for car, etat in _OUVERTURES.items()}
_COUPABLES = ("apostrophe", "guillemet")


def script_de(page: str) -> str:
    """Le contenu du bloc `<script>` de la page.

    Découpé sur les balises littérales plutôt qu'avec une expression
    régulière : le fichier lu est le nôtre, il en contient exactement un, et une
    expression régulière qui prétend reconnaître des balises HTML est un piège
    documenté qu'on n'a aucune raison de poser ici.

    Le compte est vérifié plutôt que supposé. Un second bloc ajouté un jour
    passerait sinon en silence, non vérifié, ce qui est exactement l'angle mort
    qui a rendu ce fichier nécessaire.
    """
    contenu = (STATIC / page).read_text(encoding="utf-8")
    morceaux = contenu.split("<script>")
    assert len(morceaux) == 2, f"{page} : {len(morceaux) - 1} blocs <script>, le test en attend un"
    corps, fermeture, _ = morceaux[1].partition("</script>")
    assert fermeture, f"{page} : bloc <script> jamais refermé"
    return corps


def fins_de_ligne_dans_une_chaine(source: str) -> list[int]:
    """Numéros de ligne où une chaîne JavaScript est coupée par un saut de ligne.

    Une chaîne entre `'` ou `"` ne peut pas contenir de fin de ligne brute : le
    navigateur rejette tout le bloc. Un gabarit entre accents graves, si.
    """
    fautes: list[int] = []
    ligne = 1
    etat = "code"
    index = 0
    while index < len(source):
        car = source[index]
        suivant = source[index + 1] if index + 1 < len(source) else ""

        if car == "\n":
            ligne += 1
            if etat in _COUPABLES:
                fautes.append(ligne - 1)
                etat = "code"
            elif etat == "commentaire_ligne":
                etat = "code"
            index += 1
            continue

        if etat in _FERMETURES and car == "\\":
            # L'échappement mange le caractère suivant, y compris un guillemet
            # ou une barre oblique inverse.
            index += 2
            continue

        if etat == "code":
            if car == "/" and suivant == "/":
                etat = "commentaire_ligne"
                index += 2
                continue
            if car == "/" and suivant == "*":
                etat = "commentaire_bloc"
                index += 2
                continue
            etat = _OUVERTURES.get(car, "code")
        elif etat == "commentaire_bloc":
            if car == "*" and suivant == "/":
                etat = "code"
                index += 2
                continue
        elif car == _FERMETURES.get(etat):
            etat = "code"

        index += 1
    return fautes


@pytest.mark.parametrize("page", PAGES)
def test_aucune_chaine_coupee_par_une_fin_de_ligne(page: str) -> None:
    """⭐ Régression : la fenêtre principale était entièrement morte.

    Le cas réel, relevé le 05/08/2026 dans la page servie par le programme :

        extrait.textContent = ... +
          "
    " + (corps.extrait.length ? corps.extrait.join("

    Un `\\n` avait été écrit comme une vraie fin de ligne. Le navigateur
    refusait le bloc entier, donc la page n'avait plus ni rafraîchissement, ni
    bouton, ni calibrage — et rien ne le disait, puisqu'une application au repos
    affiche elle aussi des zéros et des tableaux vides.
    """
    fautes = fins_de_ligne_dans_une_chaine(script_de(page))

    assert fautes == [], f"{page} : chaîne coupée aux lignes {fautes} du bloc <script>"


class TestLeDetecteur:
    """Un garde-fou qui ne peut pas échouer ne garde rien.

    Ces trois cas fixent ce que le détecteur voit et ce qu'il laisse passer,
    sur le code réel de la page.
    """

    def test_il_voit_la_faute_qui_a_eu_lieu(self) -> None:
        """Le code exact tel qu'il était sur `main` avant la correction.

        ⚠️ Il rend **une** faute et non deux, alors que le code en contenait
        deux. Après une chaîne coupée, les guillemets restants se réapparient
        autrement et la seconde coupure disparaît du compte. C'est sans
        importance ici : une erreur de syntaxe fait tomber tout le bloc, donc
        un seul signal suffit à condamner la page. Compter juste demanderait un
        vrai analyseur JavaScript.
        """
        casse = (
            '      "\n" + (corps.extrait.length ? corps.extrait.join("\n") : "(aucun texte lu)");'
        )

        assert fins_de_ligne_dans_une_chaine(casse) == [1]

    def test_un_saut_de_ligne_echappe_est_correct(self) -> None:
        """Le même code une fois corrigé, tel qu'il est maintenant."""
        correct = (
            '      "\\n" + (corps.extrait.length ? corps.extrait.join("\\n") : "(aucun texte lu)");'
        )

        assert fins_de_ligne_dans_une_chaine(correct) == []

    def test_un_gabarit_peut_tenir_sur_plusieurs_lignes(self) -> None:
        """La page en contient un vrai, dans `duree()` : `${h}:${m}:${s}`."""
        assert fins_de_ligne_dans_une_chaine("const x = `deux\nlignes`;") == []

    def test_une_apostrophe_dans_un_commentaire_ne_compte_pas(self) -> None:
        """Le projet écrit ses commentaires en français : « l'image », « d'où »,
        « c'est ». Sans le suivi des commentaires, chacun ouvrirait une chaîne
        fantôme et le détecteur crierait à chaque ligne."""
        assert (
            fins_de_ligne_dans_une_chaine("// un nom d'objet vient d'ailleurs\nconst x = 1;") == []
        )
