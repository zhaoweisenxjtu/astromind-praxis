"""v0.2.2 调用点合并验证：每次流程仅 1 次 LLM 调用（checkpoint 往返计数核心）.

G3 目标：diagnose 3→2 次往返、session 2→1 次往返、review 逐节点→批量 1 次。
本测试用 FakeLLM 计数验证合并后的实际 LLM 调用次数。
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.runs import RunStore
from engine.teaching.workflow import TeachingOrchestrator
from engine.llm.prompts import PROMPT_REGISTRY


class CountingLLM:
    """记录每次 chat 的 prompt 名（通过 user_prompt 特征）与调用次数。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []  # 每次调用的 (调用序号, user_prompt 摘要)

    def chat(self, system_prompt, user_prompt, schema=None, temperature=0.7, max_tokens=4096):
        idx = len(self.calls)
        self.calls.append((idx, user_prompt[:80]))
        if self.responses:
            return self.responses.pop(0)
        return {"ok": True}


class FakeSearch:
    def search(self, query, max_results=10, **kwargs):
        return [{"title": "r", "url": "u", "content": "内容摘要"}]


def _env(tmp_path, monkeypatch):
    from engine.db import database as db_database
    monkeypatch.setattr(db_database, "DB_PATH", tmp_path / "test.db")
    from engine.db.database import init_db, Database
    init_db()
    db = Database()
    store = RunStore(base_dir=tmp_path / "runs")
    run = store.create_run("test", {"x": 1}, track_id=1)
    db.execute("INSERT INTO users (name, created_at, updated_at) VALUES ('t', 'x', 'x')")
    db.execute("INSERT INTO tracks (user_id, name, target_type, created_at, updated_at) "
               "VALUES (1, 't', 'interest', 'x', 'x')")
    from engine.teaching.session import SessionManager
    sm = SessionManager(db)
    return db, store, run, sm


def test_diagnose_pack_single_llm_call(tmp_path, monkeypatch):
    """v0.2.2: diagnose 全程仅 1 次 LLM 调用（KG+诊断合并，原 2 次）。"""
    db, store, run, sm = _env(tmp_path, monkeypatch)
    llm = CountingLLM([{
        "concepts": [
            {"name": "量子比特", "level": "foundational", "complexity": 2,
             "description": "基本信息单元"},
            {"name": "叠加态", "level": "intermediate", "complexity": 3,
             "description": "量子态组合"},
        ],
        "edges": [{"source": "量子比特", "target": "叠加态", "relation": "prerequisite"}],
        "level": 2,
        "gaps": [{"concept": "叠加态", "gap_type": "weak", "description": "概念模糊"}],
        "misconceptions": [{"concept": "量子比特", "misconception": "以为必为0/1"}],
        "recommended_path": ["量子比特", "叠加态"],
    }])
    o = TeachingOrchestrator(db, llm, FakeSearch(), "1", 1, run=run, run_store=store)

    result = o.run_diagnosis("量子计算", self_assessment=3)

    assert len(llm.calls) == 1, f"expected 1 LLM call, got {len(llm.calls)}"
    # 搜索结果注入 prompt（search 是独立能力，不走 LLM）
    assert "内容摘要" in llm.calls[0][1]
    # 合并结果完整：session 创建 + 节点 + 边 + 诊断
    assert result["session_id"] == 1
    assert result["diagnosis"]["level"] == 2
    nodes = db.fetch_all("SELECT * FROM knowledge_nodes")
    assert len(nodes) == 2
    deps = db.fetch_all("SELECT * FROM node_dependencies")
    assert len(deps) == 1
    db.close()


def test_teach_session_single_llm_call(tmp_path, monkeypatch):
    """v0.2.2: teach session 仅 1 次 LLM 调用（内容+出题合并，原 2 次）。"""
    db, store, run, sm = _env(tmp_path, monkeypatch)
    session_id = sm.create_session("1", 1, "量子计算", {
        "topic": "量子计算",
        "node_ids": [1],
        "node_map": {"量子比特": 1},
        "recommended_path": ["量子比特"],
    })
    nid = db.execute(
        "INSERT INTO knowledge_nodes (track_id, name, status, created_at, updated_at) "
        "VALUES (1, '量子比特', 'pending', 'x', 'x')"
    )
    llm = CountingLLM([{
        "intuition": "硬币类比",
        "motivation": "量子计算基础",
        "definition": "量子比特定义",
        "boundary": "不适用场景",
        "connections": [{"concept": "叠加态", "relation": "related"}],
        "examples": [{"question": "例1", "solution": "解1", "difficulty": 2}],
        "questions": [
            {"question": "概念题", "answer": "答", "explanation": "解析",
             "type": "conceptual", "difficulty": 2},
            {"question": "应用题", "answer": "答", "explanation": "解析",
             "type": "applied", "difficulty": 3},
            {"question": "辨析题", "answer": "答", "explanation": "解析",
             "type": "discrimination", "difficulty": 4},
        ],
    }])
    o = TeachingOrchestrator(db, llm, FakeSearch(), "1", 1, run=run, run_store=store)

    result = o.run_teaching_session(session_id)

    assert len(llm.calls) == 1, f"expected 1 LLM call, got {len(llm.calls)}"
    assert result["node_name"] == "量子比特"
    assert result["concept_content"]["intuition"] == "硬币类比"
    assert len(result["questions"]) == 3
    db.close()


def test_review_pack_single_llm_call_for_multiple_nodes(tmp_path, monkeypatch):
    """v0.2.2: review 多节点批量出题仅 1 次 LLM 调用（原逐节点 N 次）。"""
    db, store, run, sm = _env(tmp_path, monkeypatch)
    nids = []
    for name in ("概念A", "概念B"):
        nid = db.execute(
            "INSERT INTO knowledge_nodes (track_id, name, status, content, next_review, created_at, updated_at) "
            "VALUES (1, ?, 'active', '内容', '2020-01-01', 'x', 'x')",
            [name],
        )
        nids.append(nid)
    llm = CountingLLM([{
        "items": [
            {"node_id": nids[0], "questions": [
                {"question": "A题1", "answer": "a", "explanation": "e",
                 "type": "recall", "difficulty": 2},
                {"question": "A题2", "answer": "a", "explanation": "e",
                 "type": "application", "difficulty": 3},
            ]},
            {"node_id": nids[1], "questions": [
                {"question": "B题1", "answer": "a", "explanation": "e",
                 "type": "discrimination", "difficulty": 3},
                {"question": "B题2", "answer": "a", "explanation": "e",
                 "type": "recall", "difficulty": 2},
            ]},
        ],
    }])
    o = TeachingOrchestrator(db, llm, FakeSearch(), "1", 1, run=run, run_store=store)

    items = o.run_review_questions(o.get_due_nodes(limit=5))

    assert len(llm.calls) == 1, f"expected 1 LLM call for 2 nodes, got {len(llm.calls)}"
    assert len(items) == 2
    by_id = {it["node_id"]: len(it["questions"]) for it in items}
    assert by_id[nids[0]] == 2 and by_id[nids[1]] == 2
    db.close()


def test_prompt_registry_five_callpoints():
    """G4: 注册表收敛为 5 个调用点。"""
    assert set(PROMPT_REGISTRY.keys()) == {
        "diagnose_pack", "teach_pack", "evaluate_answers_batch", "review_pack", "assessment",
    }
