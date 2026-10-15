"""Workflow 1: Merged Union with Single LLM (wf1-merged).

Merged union → BERT → LLM single extraction of 5 fields.
"""

from __future__ import annotations

import re
import time
from typing import Any

from pipeline.benchmark.config import (
    WF1_BERT_THRESHOLD,
    WF1_MAX_LLM_SENTENCES,
)
from pipeline.benchmark.stages.bert_client import SerialBertClient, filter_english_only, split_sentences
from pipeline.benchmark.stages.llm_client import SingleLLMClient
from pipeline.benchmark.stages.union_merge import merge_union_text
from pipeline.benchmark.workflows.base import BaseWorkflow, WorkflowInput, WorkflowResult, utc_now
from pipeline.benchmark.workflows.registry import register_workflow
from pipeline.json_repair import parse_json_object, repair_json_text
from preprocess.pipeline import run_preprocess_steps
from preprocess.section_union import union_experiment_sections
from preprocess.section_union_abs_intro import union_abs_intro_sections


def build_wf1_llm_prompt(sentences: list[str], paper_title: str) -> str:
    """Build LLM prompt for wf1 - extract all 5 fields at once."""
    numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sentences))
    title_line = paper_title or "(unknown)"
    return f"""/no_think
Extract experiment and research information from a scientific paper.

Paper title:
{title_line}

The text below contains experiment sections and abstract/introduction sections.

Return ONLY valid JSON:
{{
  "experiment_name": "primary experiment or method name",
  "key_results": [
    "key finding 1 with metrics",
    "key finding 2 with metrics"
  ],
  "method": "brief description of the method/approach",
  "research_problem": "the problem this paper addresses",
  "research_goal": "the main goal or contribution of this paper"
}}

Rules:
- experiment_name: Use the paper title when it describes the main method. Prefer a concise, method-level name.
- key_results: Extract 0-5 key quantitative findings with metrics/percentages when available. Each item must be one complete sentence. Do NOT fabricate numbers.
- method: Brief description of the proposed method or approach (1-2 sentences).
- research_problem: What problem does this paper solve? (1-2 sentences).
- research_goal: What is the main contribution or goal? (1-2 sentences).
- If a field cannot be extracted from the text, return an empty string for that field.
- For key_results, return empty array [] if no concrete quantitative results are found.

No markdown fences, no explanation.

Sentences:
{numbered}
"""


def metric_richness_score(sentence: str) -> int:
    """Score sentences based on metric richness."""
    score = 0
    metric_pattern = re.compile(
        r"%|"
        r"\bAP\b|\bmIoU\b|\bIoU\b|\bF1(?:-score)?\b|\bAUROC\b|\bAUC\b|"
        r"\baccuracy\b|\bprecision\b|\brecall\b|\bEER\b|\bACER\b|\bBLEU\b|"
        r"\bimprovement\b|\boutperform|\bbaseline|\bstate-of-the-art\b|"
        r"\d+\.?\d*\s*%|\d+\.\d+",
        re.IGNORECASE,
    )
    if metric_pattern.search(sentence):
        score += 3
    if re.search(r"\d+\.?\d*\s*%", sentence):
        score += 2
    if re.search(r"\b\d+\.\d+\b", sentence):
        score += 1
    return score


def select_llm_sentences(
    kept_sentences: list[str],
    confidences: list[float] | None = None,
    max_sentences: int = WF1_MAX_LLM_SENTENCES,
) -> tuple[list[str], dict[str, Any]]:
    """Prioritize metric-rich sentences, then fill with highest BERT confidence."""
    if len(kept_sentences) <= max_sentences:
        metric_rich = sum(1 for s in kept_sentences if metric_richness_score(s) > 0)
        return kept_sentences, {
            "total_kept": len(kept_sentences),
            "selected": len(kept_sentences),
            "metric_rich_selected": metric_rich,
            "truncated": False,
        }

    confidences = confidences or [0.0] * len(kept_sentences)
    ranked = [
        (metric_richness_score(sent), confidences[i], i, sent)
        for i, sent in enumerate(kept_sentences)
    ]
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
    top = ranked[:max_sentences]
    # Select by score, then restore original document order (same as bert-struct).
    top_by_orig = sorted(top, key=lambda item: item[2])
    selected = [item[3] for item in top_by_orig]
    metric_rich = sum(1 for item in top if item[0] > 0)

    return selected, {
        "total_kept": len(kept_sentences),
        "selected": max_sentences,
        "metric_rich_selected": metric_rich,
        "truncated": True,
    }


# TODO-TXT-02: paper titles wrapped across several markdown lines were cut at
# the first line (``.`` in the H1 regex does not match newlines). Continuation
# lines are joined back here, under conservative guards: stop at the first
# blank line / block-structure line, take at most this many lines, and fall
# back to the first line only when the joined result exceeds a sane title
# length (i.e. we likely swallowed body text, not a wrapped title).
_TITLE_CONTINUATION_MAX_LINES = 3
_TITLE_SANITY_MAX_CHARS = 300
_TITLE_NEXT_BLOCK_RE = re.compile(r"^(?:[#\-*>|!\[]|\d+[.)]\s)")


def _join_wrapped_title(first_line: str, following_lines: list[str]) -> str:
    """Join a wrapped H1 title back into one line, re-gluing hyphen breaks."""
    parts = [first_line.strip()]
    for line in following_lines[:_TITLE_CONTINUATION_MAX_LINES]:
        stripped = line.strip()
        if not stripped or _TITLE_NEXT_BLOCK_RE.match(stripped):
            break
        parts.append(stripped)
    joined = " ".join(p for p in parts if p)
    # Re-glue words hyphen-broken at the wrap ("IN- context" → "IN-context");
    # a hyphen directly after a word char only arises from the join above.
    joined = re.sub(r"(\w)- (?=\w)", r"\1-", joined)
    if len(joined) > _TITLE_SANITY_MAX_CHARS:
        return first_line.strip()  # sanity fallback: keep the pre-fix behavior
    return joined


def extract_paper_title(md_text: str) -> str:
    """Extract the first markdown H1 title from raw paper text."""
    match = re.search(r"^#\s+(.+?)\s*$", md_text, re.MULTILINE)
    if not match:
        return ""
    following_lines = md_text[match.end(1):].splitlines()[1:]  # drop the rest of the H1 line
    title = _join_wrapped_title(match.group(1), following_lines)
    title = re.sub(r"\$[^$]+\$", "", title)
    title = re.sub(r"\\[*^][{]?[^}]*[}]?", "", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


@register_workflow("wf1-merged")
class Wf1MergedUnionWorkflow(BaseWorkflow):
    """Workflow 1: Merged union with single LLM extraction."""

    def __init__(self, run_id: str | None = None) -> None:
        super().__init__(run_id)
        self.bert_client = SerialBertClient()
        self.llm_client = SingleLLMClient()

    @property
    def workflow_id(self) -> str:
        return "wf1-merged"

    @property
    def workflow_version(self) -> str:
        return "0.1.0"

    def run(self, input_data: WorkflowInput) -> WorkflowResult:
        """Execute merged union workflow on a single paper."""
        monitor: dict[str, Any] = {
            "paper_id": input_data.paper_id,
            "workflow": self.workflow_id,
            "workflow_version": self.workflow_version,
            "run_id": self.run_id,
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

            # Stage 1: Preprocess
            print(f"\n[{self.workflow_id}] Preprocessing...")
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

            # Stage 2: Union merge
            print(f"\n[{self.workflow_id}] Union merge...")
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

            # Stage 3: Sentence split and filter
            print(f"\n[{self.workflow_id}] Sentence processing...")
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

            # Stage 4: BERT filter
            print(f"\n[{self.workflow_id}] BERT filtering (threshold={WF1_BERT_THRESHOLD})...")
            bert_start = time.perf_counter()
            bert_result = self.bert_client.filter_sentences_serial(
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

            # Stage 5: Select sentences for LLM
            print(f"\n[{self.workflow_id}] Selecting sentences for LLM...")
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
            print(
                f"LLM input: {sentence_selection['selected']}/{sentence_selection['total_kept']} sentences "
                f"({sentence_selection['metric_rich_selected']} metric-rich)"
            )

            # Stage 6: LLM generation
            print(f"\n[{self.workflow_id}] LLM generation (5 fields)...")
            llm_start = time.perf_counter()
            prompt = build_wf1_llm_prompt(llm_input, paper_title)
            llm_result = self.llm_client.generate(
                prompt,
                temperature=0.05,
                num_predict=2048,
            )
            llm_elapsed = time.perf_counter() - llm_start

            # Parse LLM output
            repaired = repair_json_text(llm_result["raw_output"])
            parsed, parse_error = parse_json_object(llm_result["raw_output"])

            monitor["events"].append({
                "timestamp": utc_now(),
                "stage": "llm_generate",
                "event": "completed",
                "elapsed_sec": round(llm_elapsed, 4),
                "raw_output_preview": llm_result["raw_output"][:200],
                "repaired_json": repaired,
                "parse_error": parse_error,
            })

            total_elapsed = time.perf_counter() - overall_start

            # Build prediction
            prediction = {
                "paper_id": input_data.paper_id,
                "paper_title": paper_title,
                "workflow_id": self.workflow_id,
                "workflow_version": self.workflow_version,
                "run_id": self.run_id,
                "experiment_name": parsed.get("experiment_name", "") if parsed else "",
                "key_results": parsed.get("key_results", []) if parsed else [],
                "method": parsed.get("method", "") if parsed else "",
                "research_problem": parsed.get("research_problem", "") if parsed else "",
                "research_goal": parsed.get("research_goal", "") if parsed else "",
                "time_breakdown_sec": {
                    "preprocess": round(preprocess_elapsed, 4),
                    "union_merge": round(union_elapsed, 4),
                    "bert_filter": round(bert_elapsed, 4),
                    "llm_generate": round(llm_elapsed, 4),
                    "total": round(total_elapsed, 4),
                },
                "provenance": {
                    "union_mode": "merged",
                    "bert_mode": "serial",
                    "llm_mode": "single",
                    "bert_threshold": WF1_BERT_THRESHOLD,
                    "max_llm_sentences": WF1_MAX_LLM_SENTENCES,
                },
                "parse_error": parse_error,
            }

            monitor["finished_at"] = utc_now()
            monitor["total_elapsed_sec"] = round(total_elapsed, 4)

            print(f"\n[{self.workflow_id}] Summary:")
            print(f"  experiment_name: {prediction['experiment_name'][:80] or '(empty)'}")
            print(f"  key_results: {len(prediction['key_results'])} items")
            print(f"  method: {prediction['method'][:80] or '(empty)'}")
            print(f"  research_problem: {prediction['research_problem'][:80] or '(empty)'}")
            print(f"  research_goal: {prediction['research_goal'][:80] or '(empty)'}")
            print(f"  total time: {total_elapsed:.2f}s")

            return WorkflowResult(
                workflow_id=self.workflow_id,
                workflow_version=self.workflow_version,
                run_id=self.run_id,
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
                workflow_id=self.workflow_id,
                workflow_version=self.workflow_version,
                run_id=self.run_id,
                paper_id=input_data.paper_id,
                prediction={},
                monitor=monitor,
                error=str(e),
            )