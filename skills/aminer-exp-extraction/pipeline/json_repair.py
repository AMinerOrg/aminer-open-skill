"""Repair and parse JSON from LLM outputs."""

from __future__ import annotations

import json
import re
from typing import Any


FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


THINKING_BLOCK_RE = re.compile(
    r"<\s*(?:think|redacted_thinking)\s*>.*?</\s*(?:think|redacted_thinking)\s*>",
    re.DOTALL | re.IGNORECASE,
)


def strip_thinking_blocks(text: str) -> str:
    cleaned = THINKING_BLOCK_RE.sub("", text)
    return cleaned.strip()


def strip_code_fence(text: str) -> str:
    text = strip_thinking_blocks(text)
    match = FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    if text.startswith("```") and text.endswith("```"):
        return text.strip("`").replace("json", "", 1).strip()
    return text


# JSON valid escape continuation chars (the char immediately after a backslash
# inside a string literal that json.loads accepts): " \ / b f n r t u
_JSON_VALID_ESCAPES = set('"\\/bfnrtu')


def _fix_invalid_escapes(text: str) -> str:
    """Fix invalid backslash escapes inside JSON string literals.

    LLMs frequently emit LaTeX / markdown backslashes inside JSON string values
    (e.g. ``\\Theta(n^{0.6})``, ``\\times``, ``\\approx``, ``\\%``). The JSON
    spec only permits ``\\" \\\\ \\/ \\b \\f \\n \\r \\t \\uXXXX``; any other
    ``\\X`` is an ``Invalid \\escape`` and makes ``json.loads`` reject the whole
    document — every LLM field then comes back empty (dev500: 24/30 parse_error
    papers failed on exactly this).

    This walker tracks string-literal context (honouring ``\\"`` so escaped
    quotes do not toggle state) and, for each backslash inside a string that is
    NOT a valid JSON escape, doubles it (``\\X`` -> ``\\\\X``) so it parses to a
    literal backslash + X — preserving the LLM's original content faithfully.

    A plain regex cannot do this correctly because it cannot tell an already-
    escaped ``\\\\`` (one literal backslash) apart from a lone ``\\X``; the
    stateful walker can. Valid JSON passes through unchanged (idempotent).
    """
    out: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    while i < n:
        ch = text[i]
        if not in_string:
            if ch == '"':
                in_string = True
            out.append(ch)
            i += 1
            continue
        # inside a string literal
        if ch == "\\":
            nxt = text[i + 1] if i + 1 < n else ""
            if nxt == "u":
                # \uXXXX requires exactly 4 hex digits. LLMs often emit LaTeX
                # commands like \underline, \upsilon, \unit where \u is followed
                # by non-hex — json.loads rejects these as "Invalid \uXXXX
                # escape". Validate the 4 chars after \u; if not all hex, treat
                # as an invalid escape (double the backslash -> literal \u...).
                hex4 = text[i + 2 : i + 6]
                if len(hex4) == 4 and all(c in "0123456789abcdefABCDEF" for c in hex4):
                    out.append(ch)
                    out.append(nxt)
                    out.extend(hex4)
                    i += 6
                else:
                    out.append("\\\\")
                    out.append(nxt)
                    i += 2
                continue
            if nxt in _JSON_VALID_ESCAPES:
                # valid escape (excl. \u, handled above) — keep both chars as-is
                out.append(ch)
                out.append(nxt)
                i += 2
            else:
                # invalid escape — double the backslash -> literal backslash + X
                out.append("\\\\")
                if nxt:
                    out.append(nxt)
                    i += 2
                else:
                    i += 1
            continue
        if ch == '"':
            in_string = False
        out.append(ch)
        i += 1
    return "".join(out)


def repair_json_text(text: str) -> str:
    cleaned = strip_code_fence(text)
    cleaned = cleaned.strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    cleaned = TRAILING_COMMA_RE.sub(r"\1", cleaned)
    cleaned = _fix_invalid_escapes(cleaned)
    return cleaned


def parse_json_object(text: str) -> tuple[dict[str, Any] | None, str | None]:
    """Parse JSON object with repair attempts."""
    candidates = [text.strip(), repair_json_text(text)]
    last_error: str | None = None

    for candidate in candidates:
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data, None
            last_error = "root is not a JSON object"
        except json.JSONDecodeError as exc:
            last_error = str(exc)

    return None, last_error


def extract_experiment_names(data: dict[str, Any]) -> list[str]:
    """Extract experiment_name list from parsed JSON."""
    return [item["experiment_name"] for item in extract_experiments(data)]


def extract_experiments(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract structured experiments with optional key_results."""
    experiments: list[dict[str, Any]] = []

    if "experiments" in data and isinstance(data["experiments"], list):
        for item in data["experiments"]:
            if not isinstance(item, dict):
                continue
            name = item.get("experiment_name") or item.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            key_results = _normalize_key_results(item.get("key_results"))
            experiments.append({
                "experiment_name": name.strip(),
                "key_results": key_results,
                "source_index": item.get("source_index"),
            })
        if experiments:
            return experiments

    if "experiment_names" in data and isinstance(data["experiment_names"], list):
        paper_key_results = _normalize_key_results(data.get("key_results"))
        for index, item in enumerate(data["experiment_names"]):
            if isinstance(item, str) and item.strip():
                experiments.append({
                    "experiment_name": item.strip(),
                    "key_results": paper_key_results if index == 0 else [],
                    "source_index": None,
                })
            elif isinstance(item, dict):
                name = item.get("experiment_name") or item.get("name")
                if isinstance(name, str) and name.strip():
                    experiments.append({
                        "experiment_name": name.strip(),
                        "key_results": _normalize_key_results(item.get("key_results")),
                        "source_index": item.get("source_index"),
                    })
        if experiments:
            return experiments

    single = data.get("experiment_name")
    if isinstance(single, str) and single.strip():
        experiments.append({
            "experiment_name": single.strip(),
            "key_results": _normalize_key_results(data.get("key_results")),
            "source_index": data.get("source_index"),
        })

    return experiments


def _normalize_key_results(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    results: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            results.append(re.sub(r"\s+", " ", item.strip()))
    return results
