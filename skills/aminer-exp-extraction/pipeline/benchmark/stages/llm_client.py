"""LLM client for benchmark workflows (Zhipu BigModel glm-5.3).

All LLM traffic goes to the BigModel chat-completions API
(https://open.bigmodel.cn/api/paas/v4/chat/completions, Bearer auth,
model glm-5.3) — same contract as the OpenAIChatLLMClient used by the
production entry script. The previous local Ollama backend is gone.
"""

from __future__ import annotations

from pipeline.benchmark.config import BIGMODEL_CHAT_URL, LLM_MODEL, LLM_TIMEOUT
from pipeline.benchmark.stages.openai_chat_llm_client import OpenAIChatLLMClient


class SingleLLMClient(OpenAIChatLLMClient):
    """Single LLM client for JSON extraction (BigModel glm-5.3).

    Thin subclass of :class:`OpenAIChatLLMClient` whose defaults come from the
    benchmark config: ``LLM_CHAT_URL`` env (default
    ``https://open.bigmodel.cn/api/paas/v4/chat/completions``), model
    ``LLM_MODEL`` (default ``glm-5.3``), ``BIGMODEL_API_KEY`` Bearer auth.
    ``generate`` keeps the historical SingleLLMClient signature —
    Ollama-only knobs (``format``/``num_ctx``) are accepted and ignored —
    so wf1/wf4/wf8 call sites are unchanged.
    """

    def __init__(
        self,
        api_url: str = BIGMODEL_CHAT_URL,
        timeout: int = LLM_TIMEOUT,
        default_model: str | None = None,
    ) -> None:
        super().__init__(
            api_url=api_url,
            timeout=timeout,
            default_model=default_model or LLM_MODEL,
        )


class ParallelLLMClient:
    """Future: Parallel LLM client for batch processing. Not implemented in v0.1.0."""

    def generate_batch(self, prompts: list[str]) -> list[dict]:
        """Phase 2: LLM parallel mode."""
        raise NotImplementedError("Phase 2: LLM parallel mode not implemented in v0.1.0")
