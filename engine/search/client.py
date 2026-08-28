"""SearchClient 降级链编排器.

按序尝试各策略，前一个失败自动切下一个：
  AnySearch (匿名或 key) -> Bing API -> WebFetch -> Agent checkpoint (Tier 4)

v0.2.1 变更:
  - Tier 4 AgentSearchStrategy 从 Stdio 改为 checkpoint 协议（NeedsSearch → exit 76）
  - 同一 run 内相同 query 结果缓存（cache.json），保证 resume 重放幂等
"""

import logging
from typing import Optional

from .strategies import SearchStrategy
from .strategies.anysearch_api import AnySearchStrategy
from .strategies.bing_api import BingSearchStrategy
from .strategies.webfetch import WebFetchSearchStrategy
from .strategies.agent import AgentSearchStrategy
from ..runs.store import NeedsSearch, Run, RunStore

logger = logging.getLogger(__name__)


class SearchAllFailedError(RuntimeError):
    """All search strategies failed."""

    def __init__(self, errors: list[tuple[str, str]]):
        self.errors = errors
        detail = "; ".join(f"{name}: {err}" for name, err in errors)
        super().__init__(f"All search strategies failed: {detail}")


class SearchClient:
    """Search degradation chain orchestrator."""

    def __init__(
        self,
        anysearch_api_key: str = "",
        bing_api_key: str = "",
        is_agent_mode: bool = False,
        store: Optional[RunStore] = None,
        run: Optional[Run] = None,
    ):
        self.strategies: list[SearchStrategy] = []
        self._store = store
        self._run = run

        # Tier 1: AnySearch (always available)
        self.strategies.append(AnySearchStrategy(anysearch_api_key))

        # Tier 2: Bing API (only if key configured)
        if bing_api_key:
            self.strategies.append(BingSearchStrategy(bing_api_key))

        # Tier 3: WebFetch (always available, no key needed)
        self.strategies.append(WebFetchSearchStrategy())

        # Tier 4: Agent checkpoint protocol (only in agent mode)
        if is_agent_mode:
            self.strategies.append(AgentSearchStrategy(store=store, run=run))

    def search(self, query: str, max_results: int = 10, **kwargs) -> list[dict]:
        """Execute search across degradation chain.

        幂等缓存：同 run 同 query 已搜过 → 直接返回缓存（重放保护）。
        Tier 4 checkpoint：NeedsSearch 向上传播（CLI exit 76），不吞。
        Raises SearchAllFailedError if all strategies fail.
        """
        cache_key = f"search:{query}"
        store = getattr(self, "_store", None)   # 兼容 __new__ 模拟（既有测试）
        run = getattr(self, "_run", None)
        if store and run:
            hit = store.cache_get(run, cache_key)
            if hit is not None:
                logger.debug("Search cache hit: %s", cache_key)
                return hit

        errors = []
        for strategy in self.strategies:
            name = type(strategy).__name__
            try:
                result = strategy.search(query, max_results, **kwargs)
                if result is None:
                    logger.debug("Search strategy %s unavailable, degrading", name)
                    continue
                if len(result) > 0:
                    if store and run:
                        store.cache_set(run, cache_key, result)
                    logger.debug("Search strategy %s returned %d results", name, len(result))
                    return result
                # Empty list means search completed but no results
                logger.debug("Search strategy %s returned 0 results", name)
            except NeedsSearch:
                raise
            except Exception as e:
                logger.warning("Search strategy %s failed: %s", name, e)
                errors.append((name, str(e)))
                continue

        if errors:
            raise SearchAllFailedError(errors)
        return []

    def search_first(self, query: str, max_results: int = 10, **kwargs) -> Optional[list[dict]]:
        """Try first available strategy only, return None if all unavailable.

        Unlike search(), this doesn't raise on failure.
        """
        for strategy in self.strategies:
            try:
                result = strategy.search(query, max_results, **kwargs)
                if result is not None:
                    return result
            except NeedsSearch:
                raise
            except Exception:
                continue
        return None
