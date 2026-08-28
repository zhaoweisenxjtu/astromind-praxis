"""Astromind Praxis v0.2.2 Database initialization.

Unified database at ~/.astromind-praxis/astromind_praxis.db
Schema v7: 8 基表 + FTS（17 表收敛）。
Env override: ASTROMIND_DB_PATH (测试隔离用).
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_DIR = Path.home() / ".astromind-praxis"
DB_PATH = Path(os.environ.get("ASTROMIND_DB_PATH", str(DB_DIR / "astromind_praxis.db")))
SCHEMA_PATH = Path(__file__).parent / "schema_v7.sql"


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


def _has_teaching_interactions(conn: sqlite3.Connection) -> bool:
    """Detect v6 DB（有 teaching_interactions 表）——需要 v6->v7 迁移."""
    return _table_exists(conn, "teaching_interactions")


def _create_missing_tables(conn: sqlite3.Connection, schema_path: Path):
    """Create any tables from schema_v7.sql that don't exist yet."""
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


# ?? Migration: v6 -> v7（完整重建，数据行级迁移）??

def _migrate_v6_to_v7(conn: sqlite3.Connection):
    """v6 DB 升级 v7：重建 knowledge_nodes / tracks，合并交互表，删除废弃表。

    数据保留：
      - knowledge_nodes: 删 node_type + 9 个 NUSAP 质量字段（数据本就全默认值）
      - tracks: 删 workflow_context JSON 列
      - teaching_interactions(type=review_session) -> interaction_log（补 interaction_type 标签）
      - misconceptions: 删 interaction_id（FK 目标表删除，置 NULL 语义即丢弃）
    废弃表（无生产写入）：DROP。
    """
    logger.info("Detected v6 DB, migrating to v7 schema")
    # 迁移期间关闭 FK（重建父表时避免约束检查失败；迁移结束后恢复）
    conn.execute("PRAGMA foreign_keys=OFF")
    _create_missing_tables(conn, SCHEMA_PATH)

    # 1. knowledge_nodes: 重建（保留数据列，丢弃质量字段）
    if _column_exists(conn, "knowledge_nodes", "node_type"):
        conn.executescript("""
            CREATE TABLE knowledge_nodes_v7 (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                track_id      INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
                parent_id     INTEGER REFERENCES knowledge_nodes(id) ON DELETE SET NULL,
                name          TEXT    NOT NULL,
                description   TEXT    NOT NULL DEFAULT '',
                importance    INTEGER NOT NULL DEFAULT 3 CHECK (importance BETWEEN 1 AND 5),
                current_level INTEGER NOT NULL DEFAULT 1 CHECK (current_level BETWEEN 1 AND 5),
                status        TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'pending', 'mastered', 'archived')),
                ef            REAL    NOT NULL DEFAULT 2.5 CHECK (ef >= 1.3),
                interval      INTEGER NOT NULL DEFAULT 0 CHECK (interval >= 0),
                repetitions   INTEGER NOT NULL DEFAULT 0 CHECK (repetitions >= 0),
                next_review   TEXT,
                content         TEXT    NOT NULL DEFAULT '',
                content_format  TEXT    NOT NULL DEFAULT 'markdown',
                source_url      TEXT    NOT NULL DEFAULT '',
                source_title    TEXT    NOT NULL DEFAULT '',
                tags            TEXT    NOT NULL DEFAULT '[]',
                cached_at       TEXT,
                created_at      TEXT    NOT NULL DEFAULT (date('now')),
                updated_at      TEXT    NOT NULL DEFAULT (date('now'))
            );
            INSERT INTO knowledge_nodes_v7
              (id, track_id, parent_id, name, description, importance, current_level,
               status, ef, interval, repetitions, next_review, content, content_format,
               source_url, source_title, tags, cached_at, created_at, updated_at)
            SELECT id, track_id, parent_id, name, description, importance, current_level,
                   status, ef, interval, repetitions, next_review, content, content_format,
                   source_url, source_title, tags, cached_at, created_at, updated_at
            FROM knowledge_nodes;
            DROP TABLE knowledge_nodes;
            ALTER TABLE knowledge_nodes_v7 RENAME TO knowledge_nodes;
            CREATE INDEX IF NOT EXISTS idx_nodes_track_status ON knowledge_nodes(track_id, status);
            CREATE INDEX IF NOT EXISTS idx_nodes_next_review ON knowledge_nodes(next_review);
            CREATE INDEX IF NOT EXISTS idx_nodes_type ON knowledge_nodes(status);
        """)

    # 2. tracks: 删 workflow_context 列
    if _column_exists(conn, "tracks", "workflow_context"):
        conn.executescript("""
            CREATE TABLE tracks_v7 (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name            TEXT    NOT NULL,
                target_type     TEXT    NOT NULL CHECK (target_type IN ('exam', 'applied', 'interest')),
                status          TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'completed', 'archived')),
                priority        INTEGER NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
                current_state   TEXT    NOT NULL DEFAULT 'init' CHECK (current_state IN ('init', 'diagnosis', 'teaching', 'assessment', 'practice', 'completed')),
                created_at      TEXT    NOT NULL DEFAULT (date('now')),
                updated_at      TEXT    NOT NULL DEFAULT (date('now'))
            );
            INSERT INTO tracks_v7 (id, user_id, name, target_type, status, priority, current_state, created_at, updated_at)
            SELECT id, user_id, name, target_type, status, priority, current_state, created_at, updated_at
            FROM tracks;
            DROP TABLE tracks;
            ALTER TABLE tracks_v7 RENAME TO tracks;
            CREATE INDEX IF NOT EXISTS idx_tracks_user_status ON tracks(user_id, status);
            CREATE INDEX IF NOT EXISTS idx_tracks_user_priority ON tracks(user_id, priority);
        """)

    # 2b. node_dependencies: 重建（relation_type 枚举 8 值收窄为 3 值）
    conn.executescript("""
        CREATE TABLE node_dependencies_v7 (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id       INTEGER NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
            depends_on_id INTEGER NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
            relation_type TEXT    NOT NULL DEFAULT 'prerequisite' CHECK (relation_type IN (
                                'prerequisite', 'related', 'part_of'
                            )),
            UNIQUE(node_id, depends_on_id)
        );
        INSERT INTO node_dependencies_v7 (id, node_id, depends_on_id, relation_type)
        SELECT id, node_id, depends_on_id,
               CASE WHEN relation_type IN ('prerequisite','related','part_of') THEN relation_type
                    ELSE 'related' END
        FROM node_dependencies;
        DROP TABLE node_dependencies;
        ALTER TABLE node_dependencies_v7 RENAME TO node_dependencies;
        CREATE INDEX IF NOT EXISTS idx_deps_node ON node_dependencies(node_id);
        CREATE INDEX IF NOT EXISTS idx_deps_depends ON node_dependencies(depends_on_id);
    """)

    # 3. interaction_log: 增 interaction_type 列（v7 新表已含；若为旧表则 ALTER）
    if not _column_exists(conn, "interaction_log", "interaction_type"):
        conn.execute(
            "ALTER TABLE interaction_log ADD COLUMN interaction_type TEXT NOT NULL DEFAULT 'deep_teaching'"
        )

    # 4. teaching_interactions -> interaction_log（review_session 记录回填）
    if _has_teaching_interactions(conn):
        conn.executescript("""
            INSERT INTO interaction_log (user_id, track_id, node_id, question, answer,
                                         is_correct, understanding_level, fake_signals,
                                         interaction_type, created_at)
            SELECT user_id, track_id, node_id, '', '', 0, level_after, '[]',
                   interaction_type, created_at
            FROM teaching_interactions;
            DROP TABLE teaching_interactions;
        """)

    # 5. misconceptions: 删 interaction_id 列
    if _column_exists(conn, "misconceptions", "interaction_id"):
        conn.executescript("""
            CREATE TABLE misconceptions_v7 (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL,
                node_id         INTEGER NOT NULL,
                misconception   TEXT    NOT NULL,
                correction      TEXT    NOT NULL DEFAULT '',
                category        TEXT,
                is_resolved     INTEGER NOT NULL DEFAULT 0,
                encounter_count INTEGER NOT NULL DEFAULT 1,
                created_at      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
                resolved_at     TEXT
            );
            INSERT INTO misconceptions_v7 (id, user_id, node_id, misconception, correction,
                                           category, is_resolved, encounter_count, created_at, resolved_at)
            SELECT id, user_id, node_id, misconception, correction, category,
                   is_resolved, encounter_count, created_at, resolved_at
            FROM misconceptions;
            DROP TABLE misconceptions;
            ALTER TABLE misconceptions_v7 RENAME TO misconceptions;
            CREATE INDEX IF NOT EXISTS idx_mc_user_node ON misconceptions(user_id, node_id);
            CREATE INDEX IF NOT EXISTS idx_mc_resolved ON misconceptions(user_id, is_resolved);
        """)

    # 6. 废弃表清理（node_dependencies 是 v7 保留表，不在此列）
    for tbl in ("learning_journal", "assessment_log", "weakness_patterns",
                "knowledge_graph_edges", "quality_audit_log", "knowledge_sources",
                "knowledge_coverage"):
        if _table_exists(conn, tbl):
            conn.execute(f"DROP TABLE IF EXISTS {tbl}")

    # 7. FTS 重建（knowledge_nodes 重建后触发器丢失，必须重建）
    conn.execute("DROP TABLE IF EXISTS knowledge_fts")
    conn.commit()
    _init_fts(conn)

    conn.commit()
    conn.execute("PRAGMA foreign_keys=ON")
    logger.info("Migrated v6 -> v7")


# ?? Main init ??


def init_db(force: bool = False):
    """Initialize or migrate database to v7 schema."""
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
            conn.commit()
            logger.info("Fresh database initialized at %s (v7 schema)", DB_PATH)
        elif _has_teaching_interactions(conn):
            # v6 DB -> v7 迁移
            _migrate_v6_to_v7(conn)
        else:
            # 已是 v7 或部分表缺失，补齐
            _create_missing_tables(conn, SCHEMA_PATH)
            _init_fts(conn)
            conn.commit()
            logger.info("Ensured v7 schema")

    finally:
        conn.close()

    return True
