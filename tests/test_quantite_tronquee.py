"""Tests de la quantité perdue en fin de ligne.

⭐ Toutes les chaînes viennent du journal d'une VRAIE session de Maxime, le
07/08/2026 (`session-0013`). L'objet n'y tombe qu'en x2, x5, x7 et x10 — et le
compteur a pourtant crédité quatre fois « 1 » et une fois « 3 ». Sept unités
inventées sur un écart total de quinze contre son inventaire.

Le mécanisme, visible dans le texte brut :

    Vous avez obtenu :  [Pierre de puissance ... ancestrale] x2 (16:32)
    Vous avez obtenu :  [Pierre de puissance ... ancestrale]. (16:32)

La seconde est la MÊME ligne, sa quantité rabotée par la reconnaissance. Or le
jeu écrit 1 par une absence de quantité : la ligne tronquée devient un drop
unitaire parfaitement crédible, différent de son original, donc comptée comme
nouvelle.
"""

from __future__ import annotations

import pytest

from butin.catalog.models import Item
from butin.tracking.models import ObservedLine
from butin.tracking.similarity import (
    QUANTITE_TRONQUABLE_MAX,
    MatchConfig,
    line_similarity,
    quantite_perdue,
    quantities_match,
)

#: L'objet de la session, avec son vrai identifiant.
PIERRE = Item(item_id=44380, names={"fr": "Pierre de puissance sous-marine d'arme ancestrale"})


def _ligne(raw: str, qty: int) -> ObservedLine:
    return ObservedLine(raw=raw, item=PIERRE, qty=qty)


#: Les deux lectures réelles de la MÊME ligne du jeu.
ENTIERE = _ligne("[Pierre de puissance sous-marine d'arme ancestrale] x2 (16:32)", 2)
TRONQUEE = _ligne("[Pierre de puissance sous-marine d'arme ancestrale]. (16:32)", 1)


class TestLeCasReel:
    def test_la_ligne_tronquee_n_est_plus_une_ligne_neuve(self) -> None:
        """⛔ Le test qui porte le correctif.

        Avant, ces deux lectures ne se ressemblaient plus assez, donc la
        seconde était déclarée nouvelle et créditée : un drop inventé. C'est
        arrivé cinq fois en trois minutes de farm.
        """
        cfg = MatchConfig()
        assert line_similarity(ENTIERE, TRONQUEE, cfg) >= cfg.line_accept

    def test_sans_le_correctif_elle_le_serait_encore(self) -> None:
        """⭐ Le banc sait dire non : on éteint la règle et le défaut revient.

        Un correctif dont on ne sait pas montrer l'absence n'est pas un
        correctif, c'est une coïncidence.
        """
        cfg = MatchConfig(quantite_tronquee=False)
        assert line_similarity(ENTIERE, TRONQUEE, cfg) < cfg.line_accept

    @pytest.mark.parametrize("quantite", [2, 5, 7, 10])
    def test_toutes_les_quantites_de_cet_objet_sont_couvertes(self, quantite: int) -> None:
        """Le jeu ne le donne qu'en x2, x5, x7 et x10 sur ce spot."""
        assert quantite_perdue(1, quantite)


class TestLaBorne:
    def test_un_montant_n_est_PAS_une_troncature(self) -> None:
        """⛔ Régression sur une décision existante qu'on ne balaie pas.

        `test_meme_objet_quantite_franchement_differente_chute` dit qu'une
        quantité franchement différente signale un second drop. Perdre ` x7000`
        en gardant la parenthèse de l'heure qui suit n'est pas la panne
        observée : c'est une autre lecture, et l'y assimiler ferait fondre un
        vrai drop unitaire dans une pile de sept mille.
        """
        assert not quantite_perdue(1, 7000)
        assert quantities_match(1, 7000) == (False, 0.0)

    def test_la_borne_vaut_deux_chiffres(self) -> None:
        assert quantite_perdue(1, QUANTITE_TRONQUABLE_MAX)
        assert not quantite_perdue(1, QUANTITE_TRONQUABLE_MAX + 1)

    def test_deux_quantites_qui_ne_valent_ni_l_une_ni_l_autre_1_ne_sont_pas_concernees(
        self,
    ) -> None:
        """La règle ne parle que du 1, parce que 1 est le seul écrit par une absence."""
        assert not quantite_perdue(2, 5)
        assert not quantite_perdue(5, 7)

    def test_deux_fois_1_n_est_pas_une_troncature_non_plus(self) -> None:
        """Ce sont deux lectures d'accord entre elles, pas une ambiguïté."""
        assert not quantite_perdue(1, 1)


class TestLaConfianceResteBasse:
    def test_elle_est_SOUS_celle_d_une_confusion_de_chiffres(self) -> None:
        """⭐ L'ordre des confiances dit ce qu'on sait, et ce qu'on suppose.

        Une confusion de chiffres compare deux lectures d'un nombre. Une
        troncature suppose qu'un nombre a **disparu** : c'est une hypothèse
        plus forte, donc une confiance plus basse. Assez pour ne pas inventer
        un drop, assez peu pour qu'un meilleur recouvrement l'emporte ailleurs.
        """
        _, confiance_tronquee = quantities_match(1, 2)
        _, confiance_chiffres = quantities_match(68, 88)
        assert confiance_tronquee < confiance_chiffres
        assert confiance_tronquee < 1.0

    def test_une_egalite_reste_la_meilleure_confiance(self) -> None:
        assert quantities_match(5, 5) == (True, 1.0)


class TestLePrixAssume:
    def test_un_VRAI_drop_unitaire_du_meme_objet_peut_etre_fondu(self) -> None:
        """⚠️ Ce que ce correctif coûte, écrit plutôt que découvert.

        Un vrai drop de 1 qui suit un drop du même objet dans la même minute
        est désormais indiscernable d'une troncature, donc il peut être perdu.

        C'est le sens acceptable de l'erreur : rater un drop donne un chiffre un
        peu bas, en inventer un donne un chiffre faux. Ce test existe pour que
        personne ne découvre ce prix par surprise en lisant un écart.
        """
        cfg = MatchConfig()
        vrai_unitaire = _ligne("[Pierre de puissance sous-marine d'arme ancestrale]. (16:32)", 1)
        pile = _ligne("[Pierre de puissance sous-marine d'arme ancestrale] x5 (16:32)", 5)
        assert line_similarity(pile, vrai_unitaire, cfg) >= cfg.line_accept

    def test_un_objet_DIFFERENT_reste_un_drop_different(self) -> None:
        """La règle ne touche qu'à la quantité, jamais à l'identité."""
        autre = ObservedLine(
            raw="[Poussiere d'esprit ancien]. (16:32)",
            item=Item(item_id=721002, names={"fr": "Poussière d'esprit ancien"}),
            qty=1,
        )
        cfg = MatchConfig()
        assert line_similarity(ENTIERE, autre, cfg) < cfg.line_accept
