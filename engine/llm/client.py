"""LLM 双策略客户端：直连 API / Checkpoint 协议（v0.2.1）.

直连 API: OpenAI-compatible API (httpx, 重试+超时)
Checkpoint 协议: 无直连配置时由 CheckpointLLMClient（engine/runs/）提供，
  写 req-NNN.json → CLI exit 75 → agent 补答 → resume 消费（幂等重放）
"""

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """LLM call failed."""


class LLMClient:
    """直连 API 客户端。checkpoint 模式见 engine.runs.CheckpointLLMClient."""

    def __init__(self, base_url: str = "", api_key: str = "", model: str = ""):
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.api_key = api_key
        self.model = model

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: Optional[dict] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> dict:
        """Send chat request, return parsed JSON response.

        Args:
            system_prompt: System prompt text.
            user_prompt: User message text.
            schema: Optional JSON schema for structured output.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in response.

        Returns:
            Parsed JSON dict from LLM response.

        Raises:
            LLMError: If direct API fails.
        """
        return self._call_direct_api(
            system_prompt, user_prompt, schema, temperature, max_tokens
        )

    def chat_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
    ):
        """Stream response from LLM (only available in direct API mode)."""
        if self._has_direct_config():
            yield from self._stream_direct_api(system_prompt, user_prompt, temperature)
        else:
            # Stdio cannot stream; fall back to chat
            result = self._call_stdio_protocol(
                system_prompt, user_prompt, None, temperature, 4096
            )
            yield json.dumps(result, ensure_ascii=False)

    def _has_direct_config(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    # ── Direct API strategy ──

    def _call_direct_api(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: Optional[dict] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> dict:
        import httpx

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if schema:
            body["response_format"] = {"type": "json_schema", "json_schema": schema}

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        last_error = None
        for attempt in range(3):
            try:
                with httpx.Client(timeout=180) as client:
                    resp = client.post(url, json=body, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
            except httpx.TimeoutException as e:
                last_error = f"timeout (attempt {attempt + 1})"
                logger.warning("LLM direct API timeout: %s", e)
                continue
            except httpx.HTTPStatusError as e:
                last_error = f"HTTP {e.response.status_code}"
                logger.warning("LLM direct API HTTP error: %s", e)
                continue
            except Exception as e:
                last_error = str(e)
                logger.warning("LLM direct API error: %s", e)
                continue

            try:
                content = data["choices"][0]["message"]["content"]
                if schema:
                    return json.loads(content)
                # Try JSON parse, return raw if fails
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    return {"response": content}
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                last_error = f"parse error: {e}"
                continue

        raise LLMError(f"Direct API failed after 3 attempts: {last_error}")

    def _stream_direct_api(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
    ):
        import httpx

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        try:
            with httpx.Client(timeout=300) as client:
                with client.stream("POST", url, json=body, headers=headers) as resp:
                    for line in resp.iter_lines():
                        if line.startswith("data: "):
                            payload = line[6:]
                            if payload.strip() == "[DONE]":
                                break
                            try:
                                chunk = json.loads(payload)
                                delta = chunk["choices"][0]["delta"]
                                if "content" in delta:
                                    yield delta["content"]
                            except (json.JSONDecodeError, KeyError, IndexError):
                                continue
        except Exception as e:
            logger.warning("LLM stream error: %s", e)

    # ── Stdio protocol strategy ──

