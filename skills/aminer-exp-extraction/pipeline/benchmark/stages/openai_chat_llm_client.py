"""Zhipu BigModel chat-completions LLM client (OpenAI-compatible).

All LLM calls in this skill go through this client:
``POST https://open.bigmodel.cn/api/paas/v4/chat/completions`` with
``Authorization: Bearer $BIGMODEL_API_KEY``, model ``glm-5.3``, standard
OpenAI messages format, ``stream: false``.

Maintains the same return contract as SingleLLMClient.generate()
for compatibility with run_llm_stage_wf4.
"""

from __future__ import annotations

import os
import time
from typing import Any

import requests

from pipeline.production.adapters.gateway_auth import bigmodel_headers

# Default LLM backend: Zhipu BigModel (OpenAI-compatible). Override with
# the LLM_CHAT_URL / LLM_MODEL env vars.
DEFAULT_LLM_API_URL = os.environ.get(
    "LLM_CHAT_URL", "https://open.bigmodel.cn/api/paas/v4/chat/completions"
)
DEFAULT_LLM_MODEL = os.environ.get("LLM_MODEL", "glm-5.3-flash")

# glm-5.3 is an always-thinking model (the API rejects disabling it; levels
# are low / high / max). "low" keeps reasoning short so the answer fits the
# max_tokens budget — with the server default (high) a 4096-token cap can be
# burned entirely by reasoning_tokens, leaving content empty
# (finish_reason=length). Override with LLM_THINKING_LEVEL=high|max, or
# "off" to omit the field entirely.
DEFAULT_THINKING_LEVEL = os.environ.get("LLM_THINKING_LEVEL", "low")


class OpenAIChatLLMClient:
    """Zhipu BigModel Chat Completions API client for LLM.

    Works with any OpenAI-compatible /chat/completions endpoint
    (configure via the LLM_CHAT_URL env var or the api_url argument).

    Return format matches SingleLLMClient.generate() for drop-in replacement.
    """

    def __init__(
        self,
        api_url: str = DEFAULT_LLM_API_URL,
        timeout: int = 180,
        default_model: str | None = None,
        thinking_level: str | None = None,
    ) -> None:
        self.api_url = api_url
        self.timeout = timeout
        # Effective model sent as payload["model"] on every generate() call.
        self.default_model = default_model or DEFAULT_LLM_MODEL
        self._model = self.default_model
        self.thinking_level = (
            thinking_level if thinking_level is not None else DEFAULT_THINKING_LEVEL
        )
        if self.thinking_level == "off":
            self.thinking_level = None
        self._session = requests.Session()

    def generate(
        self,
        prompt: str,
        model: str | None = None,
        temperature: float = 0.05,
        num_predict: int = 2048,
        format: str | None = None,  # Ignored for OpenAI chat (not needed)
        stop: list[str] | None = None,  # Mapped if supported
        num_ctx: int | None = None,  # Ignored (server-side Ollama option)
        system: str | None = None,
    ) -> dict[str, Any]:
        """Generate via BigModel chat completions API.

        Args:
            prompt: The user message content to send.
            model: Model id (default ``glm-5.3``); sent as payload["model"].
            temperature: Sampling temperature.
            num_predict: Maximum tokens to generate (sent as ``max_tokens``).
            format: Ignored — kept for SingleLLMClient signature compatibility.
            stop: Optional stop sequences.
            num_ctx: Ignored — Ollama-only context option, not standard OpenAI.
            system: Optional system message content (``role: system``), sent
                ahead of the user message when set.

        Returns same dict shape as SingleLLMClient.generate():
        {raw_output, elapsed_sec, eval_count?, prompt_eval_count?, total_duration_ns?}
        """
        start = time.perf_counter()

        # Standard OpenAI chat format (same contract as the BigModel curl):
        # messages is an array of {role, content} objects; "model" names the
        # backend model (default glm-5.3); "stream": false for one-shot JSON.
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: dict[str, Any] = {
            "model": model or self._model,
            "messages": messages,
            "stream": False,
        }
        # glm-5.3 always thinks; pin the level (default low) so reasoning
        # stays short and the JSON answer fits the max_tokens budget.
        if self.thinking_level:
            payload["thinking"] = {"level": self.thinking_level}

        # Always send sampling params explicitly: omitting them at the
        # production defaults (temperature=0.05, num_predict=2048) would make
        # behavior depend on the server-side defaults.
        payload["temperature"] = temperature
        payload["max_tokens"] = num_predict
        if stop is not None:
            payload["stop"] = stop

        # BigModel auth: Authorization: Bearer $BIGMODEL_API_KEY
        # (OPENAI_API_KEY accepted as fallback inside bigmodel_headers).
        headers = bigmodel_headers({"Content-Type": "application/json"})

        response = self._session.post(
            self.api_url, json=payload, timeout=self.timeout,
            headers=headers,
        )
        elapsed = time.perf_counter() - start
        response.raise_for_status()

        result_data = response.json()
        # Online gateway envelope: {code, success, msg, data} with the OpenAI
        # response nested under data. BigModel returns it directly.
        if isinstance(result_data, dict) and "code" in result_data and "choices" not in result_data:
            if result_data.get("code") != 200 or not result_data.get("success") or result_data.get("data") is None:
                raise RuntimeError(
                    f"LLM gateway error: code={result_data.get('code')} "
                    f"msg={result_data.get('msg')!r}"
                )
            result_data = result_data["data"]
        raw_output = result_data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

        # Extract token counts if available in usage field
        usage = result_data.get("usage", {})
        eval_count = usage.get("completion_tokens")
        prompt_eval_count = usage.get("prompt_tokens")

        return {
            "raw_output": raw_output,
            "elapsed_sec": elapsed,
            "eval_count": eval_count,
            "prompt_eval_count": prompt_eval_count,
            "total_duration_ns": None,  # Not provided by OpenAI format
        }

    def resolve_model(self, preferred: list[str] | None = None) -> str:
        """Return the model this client sends as payload["model"].

        Signature kept for API compatibility with SingleLLMClient.
        """
        return self._model
