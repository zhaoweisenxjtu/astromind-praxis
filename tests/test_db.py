"""数据库初始化测试"""
import sys, os, tempfile, shutil
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engine.db.database import Database, init_db


def test_database_init():
    """init_db 在临时目录中调用不应抛异常"""
    tmp_dir = Path(tempfile.mkdtemp())
    import engine.db.database as db_mod
    orig_dir, orig_path = db_mod.DB_DIR, db_mod.DB_PATH
    db_mod.DB_DIR = tmp_dir
    db_mod.DB_PATH = tmp_dir / "astromind_praxis.db"
    try:
        result = init_db(force=True)
        assert result is True
        assert db_mod.DB_PATH.exists()
    finally:
        db_mod.DB_DIR = orig_dir
        db_mod.DB_PATH = orig_path
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_db_execute_and_fetch():
    db = Database(":memory:")
    db.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
    row_id = db.execute("INSERT INTO test (name) VALUES (?)", ["hello"])
    assert row_id == 1

    row = db.fetch_one("SELECT * FROM test WHERE id = ?", [1])
    assert row["name"] == "hello"

    rows = db.fetch_all("SELECT * FROM test")
    assert len(rows) == 1
    db.close()


def test_db_execute_return_none():
    db = Database(":memory:")
    db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    db.execute("INSERT INTO t (v) VALUES ('a')")
    db.execute("INSERT INTO t (v) VALUES ('b')")
    rows = db.fetch_all("SELECT * FROM t")
    assert len(rows) == 2
    db.close()


def test_db_context_manager():
    with Database(":memory:") as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        db.execute("INSERT INTO t (v) VALUES ('x')")
        row = db.fetch_one("SELECT * FROM t")
        assert row["v"] == "x"


def test_db_fetch_empty():
    db = Database(":memory:")
    row = db.fetch_one("SELECT * FROM sqlite_master WHERE 1=0")
    assert row is None
    rows = db.fetch_all("SELECT * FROM sqlite_master WHERE 1=0")
    assert rows == []
    db.close()


if __name__ == "__main__":
    failures = []
    for name, fn in sorted({k: v for k, v in globals().items() if k.startswith("test_")}.items()):
        try:
            fn()
            print(f"  PASS {name}")
        except Exception as e:
            import traceback
            failures.append((name, e))
            traceback.print_exc()
    if failures:
        print(f"\n{len(failures)} test(s) FAILED")
        sys.exit(1)
    print("All DB tests passed")
