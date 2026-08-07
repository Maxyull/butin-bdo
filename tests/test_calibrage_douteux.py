"""Tests de l'avertissement sur un calibrage douteux.

⭐ Tous les chiffres viennent de VRAIES sessions de Maxime, relevées dans les
journaux de diagnostic du 07/08/2026. Aucun n'est inventé, et c'est essentiel
ici : le seuil qu'on garde a été posé à partir de ces mesures, donc le tester
avec des valeurs imaginaires reviendrait à vérifier une décision contre
elle-même.

Le cas fondateur, session 11 : Maxime recalibre en cours de session et remplace
un calibrage qui marchait par un qui ne lit plus rien.

    avant : 475x493, pas 21,7 px, 22 rangées, force 0,53 → 19 lectures sur 19
            contiennent du texte
    après : 415x215, pas 38,0 px,  5 rangées, force 0,16 →  9 lectures sur 38

Ses objets n'étaient pas mal comptés : ils n'étaient **jamais lus**. Et rien à
l'écran ne le disait.
"""

from __future__ import annotations

import pytest

from butin.capture.calibrate import FORCE_FIABLE, MIN_ROWS, MIN_STRENGTH, Calibration
from butin.capture.screen import Region


def _calibrage(
    *, largeur: int, hauteur: int, pas: float, rangees: int, force: float
) -> Calibration:
    return Calibration(
        region=Region(left=12, top=778, width=largeur, height=hauteur),
        row_height_px=pas,
        ruler_left_ratio=0.0,
        ruler_right_ratio=1.0,
        rows=rangees,
        strength=force,
    )


#: Les deux calibrages réels de la session 11, dans l'ordre où ils ont eu lieu.
BON = _calibrage(largeur=475, hauteur=493, pas=21.7, rangees=22, force=0.53)
MAUVAIS = _calibrage(largeur=415, hauteur=215, pas=38.0, rangees=5, force=0.16)

#: Session 12, même journée, bon calibrage : 107 objets comptés pour 107 réels,
#: sur 22 rangées. C'est la preuve que le multi-ligne n'est pas le problème.
SESSION_12 = _calibrage(largeur=601, hauteur=505, pas=21.7, rangees=22, force=0.51)


class TestLeCasReel:
    def test_le_mauvais_calibrage_de_la_session_11_est_signale(self) -> None:
        """⛔ Le test qui justifie tout ce module.

        Ce calibrage a été accepté en silence, et Maxime a farmé pendant une
        minute sans que rien ne soit lu.
        """
        raisons = MAUVAIS.doutes()
        assert raisons, "le calibrage qui n'a rien lu passe toujours sans un mot"

    def test_le_bon_calibrage_de_la_session_11_ne_dit_rien(self) -> None:
        """⛔ L'autre moitié, et la plus facile à oublier.

        Un avertissement qui se déclenche aussi sur les bons calibrages est un
        avertissement que les gens apprennent à ignorer, donc pire que rien.
        """
        assert BON.doutes() == []

    def test_la_session_12_ne_dit_rien_non_plus(self) -> None:
        """107 comptés pour 107 réels, sur 22 rangées : rien à signaler."""
        assert SESSION_12.doutes() == []

    def test_remplacer_un_bon_calibrage_par_un_mauvais_est_signale_EXPLICITEMENT(self) -> None:
        """⭐ Ce que seule la comparaison peut dire.

        Le calibrage précédent est sur le disque au moment du recalibrage : ne
        pas s'en servir alors qu'on l'a sous la main serait absurde. C'est
        exactement le geste qui a coûté la session.
        """
        raisons = MAUVAIS.doutes(BON)
        assert any("précédent était nettement meilleur" in r for r in raisons)
        assert any("plus courte qu'avant" in r for r in raisons)

    def test_remplacer_un_bon_par_un_bon_ne_dit_rien(self) -> None:
        """Recalibrer sans rien casser doit rester silencieux."""
        assert SESSION_12.doutes(BON) == []


class TestChaqueCritere:
    def test_une_force_sous_le_seuil_fiable_est_signalee(self) -> None:
        """La zone grise entre `MIN_STRENGTH` et `FORCE_FIABLE`.

        Elle n'est pas inventée : la docstring de `MIN_STRENGTH` mesure
        « 0,26 à 0,60 » sur un chat lisible et « 0,06 au plus » sur un chat
        masqué. Tout ce qui tombe entre 0,15 et 0,26 est accepté sans
        ressembler à quoi que ce soit d'observé comme bon.
        """
        faible = _calibrage(largeur=400, hauteur=400, pas=21.7, rangees=15, force=0.20)
        assert any("faiblement" in r for r in faible.doutes())

    def test_le_nombre_minimal_de_rangees_est_signale(self) -> None:
        """`MIN_ROWS` pile n'est pas « acceptable », c'est « tout juste »."""
        court = _calibrage(largeur=400, hauteur=200, pas=21.7, rangees=MIN_ROWS, force=0.50)
        assert any("minimum absolu" in r for r in court.doutes())

    def test_un_pas_proche_du_maximum_est_signale(self) -> None:
        """38 px là où le bon calibrage en trouvait 21,7.

        Un pas proche du plafond cherché veut souvent dire qu'on s'est accroché
        à un multiple du vrai pas, donc qu'on ne voit qu'une ligne sur deux.
        """
        large = _calibrage(largeur=400, hauteur=400, pas=39.0, rangees=15, force=0.50)
        assert any("une ligne sur deux" in r for r in large.doutes())

    def test_un_calibrage_franchement_bon_ne_declenche_rien(self) -> None:
        assert _calibrage(largeur=600, hauteur=500, pas=21.7, rangees=22, force=0.60).doutes() == []


class TestIlNeRefuseJamais:
    def test_les_doutes_ne_levent_pas(self) -> None:
        """⛔ Avertir, jamais refuser.

        Refuser à 0,25 jetterait des calibrages peut-être bons sur une
        résolution jamais mesurée — et le calibrage n'a été vérifié que sur un
        seul écran. Se tromper dans ce sens-là empêcherait de farmer du tout,
        ce qui est pire que de farmer en étant prévenu.
        """
        assert isinstance(MAUVAIS.doutes(), list)

    def test_les_seuils_gardent_leur_ordre(self) -> None:
        """Régression : `FORCE_FIABLE` doit rester AU-DESSUS de `MIN_STRENGTH`.

        Les inverser rendrait l'avertissement impossible à déclencher, en
        silence : tout ce qui passe le refus passerait aussi le doute.
        """
        assert MIN_STRENGTH < FORCE_FIABLE, "l'avertissement ne peut plus se déclencher"


class TestPlusieursDoutesALaFois:
    def test_le_calibrage_reel_en_cumule_trois(self) -> None:
        """⭐ Ce que le contrôle un-par-un ne pouvait pas voir.

        Le calibrage de la session 11 passait CHAQUE critère de justesse :
        force juste au-dessus du refus, rangées au minimum exact, pas près du
        plafond. Pris séparément, chacun était « acceptable ». Ensemble,
        c'était du bruit — et c'est la combinaison qui le dit.
        """
        raisons = MAUVAIS.doutes()
        assert len(raisons) >= 3, f"un seul critère vu au lieu de trois : {raisons}"


@pytest.mark.parametrize("force", [0.15, 0.16, 0.20, 0.25])
def test_toute_la_zone_grise_est_couverte(force: float) -> None:
    calibrage = _calibrage(largeur=400, hauteur=400, pas=21.7, rangees=15, force=force)
    assert calibrage.doutes(), f"force {force} passe sans un mot"
