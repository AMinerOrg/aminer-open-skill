"""wf4 sentence cleaning — keep dataset/data heading lines, drop other junk.

A self-contained copy of ``pipeline/benchmark/stages/sentence_clean.py``'s
classify logic with one override: R3 (the markdown-heading / ALLCAPS-title /
chat-residue drop rule) is split so that ``#``-heading lines containing a
``WF4_SENTENCE_CLEAN_HEADING_KEEP_KEYWORDS`` token (default ``("dataset","data")``)
are KEPT (because wf4 needs dataset section headers as LLM extraction signal),
while other heading lines and ALLCAPS titles are still dropped.

The frozen ``sentence_clean.py`` is NOT modified — wf3/wf8 keep dropping all
heading lines. R1/R2/R4 junk rules (html_table, too_short, ocr_fragment) are
unchanged. Stats gain a ``dataset_heading_kept`` counter.
"""

from __future__ import annotations

import re
from typing import Any

from pipeline.production.config import WF4_SENTENCE_CLEAN_HEADING_KEEP_KEYWORDS

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


def _wf4_classify(s: str) -> str | None:
    """Return drop reason if ``s`` should be dropped, else None (keep).

    Same order as sentence_clean._classify (R1 -> R4); R3 heading branch is
    overridden to KEEP dataset/data headings.
    """
    if _HTML_TABLE_RE.search(s):
        return "html_table"
    stripped = s.strip()
    if len(stripped) < 30 or len(_WORD_RE.findall(s)) < 6:
        return "too_short"
    if _HEADING_RE.match(s):
        # wf4 override: keep heading lines mentioning dataset/data.
        lowered = s.lower()
        if any(kw in lowered for kw in WF4_SENTENCE_CLEAN_HEADING_KEEP_KEYWORDS):
            return None  # keep
        return "title_layout"
    if _ALLCAPS_TITLE_RE.match(stripped) or _CHAT_RE.match(stripped):
        return "title_layout"
    if not _LETTER_RE.search(s) or _letter_ratio(stripped) < 0.40 or _NUMERIC_LAYOUT_RE.match(s):
        return "ocr_fragment"
    return None


def wf4_clean_sentences_for_llm(sentences: list[str]) -> tuple[list[str], dict[str, Any]]:
    """Drop junk sentences before BERT/LLM (wf4 variant).

    Like ``clean_sentences_for_llm`` but keeps ``#``-heading lines that contain
    a dataset/data keyword. Returns (kept_sentences, stats). Kept sentences are
    whitespace-normalized; semantics are never rewritten.
    """
    kept: list[str] = []
    dropped_by_reason: dict[str, int] = {
        "html_table": 0,
        "too_short": 0,
        "title_layout": 0,
        "ocr_fragment": 0,
    }
    dropped_samples: list[str] = []
    dataset_heading_kept = 0

    for s in sentences:
        reason = _wf4_classify(s)
        if reason is None:
            # A kept heading line that matched the dataset/data keep-rule counts.
            if _HEADING_RE.match(s):
                dataset_heading_kept += 1
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
        "dataset_heading_kept": dataset_heading_kept,
    }
    return kept, stats
