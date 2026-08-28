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
    """验证全部调用点注册（v0.2.2: 5 个合并后调用点）"""
    expected = {"diagnose_pack", "teach_pack",
                "evaluate_answers_batch", "review_pack", "assessment"}
    assert set(PROMPT_REGISTRY.keys()) == expected


def test_build_prompt_returns_three():
    """build_prompt 返回 (system, user, schema)"""
    sys_p, user_p, schema = build_prompt("diagnose_pack", topic="T",
                                          search_results="r", self_assessment="3",
                                          user_description="desc")
    assert isinstance(sys_p, str)
    assert isinstance(user_p, str)
    assert isinstance(schema, dict)
    assert len(sys_p) > 0
    assert len(user_p) > 0


def test_build_prompt_diagnose_pack():
    sys_p, user_p, schema = build_prompt("diagnose_pack", topic="Python",
                                          search_results="result1\nresult2",
                                          self_assessment="3", user_description="desc")
    assert "{topic}" not in user_p
    assert "{search_results}" not in user_p
    assert "Python" in user_p
    assert "result1" in user_p
    assert schema["name"] == "diagnose_pack"
    # 合并后 schema 同时含 KG 与诊断字段
    props = schema["schema"]["properties"]
    assert "concepts" in props and "edges" in props
    assert "level" in props and "gaps" in props and "misconceptions" in props


def test_build_prompt_teach_pack():
    sys_p, user_p, schema = build_prompt("teach_pack",
                                          concept="变量", topic="Python", level="3",
                                          prerequisites="数据类型", misconceptions='[]')
    assert "变量" in user_p
    assert "Python" in user_p
    assert schema["name"] == "teach_pack"
    # 合并后 schema 同时含教学内容与检验题
    props = schema["schema"]["properties"]
    assert "intuition" in props and "definition" in props
    assert "questions" in props


def test_build_prompt_review_pack():
    sys_p, user_p, schema = build_prompt("review_pack", n="2",
                                          nodes_payload='[{"node_id":1}]')
    assert "2" in user_p
    assert schema["name"] == "review_pack"
    assert schema["schema"]["properties"]["items"]


def test_build_prompt_assessment():
    sys_p, user_p, schema = build_prompt("assessment", topic="T",
                                          node_count="5", completed_count="3",
                                          stats='{"total":10}')
    assert "T" in user_p
    assert schema["name"] == "assessment_report"
    props = schema["schema"]["properties"]
    assert "overall_level" in props and "concept_mastery" in props


def test_build_prompt_unknown():
    try:
        build_prompt("nonexistent")
        assert False
    except ValueError:
        pass


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
