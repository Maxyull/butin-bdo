"""Persistance des sessions de farm.

SQLite, par la bibliothèque standard. Aucune dépendance ajoutée pour ça : le
besoin est un fichier local que l'utilisateur garde des mois, pas un serveur.

Le numéro de schéma existe dès la première version
--------------------------------------------------

`docs/versionnage.md` classe le schéma de cette base dans l'**API publique** :
elle contient un historique de farm que personne n'accepterait de perdre à une
mise à jour.

La table `schema_version` est donc là dès le départ, alors qu'il n'y a encore
rien à migrer. C'est exactement ce qu'on ne peut pas rajouter après coup : sans
elle, la première migration devrait deviner la version d'une base existante à
partir de la forme de ses tables, ce qui est fragile et se trompe en silence.

Ce qu'on ne stocke pas, et pourquoi
-----------------------------------

Ni pseudonyme, ni nom de famille, ni capture d'écran. La base ne contient que
des identifiants d'objets, des quantités et des horodatages. Rien de ce qu'elle
contient ne permettrait d'identifier son propriétaire si le fichier était
partagé, ce qui rend un rapport de bogue bien plus facile à envoyer.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .. import paths

SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    spot          TEXT    NOT NULL DEFAULT '',
    region        TEXT    NOT NULL DEFAULT 'eu',
    started_at    REAL    NOT NULL,
    ended_at      REAL,
    silver_direct INTEGER NOT NULL DEFAULT 0,
    paused_s      REAL    NOT NULL DEFAULT 0,
    paused_at     REAL
);

CREATE TABLE IF NOT EXISTS loot (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    item_id    INTEGER NOT NULL,
    sid        INTEGER NOT NULL DEFAULT 0,
    qty        INTEGER NOT NULL,
    at         REAL    NOT NULL
);

CREATE INDEX IF NOT EXISTS loot_par_session ON loot(session_id);
"""


@dataclass(frozen=True, slots=True)
class Session:
    """Une session de farm."""

    id: int
    spot: str
    region: str
    started_at: float
    ended_at: float | None = None
    silver_direct: int = 0
    """Silver ramassé directement (« Pièces »), déjà exprimé dans l'unité
    finale : il ne passe jamais par une recherche de prix."""

    paused_s: float = 0.0
    """Temps déjà passé en pause, cumulé sur toute la session."""

    paused_at: float | None = None
    """Début de la pause en cours, ou None si la session tourne.

    Gardé en base plutôt que cumulé au moment de reprendre : sans lui, la durée
    affichée continuerait de grandir **pendant** la pause, et le silver par
    heure de s'effondrer sous les yeux de quelqu'un qui a justement mis en pause
    pour ne pas être compté.
    """

    @property
    def is_open(self) -> bool:
        return self.ended_at is None

    @property
    def is_paused(self) -> bool:
        return self.paused_at is not None

    def duration_s(self, now: float) -> float:
        """Durée de farm réelle, temps de pause déduit.

        ⚠️ Déduire la pause n'est pas un confort, c'est ce qui rend le chiffre
        juste. Le silver par heure divise le total par cette durée : une pause
        repas de vingt minutes comptée comme du farm diviserait le résultat
        d'une session d'une heure par 1,3. Un chiffre faux, pas un chiffre bas.
        """
        fin = self.ended_at if self.ended_at is not None else now
        brut = fin - self.started_at
        en_cours = (fin - self.paused_at) if self.paused_at is not None else 0.0
        return max(0.0, brut - self.paused_s - max(0.0, en_cours))


@dataclass(frozen=True, slots=True)
class LootRow:
    """Un drop enregistré."""

    item_id: int
    qty: int
    at: float
    sid: int = 0


class SessionStore:
    """Accès à la base des sessions."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or paths.database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # `check_same_thread=False` plus un verrou à nous, et pas l'un sans
        # l'autre. SQLite lie sa connexion au fil qui l'a créée, or le serveur
        # de l'interface traite chaque requête dans un fil différent : sans
        # cette option, toute requête HTTP échouerait. Mais lever la garde sans
        # sérialiser les accès échangerait une erreur franche contre une
        # corruption silencieuse, ce qui serait bien pire sur un historique de
        # farm.
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        # Sans cette option, SQLite ignore silencieusement les clés étrangères :
        # supprimer une session laisserait son butin orphelin pour toujours.
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    # -- cycle de vie ----------------------------------------------------

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> SessionStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock, self._connection:
            yield self._connection

    @contextmanager
    def _reading(self) -> Iterator[sqlite3.Connection]:
        """Lecture sérialisée. Les lectures aussi doivent passer par le verrou :
        une lecture pendant une écriture d'un autre fil rendrait une vue à
        moitié écrite."""
        with self._lock:
            yield self._connection

    def _migrate(self) -> None:
        """Crée le schéma, ou le fait évoluer depuis une version antérieure.

        Une base plus RÉCENTE que le code fait échouer volontairement : ouvrir
        en écriture une base écrite par une version future reviendrait à
        corrompre des données qu'on ne sait pas relire.
        """
        with self._transaction() as connection:
            connection.executescript(_SCHEMA)
            ligne = connection.execute("SELECT version FROM schema_version").fetchone()
            if ligne is None:
                connection.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,)
                )
                return
            version = int(ligne["version"])
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"base en version {version}, ce logiciel n'en connaît que "
                    f"{SCHEMA_VERSION} : installer une version plus récente de Butin"
                )
            # Une migration par palier, jamais en sautant des versions.
            if version < 2:
                self._vers_v2(connection)
            connection.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))

    @staticmethod
    def _vers_v2(connection: sqlite3.Connection) -> None:
        """v1 -> v2 : la mise en pause.

        `CREATE TABLE IF NOT EXISTS` ne touche pas une table déjà là : une base
        d'avant garde donc ses six colonnes, et il faut ajouter les deux
        nouvelles à la main. Sans ça, l'historique de farm de quelqu'un
        deviendrait illisible d'un coup après une mise à jour, ce qui est la
        perte qu'on ne pardonne pas à un outil dont le seul rôle est de compter.

        Les deux valeurs par défaut disent la vérité sur les anciennes sessions :
        aucune n'a jamais été mise en pause, donc zéro et NULL.
        """
        colonnes = {
            str(ligne["name"]) for ligne in connection.execute("PRAGMA table_info(sessions)")
        }
        if "paused_s" not in colonnes:
            connection.execute("ALTER TABLE sessions ADD COLUMN paused_s REAL NOT NULL DEFAULT 0")
        if "paused_at" not in colonnes:
            connection.execute("ALTER TABLE sessions ADD COLUMN paused_at REAL")

    # -- écriture --------------------------------------------------------

    def start_session(self, *, started_at: float, spot: str = "", region: str = "eu") -> Session:
        with self._transaction() as connection:
            curseur = connection.execute(
                "INSERT INTO sessions (spot, region, started_at) VALUES (?, ?, ?)",
                (spot, region, started_at),
            )
        return Session(
            id=int(curseur.lastrowid or 0),
            spot=spot,
            region=region,
            started_at=started_at,
        )

    def end_session(self, session_id: int, *, ended_at: float) -> None:
        """Ferme une session, en refermant d'abord une pause restée ouverte.

        ⚠️ L'ordre compte. Arrêter depuis l'état en pause laisserait `paused_at`
        posé, et la durée continuerait d'en soustraire le temps écoulé **après**
        la fin de la session : elle rétrécirait toute seule, pour toujours, dans
        l'historique.
        """
        with self._transaction() as connection:
            self._fermer_la_pause(connection, session_id, at=ended_at)
            connection.execute(
                "UPDATE sessions SET ended_at = ? WHERE id = ? AND ended_at IS NULL",
                (ended_at, session_id),
            )

    def pause_session(self, session_id: int, *, at: float) -> None:
        """Marque le début d'une pause. Sans effet si la session en est déjà à une.

        `paused_at IS NULL` dans la condition : deux clics sur Pause, ou deux
        requêtes simultanées, décaleraient sinon le début de la pause et
        rendraient du temps de farm invisible.
        """
        with self._transaction() as connection:
            connection.execute(
                "UPDATE sessions SET paused_at = ? "
                "WHERE id = ? AND ended_at IS NULL AND paused_at IS NULL",
                (at, session_id),
            )

    def resume_session(self, session_id: int, *, at: float) -> None:
        """Referme la pause en cours et l'ajoute au temps déjà mis de côté."""
        with self._transaction() as connection:
            self._fermer_la_pause(connection, session_id, at=at)

    @staticmethod
    def _fermer_la_pause(connection: sqlite3.Connection, session_id: int, *, at: float) -> None:
        """Cumule la pause en cours dans `paused_s` et efface `paused_at`.

        `MAX(0, ...)` sur l'écart : une horloge qui recule, ce que fait celle du
        système à un changement d'heure, rendrait sinon `paused_s` négatif et
        allongerait la durée de farm au lieu de la raccourcir.
        """
        connection.execute(
            "UPDATE sessions "
            "SET paused_s = paused_s + MAX(0, ? - paused_at), paused_at = NULL "
            "WHERE id = ? AND paused_at IS NOT NULL",
            (at, session_id),
        )

    def add_loot(self, session_id: int, rows: Iterable[LootRow]) -> int:
        """Enregistre des drops. Renvoie le nombre de lignes écrites."""
        valeurs = [(session_id, r.item_id, r.sid, r.qty, r.at) for r in rows]
        if not valeurs:
            return 0
        with self._transaction() as connection:
            connection.executemany(
                "INSERT INTO loot (session_id, item_id, sid, qty, at) VALUES (?, ?, ?, ?, ?)",
                valeurs,
            )
        return len(valeurs)

    def set_spot(self, session_id: int, spot: str) -> None:
        """Nomme le spot d'une session, si elle n'en a pas déjà un.

        « Si elle n'en a pas déjà un » est la partie qui compte : une détection
        automatique ne doit jamais écraser un nom saisi à la main. L'utilisateur
        qui a pris la peine de nommer sa session en sait plus que nous.
        """
        with self._transaction() as connection:
            connection.execute(
                "UPDATE sessions SET spot = ? WHERE id = ? AND spot = ''",
                (spot, session_id),
            )

    def add_silver(self, session_id: int, amount: int) -> None:
        """Ajoute du silver ramassé directement.

        Additionné plutôt qu'écrasé : il tombe par petits montants tout au long
        d'une session, écraser ne garderait que le dernier.
        """
        with self._transaction() as connection:
            connection.execute(
                "UPDATE sessions SET silver_direct = silver_direct + ? WHERE id = ?",
                (amount, session_id),
            )

    # -- lecture ---------------------------------------------------------

    def get_session(self, session_id: int) -> Session | None:
        with self._reading() as connection:
            ligne = connection.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return _to_session(ligne) if ligne else None

    def sessions(self, *, limit: int = 50) -> list[Session]:
        """Sessions de la plus récente à la plus ancienne."""
        with self._reading() as connection:
            lignes = connection.execute(
                "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_to_session(ligne) for ligne in lignes]

    def quantities(self, session_id: int) -> dict[tuple[int, int], int]:
        """Quantités cumulées par (identifiant, niveau d'amélioration).

        Cumulées en SQL et non en Python : une session de plusieurs heures
        contient des milliers de lignes, et c'est exactement ce qu'une base sait
        faire mieux que nous.
        """
        with self._reading() as connection:
            lignes = connection.execute(
                "SELECT item_id, sid, SUM(qty) AS total FROM loot "
                "WHERE session_id = ? GROUP BY item_id, sid",
                (session_id,),
            ).fetchall()
        return {(int(ligne["item_id"]), int(ligne["sid"])): int(ligne["total"]) for ligne in lignes}

    def recent_loot(self, session_id: int, *, limit: int = 40) -> list[LootRow]:
        """Les derniers drops enregistrés, du plus récent au plus ancien.

        Sert au fil qui s'écrit pendant qu'on farme. Volontairement distinct de
        `quantities`, qui cumule : un joueur veut voir **ce qui vient de
        tomber**, et un total qui grandit ne le lui montre pas. Les deux
        répondent à des questions différentes et coexistent à l'écran.

        Le tri est fait en SQL et borné : une session de plusieurs heures
        contient des milliers de lignes, et la fenêtre n'en montre qu'une
        vingtaine. Tout rapatrier pour en jeter 99 % serait payé à chaque
        rafraîchissement, c'est-à-dire chaque seconde.
        """
        with self._reading() as connection:
            lignes = connection.execute(
                "SELECT item_id, sid, qty, at FROM loot WHERE session_id = ? "
                "ORDER BY at DESC, id DESC LIMIT ?",
                (session_id, max(1, limit)),
            ).fetchall()
        return [
            LootRow(
                item_id=int(ligne["item_id"]),
                qty=int(ligne["qty"]),
                at=float(ligne["at"]),
                sid=int(ligne["sid"]),
            )
            for ligne in lignes
        ]

    def loot_count(self, session_id: int) -> int:
        with self._reading() as connection:
            ligne = connection.execute(
                "SELECT COALESCE(SUM(qty), 0) AS total FROM loot WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return int(ligne["total"])


def _to_session(ligne: sqlite3.Row) -> Session:
    return Session(
        id=int(ligne["id"]),
        spot=str(ligne["spot"]),
        region=str(ligne["region"]),
        started_at=float(ligne["started_at"]),
        ended_at=float(ligne["ended_at"]) if ligne["ended_at"] is not None else None,
        silver_direct=int(ligne["silver_direct"]),
        paused_s=float(ligne["paused_s"]),
        paused_at=float(ligne["paused_at"]) if ligne["paused_at"] is not None else None,
    )
