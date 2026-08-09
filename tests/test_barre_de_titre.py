"""La barre de titre passe-t-elle en sombre ?

Pourquoi ce fichier existe
---------------------------

Signalé par Maxime le 09/08/2026, capture à l'appui : « bar en blan aussi bien
moche ». Windows dessine la barre de titre lui-même, et rien de la feuille de
style de la page ne l'atteint — `color-scheme: dark` non plus, il ne vaut que
pour ce que le moteur web dessine.

⭐ Mesuré à la main AVANT d'écrire le module, sur une vraie fenêtre de cette
machine : luminance moyenne de la bande de titre photographiée à l'écran,
**245,2 avant** et **11,0 après**. C'est cette photo qui fait foi.

⛔ Ce que ces tests ne peuvent PAS faire, et il faut le dire
------------------------------------------------------------

Se relire. Cet attribut n'a pas de lecture fiable : `DwmGetWindowAttribute` le
refuse. Contrairement à `souris` et `transparence`, on ne peut donc pas vérifier
qu'il a pris — seulement que le système a répondu `S_OK`. Ces tests vérifient
donc l'enchaînement des appels, le repli sur l'ancien numéro d'attribut, et le
fait que rien ne lève.
"""

from __future__ import annotations

from typing import Any

import pytest

from butin import barre_de_titre

E_INVALIDARG = -2147024809


class FauxDwm:
    """Le service de composition, réduit à l'appel utilisé.

    `accepte` dit quels numéros d'attribut ce Windows-là connaît : c'est
    exactement ce qui distingue un Windows récent d'un ancien.
    """

    def __init__(self, accepte: tuple[int, ...] = (20,)) -> None:
        self.accepte = accepte
        self.demandes: list[int] = []

    def DwmSetWindowAttribute(self, fenetre: Any, attribut: int, valeur: Any, taille: int) -> int:
        self.demandes.append(attribut)
        return barre_de_titre.S_OK if attribut in self.accepte else E_INVALIDARG


class FauxUser32:
    def __init__(self) -> None:
        self.redessins = 0

    def SetWindowPos(self, *args: Any) -> int:
        self.redessins += 1
        return 1


@pytest.fixture
def windows(monkeypatch: pytest.MonkeyPatch) -> tuple[FauxDwm, FauxUser32]:
    dwm, user32 = FauxDwm(), FauxUser32()
    monkeypatch.setattr(barre_de_titre, "_est_windows", lambda: True)
    monkeypatch.setattr(barre_de_titre, "_api", lambda: (dwm, user32))
    return dwm, user32


class TestPoserLeModeSombre:
    def test_l_attribut_recent_est_essaye_en_PREMIER(
        self, windows: tuple[FauxDwm, FauxUser32]
    ) -> None:
        """Il vaut 20 depuis Windows 10 20H1, et c'est ce que tout le monde a.
        L'ancien numéro est un repli, pas un premier choix."""
        dwm, _ = windows

        assert barre_de_titre.rendre_sombre(4242) is True
        assert dwm.demandes == [20]

    def test_un_windows_ancien_recoit_l_ancien_numero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """⚠️ 19 avant 20H1, où l'attribut n'était même pas documenté. Un refus
        sur 20 n'est donc pas une panne : c'est la réponse d'un système qui ne
        connaît pas ce numéro-là."""
        dwm, user32 = FauxDwm(accepte=(19,)), FauxUser32()
        monkeypatch.setattr(barre_de_titre, "_est_windows", lambda: True)
        monkeypatch.setattr(barre_de_titre, "_api", lambda: (dwm, user32))

        assert barre_de_titre.rendre_sombre(4242) is True
        assert dwm.demandes == [20, 19]

    def test_un_windows_qui_ne_connait_ni_l_un_ni_l_autre(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dwm, user32 = FauxDwm(accepte=()), FauxUser32()
        monkeypatch.setattr(barre_de_titre, "_est_windows", lambda: True)
        monkeypatch.setattr(barre_de_titre, "_api", lambda: (dwm, user32))

        assert barre_de_titre.rendre_sombre(4242) is False
        assert dwm.demandes == [20, 19]
        assert user32.redessins == 0, "rien à redessiner si rien n'a été posé"

    def test_la_fenetre_est_REDESSINEE(self, windows: tuple[FauxDwm, FauxUser32]) -> None:
        """⛔ Trouvé en mesurant, pas en lisant la documentation : poser
        l'attribut ne repeint pas une fenêtre déjà affichée. Sans ce redessin,
        la barre reste claire jusqu'au premier déplacement — c'est-à-dire que
        le correctif marcherait en test et pas à l'écran."""
        _, user32 = windows

        barre_de_titre.rendre_sombre(4242)

        assert user32.redessins == 1


class TestCeQuiNeDoitJamaisLever:
    def test_hors_windows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(barre_de_titre, "_est_windows", lambda: False)

        assert barre_de_titre.rendre_sombre(4242) is False

    def test_une_fenetre_absente(self, windows: tuple[FauxDwm, FauxUser32]) -> None:
        assert barre_de_titre.rendre_sombre(0) is False

    def test_un_systeme_qui_refuse(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Refuse:
            def DwmSetWindowAttribute(self, *args: Any) -> int:
                raise OSError("service de composition indisponible")

        monkeypatch.setattr(barre_de_titre, "_est_windows", lambda: True)
        monkeypatch.setattr(barre_de_titre, "_api", lambda: (Refuse(), FauxUser32()))

        assert barre_de_titre.rendre_sombre(4242) is False

    def test_un_redessin_qui_echoue_ne_perd_pas_le_reglage(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L'attribut EST posé : rendre `False` parce que le repeint a raté
        ferait réessayer une pose déjà faite, et surtout ferait passer un
        succès pour un échec."""

        class RefuseLeRedessin:
            def SetWindowPos(self, *args: Any) -> int:
                raise OSError("fenêtre occupée")

        monkeypatch.setattr(barre_de_titre, "_est_windows", lambda: True)
        monkeypatch.setattr(barre_de_titre, "_api", lambda: (FauxDwm(), RefuseLeRedessin()))

        assert barre_de_titre.rendre_sombre(4242) is True


class TestSurLaVraieMachine:
    """Le seul test qui touche au vrai Windows, et il ne touche à aucune fenêtre."""

    def test_les_signatures_se_declarent(self) -> None:
        import sys

        if sys.platform != "win32":
            pytest.skip("interface de composition Windows")
        assert barre_de_titre._api() is not None

    def test_une_poignee_invalide_ne_leve_pas(self) -> None:
        import sys

        if sys.platform != "win32":
            pytest.skip("interface de composition Windows")
        assert barre_de_titre.rendre_sombre(1) is False
