"""Tests de la comparaison de deux lignes observées."""

from __future__ import annotations

import pytest

from butin.catalog import ItemCatalog
from butin.tracking import MatchConfig, digit_confusable, line_similarity
from butin.tracking.models import ObservedLine
from butin.tracking.similarity import items_match, quantities_match


def ligne(
    catalog: ItemCatalog,
    item_id: int | None,
    qty: int = 1,
    raw: str = "",
    confidence: float = 1.0,
) -> ObservedLine:
    item = catalog.get(item_id) if item_id is not None else None
    return ObservedLine(
        raw=raw or (item.name() if item else "?"),
        item=item,
        qty=qty,
        name_confidence=confidence,
    )


class TestConfusionDeChiffres:
    @pytest.mark.parametrize(("a", "b"), [(6, 8), (1, 7), (68, 88), (168, 188), (5, 6)])
    def test_paires_confondables(self, a: int, b: int) -> None:
        assert digit_confusable(a, b)
        assert digit_confusable(b, a), "la relation doit être symétrique"

    @pytest.mark.parametrize(("a", "b"), [(1, 2), (10, 20), (3, 9)])
    def test_paires_non_confondables(self, a: int, b: int) -> None:
        assert not digit_confusable(a, b)

    def test_un_nombre_n_est_pas_confondable_avec_lui_meme(self) -> None:
        """La confusion décrit une divergence, pas une égalité.

        Renvoyer True ici ferait passer une égalité pour une hypothèse, et la
        confiance associée (0,75) écraserait la certitude réelle (1,0).
        """
        assert not digit_confusable(8, 8)

    def test_longueurs_differentes_jamais_confondables(self) -> None:
        """Régression : perdre un chiffre n'est pas confondre un glyphe.

        Sans ce contrôle, « 16 » et « 160 » seraient traités comme la même
        quantité, et un drop de 160 unités serait compté 16.
        """
        assert not digit_confusable(16, 160)
        assert not digit_confusable(1, 11)


class TestCorrespondanceDeQuantites:
    def test_egalite_certaine(self) -> None:
        assert quantities_match(5, 5) == (True, 1.0)

    def test_confusion_acceptee_avec_confiance_reduite(self) -> None:
        ok, confiance = quantities_match(6, 8)
        assert ok
        assert confiance < 1.0

    def test_confusion_desactivable(self) -> None:
        cfg = MatchConfig(digit_confusion=False)
        assert quantities_match(6, 8, cfg) == (False, 0.0)

    def test_valeurs_differentes_rejetees(self) -> None:
        assert quantities_match(2, 9) == (False, 0.0)


class TestCorrespondanceDObjets:
    def test_meme_identifiant_meme_objet(self, catalog: ItemCatalog) -> None:
        """La comparaison passe par l'identifiant, pas par le texte.

        C'est la différence de fond avec le projet d'origine : deux lectures
        abîmées du même objet donnent deux chaînes différentes, mais le même
        identifiant. Comparer les chaînes les déclarerait différentes.
        """
        a = ligne(catalog, 16001, raw="Pierre noire (arme)")
        b = ligne(catalog, 16001, raw="P1erre no1re (arme)")
        assert items_match(a, b) == (True, 1.0)

    def test_identifiants_differents(self, catalog: ItemCatalog) -> None:
        a = ligne(catalog, 4998)
        b = ligne(catalog, 4997)
        assert items_match(a, b)[0] is False

    def test_lignes_non_resolues_comparees_par_texte(self, catalog: ItemCatalog) -> None:
        """Une ligne illisible reste comparable, sinon l'alignement casse.

        Elle ne deviendra jamais un drop, mais elle occupe une place à l'écran,
        et l'alignement repose sur les positions.
        """
        a = ligne(catalog, None, raw="Message systeme inconnu")
        b = ligne(catalog, None, raw="Message systeme inconnu")
        assert items_match(a, b)[0] is True

    def test_une_seule_resolue_compare_par_texte(self, catalog: ItemCatalog) -> None:
        a = ligne(catalog, 16001, raw="Pierre noire (arme)")
        b = ligne(catalog, None, raw="Texte sans aucun rapport")
        assert items_match(a, b)[0] is False


class TestSimilariteDeLigne:
    def test_ligne_identique_score_maximal(self, catalog: ItemCatalog) -> None:
        a = ligne(catalog, 16001, qty=3)
        assert line_similarity(a, a) == pytest.approx(1.0)

    def test_meme_objet_quantite_confondable_reste_haut(self, catalog: ItemCatalog) -> None:
        """La même ligne dont le chiffre a été mal lu doit rester la même ligne.

        Sinon l'alignement croit qu'elle a disparu et qu'une autre est apparue,
        ce qui recompte le drop.
        """
        a = ligne(catalog, 16001, qty=68)
        b = ligne(catalog, 16001, qty=88)
        assert line_similarity(a, b) >= MatchConfig().line_accept

    def test_meme_objet_quantite_franchement_differente_chute(self, catalog: ItemCatalog) -> None:
        """Probablement un SECOND drop du même objet, pas la même ligne."""
        a = ligne(catalog, 16001, qty=1)
        b = ligne(catalog, 16001, qty=7000)
        assert line_similarity(a, b) < MatchConfig().line_accept

    def test_objets_differents_score_tres_bas(self, catalog: ItemCatalog) -> None:
        a = ligne(catalog, 4998)
        b = ligne(catalog, 4997)
        assert line_similarity(a, b) < 0.5
