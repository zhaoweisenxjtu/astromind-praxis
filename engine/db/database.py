"""Astromind Praxis v0.1.2 Database initialization.

Unified database at ~/.astromind-praxis/astromind_praxis.db
Merges meta-learning (16 tables) + astromind workflow_context + interaction_log.
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_DIR = Path.home() / ".astromind-praxis"
DB_PATH = DB_DIR / "astromind_praxis.db"
SCHEMA_PATH = Path(__file__).parent / "schema_v6.sql"


# ?? Path helpers ??

def get_db_path() -> str:
    return str(DB_PATH)


def ensure_db_dir():
    DB_DIR.mkdir(parents=True, exist_ok=True)


# ?? Row utilities (compatible with meta-learning DAOs) ??

def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return dict(row)


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rows]


# ?? Connection (compatible with meta-learning DAO pattern) ??

def get_connection() -> sqlite3.Connection:
    """Get a new SQLite connection with WAL mode and foreign keys."""
    ensure_db_dir()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


# ?? Database class (astromind pattern, used by TeachingOrchestrator) ??

class Database:
    """Thin wrapper around sqlite3 with convenience methods."""

    def __init__(self, db_path: Optional[str] = None):
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


# ?? Schema helpers ??

def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(c["name"] == column for c in cols)


def _has_workflow_context(conn: sqlite3.Connection) -> bool:
    """Detect if this is an astromind v0.1.1 DB (has workflow_context table)."""
    return _table_exists(conn, "workflow_context")


def _has_teaching_interactions(conn: sqlite3.Connection) -> bool:
    """Detect if this is a meta-learning DB (has teaching_interactions)."""
    return _table_exists(conn, "teaching_interactions")


# ?? Migration: add columns to existing tables ??

_CONTENT_COLUMNS = [
    ("content", "TEXT NOT NULL DEFAULT ''"),
    ("content_format", "TEXT NOT NULL DEFAULT 'markdown'"),
    ("source_url", "TEXT NOT NULL DEFAULT ''"),
    ("source_title", "TEXT NOT NULL DEFAULT ''"),
    ("quality_score", "INTEGER DEFAULT 0"),
    ("cached_at", "TEXT"),
    ("tags", "TEXT NOT NULL DEFAULT '[]'"),
]

_QUALITY_COLUMNS = [
    ("node_type", "TEXT NOT NULL DEFAULT 'concept'"),
    ("theory_level", "INTEGER DEFAULT 0"),
    ("data_level", "INTEGER DEFAULT 0"),
    ("method_level", "INTEGER DEFAULT 0"),
    ("source_reliability", "INTEGER DEFAULT 0"),
    ("freshness_date", "TEXT"),
    ("completeness", "INTEGER DEFAULT 0"),
    ("consistency", "INTEGER DEFAULT 0"),
]


def _migrate_knowledge_nodes(conn: sqlite3.Connection):
    """Add content + quality columns to knowledge_nodes if missing."""
    existing = {c["name"] for c in conn.execute("PRAGMA table_info(knowledge_nodes)").fetchall()}
    for col_name, col_def in _CONTENT_COLUMNS + _QUALITY_COLUMNS:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE knowledge_nodes ADD COLUMN {col_name} {col_def}")


def _migrate_assessment_log(conn: sqlite3.Connection):
    """Add quality columns to assessment_log if missing."""
    existing = {c["name"] for c in conn.execute("PRAGMA table_info(assessment_log)").fetchall()}
    for col_name, col_def in [
        ("quality_before", "INTEGER DEFAULT 0"),
        ("quality_after", "INTEGER DEFAULT 0"),
        ("quality_notes", "TEXT NOT NULL DEFAULT ''"),
    ]:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE assessment_log ADD COLUMN {col_name} {col_def}")


def _create_missing_tables(conn: sqlite3.Connection, schema_path: Path):
    """Create any tables from schema_v6.sql that don't exist yet."""
    schema_text = schema_path.read_text(encoding="utf-8")
    import re
    for match in re.finditer(r"CREATE (?:VIRTUAL )?TABLE IF NOT EXISTS (\w+)", schema_text):
        name = match.group(1)
        if not _table_exists(conn, name):
            # Find and execute the full DDL for this table
            pos = match.start()
            end = schema_text.find(");\n", pos)
            if end != -1:
                ddl = schema_text[pos:end + 3]
                conn.executescript(ddl)


def _init_fts(conn: sqlite3.Connection):
    """Create FTS5 virtual table + triggers if they don't exist."""
    if _table_exists(conn, "knowledge_fts"):
        return
    if not _column_exists(conn, "knowledge_nodes", "content"):
        return
    conn.executescript("""
        CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
            name, content, tags, source_title,
            content='knowledge_nodes',
            content_rowid='id',
            tokenize='unicode61'
        );
        CREATE TRIGGER IF NOT EXISTS knowledge_fts_insert AFTER INSERT ON knowledge_nodes BEGIN
            INSERT INTO knowledge_fts(rowid, name, content, tags, source_title)
            VALUES (new.id, new.name, new.content, new.tags, new.source_title);
        END;
        CREATE TRIGGER IF NOT EXISTS knowledge_fts_delete AFTER DELETE ON knowledge_nodes BEGIN
            INSERT INTO knowledge_fts(knowledge_fts, rowid, name, content, tags, source_title)
            VALUES ('delete', old.id, old.name, old.content, old.tags, old.source_title);
        END;
        CREATE TRIGGER IF NOT EXISTS knowledge_fts_update AFTER UPDATE ON knowledge_nodes BEGIN
            INSERT INTO knowledge_fts(knowledge_fts, rowid, name, content, tags, source_title)
            VALUES ('delete', old.id, old.name, old.content, old.tags, old.source_title);
            INSERT INTO knowledge_fts(rowid, name, content, tags, source_title)
            VALUES (new.id, new.name, new.content, new.tags, new.source_title);
        END;
    """)


# ?? Main init ??

_SCHEMA_V6_1_PATH = Path(__file__).parent / "schema_v6_1.sql"


def _ensure_v6_1_tables(conn: sqlite3.Connection):
    """Create author-knowledge v6.1 tables (articles, knowledge_atoms, etc.)."""
    if _table_exists(conn, "author_profiles"):
        return
    schema = _SCHEMA_V6_1_PATH.read_text(encoding="utf-8")
    conn.executescript(schema)
    conn.commit()
    logger.info("Created v6.1 author-knowledge tables")


def init_db(force: bool = False):
    """Initialize or migrate database to v6 schema."""
    ensure_db_dir()
    if not DB_PATH.exists():
        DB_PATH.touch()

    conn = get_connection()
    try:
        existing = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        if not existing:
            # Fresh init: run full schema
            schema = SCHEMA_PATH.read_text(encoding="utf-8")
            conn.executescript(schema)
            # Also create v6.1 author tables
            _ensure_v6_1_tables(conn)
            conn.commit()
            logger.info("Fresh database initialized at %s (v6 + v6.1 schema)", DB_PATH)
        else:
            # Migration path
            old_astro = _has_workflow_context(conn)
            old_meta = _has_teaching_interactions(conn)

            if old_astro:
                logger.info("Detected astromind v0.1.1 DB, upgrading to v6")
                _create_missing_tables(conn, SCHEMA_PATH)
                _migrate_knowledge_nodes(conn)
                _migrate_assessment_log(conn)
                _init_fts(conn)
                conn.commit()
                logger.info("Upgraded from astromind v0.1.1 to v6")

            if old_meta and not old_astro:
                logger.info("Detected meta-learning DB, upgrading to v6")
                _create_missing_tables(conn, SCHEMA_PATH)
                _init_fts(conn)
                conn.commit()
                logger.info("Upgraded from meta-learning to v6")

            if not old_astro and not old_meta:
                # Some other schema version, just ensure all tables exist
                _create_missing_tables(conn, SCHEMA_PATH)
                _migrate_knowledge_nodes(conn)
                _migrate_assessment_log(conn)
                _init_fts(conn)
                conn.commit()
                logger.info("Migrated unknown schema to v6")

            # Always ensure v6.1 tables exist (idempotent)
            _ensure_v6_1_tables(conn)

    finally:
        conn.close()

    return True
