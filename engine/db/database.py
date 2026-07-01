"""Astromind Praxis 数据库初始化（独立 DB）.

DB 路径: ~/.astromind-praxis/astromind_praxis.db
与 meta-learn 的 ~/.meta-learning/meta_learning.db 完全隔离，互不影响。
"""

import json
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

DB_DIR = Path.home() / ".astromind-praxis"
DB_PATH = DB_DIR / "astromind_praxis.db"


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
    """Initialize DB with all required tables."""
    ensure_db_dir()
    if not DB_PATH.exists():
        DB_PATH.touch()

    db = Database()

    existing = {
        r["name"]
        for r in db.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }

    # ── Users ──
    if "users" not in existing:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                name         TEXT    NOT NULL UNIQUE,
                display_name TEXT    NOT NULL DEFAULT '',
                config       TEXT    NOT NULL DEFAULT '{}',
                created_at   TEXT    NOT NULL,
                updated_at   TEXT    NOT NULL
            )
        """)

    # ── Learning Tracks ──
    if "tracks" not in existing:
        db.execute("""
            CREATE TABLE IF NOT EXISTS tracks (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name            TEXT    NOT NULL,
                target_type     TEXT    NOT NULL DEFAULT 'interest'
                    CHECK (target_type IN ('exam', 'applied', 'interest')),
                status          TEXT    NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'paused', 'completed', 'archived')),
                priority        INTEGER NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
                level           INTEGER DEFAULT 1 CHECK (level BETWEEN 1 AND 5),
                created_at      TEXT    NOT NULL,
                updated_at      TEXT    NOT NULL
            )
        """)
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_tracks_user_status ON tracks(user_id, status)"
        )

    # ── Knowledge Nodes ──
    if "knowledge_nodes" not in existing:
        db.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_nodes (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                track_id      INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
                name          TEXT    NOT NULL,
                description   TEXT    NOT NULL DEFAULT '',
                node_type     TEXT    NOT NULL DEFAULT 'concept'
                    CHECK (node_type IN ('concept','fact','principle','procedure','framework','case')),
                importance    INTEGER NOT NULL DEFAULT 3 CHECK (importance BETWEEN 1 AND 5),
                complexity    INTEGER DEFAULT 3 CHECK (complexity BETWEEN 1 AND 5),
                node_level    TEXT    DEFAULT 'concept',
                status        TEXT    NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','active','mastered','archived')),
                ef            REAL    NOT NULL DEFAULT 2.5 CHECK (ef >= 1.3),
                interval      INTEGER NOT NULL DEFAULT 0 CHECK (interval >= 0),
                repetitions   INTEGER NOT NULL DEFAULT 0 CHECK (repetitions >= 0),
                next_review   TEXT,
                created_at    TEXT    NOT NULL,
                updated_at    TEXT    NOT NULL
            )
        """)
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_nodes_track_status ON knowledge_nodes(track_id, status)"
        )

    # ── Node Dependencies ──
    if "node_dependencies" not in existing:
        db.execute("""
            CREATE TABLE IF NOT EXISTS node_dependencies (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id       INTEGER NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
                depends_on_id INTEGER NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
                relation_type TEXT    NOT NULL DEFAULT 'prerequisite'
                    CHECK (relation_type IN ('prerequisite','related','part_of','extends','example_of')),
                UNIQUE(node_id, depends_on_id)
            )
        """)

    # ── Workflow Context (教学会话状态) ──
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

    # ── Interaction Log ──
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

    # ── Misconceptions ──
    if "misconceptions" not in existing:
        db.execute("""
            CREATE TABLE IF NOT EXISTS misconceptions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       TEXT    NOT NULL,
                node_id       INTEGER NOT NULL,
                misconception TEXT    NOT NULL,
                correction    TEXT    NOT NULL DEFAULT '',
                created_at    TEXT    NOT NULL
            )
        """)

    db.close()
    logger.info("Database initialized at %s", DB_PATH)
    return True
