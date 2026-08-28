"""答题流 + 复习闭环测试（阶段 4/5 验收）.

用 fake LLM 直接测 workflow 层：SM-2 三值映射、批量评估、
副作用幂等（resume 重放不重复写）、复习出题/落库。
"""

import json
import sys
import tempfile
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.runs import RunStore
from engine.runs.store import NeedsLLM
from engine.teaching.workflow import TeachingOrchestrator, quality_from_eval
from engine.core.sm2 import SM2Calculator


class FakeLLM:
    """可编程 LLM：按调用次数返回预设响应，或抛 NeedsLLM。"""

    def __init__(self, responses=None, checkpoint_mode=False):
        self.responses = responses or []
        self.calls = []
        self.checkpoint_mode = checkpoint_mode

    def chat(self, system_prompt, user_prompt, schema=None, temperature=0.7, max_tokens=4096):
        self.calls.append(user_prompt)  # 存完整 prompt（断言需要全文）
        if self.checkpoint_mode:
            raise NeedsLLM("run-x", "step-001", Path("req-001.json"))
        return self.responses.pop(0) if self.responses else {"ok": True}


class FakeSearch:
    def search(self, query, max_results=10, **kwargs):
        return [{"title": "r", "url": "u", "content": "c"}]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """隔离 DB + run store（monkeypatch 模块级 DB_PATH）。"""
    from engine.db import database as db_database
    monkeypatch.setattr(db_database, "DB_PATH", tmp_path / "test.db")
    from engine.db.database import init_db, Database
    init_db()
    db = Database()
    store = RunStore(base_dir=tmp_path / "runs")
    run = store.create_run("test", {"x": 1}, track_id=1)
    yield db, store, run
    db.close()


@pytest.fixture()
def orch(env):
    db, store, run = env
    # user + track + session 准备
    db.execute("INSERT INTO users (name, created_at, updated_at) VALUES ('t', 'x', 'x')")
    db.execute("INSERT INTO tracks (user_id, name, target_type, created_at, updated_at) "
               "VALUES (1, 't', 'interest', 'x', 'x')")
    from engine.teaching.session import SessionManager
    sm = SessionManager(db)
    session_id = sm.create_session("1", 1, "测试", {"node_ids": [1], "node_map": {"A": 1}})
    nid = db.execute(
        "INSERT INTO knowledge_nodes (track_id, name, status, created_at, updated_at) "
        "VALUES (1, 'A', 'pending', 'x', 'x')"
    )
    return db, store, run, session_id, nid


# ── SM-2 三值映射 ──

@pytest.mark.parametrize("correct,level,expected", [
    (True, 5, 5), (True, 4, 5), (True, 3, 4), (True, 2, 4),
    (False, 5, 2), (False, 3, 2), (False, 1, 1), (False, 0, 1),
])
def test_quality_three_value_mapping(correct, level, expected):
    assert quality_from_eval(correct, level) == expected


# ── 批量评估 + SM-2 ──

def test_answer_batch_applies_sm2(orch):
    db, store, run, session_id, nid = orch
    fake = FakeLLM([{
        "results": [
            {"question": "q1", "correct": True, "level": 5, "fake_signals": [], "feedback": "ok"},
            {"question": "q2", "correct": False, "level": 2, "fake_signals": [], "feedback": "no"},
            {"question": "q3", "correct": True, "level": 3, "fake_signals": [], "feedback": "ok"},
        ],
        "overall_feedback": "整体一般",
    }])
    o = TeachingOrchestrator(db, fake, FakeSearch(), "1", 1, run=run, run_store=store)

    result = o.run_answer_batch(session_id, nid, [
        {"question": "q1", "answer": "a1"},
        {"question": "q2", "answer": "a2"},
        {"question": "q3", "answer": "a3"},
    ], ["x", "y", "z"])

    # qualities = [5, 2, 4] → mean = round(11/3) = 4（SM-2 quality=4 → EF 中性不变）
    node = db.fetch_one("SELECT * FROM knowledge_nodes WHERE id = ?", [nid])
    assert node["repetitions"] == 1
    assert node["ef"] == 2.5
    assert node["interval"] == 1
    # interaction_log 3 行
    cnt = db.fetch_one("SELECT COUNT(*) AS c FROM interaction_log WHERE node_id = ?", [nid])
    assert cnt["c"] == 3
    # 节点完成 → status active
    assert node["status"] == "active"
    # next_review 已落库（v0.2.1 修复）
    assert node["next_review"] is not None


def test_answer_batch_idempotent_replay(orch):
    """resume 重放：命中 apply 缓存，不重复写 SM-2/interaction。"""
    db, store, run, session_id, nid = orch
    fake = FakeLLM([{"results": [{"question": "q1", "correct": True, "level": 5,
                                  "fake_signals": [], "feedback": "ok"}],
                     "overall_feedback": ""}])
    o = TeachingOrchestrator(db, fake, FakeSearch(), "1", 1, run=run, run_store=store)
    questions = [{"question": "q1", "answer": "a"}]

    o.run_answer_batch(session_id, nid, questions, ["ok"])
    before = db.fetch_one("SELECT * FROM knowledge_nodes WHERE id = ?", [nid])

    # 重放（LLM 换成 checkpoint 模式应抛——但缓存命中不调用 LLM）
    fake2 = FakeLLM(checkpoint_mode=True)
    o2 = TeachingOrchestrator(db, fake2, FakeSearch(), "1", 1, run=run, run_store=store)
    result = o2.run_answer_batch(session_id, nid, questions, ["ok"])  # 不抛，命中缓存

    after = db.fetch_one("SELECT * FROM knowledge_nodes WHERE id = ?", [nid])
    assert after["repetitions"] == before["repetitions"]
    assert after["ef"] == before["ef"]
    cnt = db.fetch_one("SELECT COUNT(*) AS c FROM interaction_log WHERE node_id = ?", [nid])
    assert cnt["c"] == 1
    assert result["sm2"]["repetitions"] == before["repetitions"]


# ── 复习闭环 ──

def test_get_due_nodes_filters_by_next_review(orch):
    db, store, run, session_id, nid = orch
    o = TeachingOrchestrator(db, FakeLLM(), FakeSearch(), "1", 1, run=run, run_store=store)

    # 未到期节点（future）不返回
    db.execute("UPDATE knowledge_nodes SET next_review = '2999-01-01', status='active' WHERE id = ?", [nid])
    assert o.get_due_nodes() == []

    # 到期节点（past）返回
    db.execute("UPDATE knowledge_nodes SET next_review = '2020-01-01' WHERE id = ?", [nid])
    due = o.get_due_nodes()
    assert len(due) == 1 and due[0]["id"] == nid

    # pending 状态不进入复习
    db.execute("UPDATE knowledge_nodes SET status='pending' WHERE id = ?", [nid])
    assert o.get_due_nodes() == []


def test_review_answers_writes_all_tables(orch):
    db, store, run, session_id, nid = orch
    db.execute("UPDATE knowledge_nodes SET status='active', next_review='2020-01-01' WHERE id = ?", [nid])
    fake = FakeLLM([{"results": [{"question": "r1", "correct": True, "level": 4,
                                  "fake_signals": [], "feedback": "ok"},
                                 {"question": "r2", "correct": True, "level": 5,
                                  "fake_signals": [], "feedback": "ok"}],
                     "overall_feedback": "通过"}])
    o = TeachingOrchestrator(db, fake, FakeSearch(), "1", 1, run=run, run_store=store)

    result = o.run_review_answers(session_id, [{
        "node_id": nid, "node_name": "A",
        "questions": [{"question": "r1", "answer": "a"}, {"question": "r2", "answer": "b"}],
        "answers": ["x", "y"],
    }])

    assert result["items"][0]["correct_count"] == 2
    rh = db.fetch_one("SELECT COUNT(*) AS c FROM review_history WHERE node_id = ?", [nid])
    assert rh["c"] == 1
    # v0.2.2: teaching_interactions 已并入 interaction_log（review_session 标签）
    ti = db.fetch_one(
        "SELECT COUNT(*) AS c FROM interaction_log WHERE node_id = ? AND interaction_type = 'review_session'",
        [nid],
    )
    assert ti["c"] == 2
    # SM-2 演进（reps 0→1，ef 2.5→2.6）
    node = db.fetch_one("SELECT * FROM knowledge_nodes WHERE id = ?", [nid])
    assert node["repetitions"] == 1
    assert node["next_review"] is not None


def test_review_answers_idempotent_replay(orch):
    db, store, run, session_id, nid = orch
    db.execute("UPDATE knowledge_nodes SET status='active', next_review='2020-01-01' WHERE id = ?", [nid])
    fake = FakeLLM([{"results": [{"question": "r1", "correct": True, "level": 5,
                                  "fake_signals": [], "feedback": "ok"}],
                     "overall_feedback": ""}])
    o = TeachingOrchestrator(db, fake, FakeSearch(), "1", 1, run=run, run_store=store)
    items = [{"node_id": nid, "node_name": "A",
              "questions": [{"question": "r1", "answer": "a"}], "answers": ["x"]}]

    o.run_review_answers(session_id, items)
    # 重放命中缓存
    fake2 = FakeLLM(checkpoint_mode=True)
    o2 = TeachingOrchestrator(db, fake2, FakeSearch(), "1", 1, run=run, run_store=store)
    o2.run_review_answers(session_id, items)  # 不抛

    rh = db.fetch_one("SELECT COUNT(*) AS c FROM review_history WHERE node_id = ?", [nid])
    assert rh["c"] == 1
    ti = db.fetch_one(
        "SELECT COUNT(*) AS c FROM interaction_log WHERE node_id = ? AND interaction_type = 'review_session'",
        [nid],
    )
    assert ti["c"] == 1


def test_review_questions_prompt_uses_history(orch):
    """复习出题携带历史题目与假懂信号（防原题重考 + 定向检测）。"""
    db, store, run, session_id, nid = orch
    db.execute("UPDATE knowledge_nodes SET status='active', content='教学内容', "
               "next_review='2020-01-01' WHERE id = ?", [nid])
    # 历史作答 + 假懂信号
    db.execute(
        "INSERT INTO interaction_log (user_id, track_id, node_id, question, answer, is_correct, "
        "understanding_level, fake_signals, created_at) "
        "VALUES ('1', 1, ?, '旧题', 'x', 1, 3, '[{\"type\":\"boundary_blur\",\"detail\":\"边界\"}]', 'x')",
        [nid],
    )
    fake = FakeLLM([{"items": [{"node_id": nid, "questions": [
        {"question": "新题", "answer": "a", "explanation": "e",
         "type": "recall", "difficulty": 3},
    ]}]}])
    o = TeachingOrchestrator(db, fake, FakeSearch(), "1", 1, run=run, run_store=store)

    items = o.run_review_questions(o.get_due_nodes())
    prompt = fake.calls[0]
    assert "旧题" in prompt          # 历史题目注入（去重）
    assert "boundary_blur" in prompt  # 假懂信号注入
    assert items[0]["node_id"] == nid
