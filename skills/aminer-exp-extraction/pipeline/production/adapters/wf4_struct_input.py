"""Shared block-structure primitives for wf4 structured-input axes.

Extracted from ``wf4_nobert_struct.py`` so both input-axis strategies reuse the
same building blocks without one module importing the other's private helpers:

  * ``nobert-struct-full`` (``--skip-bert-filter``) — skip SciBERT, full text.
  * ``bert-struct-60``     (``--bert-struct``)      — keep SciBERT, cap 60.

Both consume ``merge_union_text`` output, which emits three block markers on
their own lines:

    === EXPERIMENT ===
    === ABSINTRO ===
    === DATASET_FALLBACK ===

``split_sentences`` (``bert_client.py``) collapses all whitespace with
``re.sub(r"\\s+", " ", text)`` BEFORE sentence splitting, smearing these markers
into adjacent sentences — block structure is lost before BERT/LLM ever see it.
The primitives here split the merged text **by marker first**, wash each block
independently (same pipeline as PREP), and cross-block dedup (EXPERIMENT wins)
so callers get clean block boundaries and no cross-block duplicates.

These functions are pure text ops — no BERT, no LLM, no cap. Each strategy
applies its own cap/overflow policy on top.
"""

from __future__ import annotations

import re
from typing import Any

from pipeline.benchmark.config import (
    ABSINTRO_SECTION_MARKER,
    DATASET_FALLBACK_SECTION_MARKER,
    EXPERIMENT_SECTION_MARKER,
)
from pipeline.benchmark.stages.bert_client import filter_english_only, split_sentences
from pipeline.production.adapters.wf4_sentence_clean import wf4_clean_sentences_for_llm

# Block order matches merge_union_text (EXPERIMENT -> ABSINTRO -> DATASET_FALLBACK).
BLOCK_ORDER: tuple[str, ...] = (
    EXPERIMENT_SECTION_MARKER,
    ABSINTRO_SECTION_MARKER,
    DATASET_FALLBACK_SECTION_MARKER,
)
BLOCK_MARKERS: frozenset[str] = frozenset(BLOCK_ORDER)

# A line that is exactly one of the three markers (merge_union_text emits them
# on their own line, separated from bodies by blank lines).
MARKER_SPLIT_RE = re.compile(
    r"(?:^|\n)[ \t]*===[ \t]+(EXPERIMENT|ABSINTRO|DATASET_FALLBACK)[ \t]+===[ \t]*(?=\n|$)"
)


# --------------------------------------------------------------------------- #
# Split merged text into (marker, body) blocks                                #
# --------------------------------------------------------------------------- #


def split_merged_into_blocks(merged_text: str) -> list[tuple[str, str]]:
    """Split ``merge_union_text`` output into ordered (marker, body) blocks.

    Returns blocks in EXPERIMENT -> ABSINTRO -> DATASET_FALLBACK order, skipping
    any marker that is absent. ``body`` is the raw text between this marker and
    the next (markers stripped, surrounding blank lines trimmed). Content before
    the first marker (shouldn't happen with merge_union_text, but defensively)
    is dropped.
    """
    matches = list(MARKER_SPLIT_RE.finditer(merged_text))
    if not matches:
        return []
    blocks: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        name = m.group(1)
        marker = f"=== {name} ==="
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(merged_text)
        body = merged_text[body_start:body_end].strip()
        blocks.append((marker, body))
    # Reorder to canonical block order (defensive; merge_union_text already emits
    # in this order, but a stray marker elsewhere must not break ordering).
    by_marker = {marker: body for marker, body in blocks}
    return [(m, by_marker[m]) for m in BLOCK_ORDER if m in by_marker]


# --------------------------------------------------------------------------- #
# Per-block wash (split + english filter + wf4 clean)                         #
# --------------------------------------------------------------------------- #


def wash_block(body: str) -> tuple[list[str], dict[str, Any]]:
    """Wash one block body into kept sentences using the SAME pipeline as PREP.

    Mirrors prepare_llm_inputs_wf4's per-block steps: split_sentences ->
    filter_english_only -> wf4_clean_sentences_for_llm. Wash rules are
    unchanged (dataset/data heading lines kept, other ``##`` headings dropped).
    """
    all_sentences = split_sentences(body)
    english_sentences = filter_english_only(all_sentences)
    if not english_sentences:
        return [], {"input_count": len(all_sentences), "kept_count": 0}
    kept, stats = wf4_clean_sentences_for_llm(english_sentences)
    return kept, stats


# --------------------------------------------------------------------------- #
# Cross-block exact dedup (EXPERIMENT wins)                                   #
# --------------------------------------------------------------------------- #


def dedup_key(s: str) -> str:
    """Normalize for exact dedup: collapse whitespace, strip, lowercase."""
    return re.sub(r"\s+", " ", s).strip().lower()


def dedup_blocks_preserve_order(
    blocks: list[tuple[str, list[str]]],
) -> tuple[list[tuple[str, list[str]]], dict[str, Any]]:
    """Cross-block exact dedup; first-seen wins (EXPERIMENT scanned first).

    Returns deduped blocks (empty blocks dropped) and stats:
    ``dedup_removed_count`` (total), ``dedup_removed_by_block`` (per-marker
    count of duplicates dropped *within* that block because they already
    appeared in an earlier block).
    """
    seen: set[str] = set()
    out: list[tuple[str, list[str]]] = []
    removed_by_block: dict[str, int] = {}
    removed_total = 0
    for marker, sents in blocks:  # EXPERIMENT first by block order
        kept: list[str] = []
        dropped = 0
        for s in sents:
            key = dedup_key(s)
            if not key:
                continue
            if key in seen:
                dropped += 1
                continue
            seen.add(key)
            kept.append(s)
        if kept:
            out.append((marker, kept))
        removed_by_block[marker] = dropped
        removed_total += dropped
    return out, {
        "dedup_removed_count": removed_total,
        "dedup_removed_by_block": removed_by_block,
    }


def flatten_structured_lines(deduped_blocks: list[tuple[str, list[str]]]) -> list[str]:
    """Flatten ``(marker, [sent])`` blocks into ``[marker, sent, sent, ...]``.

    The exact shape the ``structured`` prompt adapter renders: one marker
    sentinel line per non-empty block, followed by its bare sentences.
    Markers are never numbered and never count toward any sentence cap.
    """
    structured_lines: list[str] = []
    for marker, sents in deduped_blocks:
        structured_lines.append(marker)
        structured_lines.extend(sents)
    return structured_lines
