"""wf4 normalization — datasets[] + multi-experiment coerce/cap.

``normalize_llm_datasets`` takes a parsed ``datasets`` value and returns schema-
shaped dataset dicts (via ``empty_dataset()``). Entries with an empty name are
dropped; the list is capped at ``WF4_DATASETS_CAP`` (20) **per experiment**.

``normalize_experiments`` / ``coerce_wf4_llm_parsed`` handle the multi-exp LLM
schema (paper-level research_problem* + experiments[0..3]) with backward
compat for the old flat single-experiment JSON shape.

EXT-09: each experiment carries ``methods: [{name, description, aliases}, ...]``.
Paper-level ``research_problem_aliases`` rides alongside
``research_problem``/``research_problem_description`` (Problem is NOT
objectified). Legacy ingest coerces ``methods: string[]`` and/or ``method`` +
``method_description`` into objects (shared description attaches to the first
name only; aliases default empty). Output never writes ``method`` /
``method_description``. Justification fields are not part of the schema
(incoming keys are dropped). Paper-level hard budget
``M_total ≤ WF4_MAX_METHODS_PER_PAPER`` counts names.
"""

from __future__ import annotations

import re
from typing import Any

from pipeline.benchmark.parse_helpers import normalize_sample_size, normalize_string_list
from pipeline.production.config import (
    WF4_DATASETS_CAP,
    WF4_MAX_EXPERIMENTS,
    WF4_MAX_METHODS_PER_PAPER,
    WF8_METRICS_CAP,
)
from pipeline.production.schema import empty_dataset

# Advisory enums (mirror the prompt closed sets). Out-of-enum strings coerce
# to "" rather than rejecting — the prompt enum is advisory only.
_DATASET_TYPE_ENUM = {
    "tabular",
    "image",
    "video",
    "text",
    "audio",
    "graph",
    "point_cloud",
    "3d_mesh",
    "time_series",
    "multimodal",
    "code",
    "other",
}

_DOMAIN_ENUM = {
    "computer_science",
    "medicine",
    "biology",
    "chemistry",
    "physics",
    "materials",
    "engineering",
    "economics",
    "education",
    "energy",
    "environment",
    "social_science",
    "other",
}

_EXPERIMENT_TYPE_ENUM = {
    "benchmark",
    "comparison",
    "ablation",
    "simulation",
    "survey",
    "human_study",
    "field_study",
    "lab_experiment",
    "clinical_trial",
    "case_study",
    "empirical_study",
    "data_analysis",
    "other",
}


def _normalize_closed_enum(raw: Any, allowed: set[str]) -> str:
    """Lowercase + collapse spaces/hyphens to underscores; unknown → \"\"."""
    if raw is None:
        return ""
    s = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    s = re.sub(r"_+", "_", s).strip("_")
    return s if s in allowed else ""


def normalize_domain(raw: Any) -> str:
    """Paper-level domain closed-set; unknown / empty → \"\"."""
    return _normalize_closed_enum(raw, _DOMAIN_ENUM)


def normalize_experiment_type(raw: Any) -> str:
    """Per-experiment type closed-set; unknown / empty → \"\"."""
    return _normalize_closed_enum(raw, _EXPERIMENT_TYPE_ENUM)

# Paper-structure labels mistaken for dataset names (Table 2, Fig. 1, ...).
_PAPER_STRUCTURE_DATASET_NAME_RE = re.compile(
    r"^\s*(tables?|figures?|figs?|eqs?|equations?|algorithms?|sections?|"
    r"appendi(?:x|ces)|supp(?:lementary)?)\s*[\d]+([.\-]\d+)*\s*$",
    re.IGNORECASE,
)


def _is_paper_structure_dataset_name(name: str) -> bool:
    """True when name is a paper table/figure/section label, not a dataset."""
    return bool(_PAPER_STRUCTURE_DATASET_NAME_RE.match(name or ""))


# TODO-TXT-01: LLM-extracted name-class fields can carry paper citation
# markers ("Checkpoint Merging [113]"). Names are labels, not prose, so the
# markers are stripped there only; description/key_results prose keeps its
# citation style untouched. Accepts plain digit runs and "1,2" / "1-3" lists.
_CITATION_MARKER_RE = re.compile(r"\s*\[\d+(?:\s*[,;\u2013\-]\s*\d+)*\]")


def strip_citation_markers(value: str) -> str:
    """Strip bracketed-digit citation markers from a name-class string."""
    if not value:
        return value
    return _CITATION_MARKER_RE.sub("", value).strip()


def strip_citation_markers_list(values: list[str]) -> list[str]:
    """List form of ``strip_citation_markers``; entries emptied by the strip drop."""
    return [s for s in (strip_citation_markers(v) for v in values) if s]


def normalize_single_phrase(raw: Any) -> str:
    """Coerce a parsed method/research_problem value to a single string.

    Quantity/shape normalization only — no word-count truncation.
    """
    if raw is None:
        return ""
    if isinstance(raw, list):
        for item in raw:
            s = str(item).strip()
            if s:
                return s
        return ""
    return str(raw).strip()


def normalize_description(raw: Any) -> str:
    """Coerce a parsed description field to a single string (1-2 sentences).

    Quantity/shape normalization only — no sentence truncation.
    """
    return normalize_single_phrase(raw)


def _method_object(
    name: str,
    description: str = "",
    aliases: list[str] | None = None,
) -> dict[str, Any]:
    """Build a single methods[] item: ``{name, description, aliases}``."""
    return {
        "name": name,
        "description": description,
        "aliases": list(aliases or []),
    }


def normalize_methods(
    raw: Any,
    legacy_method: Any = None,
    legacy_method_description: Any = None,
) -> list[dict[str, Any]]:
    """Normalize methods to ``[{name, description, aliases}, ...]``.

    Ingest priority:
      1. ``methods`` as object list → keep name/description/aliases per item
         (legacy ``{name, description}`` coerced up; ``justification`` dropped).
      2. ``methods`` as string list (or single string) → objects with empty
         descriptions; attach shared ``legacy_method_description`` to the first.
      3. Else promote legacy ``method`` (+ optional shared description).
      4. Description-only with no name → [].

    Cap is loose here; paper budget is applied later. Output never includes
    legacy ``method`` / ``method_description`` or ``justification`` keys.
    """
    # Allow > paper budget here so apply_paper_methods_budget can detect truncation.
    loose_cap = max(20, WF4_MAX_METHODS_PER_PAPER * 3)
    shared_desc = normalize_description(legacy_method_description)

    def _from_names(names: list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for i, name in enumerate(names):
            name = strip_citation_markers(name)
            if not name:
                continue
            desc = shared_desc if i == 0 else ""
            out.append(_method_object(name, desc))
            if len(out) >= loose_cap:
                break
        return out

    if isinstance(raw, list):
        if not raw:
            return []
        # Object list: any dict item with a usable name.
        if any(isinstance(x, dict) for x in raw):
            out: list[dict[str, Any]] = []
            for item in raw:
                if not isinstance(item, dict):
                    # Tolerate mixed lists: bare strings become name-only objects.
                    phrase = strip_citation_markers(normalize_single_phrase(item))
                    if phrase:
                        out.append(_method_object(phrase, ""))
                    continue
                name = strip_citation_markers(
                    normalize_single_phrase(item.get("name"))
                )
                if not name:
                    continue
                desc = normalize_description(item.get("description"))
                aliases = strip_citation_markers_list(
                    normalize_string_list(item.get("aliases"), max_items=20)
                )
                out.append(_method_object(name, desc, aliases))
                if len(out) >= loose_cap:
                    break
            return out
        # String list (legacy EXT-09).
        names = normalize_string_list(raw, max_items=loose_cap)
        return _from_names(names)

    if isinstance(raw, str) and raw.strip():
        names = normalize_string_list([raw], max_items=loose_cap)
        return _from_names(names)

    # legacy single method field
    if legacy_method is not None:
        phrase = strip_citation_markers(normalize_single_phrase(legacy_method))
        if phrase:
            return [_method_object(phrase, shared_desc)]
    return []


def method_name_for_ml(exp: dict[str, Any] | None) -> str:
    """First methods[].name for ML feature dicts; never reads legacy ``method``."""
    if not isinstance(exp, dict):
        return ""
    methods = exp.get("methods") or []
    if methods and isinstance(methods[0], dict):
        return str(methods[0].get("name") or "").strip()
    return ""


def _per_experiment_method_cap(n_experiments: int) -> int:
    """Max methods kept on one experiment given paper experiment count E."""
    if n_experiments <= 0:
        return 0
    if n_experiments == 1:
        return WF4_MAX_METHODS_PER_PAPER  # 0–3
    if n_experiments == 2:
        return 2  # allow 2+1
    return 1  # E>=3: at most 1 each


def apply_paper_methods_budget(
    experiments: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    """Enforce paper-level method-name budget; preserve descriptions of kept items.

    Returns ``(experiments, truncated)`` where truncated is True if any method
    was dropped by the paper budget or per-experiment cap. Does not write
    ``method`` / ``method_description``.
    """
    e_count = len(experiments)
    if e_count == 0:
        return experiments, False

    per_cap = _per_experiment_method_cap(e_count)
    remaining = WF4_MAX_METHODS_PER_PAPER
    truncated = False
    out: list[dict[str, Any]] = []
    for exp in experiments:
        methods = list(exp.get("methods") or [])
        before = len(methods)
        keep_n = min(len(methods), per_cap, remaining)
        if keep_n < before:
            truncated = True
        kept = methods[:keep_n]
        remaining -= len(kept)
        updated = dict(exp)
        updated["methods"] = kept
        updated.pop("method", None)
        updated.pop("method_description", None)
        out.append(updated)
    return out, truncated


def _coerce_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("true", "false"):
            return s == "true"
        # Tolerate natural-language public/private labels emitted by some
        # extraction models (e.g. LFM2 emits "Public"/"Private"). wf4-local
        # hardening only; does not affect the conservative parse_helpers path.
        if s in ("public", "open", "yes", "y", "released"):
            return True
        if s in ("private", "restricted", "no", "n", "closed"):
            return False
    return None


def _coerce_sample_size(value: Any) -> int | None:
    """wf4-local sample_size coercion with a suffix fallback.

    Defers to the conservative ``normalize_sample_size`` first (handles int,
    numeric strings, commas). If that returns None, tries compact suffix
    forms emitted by some extraction models (``"10M"``/``"1.2m"``/``"5k"``/``"3.5K"``).
    Never guesses when neither path parses. wf4-local — parse_helpers stays
    conservative for baseline/wf8.
    """
    primary = normalize_sample_size(value)
    if primary is not None:
        return primary
    if isinstance(value, str):
        s = value.strip().replace(",", "").lower()
        if not s:
            return None
        suffix = s[-1]
        mult = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(suffix)
        if mult is not None and len(s) > 1:
            try:
                return int(float(s[:-1]) * mult)
            except ValueError:
                return None
    return None


def normalize_llm_datasets(raw: Any) -> list[dict[str, Any]]:
    """Normalize parsed datasets into a list of schema-shaped dataset dicts.

    - Tolerates None, a single dict, or a list.
    - Each item is filled against ``empty_dataset()``.
    - Items with an empty name are dropped.
    - Paper-structure labels (``Table 2``, ``Fig. 1``, …) are dropped.
    - Incoming ``justification`` keys are ignored (not in schema).
    - Capped at ``WF4_DATASETS_CAP`` **per experiment**.
    """
    if raw is None:
        return []
    if isinstance(raw, dict):
        raw = [raw]  # tolerate a single object
    if not isinstance(raw, list):
        return []

    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        d = empty_dataset()
        name = strip_citation_markers(str(item.get("name", "") or "").strip())
        if not name:
            continue  # drop nameless entries (incl. marker-only names)
        if _is_paper_structure_dataset_name(name):
            continue  # Table/Figure/Section labels are not datasets
        d["name"] = name
        d["aliases"] = strip_citation_markers_list(
            normalize_string_list(item.get("aliases"), max_items=20)
        )
        dt = str(item.get("dataset_type", "") or "").strip().lower()
        d["dataset_type"] = dt if dt in _DATASET_TYPE_ENUM else ""
        d["description"] = str(item.get("description", "") or "").strip()
        d["sample_size"] = _coerce_sample_size(item.get("sample_size"))
        d["is_public"] = _coerce_bool(item.get("is_public"))
        d["is_self_collected"] = _coerce_bool(item.get("is_self_collected"))
        for akey in ("urls", "github_urls", "doi_list", "cstr_list"):
            d[akey] = normalize_string_list(item.get(akey), max_items=50)
        out.append(d)
        if len(out) >= WF4_DATASETS_CAP:
            break
    return out


def normalize_experiment_item(raw: Any) -> dict[str, Any] | None:
    """Normalize one experiment object. Returns None if unusable."""
    if not isinstance(raw, dict):
        return None
    methods = normalize_methods(
        raw.get("methods"),
        legacy_method=raw.get("method"),
        legacy_method_description=raw.get("method_description"),
    )
    return {
        "experiment_name": strip_citation_markers(
            str(raw.get("experiment_name", "") or "").strip()
        ),
        "experiment_type": normalize_experiment_type(raw.get("experiment_type")),
        "key_results": normalize_string_list(raw.get("key_results")),
        "methods": methods,
        "research_goal": str(raw.get("research_goal", "") or "").strip(),
        "experiment_subject": normalize_string_list(raw.get("experiment_subject")),
        "metrics": normalize_string_list(raw.get("metrics"), max_items=WF8_METRICS_CAP),
        "datasets": normalize_llm_datasets(raw.get("datasets")),
    }


def normalize_experiments(raw: Any) -> list[dict[str, Any]]:
    """Normalize experiments list: drop malformed, cap at WF4_MAX_EXPERIMENTS.

    Does **not** apply the paper-level methods budget; call
    ``apply_paper_methods_budget`` (via ``coerce_wf4_llm_parsed``) after.
    """
    if raw is None:
        return []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        normed = normalize_experiment_item(item)
        if normed is None:
            continue
        out.append(normed)
        if len(out) >= WF4_MAX_EXPERIMENTS:
            break
    return out


def _looks_like_old_flat_experiment(parsed: dict[str, Any]) -> bool:
    """True when top-level has experiment fields and no usable experiments[]."""
    experiments = parsed.get("experiments")
    if isinstance(experiments, list) and any(isinstance(x, dict) for x in experiments):
        return False
    return any(
        parsed.get(k) not in (None, "", [], {})
        for k in (
            "experiment_name",
            "method",
            "methods",
            "research_goal",
            "datasets",
            "key_results",
        )
    )


def coerce_wf4_llm_parsed(
    parsed: Any, *, full_text: str | None = None
) -> dict[str, Any]:
    """Coerce parsed LLM JSON into paper-level RP + normalized experiments.

    - New schema: top-level research_problem* + experiments[].
    - Old flat schema: wrap single-exp fields into experiments[0].
    - Missing/unusable: experiments=[] (caller may treat as ok; do not invent).
    - Applies paper-level methods budget; sets ``methods_truncated_by_paper_budget``.
    - Carries ``research_problem_aliases`` (Problem is NOT objectified).
    - Paper-level ``domain`` and per-experiment ``experiment_type`` are closed
      enums; unknown values coerce to "".
    - ``full_text`` is accepted for call-site compatibility; unused here
      (justification scrubbing removed from the schema).
    """
    _ = full_text  # API compat with wf4_stages; scrubbing removed
    if not isinstance(parsed, dict):
        return {
            "research_problem": "",
            "research_problem_description": "",
            "research_problem_aliases": [],
            "domain": "",
            "experiments": [],
            "methods_truncated_by_paper_budget": False,
        }

    research_problem = strip_citation_markers(
        normalize_single_phrase(parsed.get("research_problem"))
    )
    research_problem_description = normalize_description(
        parsed.get("research_problem_description")
    )
    research_problem_aliases = strip_citation_markers_list(
        normalize_string_list(parsed.get("research_problem_aliases"), max_items=20)
    )
    domain = normalize_domain(parsed.get("domain"))

    experiments_raw = parsed.get("experiments")
    if isinstance(experiments_raw, list) and any(
        isinstance(x, dict) for x in experiments_raw
    ):
        experiments = normalize_experiments(experiments_raw)
    elif _looks_like_old_flat_experiment(parsed):
        experiments = normalize_experiments(
            [
                {
                    "experiment_name": parsed.get("experiment_name", ""),
                    "key_results": parsed.get("key_results"),
                    "method": parsed.get("method"),
                    "methods": parsed.get("methods"),
                    "method_description": parsed.get("method_description"),
                    "research_goal": parsed.get("research_goal", ""),
                    "experiment_subject": parsed.get("experiment_subject"),
                    "experiment_type": parsed.get("experiment_type"),
                    "metrics": parsed.get("metrics"),
                    "datasets": parsed.get("datasets"),
                }
            ]
        )
    else:
        experiments = normalize_experiments(experiments_raw)

    experiments, truncated = apply_paper_methods_budget(experiments)

    return {
        "research_problem": research_problem,
        "research_problem_description": research_problem_description,
        "research_problem_aliases": research_problem_aliases,
        "domain": domain,
        "experiments": experiments,
        "methods_truncated_by_paper_budget": truncated,
    }
