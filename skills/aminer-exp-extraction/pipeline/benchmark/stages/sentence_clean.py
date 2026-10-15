"""Conservative sentence cleaning before BERT/LLM (input-sentence-clean axis).

Drops junk sentences (HTML/table residue, too-short fragments, title/layout
lines, OCR/numeric fragments) that survived preprocess + split + english_filter.
Conservative: when unsure, keep. Does NOT rewrite semantics, does NOT call an
LLM, does NOT extract metrics by regex. Only normalizes whitespace on kept
sentences.

Used by the wf8 v2 ``*wash`` variants (dev10v2wash / dev20v2wash) — a single
insertion point between ``filter_english_only`` and the BERT filter.
"""

from __future__ import annotations

import re
from typing import Any

# R1: HTML / table residue
_HTML_TABLE_RE = re.compile(r"<html|<table|</tr>|<td|<th", re.IGNORECASE)
# R3: markdown heading line
_HEADING_RE = re.compile(r"^\s*#{1,3}\s")
# R3: ALLCAPS title / layout line (>=16 chars of caps/digits/punct)
_ALLCAPS_TITLE_RE = re.compile(r"^[A-Z][A-Z\s\d\.\(\)\\%/]{15,}$")
# R3: chat residue
_CHAT_RE = re.compile(r"^(Human:|Assistant:)")
# R4: pure numeric/punct layout line
_NUMERIC_LAYOUT_RE = re.compile(r"^\s*[\d\.\$\\\%\(\),\s]+\s*$")
_LETTER_RE = re.compile(r"[a-zA-Z]")
_WORD_RE = re.compile(r"[a-zA-Z]+")


def _letter_ratio(s: str) -> float:
    n = len(s)
    if not n:
        return 0.0
    return len(_LETTER_RE.findall(s)) / n


def _classify(s: str) -> str | None:
    """Return drop reason if ``s`` should be dropped, else None (keep).

    Checked in order R1 -> R4; first hit wins.
    """
    if _HTML_TABLE_RE.search(s):
        return "html_table"
    stripped = s.strip()
    if len(stripped) < 30 or len(_WORD_RE.findall(s)) < 6:
        return "too_short"
    if _HEADING_RE.match(s) or _ALLCAPS_TITLE_RE.match(stripped) or _CHAT_RE.match(stripped):
        return "title_layout"
    if not _LETTER_RE.search(s) or _letter_ratio(stripped) < 0.40 or _NUMERIC_LAYOUT_RE.match(s):
        return "ocr_fragment"
    return None


def clean_sentences_for_llm(sentences: list[str]) -> tuple[list[str], dict[str, Any]]:
    """Drop junk sentences before BERT/LLM. Conservative: when unsure, keep.

    Returns (kept_sentences, stats). Kept sentences are whitespace-normalized
    (``re.sub(r"\\s+", " ", s).strip()``); semantics are never rewritten.
    """
    kept: list[str] = []
    dropped_by_reason: dict[str, int] = {
        "html_table": 0,
        "too_short": 0,
        "title_layout": 0,
        "ocr_fragment": 0,
    }
    dropped_samples: list[str] = []

    for s in sentences:
        reason = _classify(s)
        if reason is None:
            kept.append(re.sub(r"\s+", " ", s).strip())
        else:
            dropped_by_reason[reason] += 1
            if len(dropped_samples) < 5:
                dropped_samples.append(s.strip()[:120])

    dropped_count = len(sentences) - len(kept)
    stats: dict[str, Any] = {
        "input_count": len(sentences),
        "kept_count": len(kept),
        "dropped_count": dropped_count,
        "dropped_by_reason": dropped_by_reason,
        "dropped_samples": dropped_samples,
    }
    return kept, stats
