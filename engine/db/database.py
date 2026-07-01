"""Astromind 数据库初始化（复用 meta-learning db + v5 迁移）."""

import json
import sqlite3
from pathlib import Path

DB_DIR = Path.home() / ".meta-learning"
DB_PATH = DB_DIR / "meta_learning.db"


def get_db_path() -> str:
    return str(DB_PATH)


def ensure_db_dir():
    DB_DIR.mkdir(parents=True, exist_ok=True)


class Database:
    """Thin wrapper around sqlite3 with convenience methods."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or str(DB_PATH)
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            ensure_db_dir()
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
        return self._conn

    def execute(self, sql: str, params: list = None) -> int | None:
        cur = self.conn.execute(sql, params or [])
        self.conn.commit()
        return cur.lastrowid

    def fetch_one(self, sql: str, params: list = None) -> sqlite3.Row | None:
        return self.conn.execute(sql, params or []).fetchone()

    def fetch_all(self, sql: str, params: list = None) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params or []).fetchall()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def init_db(force: bool = False):
    """Initialize DB and run v5 migration."""
    ensure_db_dir()
    if not DB_PATH.exists():
        # Create empty file
        DB_PATH.touch()

    db = Database()

    # Check if v5 tables exist
    existing = {
        r["name"]
        for r in db.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }

    if "workflow_context" not in existing:
        db.execute("""
            CREATE TABLE IF NOT EXISTS workflow_context (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         TEXT    NOT NULL,
                track_id        INTEGER NOT NULL,
                topic           TEXT    NOT NULL,
                status          TEXT    NOT NULL DEFAULT 'diagnosed'
                    CHECK (status IN ('diagnosed','teaching','teaching_complete',
                                      'assessing','completed','abandoned')),
                level           INTEGER DEFAULT 1 CHECK (level BETWEEN 1 AND 5),
                diagnosis       TEXT    NOT NULL DEFAULT '{}',
                current_node    INTEGER,
                completed_nodes TEXT    NOT NULL DEFAULT '[]',
                state_data      TEXT    NOT NULL DEFAULT '{}',
                created_at      TEXT    NOT NULL,
                updated_at      TEXT    NOT NULL
            )
        """)
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_wfc_user ON workflow_context(user_id)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_wfc_track ON workflow_context(track_id)"
        )

    if "interaction_log" not in existing:
        db.execute("""
            CREATE TABLE IF NOT EXISTS interaction_log (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id             TEXT    NOT NULL,
                track_id            INTEGER NOT NULL,
                node_id             INTEGER NOT NULL,
                question            TEXT    NOT NULL,
                answer              TEXT    NOT NULL DEFAULT '',
                is_correct          INTEGER NOT NULL DEFAULT 0,
                understanding_level INTEGER DEFAULT 1 CHECK (understanding_level BETWEEN 1 AND 5),
                fake_signals        TEXT    NOT NULL DEFAULT '[]',
                quality             INTEGER DEFAULT 0 CHECK (quality BETWEEN 0 AND 5),
                created_at          TEXT    NOT NULL
            )
        """)
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_il_user_track ON interaction_log(user_id, track_id)"
        )

    if "knowledge_edges" not in existing:
        db.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_edges (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                track_id        INTEGER NOT NULL,
                source_node_id  INTEGER NOT NULL,
                target_node_id  INTEGER NOT NULL,
                relation_type   TEXT    NOT NULL DEFAULT 'related'
                    CHECK (relation_type IN ('prerequisite','related','part_of','extends','example_of')),
                created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
                UNIQUE(track_id, source_node_id, target_node_id)
            )
        """)

    # Add astromind-praxis-specific columns to knowledge_nodes
    try:
        db.execute("ALTER TABLE knowledge_nodes ADD COLUMN complexity INTEGER DEFAULT 3")
    except sqlite3.OperationalError:
        pass  # already exists
    try:
        db.execute("ALTER TABLE knowledge_nodes ADD COLUMN node_level TEXT DEFAULT 'concept'")
    except sqlite3.OperationalError:
        pass

    db.close()
    return True
