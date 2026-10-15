"""wf4 bert-struct-60 structured-input builder (keep SciBERT + block structure + 60 cap).

This module implements the **bert-struct-60 input axis** for wf4: SciBERT
``/filter/batch`` is STILL called (unlike ``nobert-struct-full``), but the LLM
input preserves the three ``=== EXPERIMENT / ABSINTRO / DATASET_FALLBACK ===``
block markers and the sentence cap is raised from 40 to 60.

Why this exists (see ``docs/STRATEGY_PROD_WF4_BERT_STRUCT_60.md``):
  * ``nobert-struct-full`` proved block structure + cross-block dedup raises
    Silver datasets.recall (0.368 -> 0.58) — but it drops SciBERT entirely and
    inflates the prompt to ~22.8k chars (+37% wall).
  * ``bert-struct-60`` isolates the single variable: keep SciBERT, only change
    the input form from "flat 40" to "structured 60". Question: does it recover
    most of nobert's recall gain at much lower prompt/wall cost?

Mechanism (structure-first + index-based block re-attachment):
  1. ``build_bert_struct_blocks`` — split merged_text by marker (reuses
     ``wf4_struct_input``), wash each block, cross-block dedup (EXPERIMENT
     wins). Produces ``flat_sentences`` + a parallel ``block_ids`` list (one
     marker per sentence, index-aligned). Dedup runs BEFORE BERT so neither
     BERT inference nor the 60 slots are wasted on EXPERIMENT/ABSINTRO dupes.
  2. The scheduler sends ``flat_sentences`` to ``/filter/batch`` (same service
     path as ``bert-flat-40``). The server returns ``kept`` + ``indices`` +
     ``confidences`` (``indices`` is local 0-based into the input list).
  3. ``build_bert_structured`` re-attaches block membership via
     ``block_ids[indices[i]]`` (exact, not guessed), groups kept sentences by
     block, selects up to 60 (metric-rich + conf when over cap, then re-sorted
     to document order), and renders via the ``structured`` prompt adapter.

This module is **opt-in** (only called from the ``--bert-struct`` scheduler
branch). The baseline (``bert-flat-40``) path never imports it, so baseline
behavior is unchanged. Schema/rules are byte-identical to V0 via the shared
``_render_wf4_prompt_body`` used by the ``structured`` adapter.
"""

from __future__ import annotations

from typing import Any

from pipeline.benchmark.workflows.wf1_merged import metric_richness_score
from pipeline.production.adapters.wf4_prompt_adapter import build_wf4_prompt_for_adapter
from pipeline.production.adapters.wf4_struct_input import (
    BLOCK_ORDER,
    dedup_blocks_preserve_order,
    flatten_structured_lines,
    split_merged_into_blocks,
    wash_block,
)

# Block rank for canonical ordering (EXPERIMENT -> ABSINTRO -> DATASET_FALLBACK).
_BLOCK_RANK: dict[str, int] = {m: i for i, m in enumerate(BLOCK_ORDER)}


def build_bert_struct_blocks(prepared) -> dict[str, Any]:
    """Split + wash + cross-block-dedup merged_text into BERT-ready sentences.

    Reads ``prepared.clean_stats["merged_text"]`` (stashed unconditionally by
    PREP). Returns the deduped blocks plus a flat sentence list and a parallel
    ``block_ids`` list (one marker per sentence, index-aligned) — the exact list
    sent to ``/filter/batch`` so the returned ``indices`` map back to blocks.

    Returns dict with:
        deduped_blocks : list[tuple[str, list[str]]] — (marker, [sent]) per block
        flat_sentences  : list[str]                 — deduped sentences in doc order
        block_ids       : list[str]                 — marker per flat_sentences[i]
        stats           : dict                      — dedup + sentence-count stats
    """
    merged = (prepared.clean_stats or {}).get("merged_text") or ""
    raw_blocks = split_merged_into_blocks(merged)

    washed: list[tuple[str, list[str]]] = []
    wash_stats: dict[str, Any] = {}
    pre_dedup_total = 0
    for marker, body in raw_blocks:
        kept, wstats = wash_block(body)
        washed.append((marker, kept))
        wash_stats[marker] = wstats
        pre_dedup_total += len(kept)

    deduped, dedup_stats = dedup_blocks_preserve_order(washed)

    flat_sentences: list[str] = []
    block_ids: list[str] = []
    for marker, sents in deduped:
        flat_sentences.extend(sents)
        block_ids.extend([marker] * len(sents))
    post_dedup_total = sum(len(sents) for _, sents in deduped)

    stats = {
        **dedup_stats,
        "input_sentence_count_pre_dedup": pre_dedup_total,
        "input_sentence_count_post_dedup": post_dedup_total,
        "deduped_block_markers": [marker for marker, _ in deduped],
        "wash_stats": wash_stats,
    }
    return {
        "deduped_blocks": deduped,
        "flat_sentences": flat_sentences,
        "block_ids": block_ids,
        "stats": stats,
    }


def select_struct_sentences(
    kept_tagged: list[tuple[str, str, float, int]],
    *,
    max_sentences: int = 60,
) -> tuple[list[tuple[str, list[str]]], dict[str, Any]]:
    """Select up to ``max_sentences`` kept sentences, preserving block structure.

    Args:
        kept_tagged: ``(block_id, text, conf, orig_idx)`` per kept sentence, in
            document order (``orig_idx`` is the index into the BERT input list,
            which is monotonic in EXPERIMENT -> ABSINTRO -> DATASET_FALLBACK).
        max_sentences: cap on *sentence* count (markers never counted).

    - If kept <= cap: keep all, document order (no rerank).
    - If kept >  cap: rank by ``(-metric_richness, -conf, +orig_idx)`` (same
      semantics as ``select_llm_sentences``), take top cap, then re-sort the
      selected by ``orig_idx`` to restore document block order.

    Returns ``(selected_blocks, stats)`` where selected_blocks is
    ``(marker, [sent])`` in canonical block order and stats carries
    ``selected``/``total_kept``/``truncated``/``selected_by_block``/
    ``max_qwen_sentences``/``metric_rich_selected``.
    """
    total = len(kept_tagged)
    truncated = total > max_sentences
    if not truncated:
        selected_tagged = list(kept_tagged)
    else:
        ranked = sorted(
            kept_tagged,
            key=lambda t: (-metric_richness_score(t[1]), -(t[2] or 0.0), t[3]),
        )
        top = ranked[:max_sentences]
        # Restore document order (orig_idx is monotonic across blocks).
        selected_tagged = sorted(top, key=lambda t: t[3])

    grouped: dict[str, list[str]] = {}
    for block_id, text, _conf, _idx in selected_tagged:
        grouped.setdefault(block_id, []).append(text)
    selected_blocks = [(m, grouped[m]) for m in BLOCK_ORDER if m in grouped]
    selected_by_block = {m: len(grouped[m]) for m, _ in selected_blocks}
    selected_count = sum(len(ss) for _, ss in selected_blocks)
    metric_rich_selected = sum(
        1 for _m, text, _c, _i in selected_tagged if metric_richness_score(text) > 0
    )

    stats = {
        "total_kept": total,
        "selected": selected_count,
        "truncated": truncated,
        "selected_by_block": selected_by_block,
        "max_llm_sentences": max_sentences,
        "metric_rich_selected": metric_rich_selected,
    }
    return selected_blocks, stats


def build_bert_structured(
    prepared,
    batch_entry: dict[str, Any],
    *,
    max_sentences: int = 60,
    paper_title: str | None = None,
) -> dict[str, Any]:
    """Re-attach block membership to BERT-kept sentences + assemble structured prompt.

    Args:
        prepared: ``LlmPrepared`` whose ``clean_stats["merged_text"]`` was stashed
            unconditionally by PREP.
        batch_entry: one ``/filter/batch`` per-paper entry — ``{kept, indices,
            confidences, total, kept_count}``. ``indices[i]`` is the local index
            into the ``flat_sentences`` list built by ``build_bert_struct_blocks``.
        max_sentences: sentence cap (60 for bert-struct-60).
        paper_title: override (defaults to ``prepared.paper_title``).

    Returns dict with:
        structured_lines : list[str] — marker sentinels + selected bare sentences
        prompt           : str       — assembled structured prompt
        prompt_chars     : int
        stats            : dict      — dedup + selection + bert stats
    """
    built = build_bert_struct_blocks(prepared)
    block_ids = built["block_ids"]
    stats_base = built["stats"]

    kept = list(batch_entry.get("kept", []))
    indices = batch_entry.get("indices") or []
    confidences = batch_entry.get("confidences") or []

    # Re-attach block_id via indices[i] (exact, not guessed). Skip any kept
    # sentence whose index is missing/out-of-range (defensive — should not happen
    # since the server aligns indices to the input list we sent).
    kept_tagged: list[tuple[str, str, float, int]] = []
    for i, text in enumerate(kept):
        idx = indices[i] if i < len(indices) else None
        conf = float(confidences[i]) if i < len(confidences) else 0.0
        if idx is None or not (0 <= idx < len(block_ids)):
            continue
        kept_tagged.append((block_ids[idx], text, conf, idx))

    selected_blocks, sel_stats = select_struct_sentences(
        kept_tagged, max_sentences=max_sentences
    )

    structured_lines = flatten_structured_lines(selected_blocks)
    title = paper_title if paper_title is not None else prepared.paper_title
    prompt = build_wf4_prompt_for_adapter(structured_lines, title, "structured")

    stats = {
        **stats_base,
        **sel_stats,
        "bert_kept_count": len(kept),
        "bert_total": batch_entry.get("total", len(built["flat_sentences"])),
        "bert_struct_blocks": [marker for marker, _ in selected_blocks],
        "bert_struct_prompt_chars": len(prompt),
    }
    return {
        "structured_lines": structured_lines,
        "prompt": prompt,
        "prompt_chars": len(prompt),
        "stats": stats,
    }
