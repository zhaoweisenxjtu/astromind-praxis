"""搜索策略层测试"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engine.search.strategies import SearchStrategy
from engine.search.strategies.bing_api import BingSearchStrategy
from engine.search.strategies.agent import AgentSearchStrategy
from engine.search.client import SearchClient, SearchAllFailedError


def test_strategy_interface():
    """验证抽象接口定义了 search 方法"""
    import inspect
    assert hasattr(SearchStrategy, "search")
    assert callable(SearchStrategy.search)
    sig = inspect.signature(SearchStrategy.search)
    params = list(sig.parameters.keys())
    assert "query" in params
    assert "max_results" in params


def test_bing_no_key_returns_none():
    """Bing 无 key 返回 None (标记不可用)"""
    s = BingSearchStrategy(api_key="")
    result = s.search("test")
    assert result is None


def test_bing_with_key():
    """Bing 带假 key 应失败而非返回 None (HTTP 401 而非 key missing)"""
    s = BingSearchStrategy(api_key="fake_key_123")
    result = s.search("test")
    assert result is None  # requests raise exception caught → None


def test_agent_no_stdin():
    """Agent 策略在 stdin 是 tty 时返回 None"""
    s = AgentSearchStrategy()
    # stdin is a tty in test context
    result = s.search("test")
    assert result is None


def test_search_client_no_keys():
    """SearchClient 无 key 时仍有 AnySearch + WebFetch"""
    c = SearchClient(anysearch_api_key="", bing_api_key="")
    assert len(c.strategies) == 2
    names = [type(s).__name__ for s in c.strategies]
    assert "AnySearchStrategy" in names
    assert "WebFetchSearchStrategy" in names


def test_search_client_with_bing_key():
    """SearchClient 有 bing key 时含 Bing 策略"""
    c = SearchClient(anysearch_api_key="", bing_api_key="my_bing_key")
    assert len(c.strategies) == 3
    names = [type(s).__name__ for s in c.strategies]
    assert "BingSearchStrategy" in names


def test_search_client_agent_mode():
    """SearchClient agent_mode=True 含 Agent 策略"""
    c = SearchClient(is_agent_mode=True)
    names = [type(s).__name__ for s in c.strategies]
    assert "AgentSearchStrategy" in names


class MockSuccessStrategy(SearchStrategy):
    def search(self, query, max_results=10, **kwargs):
        return [{"title": "mock", "url": "http://mock", "content": "mock", "source": "mock"}]


class MockFailStrategy(SearchStrategy):
    def search(self, query, max_results=10, **kwargs):
        raise RuntimeError("mock fail")


class MockNoneStrategy(SearchStrategy):
    def search(self, query, max_results=10, **kwargs):
        return None


class MockEmptyStrategy(SearchStrategy):
    def search(self, query, max_results=10, **kwargs):
        return []


def test_search_client_first_success():
    """降级链在第一个成功时返回"""
    c = SearchClient.__new__(SearchClient)
    c.strategies = [MockFailStrategy(), MockSuccessStrategy(), MockEmptyStrategy()]
    result = c.search("test")
    assert len(result) == 1
    assert result[0]["title"] == "mock"


def test_search_client_all_fail_raises():
    """所有策略失败时抛 SearchAllFailedError"""
    c = SearchClient.__new__(SearchClient)
    c.strategies = [MockFailStrategy(), MockFailStrategy()]
    try:
        c.search("test")
        assert False, "should have raised"
    except SearchAllFailedError as e:
        assert len(e.errors) == 2


def test_search_client_all_none_returns_empty():
    """全部返回 None 时返回空列表（不抛异常）"""
    c = SearchClient.__new__(SearchClient)
    c.strategies = [MockNoneStrategy(), MockNoneStrategy()]
    result = c.search("test")
    assert result == []


def test_search_client_empty_result():
    """搜索成功但无结果返回空列表"""
    c = SearchClient.__new__(SearchClient)
    c.strategies = [MockEmptyStrategy()]
    result = c.search("test")
    assert result == []


def test_search_first_returns_first():
    """search_first 返回第一个可用结果"""
    c = SearchClient.__new__(SearchClient)
    c.strategies = [MockNoneStrategy(), MockSuccessStrategy()]
    result = c.search_first("test")
    assert result is not None
    assert result[0]["source"] == "mock"


def test_search_first_all_none():
    """search_first 全部不可用时返回 None"""
    c = SearchClient.__new__(SearchClient)
    c.strategies = [MockNoneStrategy(), MockNoneStrategy()]
    result = c.search_first("test")
    assert result is None


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
    print("All search tests passed")
