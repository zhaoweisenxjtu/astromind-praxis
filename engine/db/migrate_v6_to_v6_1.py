"""Schema v6 → v6.1 迁移: 新增 author-knowledge 系统表.

Usage:
  python engine/db/migrate_v6_to_v6_1.py --check   检查当前版本
  python engine/db/migrate_v6_to_v6_1.py --upgrade  执行升级
  python engine/db/migrate_v6_to_v6_1.py --dry-run  预览(不执行)
"""

import argparse
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from engine.db.database import get_connection, ensure_db_dir, DB_PATH


V6_1_TABLES = ["articles", "knowledge_atoms", "mental_models", "author_profiles"]
SCHEMA_6_1 = Path(__file__).parent / "schema_v6_1.sql"


def _table_exists(conn, name):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


def check_version():
    """Check which tables from v6.1 already exist."""
    ensure_db_dir()
    if not DB_PATH.exists():
        print("No database found. Run 'python engine/__main__.py init' first.")
        return False

    conn = get_connection()
    try:
        existing = []
        missing = []
        for t in V6_1_TABLES:
            if _table_exists(conn, t):
                existing.append(t)
            else:
                missing.append(t)

        print(f"DB: {DB_PATH}")
        print(f"Version: v6 + {'partial' if missing else 'full'} v6.1")
        print(f"  Existing v6.1 tables: {existing if existing else '(none)'}")
        print(f"  Missing v6.1 tables:  {missing if missing else '(none)'}")
        return len(missing) == 0
    finally:
        conn.close()


def _ensure_columns(conn, table, columns: list[tuple[str, str]]):
    """Add columns to existing table if missing. columns = [(name, type_spec), ...]"""
    cur = conn.execute(f"PRAGMA table_info('{table}')")
    existing = {row[1] for row in cur.fetchall()}
    for col_name, col_spec in columns:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_spec}")
            print(f"  [+] Added {table}.{col_name} {col_spec}")


def upgrade():
    """Execute schema_v6_1.sql plus incremental column migrations."""
    ensure_db_dir()
    if not DB_PATH.exists():
        print("No database found. Run 'python engine/__main__.py init' first.")
        return False

    if not SCHEMA_6_1.exists():
        print(f"Schema file not found: {SCHEMA_6_1}")
        return False

    conn = get_connection()
    try:
        schema = SCHEMA_6_1.read_text(encoding="utf-8")
        conn.executescript(schema)
        conn.commit()

        # Verify tables
        for t in V6_1_TABLES:
            if _table_exists(conn, t):
                print(f"  [+] {t} ok")
            else:
                print(f"  [!] {t} failed to create")

        # Incremental column migrations for existing tables
        _ensure_columns(conn, "author_profiles", [
            ("persona_md", "TEXT DEFAULT ''"),
            ("mirror_md", "TEXT DEFAULT ''"),
        ])

        conn.commit()
        print("v6 → v6.1 upgrade complete.")
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Migrate astromind DB v6 → v6.1")
    parser.add_argument("--check", action="store_true", help="Check current version")
    parser.add_argument("--upgrade", action="store_true", help="Execute upgrade")
    parser.add_argument("--dry-run", action="store_true", help="Preview SQL without executing")
    args = parser.parse_args()

    if args.dry_run:
        if SCHEMA_6_1.exists():
            print(SCHEMA_6_1.read_text(encoding="utf-8"))
        else:
            print(f"Schema file not found: {SCHEMA_6_1}")
        return

    if args.upgrade:
        success = upgrade()
    else:
        success = check_version()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
