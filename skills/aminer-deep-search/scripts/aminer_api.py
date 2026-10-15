#!/usr/bin/env python3
"""AMiner Open Platform tool CLI for aminer-deep-search.

Pure-stdlib tool commands driven by the host model. Every subcommand prints a
single JSON document to stdout (the tool result); diagnostics and the cost
summary go to stderr. No relevance scoring or loop control happens here — the
host model decides what to search, what to keep, and when to stop.

Endpoints (base: https://datacenter.aminer.cn/gateway/open_platform):
  GET  /api/paper/search/pro     fielded keyword search, ¥0.01/page (subcommand: search)
  POST /api/paper/qa/search      natural-language search, ¥0.05/call (qa-search)
  POST /api/paper/qa/searchPro   structured-filter search, ¥0.30/page (qa-search-pro)
  POST /api/paper/info           batch metadata, free, <=100 ids     (info, and enrichment)
  GET  /api/paper/relation       backward references, ¥0.10/seed     (references)
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
from pathlib import Path
from typing import Any

BASE_URL = "https://datacenter.aminer.cn/gateway/open_platform"
SKILL_NAME = "aminer-deep-search"
SKILL_VERSION = "2.2.0"
CONSOLE_URL = "https://open.aminer.cn/open/board?tab=control"
PAPER_URL_TEMPLATE = "https://www.aminer.cn/pub/{}"
TIMEOUT_SECONDS = 30.0
MAX_RETRIES = 3
RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})
PAPER_INFO_BATCH_LIMIT = 100
SEARCH_PRO_PAGE_SIZE = 100  # max size per doc; same ¥0.01 price per page
QA_SEARCH_PRO_PAGE_SIZE = 10  # fixed by the backend; cursor pagination
ABSTRACT_SLICE_LIMIT = 300
MAX_AUTHOR_NAMES = 20

PRICE_CNY = {
    "search_pro": 0.01,
    "qa_search": 0.05,
    "qa_search_pro": 0.30,
    "paper_info": 0.0,
    "relation": 0.10,
}

# Official open-platform business error codes (returned in the envelope `code`).
ERROR_NAMES = {
    40001: "invalid_params",
    40301: "permission_denied",
    40302: "token_expired",
    40306: "rate_limited",
    40307: "invalid_api_key",
    40308: "invalid_token",
    50001: "server_error",
}

_call_counts: dict[str, int] = {}


class ToolError(Exception):
    """Fatal error carrying a structured JSON payload for stdout."""

    def __init__(self, payload: dict[str, Any], exit_code: int = 1) -> None:
        super().__init__(payload.get("message", "tool error"))
        self.payload = payload
        self.exit_code = exit_code


def _get_token() -> str:
    token = (os.getenv("AMINER_API_KEY") or "").strip()
    if not token:
        raise ToolError(
            {
                "ok": False,
                "error": "missing_aminer_api_key",
                "message": "Set the AMINER_API_KEY environment variable before calling AMiner APIs.",
                "console": CONSOLE_URL,
            },
            exit_code=2,
        )
    return token


def detect_skill_runtime() -> str:
    explicit = (os.environ.get("AMINER_SKILL_RUNTIME") or "").strip().lower().replace("_", "-")
    if explicit:
        return explicit
    if os.environ.get("CLAUDE_CODE") or os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_PROJECT_DIR"):
        return "claude-code"
    if os.environ.get("CURSOR_TRACE_ID") or os.environ.get("CURSOR_AGENT"):
        return "cursor"
    if os.environ.get("CODEX_HOME") or os.environ.get("CODEX_CLI"):
        return "codex"
    if os.environ.get("OPENCLAW") or os.environ.get("OPENCLAW_HOME"):
        return "openclaw"
    return "unknown"


def _skill_md_version(fallback: str) -> str:
    path = Path(__file__).resolve().parents[1] / "SKILL.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return fallback
    if not text.startswith("---"):
        return fallback
    end = text.find("\n---", 3)
    if end < 0:
        return fallback
    for line in text[3:end].splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() == "version":
            version = value.strip().strip("'\"")
            if version:
                return version
    return fallback


def skill_identity_headers() -> dict[str, str]:
    return {
        "X-Platform": detect_skill_runtime(),
        "X-Skill-Name": SKILL_NAME,
        "X-Skill-Version": _skill_md_version(SKILL_VERSION),
    }


def _redact(value: Any, token: str) -> Any:
    if isinstance(value, str):
        return value.replace(token, "[REDACTED]") if token else value
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, token) for key, item in value.items()}
    return value


def _request(api_name: str, method: str, path: str,
             params: dict[str, Any] | None = None,
             body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call one endpoint with retries; return the parsed JSON envelope."""
    token = _get_token()
    url = BASE_URL + path
    if method == "GET" and params:
        query = urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None}
        )
        url = f"{url}?{query}"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {"Authorization": token, **skill_identity_headers()}
    if data is not None:
        headers["Content-Type"] = "application/json;charset=utf-8"

    _call_counts[api_name] = _call_counts.get(api_name, 0) + 1

    last_error: dict[str, Any] | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                raw = response.read().decode("utf-8", errors="replace")
                envelope = json.loads(raw)
                if not isinstance(envelope, dict):
                    return {"data": envelope}
                # AMiner can wrap errors in an HTTP-200 response, e.g. code 403
                # for insufficient balance/permission. Surface those instead of
                # letting them look like an empty result set.
                code = envelope.get("code")
                if isinstance(code, int) and code not in (0, 200):
                    raise ToolError({
                        "ok": False,
                        "error": ERROR_NAMES.get(code, "api_error"),
                        "api": api_name,
                        "code": code,
                        "message": _redact(str(envelope.get("msg") or envelope.get("message") or ""),
                                           token)[:300],
                    })
                return envelope
        except urllib.error.HTTPError as exc:
            detail = _redact(exc.read().decode("utf-8", errors="replace")[:500], token)
            last_error = {
                "ok": False,
                "error": "http_error",
                "api": api_name,
                "status": exc.code,
                "detail": detail,
            }
            if exc.code not in RETRYABLE_STATUS:
                break
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = {
                "ok": False,
                "error": "network_error",
                "api": api_name,
                "detail": _redact(str(getattr(exc, "reason", exc)), token)[:500],
            }
        except json.JSONDecodeError as exc:
            last_error = {
                "ok": False,
                "error": "invalid_response",
                "api": api_name,
                "detail": str(exc)[:200],
            }
            break
        if attempt < MAX_RETRIES:
            backoff = (2 ** (attempt - 1)) + random.uniform(0, 0.3)
            print(f"[retry] {api_name} attempt={attempt}/{MAX_RETRIES} wait={backoff:.1f}s",
                  file=sys.stderr)
            time.sleep(backoff)

    raise ToolError(last_error or {"ok": False, "error": "request_failed", "api": api_name})


def _envelope_items(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    data = envelope.get("data")
    if isinstance(data, dict):
        data = data.get("data") or data.get("items") or []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = str(item or "").strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _paper_id(item: dict[str, Any]) -> str:
    return str(item.get("id") or item.get("_id") or item.get("paper_id") or "").strip()


# ──────────────────────────────────────────────────────────────────────────────
# paper/info enrichment (free)
# ──────────────────────────────────────────────────────────────────────────────

def _fetch_paper_info(ids: list[str]) -> dict[str, dict[str, Any]]:
    """Batch-fetch lightweight cards; returns a map of id -> raw info entry."""
    info_by_id: dict[str, dict[str, Any]] = {}
    unique_ids = _dedupe(ids)
    for start in range(0, len(unique_ids), PAPER_INFO_BATCH_LIMIT):
        chunk = unique_ids[start:start + PAPER_INFO_BATCH_LIMIT]
        envelope = _request("paper_info", "POST", "/api/paper/info", body={"ids": chunk})
        for entry in _envelope_items(envelope):
            entry_id = _paper_id(entry)
            if entry_id:
                info_by_id[entry_id] = entry
    return info_by_id


def _venue_text(entry: dict[str, Any]) -> str:
    venue = entry.get("venue")
    if isinstance(venue, dict):
        return str(venue.get("raw") or venue.get("name") or "")
    return str(venue or entry.get("raw") or entry.get("venue_name") or "")


def _author_names(raw_authors: Any) -> list[str]:
    if not isinstance(raw_authors, list):
        return []
    names: list[str] = []
    for author in raw_authors:
        if isinstance(author, dict):
            name = str(author.get("name") or author.get("name_zh") or "").strip()
        else:
            name = str(author or "").strip()
        if name:
            names.append(name)
    return names


def _compact_paper(base: dict[str, Any], info: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = dict(info or {})
    item: dict[str, Any] = {
        "id": _paper_id(base) or _paper_id(merged),
        "title": str(base.get("title") or merged.get("title")
                     or base.get("title_zh") or merged.get("title_zh") or "").strip(),
    }
    year = merged.get("year") or base.get("year")
    if year:
        item["year"] = int(year)
    venue = _venue_text(merged) or _venue_text(base)
    if venue:
        item["venue"] = venue
    authors = _author_names(merged.get("authors")) or _author_names(base.get("authors"))
    if authors:
        item["authors"] = authors[:MAX_AUTHOR_NAMES]
    author_count = merged.get("author_count") or base.get("author_count")
    if author_count:
        item["author_count"] = int(author_count)
    first_author = str(base.get("first_author") or merged.get("first_author") or "").strip()
    if first_author and not authors:
        item["first_author"] = first_author
    doi = str(base.get("doi") or merged.get("doi") or "").strip()
    if doi:
        item["doi"] = doi
    # search/pro and qa/search now return a citation tier on the search result itself,
    # so it survives even when paper/info has nothing for the id.
    bucket = str(base.get("n_citation_bucket") or merged.get("n_citation_bucket") or "").strip()
    if bucket:
        item["n_citation_bucket"] = bucket
    abstract = str(merged.get("abstract_slice") or merged.get("abstract") or "").strip()
    if abstract:
        item["abstract_slice"] = abstract[:ABSTRACT_SLICE_LIMIT]
    if item["id"]:
        item["url"] = PAPER_URL_TEMPLATE.format(item["id"])
    return item


def _enrich(base_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach year/venue/authors/abstract_slice from the free paper/info endpoint."""
    ids = [_paper_id(item) for item in base_items if _paper_id(item)]
    info_by_id = _fetch_paper_info(ids) if ids else {}
    papers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in base_items:
        paper_id = _paper_id(item)
        if not paper_id or paper_id in seen:
            continue
        seen.add(paper_id)
        compact = _compact_paper(item, info_by_id.get(paper_id))
        if compact["id"] and compact["title"]:
            papers.append(compact)
    return papers


def _year_in_range(paper: dict[str, Any], year_from: int | None, year_to: int | None) -> bool:
    """Client-side year filter; papers with unknown year pass through."""
    year = paper.get("year")
    if not year:
        return True
    if year_from and int(year) < year_from:
        return False
    if year_to and int(year) > year_to:
        return False
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Subcommands
# ──────────────────────────────────────────────────────────────────────────────

def cmd_search(args: argparse.Namespace) -> list[dict[str, Any]]:
    field_params = {
        "keyword": args.query,
        "title": args.title,
        "abstract": args.abstract,
        "author": args.author,
        "org": args.org,
        "venue": args.venue,
    }
    if not any(value for value in field_params.values()):
        raise ToolError({
            "ok": False,
            "error": "invalid_request",
            "message": "search requires at least one of --query/--title/--abstract/--author/--org/--venue",
        }, exit_code=2)
    target = max(1, args.size)
    year_to = args.year_to or args.year  # --year is the deprecated alias of --year-to
    collected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page in range(max(1, args.max_pages)):
        params: dict[str, Any] = {
            "page": page,
            "size": SEARCH_PRO_PAGE_SIZE,
        }
        params.update({k: v for k, v in field_params.items() if v})
        if args.order:
            params["order"] = args.order
        envelope = _request("search_pro", "GET", "/api/paper/search/pro", params=params)
        page_items = _envelope_items(envelope)
        if not page_items:
            break
        enriched = _enrich(page_items)
        for paper in enriched:
            if paper["id"] in seen:
                continue
            if not _year_in_range(paper, args.year_from, year_to):
                continue
            seen.add(paper["id"])
            collected.append(paper)
        if len(collected) >= target or len(page_items) < SEARCH_PRO_PAGE_SIZE:
            break
    return collected[:target]


def cmd_qa_search(args: argparse.Namespace) -> list[dict[str, Any]]:
    # The backend only uses the `query` keyword-extraction result when
    # use_topic=true; with use_topic=false it reads `title` only, so a
    # query-only request ends up with empty terms and returns envelope 403.
    # Therefore always send use_topic=true.
    body: dict[str, Any] = {
        "use_topic": True,
        "size": max(1, args.size),
    }
    if args.query:
        body["query"] = args.query
    if args.topic_high:
        body["topic_high"] = args.topic_high
    if not args.query and not args.topic_high:
        raise ToolError({
            "ok": False,
            "error": "invalid_request",
            "message": "qa-search requires --query and/or --topic-high",
        }, exit_code=2)
    if args.year_from or args.year_to:
        year_from = args.year_from or 1900
        year_to = args.year_to or time.gmtime().tm_year
        body["year"] = list(range(year_from, year_to + 1))
    if args.citation_sort:
        body["force_citation_sort"] = True
    envelope = _request("qa_search", "POST", "/api/paper/qa/search", body=body)
    return _enrich(_envelope_items(envelope))


def cmd_qa_search_pro(args: argparse.Namespace) -> list[dict[str, Any]]:
    body: dict[str, Any] = {}
    if args.query:
        body["query"] = args.query
        body["query_type"] = args.query_type
    if args.authors:
        body["authors"] = args.authors
    if args.orgs:
        body["organizations"] = args.orgs
    if args.venues:
        body["venues"] = args.venues
    if args.year_from is not None:
        body["year_from"] = args.year_from
    if args.year_to is not None:
        body["year_to"] = args.year_to
    if args.languages:
        body["languages"] = args.languages
    if args.all_terms:
        body["all_terms"] = args.all_terms
    if args.any_terms:
        body["any_terms"] = args.any_terms
    if args.exclude_terms:
        body["exclude_terms"] = args.exclude_terms
    if args.search_in:
        body["search_in"] = args.search_in
    if args.min_citations is not None:
        body["min_citations"] = args.min_citations
    if args.max_citations is not None:
        body["max_citations"] = args.max_citations
    if args.sort:
        body["sort"] = args.sort
    if not (args.query or args.authors or args.orgs or args.venues
            or args.all_terms or args.any_terms):
        raise ToolError({
            "ok": False,
            "error": "invalid_request",
            "message": "qa-search-pro requires --query or at least one of "
                       "--authors/--orgs/--venues/--all-terms/--any-terms",
        }, exit_code=2)

    target = max(1, args.size)
    base_items: list[dict[str, Any]] = []
    cursor: str | None = None
    while len(base_items) < target:
        # Per the API doc, a continuation request must carry ONLY the cursor.
        payload = {"cursor": cursor} if cursor else body
        try:
            envelope = _request("qa_search_pro", "POST", "/api/paper/qa/searchPro", body=payload)
        except ToolError as exc:
            # Cursors can be invalidated server-side mid-pagination (upstream 410
            # "cursor 已过期或不存在"); a failed continuation must not discard the
            # already-paid-for pages, so return what was collected.
            if not base_items:
                raise
            print(f"[warning] qa_search_pro continuation failed "
                  f"({exc.payload.get('error')}); returning {len(base_items)} collected items",
                  file=sys.stderr)
            break
        data = envelope.get("data")
        if not isinstance(data, dict):
            break
        for warning in data.get("warnings") or []:
            if isinstance(warning, dict):
                print(f"[warning] qa_search_pro {warning.get('code')}: {warning.get('message')}",
                      file=sys.stderr)
        items = [item for item in (data.get("items") or []) if isinstance(item, dict)]
        if not items:
            break
        base_items.extend(items)
        cursor = data.get("next_cursor")
        if not cursor:
            break
    return _enrich(base_items)[:target]


def cmd_info(args: argparse.Namespace) -> list[dict[str, Any]]:
    info_by_id = _fetch_paper_info(args.ids)
    return [_compact_paper(entry, None) for entry in info_by_id.values()]


def cmd_references(args: argparse.Namespace) -> list[dict[str, Any]]:
    seed_ids = _dedupe(args.ids)
    per_seed = max(1, args.per_seed)
    sources_by_id: dict[str, list[str]] = {}
    ordered_ids: list[str] = []
    seed_set = set(seed_ids)
    for seed_id in seed_ids:
        envelope = _request("relation", "GET", "/api/paper/relation",
                            params={"id": seed_id})
        cited_ids: list[str] = []
        for item in _envelope_items(envelope):
            cited = item.get("cited") or []
            if not isinstance(cited, list):
                continue
            for cited_item in cited:
                cited_id = _paper_id(cited_item) if isinstance(cited_item, dict) else str(cited_item or "").strip()
                if cited_id:
                    cited_ids.append(cited_id)
        for cited_id in _dedupe(cited_ids)[:per_seed]:
            if cited_id in seed_set:
                continue
            if cited_id not in sources_by_id:
                sources_by_id[cited_id] = []
                ordered_ids.append(cited_id)
            sources_by_id[cited_id].append(seed_id)

    papers = _enrich([{"id": paper_id} for paper_id in ordered_ids])
    for paper in papers:
        paper["source_paper_ids"] = sources_by_id.get(paper["id"], [])
    return papers


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="AMiner Open Platform tool commands (stdout: JSON only; diagnostics: stderr)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="Fielded keyword search via paper/search/pro (¥0.01/page).")
    p_search.add_argument("--query", default=None, help="Keyword (maps to the `keyword` field).")
    p_search.add_argument("--title", default=None, help="Title phrase filter.")
    p_search.add_argument("--abstract", default=None, help="Abstract phrase filter.")
    p_search.add_argument("--author", default=None, help="Author name filter.")
    p_search.add_argument("--org", default=None, help="Institution name filter.")
    p_search.add_argument("--venue", default=None, help="Journal/conference name filter.")
    p_search.add_argument("--size", type=int, default=20, help="Papers to return (default 20).")
    p_search.add_argument("--year-from", type=int, default=None,
                          help="Inclusive publication start year (client-side filter).")
    p_search.add_argument("--year-to", type=int, default=None,
                          help="Inclusive publication end year (client-side filter).")
    p_search.add_argument("--year", type=int, default=None, help=argparse.SUPPRESS)  # alias of --year-to
    p_search.add_argument("--order", choices=["n_citation", "year"], default=None)
    p_search.add_argument("--max-pages", type=int, default=3,
                          help="Max result pages to fetch (default 3, 100 results/page).")
    p_search.set_defaults(func=cmd_search)

    p_qa = sub.add_parser("qa-search", help="Natural-language search via paper/qa/search (¥0.05/call).")
    p_qa.add_argument("--query", default=None, help="Natural-language question.")
    p_qa.add_argument("--topic-high", default=None,
                      help='Structured keywords, JSON string like [["termA","termB"],["termC"]] '
                           "(outer AND, inner OR).")
    p_qa.add_argument("--size", type=int, default=20)
    p_qa.add_argument("--year-from", type=int, default=None)
    p_qa.add_argument("--year-to", type=int, default=None)
    p_qa.add_argument("--citation-sort", action="store_true",
                      help="Sort entirely by citation count.")
    p_qa.set_defaults(func=cmd_qa_search)

    p_qa_pro = sub.add_parser(
        "qa-search-pro",
        help="Structured-filter search via paper/qa/searchPro (¥0.30 per 10-result page).")
    p_qa_pro.add_argument("--query", default=None, help="Search text, max 500 chars.")
    p_qa_pro.add_argument("--query-type", default="auto",
                          choices=["auto", "topic", "keywords", "title", "identifier"])
    p_qa_pro.add_argument("--authors", nargs="+", default=None, help="Author names (OR within list).")
    p_qa_pro.add_argument("--orgs", nargs="+", default=None, help="Organization names (OR within list).")
    p_qa_pro.add_argument("--venues", nargs="+", default=None, help='Venue names, e.g. NeurIPS (OR).')
    p_qa_pro.add_argument("--year-from", type=int, default=None, help="Start year (inclusive).")
    p_qa_pro.add_argument("--year-to", type=int, default=None, help="End year (inclusive).")
    p_qa_pro.add_argument("--languages", nargs="+", default=None,
                          help="Hard language filter, e.g. en zh.")
    p_qa_pro.add_argument("--all-terms", nargs="+", default=None,
                          help="Every term must match (max 20).")
    p_qa_pro.add_argument("--any-terms", nargs="+", default=None,
                          help="At least one term must match.")
    p_qa_pro.add_argument("--exclude-terms", nargs="+", default=None,
                          help="Exclude papers matching any of these terms.")
    p_qa_pro.add_argument("--search-in", default=None,
                          choices=["all", "title", "title_keywords", "abstract"],
                          help="Scope for all/any/exclude terms only.")
    p_qa_pro.add_argument("--min-citations", type=int, default=None)
    p_qa_pro.add_argument("--max-citations", type=int, default=None)
    p_qa_pro.add_argument("--sort", default=None,
                          choices=["relevance", "balanced", "recent", "citation"])
    p_qa_pro.add_argument("--size", type=int, default=10,
                          help="Papers to return; each 10-result page costs ¥0.30 (default 10).")
    p_qa_pro.set_defaults(func=cmd_qa_search_pro)

    p_info = sub.add_parser("info", help="Batch metadata via paper/info (free, <=100 ids/batch).")
    p_info.add_argument("--ids", nargs="+", required=True)
    p_info.set_defaults(func=cmd_info)

    p_refs = sub.add_parser("references",
                            help="Backward-reference expansion via paper/relation (¥0.10/seed).")
    p_refs.add_argument("--ids", nargs="+", required=True, help="Seed AMiner paper IDs.")
    p_refs.add_argument("--per-seed", type=int, default=20,
                        help="Max references kept per seed (default 20).")
    p_refs.set_defaults(func=cmd_references)

    return parser


def _print_cost_summary() -> None:
    if not _call_counts:
        return
    total = sum(PRICE_CNY.get(name, 0.0) * count for name, count in _call_counts.items())
    parts = " + ".join(f"{name} x{count}" for name, count in sorted(_call_counts.items()))
    print(f"[cost] {parts} = ¥{total:.2f}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = args.func(args)
    except ToolError as exc:
        print(json.dumps(exc.payload, ensure_ascii=False), file=sys.stdout)
        _print_cost_summary()
        return exc.exit_code
    print(json.dumps(result, ensure_ascii=False, indent=2))
    _print_cost_summary()
    return 0


if __name__ == "__main__":
    sys.exit(main())
