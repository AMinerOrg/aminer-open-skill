"""Backward-reference expansion through the public AMiner Open Platform."""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

import httpx

from .aminer import normalize_pub_id
from .aminer_open import (
    AMINER_API_COST_CNY,
    AMINER_PAPER_INFO_URL,
    AMINER_PAPER_RELATION_URL,
    AMinerAPIError,
    aminer_api_key,
    aminer_headers,
    checked_payload,
    merge_paper_metadata,
    normalize_paper_record,
    paper_id,
    rows_from_payload,
)


PAPER_INFO_BATCH_LIMIT = 100
ClientFactory = Callable[..., Any]


def publication_cutoff_status(published: str, review_as_of: str) -> str:
    """Classify a date without pretending that a year-only value has a day."""
    cutoff = date.fromisoformat(review_as_of)
    value = str(published or "").strip()
    try:
        exact = date.fromisoformat(value[:10])
    except ValueError:
        exact = None
    if exact is not None:
        return "eligible" if exact <= cutoff else "after_cutoff"
    if len(value) == 4 and value.isdigit():
        year = int(value)
        if year < cutoff.year:
            return "eligible"
        if year > cutoff.year:
            return "after_cutoff"
        return "uncertain_same_year"
    return "undated"


def _cited_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract only the documented target -> cited papers edge list."""
    data: Any = payload.get("data")
    containers = data if isinstance(data, list) else [data]
    cited: list[dict[str, Any]] = []
    for container in containers:
        if not isinstance(container, dict):
            continue
        value = container.get("cited")
        if isinstance(value, list):
            cited.extend(
                item if isinstance(item, dict) else {"id": item}
                for item in value
                if isinstance(item, (dict, str))
            )
        elif isinstance(value, dict):
            cited.append(value)
    return cited


def _error_text(exc: Exception) -> str:
    if isinstance(exc, AMinerAPIError):
        return str(exc)
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__


def retrieve_aminer_relation_candidates(
    target_pub_id: str,
    *,
    review_as_of: str,
    api_key: str | None = None,
    proxy: str | None = None,
    client_factory: ClientFactory = httpx.Client,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return public backward references and never claim forward citations."""
    target = normalize_pub_id(target_pub_id)
    credential = aminer_api_key(api_key)
    diagnostics: dict[str, Any] = {
        "enabled": True,
        "target_pub_id": target,
        "provider": "AMiner Open Platform",
        "relation_endpoint": "paper_relation",
        "metadata_endpoint": "paper_info",
        "supported_directions": ["target_references_candidate"],
        "unsupported_directions": ["candidate_cites_target"],
        "forward_citations_available": False,
        "review_as_of": review_as_of,
        "provider_errors": [],
        "api_calls": {"paper_relation": 0, "paper_info": 0},
        "estimated_cost_cny_by_api": {"paper_relation": 0.0, "paper_info": 0.0},
        "estimated_cost_cny": 0.0,
        "relation_get_count": 0,
        "relation_get_completed_count": 0,
        "paper_info_post_count": 0,
        "paper_info_post_completed_count": 0,
        "total_http_request_count": 0,
        "relation_edge_count": 0,
        "unique_related_id_count": 0,
        "paper_info_record_count": 0,
        "candidate_record_count": 0,
        "uncertain_same_year_count": 0,
        "excluded_after_cutoff_count": 0,
        "undated_count": 0,
        "excluded_records": [],
        "metadata_missing_ids": [],
    }
    if not credential:
        diagnostics["status"] = "unavailable_missing_api_key"
        diagnostics["provider_errors"].append(
            "AMINER_API_KEY is unavailable; backward-reference expansion was skipped."
        )
        return [], diagnostics

    headers = aminer_headers(credential)
    try:
        with client_factory(
            timeout=httpx.Timeout(30.0, connect=10.0),
            proxy=proxy,
            follow_redirects=True,
            trust_env=proxy is not None,
        ) as client:
            diagnostics["relation_get_count"] = 1
            diagnostics["total_http_request_count"] += 1
            diagnostics["api_calls"]["paper_relation"] = 1
            diagnostics["estimated_cost_cny_by_api"]["paper_relation"] = (
                AMINER_API_COST_CNY["paper_relation"]
            )
            try:
                payload = checked_payload(
                    client.get(
                        AMINER_PAPER_RELATION_URL,
                        params={"id": target},
                        headers=headers,
                    ),
                    endpoint="paper_relation",
                )
                diagnostics["relation_response_metadata"] = {
                    "code": payload.get("code"),
                    "msg": payload.get("msg") or payload.get("message"),
                    "log_id": payload.get("log_id"),
                    "total": payload.get("total"),
                }
                relation_rows = _cited_rows(payload)
                diagnostics["relation_get_completed_count"] = 1
            except Exception as exc:
                diagnostics["provider_errors"].append(
                    f"paper_relation target_references_candidate: {_error_text(exc)}"
                )
                diagnostics["status"] = "failed"
                diagnostics["estimated_cost_cny"] = 0.10
                return [], diagnostics

            relation_records: list[dict[str, Any]] = []
            for row in relation_rows:
                normalized = normalize_paper_record(
                    row,
                    query=f"AMiner backward references from {target}",
                    source="AMiner Open Platform paper_relation",
                )
                if normalized:
                    relation_records.append(normalized)
                elif paper_id(row):
                    relation_records.append(
                        {
                            "aminer_pub_id": paper_id(row),
                            "title": "",
                            "authors": "",
                            "published": "",
                            "summary": "",
                            "query": f"AMiner backward references from {target}",
                            "source": "AMiner Open Platform paper_relation",
                        }
                    )
            related_ids = list(
                dict.fromkeys(
                    str(record.get("aminer_pub_id") or "")
                    for record in relation_records
                    if record.get("aminer_pub_id")
                )
            )
            diagnostics["relation_edge_count"] = len(relation_rows)
            diagnostics["unique_related_id_count"] = len(related_ids)

            metadata_by_id: dict[str, dict[str, Any]] = {}
            for offset in range(0, len(related_ids), PAPER_INFO_BATCH_LIMIT):
                batch = related_ids[offset : offset + PAPER_INFO_BATCH_LIMIT]
                diagnostics["paper_info_post_count"] += 1
                diagnostics["api_calls"]["paper_info"] += 1
                diagnostics["total_http_request_count"] += 1
                try:
                    info_payload = checked_payload(
                        client.post(
                            AMINER_PAPER_INFO_URL,
                            json={"ids": batch},
                            headers=headers,
                        ),
                        endpoint="paper_info",
                    )
                    for row in rows_from_payload(info_payload):
                        identifier = paper_id(row)
                        if identifier in batch:
                            metadata_by_id[identifier] = row
                    diagnostics["paper_info_post_completed_count"] += 1
                except Exception as exc:
                    diagnostics["provider_errors"].append(
                        f"paper_info: {_error_text(exc)}"
                    )
            diagnostics["paper_info_record_count"] = len(metadata_by_id)
            diagnostics["metadata_missing_ids"] = [
                identifier for identifier in related_ids if identifier not in metadata_by_id
            ]

            records: list[dict[str, Any]] = []
            for record in relation_records:
                identifier = str(record.get("aminer_pub_id") or "")
                if identifier in metadata_by_id:
                    merge_paper_metadata(record, metadata_by_id[identifier])
                if not str(record.get("title") or "").strip():
                    diagnostics["excluded_records"].append(
                        {
                            "aminer_pub_id": identifier,
                            "title": "",
                            "published": "",
                            "reason": "metadata_missing",
                        }
                    )
                    continue
                published = str(record.get("published") or "")
                cutoff_status = publication_cutoff_status(published, review_as_of)
                if cutoff_status == "after_cutoff":
                    diagnostics["excluded_after_cutoff_count"] += 1
                    diagnostics["excluded_records"].append(
                        {
                            "aminer_pub_id": identifier,
                            "title": record.get("title"),
                            "published": published,
                            "reason": "after_cutoff",
                        }
                    )
                    continue
                if cutoff_status == "undated":
                    diagnostics["undated_count"] += 1
                    diagnostics["excluded_records"].append(
                        {
                            "aminer_pub_id": identifier,
                            "title": record.get("title"),
                            "published": published,
                            "reason": "undated",
                        }
                    )
                    continue
                if cutoff_status == "uncertain_same_year":
                    diagnostics["uncertain_same_year_count"] += 1
                record.update(
                    {
                        "cutoff_status": cutoff_status,
                        "requires_cutoff_verification": cutoff_status
                        == "uncertain_same_year",
                        "retrieval_role": "citation_graph_reference",
                        "relation_direction": "target_references_candidate",
                        "relation_target_pub_id": target,
                        "relation_evidence": {
                            "provider": "AMiner Open Platform paper_relation",
                            "target_pub_id": target,
                            "related_pub_id": identifier,
                            "direction": "target_references_candidate",
                            "direction_scope": "backward_references_only",
                        },
                    }
                )
                records.append(record)
            diagnostics["candidate_record_count"] = len(records)
            diagnostics["estimated_cost_cny"] = round(
                sum(diagnostics["estimated_cost_cny_by_api"].values()), 2
            )
            diagnostics["status"] = (
                "completed" if not diagnostics["provider_errors"] else "partial"
            )
            diagnostics["time_policy"] = (
                "Exact dates after review_as_of and year-only values after the cutoff "
                "year are excluded. A year-only value in the cutoff year is retained "
                "as uncertain_same_year and requires human verification."
            )
            diagnostics["capability_limit"] = (
                "The public endpoint returns only papers cited by the target. Forward "
                "citations are unavailable and are not inferred."
            )
            return records, diagnostics
    except Exception as exc:
        diagnostics["provider_errors"].append(f"relation client: {_error_text(exc)}")
        diagnostics["status"] = "failed"
        return [], diagnostics
