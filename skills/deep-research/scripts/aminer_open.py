#!/usr/bin/env python3
"""Safe, dependency-free AMiner Open Platform client for aminer-deep-research.

The API catalog mirrors the `aminer-academic-search` skill (same endpoints,
same prices, same routing rules). Full parameter documentation lives in that
skill's `references/api-catalog.md`; this file is the executable subset that
deep research needs, with validation, cost estimation and token redaction.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any


BASE_URL = "https://datacenter.aminer.cn/gateway/open_platform"
CONSOLE_URL = "https://open.aminer.cn/open/board?tab=control"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_RETRIES = 3
HIGH_COST_CNY = 10.0
RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})

# A retry after a timeout is not free on a billed endpoint: the request may have
# been served and charged even though the response never arrived, so three
# attempts can cost three times while the ledger records nothing. Paid endpoints
# therefore try once by default; pass --retries explicitly to override.
PAID_DEFAULT_RETRIES = 1

_UNSET = object()


@dataclass(frozen=True)
class Field:
    """Declared type and bounds for one request parameter."""

    kind: str  # string | int | bool | string_list | int_list | string_or_list
    default: Any = _UNSET
    minimum: int | None = None
    maximum: int | None = None
    choices: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ApiSpec:
    method: str
    path: str
    price_cny: float
    fields: dict[str, Field] = field(default_factory=dict)
    required: tuple[str, ...] = ()
    any_of: tuple[str, ...] = ()
    note: str = ""

    @property
    def allowed(self) -> frozenset[str]:
        return frozenset(self.fields)

    @property
    def optional(self) -> tuple[str, ...]:
        return tuple(k for k in self.fields if k not in self.required and k not in self.any_of)

    @property
    def defaults(self) -> tuple[tuple[str, Any], ...]:
        return tuple((k, f.default) for k, f in self.fields.items() if f.default is not _UNSET)


def _s(**kwargs: Any) -> Field:
    return Field("string", **kwargs)


def _i(**kwargs: Any) -> Field:
    return Field("int", **kwargs)


def _b(**kwargs: Any) -> Field:
    return Field("bool", **kwargs)


def _sl(**kwargs: Any) -> Field:
    return Field("string_list", **kwargs)


def _il(**kwargs: Any) -> Field:
    return Field("int_list", **kwargs)


_PAGE = _i(default=1, minimum=0, maximum=10_000)
_YEAR = _i(minimum=1000, maximum=3000)


API_SPECS: dict[str, ApiSpec] = {
    # ---------------- Paper ----------------
    "paper_search": ApiSpec(
        "GET", "/api/paper/search", 0.0,
        fields={"title": _s(), "page": _i(default=1, minimum=0), "size": _i(default=8, minimum=1, maximum=100)},
        required=("title",),
    ),
    "paper_info": ApiSpec(
        "POST", "/api/paper/info", 0.0,
        fields={"ids": _sl()},
        required=("ids",),
    ),
    "paper_search_pro": ApiSpec(
        "GET", "/api/paper/search/pro", 0.01,
        fields={
            "title": _s(), "keyword": _s(), "abstract": _s(), "author": _s(), "org": _s(), "venue": _s(),
            "order": _s(choices=("n_citation", "year")),
            "page": _i(default=0, minimum=0), "size": _i(default=8, minimum=1, maximum=100),
        },
        any_of=("title", "keyword", "abstract", "author", "org", "venue"),
    ),
    "paper_qa_search_pro": ApiSpec(
        "POST", "/api/v3/paper/qa/searchPro", 0.70,
        fields={
            "query": _s(maximum=500),
            "query_type": _s(choices=("auto", "topic", "keywords", "title", "identifier")),
            "cursor": _s(),
            "authors": _sl(), "author_ids": _sl(),
            "organizations": _sl(), "organization_ids": _sl(),
            "venues": _sl(), "venue_ids": _sl(),
            "year_values": _il(), "year_from": _YEAR, "year_to": _YEAR,
            "languages": _sl(), "language_preference": _s(choices=("zh", "en")),
            "has_chinese_title": _b(), "has_abstract": _b(),
            "min_citations": _i(minimum=0), "max_citations": _i(minimum=0),
            "all_terms": _sl(), "any_terms": _sl(), "exclude_terms": _sl(),
            "search_in": _s(choices=("all", "title", "title_keywords", "abstract")),
            "paper_ids": _sl(), "exclude_paper_ids": _sl(), "dois": _sl(),
            "sort": _s(choices=("relevance", "balanced", "recent", "citation")),
        },
        any_of=(
            "query", "cursor", "authors", "author_ids", "organizations", "organization_ids",
            "venues", "venue_ids", "all_terms", "any_terms", "paper_ids", "dois",
        ),
        note="Page size is fixed at 10. Paginate with next_cursor; a follow-up body carries cursor only.",
    ),
    "paper_qa_search": ApiSpec(
        "POST", "/api/paper/qa/search", 0.05,
        fields={
            "query": _s(), "topic_high": Field("string_or_list"), "topic_middle": Field("string_or_list"),
            "topic_low": Field("string_or_list"), "title": _sl(), "doi": _s(),
            "author_id": _sl(), "org_id": _sl(), "venue_ids": _sl(),
            "author_terms": _sl(), "org_terms": _sl(), "year": _il(),
            # use_topic defaults to true: the backend ignores `query` when it is
            # false (only `title`/`doi` are read), returning envelope 403 "no data".
            "use_topic": _b(default=True), "sci_flag": _b(), "n_citation_flag": _b(),
            "force_citation_sort": _b(), "force_year_sort": _b(),
            "size": _i(default=8, minimum=1, maximum=100), "offset": _i(default=0, minimum=0),
        },
        any_of=("query", "topic_high", "title", "doi", "author_id", "org_id", "venue_ids"),
        note="Legacy. Use only for topic_high/middle/low OR-AND mode; otherwise call paper_qa_search_pro.",
    ),
    "paper_detail": ApiSpec("GET", "/api/paper/detail", 0.01, fields={"id": _s()}, required=("id",)),
    "paper_relation": ApiSpec("GET", "/api/paper/relation", 0.10, fields={"id": _s()}, required=("id",)),
    "paper_list_by_keywords": ApiSpec(
        "GET", "/api/paper/list/citation/by/keywords", 0.10,
        fields={
            "keywords": _sl(),
            "page": _i(default=0, minimum=0), "size": _i(default=10, minimum=1, maximum=100),
        },
        required=("keywords",),
    ),
    "paper_detail_by_condition": ApiSpec(
        "GET", "/api/paper/platform/allpubs/more/detail/by/ts/org/venue", 0.20,
        fields={"year": _YEAR, "venue_id": _s(), "org_id": _s(), "page": _i(default=0, minimum=0),
                "size": _i(default=10, minimum=1, maximum=100)},
        required=("year", "venue_id"),
        note="year and venue_id must be sent together; year alone returns null.",
    ),
    # ---------------- Scholar ----------------
    "person_search": ApiSpec(
        "POST", "/api/person/search", 0.0,
        fields={"name": _s(), "org": _s(), "org_id": _sl(),
                "offset": _i(default=0, minimum=0), "size": _i(default=5, minimum=1, maximum=100)},
        any_of=("name", "org", "org_id"),
    ),
    "person_detail": ApiSpec("GET", "/api/person/detail", 1.00, fields={"id": _s()}, required=("id",)),
    "person_figure": ApiSpec("GET", "/api/person/figure", 0.50, fields={"id": _s()}, required=("id",)),
    "person_paper_relation": ApiSpec("GET", "/api/person/paper/relation", 1.50, fields={"id": _s()}, required=("id",)),
    "person_patent_relation": ApiSpec("GET", "/api/person/patent/relation", 1.50, fields={"id": _s()}, required=("id",)),
    "person_project": ApiSpec("GET", "/api/project/person/v3/open", 1.50, fields={"id": _s()}, required=("id",)),
    # ---------------- Institution ----------------
    "org_search": ApiSpec("POST", "/api/organization/search", 0.0, fields={"orgs": _sl()}, required=("orgs",)),
    "org_disambiguate": ApiSpec("POST", "/api/organization/na", 0.01, fields={"org": _s()}, required=("org",)),
    "org_disambiguate_pro": ApiSpec("POST", "/api/organization/na/pro", 0.05, fields={"org": _s()}, required=("org",)),
    "org_detail": ApiSpec("POST", "/api/organization/detail", 0.01, fields={"ids": _sl()}, required=("ids",)),
    "org_person_relation": ApiSpec(
        "GET", "/api/organization/person/relation", 0.50,
        fields={"org_id": _s(), "offset": _i(default=0, minimum=0)}, required=("org_id",),
    ),
    "org_paper_relation": ApiSpec(
        "GET", "/api/organization/paper/relation", 0.10,
        fields={"org_id": _s(), "offset": _i(default=0, minimum=0)}, required=("org_id",),
    ),
    "org_patent_relation": ApiSpec(
        "GET", "/api/organization/patent/relation", 0.10,
        fields={"id": _s(), "page": _PAGE, "page_size": _i(default=100, minimum=1, maximum=10_000)},
        required=("id",),
    ),
    # ---------------- Venue ----------------
    "venue_search": ApiSpec("POST", "/api/venue/search", 0.0, fields={"name": _s()}, required=("name",)),
    "venue_detail": ApiSpec("POST", "/api/venue/detail", 0.20, fields={"id": _s()}, required=("id",)),
    "venue_paper_relation": ApiSpec(
        "POST", "/api/venue/paper/relation", 0.10,
        fields={"id": _s(), "offset": _i(default=0, minimum=0),
                "limit": _i(default=20, minimum=1, maximum=100), "year": _YEAR},
        required=("id",),
    ),
    # ---------------- Patent ----------------
    "patent_search": ApiSpec(
        "POST", "/api/patent/search", 0.0,
        fields={"query": _s(), "page": _i(default=0, minimum=0), "size": _i(default=8, minimum=1, maximum=100)},
        required=("query",),
    ),
    "patent_info": ApiSpec("GET", "/api/patent/info", 0.0, fields={"id": _s()}, required=("id",)),
    "patent_detail": ApiSpec("GET", "/api/patent/detail", 0.01, fields={"id": _s()}, required=("id",)),
}


class ClientError(ValueError):
    """Safe user-facing validation or transport error."""


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple)):
        return bool(value)
    return True


def _load_token() -> str:
    """Read the AMiner API key from the shell environment (``AMINER_API_KEY``).

    The host exports the key into the shell env (e.g. ``export AMINER_API_KEY=…`` or
    a sourced ``.env``) before invoking the skill; the token is read here and
    nowhere else. Never print or log the returned value.
    """
    return (os.getenv("AMINER_API_KEY") or "").strip()


def _check_int(api_name: str, key: str, value: Any, spec: Field) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ClientError(f"Parameter {key} for {api_name} must be an integer")
    if spec.minimum is not None and value < spec.minimum:
        raise ClientError(f"Parameter {key} for {api_name} must be at least {spec.minimum}")
    if spec.maximum is not None and value > spec.maximum:
        raise ClientError(f"Parameter {key} for {api_name} must be at most {spec.maximum}")


def _check_field(api_name: str, key: str, value: Any, spec: Field) -> None:
    if spec.kind == "string_list" or spec.kind == "int_list":
        if not isinstance(value, list):
            raise ClientError(f"Parameter {key} for {api_name} must be a JSON array")
        if spec.kind == "int_list":
            for item in value:
                _check_int(api_name, key, item, spec)
        elif any(not isinstance(item, str) or not item.strip() for item in value):
            raise ClientError(f"Parameter {key} for {api_name} must contain non-empty strings")
    elif spec.kind == "bool":
        if not isinstance(value, bool):
            raise ClientError(f"Parameter {key} for {api_name} must be true or false")
    elif spec.kind == "int":
        _check_int(api_name, key, value, spec)
    elif spec.kind == "string_or_list":
        if not isinstance(value, (str, list)):
            raise ClientError(f"Parameter {key} for {api_name} must be a string or JSON array")
    else:  # string
        if value is None:
            return
        if not isinstance(value, str):
            raise ClientError(f"Parameter {key} for {api_name} must be a string")
        if spec.maximum is not None and len(value) > spec.maximum:
            raise ClientError(f"Parameter {key} for {api_name} must be at most {spec.maximum} characters")
        if spec.choices and value not in spec.choices:
            raise ClientError(f"Parameter {key} for {api_name} must be one of: {', '.join(spec.choices)}")


def _check_cross_field_rules(api_name: str, params: dict[str, Any]) -> None:
    if api_name == "paper_qa_search_pro":
        if _has_value(params.get("cursor")) and len(params) > 1:
            raise ClientError("paper_qa_search_pro pagination request must send cursor only")
        if _has_value(params.get("year_values")) and (
            _has_value(params.get("year_from")) or _has_value(params.get("year_to"))
        ):
            raise ClientError("paper_qa_search_pro accepts year_values or year_from/year_to, not both")
        year_from, year_to = params.get("year_from"), params.get("year_to")
        if isinstance(year_from, int) and isinstance(year_to, int) and year_to < year_from:
            raise ClientError("Parameter year_to for paper_qa_search_pro must be greater than or equal to year_from")
        low, high = params.get("min_citations"), params.get("max_citations")
        if isinstance(low, int) and isinstance(high, int) and high < low:
            raise ClientError("Parameter max_citations for paper_qa_search_pro must be greater than or equal to min_citations")
        query_type = params.get("query_type")
        if query_type and query_type != "auto" and not _has_value(params.get("query")):
            raise ClientError(f"paper_qa_search_pro requires query when query_type is {query_type}")
    elif api_name == "paper_qa_search":
        topics = [k for k in ("topic_high", "topic_middle", "topic_low") if _has_value(params.get(k))]
        if _has_value(params.get("query")) and topics:
            raise ClientError("paper_qa_search accepts query or topic_high/topic_middle/topic_low, not both")


def _validate_params(api_name: str, raw_params: Any) -> dict[str, Any]:
    if api_name not in API_SPECS:
        raise ClientError(f"Unknown API: {api_name}")
    if not isinstance(raw_params, dict):
        raise ClientError("Parameters must be a JSON object")

    spec = API_SPECS[api_name]
    unknown = sorted(set(raw_params) - spec.allowed)
    if unknown:
        raise ClientError(f"Unsupported parameter(s) for {api_name}: {', '.join(unknown)}")

    params = dict(raw_params)
    is_cursor_page = api_name == "paper_qa_search_pro" and _has_value(params.get("cursor"))
    if not is_cursor_page:
        for key, value in spec.defaults:
            params.setdefault(key, value)

    missing = [key for key in spec.required if not _has_value(params.get(key))]
    if missing:
        raise ClientError(f"Missing required parameter(s) for {api_name}: {', '.join(missing)}")
    if spec.any_of and not any(_has_value(params.get(key)) for key in spec.any_of):
        raise ClientError(f"{api_name} requires at least one of: {', '.join(spec.any_of)}")

    for key, value in params.items():
        _check_field(api_name, key, value, spec.fields[key])
    _check_cross_field_rules(api_name, params)
    return params


def _parse_json(raw: str, label: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ClientError(f"{label} is not valid JSON: {exc.msg}") from None


def _normalize_calls(api_name: str | None, params_json: str, batch_json: str | None) -> list[dict[str, Any]]:
    if batch_json is not None:
        raw_calls = _parse_json(batch_json, "--batch")
        if not isinstance(raw_calls, list) or not raw_calls:
            raise ClientError("--batch must be a non-empty JSON array")
        if len(raw_calls) > 50:
            raise ClientError("--batch accepts at most 50 calls")
    else:
        if not api_name:
            raise ClientError("Provide --api, --batch, or --list-apis")
        raw_calls = [{"api": api_name, "params": _parse_json(params_json, "--params")}]

    calls: list[dict[str, Any]] = []
    for index, item in enumerate(raw_calls):
        if not isinstance(item, dict):
            raise ClientError(f"Batch item {index} must be a JSON object")
        extra = sorted(set(item) - {"api", "params"})
        if extra:
            raise ClientError(f"Unsupported batch item field(s): {', '.join(extra)}")
        name = item.get("api")
        if not isinstance(name, str) or not name:
            raise ClientError(f"Batch item {index} requires a non-empty api name")
        calls.append({"api": name, "params": _validate_params(name, item.get("params", {}))})
    return calls


def _encode_get_url(path: str, params: dict[str, Any]) -> str:
    query = urllib.parse.urlencode({
        key: json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if isinstance(value, (list, dict)) else value
        for key, value in params.items() if value is not None
    })
    return f"{BASE_URL}{path}" + (f"?{query}" if query else "")


def _request_plan(api_name: str, params: dict[str, Any]) -> dict[str, Any]:
    spec = API_SPECS[api_name]
    url = _encode_get_url(spec.path, params) if spec.method == "GET" else f"{BASE_URL}{spec.path}"
    plan: dict[str, Any] = {
        "api": api_name,
        "method": spec.method,
        "url": url,
        "unit_cost_cny": spec.price_cny,
    }
    if spec.method == "POST":
        plan["body"] = params
    return plan


def _redact(value: Any, token: str) -> Any:
    if isinstance(value, str):
        return value.replace(token, "[REDACTED]") if token else value
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, token) for key, item in value.items()}
    return value


def _decode_body(raw: bytes) -> Any:
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text[:2000]}


def _perform_call(
    api_name: str,
    params: dict[str, Any],
    token: str,
    timeout: float | None,
    retries: int | None,
) -> dict[str, Any]:
    spec = API_SPECS[api_name]
    paid = spec.price_cny > 0
    if timeout is None:
        timeout = DEFAULT_TIMEOUT_SECONDS
    if retries is None:
        retries = PAID_DEFAULT_RETRIES if paid else DEFAULT_RETRIES
    url = _encode_get_url(spec.path, params) if spec.method == "GET" else f"{BASE_URL}{spec.path}"
    body = None if spec.method == "GET" else json.dumps(params, ensure_ascii=False).encode("utf-8")
    headers = {"Authorization": token, "X-Platform": "openclaw"}
    if body is not None:
        headers["Content-Type"] = "application/json;charset=utf-8"

    last_error: dict[str, Any] | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(url, data=body, headers=headers, method=spec.method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = _redact(_decode_body(response.read()), token)
                result = {
                    "ok": True,
                    "api": api_name,
                    "status": getattr(response, "status", 200),
                    "unit_cost_cny": spec.price_cny,
                    "data": payload,
                }
                # Hoist the server's own signals so a caller does not have to dig
                # for them: a warning means the query you sent is not the query
                # that ran, and `total` says whether the field is thin or the
                # query missed.
                inner = payload.get("data") if isinstance(payload, dict) else None
                if isinstance(inner, dict):
                    if inner.get("warnings"):
                        result["warnings"] = inner["warnings"]
                    if inner.get("total") is not None:
                        result["total"] = inner["total"]
                return result
        except urllib.error.HTTPError as exc:
            error_body = _redact(_decode_body(exc.read()), token)
            last_error = {
                "ok": False,
                "api": api_name,
                "status": exc.code,
                "unit_cost_cny": spec.price_cny,
                "error": "http_error",
                "detail": error_body,
            }
            if exc.code not in RETRYABLE_STATUS:
                break
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = {
                "ok": False,
                "api": api_name,
                "status": None,
                "unit_cost_cny": spec.price_cny,
                "error": "network_error",
                "detail": _redact(str(getattr(exc, "reason", exc)), token)[:500],
            }
            if paid:
                # The server may have run and billed the request even though the
                # response never arrived. Say so, because the ledger only counts
                # cost on success and would otherwise report this call as free.
                last_error["may_have_been_billed"] = True
                last_error["reconcile"] = (
                    f"If AMiner billed this attempt, record it with: "
                    f"evidence.py spend --api {api_name} --cny {spec.price_cny}"
                )
        except Exception as exc:  # defensive: keep credentials out of unexpected errors
            last_error = {
                "ok": False,
                "api": api_name,
                "status": None,
                "unit_cost_cny": spec.price_cny,
                "error": "unexpected_error",
                "detail": _redact(str(exc), token)[:500],
            }
            break

        if attempt < retries:
            time.sleep((2 ** (attempt - 1)) + random.uniform(0, 0.2))

    return last_error or {
        "ok": False,
        "api": api_name,
        "status": None,
        "unit_cost_cny": spec.price_cny,
        "error": "request_failed",
    }


def _cost_summary(calls: list[dict[str, Any]]) -> dict[str, Any]:
    breakdown: dict[str, dict[str, Any]] = {}
    total = 0.0
    for call in calls:
        name = call["api"]
        price = API_SPECS[name].price_cny
        total += price
        entry = breakdown.setdefault(name, {"calls": 0, "unit_cost_cny": price, "subtotal_cny": 0.0})
        entry["calls"] += 1
        entry["subtotal_cny"] = round(entry["subtotal_cny"] + price, 2)
    return {
        "currency": "CNY",
        "estimated_total": round(total, 2),
        "breakdown": breakdown,
        "requires_confirmation": total >= HIGH_COST_CNY,
        "confirmation_threshold": HIGH_COST_CNY,
    }


def _api_catalog() -> dict[str, Any]:
    return {
        "ok": True,
        "base_url": BASE_URL,
        "apis": {
            name: {
                "method": spec.method,
                "path": spec.path,
                "price_cny": spec.price_cny,
                "required": list(spec.required),
                "any_of": list(spec.any_of),
                "optional": list(spec.optional),
                **({"note": spec.note} if spec.note else {}),
            }
            for name, spec in sorted(API_SPECS.items())
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Call allowlisted AMiner Open Platform APIs")
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument("--api", help="Allowed API name for a single call")
    choice.add_argument("--batch", help="JSON array of {api, params} calls")
    choice.add_argument("--list-apis", action="store_true", help="Print the allowed API registry")
    parser.add_argument("--params", default="{}", help="JSON object for --api")
    parser.add_argument("--dry-run", action="store_true", help="Validate and estimate without network access")
    parser.add_argument("--confirm-high-cost", action="store_true", help="Confirm an estimated batch cost of CNY 10 or more")
    parser.add_argument("--timeout", type=float, default=None,
                        help=f"Seconds per attempt (default {DEFAULT_TIMEOUT_SECONDS:.0f} for every endpoint)")
    parser.add_argument("--retries", type=int, default=None,
                        help=f"Attempts per call (default {DEFAULT_RETRIES} free, "
                             f"{PAID_DEFAULT_RETRIES} for paid endpoints: a retried timeout may bill twice)")
    return parser


def run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    if args.list_apis:
        return _api_catalog(), 0
    if args.timeout is not None and args.timeout <= 0:
        raise ClientError("--timeout must be greater than zero")
    if args.retries is not None and not 1 <= args.retries <= 5:
        raise ClientError("--retries must be between 1 and 5")

    calls = _normalize_calls(args.api, args.params, args.batch)
    costs = _cost_summary(calls)
    plans = [_request_plan(call["api"], call["params"]) for call in calls]
    if args.dry_run:
        return {"ok": True, "dry_run": True, "requests": plans, "cost": costs}, 0
    if costs["requires_confirmation"] and not args.confirm_high_cost:
        return {
            "ok": False,
            "error": "high_cost_confirmation_required",
            "message": "Estimated AMiner cost reaches CNY 5. Ask the user to confirm before retrying.",
            "requests": plans,
            "cost": costs,
        }, 3

    token = _load_token()
    if not token:
        return {
            "ok": False,
            "error": "missing_aminer_key",
            "message": "Set AMINER_API_KEY in the shell environment before making AMiner calls.",
            "console": CONSOLE_URL,
            "cost": costs,
        }, 2

    results = [
        _perform_call(call["api"], call["params"], token, args.timeout, args.retries)
        for call in calls
    ]
    return {
        "ok": all(item.get("ok") for item in results),
        "results": results,
        "cost": costs,
    }, 0 if all(item.get("ok") for item in results) else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        payload, exit_code = run(parser.parse_args(argv))
    except ClientError as exc:
        payload, exit_code = {"ok": False, "error": "invalid_request", "message": str(exc)}, 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
