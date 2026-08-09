"""Le fond du panneau perce-t-il vraiment jusqu'au jeu ?

Pourquoi ce fichier existe
---------------------------

⛔ Le panneau se déclarait transparent depuis toujours, et son en-tête disait
que c'était « la seule raison d'être de cette page ». **Ça n'a jamais marché
sous Windows.** pywebview rend la vue web transparente sur le fond du
formulaire qui la porte, et ne touche jamais à ce fond : un gris très clair.

Photographié par-dessus le vrai jeu le 09/08/2026 : un aplat clair sous la
boîte du récap. C'est le « blanc très moche » signalé par Maxime — et c'est,
une fois de plus dans ce projet, une justification écrite et non implémentée
qui empêchait de voir le trou.

⚠️ Ce que ces tests NE font pas : ouvrir une fenêtre ni photographier quoi que
ce soit. La CI est sous Linux, sans .NET et sans jeu. Ils vérifient qu'on relit
au lieu de croire, qu'on ne repose pas ce qui est déjà posé, et que rien ne
lève. La preuve que ça perce est une **photo**, prise à la main avant et après.
"""

from __future__ import annotations

from typing import Any

import pytest

from butin import transparence


class FausseCouleur:
    """Ce que .NET rend pour une couleur : trois composantes lisibles."""

    def __init__(self, r: int, v: int, b: int) -> None:
        self.R, self.G, self.B = r, v, b


class FauxFormulaire:
    """Le formulaire .NET, réduit à ce que le module touche."""

    def __init__(self) -> None:
        self.TransparencyKey = FausseCouleur(0, 0, 0)
        self.BackColor = FausseCouleur(240, 240, 240)
        self.invocations = 0

    def Invoke(self, action: Any) -> None:
        self.invocations += 1
        action()


class FausseFenetre:
    def __init__(self, native: Any) -> None:
        self.native = native


@pytest.fixture
def dotnet(monkeypatch: pytest.MonkeyPatch) -> FauxFormulaire:
    """Un Windows avec .NET de laboratoire, quelle que soit la plateforme.

    ⚠️ `Action` et `Color` sont importés DANS la fonction, donc on remplace ce
    que la fonction obtiendra : `Color.FromArgb` rend notre fausse couleur, et
    `Action` rend l'appelable tel quel puisque le faux `Invoke` l'exécute.
    """
    import sys
    import types

    faux_system = types.ModuleType("System")
    faux_system.Action = lambda fonction: fonction  # type: ignore[attr-defined]
    faux_dessin = types.ModuleType("System.Drawing")
    faux_dessin.Color = types.SimpleNamespace(  # type: ignore[attr-defined]
        FromArgb=lambda r, v, b: FausseCouleur(r, v, b),
        # ⛔ `Color.Empty` est ce que .NET rend pour « aucune couleur-clé ». Ses
        # composantes valent zéro, donc il ne peut percer que du noir pur, que
        # la palette du panneau n'emploie nulle part.
        Empty=FausseCouleur(0, 0, 0),
    )
    monkeypatch.setitem(sys.modules, "System", faux_system)
    monkeypatch.setitem(sys.modules, "System.Drawing", faux_dessin)
    monkeypatch.setattr(transparence, "_est_windows", lambda: True)
    return FauxFormulaire()


class TestPoserLaCouleurCle:
    def test_le_fond_devient_la_couleur_qui_perce(self, dotnet: FauxFormulaire) -> None:
        fenetre = FausseFenetre(dotnet)

        assert transparence.rendre_le_fond_transparent(fenetre) is True
        assert (dotnet.TransparencyKey.R, dotnet.TransparencyKey.G, dotnet.TransparencyKey.B) == (
            transparence.CLE
        )

    def test_le_fond_du_formulaire_porte_LA_MEME_couleur(self, dotnet: FauxFormulaire) -> None:
        """⛔ Les deux vont ensemble. La clé ne perce que ce qui porte
        EXACTEMENT cette couleur : la poser sans repeindre le fond ne
        percerait rien du tout, et le panneau resterait gris clair."""
        transparence.rendre_le_fond_transparent(FausseFenetre(dotnet))

        assert (dotnet.BackColor.R, dotnet.BackColor.G, dotnet.BackColor.B) == transparence.CLE

    def test_deja_pose_ne_repose_pas(self, dotnet: FauxFormulaire) -> None:
        """⛔ Idempotent, et il FAUT que ça le reste : c'est cet appel-là qui
        efface `WS_EX_TRANSPARENT`, le style qui laisse passer la souris.
        Reposer la clé à chaque rafraîchissement rendrait le panneau capteur de
        souris par intermittence, ce que personne ne saurait diagnostiquer."""
        fenetre = FausseFenetre(dotnet)
        transparence.rendre_le_fond_transparent(fenetre)

        assert transparence.rendre_le_fond_transparent(fenetre) is True
        assert dotnet.invocations == 1

    def test_le_travail_passe_par_le_fil_graphique(self, dotnet: FauxFormulaire) -> None:
        """Ces propriétés appartiennent au fil de la couche graphique : y
        toucher depuis le fil de préparation est refusé par .NET."""
        transparence.rendre_le_fond_transparent(FausseFenetre(dotnet))

        assert dotnet.invocations == 1


class TestTransparentOuCliquable:
    """⛔ Régression trouvée par Maxime EN FARMANT, case décochée.

    « les boutons en direct ne fonctionnent plus et impossible de bouger la
    fenêtre ». Mesuré sur son panneau en session : `WS_EX_TRANSPARENT` était
    bien retiré, et pourtant les quatre points testés rendaient tous
    `BlackDesertWindowClass`, barre du haut comprise.

    La couleur-clé rend la fenêtre entière intraversable au clic — WebView2
    dessine dans une fenêtre fille, et la surface en couches que Windows teste
    ne porte que du magenta d'un bord à l'autre. Aucun réglage de souris ne peut
    le rattraper : les deux états s'excluent, et c'est la case qui tranche.
    """

    def test_le_fond_opaque_retire_la_cle(self, dotnet: FauxFormulaire) -> None:
        fenetre = FausseFenetre(dotnet)
        transparence.rendre_le_fond_transparent(fenetre)

        assert transparence.rendre_le_fond_opaque(fenetre) is True
        assert transparence.fond_transparent(fenetre) is False

    def test_le_fond_opaque_REPEINT_au_lieu_de_laisser_le_gris(
        self, dotnet: FauxFormulaire
    ) -> None:
        """⛔ Sans repeindre, on retombe sur le gris clair du formulaire : le
        « blanc très moche » d'où vient tout ce module. Retirer la clé sans
        poser de fond échangerait une gêne contre celle d'avant."""
        transparence.rendre_le_fond_opaque(FausseFenetre(dotnet))

        assert (dotnet.BackColor.R, dotnet.BackColor.G, dotnet.BackColor.B) == (transparence.OPAQUE)

    def test_les_deux_sens_sont_idempotents(self, dotnet: FauxFormulaire) -> None:
        """Le réglage est réappliqué à chaque enregistrement, y compris quand il
        n'a pas bougé : reposer la clé fait retravailler le formulaire pour
        rien, et c'est cet appel-là qui efface le style de souris."""
        fenetre = FausseFenetre(dotnet)

        transparence.rendre_le_fond_opaque(fenetre)
        transparence.rendre_le_fond_opaque(fenetre)
        transparence.rendre_le_fond_transparent(fenetre)
        transparence.rendre_le_fond_transparent(fenetre)

        assert dotnet.invocations == 2, "un aller-retour, deux écritures, pas quatre"

    def test_l_aller_retour_revient_a_l_etat_de_depart(self, dotnet: FauxFormulaire) -> None:
        fenetre = FausseFenetre(dotnet)

        transparence.rendre_le_fond_transparent(fenetre)
        transparence.rendre_le_fond_opaque(fenetre)

        assert transparence.rendre_le_fond_transparent(fenetre) is True
        assert transparence.fond_transparent(fenetre) is True


class TestOnRelitAuLieuDeCroire:
    def test_un_formulaire_qui_ignore_la_pose_rend_False(
        self, dotnet: FauxFormulaire, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le mode de défaillance qui compte : l'appel passe, rien ne change.
        Sans relecture, il serait indistinguable d'un succès."""

        class Sourd(FauxFormulaire):
            def Invoke(self, action: Any) -> None:
                self.invocations += 1  # accepte, et ne fait rien

        assert transparence.rendre_le_fond_transparent(FausseFenetre(Sourd())) is False


class TestCeQuiNeDoitJamaisLever:
    """Le fond du panneau est un confort. Aucun comptage n'en dépend."""

    def test_hors_windows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(transparence, "_est_windows", lambda: False)

        assert transparence.rendre_le_fond_transparent(FausseFenetre(FauxFormulaire())) is False

    def test_une_fenetre_pas_encore_creee(self, dotnet: FauxFormulaire) -> None:
        """`native` n'est renseigné qu'après la création par la couche
        graphique. Ce n'est pas une panne, c'est « pas encore »."""
        assert transparence.rendre_le_fond_transparent(FausseFenetre(None)) is False
        assert transparence.fond_transparent(FausseFenetre(None)) is None

    def test_un_formulaire_qui_refuse(self, dotnet: FauxFormulaire) -> None:
        class Refuse(FauxFormulaire):
            def Invoke(self, action: Any) -> None:
                raise RuntimeError("fil graphique indisponible")

        assert transparence.rendre_le_fond_transparent(FausseFenetre(Refuse())) is False

    def test_sans_dotnet_du_tout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys

        monkeypatch.setattr(transparence, "_est_windows", lambda: True)
        monkeypatch.setitem(sys.modules, "System", None)

        assert transparence.rendre_le_fond_transparent(FausseFenetre(FauxFormulaire())) is False
