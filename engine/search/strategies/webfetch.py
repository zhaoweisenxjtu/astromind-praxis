"""WebFetch 通用搜索引擎爬取策略 (Tier 3).

爬取百度 / Bing CN / DuckDuckGo HTML 搜索结果。
无需 API key，纯 HTML 解析。
"""

import logging
import re
import time
from typing import Optional
from . import SearchStrategy

# Browser-like headers to avoid being blocked
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "identity",
}

logger = logging.getLogger(__name__)


class WebFetchSearchStrategy(SearchStrategy):
    """爬取搜索引擎 HTML，按序尝试 DuckDuckGo -> Bing CN -> 百度."""

    def __init__(self):
        self._session = None

    @property
    def session(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
            self._session.headers.update(HEADERS)
        return self._session

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[list[dict]]:
        engines = [
            ("duckduckgo", self._search_duckduckgo),
            ("bing_cn", self._search_bing_cn),
            ("baidu", self._search_baidu),
        ]

        all_results = []
        seen_urls = set()

        for name, func in engines:
            try:
                results = func(query, max_results)
                if results is None:
                    logger.debug("WebFetch engine %s returned None, degrading", name)
                    continue
                for r in results:
                    if r["url"] and r["url"] not in seen_urls:
                        seen_urls.add(r["url"])
                        all_results.append(r)
                        if len(all_results) >= max_results:
                            return all_results[:max_results]
            except Exception as e:
                logger.debug("WebFetch engine %s failed: %s", name, e)
                continue

        return all_results[:max_results] if all_results else []

    def _parse_html(self, html: str, engine: str) -> list[dict]:
        """Parse HTML from any engine into structured results."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        results = []

        if engine == "duckduckgo":
            for a_tag in soup.select("a.result__a"):
                title = a_tag.get_text(strip=True)
                url = self._extract_ddg_url(a_tag.get("href", ""))
                if not title or not url:
                    continue
                # Find snippet sibling
                snippet_tag = a_tag.find_parent().find_next_sibling(
                ) if a_tag.find_parent() else None
                snippet = ""
                if snippet_tag:
                    s = snippet_tag.select_one(".result__snippet")
                    if s:
                        snippet = s.get_text(strip=True)
                results.append({
                    "title": title,
                    "url": url,
                    "content": snippet,
                    "source": "duckduckgo",
                })

        elif engine == "bing_cn":
            for li in soup.select("li.b_algo"):
                a_tag = li.select_one("h2 a")
                if not a_tag:
                    continue
                title = a_tag.get_text(strip=True)
                url = a_tag.get("href", "")
                snippet_tag = li.select_one(".b_caption p")
                snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
                results.append({
                    "title": title,
                    "url": url,
                    "content": snippet,
                    "source": "bing",
                })

        elif engine == "baidu":
            for div in soup.select("div.result, div.c-container"):
                a_tag = div.select_one("h3.t a, a[data-click]")
                if not a_tag:
                    continue
                title = a_tag.get_text(strip=True)
                url = a_tag.get("href", "")
                snippet_tag = div.select_one(
                    "span.content-right_8Zs40, div.c-abstract, span.c-gap-bottom"
                )
                snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
                results.append({
                    "title": title,
                    "url": url,
                    "content": snippet,
                    "source": "baidu",
                })

        return results

    def _extract_ddg_url(self, href: str) -> str:
        """Extract real URL from DuckDuckGo redirect."""
        if not href or href == "#":
            return ""
        if href.startswith("http"):
            return href
        # /l/?uddg=base64url
        m = re.search(r"uddg=([^&]+)", href)
        if m:
            import urllib.parse
            try:
                return urllib.parse.unquote(m.group(1))
            except Exception:
                pass
        return ""

    def _search_duckduckgo(self, query: str, max_results: int) -> Optional[list[dict]]:
        """POST to DuckDuckGo HTML endpoint."""
        try:
            resp = self.session.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query},
                timeout=10,
            )
            resp.raise_for_status()
        except Exception:
            return None

        # Check for anti-bot challenge
        if resp.status_code == 202 or "challenge-form" in resp.text:
            logger.debug("DuckDuckGo returned challenge page, degrading")
            return None

        return self._parse_html(resp.text, "duckduckgo")

    def _search_bing_cn(self, query: str, max_results: int) -> Optional[list[dict]]:
        """GET Bing CN search."""
        try:
            resp = self.session.get(
                "https://cn.bing.com/search",
                params={"q": query, "count": min(max_results, 50)},
                timeout=10,
            )
            resp.raise_for_status()
        except Exception:
            return None

        # Check for captcha
        if "captcha" in resp.text.lower() or "unusual traffic" in resp.text.lower():
            logger.debug("Bing CN returned captcha page, degrading")
            return None

        return self._parse_html(resp.text, "bing_cn")

    def _search_baidu(self, query: str, max_results: int) -> Optional[list[dict]]:
        """GET Baidu search."""
        try:
            resp = self.session.get(
                "https://www.baidu.com/s",
                params={"wd": query, "rn": min(max_results, 50)},
                timeout=10,
            )
            resp.raise_for_status()
        except Exception:
            return None

        return self._parse_html(resp.text, "baidu")
