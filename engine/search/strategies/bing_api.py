"""Bing Web Search API 策略 (Tier 2)."""

from typing import Optional
from . import SearchStrategy


class BingSearchStrategy(SearchStrategy):
    """Bing Web Search API v7.0. 需要 bing_key 配置."""

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[list[dict]]:
        if not self.api_key:
            return None

        import requests

        try:
            headers = {"Ocp-Apim-Subscription-Key": self.api_key}
            params = {"q": query, "count": max_results, "mkt": "zh-CN"}
            resp = requests.get(
                "https://api.bing.microsoft.com/v7.0/search",
                headers=headers, params=params, timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return None

        results = []
        for item in data.get("webPages", {}).get("value", []):
            results.append({
                "title": item.get("name", ""),
                "url": item.get("url", ""),
                "content": item.get("snippet", ""),
                "source": "bing",
            })

        return results
