"""wf8 core: single-LLM 7-field pipeline (wf7 v0.4 + LLM-extracted metrics).

Inherits wf7 v0.4 wholesale (BERT, select_llm_sentences max=35, the v0.4
6-field prompt rules verbatim) and extends the SAME single LLM request with a
7th field ``metrics: list[str]`` (evaluation-metric names, aligned with GLM
``data/json/*.json``). No second LLM call, no rule engine — metrics come from
the LLM in the same JSON response as the other 6 fields.

dev10 / dev20 are a single variable: the metrics count cap (0-10 vs 0-20) in
the prompt rule line + the post-processing cap. Everything else is identical.

``build_wf7_v04_prompt`` is FROZEN as the control; wf8 keeps its own prompt
builders here (copied from v0.4 + 2 lines) so wf7 is untouched.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from pipeline.benchmark.config import WF1_BERT_THRESHOLD, WF1_MAX_LLM_SENTENCES
from pipeline.benchmark.parse_helpers import normalize_string_list
from pipeline.benchmark.stages.bert_client import SerialBertClient, filter_english_only, split_sentences
from pipeline.benchmark.stages.llm_client import SingleLLMClient
from pipeline.benchmark.stages.sentence_clean import clean_sentences_for_llm
from pipeline.benchmark.stages.union_merge import merge_union_text
from pipeline.benchmark.workflows.base import WorkflowInput, WorkflowResult, utc_now
from pipeline.benchmark.workflows.wf1_merged import extract_paper_title, select_llm_sentences
from pipeline.json_repair import parse_json_object, repair_json_text
from preprocess.pipeline import run_preprocess_steps
from preprocess.section_union import union_experiment_sections
from preprocess.section_union_abs_intro import union_abs_intro_sections

PromptBuilder = Callable[[list[str], str], str]


def build_wf8_dev10_prompt(sentences: list[str], paper_title: str) -> str:
    """wf8 dev10 prompt — v0.4 6-field prompt + metrics (cap 0-10).

    Copied verbatim from build_wf7_v04_prompt, plus:
      - JSON schema: one extra line "metrics": [...]
      - Rules: one extra metrics line (cap 0-10)
    The 6 existing field rules are byte-identical to v0.4.
    """
    numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sentences))
    title_line = paper_title or "(unknown)"
    return f"""/no_think
Extract experiment and research information from a scientific paper.

Paper title:
{title_line}

Return ONLY valid JSON:
{{
  "experiment_name": "primary experiment or method name",
  "key_results": ["key finding with metrics"],
  "method": "brief method description",
  "research_problem": "problem addressed",
  "research_goal": "main contribution or goal",
  "experiment_subject": ["what is studied or evaluated"],
  "metrics": ["evaluation metric name"]
}}

Rules:
- experiment_name: prefer paper title if it names the main method; method-level name, not dataset alone.
- key_results: 0-5 items; one sentence each; include numbers only if in sentences below; do not fabricate.
- method / research_problem / research_goal: 1-2 sentences each; empty string if unknown.
- experiment_subject: 0-3 short English phrases naming the TASK or problem domain studied (e.g. "point cloud completion", "face anti-spoofing", "semi-supervised semantic segmentation"); prefer task phrases that appear in the paper, not generic labels like "deep learning"; not model/baseline names, not dataset names; [] if unknown.
- metrics: 0-10 short English metric names or abbreviations used to evaluate experiments (e.g. "mIoU", "F1-score", "Chamfer Distance (CD)", "AUC"); names only, not numeric results; prefer metrics explicitly stated in the sentences below; not dataset names; [] if unknown.
- No markdown fences, no explanation.

Sentences:
{numbered}
"""


def build_wf8_dev20_prompt(sentences: list[str], paper_title: str) -> str:
    """wf8 dev20 prompt — identical to dev10 except metrics cap 0-10 -> 0-20."""
    numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sentences))
    title_line = paper_title or "(unknown)"
    return f"""/no_think
Extract experiment and research information from a scientific paper.

Paper title:
{title_line}

Return ONLY valid JSON:
{{
  "experiment_name": "primary experiment or method name",
  "key_results": ["key finding with metrics"],
  "method": "brief method description",
  "research_problem": "problem addressed",
  "research_goal": "main contribution or goal",
  "experiment_subject": ["what is studied or evaluated"],
  "metrics": ["evaluation metric name"]
}}

Rules:
- experiment_name: prefer paper title if it names the main method; method-level name, not dataset alone.
- key_results: 0-5 items; one sentence each; include numbers only if in sentences below; do not fabricate.
- method / research_problem / research_goal: 1-2 sentences each; empty string if unknown.
- experiment_subject: 0-3 short English phrases naming the TASK or problem domain studied (e.g. "point cloud completion", "face anti-spoofing", "semi-supervised semantic segmentation"); prefer task phrases that appear in the paper, not generic labels like "deep learning"; not model/baseline names, not dataset names; [] if unknown.
- metrics: 0-20 short English metric names or abbreviations used to evaluate experiments (e.g. "mIoU", "F1-score", "Chamfer Distance (CD)", "AUC"); names only, not numeric results; prefer metrics explicitly stated in the sentences below; not dataset names; [] if unknown.
- No markdown fences, no explanation.

Sentences:
{numbered}
"""


def build_wf8_dev10_v2_prompt(sentences: list[str], paper_title: str) -> str:
    """wf8 dev10 v2 prompt — three bundled simplifications vs v1 (cap 0-10).

    vs v1 build_wf8_dev10_prompt:
      1. metrics rule: dropped the fixed examples "(e.g. ...)" (anti cross-paper pollution).
      2. method/research_problem/research_goal rules merged into one line.
      3. JSON schema placeholders reduced to empty values (no descriptive text).
    experiment_name / key_results / experiment_subject rule lines and the v0.4
    subject line are byte-identical to v1. dev10v2 vs dev20v2: only 0-10 vs 0-20.
    """
    numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sentences))
    title_line = paper_title or "(unknown)"
    return f"""/no_think
Extract experiment and research information from a scientific paper.

Paper title:
{title_line}

Return ONLY valid JSON:
{{
  "experiment_name": "",
  "key_results": [],
  "method": "",
  "research_problem": "",
  "research_goal": "",
  "experiment_subject": [],
  "metrics": []
}}

Rules:
- experiment_name: prefer paper title if it names the main method; method-level name, not dataset alone.
- key_results: 0-5 items; one sentence each; include numbers only if in sentences below; do not fabricate.
- method, research_problem, research_goal: 1-2 sentences each; "" if unknown.
- experiment_subject: 0-3 short English phrases naming the TASK or problem domain studied (e.g. "point cloud completion", "face anti-spoofing", "semi-supervised semantic segmentation"); prefer task phrases that appear in the paper, not generic labels like "deep learning"; not model/baseline names, not dataset names; [] if unknown.
- metrics: 0-10 metric names stated in the sentences below; names only, not numeric results; not dataset names; [] if unknown.
- No markdown fences, no explanation.

Sentences:
{numbered}
"""


def build_wf8_dev20_v2_prompt(sentences: list[str], paper_title: str) -> str:
    """wf8 dev20 v2 prompt — identical to dev10 v2 except metrics cap 0-10 -> 0-20."""
    numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sentences))
    title_line = paper_title or "(unknown)"
    return f"""/no_think
Extract experiment and research information from a scientific paper.

Paper title:
{title_line}

Return ONLY valid JSON:
{{
  "experiment_name": "",
  "key_results": [],
  "method": "",
  "research_problem": "",
  "research_goal": "",
  "experiment_subject": [],
  "metrics": []
}}

Rules:
- experiment_name: prefer paper title if it names the main method; method-level name, not dataset alone.
- key_results: 0-5 items; one sentence each; include numbers only if in sentences below; do not fabricate.
- method, research_problem, research_goal: 1-2 sentences each; "" if unknown.
- experiment_subject: 0-3 short English phrases naming the TASK or problem domain studied (e.g. "point cloud completion", "face anti-spoofing", "semi-supervised semantic segmentation"); prefer task phrases that appear in the paper, not generic labels like "deep learning"; not model/baseline names, not dataset names; [] if unknown.
- metrics: 0-20 metric names stated in the sentences below; names only, not numeric results; not dataset names; [] if unknown.
- No markdown fences, no explanation.

Sentences:
{numbered}
"""


def run_wf8_pipeline(
    input_data: WorkflowInput,
    *,
    run_id: str,
    workflow_id: str,
    workflow_version: str,
    prompt_builder: PromptBuilder,
    llm_mode_label: str,
    metrics_cap: int,
    sentence_clean: bool = False,
) -> WorkflowResult:
    """Execute the wf8 single-LLM 7-field pipeline on a single paper.

    Identical to wf7 v0.4's pipeline (one BERT, one LLM); only the prompt
    carries a 7th field and the prediction records ``metrics`` + ``metrics_cap``.
    No second LLM call, no rule engine, no metric_extract timing line.
    """
    bert_client = SerialBertClient()
    llm_client = SingleLLMClient()

    monitor: dict[str, Any] = {
        "paper_id": input_data.paper_id,
        "workflow": workflow_id,
        "workflow_version": workflow_version,
        "run_id": run_id,
        "started_at": utc_now(),
        "events": [],
    }

    overall_start = time.perf_counter()

    try:
        md_text = input_data.md_path.read_text(encoding="utf-8")
        paper_title = extract_paper_title(md_text)
        monitor["events"].append({
            "timestamp": utc_now(),
            "stage": "paper_meta",
            "event": "title_extracted",
            "paper_title": paper_title,
        })

        print(f"\n[{workflow_id}] Preprocessing...")
        preprocess_start = time.perf_counter()
        preprocess_result = run_preprocess_steps(
            md_text,
            steps=["strip_references", "compact_markdown"],
        )
        preprocess_elapsed = time.perf_counter() - preprocess_start
        monitor["events"].append({
            "timestamp": utc_now(),
            "stage": "preprocess",
            "event": "completed",
            "elapsed_sec": round(preprocess_elapsed, 4),
            "text_chars": len(preprocess_result.text),
        })

        print(f"\n[{workflow_id}] Union merge...")
        union_start = time.perf_counter()
        experiment_union = union_experiment_sections(preprocess_result.text)
        absintro_union = union_abs_intro_sections(preprocess_result.text)
        merged_text = merge_union_text(experiment_union.text, absintro_union.text)
        union_elapsed = time.perf_counter() - union_start
        monitor["events"].append({
            "timestamp": utc_now(),
            "stage": "union_merge",
            "event": "completed",
            "elapsed_sec": round(union_elapsed, 4),
            "experiment_chars": len(experiment_union.text),
            "absintro_chars": len(absintro_union.text),
            "merged_chars": len(merged_text),
        })

        print(f"\n[{workflow_id}] Sentence processing...")
        split_start = time.perf_counter()
        all_sentences = split_sentences(merged_text)
        english_sentences = filter_english_only(all_sentences)
        split_elapsed = time.perf_counter() - split_start
        monitor["events"].append({
            "timestamp": utc_now(),
            "stage": "sentence_split",
            "event": "completed",
            "elapsed_sec": round(split_elapsed, 4),
            "all_sentences": len(all_sentences),
            "english_sentences": len(english_sentences),
        })

        if not english_sentences:
            raise RuntimeError("No English sentences after preprocessing")

        # input-sentence-clean axis (single insertion point, before BERT).
        # Conservative junk drop; default False = behavior unchanged.
        clean_elapsed = 0.0
        if sentence_clean:
            print(f"\n[{workflow_id}] Sentence cleaning (input-sentence-clean)...")
            clean_start = time.perf_counter()
            english_sentences, clean_stats = clean_sentences_for_llm(english_sentences)
            clean_elapsed = time.perf_counter() - clean_start
            monitor["events"].append({
                "timestamp": utc_now(),
                "stage": "sentence_clean",
                "event": "completed",
                "elapsed_sec": round(clean_elapsed, 4),
                **clean_stats,
            })
            if not english_sentences:
                raise RuntimeError("No sentences after sentence_clean")

        print(f"\n[{workflow_id}] BERT filtering (threshold={WF1_BERT_THRESHOLD})...")
        bert_start = time.perf_counter()
        bert_result = bert_client.filter_sentences_serial(
            english_sentences,
            threshold=WF1_BERT_THRESHOLD,
        )
        bert_elapsed = time.perf_counter() - bert_start
        monitor["events"].append({
            "timestamp": utc_now(),
            "stage": "bert_filter",
            "event": "completed",
            "elapsed_sec": round(bert_elapsed, 4),
            "kept_count": bert_result["kept_count"],
            "total": bert_result["total"],
        })

        if bert_result["kept_count"] == 0:
            raise RuntimeError("No sentences passed BERT filter")

        print(f"\n[{workflow_id}] Selecting sentences for LLM...")
        llm_input, sentence_selection = select_llm_sentences(
            bert_result["kept_sentences"],
            bert_result.get("confidences"),
        )
        monitor["events"].append({
            "timestamp": utc_now(),
            "stage": "sentence_selection",
            "event": "completed",
            **sentence_selection,
        })
        monitor["llm_input_sentences"] = llm_input
        print(
            f"LLM input: {sentence_selection['selected']}/{sentence_selection['total_kept']} sentences "
            f"({sentence_selection['metric_rich_selected']} metric-rich)"
        )

        print(f"\n[{workflow_id}] LLM generation (7 fields, single call)...")
        llm_start = time.perf_counter()
        prompt = prompt_builder(llm_input, paper_title)
        prompt_chars = len(prompt)
        monitor["prompt_chars"] = prompt_chars
        llm_result = llm_client.generate(
            prompt,
            temperature=0.05,
            num_predict=2048,
        )
        llm_elapsed = time.perf_counter() - llm_start

        repaired = repair_json_text(llm_result["raw_output"])
        parsed, parse_error = parse_json_object(llm_result["raw_output"])

        experiment_subject = normalize_string_list(
            parsed.get("experiment_subject") if parsed else None
        )
        metrics = normalize_string_list(
            parsed.get("metrics") if parsed else None, max_items=metrics_cap
        )

        monitor["events"].append({
            "timestamp": utc_now(),
            "stage": "llm_generate",
            "event": "completed",
            "elapsed_sec": round(llm_elapsed, 4),
            "prompt_chars": prompt_chars,
            "eval_count": llm_result.get("eval_count"),
            "prompt_eval_count": llm_result.get("prompt_eval_count"),
            "raw_output_preview": llm_result["raw_output"][:200],
            "repaired_json": repaired,
            "parse_error": parse_error,
            "experiment_subject_count": len(experiment_subject),
            "metrics_count": len(metrics),
        })

        total_elapsed = time.perf_counter() - overall_start

        prediction = {
            "paper_id": input_data.paper_id,
            "paper_title": paper_title,
            "workflow_id": workflow_id,
            "workflow_version": workflow_version,
            "run_id": run_id,
            "experiment_name": parsed.get("experiment_name", "") if parsed else "",
            "key_results": parsed.get("key_results", []) if parsed else [],
            "method": parsed.get("method", "") if parsed else "",
            "research_problem": parsed.get("research_problem", "") if parsed else "",
            "research_goal": parsed.get("research_goal", "") if parsed else "",
            "experiment_subject": experiment_subject,
            "metrics": metrics,
            "time_breakdown_sec": {
                "preprocess": round(preprocess_elapsed, 4),
                "union_merge": round(union_elapsed, 4),
                "sentence_clean": round(clean_elapsed, 4),
                "bert_filter": round(bert_elapsed, 4),
                "llm_generate": round(llm_elapsed, 4),
                "total": round(total_elapsed, 4),
            },
            "provenance": {
                "union_mode": "merged",
                "bert_mode": "serial",
                "llm_mode": llm_mode_label,
                "output_schema": "v7",
                "bert_threshold": WF1_BERT_THRESHOLD,
                "max_llm_sentences": WF1_MAX_LLM_SENTENCES,
                "metrics_cap": metrics_cap,
                "sentence_clean": sentence_clean,
                "experiment_axis": "input-sentence-clean" if sentence_clean else None,
            },
            "parse_error": parse_error,
        }

        monitor["finished_at"] = utc_now()
        monitor["total_elapsed_sec"] = round(total_elapsed, 4)

        print(f"\n[{workflow_id}] Summary:")
        print(f"  experiment_name: {prediction['experiment_name'][:80] or '(empty)'}")
        print(f"  key_results: {len(prediction['key_results'])} items")
        print(f"  method: {prediction['method'][:80] or '(empty)'}")
        print(f"  research_problem: {prediction['research_problem'][:80] or '(empty)'}")
        print(f"  research_goal: {prediction['research_goal'][:80] or '(empty)'}")
        print(f"  experiment_subject: {prediction['experiment_subject']}")
        print(f"  metrics: {prediction['metrics']}")
        print(f"  total time: {total_elapsed:.2f}s (llm={llm_elapsed:.2f}s eval={llm_result.get('eval_count')})")

        return WorkflowResult(
            workflow_id=workflow_id,
            workflow_version=workflow_version,
            run_id=run_id,
            paper_id=input_data.paper_id,
            prediction=prediction,
            monitor=monitor,
            paper_title=paper_title,
        )

    except Exception as e:
        total_elapsed = time.perf_counter() - overall_start
        monitor["finished_at"] = utc_now()
        monitor["total_elapsed_sec"] = round(total_elapsed, 4)
        monitor["error"] = str(e)
        monitor["events"].append({
            "timestamp": utc_now(),
            "stage": "error",
            "event": str(e),
        })

        return WorkflowResult(
            workflow_id=workflow_id,
            workflow_version=workflow_version,
            run_id=run_id,
            paper_id=input_data.paper_id,
            prediction={},
            monitor=monitor,
            error=str(e),
        )
