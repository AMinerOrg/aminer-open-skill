from __future__ import annotations

import pytest

from baseline_finder import __version__
from baseline_finder.identity import aminer_headers, detect_skill_runtime


RUNTIME_MARKERS = (
    "AMINER_SKILL_RUNTIME",
    "CLAUDE_CODE",
    "CLAUDECODE",
    "CLAUDE_PROJECT_DIR",
    "CURSOR_TRACE_ID",
    "CURSOR_AGENT",
    "CODEX_HOME",
    "CODEX_CLI",
    "OPENCLAW",
    "OPENCLAW_HOME",
)


@pytest.fixture(autouse=True)
def clear_runtime_markers(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in RUNTIME_MARKERS:
        monkeypatch.delenv(name, raising=False)


def test_aminer_headers_include_skill_identity_and_unknown_fallback() -> None:
    headers = aminer_headers("test-key")

    assert headers["Authorization"] == "test-key"
    assert headers["X-Platform"] == "unknown"
    assert headers["X-Skill-Name"] == "baseline-finder"
    assert headers["X-Skill-Version"] == __version__ == "0.5.2"
    assert headers["Content-Type"] == "application/json;charset=utf-8"


def test_runtime_header_uses_explicit_override_before_host_detection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AMINER_SKILL_RUNTIME", " OpenClaw ")
    monkeypatch.setenv("CLAUDE_CODE", "1")

    assert detect_skill_runtime() == "openclaw"


def test_runtime_header_detects_supported_host_and_unknown_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CURSOR_AGENT", "1")
    assert detect_skill_runtime() == "cursor"

    monkeypatch.delenv("CURSOR_AGENT")
    assert detect_skill_runtime() == "unknown"
