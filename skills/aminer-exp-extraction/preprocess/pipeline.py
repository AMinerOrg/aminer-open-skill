"""Lightweight preprocess step orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from preprocess.compact_markdown import CompactMarkdownResult, compact_markdown
from preprocess.strip_references import StripReferencesResult, strip_references

SUPPORTED_PREPROCESS_STEPS = frozenset({"strip_references", "compact_markdown"})


@dataclass(frozen=True)
class PreprocessPipelineResult:
    text: str
    steps: list[str]
    strip_references: StripReferencesResult | None = None
    compact_markdown: CompactMarkdownResult | None = None


def run_preprocess_steps(md_text: str, steps: list[str]) -> PreprocessPipelineResult:
    """Run configured preprocess steps in order."""
    if not steps:
        return PreprocessPipelineResult(text=md_text, steps=[])

    current_text = md_text
    strip_result: StripReferencesResult | None = None
    compact_result: CompactMarkdownResult | None = None
    applied_steps: list[str] = []

    for step in steps:
        if step not in SUPPORTED_PREPROCESS_STEPS:
            raise ValueError(f"Unsupported preprocess step: {step}")
        if step == "strip_references":
            strip_result = strip_references(current_text)
            current_text = strip_result.text
            applied_steps.append(step)
        elif step == "compact_markdown":
            compact_result = compact_markdown(current_text)
            current_text = compact_result.text
            applied_steps.append(step)

    return PreprocessPipelineResult(
        text=current_text,
        steps=applied_steps,
        strip_references=strip_result,
        compact_markdown=compact_result,
    )
