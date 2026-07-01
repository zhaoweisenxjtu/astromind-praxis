"""Agent Stdio 协议搜索策略 (Tier 4 - 最后手段).

向 agent 发出搜索请求，由 agent 自由选择搜索方式。
协议：stdout 输出 [SEARCH_REQ] 标记 + JSON，从 stdin 读回 JSON 响应。
"""

import json
import sys
from typing import Optional
from . import SearchStrategy


class AgentSearchStrategy(SearchStrategy):
    """通过 Stdio 协议请求 agent 执行搜索。仅 agent 模式下可用。"""

    def __init__(self):
        self._available = None

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[list[dict]]:
        if not self._check_available():
            return None

        request = {
            "type": "search",
            "query": query,
            "max_results": max_results,
            **{k: v for k, v in kwargs.items() if v},
        }

        try:
            # Write request marker to stdout
            print(f"\n[SEARCH_REQ] {json.dumps(request, ensure_ascii=False)}", flush=True)

            # Read response from stdin (first line)
            line = sys.stdin.readline()
            if not line:
                return None

            line = line.strip()
            # Remove optional [SEARCH_RSP] marker
            if line.startswith("[SEARCH_RSP]"):
                line = line[len("[SEARCH_RSP]"):].strip()

            data = json.loads(line)
        except Exception:
            return None

        results = data.get("results", data if isinstance(data, list) else [])
        if isinstance(results, dict):
            results = [results]

        parsed = []
        for item in results:
            if isinstance(item, dict):
                parsed.append({
                    "title": item.get("title", item.get("name", "")),
                    "url": item.get("url", item.get("link", "")),
                    "content": item.get("content", item.get("snippet", item.get("text", ""))),
                    "source": "agent",
                })

        return parsed

    def _check_available(self) -> bool:
        """Check if we're in agent mode by verifying stdin is piped."""
        if self._available is not None:
            return self._available
        self._available = not sys.stdin.isatty()
        return self._available
