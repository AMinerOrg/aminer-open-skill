"""Conservative classification of retrieved baseline candidates."""

from __future__ import annotations

import json
from typing import Any, Callable

from .anchors import anchor_catalog_text, experiment_anchor_catalog


ELIGIBLE_RETRIEVAL_ROLES = {
    "direct_baseline",
    "method_precedent",
    "alternative_formulation",
}
VALID_STATUSES = {
    "compared_in_experiments",
    "mentioned_not_compared",
    "candidate_to_check",
    "not_assessable",
    "not_direct_baseline",
}
JsonModel = Callable[..., dict[str, Any]]
BASELINE_EVALUATION_CAP = 10


def select_baseline_candidates(
    records: list[dict[str, Any]], *, limit: int = BASELINE_EVALUATION_CAP
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        role = str(record.get("comparison_role") or "").lower()
        if role not in ELIGIBLE_RETRIEVAL_ROLES:
            continue
        title = str(record.get("title") or "").strip()
        title_key = " ".join(title.lower().split())
        if not title or title_key in seen_titles:
            continue
        entry: dict[str, Any] = {
            "candidate_id": f"B{len(selected) + 1}",
            "title": title,
            "authors": str(record.get("authors") or ""),
            "published": str(record.get("published") or ""),
            "source": str(record.get("source") or ""),
            "url": str(record.get("url") or ""),
            "summary": str(record.get("summary") or ""),
            "retrieval_role": str(record.get("retrieval_role") or ""),
            "comparison_role": role,
            "selection_reason": str(record.get("selection_reason") or ""),
        }
        for key in (
            "tier",
            "confidence",
            "candidate_label",
            "missing_status",
            "fill_source",
            "mechanism_branch",
            "mechanism_branch_normalized",
            "task_protocol_relevance",
            "planning_task_protocol_relevance",
            "runnability",
            "evidence_level",
            "fulltext_verified",
            "adaptation_required",
            "adaptation_note",
        ):
            if record.get(key) not in (None, ""):
                entry[key] = record.get(key)
        for key in ("comparison_purposes", "evidence_sources"):
            if isinstance(record.get(key), list):
                entry[key] = list(record.get(key) or [])
        if isinstance(record.get("comparison_purpose_evidence"), dict):
            entry["comparison_purpose_evidence"] = dict(
                record.get("comparison_purpose_evidence") or {}
            )
        for key in ("verification", "selection_evidence"):
            value = record.get(key)
            if isinstance(value, dict):
                entry[key] = dict(value)
        if isinstance(record.get("availability_warnings"), list):
            entry["availability_warnings"] = list(
                record.get("availability_warnings") or []
            )
        for key in (
            "aminer_pub_id",
            "year",
            "publication_year",
            "publication_date_precision",
            "venue",
            "venue_id",
            "doi",
            "cutoff_status",
            "aminer_cutoff_status",
            "aminer_publication_date_precision",
            "availability_evidence",
            "requires_cutoff_verification",
            "bibliography_tei_id",
            "bibliography_year",
            "citation_ref_target",
            "citation_ref_label",
            "local_citation_before_review_cutoff",
        ):
            if record.get(key) not in (None, ""):
                entry[key] = record.get(key)
        relation_evidence = record.get("relation_evidence")
        is_relation_candidate = bool(
            isinstance(relation_evidence, dict)
            or record.get("relation_direction")
            or str(record.get("retrieval_role") or "").startswith("citation_graph_")
        )
        if is_relation_candidate:
            entry.update(
                {
                    "aminer_pub_id": str(record.get("aminer_pub_id") or ""),
                    "year": record.get("year"),
                    "publication_year": record.get("publication_year"),
                    "publication_date_precision": str(
                        record.get("publication_date_precision") or ""
                    ),
                    "venue": str(record.get("venue") or ""),
                    "venue_id": str(record.get("venue_id") or ""),
                    "cutoff_status": str(record.get("cutoff_status") or ""),
                    "relation_direction": str(
                        record.get("relation_direction") or ""
                    ),
                    "relation_target_pub_id": str(
                        record.get("relation_target_pub_id") or ""
                    ),
                    "relation_evidence": (
                        dict(relation_evidence)
                        if isinstance(relation_evidence, dict)
                        else None
                    ),
                }
            )
        selected.append(entry)
        seen_titles.add(title_key)
        if len(selected) >= limit:
            break
    return selected


def normalize_baseline_audit(
    candidates: list[dict[str, Any]],
    payload: dict[str, Any] | None,
    anchor_catalog: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    two_tier_mode = any(
        isinstance(candidate, dict) and "tier" in candidate
        for candidate in candidates
    )
    raw_items = payload.get("records") if isinstance(payload, dict) else []
    raw_by_id = {
        str(item.get("candidate_id") or ""): item
        for item in raw_items
        if isinstance(item, dict)
    } if isinstance(raw_items, list) else {}
    raw_statuses = {
        str(item.get("candidate_id") or ""): str(item.get("status") or "")
        for item in raw_items
        if isinstance(item, dict)
    } if isinstance(raw_items, list) else {}
    records: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id") or "")
        raw = raw_by_id.get(candidate_id, {})
        tier = str(candidate.get("tier") or "").lower()
        default_status = (
            "candidate_to_check" if tier == "extended" else "not_assessable"
        )
        status = str(raw.get("status") or default_status).lower()
        if status not in VALID_STATUSES:
            status = default_status
        anchor_id = str(raw.get("anchor_id") or "").upper().strip()
        source = anchor_catalog.get(anchor_id)
        relation_evidence = (
            candidate.get("relation_evidence")
            if isinstance(candidate.get("relation_evidence"), dict)
            else None
        )
        relation_supports_mention = bool(
            relation_evidence
            and candidate.get("relation_direction") == "target_references_candidate"
        )
        if status == "compared_in_experiments" and not source:
            status = "not_assessable"
        if status == "mentioned_not_compared" and not (
            source or relation_supports_mention
        ):
            status = default_status
        # Extended records are medium-confidence review leads. Even when the
        # classifier sees a mention without a local experiment anchor, do not
        # turn that into a stronger omission claim.
        if tier == "extended" and status in {
            "mentioned_not_compared",
            "not_assessable",
        }:
            status = "candidate_to_check"
        missing_status = str(candidate.get("missing_status") or "unknown")
        if two_tier_mode:
            if status == "compared_in_experiments":
                missing_status = "already_compared"
            elif status == "mentioned_not_compared":
                missing_status = "cited_not_compared"
        record: dict[str, Any] = {
            **candidate,
            "status": status,
            "reason": str(raw.get("reason") or "")[:900],
            "anchor": (
                {
                    "anchor_id": anchor_id,
                    "page": source["page"],
                    "quote": source["quote"],
                }
                if source
                else None
            ),
        }
        if two_tier_mode:
            record["missing_status"] = missing_status
        if relation_evidence:
            record["evidence_basis"] = (
                "local_experiment_anchor"
                if source
                else "aminer_citation_graph"
                if status == "mentioned_not_compared" and relation_supports_mention
                else None
            )
        if status == "candidate_to_check" and not record["reason"]:
            selection_reason = str(
                candidate.get("selection_reason") or ""
            ).strip()
            if candidate.get("candidate_label") == "candidate_to_verify":
                record["reason"] = selection_reason or (
                    "This is a potential comparison candidate supported only by "
                    "discovery, abstract, or citation-context evidence. Candidate "
                    "full text and any required adaptation remain to be verified."
                )
            else:
                record["reason"] = selection_reason or (
                    "This plausible external baseline was not observed in the extracted "
                    "experimental evidence. It is an author-review candidate, not a "
                    "finding that comparison is required."
                )
        if status == "not_assessable" and not record["reason"]:
            record["reason"] = (
                "The extracted experiment evidence was insufficient to classify this candidate."
            )
        records.append(record)
    counts = {
        status: sum(item["status"] == status for item in records)
        for status in sorted(VALID_STATUSES)
    }
    tier_counts = {
        tier: sum(str(item.get("tier") or "core") == tier for item in records)
        for tier in ("core", "extended")
    }
    confidence_counts = {
        confidence: sum(
            str(item.get("confidence") or "") == confidence for item in records
        )
        for confidence in ("high", "medium")
    }
    evaluation_view_status = (
        "at_cap"
        if len(records) >= BASELINE_EVALUATION_CAP
        else "insufficient_candidates"
    )
    limitations = [
        "This audit checks whether a retrieved candidate is visibly compared in extracted experiment evidence.",
        "A candidate_to_check is not a finding that a baseline is required or that the experiment is inadequate.",
        "Discovery metadata, paper_detail, abstracts, bibliography entries, and citation contexts do not count as candidate full text; records marked candidate_to_verify require candidate-full-text verification before Core use.",
        "Aliases, incomplete tables, and PDF extraction can prevent a comparison from being observed.",
    ]
    if two_tier_mode:
        limitations.insert(
            2,
            "The evaluation view is capped at ten; Extended candidates passed a deterministic evidence/comparison-purpose gate and may include cross-task leads that require explicit adaptation and human verification.",
        )
    if any(
        isinstance(candidate.get("relation_evidence"), dict)
        for candidate in candidates
    ):
        limitations.insert(
            1,
            "AMiner target_references_candidate evidence can support a mentioned_not_compared label, but citation-graph membership never proves an experimental comparison.",
        )
    if any(
        candidate.get("cutoff_status") == "uncertain_same_year"
        for candidate in candidates
    ):
        limitations.insert(
            1,
            "AMiner supplied only a publication year for at least one cutoff-year candidate; it is retained as uncertain_same_year and requires human date verification.",
        )
    result = {
        "schema_version": "0.1",
        "status": "completed" if records else "not_assessed",
        "summary": {"candidates_checked": len(records), **counts},
        "records": records,
        "normalization_diagnostics": {
            "model_records_received": len(raw_items) if isinstance(raw_items, list) else 0,
            "model_candidate_ids": sorted(raw_by_id),
            "model_statuses": raw_statuses,
        },
        "limitations": limitations,
    }
    if two_tier_mode:
        result["summary"].update(
            {
                "tiers": tier_counts,
                "confidence": confidence_counts,
                "evaluation_view_cap": BASELINE_EVALUATION_CAP,
                "evaluation_view_status": evaluation_view_status,
                "insufficient_candidates": len(records) < BASELINE_EVALUATION_CAP,
            }
        )
        result["evaluation_view"] = {
            "max_candidates": BASELINE_EVALUATION_CAP,
            "status": evaluation_view_status,
            "candidate_ids": [
                str(item.get("candidate_id") or "") for item in records
            ],
        }
    return result


def run_baseline_audit(
    *,
    baseline_candidates: list[dict[str, Any]],
    pages: list[str],
    source_locations: list[dict[str, Any]] | None,
    local_title: str,
    retrieval_plan: dict[str, Any],
    retrieval_queries: list[str],
    retrieval_diagnostics: dict[str, Any],
    llm_json: JsonModel,
) -> dict[str, Any]:
    candidates = select_baseline_candidates(baseline_candidates)
    catalog = experiment_anchor_catalog(pages, source_locations)
    has_relation_candidates = any(
        isinstance(candidate.get("relation_evidence"), dict)
        for candidate in candidates
    )

    def decorate(audit: dict[str, Any]) -> dict[str, Any]:
        audit["experiment_anchor_count"] = len(catalog)
        audit["candidate_source"] = (
            "dedicated_baseline_retrieval_with_optional_aminer_citation_graph"
            if has_relation_candidates
            else "dedicated_baseline_retrieval"
        )
        audit["retrieval_plan"] = retrieval_plan
        audit["retrieval_queries"] = retrieval_queries
        audit["retrieval_diagnostics"] = retrieval_diagnostics
        return audit

    if not candidates:
        audit = normalize_baseline_audit([], None, catalog)
        audit["limitations"].append(
            "No retrieved records were classified as plausible direct-baseline candidates."
        )
        return decorate(audit)
    if not catalog:
        audit = normalize_baseline_audit(candidates, None, catalog)
        audit["limitations"].append(
            "No locally extracted experimental pages were available for comparison checking."
        )
        audit["status"] = "not_assessed"
        return decorate(audit)
    mentioned_rule = '''- `mentioned_not_compared`: the candidate is visibly named in the supplied
  experiment scope but no comparison result is shown. Select the anchor.'''
    inference_rule = '''- Never infer a comparison from a reference list, topical similarity, or an
  external abstract alone. Do not invent aliases or anchors.'''
    if has_relation_candidates:
        mentioned_rule = '''- `mentioned_not_compared`: the candidate is visibly named in the supplied
  experiment scope but no comparison result is shown. Select the anchor. It may
  also be used without a local anchor when the candidate has explicit
  `target_references_candidate` AMiner relation evidence; in that case say that
  the citation graph, not local experiment text, is the evidence.'''
        inference_rule = '''- Never infer a comparison from a reference list, topical similarity, or an
  external abstract alone. A candidate that merely cites the target does not
  prove that the target mentions it. Do not invent aliases or anchors.'''
    prompt = f'''Return valid JSON only, exactly in this outer schema:
{{"records":[{{"candidate_id":"B1","status":"compared_in_experiments|mentioned_not_compared|candidate_to_check|not_assessable|not_direct_baseline","anchor_id":"P1S1 or empty","reason":""}}]}}

You are auditing whether plausible externally retrieved methods are visibly
compared in a manuscript's extracted experimental evidence. This is a
conservative author-assistance check, not an experimental-quality score.

Return exactly one item in `records` for every supplied candidate ID. Do not
rename `records`, omit a candidate, or add other top-level keys.

Rules:
- `compared_in_experiments`: the supplied local experiment span explicitly
  reports, tabulates, plots, or otherwise evaluates the candidate (including a
  clearly stated alias). Select the supporting anchor.
{mentioned_rule}
- `candidate_to_check`: the candidate has at least one recorded potential
  comparison purpose, but it was not observed in the supplied experiment scope.
  A cross-task or non-full-text candidate still requires explicit adaptation or
  candidate-full-text verification. This is neutral: never say it is required
  or that the experiment is inadequate.
- `not_direct_baseline`: the candidate is merely broad background and has no
  evidence-grounded comparison purpose. A different terminal task alone is not
  enough for this label when a component-level adapted purpose is recorded.
- `not_assessable`: the supplied evidence cannot support a safe classification.
{inference_rule}

PAPER TITLE:
{local_title}

EXTERNAL CANDIDATES:
{json.dumps(candidates, ensure_ascii=False)}

LOCAL EXPERIMENT EVIDENCE (anchor IDs are the only valid local evidence):
{anchor_catalog_text(catalog)}
'''
    try:
        payload = llm_json(
            "You perform conservative, evidence-grounded baseline comparison audits. Return JSON only.",
            prompt,
            max_tokens=2200,
        )
    except Exception as exc:
        audit = normalize_baseline_audit(candidates, None, catalog)
        audit["limitations"].append(
            f"Baseline audit model call failed: {type(exc).__name__}."
        )
        audit["status"] = "not_assessed"
        return decorate(audit)
    return decorate(normalize_baseline_audit(candidates, payload, catalog))
