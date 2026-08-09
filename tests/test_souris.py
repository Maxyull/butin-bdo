"""Le panneau laisse-t-il vraiment passer la souris ?

Pourquoi ce fichier existe
---------------------------

Signalé par Maxime le 09/08/2026 : « le panneau qui se met sur l'écran de jeu
interfère avec la souris, je passe dessus et ça affiche la souris ». Black
Desert cache le curseur pendant qu'on joue, et une fenêtre posée par-dessus le
récupère au premier survol.

⚠️ Ce que ces tests NE font pas : ouvrir une vraie fenêtre. L'intégration
continue tourne sous Linux, sans Windows, sans couche graphique et sans jeu.
Ce qui est vérifié ici, c'est le **calcul du style** et le fait que le module
relise ce qu'il a posé — pas que Windows obéisse.

⭐ Que Windows obéisse a été mesuré à la main le 09/08/2026, sur cette machine
et sur le vrai jeu, AVANT d'écrire le module : `WindowFromPoint` au centre du
panneau rendait `Chrome_RenderWidgetHostHWND` (le panneau) avant la pose, et
`BlackDesertWindowClass` après. C'est cette mesure qui fait foi, pas ces tests.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest

from butin import souris


class FauxUser32:
    """Ce que Windows expose, réduit aux trois appels utilisés.

    Le style est gardé dans l'objet : c'est ce qui permet de vérifier qu'on
    relit après avoir écrit, au lieu de croire ce qu'on vient de poser.
    """

    def __init__(self, style: int = 0, *, sourd: bool = False) -> None:
        self.style = style
        self.sourd = sourd
        """Vrai pour un système qui accepte l'appel et ne change rien. C'est le
        mode de défaillance qui compte : indistinguable d'un succès si on ne
        relit pas."""
        self.poses: list[int] = []

    def FindWindowW(self, classe: object, titre: object) -> int:
        return 4242 if titre == "Butin — en direct" else 0

    def GetWindowLongW(self, fenetre: int, index: int) -> int:
        return self.style

    def SetWindowLongW(self, fenetre: int, index: int, valeur: int) -> int:
        self.poses.append(valeur)
        if not self.sourd:
            self.style = valeur
        return 1


@pytest.fixture
def windows(monkeypatch: pytest.MonkeyPatch) -> FauxUser32:
    """Un Windows de laboratoire, quelle que soit la plateforme du test."""
    faux = FauxUser32()
    monkeypatch.setattr(souris, "_est_windows", lambda: True)
    monkeypatch.setattr(souris, "_user32", lambda: faux)
    return faux


class TestPoserEtRetirer:
    def test_poser_fait_traverser_la_souris(self, windows: FauxUser32) -> None:
        assert souris.laisser_passer_la_souris(4242, True) is True
        assert windows.style & souris.WS_EX_TRANSPARENT
        assert souris.traverse_la_souris(4242) is True

    def test_retirer_rend_le_panneau_cliquable(self, windows: FauxUser32) -> None:
        souris.laisser_passer_la_souris(4242, True)

        assert souris.laisser_passer_la_souris(4242, False) is True
        assert souris.traverse_la_souris(4242) is False

    def test_retirer_GARDE_le_style_qui_porte_la_transparence(self, windows: FauxUser32) -> None:
        """⛔ Régression : `WS_EX_LAYERED` ne doit JAMAIS être retiré.

        Il est posé avec `WS_EX_TRANSPARENT`, mais il porte **aussi** la
        couleur-clé qui rend le fond du panneau transparent par-dessus le jeu.
        Le retirer en repassant en mode cliquable rendrait le panneau opaque du
        même coup — un aplat par-dessus le jeu — et personne ne ferait le lien
        avec une case à cocher qui parle de souris.
        """
        souris.laisser_passer_la_souris(4242, True)
        souris.laisser_passer_la_souris(4242, False)

        assert windows.style & souris.WS_EX_LAYERED

    def test_le_reste_du_style_n_est_pas_efface(self, windows: FauxUser32) -> None:
        """La fenêtre est déjà sans cadre et toujours au-dessus : écraser son
        style au lieu de le compléter ferait passer le panneau derrière le jeu,
        c'est-à-dire disparaître."""
        windows.style = 0x00000008  # WS_EX_TOPMOST

        souris.laisser_passer_la_souris(4242, True)

        assert windows.style & 0x00000008

    def test_deux_poses_de_suite_n_ecrivent_qu_une_fois(self, windows: FauxUser32) -> None:
        """Rien à changer, rien à écrire. Le réglage est réappliqué à chaque
        enregistrement des réglages, y compris quand il n'a pas bougé."""
        souris.laisser_passer_la_souris(4242, True)
        souris.laisser_passer_la_souris(4242, True)

        assert len(windows.poses) == 1


class TestOnRelitAuLieuDeCroire:
    """⛔ « On a demandé » et « c'est appliqué » sont deux choses différentes.

    Ce projet a déjà payé la confusion deux fois : une protection de branche
    GitHub qui affichait ses refus et laissait passer, et une priorité de fil
    qui ne s'appliquait jamais faute d'`argtypes`. Les deux se lisaient comme
    des succès.
    """

    def test_un_systeme_qui_accepte_sans_rien_faire_rend_False(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sourd = FauxUser32(sourd=True)
        monkeypatch.setattr(souris, "_est_windows", lambda: True)
        monkeypatch.setattr(souris, "_user32", lambda: sourd)

        assert souris.laisser_passer_la_souris(4242, True) is False
        assert sourd.poses, "l'appel a bien été tenté, il n'a simplement rien changé"


class TestCeQuiNeDoitJamaisLever:
    """Un confort ne doit pas pouvoir interrompre une session de farm."""

    def test_hors_windows_on_ne_fait_rien(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(souris, "_est_windows", lambda: False)

        assert souris.laisser_passer_la_souris(4242, True) is False
        assert souris.traverse_la_souris(4242) is None
        assert souris.fenetre_par_titre("Butin — en direct") is None

    def test_une_fenetre_absente_ne_leve_pas(self, windows: FauxUser32) -> None:
        assert souris.laisser_passer_la_souris(0, True) is False
        assert souris.traverse_la_souris(0) is None
        assert souris.fenetre_par_titre("une autre fenêtre") is None

    def test_un_systeme_qui_refuse_ne_leve_pas(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Refuse:
            def GetWindowLongW(self, *args: Any) -> int:
                raise OSError("appel refusé")

            def SetWindowLongW(self, *args: Any) -> int:
                raise OSError("appel refusé")

            def FindWindowW(self, *args: Any) -> int:
                raise OSError("appel refusé")

        monkeypatch.setattr(souris, "_est_windows", lambda: True)
        monkeypatch.setattr(souris, "_user32", lambda: Refuse())

        assert souris.laisser_passer_la_souris(4242, True) is False
        assert souris.traverse_la_souris(4242) is None
        assert souris.fenetre_par_titre("Butin — en direct") is None


class TestLaFenetreSeTrouveParSonTitre:
    def test_le_titre_du_panneau(self, windows: FauxUser32) -> None:
        assert souris.fenetre_par_titre("Butin — en direct") == 4242

    def test_le_titre_est_celui_que_l_application_pose(self) -> None:
        """⛔ Deux endroits, un seul fait. Changer le titre du panneau sans
        changer celui qu'on cherche laisserait le réglage sans effet, en
        silence : la fenêtre resterait introuvable et la souris captée."""
        from butin import app

        assert app.OVERLAY_TITLE == "Butin — en direct"


@pytest.mark.skipif(sys.platform != "win32", reason="styles de fenêtre Windows")
class TestSurLaVraieMachine:
    """Le seul test qui touche au vrai Windows, et il ne touche à aucune fenêtre.

    Il vérifie que les signatures sont déclarables et qu'une poignée invalide
    ne fait pas tomber le programme — ce qui est exactement ce qui arriverait
    en production si `argtypes` manquait sur un système 64 bits.
    """

    def test_les_signatures_se_declarent(self) -> None:
        assert souris._user32() is not None

    def test_une_poignee_invalide_ne_leve_pas(self) -> None:
        assert souris.laisser_passer_la_souris(1, True) is False
