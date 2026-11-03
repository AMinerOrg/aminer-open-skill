"""Model-guided query planning and conservative direct-baseline selection."""

from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from .retrieval import (
    BASELINE_DIRECT_RETRIEVAL_ROLES,
    BASELINE_BIBLIOGRAPHY_ROLE,
    BASELINE_RELATION_ROLES,
    BASELINE_RETRIEVAL_QUERY_ROLES,
    RETRIEVAL_GENERIC_TOKENS,
    is_same_paper_title,
    meaningful_tokens,
    reference_title_similarity,
    unified_retrieval_pool,
)
from .relation import publication_cutoff_status


JsonModel = Callable[..., dict[str, Any]]


BASELINE_QUERY_SPECS = (
    {
        "query_shape": "short_phrase",
        "desired_results": 20,
        "search_field": "title",
    },
    {
        "query_shape": "semantic_sentence",
        "desired_results": 20,
        "search_field": "keyword",
    },
    {
        "query_shape": "fielded_phrase",
        "desired_results": 40,
        "search_field": "keyword",
    },
    {
        "query_shape": "semantic_sentence",
        "desired_results": 20,
        "search_field": "keyword",
    },
)

BASELINE_EVALUATION_CAP = 10
BASELINE_SEMANTIC_CANDIDATE_LIMIT = 60
BASELINE_SELECTOR_BATCH_SIZE = 20
BASELINE_SELECTOR_DEFAULT_WORKERS = 3
BASELINE_SELECTOR_MAX_ALLOWED_WORKERS = 3
BASELINE_SELECTOR_DEFAULT_BATCH_STRATEGY = "balanced"
BASELINE_SELECTOR_BATCH_STRATEGIES = frozenset({"balanced", "fixed"})
BASELINE_COMPARISON_PURPOSES = (
    "direct_performance",
    "mechanism_isolation",
    "budget_matched_policy",
    "novelty_boundary",
    "robustness_stress_test",
    "cross_task_adaptation",
    "efficiency_tradeoff",
)
_PURPOSE_FIELD_WEIGHTS = {
    "direct_performance": {
        "same_task": 0.38,
        "same_protocol": 0.38,
        "fair_baseline_usefulness": 0.16,
        "intervention_interface_match": 0.08,
    },
    "mechanism_isolation": {
        "mechanism_match": 0.40,
        "intervention_interface_match": 0.35,
        "claim_diagnostic_value": 0.25,
    },
    "budget_matched_policy": {
        "intervention_interface_match": 0.40,
        "claim_diagnostic_value": 0.35,
        "mechanism_match": 0.25,
    },
    "novelty_boundary": {
        "marginal_novelty": 0.60,
        "mechanism_match": 0.20,
        "claim_diagnostic_value": 0.20,
    },
    "robustness_stress_test": {
        "claim_diagnostic_value": 0.60,
        "intervention_interface_match": 0.25,
        "fair_baseline_usefulness": 0.15,
    },
    "cross_task_adaptation": {
        "mechanism_match": 0.40,
        "intervention_interface_match": 0.35,
        "claim_diagnostic_value": 0.25,
    },
    "efficiency_tradeoff": {
        "fair_baseline_usefulness": 0.50,
        "intervention_interface_match": 0.30,
        "claim_diagnostic_value": 0.20,
    },
}
_PURPOSE_LEVEL_FIT = {
    "high": 1.0,
    "medium": 0.6,
    "unknown": 0.0,
    "low": 0.0,
}
_PURPOSE_SCORE_SCALE = 30.0
_OBVIOUS_NON_DIRECT_TITLE_MARKERS = (
    "survey",
    "systematic review",
    "literature review",
    "dataset",
    "tutorial",
    "position paper",
)


def _configured_selector_workers() -> int:
    raw_value = os.environ.get(
        "BASELINE_SELECTOR_MAX_WORKERS",
        str(BASELINE_SELECTOR_DEFAULT_WORKERS),
    ).strip()
    try:
        workers = int(raw_value)
    except ValueError as exc:
        raise ValueError(
            "BASELINE_SELECTOR_MAX_WORKERS must be an integer from 1 to 3."
        ) from exc
    if not 1 <= workers <= BASELINE_SELECTOR_MAX_ALLOWED_WORKERS:
        raise ValueError(
            "BASELINE_SELECTOR_MAX_WORKERS must be an integer from 1 to 3."
        )
    return workers


def _configured_selector_batch_strategy() -> str:
    strategy = os.environ.get(
        "BASELINE_SELECTOR_BATCH_STRATEGY",
        BASELINE_SELECTOR_DEFAULT_BATCH_STRATEGY,
    ).strip().lower()
    if strategy not in BASELINE_SELECTOR_BATCH_STRATEGIES:
        raise ValueError(
            "BASELINE_SELECTOR_BATCH_STRATEGY must be 'balanced' or 'fixed'."
        )
    return strategy


def _selector_batches(
    payload: list[dict[str, Any]],
    *,
    strategy: str,
) -> list[list[dict[str, Any]]]:
    """Split a shortlist into contiguous, order-preserving selector batches."""
    if not payload:
        return []
    if strategy == "fixed":
        return [
            payload[start : start + BASELINE_SELECTOR_BATCH_SIZE]
            for start in range(0, len(payload), BASELINE_SELECTOR_BATCH_SIZE)
        ]
    if strategy != "balanced":
        raise ValueError(f"Unsupported selector batch strategy: {strategy}")

    batch_count = (
        len(payload) + BASELINE_SELECTOR_BATCH_SIZE - 1
    ) // BASELINE_SELECTOR_BATCH_SIZE
    smaller_size, larger_batch_count = divmod(len(payload), batch_count)
    batch_sizes = [
        smaller_size + (1 if index < larger_batch_count else 0)
        for index in range(batch_count)
    ]
    batches: list[list[dict[str, Any]]] = []
    start = 0
    for batch_size in batch_sizes:
        batches.append(payload[start : start + batch_size])
        start += batch_size
    return batches


_BASELINE_GATE_GENERIC_TOKENS = RETRIEVAL_GENERIC_TOKENS | {
    "approach",
    "approaches",
    "item",
    "items",
    "negative",
    "positive",
    "protocol",
    "ranking",
    "rankings",
    "recommendation",
    "recommendations",
    "recommender",
    "recommenders",
    "sampling",
    "sequential",
    "system",
    "systems",
    "user",
    "users",
}
_MECHANISM_DIVERSITY_GENERIC_TOKENS = _BASELINE_GATE_GENERIC_TOKENS | {
    "based",
    "combining",
    "direct",
    "experimental",
    "framework",
    "history",
    "long",
    "method",
    "methods",
    "model",
    "modeling",
    "models",
    "news",
    "rich",
    "same",
    "sequence",
    "sequences",
    "text",
}
_WITHDRAWN_OR_RETRACTED_MARKERS = (
    "withdrawn",
    "withdrawal",
    "retracted",
    "retraction",
    "desk rejected",
    "desk-rejected",
)
_INCOMPLETE_EVALUATION_MARKERS = (
    "incomplete experiment",
    "incomplete evaluation",
    "experiments incomplete",
    "evaluation incomplete",
)


def _normalized_phrase(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def _normalized_mechanism_branch(value: Any) -> str:
    """Collapse common mechanism aliases without using paper-specific names."""
    normalized = _normalized_phrase(value)
    tokens = set(normalized.split())
    if not tokens:
        return "unspecified"
    if "mamba" in tokens or "ssm" in tokens or {"state", "space"} <= tokens:
        return "state_space_sequence_model"
    if any(token.startswith("denois") for token in tokens):
        return "denoising"
    if any(token.startswith("retriev") for token in tokens):
        return "retrieval_augmentation"
    if any(token.startswith("diffus") for token in tokens):
        return "diffusion"
    if "profile" in tokens and ("sparse" in tokens or "memory" in tokens):
        return "sparse_profile"
    if any(token.startswith("compress") for token in tokens):
        return "compression"
    return "_".join(normalized.split()[:8])


def _task_relevance_priority(value: Any) -> int:
    return {
        "high": 0,
        "medium": 1,
        "low": 3,
    }.get(str(value or "").strip().lower(), 2)


def _model_rank_value(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


_SEMANTIC_LEVELS = {"high", "medium", "low", "unknown"}


def _semantic_level(value: Any) -> str:
    """Normalize selector evidence levels without treating prose as proof."""
    if isinstance(value, dict):
        value = value.get("level") or value.get("rating") or value.get("value")
    if isinstance(value, bool):
        return "high" if value else "low"
    normalized = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "yes": "high",
        "strong": "high",
        "direct": "high",
        "partial": "medium",
        "moderate": "medium",
        "weak": "low",
        "no": "low",
        "missing": "unknown",
        "uncertain": "unknown",
        "not_assessable": "unknown",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in _SEMANTIC_LEVELS else "unknown"


def _semantic_level_score(value: Any) -> int:
    return {"high": 3, "medium": 2, "unknown": 1, "low": 0}.get(
        _semantic_level(value), 1
    )


def _comparison_purposes(value: Any) -> list[str]:
    """Return unique, ordered purpose labels from selector JSON."""
    if isinstance(value, dict):
        raw_values = [key for key, enabled in value.items() if enabled]
    elif isinstance(value, (list, tuple, set)):
        raw_values = list(value)
    elif isinstance(value, str):
        raw_values = re.split(r"[,;|]", value)
    else:
        raw_values = []
    expanded_values: list[Any] = []
    for raw_value in raw_values:
        if isinstance(raw_value, str):
            expanded_values.extend(re.split(r"[,;|]", raw_value))
        else:
            expanded_values.append(raw_value)
    normalized = {
        str(item or "").strip().lower().replace("-", "_").replace(" ", "_")
        for item in expanded_values
    }
    return [purpose for purpose in BASELINE_COMPARISON_PURPOSES if purpose in normalized]


def _comparison_purpose_evidence(value: Any) -> dict[str, str]:
    """Keep concise evidence only for supported comparison-purpose labels."""
    evidence: dict[str, str] = {}
    if isinstance(value, dict):
        items = value.items()
    elif isinstance(value, list):
        items = (
            (item.get("purpose"), item.get("evidence"))
            for item in value
            if isinstance(item, dict)
        )
    else:
        items = ()
    for raw_purpose, raw_evidence in items:
        purposes = _comparison_purposes([raw_purpose])
        text = " ".join(str(raw_evidence or "").split())[:700]
        if purposes and text:
            evidence[purposes[0]] = text
    return evidence


def _comparison_purpose_utility_details(
    judgments: dict[str, Any],
) -> dict[str, Any]:
    """Score each grounded use by the evidence fields relevant to that use.

    A direct comparison is primarily about task/protocol comparability, whereas
    an adapted mechanism or policy comparison is primarily about mechanism,
    interface, and diagnostic value.  Taking only the strongest grounded
    purpose prevents many weak labels from outscoring one well-supported use.
    """
    raw_purposes = (
        judgments.get("grounded_comparison_purposes")
        if "grounded_comparison_purposes" in judgments
        else judgments.get("comparison_purposes")
    )
    purposes = _comparison_purposes(raw_purposes)
    if not purposes:
        return {
            "grounded_purposes": [],
            "purpose_scores": {},
            "field_contributions": {},
            "strongest_purpose": None,
            "strongest_purpose_score": 0.0,
            "multi_purpose_bonus": 0.0,
            "evidence_support": {
                "task": False,
                "protocol": False,
                "mechanism": False,
            },
            "total": 0.0,
        }

    purpose_scores: dict[str, float] = {}
    contribution_details: dict[str, dict[str, float]] = {}
    supplied_evidence = (
        judgments.get("evidence")
        if isinstance(judgments.get("evidence"), dict)
        else {}
    )
    purpose_evidence = _comparison_purpose_evidence(
        judgments.get("comparison_purpose_evidence")
    )
    task_supported = bool(
        judgments.get("objective_task_evidence_supported")
        or supplied_evidence.get("task_evidence")
    )
    protocol_supported = bool(
        judgments.get("objective_protocol_evidence_supported")
    )
    mechanism_supported = bool(
        judgments.get("objective_mechanism_evidence_supported")
        or supplied_evidence.get("mechanism_evidence")
    )
    for purpose in purposes:
        contributions: dict[str, float] = {}
        purpose_evidence_supported = bool(purpose_evidence.get(purpose))
        usefulness_supported = bool(
            supplied_evidence.get("usefulness_evidence")
            or purpose_evidence_supported
            or (
                judgments.get("objective_task_evidence_supported")
                and protocol_supported
            )
        )
        for field, weight in _PURPOSE_FIELD_WEIGHTS[purpose].items():
            fit = _PURPOSE_LEVEL_FIT[_semantic_level(judgments.get(field))]
            # A selector assertion of protocol equivalence is retained for
            # audit, but it cannot earn direct-comparison utility unless a
            # supplied dataset/metric/evaluation overlap supports it.
            if field == "same_protocol" and not protocol_supported:
                fit = 0.0
            elif field == "same_task" and not task_supported:
                fit = 0.0
            elif field == "mechanism_match" and not mechanism_supported:
                fit = 0.0
            elif field == "intervention_interface_match" and not (
                task_supported or mechanism_supported
            ):
                fit = 0.0
            elif field == "fair_baseline_usefulness" and not usefulness_supported:
                fit = 0.0
            elif field == "claim_diagnostic_value" and not (
                purpose_evidence_supported
                or usefulness_supported
                or mechanism_supported
            ):
                fit = 0.0
            elif field == "marginal_novelty" and not purpose_evidence_supported:
                fit = 0.0
            contributions[field] = _PURPOSE_SCORE_SCALE * weight * fit
        contribution_details[purpose] = {
            field: round(score, 3) for field, score in contributions.items()
        }
        purpose_scores[purpose] = round(sum(contributions.values()), 3)

    strongest_purpose = max(
        purposes,
        key=lambda purpose: (
            purpose_scores[purpose],
            -BASELINE_COMPARISON_PURPOSES.index(purpose),
        ),
    )
    strongest_score = purpose_scores[strongest_purpose]
    bounded_multi_purpose_bonus = min(1.5, 0.5 * (len(purposes) - 1))
    return {
        "grounded_purposes": purposes,
        "purpose_scores": purpose_scores,
        "field_contributions": contribution_details,
        "strongest_purpose": strongest_purpose,
        "strongest_purpose_score": round(strongest_score, 3),
        "multi_purpose_bonus": round(bounded_multi_purpose_bonus, 3),
        "evidence_support": {
            "task": task_supported,
            "protocol": protocol_supported,
            "mechanism": mechanism_supported,
        },
        "total": round(strongest_score + bounded_multi_purpose_bonus, 3),
    }


def _comparison_purpose_utility(judgments: dict[str, Any]) -> float:
    """Return the strongest purpose-conditioned utility plus a bounded bonus."""
    return float(_comparison_purpose_utility_details(judgments)["total"])


def _selector_semantic_judgments(
    item: dict[str, Any],
    verification: dict[str, Any],
    *,
    allow_legacy_purpose_inference: bool = True,
) -> dict[str, Any]:
    """Preserve selector judgments while grounding Core protocol claims.

    Legacy callers may omit the new fields.  In that case only deterministic
    evidence already visible in the candidate/plan can supply a high rating.
    A model's unsupported `same_protocol=high` is retained for audit but cannot
    pass the Core hard gate.
    """
    objective_task = bool(verification.get("task_match"))
    objective_protocol = bool(verification.get("protocol_overlap"))
    objective_mechanism = bool(verification.get("mechanism_overlap"))

    same_task = _semantic_level(item.get("same_task"))
    same_protocol = _semantic_level(item.get("same_protocol"))
    mechanism_match = _semantic_level(item.get("mechanism_match"))
    interface_match = _semantic_level(item.get("intervention_interface_match"))
    usefulness = _semantic_level(item.get("fair_baseline_usefulness"))
    diagnostic_value = _semantic_level(item.get("claim_diagnostic_value"))
    marginal_novelty = _semantic_level(item.get("marginal_novelty"))

    if same_task == "unknown" and objective_task:
        same_task = "high"
    if same_protocol == "unknown" and objective_protocol:
        same_protocol = "high"
    if mechanism_match == "unknown" and objective_mechanism:
        mechanism_match = "high"
    if interface_match == "unknown":
        interface_match = "high" if objective_mechanism else "medium"
    if usefulness == "unknown" and objective_task and objective_protocol:
        usefulness = "high"
    if diagnostic_value == "unknown" and objective_task:
        diagnostic_value = "medium"
    if marginal_novelty == "unknown":
        marginal_novelty = "medium"

    purpose_field_present = "comparison_purposes" in item
    purpose_evidence_field_present = "comparison_purpose_evidence" in item
    purposes = _comparison_purposes(item.get("comparison_purposes"))
    purpose_source = "selector"
    if not purpose_field_present and allow_legacy_purpose_inference:
        # Backward compatibility for stored v0.4.x selector responses and
        # genuinely legacy `selected` responses. Complete `assessments`
        # responses must satisfy the explicit comparison-purpose contract.
        purpose_source = "legacy_semantic_inference"
        if (
            same_task in {"high", "medium"}
            and same_protocol != "low"
            and usefulness in {"high", "medium"}
        ):
            purposes = ["direct_performance"]
    purpose_evidence = _comparison_purpose_evidence(
        item.get("comparison_purpose_evidence")
    )
    evidence_grounded_purposes = (
        list(purposes)
        if purpose_source == "legacy_semantic_inference"
        else [purpose for purpose in purposes if purpose_evidence.get(purpose)]
    )
    strong_evidence = (
        verification.get("strong_evidence")
        if isinstance(verification.get("strong_evidence"), dict)
        else {}
    )
    exact_citation_supported = bool(
        strong_evidence.get("exact_bibliography_verification")
    )
    protocol_supported = bool(
        strong_evidence.get("specific_dataset_or_metric_match")
        or verification.get("protocol_overlap")
    )
    mechanism_supported = bool(
        strong_evidence.get("non_generic_mechanism_match")
        or verification.get("mechanism_overlap")
    )
    task_supported = bool(verification.get("task_match"))
    objective_purpose_support = {
        "direct_performance": task_supported
        and (protocol_supported or exact_citation_supported),
        "mechanism_isolation": mechanism_supported,
        "budget_matched_policy": mechanism_supported or protocol_supported,
        "novelty_boundary": mechanism_supported or exact_citation_supported,
        "robustness_stress_test": mechanism_supported or protocol_supported,
        "cross_task_adaptation": mechanism_supported,
        "efficiency_tradeoff": mechanism_supported or protocol_supported,
    }
    if purpose_source == "legacy_semantic_inference":
        # Frozen v0.4.x `selected` responses predate the explicit evidence
        # contract. Preserve their direct-purpose compatibility while keeping
        # the independent Core protocol/full-text gates unchanged.
        objective_purpose_support["direct_performance"] = bool(
            same_task in {"high", "medium"}
            and same_protocol != "low"
            and usefulness in {"high", "medium"}
        )
    grounded_purposes = [
        purpose
        for purpose in evidence_grounded_purposes
        if objective_purpose_support.get(purpose, False)
    ]
    raw_adaptation = item.get("adaptation_required")
    adaptation_required = (
        raw_adaptation is True
        or str(raw_adaptation or "").strip().lower() in {"1", "true", "yes"}
        or "cross_task_adaptation" in grounded_purposes
        or (same_task == "low" and bool(grounded_purposes))
    )
    adaptation_note = " ".join(
        str(item.get("adaptation_note") or "").split()
    )[:700]
    if adaptation_required and not adaptation_note:
        adaptation_note = (
            "Task formulation, inputs, outputs, and evaluation budget require "
            "explicit adaptation verification."
        )

    evidence = {
        key: " ".join(str(item.get(key) or "").split())[:700]
        for key in (
            "task_evidence",
            "protocol_evidence",
            "mechanism_evidence",
            "usefulness_evidence",
        )
        if str(item.get(key) or "").strip()
    }
    return {
        "same_task": same_task,
        "same_protocol": same_protocol,
        "mechanism_match": mechanism_match,
        "intervention_interface_match": interface_match,
        "fair_baseline_usefulness": usefulness,
        "claim_diagnostic_value": diagnostic_value,
        "marginal_novelty": marginal_novelty,
        "comparison_purposes": purposes,
        "evidence_grounded_comparison_purposes": evidence_grounded_purposes,
        "grounded_comparison_purposes": grounded_purposes,
        "ungrounded_comparison_purposes": [
            purpose for purpose in purposes if purpose not in grounded_purposes
        ],
        "objective_comparison_purpose_support": objective_purpose_support,
        "comparison_purpose_evidence": purpose_evidence,
        "comparison_purpose_source": purpose_source,
        "comparison_purpose_contract_required": (
            not allow_legacy_purpose_inference
        ),
        "comparison_purpose_contract_complete": (
            purpose_field_present and purpose_evidence_field_present
        ),
        "adaptation_required": adaptation_required,
        "adaptation_note": adaptation_note,
        "objective_task_evidence_supported": objective_task,
        "objective_protocol_evidence_supported": objective_protocol,
        "objective_mechanism_evidence_supported": objective_mechanism,
        "evidence": evidence,
    }


def _availability_evidence_warnings(candidate: dict[str, Any]) -> list[str]:
    """Return deterministic availability warnings visible in source metadata."""
    fields = (
        "title",
        "status",
        "publication_status",
        "submission_status",
        "venue",
        "source",
        "availability_evidence",
        "bibliography_entry",
        "raw_reference",
    )
    evidence = " ".join(str(candidate.get(field) or "") for field in fields).casefold()
    warnings: list[str] = []
    if candidate.get("withdrawn") is True or candidate.get("retracted") is True:
        warnings.append("withdrawn_or_retracted")
    elif any(marker in evidence for marker in _WITHDRAWN_OR_RETRACTED_MARKERS):
        warnings.append("withdrawn_or_retracted")
    if any(marker in evidence for marker in _INCOMPLETE_EVALUATION_MARKERS):
        warnings.append("incomplete_experimental_evidence")
    return list(dict.fromkeys(warnings))


def _core_availability_blockers(
    candidate: dict[str, Any], selection_item: dict[str, Any]
) -> list[str]:
    """Return explicit evidence that prevents a candidate from entering Core."""
    blockers = _availability_evidence_warnings(candidate)
    runnability = str(selection_item.get("runnability") or "").strip().lower()
    if runnability in {"not_runnable", "unrunnable", "unavailable"}:
        blockers.append("model_marked_not_runnable")
    elif runnability != "runnable":
        blockers.append("runnability_not_explicit_runnable")
    return list(dict.fromkeys(blockers))


def _matches_current_baseline(
    candidate: dict[str, Any], retrieval_plan: dict[str, Any]
) -> bool:
    """Return true only for a visible current-baseline title/name match."""
    title = str(candidate.get("title") or "").strip()
    normalized_title = _normalized_phrase(title)
    raw_baselines = retrieval_plan.get("current_baselines")
    baselines = raw_baselines if isinstance(raw_baselines, list) else []
    for raw_baseline in baselines:
        baseline = str(raw_baseline or "").strip()
        normalized_baseline = _normalized_phrase(baseline)
        if not normalized_baseline:
            continue
        if reference_title_similarity(title, baseline) >= 0.9:
            return True
        # Exact phrase/name matching is deliberately conservative. A one-token
        # name must still be at least four characters to avoid incidental hits.
        if len(normalized_baseline) >= 4 and re.search(
            rf"(?:^| ){re.escape(normalized_baseline)}(?: |$)", normalized_title
        ):
            return True
    return False


def _missing_status(
    candidate: dict[str, Any], retrieval_plan: dict[str, Any]
) -> str:
    if _matches_current_baseline(candidate, retrieval_plan):
        return "already_compared"
    role = str(candidate.get("retrieval_role") or "")
    if role == BASELINE_BIBLIOGRAPHY_ROLE:
        return "cited_not_compared"
    if (
        role in BASELINE_RELATION_ROLES
        and str(candidate.get("relation_direction") or "")
        == "target_references_candidate"
    ):
        return "cited_not_compared"
    # Broad search does not prove absence from the bibliography, so `uncited`
    # is never inferred here.
    return "unknown"


def _selection_evidence(candidate: dict[str, Any]) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "retrieval_role": str(candidate.get("retrieval_role") or ""),
        "source": str(candidate.get("source") or ""),
        "published": str(candidate.get("published") or ""),
        "query": str(candidate.get("query") or ""),
        "summary_excerpt": str(candidate.get("summary") or "")[:500],
    }
    for key in (
        "bibliography_title",
        "bibliography_title_similarity",
        "citation_context",
        "bibliography_reason",
        "bibliography_entry",
        "bibliography_tei_id",
        "bibliography_authors",
        "bibliography_year",
        "citation_ref_target",
        "citation_ref_label",
        "local_citation_before_review_cutoff",
        "method_name",
        "experiment_comparison_status",
        "mechanism_branch",
        "task_protocol_relevance",
        "citation_link_method",
        "evidence_chain",
        "relation_direction",
        "cutoff_status",
        "aminer_cutoff_status",
        "aminer_publication_date_precision",
        "availability_evidence",
        "publication_status",
        "submission_status",
        "venue",
    ):
        if candidate.get(key) not in (None, ""):
            evidence[key] = candidate.get(key)
    return evidence


def _candidate_evidence_profile(candidate: dict[str, Any]) -> dict[str, Any]:
    """Classify candidate-side evidence without treating metadata as full text."""
    sources: list[str] = []
    if any(
        candidate.get(key)
        for key in ("title", "source", "url", "aminer_pub_id", "doi")
    ):
        sources.append("discovery_metadata")
    if str(candidate.get("summary") or "").strip():
        # AMiner paper_detail enriches this same abstract/metadata field.  It is
        # deliberately not a candidate-full-text source.
        sources.append("candidate_abstract")
    if str(candidate.get("bibliography_entry") or "").strip():
        sources.append("target_bibliography_entry")
    if str(candidate.get("citation_context") or "").strip():
        sources.append("target_citation_context")

    declared_sources = candidate.get("evidence_sources")
    if isinstance(declared_sources, (list, tuple, set)):
        for raw_source in declared_sources:
            source = " ".join(str(raw_source or "").split())[:160]
            if source and source not in sources:
                sources.append(source)

    fulltext_evidence = candidate.get("candidate_fulltext_evidence")
    if not fulltext_evidence:
        fulltext_evidence = candidate.get("candidate_fulltext_sections")
    fulltext_source = " ".join(
        str(candidate.get("candidate_fulltext_source") or "").split()
    )[:300]
    fulltext_declared = candidate.get("candidate_fulltext_verified") is True
    fulltext_verified = bool(
        fulltext_declared and fulltext_source and fulltext_evidence
    )
    if fulltext_verified:
        sources.append("candidate_structured_fulltext")
        sources.append(f"candidate_fulltext_source:{fulltext_source}")

    if fulltext_verified:
        level = "fulltext_verified"
    elif any(
        source in {
            "candidate_abstract",
            "target_bibliography_entry",
            "target_citation_context",
        }
        for source in sources
    ):
        level = "abstract_screened"
    else:
        level = "discovered"
    return {
        "evidence_level": level,
        "evidence_sources": list(dict.fromkeys(sources)),
        "fulltext_verified": fulltext_verified,
    }


def _extended_hard_gate(
    candidate: dict[str, Any],
    retrieval_plan: dict[str, Any],
    *,
    local_title: str,
    review_as_of: str,
) -> tuple[bool, dict[str, Any]]:
    """Admit only medium-confidence, directly comparable manual checks.

    This is intentionally a gate rather than a rank-only backfill. It can leave
    the evaluation view below its cap when task/protocol evidence is insufficient.
    """
    title = str(candidate.get("title") or "").strip()
    normalized_title = _normalized_phrase(title)
    role = str(candidate.get("retrieval_role") or "")
    result: dict[str, Any] = {
        "gate": "deterministic_task_protocol_v2",
        "task_match": False,
        "protocol_match": False,
        "objective_exclusion": False,
        "decision": "low_confidence_internal_only",
        "reason": "",
        **_candidate_evidence_profile(candidate),
    }
    if not title or role not in BASELINE_DIRECT_RETRIEVAL_ROLES:
        result["objective_exclusion"] = True
        result["reason"] = "Missing title or unsupported retrieval role."
        return False, result
    if local_title and is_same_paper_title(title, local_title):
        result["objective_exclusion"] = True
        result["reason"] = "Candidate matches the uploaded manuscript."
        return False, result
    if publication_cutoff_status(
        str(candidate.get("published") or ""), review_as_of
    ) == "after_cutoff":
        result["objective_exclusion"] = True
        result["reason"] = "Candidate was published after the review cutoff."
        return False, result
    if any(marker in normalized_title for marker in _OBVIOUS_NON_DIRECT_TITLE_MARKERS):
        result["objective_exclusion"] = True
        result["reason"] = "Title indicates a survey, dataset, tutorial, or other non-method item."
        return False, result
    if _matches_current_baseline(candidate, retrieval_plan):
        result["objective_exclusion"] = True
        result["reason"] = "Candidate is already listed as a current experimental baseline."
        result["missing_status"] = "already_compared"
        return False, result

    task_only_text = str(retrieval_plan.get("task") or "")
    method_text = str(retrieval_plan.get("method_family") or "")
    task_text = f"{task_only_text} {method_text}"
    datasets = retrieval_plan.get("datasets_or_benchmarks")
    dataset_values = (
        [str(item) for item in datasets if str(item).strip()]
        if isinstance(datasets, list)
        else []
    )
    protocol_text = " ".join(
        [*dataset_values, str(retrieval_plan.get("evaluation_setting") or "")]
    )
    plan_text = f"{task_text} {protocol_text}"
    candidate_text = " ".join(
        str(candidate.get(key) or "")
        for key in (
            "title",
            "summary",
            "bibliography_reason",
            "citation_context",
        )
    )
    task_tokens = meaningful_tokens(task_text) - _BASELINE_GATE_GENERIC_TOKENS
    specific_task_tokens = (
        meaningful_tokens(task_only_text) - _BASELINE_GATE_GENERIC_TOKENS
    )
    mechanism_tokens = meaningful_tokens(method_text) - _BASELINE_GATE_GENERIC_TOKENS
    protocol_tokens = meaningful_tokens(protocol_text) - _BASELINE_GATE_GENERIC_TOKENS
    plan_tokens = meaningful_tokens(plan_text) - _BASELINE_GATE_GENERIC_TOKENS
    candidate_tokens = meaningful_tokens(candidate_text) - _BASELINE_GATE_GENERIC_TOKENS
    title_tokens = meaningful_tokens(title) - _BASELINE_GATE_GENERIC_TOKENS
    task_overlap = task_tokens & candidate_tokens
    specific_task_overlap = specific_task_tokens & candidate_tokens
    mechanism_overlap = mechanism_tokens & candidate_tokens
    protocol_overlap = protocol_tokens & candidate_tokens
    plan_overlap = plan_tokens & candidate_tokens
    lexical_score = int(str(candidate.get("relevance_score") or "0") or 0)
    distinctive = str(candidate.get("has_distinctive_title_overlap") or "").lower() == "true"
    exact_verified = bool(
        role == BASELINE_BIBLIOGRAPHY_ROLE
        and float(candidate.get("bibliography_title_similarity") or 0) >= 0.94
        and candidate.get("bibliography_entry")
        and candidate.get("citation_context")
    )
    concrete_protocol_match = bool(protocol_overlap)
    specific_task_match = len(specific_task_overlap) >= 2
    # Task-language overlap can support same-task screening, but it is not
    # objective evidence for a mechanism comparison.  Keep the two signals
    # separate so model-authored mechanism/cross-task prose cannot turn a
    # merely topical candidate into a grounded comparison purpose.
    mechanism_match = bool(mechanism_overlap)
    strong_evidence = (
        exact_verified
        or concrete_protocol_match
        or mechanism_match
        or specific_task_match
    )
    task_match = bool(task_overlap or title_tokens & task_tokens) or exact_verified
    protocol_match = strong_evidence

    result.update(
        {
            "task_match": task_match,
            "protocol_match": protocol_match,
            "task_overlap": sorted(task_overlap),
            "specific_task_overlap": sorted(specific_task_overlap),
            "mechanism_overlap": sorted(mechanism_overlap),
            "protocol_overlap": sorted(protocol_overlap),
            "plan_overlap_count": len(plan_overlap),
            "lexical_score": lexical_score,
            "distinctive_title_overlap": distinctive,
            "strong_evidence": {
                "exact_bibliography_verification": exact_verified,
                "specific_dataset_or_metric_match": concrete_protocol_match,
                "non_generic_mechanism_match": mechanism_match,
                "specific_task_match": specific_task_match,
            },
        }
    )
    if not task_match:
        result["reason"] = (
            "Insufficient non-generic evidence that the candidate solves the same "
            "task; generic task words alone are ignored."
        )
        return False, result
    if not protocol_match:
        result["reason"] = (
            "Only generic task words overlap; no exact cited-title proof, concrete "
            "dataset/metric match, or non-generic mechanism match was found."
        )
        return False, result
    result["decision"] = "medium_confidence_extended"
    result["reason"] = (
        "Passed deterministic same-task and comparable-protocol evidence gates; "
        "manual verification is still required."
    )
    return True, result


def _decorate_two_tier_candidate(
    candidate: dict[str, Any],
    *,
    retrieval_plan: dict[str, Any],
    tier: str,
    confidence: str,
    reason: str,
    verification: dict[str, Any],
    fill_source: str,
) -> dict[str, Any]:
    entry = dict(candidate)
    verification_payload = dict(verification)
    if not isinstance(
        verification_payload.get("selector_semantic_judgments"), dict
    ):
        verification_payload["selector_semantic_judgments"] = (
            _selector_semantic_judgments({}, verification_payload)
        )
    availability_warnings = _availability_evidence_warnings(candidate)
    if availability_warnings:
        verification_payload["availability_warnings"] = availability_warnings
        verification_payload["requires_human_availability_check"] = True
    semantic_judgments = verification_payload.get("selector_semantic_judgments")
    if not isinstance(semantic_judgments, dict):
        semantic_judgments = {}
    evidence_profile = _candidate_evidence_profile(candidate)
    # Candidate-side provenance is authoritative.  Selector prose and API
    # paper_detail metadata cannot upgrade an abstract to verified full text.
    verification_payload.update(evidence_profile)
    comparison_purposes = _comparison_purposes(
        semantic_judgments.get("grounded_comparison_purposes")
        if "grounded_comparison_purposes" in semantic_judgments
        else semantic_judgments.get("comparison_purposes")
    )
    purpose_evidence = _comparison_purpose_evidence(
        semantic_judgments.get("comparison_purpose_evidence")
    )
    entry.update(
        {
            "semantic_relevance": (
                "direct_baseline_candidate"
                if tier == "core"
                else "extended_candidate_to_check"
            ),
            "comparison_role": "direct_baseline",
            "selection_reason": reason,
            "tier": tier,
            "confidence": confidence,
            "candidate_label": (
                "candidate_to_check"
                if evidence_profile["fulltext_verified"]
                else "candidate_to_verify"
            ),
            "comparison_purposes": comparison_purposes,
            "comparison_purpose_evidence": purpose_evidence,
            "adaptation_required": bool(
                semantic_judgments.get("adaptation_required")
            ),
            "adaptation_note": str(
                semantic_judgments.get("adaptation_note") or ""
            ),
            **evidence_profile,
            "missing_status": _missing_status(candidate, retrieval_plan),
            "verification": verification_payload,
            "selection_evidence": _selection_evidence(candidate),
            "fill_source": fill_source,
        }
    )
    mechanism_branch = " ".join(
        str(candidate.get("mechanism_branch") or "").split()
    )[:160]
    task_protocol_relevance = (
        str(candidate.get("task_protocol_relevance") or "").strip().lower()[:32]
    )
    if mechanism_branch:
        entry["mechanism_branch"] = mechanism_branch
        entry["mechanism_branch_normalized"] = _normalized_mechanism_branch(
            mechanism_branch
        )
    if task_protocol_relevance:
        entry["task_protocol_relevance"] = task_protocol_relevance
    runnability = str(candidate.get("runnability") or "").strip().lower()
    if not runnability and tier == "extended":
        runnability = "uncertain"
    if runnability:
        entry["runnability"] = runnability
    if availability_warnings:
        entry["availability_warnings"] = availability_warnings
    return entry


def _mechanism_diversity_reorder(
    model_selected: list[dict[str, Any]],
    *,
    retrieval_plan: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build a diagnostic-only branch preview for model-verified Core candidates.

    This legacy preview is retained for backward-compatible diagnostics. It does
    not choose the final evaluation view; final selection is semantic-utility
    first and uses branch only to break exact utility ties.
    """
    plan_text = " ".join(
        str(retrieval_plan.get(key) or "") for key in ("method_family", "task")
    )
    mechanism_tokens = (
        meaningful_tokens(plan_text) - _MECHANISM_DIVERSITY_GENERIC_TOKENS
    )
    candidate_tokens: dict[str, set[str]] = {}
    eligible: list[dict[str, Any]] = []
    for candidate in model_selected:
        title = str(candidate.get("title") or "").strip()
        key = _normalized_phrase(title)
        if not key:
            continue
        evidence_text = " ".join(
            str(candidate.get(field) or "")
            for field in (
                "title",
                "summary",
                "citation_context",
            )
        )
        candidate_tokens[key] = (
            meaningful_tokens(evidence_text) - _MECHANISM_DIVERSITY_GENERIC_TOKENS
        )
        eligible.append(candidate)

    document_frequency = {
        token: sum(token in tokens for tokens in candidate_tokens.values())
        for token in mechanism_tokens
    }
    frequency_cap = max(1, (len(eligible) + 1) // 2)
    informative_tokens = {
        token
        for token in mechanism_tokens
        if 0 < document_frequency.get(token, 0) <= frequency_cap
    }
    overlaps = {
        key: tokens & informative_tokens for key, tokens in candidate_tokens.items()
    }
    model_rank = {
        _normalized_phrase(item.get("title")): index
        for index, item in enumerate(model_selected)
    }
    branch_queues: dict[str, list[dict[str, Any]]] = {}
    branch_labels: dict[str, str] = {}
    for candidate in eligible:
        title_key = _normalized_phrase(candidate.get("title"))
        explicit_label = " ".join(
            str(candidate.get("mechanism_branch") or "").split()
        )[:160]
        lexical_terms = sorted(overlaps.get(title_key, set()))
        if explicit_label:
            branch_key = _normalized_mechanism_branch(explicit_label)
            branch_label = explicit_label
        elif lexical_terms:
            branch_key = _normalized_mechanism_branch(" ".join(lexical_terms))
            branch_label = " / ".join(lexical_terms)
        else:
            branch_key = "unspecified"
            branch_label = "unspecified"
        entry = dict(candidate)
        entry["mechanism_coverage"] = lexical_terms
        entry["mechanism_branch_normalized"] = branch_key
        if explicit_label:
            entry["mechanism_branch"] = explicit_label
        branch_queues.setdefault(branch_key, []).append(entry)
        branch_labels.setdefault(branch_key, branch_label)

    for queue in branch_queues.values():
        queue.sort(
            key=lambda item: (
                _task_relevance_priority(item.get("task_protocol_relevance")),
                _model_rank_value(
                    item.get("model_selection_rank"),
                    model_rank.get(_normalized_phrase(item.get("title")), 10_000),
                ),
            )
        )

    chosen: list[dict[str, Any]] = []
    covered: set[str] = set()
    branch_order = sorted(
        branch_queues,
        key=lambda branch: (
            _task_relevance_priority(
                branch_queues[branch][0].get("task_protocol_relevance")
            ),
            _model_rank_value(
                branch_queues[branch][0].get("model_selection_rank"),
                model_rank.get(
                    _normalized_phrase(branch_queues[branch][0].get("title")),
                    10_000,
                ),
            ),
        ),
    )
    while len(chosen) < min(BASELINE_EVALUATION_CAP, len(model_selected)):
        progressed = False
        for branch_key in branch_order:
            queue = branch_queues[branch_key]
            if not queue:
                continue
            entry = queue.pop(0)
            chosen.append(entry)
            covered.update(entry.get("mechanism_coverage") or [])
            progressed = True
            if len(chosen) >= BASELINE_EVALUATION_CAP:
                break
        if not progressed:
            break

    only_model_selected = all(
        _normalized_phrase(item.get("title")) in model_rank for item in chosen
    )
    original_titles = [str(item.get("title") or "") for item in model_selected]
    reordered_titles = [str(item.get("title") or "") for item in chosen]
    return chosen, {
        "enabled": bool(len(branch_queues) > 1 or informative_tokens),
        "applied": reordered_titles != original_titles[: len(reordered_titles)],
        "plan_mechanism_terms": sorted(informative_tokens),
        "covered_mechanism_terms": sorted(covered),
        "covered_mechanism_branches": list(
            dict.fromkeys(
                str(item.get("mechanism_branch_normalized") or "unspecified")
                for item in chosen
            )
        ),
        "normalized_branch_count": len(branch_queues),
        "normalized_branch_labels": {
            branch: branch_labels[branch] for branch in branch_order
        },
        "candidate_set_preserved": set(reordered_titles) == set(original_titles),
        "only_model_selected_candidates": only_model_selected,
        "model_verified_pool_size": len(model_selected),
        "retained_after_cap": len(chosen),
        "used_for_final_selection": False,
        "original_titles": original_titles,
        "reordered_titles": reordered_titles,
        "policy": (
            "Diagnostic-only legacy branch preview. Final Top-10 selection uses "
            "semantic utility and branch only as an exact-utility tie-break."
        ),
    }


def _extended_candidate_order_key(item: dict[str, Any]) -> tuple[Any, ...]:
    """Break equal-utility ties with objective evidence and stable input rank."""
    verification = (
        item.get("verification")
        if isinstance(item.get("verification"), dict)
        else {}
    )
    strong = (
        verification.get("strong_evidence")
        if isinstance(verification.get("strong_evidence"), dict)
        else {}
    )
    exact_verified = bool(strong.get("exact_bibliography_verification"))
    strong_count = sum(bool(value) for value in strong.values())
    cited_not_compared = bool(
        item.get("missing_status") == "cited_not_compared"
        or item.get("retrieval_role") == BASELINE_BIBLIOGRAPHY_ROLE
    )
    availability_warnings = list(item.get("availability_warnings") or [])
    try:
        lexical_score = int(
            str(
                verification.get("lexical_score")
                if verification.get("lexical_score") not in (None, "")
                else item.get("relevance_score") or "0"
            )
        )
    except (TypeError, ValueError):
        lexical_score = 0
    mechanism_overlap_count = len(verification.get("mechanism_overlap") or [])
    specific_task_overlap_count = len(
        verification.get("specific_task_overlap") or []
    )
    try:
        plan_overlap_count = int(verification.get("plan_overlap_count") or 0)
    except (TypeError, ValueError):
        plan_overlap_count = 0
    evidence_level_priority = {
        "fulltext_verified": 2,
        "abstract_screened": 1,
        "discovered": 0,
    }.get(str(item.get("evidence_level") or ""), 0)
    return (
        -_candidate_semantic_utility(item),
        -evidence_level_priority,
        -int(cited_not_compared),
        int(bool(availability_warnings)),
        -int(exact_verified),
        -strong_count,
        -mechanism_overlap_count,
        -specific_task_overlap_count,
        -plan_overlap_count,
        -lexical_score,
        _model_rank_value(item.get("model_selection_rank"), 10_000),
        _model_rank_value(item.get("_selection_input_rank"), 10_000),
        _normalized_phrase(item.get("title")),
    )


def _candidate_semantic_utility_details(item: dict[str, Any]) -> dict[str, Any]:
    """Return a purpose-conditioned, evidence-aware utility breakdown."""
    verification = (
        item.get("verification")
        if isinstance(item.get("verification"), dict)
        else {}
    )
    semantic = (
        verification.get("selector_semantic_judgments")
        if isinstance(verification.get("selector_semantic_judgments"), dict)
        else {}
    )
    purpose_details = _comparison_purpose_utility_details(semantic)
    relevance_score = {
        "high": 6.0,
        "medium": 3.0,
        "missing": 0.0,
        "low": -4.0,
    }.get(str(item.get("task_protocol_relevance") or "missing").lower(), 0.0)
    strong = (
        verification.get("strong_evidence")
        if isinstance(verification.get("strong_evidence"), dict)
        else {}
    )
    exact_verified = bool(strong.get("exact_bibliography_verification"))
    cited_not_compared = bool(
        item.get("missing_status") == "cited_not_compared"
        or item.get("retrieval_role") == BASELINE_BIBLIOGRAPHY_ROLE
    )
    availability_warnings = list(item.get("availability_warnings") or [])
    warning_penalty = (
        12.0 + 4.0 * (len(availability_warnings) - 1)
        if availability_warnings
        else 0.0
    )
    runnability = str(item.get("runnability") or "uncertain").strip().lower()
    runnability_penalty = (
        10.0
        if runnability in {"not_runnable", "unrunnable", "unavailable"}
        else 0.0
        if runnability == "runnable"
        else 1.0
    )
    evidence_level_score = {
        "fulltext_verified": 3.0,
        "abstract_screened": 1.0,
        "discovered": 0.0,
    }.get(str(item.get("evidence_level") or ""), 0.0)
    try:
        lexical = min(20, max(0, int(item.get("relevance_score") or 0)))
    except (TypeError, ValueError):
        lexical = 0
    components = {
        "purpose_conditioned": float(purpose_details["total"]),
        "task_protocol_relevance": relevance_score,
        "exact_bibliography_verification": 4.0 * int(exact_verified),
        "cited_not_compared": 2.0 * int(cited_not_compared),
        "structured_evidence": float(
            min(3, sum(bool(value) for value in strong.values()))
        ),
        "evidence_maturity": evidence_level_score,
        "lexical_support": round(0.05 * lexical, 3),
        "availability_warning_penalty": -warning_penalty,
        "runnability_penalty": -runnability_penalty,
    }
    return {
        "total": round(sum(components.values()), 3),
        "components": components,
        "purpose": purpose_details,
    }


def _candidate_semantic_utility(item: dict[str, Any]) -> float:
    """Return purpose-conditioned utility; mechanism diversity is applied later."""
    return float(_candidate_semantic_utility_details(item)["total"])


def _extended_diversity_reorder(
    eligible_extended: list[dict[str, Any]],
    *,
    limit: int,
    precovered_branches: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Rank by utility; branch diversity only breaks near-equal utility ties."""
    precovered = set(precovered_branches or set())
    prepared: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    canonical_titles: dict[str, str] = {}
    identity_deduplications: list[dict[str, Any]] = []
    for item in eligible_extended:
        title_key = _normalized_phrase(item.get("title"))
        if not title_key:
            continue
        if title_key in seen_titles:
            raw_input_rank = item.get("_selection_input_rank")
            try:
                input_rank = int(raw_input_rank)
            except (TypeError, ValueError):
                input_rank = 0
            verification = (
                item.get("verification")
                if isinstance(item.get("verification"), dict)
                else {}
            )
            semantic_judgments = (
                verification.get("selector_semantic_judgments")
                if isinstance(
                    verification.get("selector_semantic_judgments"), dict
                )
                else {}
            )
            identity_deduplications.append(
                {
                    "candidate_id": (
                        f"R{input_rank}"
                        if input_rank > 0
                        else str(item.get("candidate_id") or "")
                    ),
                    "title": str(item.get("title") or ""),
                    "canonical_title": canonical_titles[title_key],
                    "decision": "eligible_duplicate_merged_before_ranking",
                    "reason": (
                        "Normalized title identity matches an earlier eligible "
                        "candidate; the duplicate is merged before utility ranking."
                    ),
                    "comparison_purposes": list(
                        item.get("comparison_purposes") or []
                    ),
                    "comparison_purpose_evidence": dict(
                        item.get("comparison_purpose_evidence") or {}
                    ),
                    "selector_semantic_judgments": semantic_judgments,
                }
            )
            continue
        entry = dict(item)
        branch_label = " ".join(
            str(entry.get("mechanism_branch") or "").split()
        )[:160]
        if not branch_label:
            verification = (
                entry.get("verification")
                if isinstance(entry.get("verification"), dict)
                else {}
            )
            overlap = verification.get("mechanism_overlap")
            branch_label = " ".join(
                str(value) for value in overlap or [] if str(value).strip()
            )
        branch_key = _normalized_mechanism_branch(branch_label)
        if not branch_label or branch_key == "unspecified":
            branch_label = "unspecified"
            branch_key = "unspecified"
        entry["mechanism_branch"] = branch_label
        entry["mechanism_branch_normalized"] = branch_key
        relevance = str(entry.get("task_protocol_relevance") or "").strip().lower()
        entry["task_protocol_relevance"] = relevance or "missing"
        if not str(entry.get("runnability") or "").strip():
            entry["runnability"] = "uncertain"
        prepared.append(entry)
        seen_titles.add(title_key)
        canonical_titles[title_key] = str(entry.get("title") or "")

    pool_branch_counts: dict[str, int] = {}
    for entry in prepared:
        branch = str(entry.get("mechanism_branch_normalized") or "unspecified")
        pool_branch_counts[branch] = pool_branch_counts.get(branch, 0) + 1

    branch_selected_counts = {
        branch: 1 for branch in precovered if branch != "unspecified"
    }
    remaining = list(prepared)
    ranked: list[dict[str, Any]] = []
    candidate_utility_trace: list[dict[str, Any]] = []
    utility_tie_band = 2.0
    while remaining:
        utilities = [_candidate_semantic_utility(entry) for entry in remaining]
        max_utility = max(utilities)
        tied = [
            (index, entry, utility)
            for index, (entry, utility) in enumerate(zip(remaining, utilities))
            if max_utility - utility <= utility_tie_band
        ]
        index, entry, _utility = min(
            tied,
            key=lambda pair: (
                branch_selected_counts.get(
                    str(
                        pair[1].get("mechanism_branch_normalized") or "unspecified"
                    ),
                    0,
                )
                > 0
                if str(
                    pair[1].get("mechanism_branch_normalized") or "unspecified"
                )
                != "unspecified"
                else True,
                -pair[2],
                _extended_candidate_order_key(pair[1]),
                pair[0],
            ),
        )
        branch = str(entry.get("mechanism_branch_normalized") or "unspecified")
        utility_details = _candidate_semantic_utility_details(entry)
        base_utility = float(utility_details["total"])
        branch_diversity_eligible = branch != "unspecified"
        branch_previously_selected = bool(branch_selected_counts.get(branch, 0))
        ranked.append(entry)
        raw_input_rank = entry.get("_selection_input_rank")
        try:
            input_rank = int(raw_input_rank)
        except (TypeError, ValueError):
            input_rank = 0
        verification = (
            entry.get("verification")
            if isinstance(entry.get("verification"), dict)
            else {}
        )
        semantic_judgments = (
            verification.get("selector_semantic_judgments")
            if isinstance(
                verification.get("selector_semantic_judgments"), dict
            )
            else {}
        )
        candidate_utility_trace.append(
            {
                "candidate_id": (
                    f"R{input_rank}"
                    if input_rank > 0
                    else str(entry.get("candidate_id") or "")
                ),
                "title": str(entry.get("title") or ""),
                "tier": str(entry.get("tier") or ""),
                "fill_source": str(entry.get("fill_source") or ""),
                "branch": branch,
                "base_utility": round(base_utility, 3),
                "utility_details": utility_details,
                "near_equal_utility_count": len(tied),
                "branch_diversity_eligible": branch_diversity_eligible,
                "branch_previously_selected": branch_previously_selected,
                "final_rank": len(ranked),
                "comparison_purposes": list(
                    entry.get("comparison_purposes") or []
                ),
                "comparison_purpose_evidence": dict(
                    entry.get("comparison_purpose_evidence") or {}
                ),
                "selector_decision": str(
                    verification.get("selector_requested_tier") or ""
                ),
                "selector_reason": str(entry.get("selection_reason") or ""),
                "selection_evidence": dict(
                    entry.get("selection_evidence") or {}
                ),
                "adaptation_required": bool(
                    entry.get("adaptation_required")
                ),
                "confidence": str(entry.get("confidence") or ""),
                "evidence_level": str(entry.get("evidence_level") or ""),
                "fulltext_verified": entry.get("fulltext_verified") is True,
                "task_protocol_relevance": str(
                    entry.get("task_protocol_relevance") or ""
                ),
                "runnability": str(entry.get("runnability") or ""),
                "availability_warnings": list(
                    entry.get("availability_warnings") or []
                ),
                "selector_semantic_judgments": semantic_judgments,
            }
        )
        if branch != "unspecified":
            branch_selected_counts[branch] = branch_selected_counts.get(branch, 0) + 1
            precovered.add(branch)
        remaining.pop(index)

    chosen = ranked[:limit]
    original_titles = [str(item.get("title") or "") for item in prepared]
    chosen_titles = [str(item.get("title") or "") for item in chosen]
    utilities_descending = sorted(
        {float(item["base_utility"]) for item in candidate_utility_trace},
        reverse=True,
    )
    utility_ranks = {
        utility: rank
        for rank, utility in enumerate(utilities_descending, start=1)
    }
    for trace in candidate_utility_trace:
        retained = int(trace["final_rank"]) <= len(chosen)
        trace["utility_rank"] = utility_ranks[float(trace["base_utility"])]
        trace["retained"] = retained
        trace["decision"] = (
            "retained_in_evaluation_view"
            if retained
            else "eligible_but_omitted_by_evaluation_cap"
        )
        trace["reason"] = (
            "Retained after purpose-conditioned utility ranking and the "
            "near-equal mechanism-branch tie-break."
            if retained
            else (
                "Passed the evidence and comparison-purpose gates but was "
                f"outside the Top-{limit} evaluation cap."
            )
        )
    selection_trace = [
        {
            "title": trace["title"],
            "branch": trace["branch"],
            "base_utility": trace["base_utility"],
            "near_equal_utility_count": trace["near_equal_utility_count"],
            "branch_diversity_eligible": trace["branch_diversity_eligible"],
            "branch_previously_selected": trace["branch_previously_selected"],
        }
        for trace in candidate_utility_trace
        if trace["retained"]
    ]
    cap_omissions = [
        trace for trace in candidate_utility_trace if not trace["retained"]
    ]
    sanitized: list[dict[str, Any]] = []
    for item in chosen:
        entry = dict(item)
        entry.pop("_selection_input_rank", None)
        sanitized.append(entry)
    omitted = [
        str(item.get("title") or "")
        for item in prepared
        if _normalized_phrase(item.get("title"))
        not in {_normalized_phrase(chosen_item.get("title")) for chosen_item in chosen}
    ]
    return sanitized, {
        "enabled": len(pool_branch_counts) > 1,
        "applied": chosen_titles != original_titles[: len(chosen_titles)],
        "eligible_pool_count": len(prepared),
        "retained_after_cap": len(chosen),
        "omitted_by_cap_count": len(prepared) - len(chosen),
        "omitted_by_cap_titles": omitted,
        "candidate_utility_trace": candidate_utility_trace,
        "cap_omissions": cap_omissions,
        "identity_deduplication_count": len(identity_deduplications),
        "identity_deduplications": identity_deduplications,
        "normalized_branch_count": len(pool_branch_counts),
        "pool_branch_counts": pool_branch_counts,
        "covered_mechanism_branches": list(
            dict.fromkeys(
                str(item.get("mechanism_branch_normalized") or "unspecified")
                for item in chosen
            )
        ),
        "branch_diversity_policy": "near_equal_semantic_utility_tie_break_only",
        "semantic_utility_tie_band": utility_tie_band,
        "selection_trace": selection_trace,
        "original_titles": original_titles,
        "reordered_titles": chosen_titles,
        "policy": (
            "Rank the unified Core/Extended pool by grounded semantic baseline "
            "utility. Mechanism branch is considered only as a tie-break within "
            "a two-point near-equal utility band; it never reserves a seat or subtracts "
            "value merely because another candidate shares the branch."
        ),
    }


def bibliography_context(markdown: str, *, limit: int = 22000) -> str:
    """Return the bibliography tail so references are not lost to prompt truncation."""
    text = str(markdown or "")
    matches = list(
        re.finditer(
            r"(?im)^#{1,6}\s*(?:references|bibliography|参考文献)\s*$",
            text,
        )
    )
    if matches:
        return text[matches[-1].start() :][:limit]
    return text[-limit:]


def render_structured_bibliography(
    entries: list[dict[str, Any]],
    citation_contexts: list[dict[str, Any]],
    *,
    limit: int = 26000,
) -> str:
    """Render a compact, complete exact-title inventory for the planning prompt.

    Complete raw entries remain in ``bibliography_evidence.json`` and are used
    after the model returns a title. Keeping the prompt view compact ensures the
    final bibliography records are not silently lost to front truncation.
    """
    by_target: dict[str, list[dict[str, Any]]] = {}
    for context in citation_contexts:
        if not isinstance(context, dict):
            continue
        for target_id in context.get("target_ids") or []:
            by_target.setdefault(str(target_id), []).append(context)
    blocks: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        title = " ".join(str(entry.get("title") or "").split())
        complete_entry = " ".join(str(entry.get("entry") or "").split())
        if not title and not complete_entry:
            continue
        tei_id = str(entry.get("tei_id") or "")
        header = (
            f"[tei_id={tei_id or 'unknown'}] TITLE: {title}\n"
            f"YEAR: {entry.get('year') or ''}"
        )
        linked = entry.get("citation_contexts")
        contexts = (
            [item for item in linked if isinstance(item, dict)]
            if isinstance(linked, list)
            else by_target.get(tei_id, [])
        )
        if contexts:
            title_tokens = meaningful_tokens(title) - RETRIEVAL_GENERIC_TOKENS
            best_context = max(
                contexts,
                key=lambda context: len(
                    title_tokens
                    & meaningful_tokens(str(context.get("context") or ""))
                ),
            )
            header += (
                "\nINLINE REF "
                f"target={best_context.get('target') or ''} "
                f"label={best_context.get('label') or ''}: "
                f"{str(best_context.get('context') or '')[:260]}"
            )
        blocks.append(header)
    return "\n\n".join(blocks)[:limit]


def _normalized_evidence_text(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def _bibliography_blocks(value: str) -> list[str]:
    """Group common numbered-reference layouts without reconstructing titles."""
    lines = [line.strip() for line in str(value or "").splitlines()]
    blocks: list[str] = []
    current: list[str] = []
    marker = re.compile(r"^(?:\[\d+\]|\d+[.)])\s+")
    for line in lines:
        if not line:
            if current:
                blocks.append(" ".join(current))
                current = []
            continue
        if marker.match(line) and current:
            blocks.append(" ".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append(" ".join(current))
    return blocks


def _exact_bibliography_entry(title: str, references: str) -> str:
    normalized_title = _normalized_evidence_text(title)
    if not normalized_title:
        return ""
    for block in _bibliography_blocks(references):
        if normalized_title in _normalized_evidence_text(block):
            return block[:1800]
    return ""


def _structured_bibliography_match(
    title: str, entries: list[dict[str, Any]]
) -> dict[str, Any] | None:
    normalized_title = _normalized_evidence_text(title)
    if not normalized_title:
        return None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        candidate = _normalized_evidence_text(str(entry.get("title") or ""))
        if candidate and candidate == normalized_title:
            return entry
    return None


def _structured_citation_context(
    entry: dict[str, Any],
    citation_contexts: list[dict[str, Any]],
    *,
    method_names: list[str],
) -> tuple[str, dict[str, Any] | None]:
    tei_id = str(entry.get("tei_id") or "")
    embedded = entry.get("citation_contexts")
    candidates = (
        [item for item in embedded if isinstance(item, dict)]
        if isinstance(embedded, list)
        else []
    )
    candidates.extend(
        item
        for item in citation_contexts
        if isinstance(item, dict)
        and tei_id
        and tei_id in [str(value) for value in item.get("target_ids") or []]
    )
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict[str, Any]] = []
    for candidate in candidates:
        key = (
            str(candidate.get("target") or ""),
            str(candidate.get("label") or ""),
            str(candidate.get("context") or ""),
        )
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    for method_name in method_names:
        for candidate in unique:
            context = str(candidate.get("context") or "")
            if _evidence_mentions(context, method_name):
                return context[:900], candidate
    if unique:
        return str(unique[0].get("context") or "")[:900], unique[0]
    return "", None


def _candidate_method_names(title: str, supplied: str) -> list[str]:
    values: list[str] = []
    supplied = " ".join(str(supplied or "").split())
    if supplied:
        values.append(supplied)
    prefix = title.split(":", 1)[0].strip()
    if prefix and len(prefix.split()) <= 5:
        values.append(prefix)
    values.extend(
        token
        for token in re.findall(r"\b[A-Za-z][A-Za-z0-9-]{2,}\b", title)
        if (
            any(character.isupper() for character in token[1:])
            or any(character.isdigit() for character in token)
            or token.isupper()
        )
    )
    return list(dict.fromkeys(value for value in values if len(value) >= 3))


def _inline_method_alias(
    context: str, citation_metadata: dict[str, Any] | None
) -> str:
    """Return a visible acronym immediately before a linked TEI citation.

    Some bibliography titles omit the acronym used in prose (for example, the
    title is expanded while the body names a method). A targeted TEI edge
    proves the reference identity, so the adjacent acronym can be preserved as
    the method label without trusting a model-invented alias.
    """
    if not citation_metadata:
        return ""
    label = " ".join(str(citation_metadata.get("label") or "").split())
    rendered = " ".join(str(context or "").split())
    if not label or not rendered:
        return ""
    label_start = rendered.find(label)
    if label_start < 0:
        return ""
    prefix = rendered[:label_start].rstrip(" ([{")
    match = re.search(r"\b([A-Za-z][A-Za-z0-9-]{2,})$", prefix)
    if not match:
        return ""
    alias = match.group(1)
    if not (
        alias.isupper()
        or any(character.isupper() for character in alias[1:])
        or any(character.isdigit() for character in alias)
    ):
        return ""
    return alias


def _targetless_structured_citation_context(
    entry: dict[str, Any],
    citation_contexts: list[dict[str, Any]],
    *,
    method_names: list[str],
) -> tuple[str, dict[str, Any] | None, str]:
    """Link a target-less inline citation using two independent identity cues.

    GROBID occasionally preserves the inline bibliographic marker but drops its
    ``target``.  A method/full-title mention plus the matching reference ordinal
    or author-year pair is still deterministic; a generic body mention alone is
    deliberately insufficient.
    """
    ordinal = entry.get("ordinal")
    try:
        ordinal_value = int(ordinal) if ordinal not in (None, "") else None
    except (TypeError, ValueError):
        ordinal_value = None
    year = str(entry.get("year") or "").strip()
    surnames = {
        parts[-1].casefold()
        for author in entry.get("authors") or []
        if (parts := re.findall(r"[A-Za-z][A-Za-z'-]+", str(author)))
    }
    full_title = str(entry.get("title") or "").strip()
    identity_phrases = list(dict.fromkeys([full_title, *method_names]))
    for raw_context in citation_contexts:
        if not isinstance(raw_context, dict):
            continue
        target_ids = [
            str(value).strip().lstrip("#")
            for value in raw_context.get("target_ids") or []
            if str(value).strip().lstrip("#")
        ]
        if target_ids or str(raw_context.get("target") or "").strip():
            continue
        context = " ".join(str(raw_context.get("context") or "").split())
        if not context:
            continue
        matched_identity = next(
            (
                phrase
                for phrase in identity_phrases
                if phrase and _evidence_mentions(context, phrase)
            ),
            "",
        )
        if not matched_identity:
            continue
        label_numbers = {
            int(value)
            for value in re.findall(r"\d+", str(raw_context.get("label") or ""))
        }
        label_match = ordinal_value is not None and ordinal_value in label_numbers
        normalized_context = _normalized_evidence_text(context)
        author_match = bool(
            year
            and year in normalized_context.split()
            and any(
                re.search(
                    rf"(?:^| ){re.escape(surname)}(?: |$)", normalized_context
                )
                for surname in surnames
                if len(surname) >= 3
            )
        )
        if not (label_match or author_match):
            continue
        if author_match and label_match:
            link_method = "targetless_method_name_plus_author_year_and_label"
        elif author_match:
            link_method = "targetless_method_name_plus_author_year"
        else:
            link_method = "targetless_method_name_plus_label"
        return (
            context[:900],
            {
                **raw_context,
                "matched_identity": matched_identity,
                "author_year_match": author_match,
                "ordinal_label_match": label_match,
            },
            link_method,
        )
    return "", None, ""


def _structured_entry_citation_context(
    entry: dict[str, Any],
    citation_contexts: list[dict[str, Any]],
    *,
    method_names: list[str],
) -> tuple[str, dict[str, Any] | None, str]:
    context, metadata = _structured_citation_context(
        entry,
        citation_contexts,
        method_names=method_names,
    )
    if context:
        return context, metadata, "tei_target"
    return _targetless_structured_citation_context(
        entry,
        citation_contexts,
        method_names=method_names,
    )


def _body_author_year_citation_context(
    entry: dict[str, Any],
    body: str,
    *,
    method_names: list[str],
) -> tuple[str, dict[str, Any] | None, str]:
    """Recover a citation omitted entirely from GROBID's ``ref`` inventory.

    A single sentence must contain both the bibliography identity (full title
    or method acronym) and matching author-year evidence. This handles GROBID
    output where visible citations survive as ordinary ``s`` text but no
    ``<ref type="bibr">`` node is emitted.
    """
    year = str(entry.get("year") or "").strip()
    surnames = {
        parts[-1].casefold()
        for author in entry.get("authors") or []
        if (parts := re.findall(r"[A-Za-z][A-Za-z'-]+", str(author)))
    }
    if not year or not surnames:
        return "", None, ""
    full_title = str(entry.get("title") or "").strip()
    identity_phrases = list(dict.fromkeys([full_title, *method_names]))
    # Keep ``et al.`` inside its sentence while applying the same conservative
    # sentence boundary used by the text-only citation fallback.
    protected = re.sub(
        r"\bet\s+al\.",
        "et al<BASELINE_PERIOD>",
        str(body or ""),
        flags=re.IGNORECASE,
    )
    spans = [
        span.replace("<BASELINE_PERIOD>", ".").strip()
        for span in re.split(r"(?<=[.!?。！？])\s+|\n+", protected)
        if span.strip()
    ]
    for context in spans:
        matched_identity = next(
            (
                phrase
                for phrase in identity_phrases
                if phrase and _evidence_mentions(context, phrase)
            ),
            "",
        )
        if not matched_identity:
            continue
        normalized_context = _normalized_evidence_text(context)
        author_year_match = bool(
            year in normalized_context.split()
            and any(
                re.search(
                    rf"(?:^| ){re.escape(surname)}(?: |$)", normalized_context
                )
                for surname in surnames
                if len(surname) >= 3
            )
        )
        if not author_year_match:
            continue
        return (
            context[:900],
            {
                "target": "",
                "label": "",
                "matched_identity": matched_identity,
                "author_year_match": True,
                "ordinal_label_match": False,
            },
            "body_method_name_plus_author_year_without_tei_ref",
        )
    return "", None, ""


def _evidence_mentions(value: str, phrase: str) -> bool:
    normalized_value = _normalized_evidence_text(value)
    normalized_phrase = _normalized_evidence_text(phrase)
    if not normalized_phrase:
        return False
    return bool(
        re.search(
            rf"(?:^| ){re.escape(normalized_phrase)}(?: |$)", normalized_value
        )
    )


def _body_before_bibliography(markdown: str) -> str:
    matches = list(
        re.finditer(
            r"(?im)^#{1,6}\s*(?:references|bibliography|参考文献)\s*$",
            str(markdown or ""),
        )
    )
    return str(markdown or "")[: matches[-1].start()] if matches else str(markdown or "")


def _find_citation_context(
    body: str,
    bibliography_entry: str,
    *,
    method_names: list[str],
    supplied_context: str,
) -> str:
    spans = [
        span.strip()
        for span in re.split(r"(?<=[.!?。！？])\s+|\n+", body)
        if span.strip()
    ]
    for method_name in method_names:
        for span in spans:
            if _evidence_mentions(span, method_name):
                return span[:900]
    label_match = re.match(r"^\s*\[(\d+)\]", bibliography_entry) or re.match(
        r"^\s*(\d+)[.)]\s+", bibliography_entry
    )
    if label_match:
        label = label_match.group(1)
        citation = re.compile(rf"\[[^\]]*\b{re.escape(label)}\b[^\]]*\]")
        for span in spans:
            if citation.search(span):
                return span[:900]
    supplied = " ".join(str(supplied_context or "").split())
    if supplied:
        supplied_tokens = meaningful_tokens(supplied) - RETRIEVAL_GENERIC_TOKENS
        for span in spans:
            span_tokens = meaningful_tokens(span) - RETRIEVAL_GENERIC_TOKENS
            if len(supplied_tokens & span_tokens) >= min(4, len(supplied_tokens)):
                return span[:900]
    return ""


def _validated_current_baselines(
    raw_values: Any, experiment_evidence: str
) -> list[str]:
    values = raw_values if isinstance(raw_values, list) else []
    validated: list[str] = []
    for raw in values:
        name = " ".join(str(raw or "").split())[:220]
        if name and _evidence_mentions(experiment_evidence, name):
            validated.append(name)
    return list(dict.fromkeys(validated))[:12]


def _compact_query_fragment(value: Any, *, words: int = 10) -> str:
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9+_.-]*", str(value or ""))
    return " ".join(tokens[:words])[:180]


def _deterministic_discovery_queries(
    *,
    task: str,
    method_family: str,
    datasets: list[str],
    current_baselines: list[str],
    cited_not_compared: list[dict[str, Any]],
) -> list[str]:
    """Return four bounded discovery queries when model JSON ends early."""
    task_term = _compact_query_fragment(task) or "direct experimental task"
    method_term = _compact_query_fragment(method_family, words=8)
    dataset_term = _compact_query_fragment(datasets[0], words=4) if datasets else ""
    cited_method = next(
        (
            _compact_query_fragment(item.get("method_name") or item.get("title"), words=6)
            for item in cited_not_compared
            if isinstance(item, dict)
            and (item.get("method_name") or item.get("title"))
        ),
        "",
    )
    named_term = (
        _compact_query_fragment(current_baselines[0], words=6)
        if current_baselines
        else cited_method or method_term or task_term
    )
    comparison_terms = " ".join(
        _compact_query_fragment(value, words=4)
        for value in current_baselines[:2]
    ).strip()
    queries = [
        named_term,
        " ".join(
            part
            for part in ("Methods for", task_term, "evaluated on", dataset_term)
            if part
        ),
        " ".join(
            part for part in (task_term, dataset_term, comparison_terms) if part
        ),
        " ".join(
            part
            for part in (
                "Technically distinct methods for",
                task_term,
                "using",
                method_term,
            )
            if part
        ),
    ]
    fallbacks = (
        "named direct baseline",
        "Methods for the same task and evaluation protocol",
        "direct baseline comparison",
        "Technically distinct methods for the same task",
    )
    rendered: list[str] = []
    seen: set[str] = set()
    for index, query in enumerate(queries):
        normalized = " ".join(query.split()).strip()[:220] or fallbacks[index]
        key = normalized.casefold()
        if key in seen:
            normalized = fallbacks[index]
            key = normalized.casefold()
        rendered.append(normalized)
        seen.add(key)
    return rendered


def build_baseline_retrieval_plan(
    markdown: str,
    *,
    experiment_evidence: str,
    bibliography_evidence: str | None = None,
    bibliography_entries: list[dict[str, Any]] | None = None,
    citation_contexts: list[dict[str, Any]] | None = None,
    review_as_of: str,
    llm_json: JsonModel,
) -> dict[str, Any]:
    bibliography_mode = (
        bibliography_evidence is not None or bibliography_entries is not None
    )
    structured_entries = [
        dict(entry)
        for entry in bibliography_entries or []
        if isinstance(entry, dict)
    ]
    structured_contexts = [
        dict(context)
        for context in citation_contexts or []
        if isinstance(context, dict)
    ]
    references = (
        render_structured_bibliography(structured_entries, structured_contexts)
        if structured_entries
        else bibliography_evidence or ""
    )
    if bibliography_mode:
        prompt = f'''Return valid JSON only, exactly in this schema:
{{"task":"","datasets_or_benchmarks":[""],"evaluation_setting":"","method_family":"","current_baselines":[""],"cited_not_compared":[{{"title":"","method_name":"","mechanism_branch":"","task_protocol_relevance":"high|medium","citation_context":"","reason":""}}],"queries":["","","",""]}}

Build a conservative retrieval plan for plausible *direct experimental baselines*.
First identify the task, dataset/benchmark and evaluation setting. Then list only
methods that the supplied local experiment evidence actually uses as comparison
baselines. Do not list the manuscript's proposed method, methods mentioned only
in background/references, or invented aliases. It is valid for current_baselines
to be empty.

Before proposing external discovery queries, inspect the structured bibliography,
its inline-ref target/label contexts, and experiment evidence. In
cited_not_compared, return every evidence-qualified exact bibliography paper title
that (a) the manuscript cites as a method for substantially the same task, and
(b) is not visibly compared in the supplied experiment evidence. Do not truncate
the list because several earlier items use the same mechanism. Copy each TITLE
field exactly and provide the visible method name or acronym used in the body.
For every item, assign one concise, reusable mechanism_branch label and mark
task_protocol_relevance as high or medium. Use the same label for technically
equivalent branches and different labels for genuinely distinct mechanisms.
Order by task/protocol relevance while interleaving distinct branches. Never
reconstruct or combine titles. Exclude surveys, datasets, metrics, background-only
theory, the manuscript itself, and any uncertain reconstruction. It is valid and
preferable to return an empty list when the evidence is unclear.

The deterministic pipeline independently inventories every structured TEI entry
with a verifiable body citation, including guarded target-less acronym/full-title
links corroborated by author-year or reference label. Your list annotates those
records with semantic branch/relevance; omitting a title does not delete the
deterministic record, and adding a title cannot bypass its citation evidence gate.

Produce exactly four concise English queries in this order:
1. a short paper-title or named-method phrase for the task;
2. a complete natural-language sentence asking for methods on the same task,
   dataset and evaluation protocol;
3. a controlled keyword phrase for bulk discovery around the current comparison
   set and task;
4. a complete natural-language sentence asking for a technically distinct but
   directly comparable method family.

Prioritize exact local names. Do not produce surveys, tutorial queries, broad
background topics, venue names, Boolean operators, quotation marks, or the words
paper/review. The review cutoff is {review_as_of}; queries must describe work
available on or before that date.

MANUSCRIPT CONTEXT:
{markdown[:22000]}

LOCAL EXPERIMENT EVIDENCE (this is the only source for current_baselines):
{experiment_evidence[:18000]}

STRUCTURED BIBLIOGRAPHY AND INLINE CITATION CONTEXTS
(the only source for exact cited_not_compared titles):
{references[:22000]}
'''
    else:
        # Preserve the frozen standalone/Core planning contract for callers that do
        # not opt into the v0.4.1 bibliography-first pipeline.
        prompt = f'''Return valid JSON only, exactly in this schema:
{{"task":"","datasets_or_benchmarks":[""],"evaluation_setting":"","method_family":"","current_baselines":[""],"queries":["","","",""]}}

Build a conservative retrieval plan for plausible *direct experimental baselines*.
First identify the task, dataset/benchmark and evaluation setting. Then list only
methods that the supplied local experiment evidence actually uses as comparison
baselines. Do not list the manuscript's proposed method, methods mentioned only
in background/references, or invented aliases. It is valid for current_baselines
to be empty.

Produce exactly four concise English queries in this order:
1. task plus a named current baseline or its method family;
2. task plus concrete dataset/benchmark and evaluation setting;
3. task plus the current baseline set, seeking competitive alternatives;
4. a technically distinct method family for the same task and protocol.

Prioritize exact local names. Do not produce surveys, tutorial queries, broad
background topics, venue names, Boolean operators, quotation marks, or the words
paper/review. The review cutoff is {review_as_of}; queries must describe work
available on or before that date.

MANUSCRIPT CONTEXT:
{markdown[:22000]}

LOCAL EXPERIMENT EVIDENCE (this is the only source for current_baselines):
{experiment_evidence[:18000]}
'''
    payload = llm_json(
        "You construct evidence-grounded direct-baseline retrieval plans.",
        prompt,
        max_tokens=2800 if bibliography_mode else 420,
    )

    def text(key: str, limit: int = 500) -> str:
        return (
            str(payload.get(key) or "").strip()[:limit]
            if isinstance(payload, dict)
            else ""
        )

    def values(key: str, limit: int) -> list[str]:
        raw = payload.get(key) if isinstance(payload, dict) else []
        if not isinstance(raw, list):
            return []
        seen: set[str] = set()
        normalized: list[str] = []
        for value in raw:
            item = " ".join(str(value).split()).strip()
            item_key = item.lower()
            if not item or item_key in seen:
                continue
            normalized.append(item[:220])
            seen.add(item_key)
            if len(normalized) >= limit:
                break
        return normalized

    cited_not_compared: list[dict[str, Any]] = []
    raw_cited = payload.get("cited_not_compared") if isinstance(payload, dict) else []
    seen_cited: set[str] = set()
    manuscript_body = _body_before_bibliography(markdown)
    validated_current = _validated_current_baselines(
        payload.get("current_baselines") if isinstance(payload, dict) else [],
        experiment_evidence,
    )
    raw_annotations: dict[str, dict[str, Any]] = {}
    deterministically_linked_structured_entries = 0
    if isinstance(raw_cited, list):
        for item in raw_cited:
            if not isinstance(item, dict):
                continue
            title = " ".join(str(item.get("title") or "").split())[:500]
            if title:
                raw_annotations.setdefault(_normalized_evidence_text(title), item)

    def add_evidence(
        *,
        title: str,
        item: dict[str, Any],
        bibliography_entry: str,
        citation_context: str,
        citation_metadata: dict[str, Any] | None,
        structured_entry: dict[str, Any] | None,
        citation_link_method: str,
    ) -> None:
        key = title.casefold()
        if not title or key in seen_cited or not bibliography_entry or not citation_context:
            return
        method_names = _candidate_method_names(
            title, str(item.get("method_name") or "")
        )
        if any(
            _evidence_mentions(experiment_evidence, name) for name in method_names
        ):
            return
        evidence: dict[str, Any] = {
            "title": title,
            "method_name": method_names[0] if method_names else "",
            "mechanism_branch": " ".join(
                str(item.get("mechanism_branch") or "").split()
            )[:160],
            "task_protocol_relevance": (
                str(item.get("task_protocol_relevance") or "")
                .strip()
                .lower()[:32]
            ),
            "citation_context": citation_context,
            "citation_link_method": citation_link_method,
            "reason": (
                " ".join(str(item.get("reason") or "").split())[:500]
                or "Structured bibliography entry is cited in the body and is not visible in experiment comparisons."
            ),
            "bibliography_entry": bibliography_entry,
            "experiment_comparison_status": "not_observed",
            "evidence_chain": (
                "exact_tei_bibliography_title_to_deterministic_body_citation_"
                "to_local_experiment_nonappearance"
                if structured_entry is not None
                else "exact_bibliography_title_to_body_citation_context_to_"
                "local_experiment_nonappearance"
            ),
            "local_citation_before_review_cutoff": True,
            "planning_source": (
                "structured_bibliography_deterministic_inventory"
                if structured_entry is not None
                else "llm_title_with_unstructured_bibliography_verification"
            ),
        }
        if structured_entry is not None:
            evidence.update(
                {
                    "bibliography_tei_id": str(structured_entry.get("tei_id") or ""),
                    "bibliography_authors": list(structured_entry.get("authors") or []),
                    "bibliography_year": structured_entry.get("year"),
                    "bibliography_ordinal": structured_entry.get("ordinal"),
                }
            )
        if citation_metadata:
            evidence.update(
                {
                    "citation_ref_target": str(citation_metadata.get("target") or ""),
                    "citation_ref_label": str(citation_metadata.get("label") or ""),
                    "citation_link_evidence": {
                        key: citation_metadata.get(key)
                        for key in (
                            "matched_identity",
                            "author_year_match",
                            "ordinal_label_match",
                        )
                        if citation_metadata.get(key) not in (None, "")
                    },
                }
            )
        cited_not_compared.append(evidence)
        seen_cited.add(key)

    if structured_entries:
        # Structured TEI is the authoritative inventory.  The model may annotate
        # branches/relevance, but forgetting a title cannot remove it.
        for structured_entry in structured_entries:
            title = " ".join(str(structured_entry.get("title") or "").split())[:500]
            if not title:
                continue
            annotation = dict(
                raw_annotations.get(_normalized_evidence_text(title), {})
            )
            # Deterministic identity never trusts a model-invented alias.  The
            # model may still annotate branch/relevance after the title-derived
            # link has been proven.
            method_names = _candidate_method_names(title, "")
            citation_context, citation_metadata, link_method = (
                _structured_entry_citation_context(
                    structured_entry,
                    structured_contexts,
                    method_names=method_names,
                )
            )
            if not citation_context:
                citation_context, citation_metadata, link_method = (
                    _body_author_year_citation_context(
                        structured_entry,
                        manuscript_body,
                        method_names=method_names,
                    )
                )
            if citation_context:
                deterministically_linked_structured_entries += 1
            visible_method = next(
                (
                    name
                    for name in method_names
                    if _evidence_mentions(citation_context, name)
                ),
                "",
            )
            if not visible_method:
                visible_method = _inline_method_alias(
                    citation_context, citation_metadata
                )
            if not visible_method and method_names:
                visible_method = method_names[0]
            annotation["method_name"] = visible_method
            add_evidence(
                title=title,
                item=annotation,
                bibliography_entry=str(structured_entry.get("entry") or ""),
                citation_context=citation_context,
                citation_metadata=citation_metadata,
                structured_entry=structured_entry,
                citation_link_method=link_method,
            )
    elif isinstance(raw_cited, list):
        # Text-only fallback retains the legacy model-proposed title path.
        for item in raw_cited:
            if not isinstance(item, dict):
                continue
            title = " ".join(str(item.get("title") or "").split())[:500]
            bibliography_entry = _exact_bibliography_entry(title, references)
            method_names = _candidate_method_names(
                title, str(item.get("method_name") or "")
            )
            citation_context = _find_citation_context(
                manuscript_body,
                bibliography_entry,
                method_names=method_names,
                supplied_context=str(item.get("citation_context") or ""),
            )
            add_evidence(
                title=title,
                item=item,
                bibliography_entry=bibliography_entry,
                citation_context=citation_context,
                citation_metadata=None,
                structured_entry=None,
                citation_link_method="text_bibliography_body_context",
            )

    llm_queries = values("queries", len(BASELINE_RETRIEVAL_QUERY_ROLES))
    task = text("task")
    method_family = text("method_family")
    datasets_or_benchmarks = values("datasets_or_benchmarks", 8)
    fallback_queries = _deterministic_discovery_queries(
        task=task,
        method_family=method_family,
        datasets=datasets_or_benchmarks,
        current_baselines=validated_current,
        cited_not_compared=cited_not_compared,
    )
    queries = list(llm_queries)
    queries.extend(fallback_queries[len(queries) :])
    query_specs = [
        {
            "query": query,
            "retrieval_role": BASELINE_RETRIEVAL_QUERY_ROLES[index],
            **BASELINE_QUERY_SPECS[index],
        }
        for index, query in enumerate(queries)
    ]

    result: dict[str, Any] = {
        "task": task,
        "datasets_or_benchmarks": datasets_or_benchmarks,
        "evaluation_setting": text("evaluation_setting"),
        "method_family": method_family,
        "current_baselines": validated_current,
        "queries": queries,
        "source": "local_experiment_evidence_and_manuscript_context",
        "review_as_of": review_as_of,
    }
    if bibliography_mode:
        result.update(
            {
                "cited_not_compared": cited_not_compared,
                "bibliography_inventory": {
                    "structured_entry_count": len(structured_entries),
                    "deterministically_linked_not_compared_count": sum(
                        item.get("planning_source")
                        == "structured_bibliography_deterministic_inventory"
                        for item in cited_not_compared
                    ),
                    "model_annotation_count": len(raw_annotations),
                    "model_omission_cannot_remove_structured_candidate": bool(
                        structured_entries
                    )
                    and deterministically_linked_structured_entries
                    == len(structured_entries),
                    "deterministically_linked_structured_entry_count": (
                        deterministically_linked_structured_entries
                    ),
                    "unlinked_structured_entry_count": (
                        len(structured_entries)
                        - deterministically_linked_structured_entries
                    ),
                },
                "query_specs": query_specs,
                "query_generation": {
                    "llm_query_count": len(llm_queries),
                    "deterministic_fallback_count": len(queries) - len(llm_queries),
                    "expected_query_count": len(BASELINE_RETRIEVAL_QUERY_ROLES),
                },
                "source": (
                    "bibliography_first_then_local_experiment_evidence_and_external_discovery"
                ),
            }
        )
    return result


def select_direct_baseline_records(
    candidates: list[dict[str, Any]],
    *,
    local_title: str,
    queries: list[str],
    review_as_of: str,
    llm_json: JsonModel,
    retrieval_plan: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    direct_candidates = [
        candidate
        for candidate in candidates
        if str(candidate.get("retrieval_role") or "")
        in BASELINE_DIRECT_RETRIEVAL_ROLES
    ]
    if not direct_candidates:
        return [], {"selection_status": "no_candidates", "selected_record_count": 0}
    has_relation_candidates = any(
        str(candidate.get("retrieval_role") or "") in BASELINE_RELATION_ROLES
        for candidate in direct_candidates
    )
    bibliography_mode = bool(
        isinstance(retrieval_plan, dict)
        and "cited_not_compared" in retrieval_plan
    )
    bibliography_candidates = [
        candidate
        for candidate in direct_candidates
        if str(candidate.get("retrieval_role") or "") == BASELINE_BIBLIOGRAPHY_ROLE
    ]
    # Every supported source enters the same deterministic pre-selector pool.
    # Citation/bibliography evidence may break a relevance tie, but no role can
    # reserve capacity or crowd all other sources out before semantic review.
    shortlist, preselector_pool_diagnostics = unified_retrieval_pool(
        direct_candidates,
        limit=BASELINE_SEMANTIC_CANDIDATE_LIMIT,
        allowed_roles=BASELINE_DIRECT_RETRIEVAL_ROLES,
        preserve_retained_input_order=True,
    )
    bibliography_candidates_sent = sum(
        str(candidate.get("retrieval_role") or "") == BASELINE_BIBLIOGRAPHY_ROLE
        for candidate in shortlist
    )
    bibliography_truncated = max(
        0, len(bibliography_candidates) - bibliography_candidates_sent
    )
    plan = retrieval_plan or {}
    target_evidence = {
        "task": plan.get("task", ""),
        "method_modules": plan.get("method_modules") or plan.get("method_family", ""),
        "method_family": plan.get("method_family", ""),
        "datasets_or_benchmarks": plan.get("datasets_or_benchmarks") or [],
        "evaluation_setting_and_metrics": plan.get("evaluation_setting", ""),
        "current_experimental_baselines": plan.get("current_baselines") or [],
    }
    payload: list[dict[str, Any]] = []
    for index, item in enumerate(shortlist, start=1):
        evidence_profile = _candidate_evidence_profile(item)
        payload_item: dict[str, Any] = {
            "candidate_id": f"R{index}",
            "title": item.get("title", ""),
            "authors": item.get("authors", ""),
            "published": item.get("published", ""),
            "abstract": str(item.get("summary") or ""),
            "source": item.get("source", ""),
            "url": item.get("url", ""),
            "doi": item.get("doi", ""),
            "aminer_pub_id": item.get("aminer_pub_id", ""),
            "query": item.get("query", ""),
            "retrieval_role": item.get("retrieval_role", ""),
            "lexical_score": item.get("relevance_score", "0"),
            "venue": item.get("venue", ""),
            "publication_status": item.get("publication_status", ""),
            "submission_status": item.get("submission_status", ""),
            "availability_evidence": item.get("availability_evidence", ""),
            "cutoff_status": item.get("cutoff_status", ""),
            "aminer_cutoff_status": item.get("aminer_cutoff_status", ""),
            "publication_date_precision": item.get("publication_date_precision", ""),
            "runnability": item.get("runnability", ""),
            "availability_warnings": _availability_evidence_warnings(item),
            **evidence_profile,
        }
        if str(item.get("retrieval_role") or "") in BASELINE_RELATION_ROLES:
            payload_item["relation_direction"] = item.get("relation_direction", "")
            payload_item["aminer_pub_id"] = item.get("aminer_pub_id", "")
        if str(item.get("retrieval_role") or "") == "cited_not_compared_reference":
            payload_item["bibliography_title"] = item.get("bibliography_title", "")
            payload_item["bibliography_title_similarity"] = item.get(
                "bibliography_title_similarity", ""
            )
            payload_item["citation_context"] = item.get("citation_context", "")
            payload_item["bibliography_reason"] = item.get(
                "bibliography_reason", ""
            )
            payload_item["method_name"] = item.get("method_name", "")
            payload_item["experiment_comparison_status"] = item.get(
                "experiment_comparison_status", ""
            )
            payload_item["bibliography_entry"] = str(
                item.get("bibliography_entry") or ""
            )
            payload_item["bibliography_tei_id"] = item.get(
                "bibliography_tei_id", ""
            )
            payload_item["bibliography_authors"] = item.get(
                "bibliography_authors", ""
            )
            payload_item["bibliography_year"] = item.get(
                "bibliography_year", ""
            )
            payload_item["citation_ref_target"] = item.get(
                "citation_ref_target", ""
            )
            payload_item["citation_link_method"] = item.get(
                "citation_link_method", ""
            )
            payload_item["evidence_chain"] = item.get("evidence_chain", "")
        if item.get("mechanism_branch"):
            payload_item["mechanism_branch"] = item.get("mechanism_branch", "")
        if item.get("task_protocol_relevance"):
            payload_item["task_protocol_relevance"] = item.get(
                "task_protocol_relevance", ""
            )
        payload.append(payload_item)
    relation_guidance = ""
    if has_relation_candidates:
        relation_guidance = ''' AMiner backward-reference membership is discovery
evidence, not proof that a paper is a direct baseline.
`target_references_candidate` means the uploaded paper cites the candidate.
The public endpoint does not provide forward citations; none are inferred.
Apply the same evidence and comparison-purpose tests to every candidate.'''
    bibliography_guidance = ''' Exact-title-verified cited_not_compared_reference
candidates were found in the manuscript bibliography before external discovery.
Their bibliography membership proves citation, not experimental comparability or
omission. Prefer them only for a supplied-evidence comparison purpose.'''
    bibliography_prompt = (
        f"Bibliography evidence guidance: {bibliography_guidance}\n"
        if bibliography_mode
        else ""
    )
    shortlist_index = [
        {
            "candidate_id": item["candidate_id"],
            "title": item.get("title", ""),
            "retrieval_role": item.get("retrieval_role", ""),
            "mechanism_branch_hint": item.get("mechanism_branch", ""),
        }
        for item in payload
    ]
    if bibliography_mode:
        prompt_header = f'''Return valid JSON only:
{{"assessments":[{{"candidate_id":"R1","decision":"core|extended|reject","reason":"","confidence":"high|medium|low","comparison_purposes":["direct_performance","mechanism_isolation"],"comparison_purpose_evidence":{{"purpose_label":"evidence"}},"adaptation_required":false,"adaptation_note":"","same_task":"high|medium|low|unknown","same_protocol":"high|medium|low|unknown","mechanism_match":"high|medium|low|unknown","intervention_interface_match":"high|medium|low|unknown","fair_baseline_usefulness":"high|medium|low|unknown","claim_diagnostic_value":"high|medium|low|unknown","marginal_novelty":"high|medium|low|unknown","mechanism_branch":"","task_protocol_relevance":"high|medium|low","runnability":"runnable|uncertain|not_runnable","task_evidence":"","protocol_evidence":"","mechanism_evidence":"","usefulness_evidence":""}}]}}.

Return exactly one assessment for every candidate ID in the current batch,
including rejects. Do not omit difficult or low-value candidates. Use
`decision=reject` only when no evidence-grounded comparison purpose below is
valid, or for a non-method item, the uploaded paper/current baseline, or another
objectively excluded record. A different terminal task is not by itself a
rejection: a related mechanism can remain an adapted, component-diagnostic
Extended candidate. A low fair-baseline usefulness or low marginal novelty is a
ranking signal, not by itself a hard rejection. The
deterministic step, not the model, applies the final cap and objective exclusions.
The deterministic evaluation-view step will apply the Top-10 cap after branch
diversification. Core candidates must solve substantially the same task and be
plausibly runnable under a comparable dataset or evaluation protocol. Extended
candidates may instead test a concrete component, budget-matched policy,
novelty boundary, robustness condition, cross-task adaptation, or efficiency
tradeoff. Medium- or low-confidence records must not be promoted to Core.

Assign one or more `comparison_purposes` only when supplied evidence supports
the use. `direct_performance` compares end-task performance under a matched
protocol; `mechanism_isolation` isolates a module, reward, transition, or
intervention; `budget_matched_policy` holds query/retrieval/compute budget fixed;
`novelty_boundary` tests the nearest prior alternative; `robustness_stress_test`
tests fallback, domain, encoder, or perturbation sensitivity;
`cross_task_adaptation` transfers a relevant mechanism from a different task;
and `efficiency_tradeoff` compares latency, calls, tokens, throughput, or cost.
Give concise supplied evidence for every assigned purpose. Cross-task candidates
must set `adaptation_required=true`, state the required adaptation, and remain
Extended; never present them as directly runnable comparisons.

For every candidate, separately judge same task, same dataset/metric
protocol, mechanism match, intervention/interface match, fair experimental
baseline usefulness, diagnostic value for the manuscript's claims, and marginal
value beyond already-returned candidates. Cite only evidence supplied in the
target profile or candidate record. A same-protocol claim requires explicit
dataset, metric, evaluation-setting, or sampling-protocol evidence; topical
similarity and bibliography membership are not protocol evidence. Do not claim
MIND, EB-NeRD, impression sampling, or any other protocol unless it appears in
that candidate's supplied abstract/metadata/context. Use `unknown` when absent.
The supplied `evidence_level`, `evidence_sources`, and `fulltext_verified` are
deterministic provenance. `paper_detail`, title, metadata, abstract, target-side
bibliography, and citation context are not candidate full text. Never upgrade
them to full-text verification. Without `fulltext_verified=true`, describe a
purpose only as a potential candidate to verify; it cannot be Core.

First infer the manuscript's non-generic mechanism branches from the target
method modules (for example, distinct modeling or intervention families, not
generic task words). Direct task/protocol comparability is the Core hard gate,
not the sole valid comparison purpose for Extended.
Mechanism branches are descriptive evidence, not quotas: an important branch
may supply multiple candidates and an unsuitable branch may supply none. Assess
marginal novelty from concrete duplicated claims, interfaces, or interventions,
not merely from sharing a branch label; low marginal novelty is a utility signal,
not a hard exclusion. Give every assessed record
one concise, reusable `mechanism_branch` label
and an explicit `task_protocol_relevance`; use the same branch label for
technically equivalent candidates. Mark confidence and task_protocol_relevance
as `high` only with direct supplied evidence. Missing labels are not treated as
high. Core also requires explicit `runnability=runnable`; missing or uncertain
runnability can remain only as an Extended check when its hard gate passes.
Mark withdrawn, retracted, incomplete-experiment/evaluation, or artifact-blocked
methods as uncertain or not_runnable; they cannot enter Core. Keep reasons concise.

Prefer exact-title-verified cited-but-not-compared candidates when they satisfy
the same task/protocol test or have another evidence-grounded comparison
purpose. Exclude current experimental baselines, surveys, datasets, metrics,
broad background with no valid comparison purpose, work after the cutoff, and
the uploaded manuscript itself.{relation_guidance} Selection only
creates neutral author-review candidates; never state that a baseline is
required or that the experiment is inadequate. Do not invent IDs.

Uploaded manuscript title: {local_title}
Review cutoff: {review_as_of}
Baseline retrieval queries: {json.dumps(queries, ensure_ascii=False)}
Target task/method/protocol evidence: {json.dumps(target_evidence, ensure_ascii=False)}
Complete shortlist index for cross-batch marginal-novelty judgments:
{json.dumps(shortlist_index, ensure_ascii=False)}
{bibliography_prompt}Candidate records in the current assessment batch:
'''
        prompt = prompt_header + json.dumps(payload, ensure_ascii=False)
    else:
        # Keep the frozen standalone/Core contract for legacy programmatic callers.
        prompt = f'''Return valid JSON only: {{"selected":[{{"candidate_id":"R1","reason":""}}]}}.

Select at most ten papers that are plausible *direct experimental baseline*
candidate methods for the uploaded manuscript. A direct baseline should solve
substantially the same task and be plausibly runnable under a comparable
experimental setup. It must match the task and either the manuscript's method
family or a directly comparable intervention identified in the retrieval plan.
Prefer named methods and competitive alternatives within that scope. Exclude surveys, datasets,
metrics, broad background, papers with a materially different task, and the
uploaded manuscript itself. Candidates from the separate alternative-method-family
query are not supplied here and must not be reconstructed.{relation_guidance} Do not infer that a selected method is required;
this is only a conservative author-review candidate list. Do not invent IDs.

Uploaded manuscript title: {local_title}
Review cutoff: {review_as_of}
Baseline retrieval queries: {json.dumps(queries, ensure_ascii=False)}
Structured retrieval plan: {json.dumps(retrieval_plan or {}, ensure_ascii=False)}
{bibliography_prompt}Time-safe candidate records:
{json.dumps(payload, ensure_ascii=False)}
'''
    selection_error = ""
    selected_payload: list[dict[str, Any]] = []
    selector_contract_mode = bibliography_mode
    selector_complete_assessment_contract = bibliography_mode
    assessed_candidate_ids: set[str] = set()
    selector_batch_diagnostics: list[dict[str, Any]] = []
    selector_batch_strategy: str | None = None
    selector_configured_workers = 0
    selector_effective_workers = 0
    selector_stage_wall_seconds = 0.0
    selector_batch_wall_seconds_sum = 0.0
    if bibliography_mode:
        selection_errors: list[str] = []
        selector_batch_strategy = _configured_selector_batch_strategy()
        batches = _selector_batches(
            payload,
            strategy=selector_batch_strategy,
        )
        batch_specs = [
            (batch_index, batch)
            for batch_index, batch in enumerate(batches, start=1)
        ]
        selector_configured_workers = _configured_selector_workers()
        selector_effective_workers = min(
            selector_configured_workers,
            len(batch_specs),
        )

        def assess_batch(
            spec: tuple[int, list[dict[str, Any]]],
        ) -> dict[str, Any]:
            batch_index, batch = spec
            expected_ids = {
                str(item.get("candidate_id") or "").upper() for item in batch
            }
            batch_prompt = prompt_header + json.dumps(batch, ensure_ascii=False)
            batch_started = time.monotonic()
            error_type: str | None = None
            try:
                selection = llm_json(
                    "You assess every supplied baseline candidate's potential comparison purposes using only supplied evidence.",
                    batch_prompt,
                    max_tokens=6500,
                )
            except Exception as exc:
                selection = {}
                error_type = type(exc).__name__
            return {
                "batch": batch_index,
                "expected_ids": expected_ids,
                "selection": selection,
                "error": error_type,
                "wall_seconds": round(
                    max(0.0, time.monotonic() - batch_started),
                    6,
                ),
            }

        selector_started = time.monotonic()
        if selector_effective_workers > 1:
            with ThreadPoolExecutor(
                max_workers=selector_effective_workers,
                thread_name_prefix="baseline-selector",
            ) as executor:
                # Reading futures in submission order preserves the exact
                # serial merge/ranking order while requests run concurrently.
                futures = [
                    executor.submit(assess_batch, spec) for spec in batch_specs
                ]
                batch_results = [future.result() for future in futures]
        else:
            batch_results = [assess_batch(spec) for spec in batch_specs]
        selector_stage_wall_seconds = round(
            max(0.0, time.monotonic() - selector_started),
            6,
        )
        selector_batch_wall_seconds_sum = round(
            sum(float(result["wall_seconds"]) for result in batch_results),
            6,
        )

        for batch_result in batch_results:
            batch_index = int(batch_result["batch"])
            expected_ids = set(batch_result["expected_ids"])
            selection = batch_result["selection"]
            error_type = batch_result["error"]
            if error_type:
                selection_errors.append(str(error_type))
            assessments = (
                selection.get("assessments")
                if isinstance(selection, dict)
                and isinstance(selection.get("assessments"), list)
                else None
            )
            if error_type:
                selector_complete_assessment_contract = False
                raw_items = []
                batch_contract = "failed"
            elif assessments is not None:
                raw_items = assessments
                batch_contract = "complete_assessments"
            else:
                selector_complete_assessment_contract = False
                raw_items = (
                    selection.get("selected")
                    if isinstance(selection, dict)
                    and isinstance(selection.get("selected"), list)
                    else []
                )
                batch_contract = "legacy_selected_only"
            accepted_items: list[dict[str, Any]] = []
            returned_ids: set[str] = set()
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                candidate_id = str(item.get("candidate_id") or "").upper()
                if candidate_id not in expected_ids:
                    continue
                accepted_item = dict(item)
                accepted_item["_selector_response_contract"] = (
                    "complete_assessments"
                    if batch_contract == "complete_assessments"
                    else "legacy_selected_only"
                )
                accepted_items.append(accepted_item)
                returned_ids.add(candidate_id)
            selected_payload.extend(accepted_items)
            assessed_candidate_ids.update(returned_ids)
            selector_batch_diagnostics.append(
                {
                    "batch": batch_index,
                    "expected_count": len(expected_ids),
                    "assessed_count": len(returned_ids),
                    "missing_candidate_ids": sorted(expected_ids - returned_ids),
                    "contract": batch_contract,
                    "error": error_type,
                    "wall_seconds": batch_result["wall_seconds"],
                }
            )
        selection_error = ",".join(dict.fromkeys(selection_errors))
    else:
        try:
            selection = llm_json(
                "You select conservative direct-baseline candidates for experimental review.",
                prompt,
                max_tokens=1000,
            )
        except Exception as exc:
            return [], {
                "selection_status": f"failed_{type(exc).__name__}",
                "selected_record_count": 0,
            }
        raw_selected = selection.get("selected") if isinstance(selection, dict) else []
        selected_payload = raw_selected if isinstance(raw_selected, list) else []
    by_id = {f"R{index}": item for index, item in enumerate(shortlist, start=1)}
    selected: list[dict[str, Any]] = []
    model_core_selected: list[dict[str, Any]] = []
    model_extended_selected: list[dict[str, Any]] = []
    model_selection_audit: list[dict[str, Any]] = []
    model_selected_title_keys: set[str] = set()
    seen_titles: set[str] = set()
    if isinstance(selected_payload, list):
        for model_rank, item in enumerate(selected_payload, start=1):
            if not isinstance(item, dict):
                continue
            candidate_id = str(item.get("candidate_id") or "").upper()
            candidate = by_id.get(candidate_id)
            if not candidate:
                continue
            title = str(candidate.get("title") or "").strip()
            title_key = " ".join(title.lower().split())
            if not title or title_key in seen_titles:
                continue
            if bibliography_mode and _matches_current_baseline(
                candidate, retrieval_plan or {}
            ):
                continue
            if bibliography_mode and (
                (local_title and is_same_paper_title(title, local_title))
                or publication_cutoff_status(
                    str(candidate.get("published") or ""), review_as_of
                )
                == "after_cutoff"
            ):
                continue
            if bibliography_mode and any(
                marker in _normalized_phrase(title)
                for marker in _OBVIOUS_NON_DIRECT_TITLE_MARKERS
            ):
                continue
            if bibliography_mode:
                item_confidence = str(item.get("confidence") or "").strip().lower()
                mechanism_branch = " ".join(
                    str(
                        item.get("mechanism_branch")
                        or candidate.get("mechanism_branch")
                        or ""
                    ).split()
                )[:160]
                task_protocol_relevance = (
                    str(item.get("task_protocol_relevance") or "")
                    .strip()
                    .lower()[:32]
                )
                runnability = str(item.get("runnability") or "").strip().lower()
                extended_eligible, extended_verification = _extended_hard_gate(
                    candidate,
                    retrieval_plan or {},
                    local_title=local_title,
                    review_as_of=review_as_of,
                )
                semantic_judgments = _selector_semantic_judgments(
                    item,
                    extended_verification,
                    allow_legacy_purpose_inference=(
                        item.get("_selector_response_contract")
                        != "complete_assessments"
                    ),
                )
                grounded_purposes = _comparison_purposes(
                    semantic_judgments.get("grounded_comparison_purposes")
                )
                complete_selector_contract = (
                    item.get("_selector_response_contract")
                    == "complete_assessments"
                )
                selector_requested_tier = str(
                    item.get("decision")
                    if complete_selector_contract
                    else item.get("decision") or item.get("tier") or ""
                ).strip().lower()
                selector_contract_reasons: list[str] = []
                if complete_selector_contract:
                    if not semantic_judgments.get(
                        "comparison_purpose_contract_complete"
                    ):
                        selector_contract_reasons.append(
                            "selector_incomplete_comparison_purpose_contract"
                        )
                    if selector_requested_tier not in {
                        "core",
                        "extended",
                        "reject",
                    }:
                        selector_contract_reasons.append(
                            "selector_invalid_or_missing_decision"
                        )
                if selector_contract_reasons:
                    model_selection_audit.append(
                        {
                            "candidate_id": candidate_id,
                            "title": title,
                            "decision": "selector_contract_not_assessable",
                            "reasons": selector_contract_reasons,
                            "selector_requested_tier": (
                                selector_requested_tier or "missing"
                            ),
                            "selector_semantic_judgments": semantic_judgments,
                        }
                    )
                    model_selected_title_keys.add(title_key)
                    seen_titles.add(title_key)
                    continue
                if selector_requested_tier in {"reject", "excluded"}:
                    model_selection_audit.append(
                        {
                            "candidate_id": candidate_id,
                            "title": title,
                            "decision": "selector_explicit_reject",
                            "reason": str(item.get("reason") or "").strip(),
                            "selector_requested_tier": selector_requested_tier,
                            "selector_semantic_judgments": semantic_judgments,
                        }
                    )
                    # An explicit selector rejection is terminal for this
                    # shortlist pass and must not be reintroduced by the
                    # deterministic Extended pool.
                    model_selected_title_keys.add(title_key)
                    seen_titles.add(title_key)
                    continue
                if (
                    not extended_eligible
                    and grounded_purposes
                    and not extended_verification.get("objective_exclusion")
                    and extended_verification.get("evidence_level")
                    in {"abstract_screened", "fulltext_verified"}
                ):
                    # A different terminal task may still provide a useful
                    # component, budget, novelty, robustness, adaptation, or
                    # efficiency comparison.  It remains a neutral Extended
                    # lead and never bypasses the independent Core gates.
                    extended_eligible = True
                    extended_verification = {
                        **extended_verification,
                        "decision": "medium_confidence_purpose_extended",
                        "reason": (
                            "Potential comparison-purpose candidate supported "
                            "by abstract or citation-context evidence; candidate "
                            "full text and any required adaptation remain to be "
                            "verified."
                        ),
                        "comparison_purpose_gate": "passed_for_extended_only",
                        "grounded_comparison_purposes": grounded_purposes,
                    }
                semantic_rejection_reasons: list[str] = []
                if not grounded_purposes:
                    if semantic_judgments.get(
                        "evidence_grounded_comparison_purposes"
                    ):
                        semantic_rejection_reasons.append(
                            "selector_no_objectively_supported_comparison_purpose"
                        )
                    else:
                        semantic_rejection_reasons.append(
                            "selector_no_grounded_comparison_purpose"
                        )
                if semantic_rejection_reasons:
                    audit_decision = (
                        "selector_contract_not_assessable"
                        if "selector_incomplete_comparison_purpose_contract"
                        in semantic_rejection_reasons
                        else "selector_purpose_not_assessable"
                    )
                    model_selection_audit.append(
                        {
                            "candidate_id": candidate_id,
                            "title": title,
                            "decision": audit_decision,
                            "reasons": semantic_rejection_reasons,
                            "selector_semantic_judgments": semantic_judgments,
                        }
                    )
                    # Missing or ungrounded purpose evidence is not a selector
                    # rejection. It remains not-assessable in diagnostics and
                    # must not be reintroduced by deterministic backfill.
                    model_selected_title_keys.add(title_key)
                    seen_titles.add(title_key)
                    continue

                core_blockers: list[str] = []
                if selector_requested_tier == "extended":
                    core_blockers.append("selector_did_not_request_core")
                if "direct_performance" not in grounded_purposes:
                    core_blockers.append("direct_performance_purpose_missing")
                if semantic_judgments.get("adaptation_required"):
                    core_blockers.append("adaptation_required")
                if not extended_verification.get("fulltext_verified"):
                    core_blockers.append("candidate_fulltext_not_verified")
                if item_confidence != "high":
                    core_blockers.append("confidence_not_explicit_high")
                if task_protocol_relevance != "high":
                    core_blockers.append(
                        "task_protocol_relevance_not_explicit_high"
                    )
                if semantic_judgments["same_task"] != "high":
                    core_blockers.append("same_task_not_explicit_high")
                if semantic_judgments["same_protocol"] != "high":
                    core_blockers.append("same_protocol_not_explicit_high")
                if not semantic_judgments[
                    "objective_protocol_evidence_supported"
                ]:
                    core_blockers.append("same_protocol_lacks_supplied_evidence")
                if semantic_judgments["fair_baseline_usefulness"] != "high":
                    core_blockers.append(
                        "fair_baseline_usefulness_not_explicit_high"
                    )
                if (
                    semantic_judgments["mechanism_match"] == "low"
                    and semantic_judgments["intervention_interface_match"] == "low"
                ):
                    core_blockers.append("mechanism_and_interface_mismatch")
                core_blockers.extend(_core_availability_blockers(candidate, item))
                reason = (
                    str(item.get("reason") or "").strip()
                    or "Selected by the semantic direct-baseline verifier."
                )
                if not extended_verification.get("fulltext_verified"):
                    reason = (
                        "Potential comparison candidate requiring candidate-full-text "
                        f"verification: {reason}"
                    )
                tier = "core"
                confidence = "high"
                fill_source = "model_selection"
                if core_blockers:
                    if not extended_eligible:
                        model_selection_audit.append(
                            {
                                "candidate_id": candidate_id,
                                "title": title,
                                "decision": "model_selected_but_extended_gate_failed",
                                "core_blockers": core_blockers,
                                "reason": extended_verification.get("reason"),
                            }
                        )
                        model_selected_title_keys.add(title_key)
                        seen_titles.add(title_key)
                        continue
                    tier = "extended"
                    confidence = "medium"
                    fill_source = "model_selection_downgraded_extended"
                    verification = {
                        **extended_verification,
                        "status": "model_selected_downgraded_from_core",
                        "core_blockers": core_blockers,
                        "model_confidence": item_confidence or "missing",
                        "model_task_protocol_relevance": (
                            task_protocol_relevance or "missing"
                        ),
                        "model_runnability": runnability or "missing",
                        "selector_requested_tier": selector_requested_tier or "missing",
                        "selector_semantic_judgments": semantic_judgments,
                    }
                else:
                    verification = {
                        **(extended_verification if extended_eligible else {}),
                        "status": "model_selected_grounded_core",
                        "task_match": semantic_judgments["same_task"],
                        "protocol_match": semantic_judgments["same_protocol"],
                        "model_confidence": item_confidence,
                        "model_task_protocol_relevance": task_protocol_relevance,
                        "model_runnability": runnability or "unspecified",
                        "selector_requested_tier": selector_requested_tier or "missing",
                        "selector_semantic_judgments": semantic_judgments,
                        "core_blockers": [],
                        "human_review_required": True,
                    }
                entry = _decorate_two_tier_candidate(
                    candidate,
                    retrieval_plan=retrieval_plan or {},
                    tier=tier,
                    confidence=confidence,
                    reason=reason,
                    verification=verification,
                    fill_source=fill_source,
                )
                if mechanism_branch:
                    entry["mechanism_branch"] = mechanism_branch
                    entry["mechanism_branch_normalized"] = (
                        _normalized_mechanism_branch(mechanism_branch)
                    )
                planning_relevance = str(
                    candidate.get("task_protocol_relevance") or ""
                ).strip().lower()
                entry["task_protocol_relevance"] = (
                    task_protocol_relevance or "missing"
                )
                if planning_relevance:
                    entry["planning_task_protocol_relevance"] = planning_relevance
                if runnability:
                    entry["runnability"] = runnability
                entry["model_selection_rank"] = model_rank
                entry["_selection_input_rank"] = int(candidate_id[1:])
                if tier == "core":
                    model_core_selected.append(entry)
                else:
                    model_extended_selected.append(entry)
                model_selected_title_keys.add(title_key)
                seen_titles.add(title_key)
                continue
            entry = dict(candidate)
            entry["semantic_relevance"] = "direct_baseline_candidate"
            entry["comparison_role"] = "direct_baseline"
            entry["selection_reason"] = str(item.get("reason") or "").strip()
            selected.append(entry)
            seen_titles.add(title_key)
            if len(selected) >= BASELINE_EVALUATION_CAP:
                break

    if bibliography_mode:
        model_selected_count = len(model_core_selected) + len(
            model_extended_selected
        )
        _core_preview, mechanism_diversity = _mechanism_diversity_reorder(
            model_core_selected,
            retrieval_plan=retrieval_plan or {},
        )

        # Evaluate the complete shortlist before applying any remaining Top-10
        # capacity.  The previous first-ten loop made shortlist/lexical order a
        # hidden selection policy whenever the semantic selector returned no
        # records, collapsing the visible view into one mechanism family.
        extended_gate_audit: list[dict[str, Any]] = []
        deterministic_extended_pool: list[dict[str, Any]] = []
        for candidate_index, candidate in enumerate(shortlist, start=1):
            candidate_id = f"R{candidate_index}"
            title = str(candidate.get("title") or "").strip()
            title_key = " ".join(title.lower().split())
            if (
                not title
                or title_key in model_selected_title_keys
            ):
                continue
            if selector_contract_mode and candidate_id not in assessed_candidate_ids:
                extended_gate_audit.append(
                    {
                        "candidate_id": candidate_id,
                        "title": title,
                        "retrieval_role": str(candidate.get("retrieval_role") or ""),
                        "decision": "selector_not_assessed",
                        "reason": (
                            "The complete-assessment contract omitted this candidate; "
                            "it is not assigned default weak semantics or ranked."
                        ),
                    }
                )
                continue
            eligible, verification = _extended_hard_gate(
                candidate,
                retrieval_plan or {},
                local_title=local_title,
                review_as_of=review_as_of,
            )
            audit_entry = {
                "candidate_id": candidate_id,
                "title": title,
                "retrieval_role": str(candidate.get("retrieval_role") or ""),
                "decision": verification.get("decision"),
                "reason": verification.get("reason"),
            }
            if not eligible:
                extended_gate_audit.append(audit_entry)
                continue
            entry = _decorate_two_tier_candidate(
                candidate,
                retrieval_plan=retrieval_plan or {},
                tier="extended",
                confidence="medium",
                reason=str(verification.get("reason") or ""),
                verification=verification,
                fill_source="unified_shortlist_hard_gate",
            )
            entry["_selection_input_rank"] = candidate_index
            deterministic_extended_pool.append(entry)

        eligible_extended_pool = [
            *model_extended_selected,
            *deterministic_extended_pool,
        ]
        _extended_preview, extended_mechanism_diversity = (
            _extended_diversity_reorder(
                eligible_extended_pool,
                limit=BASELINE_EVALUATION_CAP,
            )
        )
        # Core/Extended is an evidence label, not a pre-cap reservation policy.
        # Rank the complete visible pool together so high-relevance, distinct
        # Extended warnings can remain visible beside model-verified Core items.
        selected, evaluation_view_mechanism_diversity = (
            _extended_diversity_reorder(
                [*model_core_selected, *eligible_extended_pool],
                limit=BASELINE_EVALUATION_CAP,
            )
        )
        core_candidate_count = sum(
            item.get("tier") == "core" for item in selected
        )
        retained_extended = [
            item for item in selected if item.get("tier") == "extended"
        ]
        model_extended_retained_count = sum(
            item.get("fill_source") == "model_selection_downgraded_extended"
            for item in retained_extended
        )
        deterministic_fill_count = sum(
            item.get("fill_source") == "unified_shortlist_hard_gate"
            for item in retained_extended
        )
        selected_title_keys = {
            _normalized_phrase(item.get("title")) for item in selected
        }
        extended_omitted_by_cap_count = sum(
            _normalized_phrase(item.get("title")) not in selected_title_keys
            for item in eligible_extended_pool
        )

        selected_count = len(selected)
        evaluation_view_status = (
            "at_cap"
            if selected_count >= BASELINE_EVALUATION_CAP
            else "insufficient_candidates"
        )
        if not selected_count:
            selection_status = "no_eligible_candidates"
        elif evaluation_view_status == "insufficient_candidates":
            selection_status = "insufficient_candidates"
        else:
            selection_status = "completed"
        policy = (
            "two_tier_unified_pool_with_citation_graph"
            if has_relation_candidates
            else "two_tier_unified_pool_direct_queries"
        )
        return selected, {
            "selection_status": selection_status,
            "selection_candidate_count": len(shortlist),
            "semantic_candidate_limit": BASELINE_SEMANTIC_CANDIDATE_LIMIT,
            "bibliography_candidate_count": len(bibliography_candidates),
            "bibliography_candidates_sent_to_model": (
                bibliography_candidates_sent
            ),
            "bibliography_candidates_truncated": bibliography_truncated,
            "preselector_unified_pool": preselector_pool_diagnostics,
            "selected_record_count": selected_count,
            "selected_roles": {"direct_baseline": selected_count},
            "selection_policy": policy,
            "evaluation_view_cap": BASELINE_EVALUATION_CAP,
            "evaluation_view_status": evaluation_view_status,
            "core_candidate_count": core_candidate_count,
            "extended_candidate_count": len(retained_extended),
            "model_selected_count": model_selected_count,
            "model_core_selected_count": len(model_core_selected),
            "model_core_retained_count": sum(
                item.get("fill_source") == "model_selection"
                for item in selected
            ),
            "model_extended_selected_count": len(model_extended_selected),
            "model_extended_retained_count": model_extended_retained_count,
            "model_selected_retained_count": sum(
                str(item.get("fill_source") or "").startswith("model_selection")
                for item in selected
            ),
            "deterministic_fill_count": deterministic_fill_count,
            "deterministic_extended_eligible_count": len(
                deterministic_extended_pool
            ),
            "extended_eligible_pool_count": len(eligible_extended_pool),
            "extended_omitted_by_cap_count": extended_omitted_by_cap_count,
            "core_double_high_required": True,
            "core_high_high_runnable_required": True,
            "core_candidate_fulltext_required": True,
            "comparison_purpose_policy": (
                "multi_label_grounded_purpose_core_requires_direct_performance"
            ),
            "comparison_purpose_counts": {
                purpose: sum(
                    purpose in (item.get("comparison_purposes") or [])
                    for item in selected
                )
                for purpose in BASELINE_COMPARISON_PURPOSES
            },
            "evidence_level_counts": {
                level: sum(item.get("evidence_level") == level for item in selected)
                for level in (
                    "discovered",
                    "abstract_screened",
                    "fulltext_verified",
                )
            },
            "fulltext_verified_candidate_count": sum(
                item.get("fulltext_verified") is True for item in selected
            ),
            "candidate_to_verify_count": sum(
                item.get("candidate_label") == "candidate_to_verify"
                for item in selected
            ),
            "mechanism_diversity": mechanism_diversity,
            "extended_mechanism_diversity": extended_mechanism_diversity,
            "evaluation_view_mechanism_diversity": (
                evaluation_view_mechanism_diversity
            ),
            "evaluation_candidate_utility_trace": list(
                evaluation_view_mechanism_diversity.get(
                    "candidate_utility_trace", []
                )
            ),
            "evaluation_cap_omission_count": len(
                evaluation_view_mechanism_diversity.get("cap_omissions", [])
            ),
            "evaluation_cap_omissions": list(
                evaluation_view_mechanism_diversity.get("cap_omissions", [])
            ),
            "evaluation_unique_eligible_candidate_count": len(
                evaluation_view_mechanism_diversity.get(
                    "candidate_utility_trace", []
                )
            ),
            "evaluation_identity_deduplication_count": int(
                evaluation_view_mechanism_diversity.get(
                    "identity_deduplication_count", 0
                )
            ),
            "evaluation_identity_deduplications": list(
                evaluation_view_mechanism_diversity.get(
                    "identity_deduplications", []
                )
            ),
            "fill_sources": {
                "model_selection": sum(
                    item.get("fill_source") == "model_selection" for item in selected
                ),
                "unified_shortlist_hard_gate": deterministic_fill_count,
                **(
                    {
                        "model_selection_downgraded_extended": (
                            model_extended_retained_count
                        )
                    }
                    if model_extended_retained_count
                    else {}
                ),
            },
            "insufficient_candidates": selected_count < BASELINE_EVALUATION_CAP,
            "selector_error": selection_error or None,
            "selector_contract": (
                "complete_batched_assessments"
                if selector_complete_assessment_contract
                else "legacy_selected_only_fail_closed"
                if selector_contract_mode
                else "legacy_selected_only"
            ),
            "selector_batch_size": BASELINE_SELECTOR_BATCH_SIZE,
            "selector_batch_strategy": selector_batch_strategy,
            "selector_batch_sizes": [
                int(batch.get("expected_count") or 0)
                for batch in selector_batch_diagnostics
            ],
            "selector_configured_workers": selector_configured_workers,
            "selector_effective_workers": selector_effective_workers,
            "selector_stage_wall_seconds": selector_stage_wall_seconds,
            "selector_batch_wall_seconds_sum": (
                selector_batch_wall_seconds_sum
            ),
            "selector_batches": selector_batch_diagnostics,
            "selector_assessed_candidate_count": len(assessed_candidate_ids),
            "selector_not_assessed_candidate_ids": (
                sorted(set(by_id) - assessed_candidate_ids)
                if selector_contract_mode
                else []
            ),
            "availability_warning_count": sum(
                bool(item.get("availability_warnings")) for item in selected
            ),
            "availability_warning_records": [
                {
                    "title": str(item.get("title") or ""),
                    "warnings": list(item.get("availability_warnings") or []),
                    "tier": str(item.get("tier") or ""),
                }
                for item in selected
                if item.get("availability_warnings")
            ],
            "low_confidence_internal_audit_count": (
                len(extended_gate_audit) + len(model_selection_audit)
            ),
            "low_confidence_internal_audit": (
                model_selection_audit + extended_gate_audit
            ),
        }

    # Legacy no-bibliography mode is retained for compatibility with frozen Core
    # callers. The standalone CLI always uses the two-tier bibliography mode.
    used_fallback = False
    if not selected:
        used_fallback = True
        for candidate in shortlist[:4]:
            title = str(candidate.get("title") or "").strip()
            title_key = " ".join(title.lower().split())
            if not title or title_key in seen_titles:
                continue
            entry = dict(candidate)
            entry["semantic_relevance"] = "fallback_candidate_to_check"
            entry["comparison_role"] = "direct_baseline"
            entry["selection_reason"] = (
                "Retained from a dedicated direct-baseline query after the semantic "
                "selector returned no candidates; requires manual relevance review."
            )
            selected.append(entry)
            seen_titles.add(title_key)
            if len(selected) >= 4:
                break
    return selected, {
        "selection_status": (
            "fallback_ranked_candidates" if used_fallback else "completed"
        ),
        "selection_candidate_count": len(shortlist),
        "selected_record_count": len(selected),
        "selected_roles": {"direct_baseline": len(selected)},
        "selection_policy": (
            "unified_pool_with_citation_graph_candidates"
            if has_relation_candidates
            else "unified_pool_direct_queries_only"
        ),
        "preselector_unified_pool": preselector_pool_diagnostics,
    }
