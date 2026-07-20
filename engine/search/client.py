"""SearchClient 降级链编排器.

按序尝试各策略，前一个失败自动切下一个：
  AnySearch (匿名或 key) -> Bing API -> WebFetch -> Agent Stdio
"""

import logging
from typing import Optional

from .strategies import SearchStrategy
from .strategies.anysearch_api import AnySearchStrategy
from .strategies.bing_api import BingSearchStrategy
from .strategies.webfetch import WebFetchSearchStrategy
from .strategies.agent import AgentSearchStrategy

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
    ):
        self.strategies: list[SearchStrategy] = []

        # Tier 1: AnySearch (always available)
        self.strategies.append(AnySearchStrategy(anysearch_api_key))

        # Tier 2: Bing API (only if key configured)
        if bing_api_key:
            self.strategies.append(BingSearchStrategy(bing_api_key))

        # Tier 3: WebFetch (always available, no key needed)
        self.strategies.append(WebFetchSearchStrategy())

        # Tier 4: Agent Stdio protocol (only in agent mode)
        if is_agent_mode:
            self.strategies.append(AgentSearchStrategy())

    def search(self, query: str, max_results: int = 10, **kwargs) -> list[dict]:
        """Execute search across degradation chain.

        Raises SearchAllFailedError if all strategies fail.
        Returns empty list if search succeeds but no results found.
        """
        errors = []
        for strategy in self.strategies:
            name = type(strategy).__name__
            try:
                result = strategy.search(query, max_results, **kwargs)
                if result is None:
                    logger.debug("Search strategy %s unavailable, degrading", name)
                    continue
                if len(result) > 0:
                    logger.debug("Search strategy %s returned %d results", name, len(result))
                    return result
                # Empty list means search completed but no results
                logger.debug("Search strategy %s returned 0 results", name)
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
            except Exception:
                continue
        return None
