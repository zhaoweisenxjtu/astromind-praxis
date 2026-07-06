"""教学会话 + 渲染 + 数据库测试"""
import sys, os, json, sqlite3, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engine.teaching.session import SessionManager
from engine.teaching.render import (
    render_concept_content, render_questions,
    render_diagnosis, render_progress_bar, render_session_status
)


def _make_mock_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS workflow_context (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            track_id INTEGER NOT NULL,
            topic TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'diagnosed',
            level INTEGER DEFAULT 1,
            diagnosis TEXT NOT NULL DEFAULT '{}',
            current_node INTEGER,
            completed_nodes TEXT NOT NULL DEFAULT '[]',
            state_data TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    return conn


def test_create_session():
    conn = _make_mock_db()
    class MockDB:
        def execute(self, sql, params=None):
            cur = conn.execute(sql, params or [])
            conn.commit()
            return cur.lastrowid
        def fetch_one(self, sql, params=None):
            return conn.execute(sql, params or []).fetchone()
        def fetch_all(self, sql, params=None):
            return conn.execute(sql, params or []).fetchall()

    sm = SessionManager(MockDB())
    sid = sm.create_session("user1", 1, "Python", {"level": 2})
    assert sid is not None

    session = sm.get_session(sid)
    assert session["topic"] == "Python"
    assert session["user_id"] == "user1"
    assert session["status"] == "diagnosed"
    assert session["diagnosis"]["level"] == 2


def test_update_session():
    conn = _make_mock_db()
    class MockDB:
        def execute(self, sql, params=None):
            cur = conn.execute(sql, params or [])
            conn.commit()
            return cur.lastrowid
        def fetch_one(self, sql, params=None):
            return conn.execute(sql, params or []).fetchone()
        def fetch_all(self, sql, params=None):
            return conn.execute(sql, params or []).fetchall()

    sm = SessionManager(MockDB())
    sid = sm.create_session("user1", 1, "Python", {})
    sm.update_session(sid, status="teaching", level=3)
    session = sm.get_session(sid)
    assert session["status"] == "teaching"
    assert session["level"] == 3


def test_completed_nodes():
    conn = _make_mock_db()
    class MockDB:
        def execute(self, sql, params=None):
            cur = conn.execute(sql, params or [])
            conn.commit()
            return cur.lastrowid
        def fetch_one(self, sql, params=None):
            return conn.execute(sql, params or []).fetchone()
        def fetch_all(self, sql, params=None):
            return conn.execute(sql, params or []).fetchall()

    sm = SessionManager(MockDB())
    sid = sm.create_session("user1", 1, "Python", {"node_ids": [1, 2, 3], "node_map": {}})
    sm.add_completed_node(sid, 1)
    sm.add_completed_node(sid, 2)
    session = sm.get_session(sid)
    assert session["completed_nodes"] == [1, 2]


def test_render_concept_content():
    content = {
        "intuition": "就像搭积木",
        "motivation": "因为需要组织代码",
        "definition": "类是对象的模板",
        "boundary": "不适用于函数式编程",
        "connections": [{"concept": "对象", "relation": "实例化"}],
        "examples": [{"question": "如何定义类", "solution": "class Foo", "difficulty": 2}],
    }
    out = render_concept_content(content, "类")
    assert "# 类" in out
    assert "就像搭积木" in out
    assert "因为需要组织代码" in out
    assert "类是对象的模板" in out
    assert "class Foo" in out


def test_render_content_minimal():
    """只含必填字段也能渲染"""
    content = {"intuition": "i", "motivation": "m", "definition": "d", "boundary": "b", "examples": []}
    out = render_concept_content(content, "test")
    assert "# test" in out


def test_render_questions():
    questions = [
        {"question": "1+1=?", "answer": "2", "explanation": "基础", "type": "conceptual", "difficulty": 1},
    ]
    out = render_questions(questions)
    assert "1+1=?" in out
    assert "概念理解" in out


def test_render_questions_with_options():
    questions = [
        {"question": "Q", "options": ["A", "B", "C"], "answer": "A", "explanation": "E", "type": "applied"},
    ]
    out = render_questions(questions)
    assert "- A" in out
    assert "- B" in out


def test_render_diagnosis():
    diag = {"level": 3, "gaps": [{"concept": "指针", "gap_type": "weak", "description": "不熟"}],
            "misconceptions": [{"concept": "指针", "misconception": "指针就是地址", "correction": "不完全是"}],
            "recommended_path": ["内存", "指针", "引用"]}
    out = render_diagnosis(diag)
    assert "诊断报告" in out
    assert "进阶" in out  # level 3 = 进阶
    assert "指针" in out
    assert "不熟" in out
    assert "内存" in out


def test_render_progress_bar():
    bar = render_progress_bar(2, 5)
    assert "📊" in bar
    assert "2/5" in bar


def test_render_session_status():
    session = {"topic": "Python", "status": "teaching", "level": 3, "current_node": 5}
    out = render_session_status(session)
    assert "Python" in out
    assert "teaching" in out


if __name__ == "__main__":
    failures = []
    for name, fn in sorted({k: v for k, v in globals().items() if k.startswith("test_")}.items()):
        try:
            fn()
            print(f"  PASS {name}")
        except Exception as e:
            failures.append((name, e))
            print(f"  FAIL {name}: {e}")
    if failures:
        print(f"\n{len(failures)} test(s) FAILED")
        sys.exit(1)
    print("All teaching tests passed")
