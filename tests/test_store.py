"""Tests des sessions et du silver par heure."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from butin.market import Price, PriceBook, PriceCache, PriceSource
from butin.store import SCHEMA_VERSION, LootRow, SessionStore, Stats, TaxProfile, compute
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
        assert version["version"] == SCHEMA_VERSION

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


class TestPause:
    """La mise en pause, et surtout ce qu'elle fait au CHIFFRE.

    Le silver par heure divise le total par la durée. Compter une pause repas
    comme du farm ne donne pas un chiffre un peu bas, il donne un chiffre faux :
    vingt minutes de pause sur une heure de session divisent le résultat par 1,3
    sans que rien ne l'explique à l'écran.
    """

    def test_le_temps_en_pause_est_deduit(self, store) -> None:
        session = store.start_session(started_at=0.0)
        store.pause_session(session.id, at=600.0)
        store.resume_session(session.id, at=1200.0)
        store.end_session(session.id, ended_at=1800.0)

        # 30 min de session, 10 min de pause : 20 min de farm.
        assert store.get_session(session.id).duration_s(now=0.0) == pytest.approx(1200.0)

    def test_la_duree_se_fige_pendant_la_pause(self, store) -> None:
        """⭐ Régression : c'est pour ça que `paused_at` est en base.

        Cumuler seulement au moment de reprendre laisserait la durée grandir
        **pendant** la pause, donc le silver par heure s'effondrer sous les yeux
        de quelqu'un qui a justement mis en pause pour ne pas être compté.
        """
        session = store.start_session(started_at=0.0)
        store.pause_session(session.id, at=600.0)
        en_pause = store.get_session(session.id)

        assert en_pause.is_paused
        assert en_pause.duration_s(now=600.0) == pytest.approx(600.0)
        assert en_pause.duration_s(now=99999.0) == pytest.approx(600.0)

    def test_deux_pauses_s_additionnent(self, store) -> None:
        session = store.start_session(started_at=0.0)
        store.pause_session(session.id, at=100.0)
        store.resume_session(session.id, at=200.0)
        store.pause_session(session.id, at=300.0)
        store.resume_session(session.id, at=500.0)

        assert store.get_session(session.id).duration_s(now=600.0) == pytest.approx(300.0)

    def test_mettre_en_pause_deux_fois_ne_decale_pas_le_debut(self, store) -> None:
        """Régression : deux clics, ou deux requêtes simultanées.

        Sans le `paused_at IS NULL` de la condition, le second appel écraserait
        le début de la pause et rendrait invisible du temps déjà mis de côté.
        """
        session = store.start_session(started_at=0.0)
        store.pause_session(session.id, at=100.0)
        store.pause_session(session.id, at=400.0)
        store.resume_session(session.id, at=500.0)

        assert store.get_session(session.id).duration_s(now=500.0) == pytest.approx(100.0)

    def test_arreter_pendant_une_pause_ferme_la_pause(self, store) -> None:
        """⭐ Régression : la session qui rétrécit toute seule, pour toujours.

        Arrêter depuis l'état en pause laissait `paused_at` posé. La durée en
        soustrayait alors le temps écoulé **après** la fin de la session, donc
        elle diminuait à chaque consultation de l'historique, des mois après.
        """
        session = store.start_session(started_at=0.0)
        store.pause_session(session.id, at=600.0)
        store.end_session(session.id, ended_at=900.0)
        arretee = store.get_session(session.id)

        assert not arretee.is_paused
        assert arretee.duration_s(now=900.0) == pytest.approx(600.0)
        # Un mois plus tard, le même chiffre.
        assert arretee.duration_s(now=900.0 + 30 * 86400) == pytest.approx(600.0)

    def test_une_horloge_qui_recule_n_allonge_pas_le_farm(self, store) -> None:
        """Le passage à l'heure d'hiver recule l'horloge système d'une heure.

        Sans le `MAX(0, ...)`, `paused_s` deviendrait négatif et la pause
        AJOUTERAIT du temps de farm, donc gonflerait le silver par heure.
        """
        session = store.start_session(started_at=0.0)
        store.pause_session(session.id, at=1000.0)
        store.resume_session(session.id, at=1000.0 - 3600.0)

        assert store.get_session(session.id).duration_s(now=2000.0) == pytest.approx(2000.0)

    def test_reprendre_sans_pause_ne_fait_rien(self, store) -> None:
        session = store.start_session(started_at=0.0)
        store.resume_session(session.id, at=500.0)

        assert store.get_session(session.id).duration_s(now=1000.0) == pytest.approx(1000.0)

    def test_une_session_neuve_n_est_pas_en_pause(self, store) -> None:
        assert not store.start_session(started_at=0.0).is_paused


class TestMigrationV1:
    """⭐ Une base d'avant doit survivre à la mise à jour.

    `CREATE TABLE IF NOT EXISTS` ne touche pas une table déjà là : sans
    migration explicite, une base v1 garderait ses six colonnes et toute
    lecture échouerait sur `paused_s`. Du point de vue de la personne, un
    historique de farm qu'on ne sait plus relire est un historique perdu.
    """

    SCHEMA_V1 = """
    CREATE TABLE schema_version (version INTEGER NOT NULL);
    CREATE TABLE sessions (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        spot          TEXT    NOT NULL DEFAULT '',
        region        TEXT    NOT NULL DEFAULT 'eu',
        started_at    REAL    NOT NULL,
        ended_at      REAL,
        silver_direct INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE loot (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        item_id    INTEGER NOT NULL,
        sid        INTEGER NOT NULL DEFAULT 0,
        qty        INTEGER NOT NULL,
        at         REAL    NOT NULL
    );
    """

    def _base_v1(self, chemin: Path) -> None:
        """Écrit une vraie base au schéma v1, tel qu'il était publié."""
        connexion = sqlite3.connect(chemin)
        connexion.executescript(self.SCHEMA_V1)
        connexion.execute("INSERT INTO schema_version (version) VALUES (1)")
        connexion.execute(
            "INSERT INTO sessions (spot, region, started_at, ended_at, silver_direct) "
            "VALUES ('Gyfin', 'eu', 0.0, 3600.0, 4200)"
        )
        connexion.execute(
            "INSERT INTO loot (session_id, item_id, sid, qty, at) VALUES (1, 16001, 0, 7, 10.0)"
        )
        connexion.commit()
        connexion.close()

    def test_une_base_v1_se_relit_sans_rien_perdre(self, tmp_path: Path) -> None:
        chemin = tmp_path / "sessions.sqlite3"
        self._base_v1(chemin)

        with SessionStore(chemin) as base:
            session = base.get_session(1)

            assert session.spot == "Gyfin"
            assert session.silver_direct == 4200
            assert base.loot_count(1) == 7
            assert session.duration_s(now=0.0) == pytest.approx(3600.0)

    def test_les_anciennes_sessions_n_ont_jamais_ete_en_pause(self, tmp_path: Path) -> None:
        """Les valeurs par défaut disent la vérité : la pause n'existait pas."""
        chemin = tmp_path / "sessions.sqlite3"
        self._base_v1(chemin)

        with SessionStore(chemin) as base:
            session = base.get_session(1)

            assert session.paused_s == 0.0
            assert session.paused_at is None
            assert not session.is_paused

    def test_le_numero_de_schema_est_releve(self, tmp_path: Path) -> None:
        """Régression : sans ça la migration rejouerait à chaque ouverture."""
        chemin = tmp_path / "sessions.sqlite3"
        self._base_v1(chemin)

        with SessionStore(chemin) as base:
            ligne = base._connection.execute("SELECT version FROM schema_version").fetchone()
            assert ligne["version"] == SCHEMA_VERSION

        with SessionStore(chemin) as relue:
            assert relue.get_session(1).spot == "Gyfin"

    def test_la_pause_marche_sur_une_base_migree(self, tmp_path: Path) -> None:
        chemin = tmp_path / "sessions.sqlite3"
        self._base_v1(chemin)

        with SessionStore(chemin) as base:
            session = base.start_session(started_at=0.0)
            base.pause_session(session.id, at=100.0)
            base.resume_session(session.id, at=300.0)

            assert base.get_session(session.id).duration_s(now=500.0) == pytest.approx(300.0)


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


class TestTauxDeTaxe:
    """Le taux vient d'un profil de compte, pas d'une constante.

    Les valeurs sont vérifiées contre le calculateur de garmoth, capture à
    l'appui, et non déduites de la documentation.
    """

    def test_point_de_mesure_reel_garmoth(self) -> None:
        """Régression : l'ancre qui valide toute la formule.

        Relevé sur le calculateur de garmoth le 05/08/2026 : Value Pack oui,
        anneau de marchand non, renommée familiale 11952, taux affiché
        **85,47 %**.

        C'est ce point qui prouve que les bonus **multiplient** le taux de base
        au lieu de s'y ajouter. L'addition donnerait 0,65 + 0,30 + 0,015 = 0,965,
        soit une surestimation de 13 % sur chaque vente, appliquée à toutes.
        """
        profil = TaxProfile(value_pack=True, merchant_ring=False, family_fame=11952)
        assert profil.net_rate == pytest.approx(0.8547, abs=0.0001)

    def test_sans_aucun_bonus(self) -> None:
        """L'hôtel des ventes prélève 35 %."""
        assert TaxProfile().net_rate == pytest.approx(0.65)

    def test_abonnement_seul_donne_le_chiffre_bien_connu(self) -> None:
        assert TaxProfile(value_pack=True).net_rate == pytest.approx(0.845)

    def test_les_paliers_de_renommee(self) -> None:
        assert TaxProfile(family_fame=999).fame_bonus == 0.0
        assert TaxProfile(family_fame=1000).fame_bonus == 0.005
        assert TaxProfile(family_fame=4000).fame_bonus == 0.010
        assert TaxProfile(family_fame=7000).fame_bonus == 0.015
        assert TaxProfile(family_fame=99999).fame_bonus == 0.015

    def test_tout_cumule(self) -> None:
        profil = TaxProfile(value_pack=True, merchant_ring=True, family_fame=7000)
        assert profil.net_rate == pytest.approx(0.65 * 1.365)

    def test_le_profil_alimente_le_calcul(self, tmp_path: Path) -> None:
        """Le profil n'est pas décoratif : il change le total."""
        book = livre(tmp_path)
        book.cache.put(
            Price(item_id=16001, value=1_000_000, source=PriceSource.MARKET, fetched_at=1000.0)
        )
        profil = TaxProfile(value_pack=True, family_fame=11952)
        stats = compute(
            {(16001, 0): 1}, book, duration_s=HEURE, market_rate=profil.net_rate, now=1100.0
        )

        assert stats.net_market == 854_750


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


class TestDerniersDrops:
    def test_du_plus_recent_au_plus_ancien(self, tmp_path: Path) -> None:
        store = SessionStore(tmp_path / "s.sqlite3")
        session = store.start_session(started_at=0.0)
        store.add_loot(
            session.id,
            [
                LootRow(item_id=1, qty=1, at=10.0),
                LootRow(item_id=2, qty=2, at=30.0),
                LootRow(item_id=3, qty=3, at=20.0),
            ],
        )

        derniers = store.recent_loot(session.id)

        assert [ligne.item_id for ligne in derniers] == [2, 3, 1]

    def test_la_liste_est_bornee(self, tmp_path: Path) -> None:
        """Une session de plusieurs heures contient des milliers de lignes.

        La fenêtre n'en montre qu'une vingtaine, et elle se rafraîchit chaque
        seconde : tout rapatrier pour en jeter 99 % serait payé à chaque fois.
        """
        store = SessionStore(tmp_path / "s.sqlite3")
        session = store.start_session(started_at=0.0)
        store.add_loot(
            session.id, [LootRow(item_id=index, qty=1, at=float(index)) for index in range(200)]
        )

        assert len(store.recent_loot(session.id, limit=25)) == 25

    def test_une_session_sans_butin_rend_une_liste_vide(self, tmp_path: Path) -> None:
        store = SessionStore(tmp_path / "s.sqlite3")
        session = store.start_session(started_at=0.0)

        assert store.recent_loot(session.id) == []
