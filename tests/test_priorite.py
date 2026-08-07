"""Tests de l'abaissement de priorité du fil de capture.

⛔ Le piège que ces tests existent pour empêcher : une fonction qui **échoue en
silence** et qu'on croit active. La première version de `priorite.py` ne
déclarait pas les signatures ctypes, donc `GetCurrentThread` rendait un
pseudo-handle tronqué à 32 bits et `SetThreadPriority` refusait. Elle rendait
`False`, la priorité ne changeait jamais, et le module aurait été livré en ne
faisant **rien** — le tout avec une docstring affirmant le contraire.

⭐ Ce qui a sauvé la mise : avoir écrit `priorite_du_fil_courant()` pour
**relire** ce qu'on venait de poser. « On a demandé » et « ça a été appliqué »
sont deux choses différentes, et c'est exactement la confusion qui avait rendu
la protection de branche GitHub inutile pendant une journée.
"""

from __future__ import annotations

import sys
import threading

import pytest

from butin.capture import priorite
from butin.capture.priorite import (
    BELOW_NORMAL,
    PRIORITE_ERREUR,
    abaisser_le_fil_courant,
    priorite_du_fil_courant,
)

windows_seulement = pytest.mark.skipif(
    sys.platform != "win32", reason="l'API de priorité est propre à Windows"
)


class TestElleEstVraimentAppliquee:
    @windows_seulement
    def test_la_priorite_relue_vaut_bien_celle_demandee(self) -> None:
        """⛔ Le test qui aurait attrapé le no-op.

        Il ne vérifie pas que l'appel a rendu `True` : il **relit** la priorité
        du fil. Un `SetThreadPriority` qui échoue rend `False` mais un code de
        retour ignoré se lit comme un succès.

        Tourne dans un fil dédié pour ne pas laisser la suite de tests à une
        priorité abaissée.
        """
        vu: dict[str, object] = {}

        def dedans() -> None:
            vu["avant"] = priorite_du_fil_courant()
            vu["applique"] = abaisser_le_fil_courant()
            vu["apres"] = priorite_du_fil_courant()

        fil = threading.Thread(target=dedans)
        fil.start()
        fil.join(timeout=10)

        assert vu["applique"] is True, "le système a refusé l'abaissement"
        assert vu["apres"] == BELOW_NORMAL, f"priorité restée à {vu['apres']}"
        assert vu["avant"] != vu["apres"], "la priorité n'a pas bougé"

    @windows_seulement
    def test_elle_ne_touche_QUE_le_fil_qui_appelle(self) -> None:
        """⛔ Régression : abaisser le mauvais fil ralentirait l'interface.

        La priorité est une propriété du fil courant. La poser depuis `start()`
        la poserait sur le fil du serveur web, c'est-à-dire précisément celui
        qu'il ne faut pas ralentir. D'où l'appel dans `_tourner`, pas ailleurs.
        """
        avant = priorite_du_fil_courant()
        fil = threading.Thread(target=abaisser_le_fil_courant)
        fil.start()
        fil.join(timeout=10)
        assert priorite_du_fil_courant() == avant, "le fil principal a été abaissé"


class TestElleNeCasseJamaisRien:
    def test_elle_ne_leve_pas(self) -> None:
        """Même garantie que partout ailleurs : c'est un confort.

        Une machine où l'API refuse doit capturer exactement comme avant.
        Personne ne s'arrête parce qu'un réglage d'ordonnancement n'a pas pris.
        """
        assert isinstance(abaisser_le_fil_courant(), bool)

    def test_hors_windows_elle_rend_faux_sans_rien_tenter(self, monkeypatch) -> None:
        """Butin est distribué pour Windows ; la CI tourne sous Linux.

        On ne fabrique pas d'équivalent qui ne serait jamais exercé en vrai.
        """
        monkeypatch.setattr(priorite.sys, "platform", "linux")
        assert abaisser_le_fil_courant() is False
        assert priorite_du_fil_courant() is None

    @windows_seulement
    def test_un_code_d_erreur_n_est_pas_lu_comme_une_priorite(self) -> None:
        """⛔ `GetThreadPriority` rend `0x7FFFFFFF` quand il échoue.

        Sans ce test, un échec se lisait comme « priorité très haute », soit
        exactement l'inverse de la vérité.
        """
        assert PRIORITE_ERREUR == 0x7FFFFFFF
        assert priorite_du_fil_courant() != PRIORITE_ERREUR


class TestLeChoixDuNiveau:
    def test_c_est_UN_cran_sous_la_normale_et_pas_le_minimum(self) -> None:
        """⛔ Pas `LOWEST` (-2) ni `IDLE` (-15), et c'est réfléchi.

        Sur une machine chargée, un fil en priorité minimale peut ne plus être
        servi du tout. Un compteur qui s'arrête de compter est le mode de
        défaillance que ce projet refuse le plus : il ressemble à un farm
        pauvre, et rien à l'écran ne le distingue.
        """
        assert BELOW_NORMAL == -1


class TestLeFilDeCaptureLaDemande:
    def test_la_boucle_de_capture_abaisse_sa_priorite(self) -> None:
        """Régression de câblage : le module peut être parfait et non branché.

        « Un module testé et bien branché n'est pas un module testé » — c'est
        la leçon écrite en tête de `test_ui_rapport_et_maj.py`, et elle a déjà
        coûté deux défauts aujourd'hui.
        """
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1] / "src" / "butin" / "capture" / "worker.py"
        ).read_text(encoding="utf-8")
        debut = source.index("def _tourner")
        corps = source[debut : debut + 1200]
        assert "abaisser_le_fil_courant()" in corps, (
            "le fil de capture ne demande plus une priorité plus basse"
        )
