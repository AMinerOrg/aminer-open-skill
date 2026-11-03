"""Public AMiner Open Platform adapters used by the standalone Skill.

The module deliberately keeps paper discovery, metadata enrichment, title
resolution, and citation lookup on documented ``open_platform`` endpoints.
It never treats a fuzzy title hit as a publication identity.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Callable

import httpx

from .aminer import AMINER_PUB_ID, normalize_pub_id
from .identity import aminer_headers


AMINER_OPEN_BASE_URL = "https://datacenter.aminer.cn/gateway/open_platform"
AMINER_PAPER_SEARCH_URL = f"{AMINER_OPEN_BASE_URL}/api/paper/search"
AMINER_PAPER_SEARCH_PRO_URL = f"{AMINER_OPEN_BASE_URL}/api/paper/search/pro"
AMINER_PAPER_QA_SEARCH_URL = f"{AMINER_OPEN_BASE_URL}/api/paper/qa/search"
AMINER_PAPER_QA_SEARCH_PRO_URL = f"{AMINER_OPEN_BASE_URL}/api/paper/qa/searchPro"
AMINER_PAPER_INFO_URL = f"{AMINER_OPEN_BASE_URL}/api/paper/info"
AMINER_PAPER_DETAIL_URL = f"{AMINER_OPEN_BASE_URL}/api/paper/detail"
AMINER_PAPER_RELATION_URL = f"{AMINER_OPEN_BASE_URL}/api/paper/relation"
AMINER_PAPER_LIST_BY_KEYWORDS_URL = (
    f"{AMINER_OPEN_BASE_URL}/api/paper/list/citation/by/keywords"
)

AMINER_API_COST_CNY: dict[str, float] = {
    "paper_search": 0.0,
    "paper_search_pro": 0.01,
    "paper_qa_search": 0.05,
    "paper_qa_search_pro": 0.30,
    "paper_info": 0.0,
    "paper_detail": 0.01,
    "paper_relation": 0.10,
    "paper_list_by_keywords": 0.10,
}
AMINER_SEARCH_TIERS = ("auto", "free", "search-pro", "qa-pro")
AMINER_QUERY_SHAPES = (
    "auto",
    "exact_title",
    "short_phrase",
    "fielded_phrase",
    "semantic_sentence",
)
ClientFactory = Callable[..., Any]


@dataclass
class AMinerAPIError(ValueError):
    """Structured provider error without exposing credentials."""

    endpoint: str
    code: str
    message: str
    http_status: int | None = None
    log_id: str = ""

    def __str__(self) -> str:
        suffix = f" HTTP {self.http_status}" if self.http_status is not None else ""
        trace = f" log_id={self.log_id}" if self.log_id else ""
        return f"AMiner {self.endpoint}{suffix} code {self.code}: {self.message}{trace}"

    @property
    def permission_or_balance(self) -> bool:
        text = f"{self.code} {self.message}".casefold()
        return self.http_status == 403 or self.code == "403" or any(
            marker in text
            for marker in (
                "permission",
                "department",
                "balance",
                "quota",
                "forbidden",
                "权限",
                "部门",
                "余额",
                "额度",
            )
        )


def aminer_api_key(value: str | None = None) -> str:
    return str(value or os.environ.get("AMINER_API_KEY") or "").strip()


def checked_payload(response: httpx.Response, *, endpoint: str) -> dict[str, Any]:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        message = ""
        log_id = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                message = str(body.get("msg") or body.get("message") or body.get("error") or "")
                log_id = str(body.get("log_id") or "")
        except Exception:
            message = response.text
        raise AMinerAPIError(
            endpoint,
            str(response.status_code),
            " ".join(message.split())[:240] or exc.response.reason_phrase,
            response.status_code,
            log_id,
        ) from exc
    payload = response.json()
    if not isinstance(payload, dict):
        raise AMinerAPIError(endpoint, "invalid_response", "non-object response")
    code = payload.get("code")
    if payload.get("success") is False or (
        code is not None and str(code) not in {"0", "200"}
    ):
        message = " ".join(
            str(payload.get("msg") or payload.get("message") or "request failed").split()
        )[:240]
        raise AMinerAPIError(
            endpoint,
            str(code),
            message,
            log_id=str(payload.get("log_id") or ""),
        )
    return payload


def rows_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Unwrap documented AMiner result lists and common gateway envelopes."""
    value: Any = payload.get("data", payload)
    for _ in range(6):
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if not isinstance(value, dict):
            return []
        if any(key in value for key in ("id", "paper_id", "_id", "title")):
            return [value]
        nested = next(
            (
                value[key]
                for key in ("items", "results", "list", "records", "data")
                if isinstance(value.get(key), (list, dict))
            ),
            None,
        )
        if nested is None:
            return []
        value = nested
    return []


def paper_id(row: dict[str, Any]) -> str:
    value = row.get("id") or row.get("paper_id") or row.get("_id")
    normalized = str(value or "").strip().lower()
    return normalized if AMINER_PUB_ID.fullmatch(normalized) else ""


def author_names(value: Any) -> str:
    if isinstance(value, str):
        return " ".join(value.split())
    if not isinstance(value, list):
        return ""
    names: list[str] = []
    for author in value:
        if isinstance(author, dict):
            name = author.get("name") or author.get("name_zh")
        else:
            name = author
        normalized = " ".join(str(name or "").split())
        if normalized:
            names.append(normalized)
    return ", ".join(names)


def venue_name(row: dict[str, Any]) -> str:
    direct = " ".join(str(row.get("venue_name") or "").split())
    if direct:
        return direct
    venue = row.get("venue")
    if isinstance(venue, dict):
        return " ".join(
            str(venue.get("name") or venue.get("display_name") or venue.get("raw") or "").split()
        )
    return " ".join(str(venue or "").split())


def normalize_paper_record(
    row: dict[str, Any], *, query: str, source: str
) -> dict[str, Any] | None:
    title = " ".join(str(row.get("title") or row.get("title_zh") or "").split())
    if not title:
        return None
    identifier = paper_id(row)
    published_raw = (
        row.get("publication_date")
        or row.get("published")
        or row.get("date")
        or row.get("year")
    )
    published_text = str(published_raw or "").strip()
    year = row.get("year") or (published_text[:4] if published_text else None)
    try:
        normalized_year: int | None = int(year)
    except (TypeError, ValueError):
        normalized_year = None
    authors = author_names(row.get("authors")) or " ".join(
        str(row.get("first_author") or "").split()
    )
    summary = " ".join(
        str(
            row.get("abstract")
            or row.get("abstract_slice")
            or row.get("abstract_zh")
            or row.get("abstract_zh_slice")
            or ""
        ).split()
    )[:1100]
    return {
        "aminer_pub_id": identifier,
        "title": title,
        "authors": authors,
        "published": (
            published_text[:10]
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", published_text)
            else str(normalized_year or "")
        ),
        "year": normalized_year,
        "publication_year": normalized_year,
        "publication_date_precision": (
            "day"
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", published_text)
            else "year"
            if normalized_year
            else "unknown"
        ),
        "venue": venue_name(row),
        "venue_id": str(row.get("venue_id") or ""),
        "doi": str(row.get("doi") or ""),
        "url": f"https://www.aminer.cn/pub/{identifier}" if identifier else "",
        "summary": summary,
        "query": query,
        "source": source,
    }


def merge_paper_metadata(record: dict[str, Any], row: dict[str, Any]) -> None:
    enriched = normalize_paper_record(
        row,
        query=str(record.get("query") or ""),
        source=str(record.get("source") or "AMiner Open Platform"),
    )
    if not enriched:
        return
    for key, value in enriched.items():
        if value not in (None, "", [], {}):
            record[key] = value


def _looks_like_sentence(query: str) -> bool:
    normalized = " ".join(query.split()).strip()
    if not normalized:
        return False
    if normalized.endswith(("?", "。", "？")):
        return True
    first = re.findall(r"[a-z]+", normalized.casefold())[:1]
    if first and first[0] in {
        "find", "identify", "retrieve", "list", "show", "which", "what",
        "how", "where", "compare", "discover", "recommend",
    }:
        return True
    return len(normalized.split()) >= 12


def classify_query_shape(
    query: str,
    *,
    query_shape: str = "auto",
    desired_results: int = 20,
) -> tuple[str, str]:
    """Classify a query using the public AMiner endpoint contracts."""
    requested = str(query_shape or "auto").strip().lower().replace("-", "_")
    if requested not in AMINER_QUERY_SHAPES:
        raise ValueError(f"Unknown AMiner query shape: {query_shape}")
    if requested != "auto":
        return requested, "explicit_query_shape"
    if _looks_like_sentence(query):
        return "semantic_sentence", "natural_language_sentence"
    if int(desired_results) > 20:
        return "fielded_phrase", "bulk_result_request"
    word_count = len(re.findall(r"[A-Za-z0-9]+", query))
    if word_count <= 5:
        return "short_phrase", "short_title_or_method_phrase"
    return "fielded_phrase", "controlled_multi_term_phrase"


def _fallback_phrase(query: str, *, limit: int = 7) -> str:
    """Build a bounded literal fallback without pretending it is semantic search."""
    tokens = [
        token
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9+_.-]*", query)
        if token.casefold()
        not in {
            "find", "identify", "retrieve", "list", "show", "which", "what",
            "how", "where", "compare", "discover", "recommend", "papers",
            "paper", "methods", "method", "that", "the", "for", "with",
            "under", "same", "using", "available", "before", "work",
        }
    ]
    return " ".join(tokens[:limit]) or " ".join(query.split()[:limit])


def _search_ladder(tier: str, query_shape: str) -> tuple[str, ...]:
    """Return an AMiner-only route; auto never probes an unavailable QA-Pro."""
    normalized = tier.strip().lower()
    if normalized not in AMINER_SEARCH_TIERS:
        raise ValueError(f"Unknown AMiner search tier: {tier}")
    if normalized == "free":
        return ("paper_search",)
    if normalized == "search-pro":
        return ("paper_search_pro", "paper_search")
    if normalized == "qa-pro":
        return (
            "paper_qa_search_pro",
            "paper_qa_search",
            "paper_search_pro",
            "paper_search",
        )
    if query_shape in {"exact_title", "short_phrase"}:
        return ("paper_search",)
    if query_shape == "fielded_phrase":
        return ("paper_search_pro", "paper_search")
    return ("paper_qa_search", "paper_search_pro", "paper_search")


def _call_search_endpoint(
    endpoint: str,
    *,
    query: str,
    year_to: int,
    client: Any,
    headers: dict[str, str],
    desired_results: int = 20,
    search_field: str = "keyword",
    query_shape: str = "auto",
) -> tuple[dict[str, Any], dict[str, Any]]:
    literal_query = _fallback_phrase(query)
    if endpoint == "paper_qa_search_pro":
        request_body = {
            "query": query,
            "query_type": "auto",
            "year_to": year_to,
            "sort": "relevance",
        }
        response = client.post(
            AMINER_PAPER_QA_SEARCH_PRO_URL,
            json=request_body,
            headers=headers,
        )
        request_shape = {
            "method": "POST",
            "parameter_names": list(request_body),
            "query_parameter": "query",
            "query_type": "auto",
            "result_limit": 10,
        }
    elif endpoint == "paper_qa_search":
        request_body = {
            "use_topic": True,
            "query": query,
            "size": min(max(1, int(desired_results)), 100),
            "offset": 0,
        }
        response = client.post(
            AMINER_PAPER_QA_SEARCH_URL,
            json=request_body,
            headers=headers,
        )
        request_shape = {
            "method": "POST",
            "parameter_names": list(request_body),
            "query_parameter": "query",
            "result_limit": request_body["size"],
        }
    elif endpoint == "paper_search_pro":
        exact_title = query_shape == "exact_title"
        query_parameter = "title" if exact_title else "query"
        query_value = query if exact_title else literal_query
        request_params: dict[str, Any] = {
            query_parameter: query_value,
            "year_to": year_to,
            "page": 0,
            "size": min(max(1, int(desired_results)), 100),
        }
        response = client.get(
            AMINER_PAPER_SEARCH_PRO_URL,
            params=request_params,
            headers=headers,
        )
        request_shape = {
            "method": "GET",
            "parameter_names": list(request_params),
            "query_parameter": query_parameter,
            "literal_query": query_value,
            "result_limit": request_params["size"],
        }
    else:
        query_value = (
            query
            if query_shape in {"exact_title", "short_phrase"}
            else literal_query
        )
        request_params = {
            "query": query_value,
            "year_to": year_to,
            "page": 1,
            "size": min(max(1, int(desired_results)), 20),
        }
        response = client.get(
            AMINER_PAPER_SEARCH_URL,
            params=request_params,
            headers=headers,
        )
        request_shape = {
            "method": "GET",
            "parameter_names": ["query", "year_to", "page", "size"],
            "query_parameter": "query",
            "literal_query": request_params["query"],
            "result_limit": request_params["size"],
        }
    return checked_payload(response, endpoint=endpoint), request_shape


def _declared_request_shape(
    endpoint: str,
    *,
    query: str,
    desired_results: int,
    search_field: str,
    query_shape: str,
) -> dict[str, Any]:
    """Describe a request even when the provider rejects it before a response."""
    if endpoint == "paper_qa_search_pro":
        return {
            "method": "POST",
            "parameter_names": ["query", "query_type", "year_to", "sort"],
            "query_parameter": "query",
            "query_type": "auto",
            "result_limit": 10,
        }
    if endpoint == "paper_qa_search":
        return {
            "method": "POST",
            "parameter_names": ["use_topic", "query", "size", "offset"],
            "query_parameter": "query",
            "result_limit": min(max(1, int(desired_results)), 100),
        }
    if endpoint == "paper_search_pro":
        exact_title = query_shape == "exact_title"
        query_parameter = "title" if exact_title else "query"
        query_value = query if exact_title else _fallback_phrase(query)
        return {
            "method": "GET",
            "parameter_names": [query_parameter, "year_to", "page", "size"],
            "query_parameter": query_parameter,
            "literal_query": query_value,
            "result_limit": min(max(1, int(desired_results)), 100),
        }
    return {
        "method": "GET",
        "parameter_names": ["query", "year_to", "page", "size"],
        "query_parameter": "query",
        "literal_query": (
            query
            if query_shape in {"exact_title", "short_phrase"}
            else _fallback_phrase(query)
        ),
        "result_limit": min(max(1, int(desired_results)), 20),
    }


def _add_call(diagnostics: dict[str, Any], endpoint: str) -> None:
    calls = diagnostics.setdefault("api_calls", {})
    calls[endpoint] = int(calls.get(endpoint, 0)) + 1
    costs = diagnostics.setdefault("estimated_cost_cny_by_api", {})
    costs[endpoint] = round(
        float(costs.get(endpoint, 0.0)) + AMINER_API_COST_CNY[endpoint], 2
    )
    diagnostics["estimated_cost_cny"] = round(
        sum(float(value) for value in costs.values()), 2
    )


def search_aminer_query(
    query: str,
    *,
    review_as_of: str,
    client: Any,
    api_key: str,
    tier: str = "auto",
    detail_limit: int = 3,
    query_shape: str = "auto",
    desired_results: int = 20,
    search_field: str = "keyword",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Route one query across public AMiner endpoints and report every attempt."""
    credential = aminer_api_key(api_key)
    resolved_shape, routing_reason = classify_query_shape(
        query,
        query_shape=query_shape,
        desired_results=desired_results,
    )
    ladder = _search_ladder(tier, resolved_shape)
    diagnostics: dict[str, Any] = {
        "provider": "AMiner Open Platform",
        "requested_tier": tier,
        "selected_endpoint": None,
        "query_plan": {
            "query": query,
            "requested_query_shape": query_shape,
            "resolved_query_shape": resolved_shape,
            "routing_reason": routing_reason,
            "primary_endpoint": ladder[0],
            "route": list(ladder),
            "desired_results": int(desired_results),
            "search_field": search_field,
            "fallback_phrase": _fallback_phrase(query),
        },
        "attempts": [],
        "api_calls": {},
        "estimated_cost_cny_by_api": {},
        "estimated_cost_cny": 0.0,
        "downgrades": [],
        "provider_errors": [],
    }
    if not credential:
        diagnostics["status"] = "unavailable_missing_api_key"
        diagnostics["provider_errors"].append(
            "AMINER_API_KEY is unavailable; AMiner discovery was not attempted."
        )
        return [], diagnostics
    headers = aminer_headers(credential)
    rows: list[dict[str, Any]] = []
    for index, endpoint in enumerate(ladder):
        _add_call(diagnostics, endpoint)
        attempt: dict[str, Any] = {
            "endpoint": endpoint,
            "query_shape": resolved_shape,
            "request": _declared_request_shape(
                endpoint,
                query=query,
                desired_results=desired_results,
                search_field=search_field,
                query_shape=resolved_shape,
            ),
            "unit_price_cny": AMINER_API_COST_CNY[endpoint],
            "estimated_fee_cny": AMINER_API_COST_CNY[endpoint],
        }
        try:
            payload, request_shape = _call_search_endpoint(
                endpoint,
                query=query,
                year_to=int(review_as_of[:4]),
                client=client,
                headers=headers,
                desired_results=desired_results,
                search_field=search_field,
                query_shape=resolved_shape,
            )
            attempt["request"] = request_shape
            rows = rows_from_payload(payload)
            response_metadata = {
                "code": payload.get("code"),
                "msg": payload.get("msg") or payload.get("message"),
                "log_id": payload.get("log_id"),
                "total": payload.get("total"),
            }
            data = payload.get("data")
            if response_metadata["total"] is None and isinstance(data, dict):
                response_metadata["total"] = data.get("total")
            attempt.update(
                {
                    "status": "completed" if rows else "empty",
                    "record_count": len(rows),
                    "response": response_metadata,
                }
            )
            diagnostics["attempts"].append(attempt)
            diagnostics["response_metadata"] = response_metadata
            if rows or index == len(ladder) - 1:
                diagnostics["selected_endpoint"] = endpoint
                break
            diagnostics["downgrades"].append(
                {
                    "from": endpoint,
                    "to": ladder[index + 1],
                    "reason": "empty_result",
                    "trigger": "empty",
                }
            )
            continue
        except AMinerAPIError as exc:
            diagnostics["provider_errors"].append(str(exc))
            attempt.update(
                {
                    "status": "failed",
                    "error_code": exc.code,
                    "error_type": (
                        "permission_or_balance"
                        if exc.permission_or_balance
                        else "provider_error"
                    ),
                    "log_id": exc.log_id,
                }
            )
            diagnostics["attempts"].append(attempt)
            lower_tier_exists = index < len(ladder) - 1
            if lower_tier_exists:
                diagnostics["downgrades"].append(
                    {
                        "from": endpoint,
                        "to": ladder[index + 1],
                        "reason": (
                            "permission_or_balance"
                            if exc.permission_or_balance
                            else "provider_error"
                        ),
                        "trigger": "error",
                    }
                )
                continue
            diagnostics["status"] = "failed"
            return [], diagnostics
        except Exception as exc:
            diagnostics["provider_errors"].append(
                f"{endpoint}: {type(exc).__name__}"
            )
            attempt.update(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                }
            )
            diagnostics["attempts"].append(attempt)
            if index < len(ladder) - 1:
                diagnostics["downgrades"].append(
                    {
                        "from": endpoint,
                        "to": ladder[index + 1],
                        "reason": "client_or_network_error",
                        "trigger": "error",
                    }
                )
                continue
            diagnostics["status"] = "failed"
            return [], diagnostics

    records = [
        normalized
        for row in rows
        if (normalized := normalize_paper_record(
            row,
            query=query,
            source=f"AMiner Open Platform {diagnostics['selected_endpoint']}",
        ))
    ]
    identifiers = list(
        dict.fromkeys(
            str(record.get("aminer_pub_id") or "")
            for record in records
            if record.get("aminer_pub_id")
        )
    )
    metadata_by_id: dict[str, dict[str, Any]] = {}
    if identifiers:
        _add_call(diagnostics, "paper_info")
        info_attempt: dict[str, Any] = {
            "endpoint": "paper_info",
            "stage": "batch_metadata_enrichment",
            "request": {
                "method": "POST",
                "parameter_names": ["ids"],
                "batch_size": min(len(identifiers), 100),
            },
            "unit_price_cny": AMINER_API_COST_CNY["paper_info"],
            "estimated_fee_cny": 0.0,
        }
        try:
            payload = checked_payload(
                client.post(
                    AMINER_PAPER_INFO_URL,
                    json={"ids": identifiers[:100]},
                    headers=headers,
                ),
                endpoint="paper_info",
            )
            metadata_by_id = {
                paper_id(row): row
                for row in rows_from_payload(payload)
                if paper_id(row)
            }
            for record in records:
                row = metadata_by_id.get(str(record.get("aminer_pub_id") or ""))
                if row:
                    merge_paper_metadata(record, row)
            info_attempt.update(
                {
                    "status": "completed",
                    "record_count": len(metadata_by_id),
                    "response": {
                        "code": payload.get("code"),
                        "msg": payload.get("msg") or payload.get("message"),
                        "log_id": payload.get("log_id"),
                    },
                }
            )
        except Exception as exc:
            diagnostics["provider_errors"].append(
                f"paper_info: {type(exc).__name__ if not isinstance(exc, AMinerAPIError) else str(exc)}"
            )
            info_attempt.update(
                {"status": "failed", "error_type": type(exc).__name__}
            )
        diagnostics["attempts"].append(info_attempt)

    detail_candidates = [
        record
        for record in records
        if record.get("aminer_pub_id") and not record.get("summary")
    ][: max(0, detail_limit)]
    for record in detail_candidates:
        _add_call(diagnostics, "paper_detail")
        detail_attempt: dict[str, Any] = {
            "endpoint": "paper_detail",
            "stage": "bounded_missing_abstract_enrichment",
            "request": {
                "method": "GET",
                "parameter_names": ["id"],
                "paper_id": record["aminer_pub_id"],
            },
            "unit_price_cny": AMINER_API_COST_CNY["paper_detail"],
            "estimated_fee_cny": AMINER_API_COST_CNY["paper_detail"],
        }
        try:
            payload = checked_payload(
                client.get(
                    AMINER_PAPER_DETAIL_URL,
                    params={"id": record["aminer_pub_id"]},
                    headers=headers,
                ),
                endpoint="paper_detail",
            )
            detail_rows = rows_from_payload(payload)
            if detail_rows:
                merge_paper_metadata(record, detail_rows[0])
            detail_attempt.update(
                {
                    "status": "completed",
                    "record_count": len(detail_rows),
                    "response": {
                        "code": payload.get("code"),
                        "msg": payload.get("msg") or payload.get("message"),
                        "log_id": payload.get("log_id"),
                    },
                }
            )
        except Exception as exc:
            diagnostics["provider_errors"].append(
                f"paper_detail {record['aminer_pub_id']}: "
                f"{type(exc).__name__ if not isinstance(exc, AMinerAPIError) else str(exc)}"
            )
            detail_attempt.update(
                {"status": "failed", "error_type": type(exc).__name__}
            )
        diagnostics["attempts"].append(detail_attempt)
    diagnostics["raw_record_count"] = len(rows)
    diagnostics["record_count"] = len(records)
    diagnostics["paper_info_record_count"] = len(metadata_by_id)
    diagnostics["status"] = (
        "completed" if not diagnostics["provider_errors"] else "partial"
    )
    return records, diagnostics


def list_aminer_by_keywords(
    keywords: list[str],
    *,
    review_as_of: str,
    client: Any,
    api_key: str,
    size: int = 30,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run one bounded multi-keyword feedback retrieval through the public API."""
    normalized_keywords = list(
        dict.fromkeys(
            " ".join(str(keyword or "").split())[:120]
            for keyword in keywords
            if str(keyword or "").strip()
        )
    )[:8]
    bounded_size = min(max(1, int(size)), 100)
    diagnostics: dict[str, Any] = {
        "provider": "AMiner Open Platform",
        "endpoint": "paper_list_by_keywords",
        "status": "not_attempted",
        "keywords": normalized_keywords,
        "review_as_of": review_as_of,
        "api_calls": {},
        "estimated_cost_cny_by_api": {},
        "estimated_cost_cny": 0.0,
        "provider_errors": [],
        "attempts": [],
    }
    if not normalized_keywords:
        diagnostics["status"] = "not_attempted_no_keywords"
        return [], diagnostics
    credential = aminer_api_key(api_key)
    if not credential:
        diagnostics["status"] = "unavailable_missing_api_key"
        diagnostics["provider_errors"].append(
            "AMINER_API_KEY is unavailable; keyword feedback retrieval was not attempted."
        )
        return [], diagnostics
    headers = aminer_headers(credential)
    _add_call(diagnostics, "paper_list_by_keywords")
    request_params = {
        "keywords": json.dumps(normalized_keywords, ensure_ascii=False),
        "page": 0,
        "size": bounded_size,
    }
    attempt: dict[str, Any] = {
        "endpoint": "paper_list_by_keywords",
        "stage": "controlled_feedback_retrieval",
        "request": {
            "method": "GET",
            "parameter_names": ["keywords", "page", "size"],
            "keyword_count": len(normalized_keywords),
            "result_limit": bounded_size,
        },
        "unit_price_cny": AMINER_API_COST_CNY["paper_list_by_keywords"],
        "estimated_fee_cny": AMINER_API_COST_CNY["paper_list_by_keywords"],
    }
    try:
        payload = checked_payload(
            client.get(
                AMINER_PAPER_LIST_BY_KEYWORDS_URL,
                params=request_params,
                headers=headers,
            ),
            endpoint="paper_list_by_keywords",
        )
        rows = rows_from_payload(payload)
        attempt.update(
            {
                "status": "completed" if rows else "empty",
                "record_count": len(rows),
                "response": {
                    "code": payload.get("code"),
                    "msg": payload.get("msg") or payload.get("message"),
                    "log_id": payload.get("log_id"),
                    "total": payload.get("total"),
                },
            }
        )
    except Exception as exc:
        diagnostics["provider_errors"].append(
            str(exc) if isinstance(exc, AMinerAPIError) else type(exc).__name__
        )
        attempt.update({"status": "failed", "error_type": type(exc).__name__})
        diagnostics["attempts"].append(attempt)
        diagnostics["status"] = "failed"
        return [], diagnostics
    diagnostics["attempts"].append(attempt)
    query_label = " | ".join(normalized_keywords)
    records = [
        normalized
        for row in rows
        if (
            normalized := normalize_paper_record(
                row,
                query=query_label,
                source="AMiner Open Platform paper_list_by_keywords",
            )
        )
    ]
    identifiers = list(
        dict.fromkeys(
            str(record.get("aminer_pub_id") or "")
            for record in records
            if record.get("aminer_pub_id")
        )
    )[:100]
    if identifiers:
        _add_call(diagnostics, "paper_info")
        info_attempt: dict[str, Any] = {
            "endpoint": "paper_info",
            "stage": "keyword_feedback_metadata_enrichment",
            "request": {
                "method": "POST",
                "parameter_names": ["ids"],
                "batch_size": len(identifiers),
            },
            "unit_price_cny": 0.0,
            "estimated_fee_cny": 0.0,
        }
        try:
            info_payload = checked_payload(
                client.post(
                    AMINER_PAPER_INFO_URL,
                    json={"ids": identifiers},
                    headers=headers,
                ),
                endpoint="paper_info",
            )
            metadata = {
                paper_id(row): row
                for row in rows_from_payload(info_payload)
                if paper_id(row)
            }
            for record in records:
                row = metadata.get(str(record.get("aminer_pub_id") or ""))
                if row:
                    merge_paper_metadata(record, row)
            info_attempt.update(
                {"status": "completed", "record_count": len(metadata)}
            )
        except Exception as exc:
            diagnostics["provider_errors"].append(
                str(exc) if isinstance(exc, AMinerAPIError) else type(exc).__name__
            )
            info_attempt.update(
                {"status": "failed", "error_type": type(exc).__name__}
            )
        diagnostics["attempts"].append(info_attempt)
    diagnostics["record_count"] = len(records)
    diagnostics["status"] = (
        "completed" if not diagnostics["provider_errors"] else "partial"
    )
    return records, diagnostics


def _normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def title_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, _normalize_title(left), _normalize_title(right)).ratio()


def _name_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if len(token) > 1
    }


def _authors_match(local_authors: list[str], candidate_authors: str) -> bool:
    candidates = [
        part.strip() for part in re.split(r"[,;]", candidate_authors) if part.strip()
    ]
    for local in local_authors:
        local_normalized = " ".join(re.findall(r"[a-z0-9]+", local.casefold()))
        local_tokens = list(_name_tokens(local))
        for candidate in candidates:
            candidate_normalized = " ".join(
                re.findall(r"[a-z0-9]+", candidate.casefold())
            )
            candidate_tokens = list(_name_tokens(candidate))
            if local_normalized and local_normalized == candidate_normalized:
                return True
            if local_tokens and candidate_tokens:
                local_surname = re.findall(r"[a-z0-9]+", local.casefold())[-1]
                candidate_surname = re.findall(r"[a-z0-9]+", candidate.casefold())[-1]
                if len(local_surname) > 2 and local_surname == candidate_surname:
                    return True
    return False


def resolve_title_to_pub_id(
    title: str,
    *,
    authors: list[str] | tuple[str, ...] | None,
    publication_year: int | None,
    review_as_of: str,
    api_key: str | None = None,
    proxy: str | None = None,
    client_factory: ClientFactory = httpx.Client,
) -> tuple[str | None, dict[str, Any]]:
    """Resolve a PDF title only when identity evidence yields one unique match."""
    local_title = " ".join(str(title or "").split())
    local_authors = [" ".join(str(name).split()) for name in authors or [] if str(name).strip()]
    diagnostics: dict[str, Any] = {
        "enabled": True,
        "provider": "AMiner Open Platform paper_search + paper_info",
        "status": "not_attempted",
        "title": local_title,
        "local_author_count": len(local_authors),
        "local_publication_year": publication_year,
        "matched_pub_id": None,
        "candidates": [],
    }
    if not local_title:
        diagnostics["status"] = "unavailable_missing_title"
        return None, diagnostics
    if not local_authors and publication_year is None:
        diagnostics["status"] = "unavailable_missing_author_and_year"
        diagnostics["reason"] = (
            "A title alone is not sufficient to claim an AMiner identity."
        )
        return None, diagnostics
    credential = aminer_api_key(api_key)
    if not credential:
        diagnostics["status"] = "unavailable_missing_api_key"
        return None, diagnostics
    with client_factory(
        timeout=httpx.Timeout(30.0, connect=10.0),
        proxy=proxy,
        follow_redirects=True,
        trust_env=proxy is not None,
    ) as client:
        records, search_diagnostics = search_aminer_query(
            local_title,
            review_as_of=review_as_of,
            client=client,
            api_key=credential,
            tier="free",
            detail_limit=0,
            query_shape="exact_title",
            desired_results=20,
            search_field="title",
        )
    diagnostics["search"] = search_diagnostics
    verified: list[dict[str, Any]] = []
    for record in records:
        similarity = title_similarity(local_title, str(record.get("title") or ""))
        candidate_authors = str(record.get("authors") or "")
        candidate_author_tokens = _name_tokens(candidate_authors)
        author_checked = bool(local_authors)
        author_match = (
            _authors_match(local_authors, candidate_authors)
            if author_checked
            else None
        )
        year_checked = publication_year is not None
        candidate_year = record.get("publication_year")
        year_match = (
            int(candidate_year) == int(publication_year)
            if year_checked and candidate_year is not None
            else None
        )
        identity_evidence_available = (
            (author_checked and candidate_author_tokens)
            or (year_checked and candidate_year is not None)
        )
        constraints_pass = (
            (not author_checked or author_match is True)
            and (not year_checked or year_match is True)
        )
        item = {
            "pub_id": record.get("aminer_pub_id"),
            "title": record.get("title"),
            "year": candidate_year,
            "title_similarity": round(similarity, 4),
            "author_checked": author_checked,
            "author_match": author_match,
            "year_checked": year_checked,
            "year_match": year_match,
            "verified": bool(
                record.get("aminer_pub_id")
                and similarity >= 0.96
                and identity_evidence_available
                and constraints_pass
            ),
        }
        diagnostics["candidates"].append(item)
        if item["verified"]:
            verified.append(item)
    if len(verified) == 1:
        identifier = normalize_pub_id(str(verified[0]["pub_id"]))
        diagnostics["status"] = "matched_unique"
        diagnostics["matched_pub_id"] = identifier
        return identifier, diagnostics
    diagnostics["status"] = "ambiguous" if len(verified) > 1 else "no_verified_match"
    diagnostics["verified_match_count"] = len(verified)
    return None, diagnostics
