"""Tests des réglages retenus d'un lancement à l'autre.

Ce que ces tests protègent : **le chiffre affiché**. Le taux de taxe est le
seul réglage qui multiplie tout le reste. Quand il vivait en mémoire, il
revenait au taux sans bonus à chaque lancement, ce qui sous-estimait de 23 % le
butin de quelqu'un qui a un abonnement, sans rien montrer à l'écran qui
distingue ça d'un farm pauvre.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from butin import paths
from butin.market import Region
from butin.store import Settings, TaxProfile

# Le profil réel de Maxime, relevé le 05/08/2026 : abonnement oui, anneau de
# marchand non, renommée familiale 11952. Le calculateur de garmoth donne
# 85,47 % pour cette combinaison.
PROFIL_REEL = TaxProfile(value_pack=True, merchant_ring=False, family_fame=11952)


class TestDefauts:
    def test_sans_fichier_le_taux_est_celui_sans_bonus(self) -> None:
        """Le défaut sous-estime, et c'est le bon sens de l'erreur.

        Un chiffre un peu bas se corrige en cochant une case ; un chiffre trop
        haut fait croire à un gain qui n'arrivera jamais.
        """
        reglages = Settings.load()

        assert reglages.market_rate == pytest.approx(0.65)
        assert reglages.language == "fr"
        assert reglages.region is Region.EU

    def test_un_fichier_absent_n_est_pas_une_erreur(self, tmp_path: Path) -> None:
        """C'est l'état normal au premier lancement."""
        assert Settings.load(tmp_path / "jamais-ecrit.json") == Settings()


class TestDisque:
    def test_aller_et_retour(self, tmp_path: Path) -> None:
        cible = tmp_path / "reglages.json"
        Settings(language="us", region=Region.NA, tax=PROFIL_REEL).save(cible)

        relu = Settings.load(cible)

        assert relu.language == "us"
        assert relu.region is Region.NA
        assert relu.tax == PROFIL_REEL
        assert relu.market_rate == pytest.approx(0.8547, abs=0.0001)

    def test_le_taux_survit_au_relancement(self) -> None:
        """Régression : le réglage n'existait que dans la mémoire du serveur.

        Le cas réel : Maxime coche « abonnement », le total passe de 0,65 à
        0,845 fois le prix affiché, il ferme l'application, il la rouvre — et
        elle est revenue à 0,65 sans le dire. L'erreur est **systématique**,
        elle ne se compense pas d'une session à l'autre, et à l'écran elle
        ressemble à un farm pauvre.
        """
        Settings(tax=PROFIL_REEL).save()

        assert Settings.load().market_rate == pytest.approx(0.8547, abs=0.0001)
        assert paths.settings_path().exists()

    def test_le_fichier_est_lisible_a_la_main(self, tmp_path: Path) -> None:
        """C'est le fichier qu'on demandera de coller dans un rapport de bogue
        quand quelqu'un trouvera son silver par heure trop bas."""
        cible = tmp_path / "reglages.json"
        Settings(tax=PROFIL_REEL).save(cible)

        contenu = json.loads(cible.read_text(encoding="utf-8"))

        assert contenu["tax"] == {
            "value_pack": True,
            "merchant_ring": False,
            "family_fame": 11952,
        }

    def test_un_fichier_illisible_rend_les_defauts_sans_lever(self, tmp_path: Path) -> None:
        """Le contraire du calibrage, et pour une raison mesurable.

        Une mauvaise zone de capture ne se voit pas : elle donne un journal
        vide, alors mieux vaut s'arrêter. Un retour au taux par défaut, lui, est
        affiché en permanence à côté des cases à cocher. Refuser de démarrer
        retirerait à l'utilisateur le seul écran d'où il peut réparer.
        """
        cible = tmp_path / "reglages.json"
        cible.write_text("{ceci n'est pas du JSON", encoding="utf-8")

        assert Settings.load(cible) == Settings()

    def test_un_fichier_qui_n_est_pas_un_objet(self, tmp_path: Path) -> None:
        cible = tmp_path / "reglages.json"
        cible.write_text("[1, 2, 3]", encoding="utf-8")

        assert Settings.load(cible) == Settings()


class TestValidation:
    def test_une_langue_inconnue_ne_change_rien(self) -> None:
        assert Settings().updated(language="klingon").language == "fr"

    def test_une_region_inconnue_ne_change_rien(self) -> None:
        assert Settings().updated(region="lune").region is Region.EU

    def test_une_renommee_negative_est_refusee(self) -> None:
        assert Settings().updated(family_fame=-1).tax.family_fame == 0

    def test_une_renommee_non_entiere_est_refusee(self) -> None:
        assert Settings().updated(family_fame="onze mille").tax.family_fame == 0

    def test_une_case_a_cocher_ne_devient_pas_une_renommee(self) -> None:
        """Régression : en Python, `isinstance(True, int)` est vrai.

        Sans le test du booléen d'abord, un `True` envoyé dans le champ de
        renommée passait pour l'entier 1. Ça ne planterait pas et ça ne
        changerait pas le taux, puisque le premier palier est à 1000 : le
        réglage serait simplement faux en silence, et le resterait.
        """
        assert Settings().updated(family_fame=True).tax.family_fame == 0

    def test_une_case_a_cocher_veut_un_booleen(self) -> None:
        assert Settings().updated(value_pack=1).tax.value_pack is False

    def test_un_champ_invalide_n_entraine_pas_les_autres(self) -> None:
        """Régression : le fichier s'édite à la main.

        Une renommée saisie en toutes lettres ne doit pas faire perdre
        l'abonnement au passage. Rejeter le lot entier pour un champ ferait
        perdre un réglage juste à cause d'un réglage faux.
        """
        reglages = Settings().updated(value_pack=True, family_fame="beaucoup")

        assert reglages.tax.value_pack is True
        assert reglages.tax.family_fame == 0

    def test_ne_rien_envoyer_ne_change_rien(self) -> None:
        """La page envoie une case à la fois : les autres doivent tenir."""
        depart = Settings(language="us", region=Region.NA, tax=PROFIL_REEL)

        assert depart.updated() == depart

    def test_cocher_une_case_garde_le_reste(self) -> None:
        reglages = Settings(tax=PROFIL_REEL).updated(merchant_ring=True)

        assert reglages.tax.value_pack is True
        assert reglages.tax.family_fame == 11952
        assert reglages.tax.merchant_ring is True
