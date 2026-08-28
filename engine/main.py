#!/usr/bin/env python3
"""Astromind Praxis CLI — 星知·笃行 认知科学驱动的元学习引擎 (v0.2.2).

v0.2.2 变更（减法重构，见 D:/workdata/output/astromind-praxis-v0.3-redesign.md）:
  - LLM 调用点 8→5：diagnose_pack（KG+诊断合并）、teach_pack（内容+出题合并）、
    review_pack（多节点批量出题）、assessment 注册化；删除 evaluate_answer 单题路径
  - 删除死代码：knowledge_quality/fake_detection/dao_weakness/dao_journal/
    dao_assessment/dao_interaction/dao_graph；graph 与 migrate 命令删除
  - Schema v7：17→9 表；interaction_log 吸收 teaching_interactions
  - checkpoint 上限：diagnose ≤2、session ≤1、review ≤2
  - 退出码契约：0 成功 / 1 错误 / 75 NEEDS_LLM / 76 NEEDS_SEARCH / 77 AWAITING_ANSWERS

用法:
  astromind init [--check|--reset|--llm-base-url ...]  初始化/检查配置
  astromind doctor                                      依赖+配置+DB 自检
  astromind teach diagnose <topic> [--self-assessment N] [--description ...]
  astromind teach session <id> | assess <id> | status <id> | next <id>
  astromind resume [run_id] [--rsp-file <f>] [--rsp '<json>']  消费补答并继续
  astromind runs list | prune [--days N]
  astromind node search <kw> | node content <id> [--content|--file]
  astromind track --user <id> | review --user <id> | report dashboard <id>
  astromind schedule today | misconception add ...
"""

import argparse
import json
import logging
import os
import pathlib
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

from .runs import (
    EXIT_NEEDS_ANSWERS,
    EXIT_NEEDS_LLM,
    EXIT_NEEDS_SEARCH,
    NeedsLLM,
    NeedsSearch,
    RunStore,
)

logger = logging.getLogger(__name__)

CONFIG_DIR = pathlib.Path.home() / ".astromind-praxis"
CONFIG_PATH = CONFIG_DIR / "config.yaml"
OPENCLAW_HOME = pathlib.Path(
    os.environ.get("OPENCLAW_HOME", str(pathlib.Path.home() / ".openclaw"))
)
OPENCLAW_CONFIG_PATH = OPENCLAW_HOME / "openclaw.json"

# ── 全局状态 ──

_current_run = None          # resume 重放时注入的 run
_agent_mode = False          # 显式 agent 模式（--agent / env / config）


def _set_agent_mode(flag: bool):
    global _agent_mode
    _agent_mode = flag


def is_agent_mode() -> bool:
    return _agent_mode


def _set_current_run(run):
    global _current_run
    _current_run = run


def _get_current_run():
    return _current_run


# ── 输出 helpers ──

def _emit(obj):
    print(json.dumps(obj, ensure_ascii=False, default=str))


def _err(msg: str):
    print(json.dumps({"error": msg}, ensure_ascii=False), file=sys.stderr)


def _want_json(args) -> bool:
    return bool(getattr(args, "json", False)) or is_agent_mode()


# ── Config helpers ──

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        import yaml
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning("Failed to load config from %s: %s", CONFIG_PATH, e)
        return {}


def _load_agent_llm_config() -> dict:
    """从 OpenClaw agent 配置继承 LLM 设置."""
    try:
        if not OPENCLAW_CONFIG_PATH.exists():
            return {}
        with open(OPENCLAW_CONFIG_PATH, encoding="utf-8") as f:
            claw = json.load(f)

        defaults = claw.get("agents", {}).get("defaults", {}) or {}
        model_cfg = defaults.get("model", {}) or {}
        primary = model_cfg.get("primary", "") or ""
        provider_name, _, model_id = primary.partition("/")
        if not provider_name or not model_id:
            return {}

        providers = claw.get("models", {}).get("providers", {}) or {}
        provider = providers.get(provider_name) or {}
        base_url = provider.get("baseUrl") or provider.get("base_url") or ""
        api_key = provider.get("apiKey") or provider.get("api_key") or ""
        if not (base_url and api_key):
            return {}

        return {
            "base_url": base_url,
            "api_key": api_key,
            "model": model_id,
        }
    except Exception as e:
        logger.warning("Failed to load OpenClaw agent LLM config: %s", e)
        return {}


def _resolve_llm_config(config: dict) -> tuple[dict, str]:
    """解析最终 LLM 配置: 本地 config.yaml 显式值优先, 否则继承 agent 配置.

    Returns:
        (llm_config, source) — source ∈ {"config", "agent", "checkpoint"}.
    """
    llm = config.get("llm", {}) or {}
    if llm.get("base_url") and llm.get("api_key") and llm.get("model"):
        return llm, "config"

    inherited = _load_agent_llm_config()
    if inherited.get("base_url") and inherited.get("api_key") and inherited.get("model"):
        merged = dict(inherited)
        for k in ("base_url", "api_key", "model"):
            if llm.get(k):
                merged[k] = llm[k]
        return merged, "agent"

    return llm, "checkpoint"


def save_config(config: dict):
    import yaml
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def check_config() -> dict:
    config = load_config()
    llm_config, llm_source = _resolve_llm_config(config)
    return {
        "config_exists": CONFIG_PATH.exists(),
        "init_completed": config.get("init", {}).get("completed", False),
        "llm_configured": bool(llm_config.get("api_key")),
        "llm_source": llm_source,
        "llm_model": llm_config.get("model", ""),
        "anysearch_configured": bool(config.get("anysearch_api_key")),
        "bing_configured": bool(config.get("bing_key")),
    }


# ── Run 上下文（checkpoint 重放核心）──

def _get_run_context(kind: str, argv: dict):
    """获取当前命令的 run：resume 注入的复用；否则新建。

    Returns: (store, run)
    """
    store = RunStore()
    run = _get_current_run()
    if run is None:
        run = store.create_run(kind=kind, argv={"_cmd": kind, **argv})
        _set_current_run(run)
    return store, run


def _rerun(run):
    """从 meta.argv 恢复参数，重放原命令（幂等：已答 checkpoint 命中缓存）. """
    argv = dict(run.argv)
    cmd_key = argv.pop("_cmd", None)
    if not cmd_key:
        raise ValueError(f"Run {run.id} missing _cmd in argv")
    ns = SimpleNamespace(**argv)
    ns.json = True
    ns.agent = is_agent_mode()
    DISPATCH[cmd_key](ns)


# ── Init command ──

def cmd_init(args):
    if getattr(args, "check", False):
        status = check_config()
        if _want_json(args):
            _emit(status)
            return
        llm_label = {
            "config": f"YES ({status['llm_model']})",
            "agent": f"YES (inherited from OpenClaw agent: {status['llm_model']})",
            "checkpoint": "NO (uses checkpoint protocol)",
        }.get(status["llm_source"], "?")
        print("Config check:")
        print(f"  Config file:     {'OK' if status['config_exists'] else 'MISSING'}")
        print(f"  Init completed:  {'YES' if status['init_completed'] else 'NO'}")
        print(f"  LLM configured:  {llm_label}")
        print(f"  AnySearch key:   {'YES' if status['anysearch_configured'] else 'NO (anonymous)'}")
        print(f"  Bing key:        {'YES' if status['bing_configured'] else 'NO (WebFetch fallback)'}")
        return

    if getattr(args, "reset", False):
        config = {}
    else:
        config = load_config()

    # 非交互路径（agent 用）
    llm_base = getattr(args, "llm_base_url", None)
    llm_key = getattr(args, "llm_api_key", None)
    llm_model = getattr(args, "llm_model", None)
    if llm_base or llm_key or llm_model:
        config["llm"] = {
            "base_url": llm_base or "",
            "api_key": llm_key or "",
            "model": llm_model or "",
        }
        from datetime import datetime, timezone
        config["init"] = {
            "completed": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        save_config(config)
        if _want_json(args):
            _emit({"ok": True, "config_path": str(CONFIG_PATH), "llm_source": "config"})
        else:
            print(f"✓ Configuration saved to {CONFIG_PATH}")
        return

    # 交互路径：非 tty 直接报错指引
    if not sys.stdin.isatty():
        _err(
            "Non-interactive shell: use flags "
            "--llm-base-url/--llm-api-key/--llm-model, or --check"
        )
        sys.exit(1)

    print("=" * 50)
    print("  星知·笃行 (Astromind Praxis) v0.2.2 — Configuration Wizard")
    print("=" * 50)
    print("(Press Enter to skip any field)\n")

    print("── LLM Configuration ──")
    print("  Leave blank to inherit OpenClaw agent's LLM (or checkpoint protocol).")
    llm = config.get("llm", {})
    base_url = input(f"  Base URL [{llm.get('base_url', '')}]: ").strip() or llm.get("base_url", "")
    api_key = input(f"  API Key [{llm.get('api_key', '')[:4] + '...' if llm.get('api_key') else ''}]: ").strip() or llm.get("api_key", "")
    model = input(f"  Model [{llm.get('model', '')}]: ").strip() or llm.get("model", "")
    if base_url or api_key or model:
        config["llm"] = {"base_url": base_url, "api_key": api_key, "model": model}
    elif "llm" not in config:
        config["llm"] = {"base_url": "", "api_key": "", "model": ""}

    print("\n── Search API Keys (optional, improves rate limits) ──")
    current_any = config.get("anysearch_api_key", "")
    anysearch_key = input(f"  AnySearch API Key [{current_any[:4] + '...' if current_any else ''}]: ").strip()
    if anysearch_key:
        config["anysearch_api_key"] = anysearch_key
    elif "anysearch_api_key" not in config:
        config["anysearch_api_key"] = ""

    current_bing = config.get("bing_key", "")
    bing_key = input(f"  Bing API Key [{current_bing[:4] + '...' if current_bing else ''}]: ").strip()
    if bing_key:
        config["bing_key"] = bing_key
    elif "bing_key" not in config:
        config["bing_key"] = ""

    from datetime import datetime, timezone
    config["init"] = {
        "completed": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    save_config(config)
    print("\n✓ Configuration saved to", CONFIG_PATH)
    print("  Run 'astromind init --check' to verify.")


# ── Doctor ──

def cmd_doctor(args):
    import importlib.util

    deps = ["httpx", "yaml", "bs4", "requests"]
    missing = [d for d in deps if importlib.util.find_spec(d) is None]

    config = load_config()
    llm_cfg, src = _resolve_llm_config(config)

    db_status = {"ok": False, "error": ""}
    try:
        from .db.database import Database, init_db
        init_db()
        Database()
        db_status = {"ok": True, "schema": "v7"}
    except Exception as e:
        db_status = {"ok": False, "error": str(e)}

    store = RunStore()
    report = {
        "dependencies": {"ok": not missing, "missing": missing},
        "config": {
            "exists": CONFIG_PATH.exists(),
            "init_completed": config.get("init", {}).get("completed", False),
            "llm_source": src,
            "llm_model": llm_cfg.get("model", ""),
        },
        "db": db_status,
        "runs": {"pending": len(store.pending_runs()), "total": len(store.list_runs())},
    }
    if _want_json(args):
        _emit(report)
        return
    print("Astromind Praxis doctor — v0.2.2")
    print(f"  dependencies: {'OK' if not missing else 'MISSING: ' + ', '.join(missing)}")
    print(f"  config:       exists={report['config']['exists']} "
          f"init={report['config']['init_completed']} llm_source={src}")
    print(f"  db:           {'OK (v7)' if db_status['ok'] else 'ERROR: ' + db_status['error']}")
    print(f"  runs:         pending={report['runs']['pending']} total={report['runs']['total']}")


# ── Resume ──

def cmd_resume(args):
    store = RunStore()
    run = store.get_run(args.run_id) if getattr(args, "run_id", None) else store.latest_pending()
    if not run:
        _err("No pending run found. Check 'astromind runs list'.")
        sys.exit(1)

    if getattr(args, "rsp_file", None) or getattr(args, "rsp", None):
        rsp_path = getattr(args, "rsp_file", None)
        if not rsp_path and getattr(args, "rsp", None):
            tmp = store._run_dir(run.id) / "rsp-inline.json"
            tmp.write_text(args.rsp, encoding="utf-8")
            rsp_path = str(tmp)
        try:
            store.submit_response(run.id, rsp_path)
        except ValueError as e:
            _err(str(e))
            sys.exit(1)

    _set_current_run(run)
    _rerun(run)


# ── Runs 管理 ──

def cmd_runs(args):
    store = RunStore()
    if getattr(args, "prune", False):
        removed = store.prune(getattr(args, "days", 14))
        if _want_json(args):
            _emit({"removed": removed, "count": len(removed)})
        else:
            print(f"Pruned {len(removed)} runs: {', '.join(removed) if removed else '(none)'}")
        return
    runs = [
        {
            "id": r.id,
            "kind": r.kind,
            "status": r.status,
            "track_id": r.track_id,
            "session_id": r.session_id,
            "created_at": r.created_at,
        }
        for r in store.list_runs()
    ]
    if _want_json(args):
        _emit({"runs": runs})
    else:
        if not runs:
            print("No runs found.")
            return
        print("Runs:")
        for r in runs:
            print(f"  {r['id']:<32} {r['kind']:<20} {r['status']:<16} created={r['created_at']}")


# ── Teach subcommands ──

def _create_orchestrator(config: dict, run_store=None, run=None, user_name: str = "default"):
    """Create TeachingOrchestrator for a user.

    v0.2.1:
      - LLM 双供给：直连 API（config/继承）或 CheckpointLLMClient（agent 充当 LLM）
      - SearchClient 注入 store/run：搜索缓存幂等 + Tier 4 checkpoint
      - user/track 幂等（SELECT 已有则复用，重放安全）
    """
    from .db.database import Database, init_db
    from .llm.client import LLMClient
    from .runs.checkpoint_llm import CheckpointLLMClient
    from .search.client import SearchClient
    from .teaching.workflow import TeachingOrchestrator

    init_db()
    db = Database()

    # ── LLM ──
    llm_config, _ = _resolve_llm_config(config)
    if llm_config.get("base_url") and llm_config.get("api_key") and llm_config.get("model"):
        llm = LLMClient(
            base_url=llm_config["base_url"],
            api_key=llm_config["api_key"],
            model=llm_config["model"],
        )
    elif run_store is not None and run is not None:
        # checkpoint 协议：agent 充当 LLM
        llm = CheckpointLLMClient(run_store, run)
    else:
        # 只读命令（status/next）不需要 LLM：占位客户端（chat 不会被调用）
        llm = LLMClient(base_url="", api_key="", model="")

    # ── Search ──
    search = SearchClient(
        anysearch_api_key=config.get("anysearch_api_key", ""),
        bing_api_key=config.get("bing_key", ""),
        is_agent_mode=is_agent_mode(),
        store=run_store,
        run=run,
    )

    # ── User: lookup by name (users.id is INTEGER) ──
    user_row = db.fetch_one(
        "SELECT id FROM users WHERE name = ?", [user_name]
    )
    if not user_row:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO users (name, display_name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            [user_name, user_name, now, now],
        )
        user_row = db.fetch_one("SELECT id FROM users WHERE name = ?", [user_name])
        if not user_row:
            raise RuntimeError(f"Failed to create user '{user_name}'")

    db_user_id = user_row["id"]

    # ── Track: get active or create new ──
    track_row = db.fetch_one(
        "SELECT id FROM tracks WHERE user_id = ? AND status = 'active' ORDER BY id DESC LIMIT 1",
        [db_user_id],
    )

    if not track_row:
        args_topic = getattr(sys, '_args_topic', "自定义学习")
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO tracks (user_id, name, target_type, status, priority, created_at, updated_at) "
            "VALUES (?, ?, ?, 'active', 3, ?, ?)",
            [db_user_id, args_topic, "interest", now, now],
        )
        track_row = db.fetch_one(
            "SELECT id FROM tracks WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            [db_user_id],
        )
        if not track_row:
            raise RuntimeError(f"Failed to create track for user '{user_name}'")

    return TeachingOrchestrator(
        db, llm, search, str(db_user_id), track_row["id"],
        run=run, run_store=run_store,
    )


def cmd_teach_diagnose(args):
    topic = getattr(args, "topic", None)
    if not topic:
        _err("Topic is required: teach diagnose <topic>")
        sys.exit(1)

    config = load_config()
    if not config.get("init", {}).get("completed"):
        _err("Not initialized. Run 'astromind init' first.")
        sys.exit(1)

    self_assessment = getattr(args, "self_assessment", 3) or 3
    description = getattr(args, "description", "") or ""

    store, run = _get_run_context("teach_diagnose", {
        "topic": topic,
        "self_assessment": self_assessment,
        "description": description,
        "json": bool(getattr(args, "json", False)),
        "agent": is_agent_mode(),
    })
    sys._args_topic = topic  # 新 track 创建时以主题命名
    orch = _create_orchestrator(config, store, run)

    if not _want_json(args):
        print(f"Diagnosing topic: {topic}...")
    result = orch.run_diagnosis(topic, self_assessment, description)

    store.mark_done(run)
    diagnosis = result.get("diagnosis", {})
    payload = {
        "session_id": result["session_id"],
        "level": diagnosis.get("level", "?"),
        "concepts": len(diagnosis.get("node_ids", [])),
        "gaps": diagnosis.get("gaps", []),
        "misconceptions": diagnosis.get("misconceptions", []),
        "recommended_path": diagnosis.get("recommended_path", []),
    }
    if _want_json(args):
        _emit(payload)
        return
    print(f"\n✓ Diagnosis complete (session #{result['session_id']})")
    print(f"  Level: {payload['level']}/5")
    print(f"  Concepts: {payload['concepts']}")
    print(f"  Gaps: {len(payload['gaps'])}")
    print(f"  Misconceptions: {len(payload['misconceptions'])}")
    print("\nRun 'astromind teach session <id>' to start teaching.")


def cmd_teach_session(args):
    config = load_config()
    store, run = _get_run_context("teach_session", {
        "session_id": args.session_id,
        "json": bool(getattr(args, "json", False)),
        "agent": is_agent_mode(),
    })
    orch = _create_orchestrator(config, store, run)

    result = orch.run_teaching_session(args.session_id)

    if result.get("status") == "completed":
        store.mark_done(run)
        if _want_json(args):
            _emit({"status": "completed", "message": "All nodes completed"})
        else:
            print("All nodes completed! Run 'astromind teach assess <id>' for final assessment.")
        return

    if _want_json(args):
        # agent 模式：输出教学内容+题目，落题库供 teach answer，exit 77 等用户答题
        store.mark_done(run)
        sm = orch.session_manager
        session = sm.get_session(args.session_id)
        state = (session or {}).get("state_data", {})
        state["questions_pending"] = {
            "node_id": result["node_id"],
            "node_name": result["node_name"],
            "questions": result.get("questions", []),
        }
        sm.update_session(args.session_id, state_data=state)
        _emit({
            "need": "answers",
            "session_id": args.session_id,
            "node_id": result["node_id"],
            "node_name": result["node_name"],
            "rendered": result.get("rendered", ""),
            "questions": result.get("questions", []),
            "next_action": "collect answers from user, then run 'astromind teach answer <session_id> --answers-file <path>'",
        })
        sys.exit(EXIT_NEEDS_ANSWERS)

    # 人类交互模式（v0.2.2：不再逐题评估，题目打印后由 teach answer 批量处理）
    print(result.get("rendered", ""))
    questions = result.get("questions", [])
    for i, q in enumerate(questions):
        print(f"\n--- Question {i + 1} ---")
        print(q["question"])
        if q.get("options"):
            for opt in q["options"]:
                print(f"  {opt}")
    print("\nSubmit answers via 'astromind teach answer <session_id> --answers-file <path>'")

    next_node = orch.get_next_node(args.session_id)
    if next_node:
        print(f"\nNext node ID: {next_node}")
        print("Run 'astromind teach session <id>' again to continue.")
    else:
        print("\nAll nodes completed! Run 'astromind teach assess <id>' for assessment.")


def cmd_teach_assess(args):
    config = load_config()
    store, run = _get_run_context("teach_assess", {
        "session_id": args.session_id,
        "json": bool(getattr(args, "json", False)),
        "agent": is_agent_mode(),
    })
    orch = _create_orchestrator(config, store, run)

    report = orch.run_assessment(args.session_id)
    store.mark_done(run)

    if _want_json(args):
        _emit(report)
        return
    print("\n=== Assessment Report ===")
    print(f"Overall Level: {report.get('overall_level', '?')}/5")
    print()
    if report.get("concept_mastery"):
        print("Concept Mastery:")
        for c in report["concept_mastery"]:
            emoji = {"mastered": "✓", "learning": "→", "struggling": "!"}
            m = emoji.get(c.get("status", ""), "?")
            print(f"  {m} {c['concept']}: L{c['level']}/5")
    print()
    if report.get("weaknesses"):
        print("Weaknesses:")
        for w in report["weaknesses"]:
            print(f"  - {w}")
    print()
    if report.get("recommendations"):
        print("Recommendations:")
        for r in report["recommendations"]:
            print(f"  - {r}")
    print()
    if report.get("review_plan"):
        print("Review Plan:")
        for rp in report["review_plan"]:
            print(f"  - {rp['concept']}: review in {rp.get('interval_days', '?')} days")


def cmd_teach_status(args):
    config = load_config()
    _init_db()

    from .db.database import Database
    from .teaching.session import SessionManager

    db = Database()
    sm = SessionManager(db)
    session = sm.get_session(args.session_id)

    if not session:
        if _want_json(args):
            _emit({"error": f"Session #{args.session_id} not found"})
        else:
            print(f"Session #{args.session_id} not found.")
        return

    from .teaching.render import render_session_status
    completed = session.get("completed_nodes", [])
    diagnosis = session.get("diagnosis", {})
    all_nodes = diagnosis.get("node_ids", [])

    if _want_json(args):
        orch = _create_orchestrator(config)
        next_n = orch.get_next_node(args.session_id)
        _emit({
            "session_id": args.session_id,
            "topic": session.get("topic", ""),
            "status": session.get("status", ""),
            "progress": f"{len(completed)}/{len(all_nodes)}",
            "completed_nodes": completed,
            "next_node": next_n,
        })
        return

    print(render_session_status(session))
    if all_nodes:
        print(f"Progress: {len(completed)}/{len(all_nodes)} nodes")
        from .teaching.workflow import TeachingOrchestrator
        orch = _create_orchestrator(config)
        next_n = orch.get_next_node(args.session_id)
        if next_n:
            next_node_data = db.fetch_one(
                "SELECT name FROM knowledge_nodes WHERE id = ?", [next_n]
            )
            next_name = next_node_data["name"] if next_node_data else str(next_n)
            print(f"Next: {next_name} (node #{next_n})")


REVIEW_PENDING_PATH = CONFIG_DIR / "review_pending.json"


def _load_review_pending() -> dict | None:
    try:
        with open(REVIEW_PENDING_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if data and data.get("items"):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return None


def _save_review_pending(data: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    from .runs.store import _atomic_write
    _atomic_write(REVIEW_PENDING_PATH, data)


def _clear_review_pending():
    try:
        REVIEW_PENDING_PATH.unlink()
    except OSError:
        pass


def _load_answers(args) -> list[str]:
    """从 --answers-file 或 --answers 读取答案数组。"""
    if getattr(args, "answers_file", None):
        try:
            with open(args.answers_file, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            _err(f"Cannot read answers file: {e}")
            sys.exit(1)
        answers = data.get("answers") if isinstance(data, dict) else data
    elif getattr(args, "answers", None):
        try:
            answers = json.loads(args.answers)
        except json.JSONDecodeError as e:
            _err(f"Invalid --answers JSON: {e}")
            sys.exit(1)
    else:
        _err("Provide --answers-file <path> or --answers '<json array>'")
        sys.exit(1)
    if not isinstance(answers, list) or not all(isinstance(a, str) for a in answers):
        _err("Answers must be a JSON array of strings: {\"answers\": [...]}")
        sys.exit(1)
    return answers


def cmd_teach_answer(args):
    """提交答案：教学答题（questions_pending）或复习答题（review_pending）.

    重放语义：答案 JSON 持久化进 run.argv，resume 重放时可无 --answers-file 直接恢复。
    """
    config = load_config()
    session_id = args.session_id

    from .db.database import Database
    from .teaching.session import SessionManager
    _init_db()
    db = Database()
    sm = SessionManager(db)

    is_review = bool(getattr(args, "review", False))
    answers = _load_answers(args)
    answers_json = json.dumps(answers, ensure_ascii=False)

    if is_review:
        pending = _load_review_pending()
        if not pending:
            _err("No review questions pending. Run 'astromind teach review' first.")
            sys.exit(1)
        items = pending.get("items", [])
        # 平铺 answers 映射回各节点
        idx = 0
        items_with_answers = []
        for item in items:
            n = len(item.get("questions", []))
            items_with_answers.append({
                **item,
                "answers": answers[idx:idx + n],
            })
            idx += n
        if idx != len(answers):
            _err(f"Answers count ({len(answers)}) != questions count ({idx})")
            sys.exit(1)
        store, run = _get_run_context("teach_answer_review", {
            "session_id": session_id,
            "answers": answers_json,
            "review": True,
            "json": bool(getattr(args, "json", False)),
            "agent": is_agent_mode(),
        })
        orch = _create_orchestrator(config, store, run)
        result = orch.run_review_answers(session_id, items_with_answers)
        store.mark_done(run)
        _clear_review_pending()
    else:
        session = sm.get_session(session_id)
        state = (session or {}).get("state_data", {}) or {}
        pending = state.get("questions_pending")
        if not pending:
            _err(f"Session #{session_id} has no pending questions. Run 'teach session {session_id}' first.")
            sys.exit(1)
        if len(pending.get("questions", [])) != len(answers):
            _err(f"Answers count ({len(answers)}) != questions count ({len(pending.get('questions', []))})")
            sys.exit(1)
        store, run = _get_run_context("teach_answer", {
            "session_id": session_id,
            "answers": answers_json,
            "review": False,
            "json": bool(getattr(args, "json", False)),
            "agent": is_agent_mode(),
        })
        orch = _create_orchestrator(config, store, run)
        result = orch.run_answer_batch(
            session_id, pending["node_id"], pending["questions"], answers
        )
        store.mark_done(run)
        # 清题库
        state["questions_pending"] = None
        sm.update_session(session_id, state_data=state)

    # 下一节点提示
    try:
        next_n = orch.get_next_node(session_id)
    except Exception:
        next_n = None
    if is_review:
        result["next_node"] = None
        result["message"] = "Review complete"
    else:
        result["next_node"] = next_n
        result["message"] = (
            f"Node {result['node_name']} done. "
            "Run 'teach session <id>' for next node, or 'teach assess <id>' for assessment."
            if next_n else
            "All nodes completed! Run 'teach assess <id>' for final assessment."
        )

    if _want_json(args):
        _emit(result)
    else:
        print(f"\n=== {result.get('node_name', 'Review')} 评估 ===")
        for r in result.get("results", []):
            status = "✓" if r.get("correct") else "✗"
            print(f"  {status} L{r.get('level')}/5: {r.get('question', '')[:60]}")
        if result.get("overall_feedback"):
            print(f"  整体反馈: {result['overall_feedback']}")
        print(f"  SM-2: interval={result['sm2'].get('interval_days')}d reps={result['sm2'].get('repetitions')} ef={result['sm2'].get('ef')}")
        print(f"  {result['message']}")


def cmd_teach_review(args):
    """到期节点复习：出题 → exit 77 → teach answer --review."""
    config = load_config()
    store, run = _get_run_context("teach_review", {
        "track_id": getattr(args, "track_id", None),
        "limit": getattr(args, "limit", 5),
        "json": bool(getattr(args, "json", False)),
        "agent": is_agent_mode(),
    })
    orch = _create_orchestrator(config, store, run)

    nodes = orch.get_due_nodes(limit=getattr(args, "limit", 5))
    if not nodes:
        store.mark_done(run)
        if _want_json(args):
            _emit({"due": 0, "message": "No due reviews. Great job!"})
        else:
            print("No due reviews. Great job!")
        return

    # LLM 出题（checkpoint 链：未答时 exit 75）
    items = orch.run_review_questions(nodes)
    store.mark_done(run)

    # 题库落盘，供 teach answer --review 消费
    _save_review_pending({
        "track_id": orch.track_id,
        "items": items,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    if _want_json(args):
        _emit({
            "need": "answers",
            "review": True,
            "due": len(nodes),
            "items": items,
            "next_action": "collect answers from user, then run 'astromind teach answer <session_id> --review --answers-file <path>'",
        })
        sys.exit(EXIT_NEEDS_ANSWERS)

    # 人类模式
    for item in items:
        print(f"\n## 复习: {item['node_name']}")
        for i, q in enumerate(item["questions"], 1):
            print(f"  Q{i}. {q['question']}")
            if q.get("options"):
                for opt in q["options"]:
                    print(f"      {opt}")
    print("\nRun 'astromind teach answer <session_id> --review --answers-file <path>' to submit answers.")


def cmd_teach_next(args):
    config = load_config()
    orch = _create_orchestrator(config)
    next_node = orch.get_next_node(args.session_id)
    if next_node:
        n = orch.db.fetch_one(
            "SELECT name FROM knowledge_nodes WHERE id = ?", [next_node]
        )
        name = n["name"] if n else "unknown"
        if _want_json(args):
            _emit({"next_node": next_node, "name": name})
        else:
            print(f"Next node: #{next_node} ({name})")
    else:
        if _want_json(args):
            _emit({"next_node": None, "message": "No pending nodes"})
        else:
            print("No pending nodes. Session may be complete.")


# ── 只读/维护命令（dispatch 修复，人类输出为主）──

def _init_db():
    from .db.database import init_db
    init_db()


def cmd_node_search(args):
    _init_db()
    from .db import dao_node
    results = dao_node.search_nodes(args.keyword, args.track, args.limit)
    if _want_json(args):
        _emit([dict(r) for r in results])
        return
    if not results:
        print("No results found.")
        return
    print("Search results:")
    for n in results:
        t = n.get("node_type", "concept") or "concept"
        print("  #%4d  [%-12s]  %s" % (n["id"], t, n["name"]))
        if n.get("content"):
            print("         %s..." % n["content"][:100])

def cmd_node_content(args):
    _init_db()
    from .db import dao_node
    if args.content:
        node = dao_node.update_node_content(args.node_id, args.content)
        msg = "Node #%d content updated" % args.node_id if node else "Node #%d not found" % args.node_id
        if _want_json(args):
            _emit({"ok": bool(node), "message": msg})
        else:
            print(msg)
    elif args.file:
        try:
            node = dao_node.import_node_content(args.node_id, args.file)
            if _want_json(args):
                _emit({"ok": bool(node), "message": f"Imported from {args.file}"})
            elif node:
                print("Node #%d content imported from %s" % (args.node_id, args.file))
        except FileNotFoundError as e:
            _err(str(e))
            sys.exit(1)
    else:
        node = dao_node.get_node(args.node_id)
        if not node:
            if _want_json(args):
                _emit({"error": f"Node #{args.node_id} not found"})
            else:
                print("Node #%d not found" % args.node_id)
            return
        if _want_json(args):
            _emit(dict(node))
        else:
            print("Node #%d: %s" % (node["id"], node["name"]))
            print("  Level: %s" % (node.get("current_level", 1)))


def cmd_track_list(args):
    _init_db()
    from .db import dao_track
    tracks = dao_track.list_tracks(args.user_id, args.status)
    if _want_json(args):
        _emit([dict(t) for t in tracks])
        return
    if not tracks:
        print("No tracks found.")
        return
    print("Tracks:")
    for t in tracks:
        print("  #%3d  %-30s  type=%-8s  state=%-12s  priority=%d" % (t["id"], t["name"], t["target_type"], t.get("current_state", "?"), t["priority"]))


def cmd_review_due(args):
    _init_db()
    from .db import dao_node
    if args.user_id:
        nodes = dao_node.get_due_nodes(user_id=args.user_id)
    elif args.track_id:
        nodes = dao_node.get_due_nodes(track_id=args.track_id)
    else:
        nodes = dao_node.get_due_nodes()
    if _want_json(args):
        _emit({"due": [dict(n) for n in nodes]})
        return
    if not nodes:
        print("No due reviews. Great job!")
        return
    print("Due reviews (%d):" % len(nodes))
    for n in nodes:
        print("  #%4d  %-30s  next_review=%-12s  level=%d" % (n["id"], n["name"], n.get("next_review", "?") or "?", n.get("current_level", 1)))


def cmd_report_dashboard(args):
    _init_db()
    from .core.indicators import Dashboard
    from .db.database import get_connection
    conn = get_connection()
    try:
        dash = Dashboard(conn)
        _emit(dash.overall(args.user_id))
    finally:
        conn.close()


def cmd_schedule_today(args):
    _init_db()
    from .scheduler.multi_track import MultiTrackScheduler
    sched = MultiTrackScheduler()
    _emit(sched.get_schedule(args.user_id, args.total_minutes))


def cmd_misconception_add(args):
    _init_db()
    from .db import dao_misconception
    mc = dao_misconception.add_misconception(
        user_id=args.user_id, node_id=args.node_id,
        misconception=args.misconception,
        correction=args.correction or "",
        category=args.category or "",
    )
    if _want_json(args):
        _emit({"id": mc["id"], "ok": True})
    else:
        print("Misconception recorded: #%d" % mc["id"])


# ── Parser ──

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="astromind",
        description="星知·笃行 — 认知科学驱动的元学习引擎 v0.2.2",
    )
    # 全局参数通过 parents 注入每个子命令（支持放在子命令后: teach diagnose X --json）
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    common.add_argument("--agent", action="store_true", help="Agent mode (explicit; alt: ASTROMIND_AGENT=1)")
    parser.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--agent", action="store_true", help=argparse.SUPPRESS)

    sub = parser.add_subparsers(dest="command", help="Commands")

    # init
    init_p = sub.add_parser("init", help="Initialize configuration", parents=[common])
    init_p.add_argument("--check", action="store_true", help="Check configuration status")
    init_p.add_argument("--reset", action="store_true", help="Reset and reconfigure")
    init_p.add_argument("--llm-base-url", help="Non-interactive LLM base URL")
    init_p.add_argument("--llm-api-key", help="Non-interactive LLM API key")
    init_p.add_argument("--llm-model", help="Non-interactive LLM model")
    init_p.set_defaults(func=cmd_init)

    # doctor
    doctor_p = sub.add_parser("doctor", help="Dependency/config/DB self-check", parents=[common])
    doctor_p.set_defaults(func=cmd_doctor)

    # resume
    resume_p = sub.add_parser("resume", help="Consume agent response and continue pending run", parents=[common])
    resume_p.add_argument("run_id", nargs="?", help="Run id (default: latest pending)")
    resume_p.add_argument("--rsp-file", help="Path to response JSON file written by agent")
    resume_p.add_argument("--rsp", help="Inline response JSON string")
    resume_p.set_defaults(func=cmd_resume)

    # runs
    runs_p = sub.add_parser("runs", help="Run management", parents=[common])
    runs_p.add_argument("action", nargs="?", choices=["list"], help="Subcommand (list)")
    runs_p.add_argument("--prune", action="store_true", help="Prune done/failed runs")
    runs_p.add_argument("--days", type=int, default=14, help="Prune older than N days")
    runs_p.set_defaults(func=cmd_runs)

    # teach
    teach_p = sub.add_parser("teach", help="Teaching commands", parents=[common])
    teach_sub = teach_p.add_subparsers(dest="teach_command", help="Teach subcommands")

    diag_p = teach_sub.add_parser("diagnose", help="Diagnose a topic", parents=[common])
    diag_p.add_argument("topic", nargs="?", help="Topic to learn")
    diag_p.add_argument("--self-assessment", type=int, choices=range(1, 6), default=3,
                        help="User self-assessed level 1-5")
    diag_p.add_argument("--description", help="User self-description of understanding")
    diag_p.set_defaults(func=cmd_teach_diagnose)

    sess_p = teach_sub.add_parser("session", help="Run a teaching session", parents=[common])
    sess_p.add_argument("session_id", type=int, help="Session ID")
    sess_p.set_defaults(func=cmd_teach_session)

    assess_p = teach_sub.add_parser("assess", help="Run comprehensive assessment", parents=[common])
    assess_p.add_argument("session_id", type=int, help="Session ID")
    assess_p.set_defaults(func=cmd_teach_assess)

    status_p = teach_sub.add_parser("status", help="Show session status", parents=[common])
    status_p.add_argument("session_id", type=int, help="Session ID")
    status_p.set_defaults(func=cmd_teach_status)

    next_p = teach_sub.add_parser("next", help="Show next node", parents=[common])
    next_p.add_argument("session_id", type=int, help="Session ID")
    next_p.set_defaults(func=cmd_teach_next)

    answer_p = teach_sub.add_parser("answer", help="Submit answers for pending questions", parents=[common])
    answer_p.add_argument("session_id", type=int, help="Session ID")
    answer_p.add_argument("--answers-file", help="Path to answers JSON: {\"answers\": [...]}")
    answer_p.add_argument("--answers", help="Inline answers JSON array string")
    answer_p.add_argument("--review", action="store_true", help="Answer review questions instead of teaching questions")
    answer_p.set_defaults(func=cmd_teach_answer)

    review_p = teach_sub.add_parser("review", help="Run due-node review (retrieval practice)", parents=[common])
    review_p.add_argument("--track", dest="track_id", type=int, help="Track id (default: active track)")
    review_p.add_argument("--limit", type=int, default=5, help="Max due nodes to review")
    review_p.set_defaults(func=cmd_teach_review)

    # node
    p_node = sub.add_parser("node", help="Knowledge nodes", parents=[common])
    ns = p_node.add_subparsers(dest="node_command")
    p_ns = ns.add_parser("search", help="Search", parents=[common])
    p_ns.add_argument("keyword")
    p_ns.add_argument("--track", type=int)
    p_ns.add_argument("--limit", type=int, default=20)
    p_ns.set_defaults(func=cmd_node_search)
    p_nc = ns.add_parser("content", help="View/set content", parents=[common])
    p_nc.add_argument("node_id", type=int)
    p_nc.add_argument("--content")
    p_nc.add_argument("--file")
    p_nc.set_defaults(func=cmd_node_content)

    # track
    p_tr = sub.add_parser("track", help="List tracks", parents=[common])
    p_tr.add_argument("--user", dest="user_id", type=int)
    p_tr.add_argument("--status")
    p_tr.set_defaults(func=cmd_track_list)

    # review
    p_rv = sub.add_parser("review", help="Due reviews", parents=[common])
    p_rv.add_argument("--user", dest="user_id", type=int)
    p_rv.add_argument("--track", dest="track_id", type=int)
    p_rv.set_defaults(func=cmd_review_due)

    # report
    p_rp = sub.add_parser("report", help="Dashboard", parents=[common])
    p_rp.add_argument("user_id", type=int)
    p_rp.set_defaults(func=cmd_report_dashboard)

    # schedule
    p_sc = sub.add_parser("schedule", help="Today", parents=[common])
    p_sc.add_argument("--user", dest="user_id", type=int, default=1)
    p_sc.add_argument("--minutes", dest="total_minutes", type=int)
    p_sc.set_defaults(func=cmd_schedule_today)

    # misconception
    p_mc = sub.add_parser("misconception", help="Record misconception", parents=[common])
    p_mc.add_argument("user_id", type=int)
    p_mc.add_argument("node_id", type=int)
    p_mc.add_argument("misconception", help="Description")
    p_mc.add_argument("--correction")
    p_mc.add_argument("--category", choices=["overgeneralization", "term_confusion", "surface_analogy", "missing_boundary", "order_reversal", "other"])
    p_mc.set_defaults(func=cmd_misconception_add)

    return parser


# ── Dispatch 表 ──

DISPATCH = {
    "init": cmd_init,
    "doctor": cmd_doctor,
    "resume": cmd_resume,
    "runs": cmd_runs,
    "teach_diagnose": cmd_teach_diagnose,
    "teach_session": cmd_teach_session,
    "teach_assess": cmd_teach_assess,
    "teach_status": cmd_teach_status,
    "teach_next": cmd_teach_next,
    "teach_answer": cmd_teach_answer,
    "teach_answer_review": cmd_teach_answer,
    "teach_review": cmd_teach_review,
    "node_search": cmd_node_search,
    "node_content": cmd_node_content,
    "track": cmd_track_list,
    "review": cmd_review_due,
    "report": cmd_report_dashboard,
    "schedule": cmd_schedule_today,
    "misconception": cmd_misconception_add,
}


def _resolve_cmd(args):
    if args.command is None:
        return None
    if args.command in ("init", "doctor", "resume", "runs"):
        return args.command
    if args.command == "teach":
        tc = getattr(args, "teach_command", None)
        return f"teach_{tc}" if tc else None
    if args.command == "node":
        nc = getattr(args, "node_command", None)
        return f"node_{nc}" if nc else None
    return args.command  # track/review/report/schedule/misconception


def main():
    parser = build_parser()
    args = parser.parse_args()

    # 显式 agent 模式（优先级: flag > env > 交给命令内部逻辑）
    _set_agent_mode(
        getattr(args, "agent", False) or os.environ.get("ASTROMIND_AGENT") == "1"
    )

    cmd_key = _resolve_cmd(args)
    if cmd_key is None:
        parser.print_help()
        sys.exit(0)

    try:
        DISPATCH[cmd_key](args)
    except NeedsLLM as e:
        _emit({
            "need": "llm",
            "run_id": e.run_id,
            "req_file": str(e.req_file),
            "step": e.step,
            "next_action": (
                f"Read {e.req_file.name} in the run directory, generate the response "
                "using your own model, write it to the sibling rsp file, then run "
                f"'astromind resume {e.run_id} --rsp-file <path>'"
            ),
        })
        sys.exit(EXIT_NEEDS_LLM)
    except NeedsSearch as e:
        _emit({
            "need": "search",
            "run_id": e.run_id,
            "req_file": str(e.req_file),
            "step": e.step,
            "next_action": (
                f"Search for the query in {e.req_file.name}, write results as JSON array "
                f"to the sibling rsp file, then run 'astromind resume {e.run_id} --rsp-file <path>'"
            ),
        })
        sys.exit(EXIT_NEEDS_SEARCH)
    except KeyboardInterrupt:
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as e:
        logger.exception("Command failed")
        _err(f"{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
