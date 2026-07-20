"""AnySearch JSON-RPC 2.0 直连策略 (Tier 1)."""

import json
import logging
import re
import requests
from typing import Optional
from . import SearchStrategy

logger = logging.getLogger(__name__)

ENDPOINT = "https://api.anysearch.com/mcp"


class AnySearchStrategy(SearchStrategy):
    """AnySearch API 直连，匿名或带 key."""

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[list[dict]]:
        arguments = {"query": query, "max_results": max_results}
        for key in ("domain", "sub_domain", "content_types", "zone", "freshness"):
            if key in kwargs and kwargs[key]:
                arguments[key] = kwargs[key]

        text = self._call_api("search", arguments)
        if text is None:
            return None
        return self._parse_results(text) or []

    def extract(self, url: str) -> Optional[str]:
        """Fetch full page content as Markdown."""
        text = self._call_api("extract", {"url": url})
        return text

    def list_domains(self, domain: str) -> Optional[str]:
        """Query available sub_domains for a vertical domain."""
        return self._call_api("list_domains", {"domain": domain})

    def _call_api(self, tool_name: str, arguments: dict) -> Optional[str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }

        try:
            resp = requests.post(ENDPOINT, json=payload, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.ConnectionError as e:
            logger.warning("AnySearch connection failed: %s", e)
            return None
        except requests.exceptions.Timeout as e:
            logger.warning("AnySearch timeout: %s", e)
            return None
        except requests.exceptions.HTTPError as e:
            logger.warning("AnySearch HTTP error: %s", e)
            return None
        except json.JSONDecodeError as e:
            logger.warning("AnySearch JSON decode error: %s", e)
            return None
        except Exception as e:
            logger.warning("AnySearch unexpected error: %s", e)
            return None

        if "error" in data:
            logger.warning("AnySearch API returned error: %s", data["error"])
            return None

        result = data.get("result", {})
        content = result.get("content", [])
        for item in content:
            if item.get("type") == "text":
                return item.get("text", "")
        return json.dumps(result, ensure_ascii=False) if result else ""

    def _parse_results(self, text: str) -> list[dict]:
        """Parse AnySearch markdown/JSON response into structured results."""
        text = text.strip()
        if not text:
            return []

        # Try JSON parse first
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [self._normalize_item(item) for item in parsed if isinstance(item, dict)]
            if isinstance(parsed, dict):
                # Check if dict has results/items wrapper
                items = parsed.get("results", parsed.get("items", None))
                if isinstance(items, list):
                    return [self._normalize_item(item) for item in items if isinstance(item, dict)]
                # Dict itself looks like a result item
                if any(k in parsed for k in ("title", "name", "url", "content", "snippet")):
                    return [self._normalize_item(parsed)]
                return []
        except json.JSONDecodeError:
            pass

        # Parse markdown sections: ### Title or **Title**
        results = []
        current = {}

        for line in text.split("\n"):
            line_stripped = line.strip()

            # ### Header format
            m = re.match(r"^#{2,3}\s+(.+)$", line_stripped)
            if m:
                if current and current.get("title"):
                    results.append(current)
                current = {"title": m.group(1).strip(), "content": ""}
                continue

            # **Title** format (bold at start of line)
            m = re.match(r"^\*\*(.+?)\*\*", line_stripped)
            if m:
                if current and current.get("title"):
                    results.append(current)
                current = {"title": m.group(1).strip(), "content": line_stripped}
                continue

            # Numbered list: 1. **Title** or 1. Title
            m = re.match(r"^\d+[.、]\s+(.+)$", line_stripped)
            if m:
                if current and current.get("title"):
                    results.append(current)
                title_text = m.group(1).strip()
                title_text = re.sub(r"^\*\*|\*\*$", "", title_text)
                current = {"title": title_text, "content": ""}
                continue

            # URL extraction from various formats
            if current:
                url_m = re.search(r"(https?://[^\s\)\]>]+)", line_stripped)
                if url_m and not current.get("url"):
                    current["url"] = url_m.group(1)
                if current.get("content"):
                    current["content"] += " " + line_stripped
                else:
                    current["content"] = line_stripped

        if current and current.get("title"):
            results.append(current)

        # If nothing parsed, return text as single result
        if not results and text:
            # Try to extract URL
            url_m = re.search(r"(https?://[^\s\)\]>]+)", text)
            results.append({
                "title": text[:80],
                "url": url_m.group(1) if url_m else "",
                "content": text[:500],
            })

        return results

    def _normalize_item(self, item: dict) -> dict:
        return {
            "title": item.get("title", item.get("name", "")),
            "url": item.get("url", item.get("link", "")),
            "content": item.get("content", item.get("snippet", item.get("text", ""))),
            "source": "anysearch",
        }
