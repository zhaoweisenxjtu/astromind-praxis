"""CLI 参数解析 + 配置 + 数据库初始化测试"""
import sys, os, json, tempfile, yaml
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engine.main import build_parser, load_config, save_config, check_config
from unittest.mock import patch


def test_parser_init():
    parser = build_parser()
    args = parser.parse_args(["init"])
    assert args.command == "init"
    assert hasattr(args, "func")


def test_parser_init_check():
    parser = build_parser()
    args = parser.parse_args(["init", "--check"])
    assert args.command == "init"
    assert args.check is True


def test_parser_init_reset():
    parser = build_parser()
    args = parser.parse_args(["init", "--reset"])
    assert args.reset is True


def test_parser_teach_diagnose():
    parser = build_parser()
    args = parser.parse_args(["teach", "diagnose", "量子计算"])
    assert args.command == "teach"
    assert args.teach_command == "diagnose"
    assert args.topic == "量子计算"


def test_parser_teach_session():
    parser = build_parser()
    args = parser.parse_args(["teach", "session", "42"])
    assert args.session_id == 42


def test_parser_teach_assess():
    parser = build_parser()
    args = parser.parse_args(["teach", "assess", "1"])
    assert args.session_id == 1


def test_parser_teach_status():
    parser = build_parser()
    args = parser.parse_args(["teach", "status", "5"])
    assert args.session_id == 5


def test_parser_teach_next():
    parser = build_parser()
    args = parser.parse_args(["teach", "next", "3"])
    assert args.session_id == 3


def test_parser_no_args():
    parser = build_parser()
    args = parser.parse_args([])
    assert args.command is None


def _with_tmp_config(fn):
    """Decorator: run test with a temporary config.yaml path."""
    def wrapper(*args, **kwargs):
        tmp_dir = tempfile.mkdtemp()
        tmp_path = Path(tmp_dir) / "config.yaml"
        import engine.main as main_mod
        orig = main_mod.CONFIG_PATH
        main_mod.CONFIG_PATH = tmp_path
        try:
            return fn(tmp_path, *args, **kwargs)
        finally:
            main_mod.CONFIG_PATH = orig
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
    return wrapper


@_with_tmp_config
def test_config_save_load(tmp_path):
    cfg = {"llm": {"base_url": "http://test", "api_key": "key123", "model": "m"},
           "anysearch_api_key": "ask", "bing_key": "bk"}
    save_config(cfg)
    loaded = load_config()
    assert loaded["llm"]["base_url"] == "http://test"
    assert loaded["llm"]["api_key"] == "key123"
    assert loaded["anysearch_api_key"] == "ask"
    assert loaded["bing_key"] == "bk"


@_with_tmp_config
def test_save_config_no_llm(tmp_path):
    save_config({"init": {"completed": True}})
    loaded = load_config()
    assert loaded["init"]["completed"] is True


@_with_tmp_config
def test_check_config_missing(tmp_path):
    # Don't create the file
    import engine.main as main_mod
    main_mod.CONFIG_PATH = tmp_path.parent / "nonexistent.yaml"
    status = check_config()
    assert status["config_exists"] is False
    assert status["init_completed"] is False


@_with_tmp_config
def test_check_config_exists(tmp_path):
    config = {"init": {"completed": True}, "llm": {"api_key": "k"}}
    # Use save_config to create the file (this sets CONFIG_PATH internally)
    save_config(config)
    import engine.main as main_mod
    # At this point main_mod.CONFIG_PATH is already tmp_path (set by decorator)
    status = check_config()
    assert status["config_exists"] is True, f"config_exists should be True, got {status['config_exists']}"
    assert status["init_completed"] is True
    assert status["llm_configured"] is True


@_with_tmp_config
def test_load_config_no_file(tmp_path):
    import engine.main as main_mod
    main_mod.CONFIG_PATH = Path("/nonexistent/path/config.yaml")
    cfg = load_config()
    assert cfg == {}


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
    print("All CLI/config tests passed")
