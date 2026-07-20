"""Content Retriever: external search API integration.

Only used when user explicitly requests Tavily/Bing search.
Zero dependencies when not used. Falls back gracefully when API keys are missing.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

CONFIG_PATH = Path.home() / ".meta-learning" / "config.yaml"


@dataclass
class SearchResult:
    title: str = ""
    url: str = ""
    content: str = ""
    score: float = 0.0
    source: str = "unknown"


def _load_config() -> dict:
    """Load config.yaml if it exists."""
    if not CONFIG_PATH.exists():
        return {}
    try:
        import yaml
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        return {}
    except Exception:
        return {}


def tavily_search(query: str, max_results: int = 5) -> list[SearchResult]:
    """Search via Tavily API. Requires tavily-python and API key."""
    config = _load_config()
    api_key = (
        os.environ.get("TAVILY_API_KEY")
        or config.get("api", {}).get("tavily_key")
    )
    if not api_key:
        return []

    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=api_key)
        resp = client.search(query, search_depth="advanced", max_results=max_results)
        results = []
        for item in resp.get("results", []):
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                content=item.get("content", ""),
                score=item.get("score", 0),
                source="tavily",
            ))
        return results
    except ImportError:
        return []
    except Exception:
        return []


def bing_search(query: str, max_results: int = 5) -> list[SearchResult]:
    """Search via Bing Web Search API."""
    config = _load_config()
    api_key = (
        os.environ.get("BING_API_KEY")
        or config.get("api", {}).get("bing_key")
    )
    if not api_key:
        return []

    import requests
    try:
        headers = {"Ocp-Apim-Subscription-Key": api_key}
        params = {"q": query, "count": max_results, "mkt": "zh-CN"}
        resp = requests.get(
            "https://api.bing.microsoft.com/v7.0/search",
            headers=headers, params=params, timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for item in data.get("webPages", {}).get("value", []):
            results.append(SearchResult(
                title=item.get("name", ""),
                url=item.get("url", ""),
                content=item.get("snippet", ""),
                source="bing",
            ))
        return results
    except Exception:
        return []


def jina_fetch(url: str) -> str | None:
    """Fetch URL content as Markdown via Jina AI Reader API."""
    config = _load_config()
    api_key = (
        os.environ.get("JINA_API_KEY")
        or config.get("api", {}).get("jina_key")
    )
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    import requests
    try:
        resp = requests.get(
            f"https://r.jina.ai/{url}",
            headers=headers, timeout=15,
        )
        resp.raise_for_status()
        return resp.text
    except Exception:
        return None


def search(query: str, engine: str = "tavily", max_results: int = 5) -> list[SearchResult]:
    """Unified search interface. `engine` can be 'tavily' or 'bing'."""
    if engine == "tavily":
        return tavily_search(query, max_results)
    elif engine == "bing":
        return bing_search(query, max_results)
    return []


def search_and_fetch(query: str, engine: str = "tavily",
                     max_results: int = 3) -> list[SearchResult]:
    """Search and fetch full content from each result."""
    results = search(query, engine, max_results)
    for r in results:
        if r.url and not r.content:
            fetched = jina_fetch(r.url)
            if fetched:
                r.content = fetched[:10000]  # cap at 10k chars
    return results
