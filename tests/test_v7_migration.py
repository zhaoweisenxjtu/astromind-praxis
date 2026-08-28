"""Schema v6 -> v7 迁移测试（v0.2.2）.

构造一个含 v6 全部 17 表的 fixture DB（含少量数据），跑 init_db 迁移，
断言：9 张表（8 基表 + FTS）、knowledge_nodes 数据行数一致、
teaching_interactions 的 review_session 记录并入 interaction_log、
废弃表全部删除。
"""

import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

V7_TABLES = {"users", "tracks", "knowledge_nodes", "node_dependencies",
             "review_history", "misconceptions", "workflow_context",
             "interaction_log", "knowledge_fts"}
V6_ONLY_TABLES = {"assessment_log", "learning_journal", "weakness_patterns",
                  "knowledge_graph_edges", "quality_audit_log",
                  "knowledge_sources", "knowledge_coverage",
                  "teaching_interactions"}


def _make_v6_db(path: Path):
    """构造 v6 fixture：建 v6 核心表 + 少量数据。"""
    conn = sqlite3.connect(str(path))
    try:
        # 用户 / 轨道 / 节点
        conn.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT UNIQUE,
                                display_name TEXT DEFAULT '', config TEXT DEFAULT '{}',
                                created_at TEXT, updated_at TEXT);
            CREATE TABLE tracks (id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT,
                                target_type TEXT, status TEXT, priority INTEGER,
                                current_state TEXT, workflow_context TEXT DEFAULT '{}',
                                created_at TEXT, updated_at TEXT);
            CREATE TABLE knowledge_nodes (
                id INTEGER PRIMARY KEY, track_id INTEGER, parent_id INTEGER,
                name TEXT, description TEXT DEFAULT '', importance INTEGER DEFAULT 3,
                current_level INTEGER DEFAULT 1, status TEXT DEFAULT 'active',
                ef REAL DEFAULT 2.5, interval INTEGER DEFAULT 0,
                repetitions INTEGER DEFAULT 0, next_review TEXT,
                content TEXT DEFAULT '', content_format TEXT DEFAULT 'markdown',
                source_url TEXT DEFAULT '', source_title TEXT DEFAULT '',
                quality_score INTEGER DEFAULT 0, tags TEXT DEFAULT '[]', cached_at TEXT,
                node_type TEXT DEFAULT 'concept', theory_level INTEGER DEFAULT 0,
                data_level INTEGER DEFAULT 0, method_level INTEGER DEFAULT 0,
                source_reliability INTEGER DEFAULT 0, freshness_date TEXT,
                completeness INTEGER DEFAULT 0, consistency INTEGER DEFAULT 0,
                created_at TEXT, updated_at TEXT);
            CREATE TABLE node_dependencies (
                id INTEGER PRIMARY KEY, node_id INTEGER, depends_on_id INTEGER,
                relation_type TEXT DEFAULT 'prerequisite',
                UNIQUE(node_id, depends_on_id));
            CREATE TABLE review_history (
                id INTEGER PRIMARY KEY, node_id INTEGER, quality INTEGER,
                ef_after REAL, interval_after INTEGER, reviewed_at TEXT);
            CREATE TABLE misconceptions (
                id INTEGER PRIMARY KEY, user_id INTEGER, node_id INTEGER,
                interaction_id INTEGER, misconception TEXT, correction TEXT,
                category TEXT, is_resolved INTEGER DEFAULT 0,
                encounter_count INTEGER DEFAULT 1,
                created_at TEXT, resolved_at TEXT);
            CREATE TABLE workflow_context (
                id INTEGER PRIMARY KEY, user_id INTEGER, track_id INTEGER, topic TEXT,
                status TEXT, level INTEGER, diagnosis TEXT, current_node INTEGER,
                completed_nodes TEXT DEFAULT '[]', state_data TEXT DEFAULT '{}',
                created_at TEXT, updated_at TEXT);
            CREATE TABLE interaction_log (
                id INTEGER PRIMARY KEY, user_id INTEGER, track_id INTEGER,
                node_id INTEGER, question TEXT, answer TEXT,
                is_correct INTEGER DEFAULT 0, understanding_level INTEGER DEFAULT 1,
                fake_signals TEXT DEFAULT '[]', quality INTEGER DEFAULT 0,
                created_at TEXT);
            CREATE TABLE teaching_interactions (
                id INTEGER PRIMARY KEY, session_id TEXT, user_id INTEGER, track_id INTEGER,
                node_id INTEGER, interaction_type TEXT, method_used TEXT,
                level_before INTEGER DEFAULT 1, level_after INTEGER DEFAULT 1,
                quality_score INTEGER DEFAULT 0, duration_seconds INTEGER DEFAULT 0,
                file_path TEXT DEFAULT '', created_at TEXT);
            CREATE TABLE learning_journal (
                id INTEGER PRIMARY KEY, user_id INTEGER, date TEXT,
                focus_minutes INTEGER DEFAULT 0, diffuse_minutes INTEGER DEFAULT 0,
                topics TEXT DEFAULT '[]', methods TEXT DEFAULT '[]',
                track_minutes TEXT DEFAULT '{}', highlights TEXT, struggles TEXT,
                tomorrow_plan TEXT);
            CREATE TABLE assessment_log (
                id INTEGER PRIMARY KEY, user_id INTEGER, track_id INTEGER, node_id INTEGER,
                level_before INTEGER, level_after INTEGER, methods TEXT DEFAULT '[]',
                duration_minutes INTEGER DEFAULT 0, fake_signals TEXT DEFAULT '{}',
                quality_before INTEGER DEFAULT 0, quality_after INTEGER DEFAULT 0,
                quality_notes TEXT DEFAULT '', notes TEXT DEFAULT '', created_at TEXT);
            CREATE TABLE weakness_patterns (
                id INTEGER PRIMARY KEY, user_id INTEGER, pattern_type TEXT,
                description TEXT, related_node_ids TEXT DEFAULT '[]',
                frequency INTEGER DEFAULT 1, severity INTEGER DEFAULT 1,
                last_observed_at TEXT, created_at TEXT);
            CREATE TABLE knowledge_graph_edges (
                id INTEGER PRIMARY KEY, user_id INTEGER, source_node_id INTEGER,
                target_node_id INTEGER, relation_type TEXT, description TEXT,
                confidence INTEGER DEFAULT 1, created_at TEXT,
                UNIQUE(user_id, source_node_id, target_node_id, relation_type));
            CREATE TABLE quality_audit_log (
                id INTEGER PRIMARY KEY, node_id INTEGER, audit_type TEXT,
                theory_level INTEGER, data_level INTEGER, method_level INTEGER,
                source_reliability INTEGER, completeness INTEGER, consistency INTEGER,
                quality_score INTEGER, findings TEXT DEFAULT '[]',
                recommendations TEXT DEFAULT '[]', notes TEXT DEFAULT '',
                audited_by TEXT DEFAULT 'system', created_at TEXT);
            CREATE TABLE knowledge_sources (
                id INTEGER PRIMARY KEY, node_id INTEGER, source_type TEXT,
                title TEXT, url TEXT, author TEXT, publisher TEXT,
                publish_date TEXT, access_date TEXT, reliability INTEGER DEFAULT 2,
                citation_count INTEGER DEFAULT 0, notes TEXT DEFAULT '',
                UNIQUE(node_id, url));
            CREATE TABLE knowledge_coverage (
                id INTEGER PRIMARY KEY, track_id INTEGER, domain TEXT,
                expected_nodes INTEGER DEFAULT 0, actual_nodes INTEGER DEFAULT 0,
                coverage_pct REAL DEFAULT 0.0, depth_avg REAL DEFAULT 0.0,
                last_assessed TEXT, notes TEXT DEFAULT '',
                UNIQUE(track_id, domain));
        """)
        conn.execute("INSERT INTO users (id, name, created_at, updated_at) VALUES (1, 't', 'x', 'x')")
        conn.execute(
            "INSERT INTO tracks (id, user_id, name, target_type, status, priority, "
            "current_state, workflow_context, created_at, updated_at) "
            "VALUES (1, 1, 't', 'interest', 'active', 3, 'init', '{}', 'x', 'x')"
        )
        conn.execute(
            "INSERT INTO knowledge_nodes (id, track_id, name, status, content, "
            "node_type, quality_score, theory_level, created_at, updated_at) "
            "VALUES (1, 1, '概念A', 'active', '内容', 'concept', 0, 0, 'x', 'x')"
        )
        conn.execute(
            "INSERT INTO interaction_log (id, user_id, track_id, node_id, question, "
            "answer, is_correct, understanding_level, fake_signals, created_at) "
            "VALUES (1, 1, 1, 1, 'q1', 'a1', 1, 3, '[]', 'x')"
        )
        # teaching_interactions 中 1 条 review_session（应并入 interaction_log）
        conn.execute(
            "INSERT INTO teaching_interactions (id, session_id, user_id, track_id, "
            "node_id, interaction_type, level_before, level_after, quality_score, created_at) "
            "VALUES (1, 's1', 1, 1, 1, 'review_session', 2, 3, 4, 'x')"
        )
        # 废弃表中放一条数据，验证迁移后清空
        conn.execute(
            "INSERT INTO learning_journal (id, user_id, date, focus_minutes) "
            "VALUES (1, 1, '2026-08-01', 30)"
        )
        conn.commit()
    finally:
        conn.close()


def _real_tables(conn):
    """过滤 FTS5 shadow 表（knowledge_fts_*）与 sqlite_sequence。"""
    return {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ) if not r[0].startswith("knowledge_fts_") and r[0] != "sqlite_sequence"}


def test_v6_to_v7_migration(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    _make_v6_db(db_path)

    from engine.db import database as db_database
    monkeypatch.setattr(db_database, "DB_PATH", db_path)
    db_database.init_db()

    conn = sqlite3.connect(str(db_path))
    try:
        tables = _real_tables(conn)

        # 1. 表收敛：9 张（8 基表 + FTS）
        assert tables == V7_TABLES, f"mismatch: {tables ^ V7_TABLES}"

        # 2. knowledge_nodes 数据保留 + 质量字段已删
        row = conn.execute("SELECT * FROM knowledge_nodes WHERE id = 1").fetchone()
        cols = [d[1] for d in conn.execute("PRAGMA table_info(knowledge_nodes)").fetchall()]
        assert row[cols.index("name")] == "概念A"
        assert row[cols.index("content")] == "内容"
        assert "node_type" not in cols
        assert "quality_score" not in cols
        assert "theory_level" not in cols

        # 3. tracks 的 workflow_context 列已删
        tcols = [d[1] for d in conn.execute("PRAGMA table_info(tracks)").fetchall()]
        assert "workflow_context" not in tcols

        # 4. interaction_log 吸收 review_session（原 1 条 + 迁移 1 条 = 2 条）
        cnt = conn.execute("SELECT COUNT(*) FROM interaction_log").fetchone()[0]
        assert cnt == 2
        ri = conn.execute(
            "SELECT interaction_type FROM interaction_log WHERE id = 2"
        ).fetchone()[0]
        assert ri == "review_session"

        # 5. misconceptions 的 interaction_id 列已删
        mcols = [d[1] for d in conn.execute("PRAGMA table_info(misconceptions)").fetchall()]
        assert "interaction_id" not in mcols

        # 6. FTS 重建可用
        fts = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='knowledge_fts'"
        ).fetchone()
        assert fts is not None
    finally:
        conn.close()


def test_fresh_init_is_v7(tmp_path, monkeypatch):
    db_path = tmp_path / "fresh.db"
    from engine.db import database as db_database
    monkeypatch.setattr(db_database, "DB_PATH", db_path)
    db_database.init_db()

    conn = sqlite3.connect(str(db_path))
    try:
        tables = _real_tables(conn)
        assert tables == V7_TABLES
        # 新库不含 v6 专属表
        assert not (tables & V6_ONLY_TABLES)
    finally:
        conn.close()
