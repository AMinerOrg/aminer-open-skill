"""Parsing helpers for benchmark workflow outputs.

This module centralises the normalisation of list-of-strings fields extracted
by LLM, so that every workflow applies the same cleaning rules before writing
a prediction to disk.

`experiment_subject` semantics (kept here in code/docs, NOT in the LLM prompt)
============================================================================

`experiment_subject` is the 6th extraction field introduced by wf7
(``wf7-merged-six-fields``), aligned with the GLM reference schema. It captures
**what the paper studies or evaluates** — the technical objects/entities under
experiment — as a list of short English phrases.

What counts as an experiment_subject:
- Named models / systems / architectures that are proposed or evaluated
  (e.g. "CSDN", "BERT", "ResNet-50", "IPAdaIN").
- Baselines / competitors compared against (e.g. "SnowflakeNet", "PoinTr").
- Modules or sub-components that are ablated / evaluated as units
  (e.g. "shape fusion module", "dual-refinement module").
- Task / capability entities that are the object of study when they are the
  thing being measured (e.g. "point cloud completion", "cross-modal feature
  fusion").

What does NOT count (these belong to other fields):
- Dataset names alone (e.g. "ShapeNet-ViPC", "KITTI") — datasets live in their
  own schema and are not subjects. A subject may *use* a dataset, but the
  dataset name by itself is not a subject.
- Pure metric names with no entity (e.g. "F1", "mIoU") — these belong to
  key_results.
- Long descriptive sentences — each item must be a short phrase, not a clause.

Anti-examples:
  - BAD:  ["ShapeNet-ViPC", "KITTI"]           (datasets, not subjects)
  - BAD:  ["The proposed method"]               (too vague; use the name)
  - BAD:  ["We evaluate on three benchmarks"]   (a sentence, not a phrase)
  - GOOD: ["CSDN", "SnowflakeNet", "PoinTr", "point cloud completion"]

The LLM prompt for wf7 intentionally keeps only a one-line rule for this
field; the full definition lives here so the prompt stays short (LLM is
output-bound, and long rules cost prompt_eval tokens without speeding up
generation).

`sample_size` semantics (wf9, kept here in code/docs, NOT in the LLM prompt)
=============================================================================

`sample_size` is the 8th extraction field introduced by wf9
(``wf9-merged-eight-fields-dev20-v2-wash``), aligned with the GLM top-level
``sample_size``. It captures **the data actually used in this experiment** —
the real usage scale of the experiment, e.g.:

- number of subjects / participants in a user study,
- number of trials / samples actually evaluated,
- the count of test instances the reported metrics are computed over.

What it is NOT:
- It is NOT ``datasets[].sample_size`` — that is dataset-metadata (the total
  size of the dataset as a resource). The experiment may use only a subset.
  e.g. a dataset of 49,600,000 images may be used in an experiment with
  sample_size = 33,223.
- Pretraining-corpus scale does NOT count.
- When a paper has multiple cohorts with no single total, ``sample_size`` is
  null (do not sum or pick max).

A paper with no dataset can still have a sample_size (e.g. 20 real-world
trials). When unsure, null.

The LLM prompt keeps a one-line rule; this full definition lives here so the
prompt stays short.
"""

from __future__ import annotations

import re
from typing import Any


def normalize_string_list(value: Any, *, max_items: int = 10) -> list[str]:
    """Normalize a value into a clean list of non-empty strings.

    Accepts a list, a single string, or None. Each item is stripped of
    surrounding whitespace, collapsed internally, deduplicated
    case-insensitively (first-seen order preserved), and capped at
    ``max_items``.

    Args:
        value: The raw value extracted from LLM JSON (typically a list, but
            defensively handles a stray string or None).
        max_items: Hard cap on the number of items returned.

    Returns:
        A cleaned, deduplicated list of non-empty strings.
    """
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = [v for v in value if isinstance(v, str)]
    else:
        return []

    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        stripped = re.sub(r"\s+", " ", item).strip()
        if not stripped:
            continue
        key = stripped.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(stripped)
        if len(cleaned) >= max_items:
            break
    return cleaned


def count_dataset_leaks(
    subjects: list[str],
    dataset_names: set[str],
    dataset_aliases: set[str],
) -> dict[str, Any]:
    """Count how many experiment_subject items match a known dataset name/alias.

    Monitoring-only metric: detects items that leaked dataset names despite the
    prompt rule "not dataset names alone". Does NOT modify the subjects — v0.2
    does no post-processing (the prompt route was chosen).

    Matching is case-insensitive exact match against the provided name/alias
    sets (both expected lowercased). A subject like "ShapeNet-ViPC" should be
    passed as-is; it matches if "shapenet-vipc" is in dataset_names.

    Args:
        subjects: The predicted experiment_subject list.
        dataset_names: Lowercased dataset name set (from data/json datasets[].name).
        dataset_aliases: Lowercased dataset alias set (from data/json datasets[].aliases).

    Returns:
        {"leak_count": int, "leaked_items": [str, ...]} — leaked_items are the
        original-cased subject strings that matched.
    """
    if not subjects:
        return {"leak_count": 0, "leaked_items": []}
    leaked: list[str] = []
    for s in subjects:
        if not isinstance(s, str):
            continue
        key = s.strip().lower()
        if not key:
            continue
        if key in dataset_names or key in dataset_aliases:
            leaked.append(s)
    return {"leak_count": len(leaked), "leaked_items": leaked}


def normalize_sample_size(value: Any) -> int | None:
    """Normalize the ``sample_size`` field into an int or None.

    Accepts an int, a numeric string (with optional commas), or null/None.
    Examples: ``38328``, ``"38,328"``, ``"1000"`` -> int. Anything that cannot
    be parsed as a plain integer (e.g. ``"11.2M"``, ``"~1000"``, ``"unknown"``)
    returns None — do NOT guess or scale.

    Rationale: sample_size is the data actually used in the experiment (see
    module docstring). Conservative parsing avoids fabricated numbers; when
    unsure, null.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        # bool is a subclass of int; reject it explicitly.
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return int(value) if value >= 0 else None
    if isinstance(value, str):
        s = value.strip().replace(",", "")
        if s.isdigit():
            return int(s)
        # negative or non-integer strings -> None
        return None
    return None
