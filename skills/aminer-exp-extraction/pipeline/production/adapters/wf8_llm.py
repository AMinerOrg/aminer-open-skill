"""LLM adapter: bridges the frozen 板块 5 wf8 pipeline as the llm_group source.

Calls ``pipeline.benchmark.workflows.wf8_core.run_wf8_pipeline`` with the frozen
dev20-v2-wash config (sentence_clean=True, metrics_cap=20). wf8 reads the md
file itself and runs its own preprocess (strip refs, union, BERT, LLM) — so
production does NOT pre-slice text1 for the LLM path (see ARCHITECTURE.md D1).

wf8 returns a single-experiment prediction (7 fields). prod-wf1 v0.1.0 is
1 paper -> 1 experiment; multi-experiment expansion is reserved in merge.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pipeline.benchmark.workflows.base import WorkflowInput
from pipeline.benchmark.workflows.wf8_core import (
    build_wf8_dev20_v2_prompt,
    run_wf8_pipeline,
)

from pipeline.production.config import (
    WF8_METRICS_CAP,
    WF8_LLM_MODE_LABEL,
    WF8_SENTENCE_CLEAN,
    WF8_WORKFLOW_ID,
    WF8_WORKFLOW_VERSION,
)
from pipeline.production.schema import FieldResult

LLM_GROUP_FIELDS = (
    "experiment_name",
    "research_problem",
    "research_goal",
    "experiment_subject",
    "method",
    "key_results",
    "metrics",
)


def run_wf8_for_production(
    paper_id: str,
    md_path: Path,
    run_id: str,
) -> FieldResult:
    """Run the frozen wf8 dev20-v2-wash pipeline and map to a FieldResult.

    Raises on failure — the caller (the llm Extractor) wraps it into
    status="error" via FieldExtractor.extract.
    """
    input_data = WorkflowInput(paper_id=paper_id, md_path=md_path, run_id=run_id)
    result = run_wf8_pipeline(
        input_data,
        run_id=run_id,
        workflow_id=WF8_WORKFLOW_ID,
        workflow_version=WF8_WORKFLOW_VERSION,
        prompt_builder=build_wf8_dev20_v2_prompt,
        llm_mode_label=WF8_LLM_MODE_LABEL,
        metrics_cap=WF8_METRICS_CAP,
        sentence_clean=WF8_SENTENCE_CLEAN,
    )

    if result.error:
        raise RuntimeError(f"wf8 pipeline error: {result.error}")

    pred = result.prediction
    value: dict[str, Any] = {f: pred.get(f) for f in LLM_GROUP_FIELDS}
    return FieldResult(
        extractor_id="llm.wf8_dev20_v2_wash",
        version=WF8_WORKFLOW_VERSION,
        status="ok",
        value=value,
        fields=list(LLM_GROUP_FIELDS),
        metadata={
            "paper_title": result.paper_title,
            "wf8_monitor": result.monitor,
            "time_breakdown": pred.get("time_breakdown_sec"),
            "provenance": pred.get("provenance"),
        },
    )
