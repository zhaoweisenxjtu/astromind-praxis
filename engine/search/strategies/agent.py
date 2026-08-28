"""Agent checkpoint 协议搜索策略 (Tier 4 - 最后手段).

向 agent 发出搜索请求（checkpoint 协议，v0.2.1），由 agent 用自身搜索能力补答。
协议：create_request(kind=search) 写 req-NNN.json → 抛 NeedsSearch → CLI exit 76。
agent 补答 → Write rsp-NNN.json → resume → cache 消费。
"""

import hashlib
import json
import logging
from typing import Optional

from ...runs.store import NeedsSearch, Run, RunStore
from . import SearchStrategy

logger = logging.getLogger(__name__)


class AgentSearchStrategy(SearchStrategy):
    """通过 checkpoint 协议请求 agent 执行搜索。仅 agent 模式下可用。"""

    def __init__(self, store: Optional[RunStore] = None, run: Optional[Run] = None):
        self._store = store
        self._run = run

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[list[dict]]:
        if not (self._store and self._run):
            return None

        request = {
            "type": "search",
            "query": query,
            "max_results": max_results,
            **{k: v for k, v in kwargs.items() if v},
        }
        # key = 搜索指纹（同 run 同 query 幂等）
        key = hashlib.sha256(
            json.dumps({"q": query, "m": max_results}, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]

        req_path = self._store.create_request(
            self._run,
            kind="search",
            key=key,
            payload=request,
        )
        raise NeedsSearch(
            run_id=self._run.id,
            step=f"step-{len(self._run.steps):03d}",
            req_file=req_path,
        )
