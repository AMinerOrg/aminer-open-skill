"""wf4 split LLM stages (8 fields: 7 wf8 fields + datasets[]) for prod-wf4.

Mirrors ``adapters/wf8_stages.py`` step-for-step and reuses the SAME imported
functions (no algorithm rewrite). Three seams differ from wf8:

  Stage-P ``prepare_llm_inputs_wf4`` : union -> ``wf4_union_experiment_sections``
                                       (adds "data" keyword); sentence_clean ->
                                       ``wf4_clean_sentences_for_llm`` (keeps
                                       dataset/data heading lines).
  Stage-B ``run_llm_stage_wf4``     : prompt -> ``build_wf4_prompt`` (8-field);
                                       adds ``normalize_llm_datasets``; provenance
                                       max_qwen_sentences=40, llm_mode=wf4_8field_datasets;
                                       metadata adds datasets_count + dataset_leak_count.
  Batch    ``run_bert_batch_for_papers_wf4`` : passes max_sentences=WF4_MAX_QWEN_SENTENCES
                                       (40) into select_llm_sentences (wf8 defaults to 35).

BERT filtering itself is identical to wf8 — only the sentence-selection cap and
the per-paper entry builder are wf4-specific. ``LlmPrepared`` / ``BertStageResult``
are reused from ``wf8_stages`` (not redefined) so the batch BERT client and the
LLM stage stay shape-compatible.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from pipeline.benchmark.config import WF1_BERT_THRESHOLD
from pipeline.benchmark.parse_helpers import count_dataset_leaks
from pipeline.benchmark.stages.bert_client import filter_english_only, split_sentences
from pipeline.benchmark.stages.llm_client import SingleLLMClient
from pipeline.benchmark.stages.union_merge import merge_union_text
from pipeline.benchmark.workflows.wf1_merged import extract_paper_title, select_llm_sentences
from pipeline.json_repair import parse_json_object, repair_json_text
from preprocess.pipeline import run_preprocess_steps
from preprocess.section_union_abs_intro import union_abs_intro_sections

from pipeline.production.adapters.wf4_bert_struct import build_bert_struct_blocks, build_bert_structured
from pipeline.production.adapters.wf4_normalize import coerce_wf4_llm_parsed


def _bert_retry_kwargs(
    bert_timeout: int | None, bert_retries: int | None
) -> dict[str, Any]:
    """Build kwargs for filter_papers_batch, omitting None values.

    Keeps the wf8 call site (which does not pass these) unchanged by not
    injecting defaults from this layer — defaults live in bert_batch_client.
    """
    kw: dict[str, Any] = {}
    if bert_timeout is not None:
        kw["timeout"] = bert_timeout
    if bert_retries is not None:
        kw["retries"] = bert_retries
    return kw


from pipeline.production.adapters.dataset_confidence import score_datasets_confidence
from pipeline.production.adapters.wf4_nobert_struct import build_nobert_structured
from pipeline.production.adapters.wf4_prompt_adapter import build_wf4_prompt_for_adapter
from pipeline.production.adapters.wf4_sentence_clean import wf4_clean_sentences_for_llm
from pipeline.production.adapters.wf4_union import (
    _section_matches_wf4,
    wf4_union_experiment_sections,
)
from pipeline.production.adapters.wf8_stages import (
    BertStageResult,
    LlmPrepared,
    _decide_chunking,
    _utc_now,
)
from pipeline.production.config import (
    WF4_DATASETS_CAP,
    WF4_DATASET_SECTION_FALLBACK,
    WF4_LLM_EXTRACTOR_ID,
    WF4_MAX_EXPERIMENTS,
    WF4_MAX_QWEN_SENTENCES,
    WF4_WORKFLOW_ID,
    WF4_WORKFLOW_VERSION,
    WF8_METRICS_CAP,
    WF8_LLM_MODE_LABEL,
    WF8_SENTENCE_CLEAN,
)
from preprocess.section_union_dataset_fallback import (
    DatasetFallbackResult,
    apply_dataset_section_fallback,
)
from pipeline.production.schema import FieldResult

# --------------------------------------------------------------------------- #
# Stage-P: prepare LLM inputs (wf4 union + wf4 wash)                          #
# --------------------------------------------------------------------------- #


def prepare_llm_inputs_wf4(md_path: Path) -> LlmPrepared:
    """Stage-P (wf4) — preprocess + wf4 union + split + wf4 sentence_clean."""
    md_text = md_path.read_text(encoding="utf-8")
    paper_title = extract_paper_title(md_text)

    t = time.perf_counter()
    preprocess_result = run_preprocess_steps(
        md_text, steps=["strip_references", "compact_markdown"]
    )
    preprocess_elapsed = time.perf_counter() - t

    t = time.perf_counter()
    experiment_union = wf4_union_experiment_sections(preprocess_result.text)  # +data keyword
    absintro_union = union_abs_intro_sections(preprocess_result.text)

    # Dataset-section fallback (shared preprocess capability): when the primary
    # union captured no dataset-bearing section, scan non-primary sections at
    # paragraph level and append a third marker block so BERT/LLM can see
    # dataset mentions under non-standard section titles. Gated by config flag.
    if WF4_DATASET_SECTION_FALLBACK:
        fallback = apply_dataset_section_fallback(
            preprocess_result.text,
            primary_selected_titles=experiment_union.selected_sections,
            primary_union_text=experiment_union.text,
            primary_fallback_to_full_text=experiment_union.fallback_to_full_text,
            section_matcher=_section_matches_wf4,
        )
    else:
        fallback = DatasetFallbackResult.empty(reason="disabled")
    merged_text = merge_union_text(
        experiment_union.text,
        absintro_union.text,
        fallback.text if fallback.triggered else None,
    )
    union_elapsed = time.perf_counter() - t

    # nobert ablation: when WF4_SKIP_BERT_FILTER is set, the scheduler rebuilds
    # the LLM input from the marker-structured merged text (split-by-marker +
    # cross-block dedup) instead of running SciBERT. Stash the merged text on
    # clean_stats so the nobert builder can recover block structure that
    # split_sentences below would otherwise flatten. Baseline path (env unset)
    # never reads this key, so behavior is unchanged.
    skip_bert_filter = bool(os.environ.get("WF4_SKIP_BERT_FILTER"))

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
        english_sentences, clean_stats = wf4_clean_sentences_for_llm(english_sentences)
        clean_elapsed = time.perf_counter() - t
        if not english_sentences:
            raise RuntimeError("No sentences after sentence_clean")

    # Stash dataset-fallback stats for the llm stage to write into provenance/
    # metadata (LlmPrepared.clean_stats is the prep->llm metadata channel).
    clean_stats["dataset_fallback"] = {
        "triggered": fallback.triggered,
        "trigger_reason": fallback.trigger_reason,
        "sections": fallback.source_section_titles,
        "paragraphs": fallback.source_paragraph_count,
        "char_count": fallback.char_count,
        "skipped_reason": fallback.skipped_reason,
    }
    # Unconditional stash of the marker-structured merged_text so structured
    # input axes can recover block structure that split_sentences below flattens.
    # Inert key on the baseline path (never read); bert-struct-60 reads it to
    # split-by-marker + cross-block dedup before sending sentences to BERT.
    clean_stats["merged_text"] = merged_text
    if skip_bert_filter:
        clean_stats["nobert_merged_text"] = merged_text

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


# --------------------------------------------------------------------------- #
# Stage-B: LLM 8-field (7 + datasets)                                        #
# --------------------------------------------------------------------------- #


def run_llm_stage_wf4(
    prepared: LlmPrepared,
    bert_result: BertStageResult,
    llm_client: SingleLLMClient | None = None,
    *,
    run_id: str = "",
    bert_mode: str = "serial",
    llm_model_tag: str | None = None,
    ollama_format: str | None = None,
    num_predict_override: int | None = None,
    prompt_adapter: str | None = None,
    num_ctx_override: int | None = None,
    input_path: str | None = None,
    capture_dir: Path | None = None,
    capture_tag: str = "",
    full_text: str = "",
) -> FieldResult:
    """Stage-B (wf4) — prompt (8-field) + LLM + parse + 7 fields + datasets.

    Output FieldResult is shape-compatible with wf8's ``run_qwen_stage`` plus an
    8th ``datasets`` key in ``value``. ``bert_mode`` is recorded in provenance
    ("batch" for wf4's /filter/batch path) and does not affect the LLM call.

    Per-model calling-convention overrides (wf4 model-sweep fix): ``ollama_format``
    (e.g. "json"; legacy Ollama knob, now ignored by the BigModel client),
    ``num_predict_override`` (int), ``prompt_adapter`` ("v3").
    All default None => production behavior (V0 prompt, no format, num_predict=2048).

    Optional I/O capture (inspection only): when ``capture_dir`` is set, the full
    prompt and full raw LLM output are written to ``{capture_dir}/{capture_tag}__*
    .txt``. Default None => nothing written; production path unaffected.
    """
    client = llm_client or SingleLLMClient()

    t = time.perf_counter()
    prompt = build_wf4_prompt_for_adapter(
        bert_result.llm_input, prepared.paper_title, adapter=prompt_adapter
    )
    prompt_chars = len(prompt)
    num_predict = num_predict_override if num_predict_override is not None else 2048
    llm_result = client.generate(
        prompt,
        model=llm_model_tag,
        temperature=0.05,
        num_predict=num_predict,
        format=ollama_format,
        num_ctx=num_ctx_override,
    )
    llm_elapsed = time.perf_counter() - t

    resolved_ollama = llm_model_tag or client._model
    if resolved_ollama is None:
        resolved_ollama = client.resolve_model()
    eval_count = llm_result.get("eval_count")
    prompt_eval_count = llm_result.get("prompt_eval_count")
    elapsed_for_tps = llm_result.get("elapsed_sec") or llm_elapsed
    tokens_per_sec = None
    if eval_count is not None and elapsed_for_tps and float(elapsed_for_tps) > 0:
        tokens_per_sec = round(float(eval_count) / float(elapsed_for_tps), 4)

    raw = llm_result["raw_output"]

    # Optional I/O capture for manual inspection (off by default; production unaffected).
    if capture_dir is not None:
        capture_dir.mkdir(parents=True, exist_ok=True)
        tag = capture_tag or "case"
        (capture_dir / f"{tag}__prompt.txt").write_text(prompt, encoding="utf-8")
        (capture_dir / f"{tag}__raw_output.txt").write_text(raw, encoding="utf-8")

    repaired = repair_json_text(raw)
    parsed, parse_error = parse_json_object(raw)

    # Multi-exp coerce (+ old flat wrap-compat). Never invent experiments.
    value = coerce_wf4_llm_parsed(
        parsed if parsed else None, full_text=full_text or None
    )
    methods_truncated = bool(value.pop("methods_truncated_by_paper_budget", False))
    experiments = value.get("experiments") or []

    # --- dataset confidence scoring per experiment (post-hoc, no LLM) ---
    if full_text:
        for exp in experiments:
            ds = exp.get("datasets") or []
            if ds:
                exp["datasets"] = score_datasets_confidence(ds, full_text, sort=True)

    # --- dataset leak detection across all experiments (monitoring-only) ---
    all_subjects: list[str] = []
    all_datasets: list[dict[str, Any]] = []
    for exp in experiments:
        all_subjects.extend(exp.get("experiment_subject") or [])
        all_datasets.extend(exp.get("datasets") or [])
    ds_names = {d["name"].strip().lower() for d in all_datasets if d.get("name")}
    ds_aliases = {
        a.strip().lower() for d in all_datasets for a in (d.get("aliases") or [])
    }
    leak = count_dataset_leaks(all_subjects, ds_names, ds_aliases)
    datasets_count = len(all_datasets)

    llm_ok = not parse_error
    llm_status = "ok" if llm_ok else "error"
    llm_error = None
    if parse_error:
        llm_error = f"parse_error: {parse_error}"
    # EXT-02: experiments==[] after successful parse is a valid ok outcome
    # (survey/theory papers); do not set empty_experiments_after_normalize.

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
    # Dataset-fallback stats stashed by prepare_llm_inputs_wf4 (prep -> llm
    # metadata channel via LlmPrepared.clean_stats).
    fb = (prepared.clean_stats or {}).get("dataset_fallback") or {}
    fb_triggered = bool(fb.get("triggered"))
    fb_suffix = "+dataset_fallback" if fb_triggered else ""

    # nobert structured-input stats (only present on the skip-bert nobert path;
    # stashed by run_nobert_stage_wf4 into bert_result.sentence_selection).
    sel = bert_result.sentence_selection or {}
    nobert_blocks = sel.get("nobert_blocks")
    dedup_removed_count = sel.get("dedup_removed_count")
    dedup_removed_by_block = sel.get("dedup_removed_by_block")
    pre_dedup = sel.get("input_sentence_count_pre_dedup")
    post_dedup = sel.get("input_sentence_count_post_dedup")
    # bert-struct-60 stats (only present on the --bert-struct path; stashed by
    # run_bert_struct_stage_from_batch_entry_wf4 into bert_result.sentence_selection).
    bert_struct_blocks = sel.get("bert_struct_blocks")
    selected_by_block = sel.get("selected_by_block")
    bert_kept_count = sel.get("bert_kept_count")
    bert_struct_prompt_chars = sel.get("bert_struct_prompt_chars")
    is_bert_struct = input_path == "bert_struct"
    is_bert_flat = input_path == "bert_flat"
    # Per-path cap override surfaces from sentence_selection when present
    # (bert-struct-60 / bert-flat-60 = 60); else WF4_MAX_QWEN_SENTENCES (60).
    provenance_max_qwen = (
        sel.get("max_llm_sentences") if sel.get("max_llm_sentences") is not None
        else WF4_MAX_QWEN_SENTENCES
    )

    provenance = {
        "union_mode": f"wf4_dataset_aware_union{fb_suffix}",
        "bert_mode": bert_mode,
        "input_path": input_path,
        "llm_mode": WF8_LLM_MODE_LABEL,
        "output_schema": "v8+multi_exp_datasets",
        "llm_mode": "wf4_multi_exp_datasets",
        "bert_threshold": WF1_BERT_THRESHOLD,
        "max_llm_sentences": provenance_max_qwen,
        "metrics_cap": WF8_METRICS_CAP,
        "max_experiments": WF4_MAX_EXPERIMENTS,
        "sentence_clean": WF8_SENTENCE_CLEAN,
        "experiment_axis": f"wf4_dataset_aware_union+wash{fb_suffix}",
        "wf4_stages": True,
        "workflow_id": WF4_WORKFLOW_ID,
        "datasets_cap": WF4_DATASETS_CAP,
        "llm_model_tag": resolved_ollama,
        "ollama_format": ollama_format,
        "prompt_adapter": prompt_adapter,
        "num_predict": num_predict,
        "num_ctx": num_ctx_override,
        "dataset_fallback_triggered": fb_triggered,
        "dataset_fallback_reason": fb.get("trigger_reason"),
        "dataset_fallback_sections": fb.get("sections") or [],
        "dataset_fallback_paragraphs": fb.get("paragraphs") or 0,
        "dataset_fallback_char_count": fb.get("char_count") or 0,
        "nobert_struct": input_path == "nobert_struct",
        "nobert_blocks": nobert_blocks,
        "bert_struct": is_bert_struct,
        "bert_flat": is_bert_flat,
        "bert_struct_blocks": bert_struct_blocks,
        "selected_by_block": selected_by_block,
        "bert_kept_count": bert_kept_count,
        "dedup_removed_count": dedup_removed_count,
        "dedup_removed_by_block": dedup_removed_by_block,
        "input_sentence_count_pre_dedup": pre_dedup,
        "input_sentence_count_post_dedup": post_dedup,
    }

    fields = [
        "research_problem",
        "research_problem_description",
        "research_problem_aliases",
        "experiments",
    ]

    return FieldResult(
        extractor_id=WF4_LLM_EXTRACTOR_ID,
        version=WF4_WORKFLOW_VERSION,
        status=llm_status,
        value=value,
        fields=fields,
        error=llm_error,
        metadata={
            "paper_title": prepared.paper_title,
            "wf4_stages": True,
            "time_breakdown_sec": time_breakdown,
            "provenance": provenance,
            "parse_error": parse_error,
            "prompt_chars": prompt_chars,
            "llm_model_tag": resolved_ollama,
            "ollama_format": ollama_format,
            "prompt_adapter": prompt_adapter,
            "num_predict": num_predict,
            "num_ctx": num_ctx_override,
            "input_path": input_path,
            "llm_eval_count": eval_count,
            "llm_prompt_eval_count": prompt_eval_count,
            "tokens_per_sec": tokens_per_sec,
            "raw_output_preview": raw[:200],
            "repaired_json": repaired,
            "run_id": run_id,
            "datasets_count": datasets_count,
            "experiment_count": len(experiments),
            "methods_truncated_by_paper_budget": methods_truncated,
            "dataset_leak_count": leak["leak_count"],
            "dataset_leaked_items": leak["leaked_items"],
            "dataset_fallback_triggered": fb_triggered,
            "dataset_fallback_char_count": fb.get("char_count") or 0,
            "nobert_struct": input_path == "nobert_struct",
            "nobert_blocks": nobert_blocks,
            "nobert_prompt_chars": bert_result.timings.get("nobert_prompt_chars"),
            "bert_struct": is_bert_struct,
            "bert_flat": is_bert_flat,
            "bert_struct_blocks": bert_struct_blocks,
            "selected_by_block": selected_by_block,
            "bert_kept_count": bert_kept_count,
            "bert_struct_prompt_chars": bert_struct_prompt_chars,
            "dedup_removed_count": dedup_removed_count,
            "dedup_removed_by_block": dedup_removed_by_block,
            "input_sentence_count_pre_dedup": pre_dedup,
            "input_sentence_count_post_dedup": post_dedup,
        },
    )


# --------------------------------------------------------------------------- #
# Batch BERT (/filter/batch) — wf4 variant (max_sentences=40)                #
# --------------------------------------------------------------------------- #


def run_bert_stage_from_batch_entry_wf4(
    prepared: LlmPrepared,
    batch_entry: dict[str, Any],
    *,
    max_sentences: int = WF4_MAX_QWEN_SENTENCES,
    chunk_index: int = 0,
) -> BertStageResult:
    """Build a BertStageResult from one /filter/batch per-paper entry (wf4).

    Identical to wf8 ``run_bert_stage_from_batch_entry`` EXCEPT it passes
    ``max_sentences`` (default ``WF4_MAX_QWEN_SENTENCES``=60) into
    ``select_llm_sentences`` (wf8 defaults to WF1_MAX_LLM_SENTENCES=35). The
    ``bert-flat-N`` axis can override the cap while keeping the flat V0 prompt
    (no structure, no dedup).
    """
    kept_sentences = list(batch_entry.get("kept", []))
    confidences = batch_entry.get("confidences")
    llm_input, sentence_selection = select_llm_sentences(
        kept_sentences, confidences, max_sentences=max_sentences
    )
    sentence_selection["max_llm_sentences"] = max_sentences
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


def run_nobert_stage_wf4(
    prepared: LlmPrepared,
    *,
    max_prompt_chars: int,
) -> BertStageResult:
    """Build a BertStageResult for the skip-SciBERT nobert structured path.

    Replaces ``run_bert_stage_from_batch_entry_wf4`` when ``--skip-bert-filter``
    is active: instead of running ``/filter/batch`` + ``select_llm_sentences``,
    the LLM input is the full washed + cross-block-deduped sentence list with
    block markers preserved (see ``wf4_nobert_struct.build_nobert_structured``).

    The caller inspects ``bert_raw["overflow"]`` to decide whether the paper's
    structured prompt fits the nobert context budget; overflow papers are routed
    to the BERT fallback path (``run_bert_batch_for_papers_wf4``) instead.
    """
    built = build_nobert_structured(prepared, max_prompt_chars=max_prompt_chars)
    structured_lines = built["structured_lines"]
    return BertStageResult(
        llm_input=structured_lines,
        sentence_selection=built["stats"],
        bert_raw={
            "nobert_struct": True,
            "prompt_chars": built["prompt_chars"],
            "overflow": built["overflow"],
        },
        timings={
            "bert_filter": 0.0,
            "nobert_prompt_chars": built["prompt_chars"],
        },
    )


def run_bert_struct_stage_from_batch_entry_wf4(
    prepared: LlmPrepared,
    batch_entry: dict[str, Any],
    *,
    max_sentences: int = 60,
    chunk_index: int = 0,
) -> BertStageResult:
    """Build a BertStageResult for the bert-struct-60 path (keep SciBERT + structure).

    Unlike ``run_bert_stage_from_batch_entry_wf4`` (flat 40 + V0), this re-attaches
    block membership to the BERT-kept sentences via ``batch_entry["indices"]``
    (see ``wf4_bert_struct.build_bert_structured``), selects up to
    ``max_sentences`` (60) preserving block structure, and emits a marker +
    bare-sentence ``llm_input`` for the ``structured`` prompt adapter. SciBERT
    filtering has already run (the caller sent ``flat_sentences`` to
    ``/filter/batch``); this only assembles the structured LLM input.
    """
    built = build_bert_structured(
        prepared, batch_entry, max_sentences=max_sentences
    )
    stats = built["stats"]
    return BertStageResult(
        llm_input=built["structured_lines"],
        sentence_selection=stats,
        bert_raw={
            "bert_struct": True,
            "kept_count": batch_entry.get("kept_count", stats.get("bert_kept_count")),
            "total": stats.get("bert_total"),
            "prompt_chars": built["prompt_chars"],
        },
        timings={
            "bert_filter": 0.0,  # amortized; see batch_monitor
            "bert_batch_chunk": chunk_index,
            "bert_struct_prompt_chars": built["prompt_chars"],
        },
    )


def run_bert_struct_batch_for_papers_wf4(
    prepared_map: dict[str, LlmPrepared],
    *,
    max_sentences: int = 60,
    chunk_max_papers: int | None = None,
    batch_size: int = 32,
    bert_server_url: str | None = None,
    bert_timeout: int | None = None,
    bert_retries: int | None = None,
) -> tuple[dict[str, BertStageResult], dict[str, Any]]:
    """Run /filter/batch across all papers with bert-struct-60 structured input.

    Mirrors ``run_bert_batch_for_papers_wf4`` chunk loop, but per paper first
    builds block-structured + cross-block-deduped ``flat_sentences`` (+ parallel
    ``block_ids``) from PREP's stashed ``merged_text`` (so the ``/filter/batch``
    ``indices`` can map kept sentences back to blocks). Sentences sent to BERT
    are the per-block-washed, deduped set (markers stripped — cleaner than the
    baseline whole-text flatten, which glues markers into adjacent sentences).

    The ``batch_monitor`` carries ``mode="bert_struct"`` + structured-input
    aggregates (avg dedup removed, avg selected sentences, total prompt chars).
    """
    raise RuntimeError(
        "SciBERT /filter/batch path removed — this skill uses the GLM "
        "sentence filter only (public BigModel service, no internal services)"
    )

    paper_ids = list(prepared_map.keys())
    per_chunk = _decide_chunking(prepared_map, chunk_max_papers or None)
    chunks: list[dict[str, Any]] = []
    results: dict[str, BertStageResult] = {}

    # Pre-build per-paper struct blocks (split+wash+dedup) -> flat_sentences + block_ids.
    struct_blocks = {pid: build_bert_struct_blocks(prepared_map[pid]) for pid in paper_ids}

    total_inference_ms = 0.0
    total_client_sec = 0.0
    total_sentences = 0
    total_kept = 0
    total_prompt_chars = 0
    selected_counts: list[int] = []
    dedup_counts: list[int] = []

    for chunk_index, start in enumerate(range(0, len(paper_ids), per_chunk)):
        chunk_ids = paper_ids[start : start + per_chunk]
        chunk_papers = [
            {"paper_id": pid, "sentences": struct_blocks[pid]["flat_sentences"]}
            for pid in chunk_ids
        ]
        chunk_started = _utc_now()
        batch_data = filter_papers_batch(
            chunk_papers, batch_size=batch_size, url=bert_server_url,
            **_bert_retry_kwargs(bert_timeout, bert_retries),
        )
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
            results[pid] = run_bert_struct_stage_from_batch_entry_wf4(
                prepared_map[pid], entry,
                max_sentences=max_sentences, chunk_index=chunk_index,
            )
            results[pid].timings["bert_amortized_sec"] = round(client_sec / chunk_n, 4)
            sel = results[pid].sentence_selection or {}
            selected_counts.append(int(sel.get("selected", 0)))
            if sel.get("dedup_removed_count") is not None:
                dedup_counts.append(int(sel["dedup_removed_count"]))
            total_prompt_chars += int(sel.get("bert_struct_prompt_chars", 0))

    batch_monitor = {
        "mode": "bert_struct",
        "chunks": chunks,
        "chunk_count": len(chunks),
        "total_inference_ms": round(total_inference_ms, 2),
        "total_client_sec": round(total_client_sec, 4),
        "total_sentences": total_sentences,
        "total_kept": total_kept,
        "batch_size": batch_size,
        "max_llm_sentences": max_sentences,
        "bert_struct_count": len(paper_ids),
        "avg_dedup_removed_count": (
            round(sum(dedup_counts) / len(dedup_counts), 4) if dedup_counts else 0
        ),
        "avg_selected_sentences": (
            round(sum(selected_counts) / len(selected_counts), 4) if selected_counts else 0
        ),
        "total_prompt_chars": total_prompt_chars,
    }
    return results, batch_monitor


def run_bert_batch_for_papers_wf4(
    prepared_map: dict[str, LlmPrepared],
    *,
    max_sentences: int = WF4_MAX_QWEN_SENTENCES,
    chunk_max_papers: int | None = None,
    batch_size: int = 32,
    bert_server_url: str | None = None,
    bert_timeout: int | None = None,
    bert_retries: int | None = None,
) -> tuple[dict[str, BertStageResult], dict[str, Any]]:
    """Run /filter/batch across all papers (wf4, max_sentences configurable).

    Copy of wf8 ``run_bert_batch_for_papers`` except it calls
    ``run_bert_stage_from_batch_entry_wf4``. ``max_sentences`` defaults to
    ``WF4_MAX_QWEN_SENTENCES`` (60); ``bert-flat-N`` may pass another cap.
    Chunking, ``filter_papers_batch``, and the batch_monitor shape are identical.
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
        batch_data = filter_papers_batch(
            chunk_papers, batch_size=batch_size, url=bert_server_url,
            **_bert_retry_kwargs(bert_timeout, bert_retries),
        )
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
            results[pid] = run_bert_stage_from_batch_entry_wf4(
                prepared_map[pid], entry,
                max_sentences=max_sentences, chunk_index=chunk_index,
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
        "max_llm_sentences": max_sentences,
    }
    return results, batch_monitor
