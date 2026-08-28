"""v0.2.1 CLI 集成测试（阶段 2/3 验收）.

通过 subprocess 调 run.py，隔离 USERPROFILE 避免污染真实配置。
覆盖: launcher 可用性、dispatch 全命令可达、退出码契约 75/0/1、
      resume 无 pending 报错、doctor JSON、checkpoint 模式 diagnose 链路。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
RUN_PY = SKILL_DIR / "run.py"


def run_cli(args, tmp_path, env_extra=None):
    env = dict(os.environ)
    env["USERPROFILE"] = str(tmp_path)   # 隔离 ~/.astromind-praxis
    env["PYTHONIOENCODING"] = "utf-8"
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, str(RUN_PY), *args],
        capture_output=True, text=True, encoding="utf-8", env=env, timeout=60,
    )
    return proc


# ── launcher 与 dispatch ──

@pytest.mark.parametrize("cmd", [
    ["init", "--check", "--json"],
    ["doctor", "--json"],
    ["runs", "list", "--json"],
    ["track", "--user", "1", "--json"],
    ["review", "--json"],
    ["report", "1", "--json"],
    ["schedule", "--user", "1", "--json"],
    ["node", "search", "test", "--json"],
    ["teach", "status", "1", "--json"],
    ["teach", "next", "1", "--json"],
])
def test_all_commands_reachable(tmp_path, cmd):
    """P0-2 修复：全部命令 dispatch 可达（exit 0，不静默无输出）。"""
    proc = run_cli(cmd, tmp_path)
    assert proc.returncode == 0, f"{cmd} failed: {proc.stderr}"
    assert proc.stdout.strip() != ""


def test_unknown_command_exits_2(tmp_path):
    proc = run_cli(["bogus"], tmp_path)
    assert proc.returncode == 2


# ── 退出码契约 ──

def test_diagnose_without_topic_exits_1(tmp_path):
    proc = run_cli(["teach", "diagnose", "--json", "--agent"], tmp_path)
    assert proc.returncode == 1
    assert "Topic is required" in proc.stderr


def test_diagnose_not_initialized_exits_1(tmp_path):
    proc = run_cli(["teach", "diagnose", "量子计算", "--json", "--agent"], tmp_path)
    assert proc.returncode == 1
    assert "Not initialized" in proc.stderr


def test_init_noninteractive_json(tmp_path):
    proc = run_cli(["init", "--llm-model", "test-model", "--json"], tmp_path)
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["ok"] is True


def test_resume_no_pending_exits_1(tmp_path):
    proc = run_cli(["resume", "--json"], tmp_path)
    assert proc.returncode == 1
    assert "No pending run" in proc.stderr


def test_doctor_json_shape(tmp_path):
    proc = run_cli(["doctor", "--json"], tmp_path)
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert "dependencies" in data and "db" in data and "runs" in data


# ── checkpoint 链路（阶段 3 验收；v0.2.2: diagnose 仅 1 次 LLM checkpoint）──

def test_diagnose_checkpoint_chain(tmp_path):
    """零 API key：init → diagnose →（搜索 checkpoint 可选）→ LLM checkpoint(75) → 补答 → 完成。"""
    # init（checkpoint 模式：不配直连 key）
    proc = run_cli(["init", "--llm-model", "test-model", "--json"], tmp_path)
    assert proc.returncode == 0

    run_id = None
    # diagnose → 循环处理 checkpoint（≤2 次：可选 search + 必选 LLM）
    for step in range(1, 3):
        if run_id is None:
            proc = run_cli(["teach", "diagnose", "量子计算", "--json", "--agent"], tmp_path)
        else:
            proc = run_cli(["resume", run_id, "--rsp-file", str(rsp_path), "--json"], tmp_path)

        if proc.returncode == 0:
            break
        assert proc.returncode in (75, 76), (
            f"step {step} expected 75/76/0, got {proc.returncode}: {proc.stderr}"
        )
        payload = json.loads(proc.stdout)
        run_id = payload["run_id"]
        req_path = Path(payload["req_file"])
        assert req_path.exists()
        req = json.loads(req_path.read_text(encoding="utf-8"))
        assert req["run_id"] == run_id

        rsp_path = req_path.with_name(f"rsp-{step:03d}.json")
        if req["kind"] == "search":
            rsp_path.write_text(json.dumps(
                [{"title": "量子计算基础", "url": "https://x", "content": "量子比特与叠加态"}],
                ensure_ascii=False,
            ), encoding="utf-8")
        else:
            # diagnose_pack（v0.2.2 单调用点：KG + 诊断合并）
            rsp_path.write_text(json.dumps({
                "concepts": [
                    {"name": "量子比特", "level": "foundational", "complexity": 2,
                     "description": "基本信息单元"},
                ],
                "edges": [],
                "level": 2,
                "gaps": [],
                "misconceptions": [],
                "recommended_path": ["量子比特"],
            }, ensure_ascii=False), encoding="utf-8")

    assert proc.returncode == 0, f"expected 0, got {proc.returncode}: {proc.stderr}"
    result = json.loads(proc.stdout)
    assert result["session_id"] == 1
    assert result["level"] == 2

    # 幂等：DB 只有 1 个 session、1 个节点
    proc = run_cli(["runs", "list", "--json"], tmp_path)
    runs = json.loads(proc.stdout)["runs"]
    assert len(runs) == 1 and runs[0]["status"] == "done"
