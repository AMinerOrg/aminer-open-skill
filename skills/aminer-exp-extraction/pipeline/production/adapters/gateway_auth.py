"""Auth headers for the Zhipu BigModel chat-completions API.

This skill's only model service is the public BigModel endpoint
(``https://open.bigmodel.cn/api/paas/v4/chat/completions``), used by both the
GLM sentence filter and the extraction stage. No internal/AMiner gateway is
contacted anywhere.

Token resolution: ``BIGMODEL_API_KEY`` (preferred) with ``OPENAI_API_KEY``
accepted as a fallback. Values are never logged.
"""

from __future__ import annotations

import os
from typing import Any


def resolve_bigmodel_token() -> str:
    """Return the Zhipu BigModel API key, or "" when none is set."""
    return (os.environ.get("BIGMODEL_API_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip()


def bigmodel_headers(extra: dict[str, Any] | None = None) -> dict[str, str]:
    """Auth headers for the BigModel chat completions API."""
    headers: dict[str, str] = {}
    token = resolve_bigmodel_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if extra:
        headers.update(extra)
    return headers
