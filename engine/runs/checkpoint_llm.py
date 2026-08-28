"""CheckpointLLMClient: 无直连配置时的 LLM 供给（v0.2.1 阶段 1 内核）。

行为（设计文档 §3.2/§6.1）:
  chat() 调用:
    1. 按 prompt_key 查 run 内已消费应答 → 命中直接返回（幂等重放）
    2. 未命中 → create_request 写 req-NNN.json → 抛 NeedsLLM(75)
  resume 后同 run 重放: 已答步骤命中缓存跳过，遇到下一个未答 checkpoint 再抛。
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from .store import NeedsLLM, Run, RunStore, prompt_key

logger = logging.getLogger(__name__)


class CheckpointLLMClient:
    """通过 checkpoint 协议使用 agent 的模型能力。"""

    def __init__(self, store: RunStore, run: Run):
        self.store = store
        self.run = run

    # 与直连 LLMClient 对齐的接口（阶段 3 编排器接入时零改动）
    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: Optional[dict] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> dict:
        # 刷新 run 快照：resume 后客户端持有的对象必须是最新状态，
        # 否则幂等重放时会把过期 status（如 pending_llm）写回 meta。
        fresh = self.store.get_run(self.run.id)
        if fresh is not None:
            self.run = fresh

        key = prompt_key(system_prompt, user_prompt, schema)

        # 1. 幂等重放：同一 run 内已答过的 prompt 直接命中
        cached = self.store.get_answer(self.run, key)
        if cached is not None:
            logger.debug("Checkpoint hit: %s key=%s", self.run.id, key)
            return cached

        # 2. 未答 → 落 checkpoint，交给 CLI 层 exit 75
        req_path = self.store.create_request(
            self.run,
            kind="llm",
            key=key,
            payload={
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "schema": schema,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "request_digest": key,
            },
        )
        raise NeedsLLM(run_id=self.run.id, step=f"step-{len(self.run.steps):03d}", req_file=req_path)

    def chat_stream(self, system_prompt: str, user_prompt: str, temperature: float = 0.7):
        # checkpoint 协议不支持流式，降级为 chat 后单块 yield
        yield json.dumps(
            self.chat(system_prompt, user_prompt, None, temperature, 4096),
            ensure_ascii=False,
        )
