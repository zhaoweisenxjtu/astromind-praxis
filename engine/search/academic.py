"""学术搜索模块.

降级链：
  1. AnySearch academic 领域直搜
  2. 通用搜索降级链 + 学术 URL 模式过滤
  3. 引文网络追踪
"""

import logging
import re
from typing import Optional

from .client import SearchClient

logger = logging.getLogger(__name__)

# 学术来源 URL 模式 (从 knowledge_quality.py 提取)
ACADEMIC_URL_PATTERNS = [
    r"scholar\.google\.",
    r"semanticsscholar\.org",
    r"arxiv\.org",
    r"pubmed\.ncbi\.nlm\.nih\.gov",
    r"doi\.org",
    r"ieeexplore\.ieee\.org",
    r"dl\.acm\.org",
    r"springer\.com",
    r"sciencedirect\.com",
    r"wiley\.com",
    r"nature\.com",
    r"science\.org",
    r"cell\.com",
    r"plos\.org",
    r"bmj\.com",
    r"jstor\.org",
    r"cambridge\.org",
    r"oxfordjournals\.org",
    r"tandfonline\.com",
    r"sagepub\.com",
    r"cnki\.net",
    r"wanfangdata\.com\.cn",
    r"cqvip\.com",
    r"openreview\.net",
    r"aclweb\.org",
]


class AcademicSearchEngine:
    """学术搜索引擎 (带降级链)."""

    def __init__(self, search_client: SearchClient):
        self.search_client = search_client

    def search(self, query: str, max_results: int = 10) -> list[dict]:
        """学术搜索：优先 AnySearch academic 领域，降级到通用搜索 + 学术过滤."""
        # Strategy 1: AnySearch academic domain
        try:
            results = self.search_client.search(
                query, max_results=max_results, domain="academic"
            )
            if results:
                logger.debug("AnySearch academic returned %d results", len(results))
                return results
        except Exception as e:
            logger.debug("AnySearch academic failed: %s", e)

        # Strategy 2: General search + URL pattern filtering
        try:
            all_results = self.search_client.search(query, max_results=max_results * 2)
            filtered = [r for r in all_results if self._is_academic_url(r.get("url", ""))]
            if filtered:
                logger.debug("Academic filter returned %d/%d results",
                           len(filtered), len(all_results))
                return filtered[:max_results]
            return all_results[:max_results] if all_results else []
        except Exception as e:
            logger.debug("Academic URL filter failed: %s", e)
            return []

    def trace_citation_network(
        self, topic: str, max_depth: int = 3
    ) -> list[dict]:
        """引文网络追踪 (简化版).

        从 citation-network.md 五步法提取：
          founders -> core -> secondary -> upstream -> downstream
        """
        nodes = []
        seen = set()

        for depth in range(max_depth):
            results = self.search(topic, max_results=5)
            for r in results:
                url = r.get("url", "")
                if url and url not in seen:
                    seen.add(url)
                    r["citation_depth"] = depth
                    nodes.append(r)
            if not results:
                break
            # Use first result's title for next depth search
            next_query = results[0].get("title", topic)

        return nodes

    def _is_academic_url(self, url: str) -> bool:
        """Check if URL is from an academic source."""
        return any(re.search(p, url, re.IGNORECASE) for p in ACADEMIC_URL_PATTERNS)
