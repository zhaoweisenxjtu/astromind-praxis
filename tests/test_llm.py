"""LLM 客户端 + 提示词测试"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engine.llm.client import LLMClient, LLMError
from engine.llm.prompts import build_prompt, PROMPT_REGISTRY


def test_no_direct_config():
    """无 direct config 时 _has_direct_config 返回 False"""
    c = LLMClient()
    assert c._has_direct_config() is False


def test_has_direct_config():
    """完整配置时 _has_direct_config 返回 True"""
    c = LLMClient(base_url="http://test", api_key="key", model="m")
    assert c._has_direct_config() is True


def test_partial_config_false():
    """部分配置不满足"""
    assert LLMClient(base_url="http://test")._has_direct_config() is False
    assert LLMClient(api_key="key")._has_direct_config() is False
    assert LLMClient(model="m")._has_direct_config() is False


def test_direct_api_fails_with_bad_url():
    """错误的 URL 应抛 LLMError"""
    c = LLMClient(base_url="http://localhost:1", api_key="test", model="test")
    try:
        c.chat("system", "user")
        assert False, "should have raised"
    except LLMError:
        pass


def test_prompt_registry_keys():
    """验证 5 个调用点全部注册"""
    expected = {"assess_knowledge_graph", "diagnosis", "concept_content", "test_questions", "evaluate_answer"}
    assert set(PROMPT_REGISTRY.keys()) == expected


def test_build_prompt_returns_three():
    """build_prompt 返回 (system, user, schema)"""
    sys_p, user_p, schema = build_prompt("diagnosis", topic="T", concepts="[]",
                                          self_assessment="3", user_description="desc",
                                          test_results="none")
    assert isinstance(sys_p, str)
    assert isinstance(user_p, str)
    assert isinstance(schema, dict)
    assert len(sys_p) > 0
    assert len(user_p) > 0


def test_build_prompt_knowledge_graph():
    sys_p, user_p, schema = build_prompt("assess_knowledge_graph", topic="Python",
                                          search_results="result1\nresult2")
    assert "{topic}" not in user_p
    assert "{search_results}" not in user_p
    assert "Python" in user_p
    assert "result1" in user_p


def test_build_prompt_concept_content():
    sys_p, user_p, schema = build_prompt("concept_content",
                                          concept="变量", topic="Python", level="3",
                                          prerequisites="数据类型", misconceptions='[]')
    assert "变量" in user_p
    assert "Python" in user_p
    assert schema == {
        "name": "concept_content",
        "schema": {
            "type": "object",
            "properties": {
                "intuition": {"type": "string"},
                "motivation": {"type": "string"},
                "definition": {"type": "string"},
                "boundary": {"type": "string"},
                "connections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "concept": {"type": "string"},
                            "relation": {"type": "string"},
                        },
                        "required": ["concept", "relation"],
                    },
                },
                "examples": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string"},
                            "solution": {"type": "string"},
                            "difficulty": {"type": "integer", "minimum": 1, "maximum": 5},
                        },
                        "required": ["question", "solution"],
                    },
                },
            },
            "required": ["intuition", "motivation", "definition", "boundary", "examples"],
        },
    }


def test_build_prompt_unknown():
    try:
        build_prompt("nonexistent")
        assert False
    except ValueError:
        pass


def test_build_prompt_evaluate_answer():
    sys_p, user_p, schema = build_prompt("evaluate_answer",
                                          concept="变量", question="1+1=?",
                                          correct_answer="2", learner_answer="3")
    assert "变量" in user_p
    assert "1+1" in user_p
    assert "3" in user_p  # learner answer
    assert schema["name"] == "evaluate_answer"


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
    print("All LLM tests passed")
