"""Schema + field policy for the production layer.

Field ownership (overrides the stale pack ``merger.py`` lists — see
``docs/FIELD_DEPENDENCIES.md``). The production ``merge.py`` is the source of
truth; the pack Merger is never called directly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# LLM-owned fields (板块 5 wf8 dev20-v2-wash, 7 fields).
# wf4 additionally owns paper-level ``domain`` and per-exp ``experiment_type``
# via the LLM partial (not this tuple; see MergerWf4).
LLM_FIELDS: tuple[str, ...] = (
    "experiment_name",
    "research_problem",
    "research_goal",
    "experiment_subject",
    "methods",
    "key_results",
    "metrics",
)

# Rule/ML-owned fields (remote pack; wf1–wf3). wf4 reads domain/experiment_type
# from the LLM partial instead of ML extractors.
RULE_FIELDS: tuple[str, ...] = (
    "paper_id",
    "sample_size",
    "domain",
    "experiment_type",
    "datasets",
    "conclusion",
    "limitations",
    "evidence",
)

# Meta / placeholder fields (orchestration).
META_FIELDS: tuple[str, ...] = (
    "_id",
    "experiment_history",
    "score",
)

# Full top-level field set of one experiment as merged for wf1-wf3 (matches
# EXPERIMENT_REQUIRED_FIELDS below). For wf4, ``research_problem`` is paper-level
# and popped by MergerWf4: the authoritative output contract is
# ``pipeline/production/schemas/wf4_experiment_v1.schema.json`` (which
# supersedes the vendored pack experiment_v1.schema.json).
EXPERIMENT_REQUIRED_FIELDS: tuple[str, ...] = (
    "_id",
    "paper_id",
    "experiment_name",
    "research_problem",
    "research_goal",
    "experiment_subject",
    "methods",
    "datasets",
    "sample_size",
    "metrics",
    "key_results",
    "conclusion",
    "limitations",
    "evidence",
    "domain",
    "experiment_type",
    "experiment_history",
    "score",
)

# Required subfields of each datasets[] entry (wf4 output contract; the
# optional confidence/confidence_breakdown keys are added by post-processing).
DATASETS_REQUIRED_SUBFIELDS: tuple[str, ...] = (
    "name",
    "aliases",
    "dataset_type",
    "description",
    "sample_size",
    "is_public",
    "is_self_collected",
    "urls",
    "github_urls",
    "doi_list",
    "cstr_list",
)


@dataclass
class FieldResult:
    """Output of one Extractor run.

    ``value`` is the raw payload this extractor produces (shape is
    extractor-specific; the Merger knows how to consume it). ``status`` is one
    of: ok | stub | error | skipped.
    """

    extractor_id: str
    version: str
    status: str
    value: Any = None
    elapsed_sec: float = 0.0
    error: str | None = None
    fields: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "extractor_id": self.extractor_id,
            "version": self.version,
            "status": self.status,
            "elapsed_sec": round(self.elapsed_sec, 4),
            "fields": self.fields,
            "error": self.error,
            "metadata": self.metadata,
        }


def empty_experiment(paper_id: str) -> dict[str, Any]:
    """Return an experiment dict with all required fields set to type-correct
    empty defaults (used by dry-run + as merge baseline)."""
    return {
        "_id": "",
        "paper_id": paper_id,
        "experiment_name": "",
        "research_problem": "",
        "research_goal": "",
        "experiment_subject": [],
        "methods": [],
        "datasets": [],
        "sample_size": None,
        "metrics": [],
        "key_results": [],
        "conclusion": "",
        "limitations": "",
        "evidence": [],
        "domain": "",
        "experiment_type": "",
        "experiment_history": [],
        "score": None,
    }


def empty_dataset() -> dict[str, Any]:
    """Return a datasets[] entry with all required subfields defaulted."""
    return {
        "name": "",
        "aliases": [],
        "dataset_type": "",
        "description": "",
        "sample_size": None,
        "is_public": None,
        "is_self_collected": None,
        "urls": [],
        "github_urls": [],
        "doi_list": [],
        "cstr_list": [],
    }


# ---------------------------------------------------------------------------
# wf4 experiment output validation (stdlib-only JSON Schema subset).
# ---------------------------------------------------------------------------

_WF4_EXPERIMENT_SCHEMA_PATH = (
    Path(__file__).resolve().parent / "schemas" / "wf4_experiment_v1.schema.json"
)
_WF4_EXPERIMENT_SCHEMA: dict[str, Any] | None = None

_TYPE_CHECKS: dict[str, Any] = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
}


def _load_wf4_experiment_schema() -> dict[str, Any]:
    global _WF4_EXPERIMENT_SCHEMA
    if _WF4_EXPERIMENT_SCHEMA is None:
        _WF4_EXPERIMENT_SCHEMA = json.loads(
            _WF4_EXPERIMENT_SCHEMA_PATH.read_text(encoding="utf-8")
        )
    return _WF4_EXPERIMENT_SCHEMA


def _validate_node(value: Any, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    expected = schema.get("type")
    if expected is not None:
        types = expected if isinstance(expected, list) else [expected]
        if not any(_TYPE_CHECKS[t](value) for t in types):
            errors.append(
                f"{path}: expected type {'/'.join(types)}, got {type(value).__name__}"
            )
            return  # shape wrong; deeper checks would only add noise
    enum = schema.get("enum")
    if enum is not None and value not in enum:
        errors.append(f"{path}: {value!r} not in enum ({len(enum)} values)")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required key {key!r}")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    errors.append(f"{path}: unexpected key {key!r}")
        for key, sub in value.items():
            if key in props:
                _validate_node(sub, props[key], f"{path}.{key}", errors)
    elif isinstance(value, list):
        items = schema.get("items")
        if isinstance(items, dict):
            for i, item in enumerate(value):
                _validate_node(item, items, f"{path}[{i}]", errors)


def validate_wf4_experiment(exp: Any) -> list[str]:
    """Validate one wf4 experiment dict against schemas/wf4_experiment_v1.schema.json.

    Returns a list of human-readable errors (empty list = valid). Implements a
    stdlib-only subset of JSON Schema: type / enum / required / properties /
    additionalProperties / items — enough for the wf4 contract above; no
    external jsonschema dependency.
    """
    errors: list[str] = []
    _validate_node(exp, _load_wf4_experiment_schema(), "$", errors)
    return errors
