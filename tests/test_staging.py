"""Tests de la validation d'un drop après plusieurs images concordantes."""

from __future__ import annotations

from butin.catalog import ItemCatalog
from butin.tracking import LootStager
from butin.tracking.models import ObservedLine

A, B, C = 16001, 16002, 4998


def ligne(
    catalog: ItemCatalog,
    item_id: int | None,
    qty: int = 1,
    raw: str = "",
    confidence: float = 1.0,
    quantity_uncertain: bool = False,
) -> ObservedLine:
    item = catalog.get(item_id) if item_id is not None else None
    return ObservedLine(
        raw=raw or (item.name() if item else "?"),
        item=item,
        qty=qty,
        name_confidence=confidence,
        quantity_uncertain=quantity_uncertain,
    )


class TestSeuilDeValidation:
    def test_une_seule_observation_ne_valide_rien(self, catalog: ItemCatalog) -> None:
        """Rien n'est compté à la première apparition.

        Une lecture unique peut être un raté d'OCR. Attendre coûte un dixième
        de seconde et rend le total insensible aux ratés ponctuels.
        """
        stager = LootStager(min_sightings=2)
        events = stager.observe(overlap=0, current_lines=[ligne(catalog, A)])
        assert events == []
        assert stager.pending_count == 1

    def test_deux_observations_valident(self, catalog: ItemCatalog) -> None:
        stager = LootStager(min_sightings=2)
        stager.observe(0, [ligne(catalog, A)])
        events = stager.observe(1, [ligne(catalog, A)])

        assert len(events) == 1
        assert events[0].item.item_id == A
        assert events[0].sightings == 2

    def test_un_drop_n_est_valide_qu_une_seule_fois(self, catalog: ItemCatalog) -> None:
        """Le test le plus important du module.

        La ligne reste affichée une quinzaine de secondes, donc elle est relue
        des dizaines de fois. Si chaque relecture produisait un événement, le
        total serait multiplié par le nombre de captures.
        """
        stager = LootStager(min_sightings=2)
        total = 0
        for _ in range(20):
            total += len(stager.observe(1, [ligne(catalog, A)]))

        assert total == 1

    def test_seuil_a_une_observation(self, catalog: ItemCatalog) -> None:
        stager = LootStager(min_sightings=1)
        events = stager.observe(0, [ligne(catalog, A)])
        assert len(events) == 1


class TestLigneDeBase:
    def test_le_butin_deja_a_l_ecran_n_est_jamais_compte(self, catalog: ItemCatalog) -> None:
        """Régression : sinon lancer le suivi compte quinze drops du passé.

        Le journal affiche les dernières lignes en permanence, y compris celles
        d'avant le démarrage du tracker. Elles appartiennent à l'historique.
        """
        stager = LootStager(min_sightings=2)
        deja_la = [ligne(catalog, A), ligne(catalog, B), ligne(catalog, C)]
        stager.seed(deja_la)

        events = stager.observe(3, deja_la)

        assert events == []
        assert stager.pending_count == 0

    def test_les_nouvelles_lignes_apres_la_base_sont_comptees(self, catalog: ItemCatalog) -> None:
        stager = LootStager(min_sightings=2)
        base = [ligne(catalog, A), ligne(catalog, B)]
        stager.seed(base)

        stager.observe(2, [*base, ligne(catalog, C)])
        events = stager.observe(3, [*base, ligne(catalog, C)])

        assert [e.item.item_id for e in events] == [C]


class TestVote:
    def test_la_lecture_majoritaire_gagne(self, catalog: ItemCatalog) -> None:
        """Un raté isolé sur trois lectures ne doit pas décider du résultat."""
        stager = LootStager(min_sightings=3)
        stager.observe(0, [ligne(catalog, A)])
        stager.observe(1, [ligne(catalog, B)])
        events = stager.observe(1, [ligne(catalog, A)])

        assert len(events) == 1
        assert events[0].item.item_id == A

    def test_la_quantite_majoritaire_gagne(self, catalog: ItemCatalog) -> None:
        stager = LootStager(min_sightings=3)
        stager.observe(0, [ligne(catalog, A, qty=3)])
        stager.observe(1, [ligne(catalog, A, qty=8)])
        events = stager.observe(1, [ligne(catalog, A, qty=3)])

        assert events[0].qty == 3

    def test_une_quantite_douteuse_pese_moins(self, catalog: ItemCatalog) -> None:
        """Une lecture dont le « x » était illisible ne vaut pas une lecture nette.

        Deux lectures douteuses à 8 contre une lecture nette à 3 : la nette
        l'emporte, parce que le doute a été enregistré au moment de la lecture
        au lieu d'être oublié.
        """
        stager = LootStager(min_sightings=3)
        stager.observe(0, [ligne(catalog, A, qty=8, quantity_uncertain=True)])
        stager.observe(1, [ligne(catalog, A, qty=8, quantity_uncertain=True)])
        events = stager.observe(1, [ligne(catalog, A, qty=3)])

        assert events[0].qty == 3

    def test_egalite_ne_gonfle_pas_le_total(self, catalog: ItemCatalog) -> None:
        """Régression : à égalité, ne jamais préférer la plus grande valeur.

        Sous un bruit symétrique (6 lu 8 aussi souvent que 8 lu 6), préférer
        systématiquement la plus grande gonflerait les totaux de façon
        régulière, ce qui est précisément l'erreur qu'un tracker ne doit pas
        commettre.
        """
        stager = LootStager(min_sightings=2)
        stager.observe(0, [ligne(catalog, A, qty=6)])
        events = stager.observe(1, [ligne(catalog, A, qty=8)])

        assert events[0].qty == 6

    def test_une_ligne_jamais_reconnue_ne_produit_rien(self, catalog: ItemCatalog) -> None:
        """Compter un drop inconnu serait pire que ne rien compter."""
        stager = LootStager(min_sightings=2)
        stager.observe(0, [ligne(catalog, None, raw="Bruit illisible")])
        events = stager.observe(1, [ligne(catalog, None, raw="Bruit illisible")])

        assert events == []
        assert stager.unresolved_finalized == 1

    def test_une_ligne_inconnue_n_est_pas_reexaminee_sans_fin(self, catalog: ItemCatalog) -> None:
        """Régression : sinon le compteur de non-reconnus explose.

        Une ligne inconnue reste à l'écran des dizaines d'images. Sans
        marquage, elle serait recomptée comme « non reconnue » à chaque image.
        """
        stager = LootStager(min_sightings=2)
        for _ in range(10):
            stager.observe(1, [ligne(catalog, None, raw="Bruit illisible")])

        assert stager.unresolved_finalized == 1


class TestSortieDEcran:
    def test_une_ligne_non_validee_sortie_est_comptabilisee_comme_perdue(
        self, catalog: ItemCatalog
    ) -> None:
        """Ce compteur mesure ce que le tracker a raté.

        Une valeur non nulle signale que du vrai butin n'a pas été compté,
        typiquement parce que la capture est trop lente pour le journal. Sans
        ce compteur, la perte serait silencieuse.
        """
        stager = LootStager(min_sightings=5)
        stager.observe(0, [ligne(catalog, A)])
        stager.observe(0, [ligne(catalog, B)])

        assert stager.dropped_unconfirmed == 1
        assert stager.lost_resolved == 1

    def test_les_traces_sont_vidables(self, catalog: ItemCatalog) -> None:
        stager = LootStager(min_sightings=5)
        stager.observe(0, [ligne(catalog, A, raw="Pierre noire (arme)")])
        stager.observe(0, [ligne(catalog, B)])

        records = stager.drain_dropped()
        assert records == [("Pierre noire (arme)", True)]
        assert stager.drain_dropped() == []


class TestVidage:
    def test_le_vidage_valide_les_derniers_drops(self, catalog: ItemCatalog) -> None:
        """À l'arrêt, le butin vu une seule fois ne doit pas être perdu."""
        stager = LootStager(min_sightings=5)
        stager.observe(0, [ligne(catalog, A)])

        events = stager.flush()

        assert [e.item.item_id for e in events] == [A]

    def test_le_vidage_ne_double_pas_un_drop_deja_valide(self, catalog: ItemCatalog) -> None:
        """Régression : le vidage est la dernière occasion de tout recompter."""
        stager = LootStager(min_sightings=2)
        stager.observe(0, [ligne(catalog, A)])
        deja = stager.observe(1, [ligne(catalog, A)])

        assert len(deja) == 1
        assert stager.flush() == []

    def test_remise_a_zero(self, catalog: ItemCatalog) -> None:
        stager = LootStager(min_sightings=5)
        stager.observe(0, [ligne(catalog, A)])
        stager.observe(0, [ligne(catalog, B)])
        stager.reset()

        assert stager.pending_count == 0
        assert stager.dropped_unconfirmed == 0
        assert stager.lost_resolved == 0
