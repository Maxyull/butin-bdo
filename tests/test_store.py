"""Tests des sessions et du silver par heure."""

from __future__ import annotations

from pathlib import Path

import pytest

from butin.market import Price, PriceBook, PriceCache, PriceSource
from butin.store import LootRow, SessionStore, Stats, compute
from butin.store.stats import MARKET_RATE_BASE

HEURE = 3600.0


@pytest.fixture
def store(tmp_path: Path):
    with SessionStore(tmp_path / "sessions.sqlite3") as base:
        yield base


def livre(tmp_path: Path, vendor: dict[int, dict[str, int]] | None = None) -> PriceBook:
    return PriceBook(
        client=None, cache=PriceCache(tmp_path / "prix.json"), vendor_values=vendor or {}
    )


class TestSchema:
    def test_le_numero_de_schema_existe_des_la_premiere_version(self, store) -> None:
        """Régression : c'est ce qu'on ne peut pas rajouter après coup.

        Sans lui, la première migration devrait deviner la version d'une base
        existante à partir de la forme de ses tables, ce qui se trompe en
        silence sur un historique de farm que personne n'accepte de perdre.
        """
        version = store._connection.execute("SELECT version FROM schema_version").fetchone()
        assert version["version"] == 1

    def test_une_base_plus_recente_que_le_code_est_refusee(self, tmp_path: Path) -> None:
        """Ouvrir en écriture une base écrite par une version future la
        corromprait, avec des données qu'on ne sait de toute façon pas relire."""
        chemin = tmp_path / "sessions.sqlite3"
        with SessionStore(chemin) as base:
            base._connection.execute("UPDATE schema_version SET version = 99")
            base._connection.commit()

        with pytest.raises(RuntimeError, match="version 99"):
            SessionStore(chemin)

    def test_reouverture_sans_perte(self, tmp_path: Path) -> None:
        chemin = tmp_path / "sessions.sqlite3"
        with SessionStore(chemin) as base:
            session = base.start_session(started_at=0.0, spot="Sausan")
            base.add_loot(session.id, [LootRow(item_id=16001, qty=3, at=1.0)])

        with SessionStore(chemin) as relu:
            assert relu.loot_count(session.id) == 3
            assert relu.get_session(session.id).spot == "Sausan"


class TestSession:
    def test_cycle_de_vie(self, store) -> None:
        session = store.start_session(started_at=100.0, spot="Gyfin", region="eu")
        assert session.is_open

        store.end_session(session.id, ended_at=100.0 + HEURE)
        relue = store.get_session(session.id)

        assert not relue.is_open
        assert relue.duration_s(now=0.0) == pytest.approx(HEURE)

    def test_une_session_ouverte_dure_jusqu_a_maintenant(self, store) -> None:
        session = store.start_session(started_at=0.0)
        assert session.duration_s(now=1800.0) == pytest.approx(1800.0)

    def test_fermer_deux_fois_ne_change_pas_la_fin(self, store) -> None:
        """Régression : sinon un double clic sur « arrêter » allongerait la
        session, donc diviserait le silver par heure sans raison."""
        session = store.start_session(started_at=0.0)
        store.end_session(session.id, ended_at=100.0)
        store.end_session(session.id, ended_at=999.0)

        assert store.get_session(session.id).ended_at == pytest.approx(100.0)

    def test_le_silver_direct_s_additionne(self, store) -> None:
        """Il tombe par petits montants tout au long d'une session.

        L'écraser ne garderait que le dernier ramassage.
        """
        session = store.start_session(started_at=0.0)
        store.add_silver(session.id, 1000)
        store.add_silver(session.id, 500)

        assert store.get_session(session.id).silver_direct == 1500


class TestQuantites:
    def test_cumul_par_objet(self, store) -> None:
        session = store.start_session(started_at=0.0)
        store.add_loot(
            session.id,
            [
                LootRow(item_id=16001, qty=3, at=1.0),
                LootRow(item_id=16001, qty=5, at=2.0),
                LootRow(item_id=44195, qty=1, at=3.0),
            ],
        )

        assert store.quantities(session.id) == {(16001, 0): 8, (44195, 0): 1}

    def test_les_niveaux_ne_se_melangent_pas(self, store) -> None:
        """Régression : un accessoire et son TET partagent leur identifiant.

        Les cumuler ensemble valoriserait le TET au prix du niveau de base, ce
        qui fausse un total de plusieurs milliards.
        """
        session = store.start_session(started_at=0.0)
        store.add_loot(
            session.id,
            [LootRow(item_id=11653, qty=1, at=1.0), LootRow(item_id=11653, qty=1, at=2.0, sid=4)],
        )

        assert store.quantities(session.id) == {(11653, 0): 1, (11653, 4): 1}

    def test_les_sessions_ne_se_melangent_pas(self, store) -> None:
        une = store.start_session(started_at=0.0)
        deux = store.start_session(started_at=10.0)
        store.add_loot(une.id, [LootRow(item_id=16001, qty=3, at=1.0)])
        store.add_loot(deux.id, [LootRow(item_id=16001, qty=7, at=11.0)])

        assert store.quantities(une.id) == {(16001, 0): 3}
        assert store.quantities(deux.id) == {(16001, 0): 7}


class TestTaxe:
    def test_la_taxe_ne_s_applique_pas_au_marchand(self, tmp_path: Path) -> None:
        """Le piège central du calcul.

        Vendre à l'hôtel des ventes coûte une taxe, vendre au marchand n'en
        coûte aucune. Appliquer la même aux deux sous-estimerait le trash loot,
        qui est justement l'essentiel du revenu d'une session de farm.
        """
        stats = compute(
            {(43984, 0): 10},
            livre(tmp_path, vendor={43984: {"base": 500}}),
            duration_s=HEURE,
        )

        assert stats.vendor == 5000
        assert stats.net_market == 0
        assert stats.total == 5000

    def test_la_taxe_s_applique_au_marche(self, tmp_path: Path) -> None:
        book = livre(tmp_path)
        book.cache.put(
            Price(item_id=16001, value=100_000, source=PriceSource.MARKET, fetched_at=1000.0)
        )
        stats = compute({(16001, 0): 10}, book, duration_s=HEURE, now=1100.0)

        assert stats.gross_market == 1_000_000
        assert stats.net_market == int(1_000_000 * MARKET_RATE_BASE)
        assert stats.net_market < stats.gross_market

    def test_le_taux_est_reglable(self, tmp_path: Path) -> None:
        """Le taux dépend du COMPTE, pas du jeu.

        Abonnement et objets bonus le font monter. Il n'y a donc pas de bon
        taux par défaut, il y a le taux de ce joueur, et un taux faux applique
        une erreur systématique au total.
        """
        book = livre(tmp_path)
        book.cache.put(
            Price(item_id=16001, value=1000, source=PriceSource.MARKET, fetched_at=1000.0)
        )
        stats = compute({(16001, 0): 1}, book, duration_s=HEURE, market_rate=0.845, now=1100.0)

        assert stats.net_market == 845

    def test_le_silver_direct_n_est_jamais_taxe(self, tmp_path: Path) -> None:
        stats = compute({}, livre(tmp_path), duration_s=HEURE, silver_direct=10_000_000)
        assert stats.total == 10_000_000


class TestSilverParHeure:
    def test_calcul_nominal(self, tmp_path: Path) -> None:
        stats = compute(
            {(43984, 0): 100},
            livre(tmp_path, vendor={43984: {"base": 1000}}),
            duration_s=2 * HEURE,
        )
        assert stats.per_hour == pytest.approx(50_000)

    def test_une_session_trop_courte_ne_rend_pas_un_chiffre_absurde(self, tmp_path: Path) -> None:
        """Régression : sur les premières secondes, la division explose.

        Un drop à 10 millions vu après deux secondes donnerait 18 milliards par
        heure, qu'un utilisateur pourrait prendre au sérieux le temps que ça se
        stabilise.
        """
        stats = compute(
            {(43984, 0): 1},
            livre(tmp_path, vendor={43984: {"base": 10_000_000}}),
            duration_s=2.0,
        )
        assert stats.per_hour == 0.0
        assert stats.total == 10_000_000, "le total, lui, reste juste"


class TestHonnetete:
    def test_un_objet_inconnu_est_compte_a_part(self, tmp_path: Path) -> None:
        """Un total calculé alors que la moitié des objets sont inconnus n'a
        pas la même valeur qu'un total complet, et seul l'utilisateur peut
        juger si ça lui suffit."""
        stats = compute({(999999, 0): 7}, livre(tmp_path), duration_s=HEURE)

        assert stats.unknown_items == 7
        assert not stats.is_complete
        assert stats.coverage == pytest.approx(0.0)

    def test_la_couverture_se_mesure(self, tmp_path: Path) -> None:
        stats = compute(
            {(43984, 0): 3, (999999, 0): 1},
            livre(tmp_path, vendor={43984: {"base": 500}}),
            duration_s=HEURE,
        )
        assert stats.coverage == pytest.approx(0.75)

    def test_les_prix_perimes_sont_signales(self, tmp_path: Path) -> None:
        """Le total reste utilisable, mais ce n'est pas un cours du jour."""
        book = livre(tmp_path)
        book.cache.put(Price(item_id=16001, value=1000, source=PriceSource.MARKET, fetched_at=0.0))
        stats = compute({(16001, 0): 4}, book, duration_s=HEURE, now=1_000_000.0)

        assert stats.stale_prices == 4
        assert stats.net_market > 0

    def test_session_vide(self, tmp_path: Path) -> None:
        stats = compute({}, livre(tmp_path), duration_s=HEURE)
        assert stats == Stats(duration_s=HEURE, per_source={})
        assert stats.is_complete
