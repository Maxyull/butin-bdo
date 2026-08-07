"""Tests de la mémoire des positions de fenêtres.

⭐ Ce que ça sert : le panneau en surimpression est placé à la main, par-dessus
le jeu, à l'endroit précis où il ne gêne pas. Une mise à jour le rouvrait au
centre, donc il fallait le replacer à chaque version.

⛔ Deux invariants portent tout ce module, et ils tirent chacun dans un sens
opposé :

1. la position doit survivre à une fermeture **de force**, parce que c'est
   exactement comme ça que l'installeur ferme Butin ;
2. une position hors écran ne doit **jamais** être restaurée, parce qu'une
   fenêtre invisible ressemble à un logiciel qui ne démarre plus.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from butin import fenetres
from butin.fenetres import (
    Position,
    charger,
    enregistrer,
    position_a_restaurer,
    position_valable,
)

#: Un écran unique, comme celui de Maxime : 2560x1440 en haut à gauche.
ECRAN = [(0, 0, 2560, 1440)]

#: Deux écrans, le second à droite. Le cas qui casse tout quand on le débranche.
DEUX_ECRANS = [(0, 0, 2560, 1440), (2560, 0, 1920, 1080)]


class TestUnePositionHorsEcranNEstJamaisRestauree:
    def test_le_second_ecran_debranche_ne_rend_pas_la_fenetre_invisible(
        self, tmp_path: Path
    ) -> None:
        """⛔ Le test qui porte le garde-fou.

        Le panneau était sur le second écran. Le lendemain il est débranché.
        Restaurer aveuglément ouvrirait la fenêtre à x=3000, c'est-à-dire nulle
        part — et de l'extérieur, ça ressemble exactement à un logiciel qui ne
        démarre plus.
        """
        sur_le_second = Position(3000, 400)
        assert position_valable(sur_le_second, DEUX_ECRANS) is True
        assert position_valable(sur_le_second, ECRAN) is False

    def test_une_position_negative_hors_champ_est_refusee(self) -> None:
        assert position_valable(Position(-5000, -5000), ECRAN) is False

    def test_une_position_normale_est_acceptee(self) -> None:
        assert position_valable(Position(100, 100), ECRAN) is True

    def test_sans_ecran_connu_on_ne_restaure_RIEN(self) -> None:
        """⛔ « On ne sait pas » n'est pas « c'est bon ».

        Si la liste des écrans est vide, on ignore où la fenêtre atterrirait.
        Le défaut est toujours visible, la position d'hier peut ne plus l'être.
        Parier ici, c'est parier sur l'invisible.
        """
        assert position_valable(Position(100, 100), []) is False

    def test_c_est_la_POIGNEE_qui_doit_etre_visible(self) -> None:
        """Un coin qu'on peut attraper suffit à récupérer la fenêtre.

        Exiger la fenêtre entière refuserait une position à peine dépassante,
        alors qu'elle reste parfaitement utilisable — et ferait perdre le
        placement pour rien.
        """
        # Coin haut gauche juste hors écran, mais la poignée retombe dedans.
        assert position_valable(Position(-10, -5), ECRAN) is True
        # Trop loin : même la poignée est dehors.
        assert position_valable(Position(-200, -200), ECRAN) is False


class TestElleSurvitAUneFermetureDeForce:
    def test_enregistrer_ecrit_tout_de_suite(self, tmp_path: Path) -> None:
        """⛔ Rien n'est gardé en mémoire pour « plus tard ».

        L'installeur ferme Butin par le Gestionnaire de redémarrage de Windows :
        aucun code de fermeture propre n'est garanti. Une position qui attend la
        fermeture pour être écrite est une position perdue au seul moment où
        elle compte.
        """
        assert enregistrer("panneau", Position(120, 340), tmp_path) is True
        # Relu depuis le disque, sans passer par l'objet qui vient d'écrire.
        assert charger(tmp_path)["panneau"] == Position(120, 340)

    def test_les_deux_fenetres_cohabitent(self, tmp_path: Path) -> None:
        """⛔ Régression : écrire l'une ne doit pas effacer l'autre.

        Elles écrivent dans le même fichier, à quelques secondes d'écart.
        """
        enregistrer("principale", Position(10, 20), tmp_path)
        enregistrer("panneau", Position(30, 40), tmp_path)
        positions = charger(tmp_path)
        assert positions["principale"] == Position(10, 20)
        assert positions["panneau"] == Position(30, 40)

    def test_reenregistrer_remplace(self, tmp_path: Path) -> None:
        enregistrer("panneau", Position(1, 1), tmp_path)
        enregistrer("panneau", Position(2, 2), tmp_path)
        assert charger(tmp_path)["panneau"] == Position(2, 2)


class TestElleNeCasseJamaisRien:
    def test_un_fichier_absent_rend_un_dictionnaire_vide(self, tmp_path: Path) -> None:
        """Les fenêtres s'ouvrent alors où elles s'ouvraient avant ce module."""
        assert charger(tmp_path / "nulle-part") == {}

    def test_un_fichier_illisible_ne_leve_pas(self, tmp_path: Path) -> None:
        (tmp_path / fenetres.FICHIER).write_text("{ ceci n'est pas du JSON", encoding="utf-8")
        assert charger(tmp_path) == {}

    def test_une_entree_abimee_n_emporte_pas_les_autres(self, tmp_path: Path) -> None:
        """⛔ Perdre le panneau parce que la principale est cassée serait gratuit."""
        (tmp_path / fenetres.FICHIER).write_text(
            '{"principale": {"x": "non"}, "panneau": {"x": 5, "y": 6}}', encoding="utf-8"
        )
        positions = charger(tmp_path)
        assert "principale" not in positions
        assert positions["panneau"] == Position(5, 6)

    def test_un_json_qui_n_est_pas_un_objet_ne_leve_pas(self, tmp_path: Path) -> None:
        (tmp_path / fenetres.FICHIER).write_text("[1, 2, 3]", encoding="utf-8")
        assert charger(tmp_path) == {}

    def test_un_dossier_impossible_a_ecrire_rend_faux(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def refuse(*args: object, **kwargs: object) -> None:
            raise OSError(13, "accès refusé")

        monkeypatch.setattr(Path, "write_text", refuse)
        assert enregistrer("panneau", Position(1, 2), tmp_path) is False


class TestLeChoixFinal:
    def test_position_a_restaurer_refuse_ce_qui_est_hors_ecran(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        enregistrer("panneau", Position(9000, 9000), tmp_path)
        monkeypatch.setattr(fenetres, "ecrans_du_bureau", lambda: ECRAN)
        assert position_a_restaurer("panneau", tmp_path) is None

    def test_position_a_restaurer_rend_ce_qui_est_visible(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        enregistrer("panneau", Position(300, 200), tmp_path)
        monkeypatch.setattr(fenetres, "ecrans_du_bureau", lambda: ECRAN)
        assert position_a_restaurer("panneau", tmp_path) == Position(300, 200)

    def test_une_fenetre_jamais_placee_rend_None(self, tmp_path: Path) -> None:
        """`None` veut dire « ouvre-la où tu veux », toujours acceptable."""
        assert position_a_restaurer("jamais-vue", tmp_path) is None


class TestLeFilNeSurvitPasALaFenetre:
    def test_fermer_le_panneau_arrete_le_suivi(self) -> None:
        """⛔ Un fil de fond qui survit à ce qu'il observe est un défaut que ce
        projet a déjà payé une fois (#37).

        Sans ça, il lirait une fenêtre détruite et écrirait des positions dans
        le vide pendant trois secondes après la fermeture.
        """
        import threading

        from butin.app import Overlay

        panneau = Overlay("http://127.0.0.1:0")
        arret = threading.Event()
        panneau._arret_suivi = arret
        panneau._window = None

        panneau.close()
        assert arret.is_set(), "le fil de suivi tourne encore après la fermeture"
