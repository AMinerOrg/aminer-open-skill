"""Union merge stage for wf1 workflow."""

from __future__ import annotations

from pipeline.benchmark.config import (
    ABSINTRO_SECTION_MARKER,
    DATASET_FALLBACK_SECTION_MARKER,
    EXPERIMENT_SECTION_MARKER,
)
from preprocess.section_union import union_experiment_sections
from preprocess.section_union_abs_intro import union_abs_intro_sections


def merge_union_text(
    experiment_union: str | None,
    absintro_union: str | None,
    dataset_fallback: str | None = None,
) -> str:
    """Merge experiment and absintro union text with section markers.

    Args:
        experiment_union: Output from union_experiment_sections()
        absintro_union: Output from union_abs_intro_sections()
        dataset_fallback: Optional third block from
            ``apply_dataset_section_fallback`` (appended only when the primary
            union missed dataset-bearing sections). ``None`` or ``""`` -> no
            third block (fully backward compatible).

    Returns:
        Merged text with === EXPERIMENT === / === ABSINTRO === and optionally
        === DATASET_FALLBACK === markers.
    """
    parts = []
    if experiment_union:
        parts.append(f"{EXPERIMENT_SECTION_MARKER}\n\n{experiment_union}")
    if absintro_union:
        parts.append(f"{ABSINTRO_SECTION_MARKER}\n\n{absintro_union}")
    if dataset_fallback:
        parts.append(f"{DATASET_FALLBACK_SECTION_MARKER}\n\n{dataset_fallback}")
    return "\n\n".join(parts).strip()


def split_merged_sections(merged_text: str) -> tuple[str, str]:
    """Split merged text back into experiment and absintro sections.

    Args:
        merged_text: Text output from merge_union_text()

    Returns:
        Tuple of (experiment_text, absintro_text)
    """
    experiment_parts = []
    absintro_parts = []
    current_target = None

    for line in merged_text.split("\n"):
        if EXPERIMENT_SECTION_MARKER in line:
            current_target = "experiment"
            continue
        elif ABSINTRO_SECTION_MARKER in line:
            current_target = "absintro"
            continue

        if current_target == "experiment":
            experiment_parts.append(line)
        elif current_target == "absintro":
            absintro_parts.append(line)

    return "\n".join(experiment_parts).strip(), "\n".join(absintro_parts).strip()