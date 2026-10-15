"""wf8 split into two LLM stages for cross-paper pipelining (prod-wf2).

wf8's LLM step is normally one blocking call (BERT ~2.5s + LLM ~2.0s). For
batch runs we split it so paper n's LLM can overlap paper n+1's BERT. The
stages mirror ``wf8_core.run_wf8_pipeline`` step-for-step (line refs in
comments) and reuse the SAME imported functions — no algorithm rewrite, no
``run_wf8_pipeline`` whole-call. Output FieldResult shape is identical to
``adapters/wf8_llm.run_wf8_for_production`` so the Merger is unaware.

Stage-P ``prepare_llm_inputs``  : read md -> title -> preprocess -> union ->
                                  split -> english -> sentence_clean (wash)
Stage-A ``run_bert_stage``      : BERT filter + select_llm_sentences
Stage-B ``run_qwen_stage``      : build prompt -> LLM -> parse -> 7 fields
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipeline.benchmark.config import WF1_BERT_THRESHOLD, WF1_MAX_LLM_SENTENCES
from pipeline.benchmark.parse_helpers import normalize_string_list
from pipeline.benchmark.stages.bert_client import (
    SerialBertClient,
    filter_english_only,
    split_sentences,
)
from pipeline.benchmark.stages.llm_client import SingleLLMClient
from pipeline.benchmark.stages.sentence_clean import clean_sentences_for_llm
from pipeline.benchmark.stages.union_merge import merge_union_text
from pipeline.benchmark.workflows.wf1_merged import (
    extract_paper_title,
    select_llm_sentences,
)
from pipeline.benchmark.workflows.wf8_core import build_wf8_dev20_v2_prompt
from pipeline.json_repair import parse_json_object, repair_json_text
from preprocess.pipeline import run_preprocess_steps
from preprocess.section_union import union_experiment_sections
from preprocess.section_union_abs_intro import union_abs_intro_sections

from pipeline.production.adapters.wf8_llm import LLM_GROUP_FIELDS
from pipeline.production.config import (
    WF8_METRICS_CAP,
    WF8_LLM_MODE_LABEL,
    WF8_SENTENCE_CLEAN,
    WF8_WORKFLOW_ID,
    WF8_WORKFLOW_VERSION,
)
from pipeline.production.schema import FieldResult

EXTRACTOR_ID = "llm.wf8_dev20_v2_wash"


@dataclass
class LlmPrepared:
    paper_title: str
    english_sentences: list[str]
    timings: dict[str, float] = field(default_factory=dict)
    clean_stats: dict[str, Any] = field(default_factory=dict)


@dataclass
class BertStageResult:
    llm_input: list[str]
    sentence_selection: dict[str, Any]
    bert_raw: dict[str, Any]
    timings: dict[str, float] = field(default_factory=dict)


def prepare_llm_inputs(md_path: Path) -> LlmPrepared:
    """Stage-P — mirrors wf8_core L218–292 (preprocess + union + split + wash)."""
    md_text = md_path.read_text(encoding="utf-8")
    paper_title = extract_paper_title(md_text)

    t = time.perf_counter()
    preprocess_result = run_preprocess_steps(
        md_text, steps=["strip_references", "compact_markdown"]
    )
    preprocess_elapsed = time.perf_counter() - t

    t = time.perf_counter()
    experiment_union = union_experiment_sections(preprocess_result.text)
    absintro_union = union_abs_intro_sections(preprocess_result.text)
    merged_text = merge_union_text(experiment_union.text, absintro_union.text)
    union_elapsed = time.perf_counter() - t

    t = time.perf_counter()
    all_sentences = split_sentences(merged_text)
    english_sentences = filter_english_only(all_sentences)
    split_elapsed = time.perf_counter() - t

    if not english_sentences:
        raise RuntimeError("No English sentences after preprocessing")

    clean_stats: dict[str, Any] = {}
    clean_elapsed = 0.0
    if WF8_SENTENCE_CLEAN:
        t = time.perf_counter()
        english_sentences, clean_stats = clean_sentences_for_llm(english_sentences)
        clean_elapsed = time.perf_counter() - t
        if not english_sentences:
            raise RuntimeError("No sentences after sentence_clean")

    return LlmPrepared(
        paper_title=paper_title,
        english_sentences=english_sentences,
        timings={
            "preprocess": preprocess_elapsed,
            "union_merge": union_elapsed,
            "sentence_split": split_elapsed,
            "sentence_clean": clean_elapsed,
        },
        clean_stats=clean_stats,
    )


def run_bert_stage(
    prepared: LlmPrepared, bert_client: SerialBertClient | None = None
) -> BertStageResult:
    """Stage-A — mirrors wf8_core L294–328 (BERT filter + sentence selection)."""
    client = bert_client or SerialBertClient()

    t = time.perf_counter()
    bert_result = client.filter_sentences_serial(
        prepared.english_sentences,
        threshold=WF1_BERT_THRESHOLD,
    )
    bert_elapsed = time.perf_counter() - t

    if bert_result["kept_count"] == 0:
        raise RuntimeError("No sentences passed BERT filter")

    llm_input, sentence_selection = select_llm_sentences(
        bert_result["kept_sentences"],
        bert_result.get("confidences"),
    )
    return BertStageResult(
        llm_input=llm_input,
        sentence_selection=sentence_selection,
        bert_raw={
            "kept_count": bert_result["kept_count"],
            "total": bert_result["total"],
        },
        timings={"bert_filter": bert_elapsed},
    )


def run_qwen_stage(
    prepared: LlmPrepared,
    bert_result: BertStageResult,
    llm_client: SingleLLMClient | None = None,
    *,
    run_id: str = "",
    bert_mode: str = "serial",
) -> FieldResult:
    """Stage-B — mirrors wf8_core L330–402 (prompt + LLM + parse + 7 fields).

    Output FieldResult is shape-compatible with ``run_wf8_for_production``.
    ``bert_mode`` is recorded in provenance ("serial" for wf2's per-paper /filter,
    "batch" for wf3's /filter/batch); does not affect the LLM call itself.
    """
    client = llm_client or SingleLLMClient()

    t = time.perf_counter()
    prompt = build_wf8_dev20_v2_prompt(bert_result.llm_input, prepared.paper_title)
    prompt_chars = len(prompt)
    llm_result = client.generate(prompt, temperature=0.05, num_predict=2048)
    llm_elapsed = time.perf_counter() - t

    raw = llm_result["raw_output"]
    repaired = repair_json_text(raw)
    parsed, parse_error = parse_json_object(raw)

    experiment_subject = normalize_string_list(
        parsed.get("experiment_subject") if parsed else None
    )
    metrics = normalize_string_list(
        parsed.get("metrics") if parsed else None, max_items=WF8_METRICS_CAP
    )

    value: dict[str, Any] = {
        "experiment_name": parsed.get("experiment_name", "") if parsed else "",
        "key_results": parsed.get("key_results", []) if parsed else [],
        "method": parsed.get("method", "") if parsed else "",
        "research_problem": parsed.get("research_problem", "") if parsed else "",
        "research_goal": parsed.get("research_goal", "") if parsed else "",
        "experiment_subject": experiment_subject,
        "metrics": metrics,
    }

    total = (
        prepared.timings.get("preprocess", 0.0)
        + prepared.timings.get("union_merge", 0.0)
        + prepared.timings.get("sentence_clean", 0.0)
        + bert_result.timings.get("bert_filter", 0.0)
        + llm_elapsed
    )
    time_breakdown = {
        "preprocess": round(prepared.timings.get("preprocess", 0.0), 4),
        "union_merge": round(prepared.timings.get("union_merge", 0.0), 4),
        "sentence_clean": round(prepared.timings.get("sentence_clean", 0.0), 4),
        "bert_filter": round(bert_result.timings.get("bert_filter", 0.0), 4),
        "llm_generate": round(llm_elapsed, 4),
        "total": round(total, 4),
    }
    provenance = {
        "union_mode": "merged",
        "bert_mode": bert_mode,
        "llm_mode": WF8_LLM_MODE_LABEL,
        "output_schema": "v7",
        "bert_threshold": WF1_BERT_THRESHOLD,
        "max_llm_sentences": WF1_MAX_LLM_SENTENCES,
        "metrics_cap": WF8_METRICS_CAP,
        "sentence_clean": WF8_SENTENCE_CLEAN,
        "experiment_axis": "input-sentence-clean" if WF8_SENTENCE_CLEAN else None,
        "wf8_stages": True,
        "workflow_id": WF8_WORKFLOW_ID,
    }

    return FieldResult(
        extractor_id=EXTRACTOR_ID,
        version=WF8_WORKFLOW_VERSION,
        status="ok",
        value=value,
        fields=list(LLM_GROUP_FIELDS),
        metadata={
            "paper_title": prepared.paper_title,
            "wf8_stages": True,
            "time_breakdown_sec": time_breakdown,
            "provenance": provenance,
            "parse_error": parse_error,
            "prompt_chars": prompt_chars,
            "llm_eval_count": llm_result.get("eval_count"),
            "raw_output_preview": raw[:200],
            "repaired_json": repaired,
            "run_id": run_id,
        },
    )


# ---------------------------------------------------------------------------
# Batch BERT (/filter/batch) — for prod-wf3 cross-paper GPU batching.
# Uses Stage-P english_sentences (NOT origin-split combined).
# ---------------------------------------------------------------------------

# Auto-chunk guards (survey-paper protection).
_BATCH_TOTAL_SENTENCE_THRESHOLD = 3000
_BATCH_SINGLE_PAPER_SENTENCE_THRESHOLD = 500
_BATCH_DEFAULT_CHUNK_PAPERS = 5


def run_bert_stage_from_batch_entry(
    prepared: LlmPrepared,
    batch_entry: dict[str, Any],
    *,
    chunk_index: int = 0,
) -> BertStageResult:
    """Build a BertStageResult from one /filter/batch per-paper entry.

    Uses the batch-returned ``kept`` + ``confidences`` and runs
    ``select_llm_sentences`` (same as ``run_bert_stage``). ``timings.bert_filter``
    is 0 — the real BERT cost is amortized in the batch_monitor, not per paper.
    """
    kept_sentences = list(batch_entry.get("kept", []))
    confidences = batch_entry.get("confidences")
    llm_input, sentence_selection = select_llm_sentences(kept_sentences, confidences)
    return BertStageResult(
        llm_input=llm_input,
        sentence_selection=sentence_selection,
        bert_raw={
            "kept_count": batch_entry.get("kept_count", len(kept_sentences)),
            "total": batch_entry.get("total", len(prepared.english_sentences)),
        },
        timings={
            "bert_filter": 0.0,  # amortized; see batch_monitor
            "bert_batch_chunk": chunk_index,
        },
    )


def _decide_chunking(
    prepared_map: dict[str, LlmPrepared],
    chunk_max_papers: int | None,
) -> int:
    """Return papers-per-chunk (or len if one shot)."""
    total_sentences = sum(len(p.english_sentences) for p in prepared_map.values())
    max_single = max((len(p.english_sentences) for p in prepared_map.values()), default=0)
    if chunk_max_papers and chunk_max_papers > 0:
        return chunk_max_papers
    if total_sentences > _BATCH_TOTAL_SENTENCE_THRESHOLD or max_single > _BATCH_SINGLE_PAPER_SENTENCE_THRESHOLD:
        return _BATCH_DEFAULT_CHUNK_PAPERS
    return len(prepared_map)  # one shot


def run_bert_batch_for_papers(
    prepared_map: dict[str, LlmPrepared],
    *,
    chunk_max_papers: int | None = None,
    batch_size: int = 32,
) -> tuple[dict[str, BertStageResult], dict[str, Any]]:
    """Run /filter/batch across all papers (chunked if large) -> (per-paper results, batch_monitor).

    ``chunk_max_papers``: force papers-per-chunk; 0/None -> auto (one shot unless
    total sentences > 3000 or a single paper > 500, then 5/chunk).
    """
    raise RuntimeError(
        "SciBERT /filter/batch path removed — this skill uses the GLM "
        "sentence filter only (public BigModel service, no internal services)"
    )

    paper_ids = list(prepared_map.keys())
    per_chunk = _decide_chunking(prepared_map, chunk_max_papers or None)
    chunks: list[dict[str, Any]] = []
    results: dict[str, BertStageResult] = {}

    total_inference_ms = 0.0
    total_client_sec = 0.0
    total_sentences = 0
    total_kept = 0

    for chunk_index, start in enumerate(range(0, len(paper_ids), per_chunk)):
        chunk_ids = paper_ids[start : start + per_chunk]
        chunk_papers = [
            {"paper_id": pid, "sentences": prepared_map[pid].english_sentences}
            for pid in chunk_ids
        ]
        chunk_started = _utc_now()
        batch_data = filter_papers_batch(chunk_papers, batch_size=batch_size)
        chunk_finished = _utc_now()
        inference_ms = float(batch_data.get("inference_time_ms", 0.0))
        client_sec = float(batch_data.get("client_elapsed_sec", 0.0))
        chunk_total_sent = int(batch_data.get("total_sentences", 0))
        chunk_total_kept = int(batch_data.get("total_kept", 0))
        chunks.append(
            {
                "chunk_index": chunk_index,
                "paper_ids": chunk_ids,
                "total_sentences": chunk_total_sent,
                "total_kept": chunk_total_kept,
                "inference_time_ms": inference_ms,
                "client_elapsed_sec": client_sec,
                "started_at": chunk_started,
                "finished_at": chunk_finished,
            }
        )
        total_inference_ms += inference_ms
        total_client_sec += client_sec
        total_sentences += chunk_total_sent
        total_kept += chunk_total_kept

        entry_by_id = {e["paper_id"]: e for e in batch_data.get("papers", [])}
        chunk_n = max(1, len(chunk_ids))
        for pid in chunk_ids:
            entry = entry_by_id.get(pid, {})
            results[pid] = run_bert_stage_from_batch_entry(
                prepared_map[pid], entry, chunk_index=chunk_index
            )
            # stash amortized bert cost on the BertStageResult for the scheduler
            results[pid].timings["bert_amortized_sec"] = round(client_sec / chunk_n, 4)

    batch_monitor = {
        "chunks": chunks,
        "chunk_count": len(chunks),
        "total_inference_ms": round(total_inference_ms, 2),
        "total_client_sec": round(total_client_sec, 4),
        "total_sentences": total_sentences,
        "total_kept": total_kept,
        "batch_size": batch_size,
    }
    return results, batch_monitor


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
