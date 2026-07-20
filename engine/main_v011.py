#!/usr/bin/env python3
"""Astromind Praxis CLI — 星知·笃行 认知科学驱动的元学习引擎 (v0.1.1).

用法:
  astromind init                    交互式初始化配置
  astromind init --check            检查配置状态
  astromind init --reset            重新配置
  astromind teach diagnose <id>     诊断阶段
  astromind teach session <id>      教学会话
  astromind teach assess <id>       综合评估
  astromind teach status <id>       会话状态
  astromind teach next <id>         下一个待学节点
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".astromind-praxis"
CONFIG_PATH = CONFIG_DIR / "config.yaml"


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


def save_config(config: dict):
    import yaml
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def check_config() -> dict:
    config = load_config()
    status = {
        "config_exists": CONFIG_PATH.exists(),
        "init_completed": config.get("init", {}).get("completed", False),
        "llm_configured": bool(config.get("llm", {}).get("api_key")),
        "anysearch_configured": bool(config.get("anysearch_api_key")),
        "bing_configured": bool(config.get("bing_key")),
    }
    return status


# ── Init command ──

def cmd_init(args):
    if args.check:
        status = check_config()
        print("Config check:")
        print(f"  Config file:     {'OK' if status['config_exists'] else 'MISSING'}")
        print(f"  Init completed:  {'YES' if status['init_completed'] else 'NO'}")
        print(f"  LLM configured:  {'YES' if status['llm_configured'] else 'NO (uses Stdio)'}")
        print(f"  AnySearch key:   {'YES' if status['anysearch_configured'] else 'NO (anonymous)'}")
        print(f"  Bing key:        {'YES' if status['bing_configured'] else 'NO (WebFetch fallback)'}")
        return

    if args.reset:
        config = {}
    else:
        config = load_config()

    print("=" * 50)
    print("  星知·笃行 (Astromind Praxis) v0.1.1 — Configuration Wizard")
    print("=" * 50)
    print("(Press Enter to skip any field)\n")

    # LLM config
    print("── LLM Configuration ──")
    print("  Leave blank to use Stdio protocol (agent's own model).")
    llm = config.get("llm", {})
    base_url = input(f"  Base URL [{llm.get('base_url', '')}]: ").strip() or llm.get("base_url", "")
    api_key = input(f"  API Key [{llm.get('api_key', '')[:4] + '...' if llm.get('api_key') else ''}]: ").strip() or llm.get("api_key", "")
    model = input(f"  Model [{llm.get('model', '')}]: ").strip() or llm.get("model", "")
    if base_url or api_key or model:
        config["llm"] = {"base_url": base_url, "api_key": api_key, "model": model}
    elif "llm" not in config:
        config["llm"] = {"base_url": "", "api_key": "", "model": ""}

    # Search API keys
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

    # Mark init complete
    from datetime import datetime, timezone
    config["init"] = {
        "completed": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    save_config(config)
    print("\n✓ Configuration saved to", CONFIG_PATH)
    print("  Run 'astromind init --check' to verify.")


# ── Teach subcommands ──

def _create_orchestrator(config: dict, user_name: str = "default"):
    """Create TeachingOrchestrator for a user.

    Flow:
      1. Init DB
      2. Look up user by name in users table (INTEGER id)
      3. Create user if not exists
      4. Get or create an active track for that user
      5. Return orchestrator bound to the track
    """
    from .db.database import Database, init_db
    from .llm.client import LLMClient
    from .search.client import SearchClient
    from .teaching.workflow import TeachingOrchestrator

    init_db()
    db = Database()

    # ── LLM ──
    llm_config = config.get("llm", {})
    llm = LLMClient(
        base_url=llm_config.get("base_url", ""),
        api_key=llm_config.get("api_key", ""),
        model=llm_config.get("model", ""),
    )

    # ── Search ──
    search = SearchClient(
        anysearch_api_key=config.get("anysearch_api_key", ""),
        bing_api_key=config.get("bing_key", ""),
        is_agent_mode=not bool(config.get("llm", {}).get("api_key")),
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

    return TeachingOrchestrator(db, llm, search, str(db_user_id), track_row["id"])


def cmd_teach_diagnose(args):
    config = load_config()
    if not config.get("init", {}).get("completed"):
        print("Not initialized. Run 'astromind init' first.")
        sys.exit(1)

    topic = args.topic or input("Topic to learn: ").strip()
    if not topic:
        print("Topic is required.")
        sys.exit(1)

    sys._args_topic = topic  # for track creation
    orch = _create_orchestrator(config)

    print(f"Diagnosing topic: {topic}...")
    result = orch.run_diagnosis(topic)

    print(f"\n✓ Diagnosis complete (session #{result['session_id']})")
    print(f"  Level: {result['diagnosis'].get('level', '?')}/5")
    print(f"  Concepts: {len(result['diagnosis'].get('node_ids', []))}")
    print(f"  Gaps: {len(result['diagnosis'].get('gaps', []))}")
    print(f"  Misconceptions: {len(result['diagnosis'].get('misconceptions', []))}")
    print("\nRun 'astromind teach session <id>' to start teaching.")


def cmd_teach_session(args):
    config = load_config()
    orch = _create_orchestrator(config)

    session_id = args.session_id
    result = orch.run_teaching_session(session_id)

    if result.get("status") == "completed":
        print("All nodes completed! Run 'astromind teach assess <id>' for final assessment.")
        return

    print(result.get("rendered", ""))

    # Track pending answers
    questions = result.get("questions", [])
    for i, q in enumerate(questions):
        print(f"\n--- Question {i + 1} ---")
        print(q["question"])
        if q.get("options"):
            for opt in q["options"]:
                print(f"  {opt}")

        # In standalone mode, wait for user input
        if not sys.stdin.isatty():
            answer = "(simulated)"
        else:
            answer = input("\nYour answer: ").strip()

        eval_result = orch.submit_answer(
            session_id, result["node_id"], q, answer
        )
        status = "CORRECT" if eval_result["correct"] else "WRONG"
        level_str = f"L{eval_result['level']}/5"
        print(f"  → {status}  ({level_str})")
        if eval_result.get("feedback"):
            print(f"  Feedback: {eval_result['feedback']}")

    orch.complete_node(session_id, result["node_id"])

    next_node = orch.get_next_node(session_id)
    if next_node:
        print(f"\nNext node ID: {next_node}")
        print("Run 'astromind teach session <id>' again to continue.")
    else:
        print("\nAll nodes completed! Run 'astromind teach assess <id>' for assessment.")


def cmd_teach_assess(args):
    config = load_config()
    orch = _create_orchestrator(config)

    report = orch.run_assessment(args.session_id)

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

    from .db.database import Database
    from .teaching.session import SessionManager

    db = Database()
    sm = SessionManager(db)
    session = sm.get_session(args.session_id)

    if not session:
        print(f"Session #{args.session_id} not found.")
        return

    from .teaching.render import render_session_status
    print(render_session_status(session))

    completed = session.get("completed_nodes", [])
    diagnosis = session.get("diagnosis", {})
    all_nodes = diagnosis.get("node_ids", [])
    if all_nodes:
        print(f"Progress: {len(completed)}/{len(all_nodes)} nodes")
        # Check next
        from .teaching.workflow import TeachingOrchestrator
        orch = _create_orchestrator(config)
        next_n = orch.get_next_node(session_id=args.session_id)
        if next_n:
            next_node_data = db.fetch_one(
                "SELECT name FROM knowledge_nodes WHERE id = ?", [next_n]
            )
            next_name = next_node_data["name"] if next_node_data else str(next_n)
            print(f"Next: {next_name} (node #{next_n})")


def cmd_teach_next(args):
    config = load_config()
    orch = _create_orchestrator(config)
    next_node = orch.get_next_node(args.session_id)
    if next_node:
        n = orch.db.fetch_one(
            "SELECT name FROM knowledge_nodes WHERE id = ?", [next_node]
        )
        name = n["name"] if n else "unknown"
        print(f"Next node: #{next_node} ({name})")
    else:
        print("No pending nodes. Session may be complete.")


# ── Main CLI ──

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="astromind",
        description="星知·笃行 — 认知科学驱动的元学习引擎 v0.1.1",
    )

    sub = parser.add_subparsers(dest="command", help="Commands")

    # init
    init_p = sub.add_parser("init", help="Initialize configuration")
    init_p.add_argument("--check", action="store_true", help="Check configuration status")
    init_p.add_argument("--reset", action="store_true", help="Reset and reconfigure")
    init_p.set_defaults(func=cmd_init)

    # teach
    teach_p = sub.add_parser("teach", help="Teaching commands")
    teach_sub = teach_p.add_subparsers(dest="teach_command", help="Teach subcommands")

    # teach diagnose
    diag_p = teach_sub.add_parser("diagnose", help="Diagnose a topic")
    diag_p.add_argument("topic", nargs="?", help="Topic to learn")
    diag_p.set_defaults(func=cmd_teach_diagnose)

    # teach session
    sess_p = teach_sub.add_parser("session", help="Run a teaching session")
    sess_p.add_argument("session_id", type=int, help="Session ID")
    sess_p.set_defaults(func=cmd_teach_session)

    # teach assess
    assess_p = teach_sub.add_parser("assess", help="Run comprehensive assessment")
    assess_p.add_argument("session_id", type=int, help="Session ID")
    assess_p.set_defaults(func=cmd_teach_assess)

    # teach status
    status_p = teach_sub.add_parser("status", help="Show session status")
    status_p.add_argument("session_id", type=int, help="Session ID")
    status_p.set_defaults(func=cmd_teach_status)

    # teach next
    next_p = teach_sub.add_parser("next", help="Show next node")
    next_p.add_argument("session_id", type=int, help="Session ID")
    next_p.set_defaults(func=cmd_teach_next)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "init":
        cmd_init(args)
    elif args.command == "teach":
        if not hasattr(args, "teach_command") or args.teach_command is None:
            parser.print_help()
            sys.exit(0)
        args.func(args)


def stdio_loop():
    """Stdio protocol loop: listen for [LLM_REQ] / [SEARCH_REQ] and respond.

    Used when running in agent-skill mode (not standalone CLI).
    """
    import logging
    logging.basicConfig(level=logging.WARNING)

    config = load_config()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        if line.startswith("[LLM_REQ]"):
            try:
                req = json.loads(line[len("[LLM_REQ]"):].strip())
            except json.JSONDecodeError:
                continue

            from .llm.client import LLMClient
            llm = LLMClient(
                base_url=config.get("llm", {}).get("base_url", ""),
                api_key=config.get("llm", {}).get("api_key", ""),
                model=config.get("llm", {}).get("model", ""),
            )

            try:
                result = llm.chat(
                    system_prompt=req.get("system_prompt", ""),
                    user_prompt=req.get("user_prompt", ""),
                    schema=req.get("schema"),
                    temperature=req.get("temperature", 0.7),
                    max_tokens=req.get("max_tokens", 4096),
                )
                print(f"[LLM_RSP] {json.dumps(result, ensure_ascii=False)}", flush=True)
            except Exception as e:
                print(f"[LLM_RSP] {json.dumps({'error': str(e)}, ensure_ascii=False)}", flush=True)

        elif line.startswith("[SEARCH_REQ]"):
            try:
                req = json.loads(line[len("[SEARCH_REQ]"):].strip())
            except json.JSONDecodeError:
                continue

            from .search.client import SearchClient
            search = SearchClient(
                anysearch_api_key=config.get("anysearch_api_key", ""),
                bing_api_key=config.get("bing_key", ""),
                is_agent_mode=False,  # avoid recursion
            )

            try:
                results = search.search(
                    query=req.get("query", ""),
                    max_results=req.get("max_results", 10),
                )
                print(f"[SEARCH_RSP] {json.dumps(results, ensure_ascii=False)}", flush=True)
            except Exception as e:
                print(f"[SEARCH_RSP] {json.dumps({'error': str(e)}, ensure_ascii=False)}", flush=True)


if __name__ == "__main__":
    main()
