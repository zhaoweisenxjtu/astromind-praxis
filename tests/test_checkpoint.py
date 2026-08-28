"""checkpoint 协议状态机测试（阶段 1 验收）.

覆盖: create → request → (agent 补答) → submit → 幂等命中 → done；
      pending.json 索引一致性；中间产物缓存；prune。
"""

import json
import shutil
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.runs import (
    EXIT_NEEDS_LLM,
    EXIT_NEEDS_SEARCH,
    NeedsLLM,
    RunStore,
    CheckpointLLMClient,
    prompt_key,
)


@pytest.fixture()
def store(tmp_path):
    return RunStore(base_dir=tmp_path / "runs")


@pytest.fixture()
def run(store):
    return store.create_run(
        kind="teach_diagnose",
        argv={"topic": "量子计算"},
        track_id=3,
    )


# ── Run 生命周期 ──

def test_create_run_structure(store, run):
    assert run.id.startswith("run-")
    assert run.status == "running"
    meta = store._meta_path(run.id)
    assert meta.exists()
    data = json.loads(meta.read_text(encoding="utf-8"))
    assert data["kind"] == "teach_diagnose"
    assert data["argv"] == {"topic": "量子计算"}
    assert data["track_id"] == 3


def test_get_run_roundtrip(store, run):
    loaded = store.get_run(run.id)
    assert loaded is not None
    assert loaded.id == run.id
    assert loaded.kind == run.kind
    assert loaded.argv == run.argv


# ── Checkpoint 请求（LLM）──

def test_llm_request_creates_checkpoint(store, run, tmp_path):
    client = CheckpointLLMClient(store, run)
    sys_p, user_p, schema = "你是专家", "请诊断", {"type": "object"}

    with pytest.raises(NeedsLLM) as exc:
        client.chat(sys_p, user_p, schema)

    assert exc.value.exit_code == EXIT_NEEDS_LLM
    req_file = Path(exc.value.req_file)
    assert req_file.exists()
    assert req_file.name == "req-001.json"

    req = json.loads(req_file.read_text(encoding="utf-8"))
    assert req["run_id"] == run.id
    assert req["kind"] == "llm"
    assert req["system_prompt"] == sys_p
    assert req["user_prompt"] == user_p
    assert req["schema"] == schema
    assert "instruction" in req

    # run 状态与索引
    updated = store.get_run(run.id)
    assert updated.status == "pending_llm"
    assert updated.steps[0].status == "pending"
    pending = store.pending_runs()
    assert any(p.id == run.id for p in pending)


def test_llm_sequence_multi_checkpoint(store, run, tmp_path):
    """同一 run 多个 LLM 调用 → 逐个 checkpoint（seq 递增）。"""
    client = CheckpointLLMClient(store, run)
    with pytest.raises(NeedsLLM):
        client.chat("sys1", "usr1", None)
    with pytest.raises(NeedsLLM):
        client.chat("sys2", "usr2", None)

    updated = store.get_run(run.id)
    assert len(updated.steps) == 2
    assert updated.steps[0].req == "req-001.json"
    assert updated.steps[1].req == "req-002.json"


# ── 应答消费（resume 语义）──

def test_submit_response_then_idempotent_hit(store, run, tmp_path):
    client = CheckpointLLMClient(store, run)
    with pytest.raises(NeedsLLM):
        client.chat("sys", "usr", None)

    # agent 补答：写 rsp-001.json（用 run 目录完整路径，避免污染技能根目录）
    run2 = store.get_run(run.id)
    req_path = store._run_dir(run.id) / run2.steps[0].req
    rsp_path = req_path.with_name("rsp-001.json")
    rsp_path.write_text(
        json.dumps({"level": 2, "gaps": []}, ensure_ascii=False),
        encoding="utf-8",
    )

    # resume：submit_response 消费
    answered = store.submit_response(run.id, rsp_path)
    assert answered == {"level": 2, "gaps": []}

    run3 = store.get_run(run.id)
    assert run3.status == "running"
    assert run3.steps[0].status == "answered"
    assert not store.pending_runs()  # pending 索引已清

    # 幂等重放：同 prompt 直接命中，不再抛 checkpoint
    result = client.chat("sys", "usr", None)
    assert result == {"level": 2, "gaps": []}
    run4 = store.get_run(run.id)
    assert run4.steps[0].status == "consumed"


def test_get_answer_returns_none_without_rsp(store, run):
    key = prompt_key("sys", "usr", None)
    store.create_request(run, kind="llm", key=key, payload={})
    assert store.get_answer(run, key) is None


def test_replay_after_resume_uses_fresh_run_state(store, run, tmp_path):
    """回归：resume 后客户端持有的 run 快照必须刷新，防止过期 status 写回 meta。"""
    client = CheckpointLLMClient(store, run)
    with pytest.raises(NeedsLLM):
        client.chat("sys", "usr", None)

    run2 = store.get_run(run.id)
    rsp_path = store._rsp_path(run.id, 1)
    rsp_path.write_text(json.dumps({"ok": True}), encoding="utf-8")
    store.submit_response(run.id, rsp_path)

    # 重放命中后：meta 必须是 running，pending 索引必须为空
    result = client.chat("sys", "usr", None)
    assert result == {"ok": True}
    meta = json.loads(store._meta_path(run.id).read_text(encoding="utf-8"))
    assert meta["status"] == "running"
    assert store.pending_runs() == []


def test_submit_response_no_pending_step(store, run, tmp_path):
    with pytest.raises(ValueError, match="no pending step"):
        store.submit_response(run.id, tmp_path / "x.json")


# ── 搜索 checkpoint（Tier 4 契约）──

def test_search_request_exit_code(store, run):
    store.create_request(run, kind="search", key="q-hash", payload={"query": "foo"})
    updated = store.get_run(run.id)
    assert updated.status == "pending_search"
    from engine.runs import NeedsSearch
    exc = NeedsSearch(run.id, "step-001", Path("req-001.json"))
    assert exc.exit_code == EXIT_NEEDS_SEARCH


# ── 中间产物缓存（搜索幂等）──

def test_cache_roundtrip(store, run):
    assert store.cache_get(run, "search:foo") is None
    store.cache_set(run, "search:foo", {"results": [{"title": "a"}]})
    hit = store.cache_get(run, "search:foo")
    assert hit == {"results": [{"title": "a"}]}


# ── pending 索引一致性 ──

def test_pending_index_rebuild_on_multiple_runs(store):
    r1 = store.create_run("teach_diagnose", {"topic": "A"})
    r2 = store.create_run("teach_diagnose", {"topic": "B"})
    key = prompt_key("s", "u", None)
    store.create_request(r1, kind="llm", key=key, payload={})
    store.create_request(r2, kind="llm", key=key, payload={})

    pending = store.pending_runs()
    assert {p.id for p in pending} == {r1.id, r2.id}

    # latest = 最新 updated
    latest = store.latest_pending()
    assert latest.id == r2.id

    # r2 完成后索引只剩 r1
    store.mark_done(r2)
    pending = store.pending_runs()
    assert [p.id for p in pending] == [r1.id]


# ── 维护 ──

def test_prune_only_done(store, run, tmp_path):
    run2 = store.create_run("teach_session", {"session_id": 1})
    store.mark_done(run2)

    # 伪造 run2 旧 mtime
    old = store._run_dir(run2.id)
    past = time.time() - 20 * 86400
    for f in old.iterdir():
        import os
        os.utime(f, (past, past))
    os.utime(old, (past, past))

    removed = store.prune(days=14)
    assert run2.id in removed
    assert store.get_run(run.id) is not None  # pending 的 run 不删


def test_mark_failed(store, run):
    store.mark_failed(run, "boom")
    loaded = store.get_run(run.id)
    assert loaded.status == "failed"
    assert loaded.error == "boom"
    assert not store.pending_runs()
