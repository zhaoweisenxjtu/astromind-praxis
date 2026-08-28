#!/usr/bin/env python3
"""Astromind Praxis v6 -> v7 一次性迁移脚本（跑完即弃）.

用法:
  python scripts/migrate_v6_to_v7.py [--db <path>]

默认迁移 ~/.astromind-praxis/astromind_praxis.db。
执行前自动备份为 <db>.bak-v6；完成后打印表数量与行数核对。

v0.2.2 变更（见 D:/workdata/output/astromind-praxis-v0.3-redesign.md §5）:
  17 表 -> 9 表（8 基表 + FTS）; interaction_log 吸收 teaching_interactions;
  knowledge_nodes 砍 9 个 NUSAP 质量字段; tracks 删 workflow_context 列;
  misconceptions 删 interaction_id; node_dependencies 枚举收窄为 3 值。
"""

import os
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

V6_TABLES = {"users", "tracks", "knowledge_nodes", "node_dependencies",
             "review_history", "assessment_log", "learning_journal",
             "teaching_interactions", "misconceptions", "weakness_patterns",
             "knowledge_graph_edges", "quality_audit_log", "knowledge_sources",
             "knowledge_coverage", "workflow_context", "interaction_log",
             "knowledge_fts"}
V7_TABLES = {"users", "tracks", "knowledge_nodes", "node_dependencies",
             "review_history", "misconceptions", "workflow_context",
             "interaction_log", "knowledge_fts"}


def _count_rows(conn: sqlite3.Connection, table: str) -> int:
    try:
        return conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
    except sqlite3.Error:
        return 0


def main():
    db_path = None
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        db_path = Path(args[0])

    if db_path is None:
        default = Path.home() / ".astromind-praxis" / "astromind_praxis.db"
        db_path = default

    if not db_path.exists():
        print(f"ERROR: database not found: {db_path}")
        sys.exit(1)

    # 备份
    backup = Path(str(db_path) + ".bak-v6")
    shutil.copy2(db_path, backup)
    print(f"Backup created: {backup}")

    # 前置校验：确认是 v6（有 teaching_interactions）
    conn = sqlite3.connect(str(db_path))
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "teaching_interactions" not in tables:
            print("WARN: 'teaching_interactions' not found — DB may already be v7. Exiting.")
            sys.exit(2)
        missing = V6_TABLES - tables
        if missing:
            print(f"WARN: missing v6 tables: {sorted(missing)} (继续)")
    finally:
        conn.close()

    # 走 init_db 迁移（含 FK off / 重建 / FTS 重建）
    os.environ.setdefault("ASTROMIND_DB_PATH", str(db_path))
    from engine.db.database import init_db
    init_db()

    # 校验（过滤 FTS5 shadow 表与 sqlite_sequence）
    conn = sqlite3.connect(str(db_path))
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")
            if not r[0].startswith("knowledge_fts_") and r[0] != "sqlite_sequence"}
        extra = tables - V7_TABLES
        missing = V7_TABLES - tables
        print("Post-migration tables:", len(tables))
        for t in sorted(tables):
            print(f"  {t}: {_count_rows(conn, t)} rows")
        if extra:
            print(f"WARN: leftover tables (应已删除): {sorted(extra)}")
        if missing:
            print(f"ERROR: missing tables: {sorted(missing)}")
            sys.exit(3)
        print("OK: v6 -> v7 migration complete.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
