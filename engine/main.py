#!/usr/bin/env python3
"""Astromind Praxis CLI — 星知·笃行 认知科学驱动的元学习引擎 (v0.1.2).

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
    print("  星知·笃行 (Astromind Praxis) v0.1.2 — Configuration Wizard")
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



def _init_db():
    from .db.database import init_db
    init_db()


def get_db():
    """Get Database instance with v6.1 author tables guaranteed."""
    from .db.database import init_db, Database
    init_db()
    return Database()


def cmd_node_search(args):
    _init_db()
    from .db import dao_node
    results = dao_node.search_nodes(args.keyword, args.track, args.limit)
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
        print("Node #%d content updated" % args.node_id if node else "Node #%d not found" % args.node_id)
    elif args.file:
        try:
            node = dao_node.import_node_content(args.node_id, args.file)
            if node:
                print("Node #%d content imported from %s" % (args.node_id, args.file))
        except FileNotFoundError as e:
            print("Error: %s" % e)
    else:
        node = dao_node.get_node(args.node_id)
        if not node:
            print("Node #%d not found" % args.node_id)
            return
        print("Node #%d: %s" % (node["id"], node["name"]))
        print("  Type: %s  Level: %s" % (node.get("node_type", "concept"), node.get("current_level", 1)))


def cmd_track_list(args):
    _init_db()
    from .db import dao_track
    tracks = dao_track.list_tracks(args.user_id, args.status)
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
        print(json.dumps(dash.generate(args.user_id), ensure_ascii=False, indent=2, default=str))
    finally:
        conn.close()


def cmd_graph_view(args):
    _init_db()
    from .db import dao_graph
    graph = dao_graph.get_graph(args.user_id)
    if not graph["nodes"]:
        print("No graph data for this user.")
        return
    print("Knowledge Graph (%d nodes, %d edges):" % (len(graph["nodes"]), len(graph["edges"])))
    print("")
    for n in graph["nodes"]:
        print("  #%3d  %-30s  level=%d" % (n["id"], n["name"], n.get("level", 1)))
    if graph["edges"]:
        print("")
        for e in graph["edges"]:
            src = next((n["name"] for n in graph["nodes"] if n["id"] == e["source_node_id"]), "#%d" % e["source_node_id"])
            tgt = next((n["name"] for n in graph["nodes"] if n["id"] == e["target_node_id"]), "#%d" % e["target_node_id"])
            print("  %s --[%s]--> %s" % (src, e["relation_type"], tgt))


def cmd_schedule_today(args):
    _init_db()
    from .scheduler.multi_track import MultiTrackScheduler
    sched = MultiTrackScheduler()
    print(json.dumps(sched.get_schedule(args.user_id, args.total_minutes), ensure_ascii=False, indent=2, default=str))


def cmd_misconception_add(args):
    _init_db()
    from .db import dao_misconception
    mc = dao_misconception.add_misconception(
        user_id=args.user_id, node_id=args.node_id,
        misconception=args.misconception,
        correction=args.correction or "",
        category=args.category or "",
    )
    print("Misconception recorded: #%d" % mc["id"])


def cmd_migrate_meta(args):
    print("Starting migration from meta-learning database...")
    source_path = args.source or str(pathlib.Path.home() / ".meta-learning" / "meta_learning.db")
    if not pathlib.Path(source_path).exists():
        print("Error: source database not found at", source_path)
        sys.exit(1)
    from .db.database import init_db, get_connection, DB_PATH
    init_db()
    conn_dst = get_connection()
    try:
        import sqlite3
        conn_src = sqlite3.connect(str(source_path))
        conn_src.row_factory = sqlite3.Row
        print("Source:", source_path)
        print("Target:", DB_PATH)
        tables = ["users", "tracks", "knowledge_nodes", "node_dependencies",
                   "review_history", "assessment_log", "learning_journal",
                   "teaching_interactions", "misconceptions", "weakness_patterns",
                   "knowledge_graph_edges", "quality_audit_log",
                   "knowledge_sources", "knowledge_coverage"]
        total = 0
        for table in tables:
            rows = conn_src.execute("SELECT * FROM [%s]" % table).fetchall()
            if not rows:
                print("  %s: 0 rows (skipped)" % table)
                continue
            cols = [d[0] for d in conn_src.execute("PRAGMA table_info([%s])" % table).fetchall()]
            ph = ",".join(["?"] * len(cols))
            cn = ",".join(cols)
            ins = 0
            for row in rows:
                try:
                    conn_dst.execute("INSERT OR IGNORE INTO %s (%s) VALUES (%s)" % (table, cn, ph), list(row))
                    ins += 1
                except Exception as e:
                    logger.warning("Failed: %s", e)
            conn_dst.commit()
            total += ins
            print("  %s: %d rows" % (table, ins))
        print("")
        print("Migration complete: %d rows copied across %d tables" % (total, len(tables)))
        print("Run 'astromind report dashboard <id>' to verify.")
    finally:
        if conn_src:
            conn_src.close()
        conn_dst.close()
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="astromind",
        description="星知·笃行 — 认知科学驱动的元学习引擎 v0.1.2",
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

        # node
    p_node = sub.add_parser("node", help="Knowledge nodes")
    ns = p_node.add_subparsers(dest="node_command")
    p_ns = ns.add_parser("search", help="Search")
    p_ns.add_argument("keyword")
    p_ns.add_argument("--track", type=int)
    p_ns.add_argument("--limit", type=int, default=20)
    p_ns.set_defaults(func=cmd_node_search)
    p_nc = ns.add_parser("content", help="View/set content")
    p_nc.add_argument("node_id", type=int)
    p_nc.add_argument("--content")
    p_nc.add_argument("--file")
    p_nc.set_defaults(func=cmd_node_content)

    # track
    p_tr = sub.add_parser("track", help="List tracks")
    p_tr.add_argument("--user", dest="user_id", type=int)
    p_tr.add_argument("--status")
    p_tr.set_defaults(func=cmd_track_list)

    # review
    p_rv = sub.add_parser("review", help="Due reviews")
    p_rv.add_argument("--user", dest="user_id", type=int)
    p_rv.add_argument("--track", dest="track_id", type=int)
    p_rv.set_defaults(func=cmd_review_due)

    # report
    p_rp = sub.add_parser("report", help="Dashboard")
    p_rp.add_argument("user_id", type=int)
    p_rp.set_defaults(func=cmd_report_dashboard)

    # graph
    p_gr = sub.add_parser("graph", help="Knowledge graph")
    p_gr.add_argument("user_id", type=int)
    p_gr.set_defaults(func=cmd_graph_view)

    # schedule
    p_sc = sub.add_parser("schedule", help="Today")
    p_sc.add_argument("--user", dest="user_id", type=int, default=1)
    p_sc.add_argument("--minutes", dest="total_minutes", type=int)
    p_sc.set_defaults(func=cmd_schedule_today)

    # misconception
    p_mc = sub.add_parser("misconception", help="Record misconception")
    p_mc.add_argument("user_id", type=int)
    p_mc.add_argument("node_id", type=int)
    p_mc.add_argument("misconception", help="Description")
    p_mc.add_argument("--correction")
    p_mc.add_argument("--category", choices=["overgeneralization","term_confusion","surface_analogy","missing_boundary","order_reversal","other"])
    p_mc.set_defaults(func=cmd_misconception_add)

    # author — 作者教练命令 (v6.1+)
    p_author = sub.add_parser("author", help="Author coaching commands")
    author_sub = p_author.add_subparsers(dest="author_command", help="Author subcommands")

    p_at = author_sub.add_parser("train", help="Start author coach session")
    p_at.add_argument("author_name", help="Author name")
    p_at.add_argument("--scenario", default=None, help="Scenario to analyze")
    p_at.set_defaults(func=cmd_author_train)

    p_aw = author_sub.add_parser("write", help="Write as author")
    p_aw.add_argument("author_name", help="Author name")
    p_aw.add_argument("topic", help="Topic to write about")
    p_aw.add_argument("--no-validate", action="store_true", help="Skip quality validation")
    p_aw.set_defaults(func=cmd_author_write)

    p_aa = author_sub.add_parser("apply", help="Apply mental model to problem")
    p_aa.add_argument("model_id", type=int, help="Mental model ID")
    p_aa.add_argument("problem", help="Problem to analyze")
    p_aa.set_defaults(func=cmd_author_apply)

    # migrate
    p_mg = sub.add_parser("migrate", help="Migration")
    mgs = p_mg.add_subparsers(dest="migrate_command")
    p_mm = mgs.add_parser("meta-db", help="Migrate from meta-learning")
    p_mm.add_argument("--source")
    p_mm.set_defaults(func=cmd_migrate_meta)

    return parser


# ── Author coach command handlers ──

def cmd_author_train(args):
    """Start author coach session."""
    db = get_db()
    from .teaching.workflow import TeachingOrchestrator
    from .llm.client import LLMClient
    config = load_config()
    llm = LLMClient(
        base_url=config.get("llm", {}).get("base_url", ""),
        api_key=config.get("llm", {}).get("api_key", ""),
        model=config.get("llm", {}).get("model", ""),
    )
    orch = TeachingOrchestrator(db, llm, None, "cli", 0)
    result = orch.train_by_author(args.author_name, args.scenario)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_author_write(args):
    """Write an article in the author's style."""
    db = get_db()
    from .teaching.workflow import TeachingOrchestrator
    from .llm.client import LLMClient
    config = load_config()
    llm = LLMClient(
        base_url=config.get("llm", {}).get("base_url", ""),
        api_key=config.get("llm", {}).get("api_key", ""),
        model=config.get("llm", {}).get("model", ""),
    )
    orch = TeachingOrchestrator(db, llm, None, "cli", 0)
    result = orch.write_as_author(
        args.author_name, args.topic,
        validate=not args.no_validate,
    )
    if "article" in result:
        print(result["article"])
        if "quality_report" in result:
            print("\n--- Quality Report ---")
            print(json.dumps(result["quality_report"], ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_author_apply(args):
    """Apply a mental model to a problem."""
    db = get_db()
    from .teaching.workflow import TeachingOrchestrator
    from .llm.client import LLMClient
    config = load_config()
    llm = LLMClient(
        base_url=config.get("llm", {}).get("base_url", ""),
        api_key=config.get("llm", {}).get("api_key", ""),
        model=config.get("llm", {}).get("model", ""),
    )
    orch = TeachingOrchestrator(db, llm, None, "cli", 0)
    result = orch.apply_mental_model(args.model_id, args.problem)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "init":
        cmd_init(args)
    elif args.command in ("teach", "author"):
        sub_cmd = getattr(args, f"{args.command}_command", None)
        if sub_cmd is None:
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
