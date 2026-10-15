"""wf4 nobert structured-input builder (skip-SciBERT ablation, opt-in only).

This module implements the **nobert input axis** for wf4: when SciBERT
``/filter/batch`` is skipped (``--skip-bert-filter``), the LLM is fed the
*full* washed + cross-block-deduped sentence list with the three
``=== EXPERIMENT / ABSINTRO / DATASET_FALLBACK ===`` block markers preserved
as structural headers, instead of the flat BERT-filtered top-40 numbered list.

Why this exists (see ``docs/STRATEGY_PROD_WF4_NOBERT_STRUCT.md``):
  * ``merge_union_text`` emits block markers, but ``split_sentences`` collapses
    all whitespace and smears the markers into adjacent sentences — structure is
    lost before BERT/LLM ever see it.
  * EXPERIMENT/ABSINTRO unions overlap (``SECTION_HEADER_RE`` mis-splits on
    bare ``#`` lines), producing exact-duplicate sentences that both enter the
    top-40 (e.g. ``63b63fca`` wastes 7/40 slots on adjacent duplicates).
  * This builder splits the merged text **by marker first**, washes each block
    independently, then cross-block dedupes (EXPERIMENT wins) — so the LLM sees
    clean block boundaries and no cross-block duplicates.

Block split / wash / dedup primitives live in ``wf4_struct_input`` (shared with
the ``bert-struct-60`` axis). This module only owns the nobert-specific
assembly: NO 40-sentence cap (full deduped set) + the char-budget overflow
decision used to route over-long papers to the BERT fallback path.

This module is **opt-in** (only called from the skip-bert scheduler branch).
The baseline (with-BERT) path never imports it, so baseline behavior is
unchanged.

Token/char budget note: there is no model tokenizer in the repo, so ``overflow``
is decided by a char threshold on the assembled structured prompt (caller passes
``max_prompt_chars``). The budget is conservative vs the ``num_ctx`` the caller
sets for the nobert path.
"""

from __future__ import annotations

from typing import Any

from pipeline.production.adapters.wf4_prompt_adapter import build_wf4_prompt_for_adapter
from pipeline.production.adapters.wf4_struct_input import (
    dedup_blocks_preserve_order,
    flatten_structured_lines,
    split_merged_into_blocks,
    wash_block,
)


def build_nobert_structured(
    prepared, *, max_prompt_chars: int, paper_title: str | None = None
) -> dict[str, Any]:
    """Build the nobert structured llm_input + prompt-size / overflow info.

    Args:
        prepared: ``LlmPrepared`` whose ``clean_stats["nobert_merged_text"]`` was
            stashed by PREP under ``WF4_SKIP_BERT_FILTER``.
        max_prompt_chars: char budget for the structured prompt; exceeding it
            marks the paper for BERT fallback (caller decides).
        paper_title: override (defaults to ``prepared.paper_title``).

    Returns dict with:
        structured_lines : list[str]  — marker sentinels + bare sentences
        prompt           : str        — assembled structured prompt
        prompt_chars     : int
        overflow         : bool       — prompt_chars > max_prompt_chars
        stats            : dict       — dedup + block + sentence-count stats
    """
    title = paper_title if paper_title is not None else prepared.paper_title
    merged = (prepared.clean_stats or {}).get("nobert_merged_text") or ""
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

    structured_lines = flatten_structured_lines(deduped)
    prompt = build_wf4_prompt_for_adapter(structured_lines, title, "structured")
    post_dedup_total = sum(len(sents) for _, sents in deduped)

    stats = {
        **dedup_stats,
        "input_sentence_count_pre_dedup": pre_dedup_total,
        "input_sentence_count_post_dedup": post_dedup_total,
        "nobert_blocks": [marker for marker, _ in deduped],
        "wash_stats": wash_stats,
    }
    return {
        "structured_lines": structured_lines,
        "prompt": prompt,
        "prompt_chars": len(prompt),
        "overflow": len(prompt) > max_prompt_chars,
        "stats": stats,
    }
