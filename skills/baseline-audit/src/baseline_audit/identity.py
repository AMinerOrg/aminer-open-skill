"""Shared AMiner request identity headers for Baseline Audit."""

from __future__ import annotations

import os

from . import __version__

SKILL_NAME = "baseline-audit"


def detect_skill_runtime() -> str:
    explicit = (
        (os.environ.get("AMINER_SKILL_RUNTIME") or "")
        .strip()
        .lower()
        .replace("_", "-")
    )
    if explicit:
        return explicit
    if (
        os.environ.get("CLAUDE_CODE")
        or os.environ.get("CLAUDECODE")
        or os.environ.get("CLAUDE_PROJECT_DIR")
    ):
        return "claude-code"
    if os.environ.get("CURSOR_TRACE_ID") or os.environ.get("CURSOR_AGENT"):
        return "cursor"
    if os.environ.get("CODEX_HOME") or os.environ.get("CODEX_CLI"):
        return "codex"
    if os.environ.get("OPENCLAW") or os.environ.get("OPENCLAW_HOME"):
        return "openclaw"
    return "unknown"


def skill_identity_headers() -> dict[str, str]:
    return {
        "X-Platform": detect_skill_runtime(),
        "X-Skill-Name": SKILL_NAME,
        "X-Skill-Version": __version__,
    }


def aminer_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": api_key,
        "Content-Type": "application/json;charset=utf-8",
        **skill_identity_headers(),
    }
