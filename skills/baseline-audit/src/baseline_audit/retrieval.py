"""AMiner-first direct-baseline retrieval with explicit provider fallbacks."""

from __future__ import annotations

import re
import time
from collections import Counter
from datetime import date
from difflib import SequenceMatcher
from http import HTTPStatus
from typing import Any, Callable
from urllib.parse import quote_plus
from xml.etree import ElementTree as etree

import httpx

from .aminer_open import (
    AMINER_SEARCH_TIERS,
    list_aminer_by_keywords,
    search_aminer_query,
)
from .relation import publication_cutoff_status


RETRIEVAL_RESULTS_PER_QUERY = 20
MAX_BIBLIOGRAPHY_VERIFICATIONS = 60
MAX_DIRECT_SEMANTIC_POOL = 80
BASELINE_RETRIEVAL_QUERY_ROLES = (
    "named_method_or_family",
    "task_and_evaluation_setting",
    "current_comparison_set",
    "alternative_method_family",
)
BASELINE_ALTERNATIVE_QUERY_ROLE = BASELINE_RETRIEVAL_QUERY_ROLES[3]
BASELINE_BIBLIOGRAPHY_ROLE = "cited_not_compared_reference"
BASELINE_KEYWORD_FEEDBACK_ROLE = "keyword_batch_feedback"
BASELINE_RELATION_ROLES = (
    "citation_graph_reference",
)
RETRIEVAL_PROVIDERS = ("aminer", "openalex", "arxiv")
EXTERNAL_FALLBACK_PROVIDERS = ("none", "openalex", "arxiv")
BASELINE_DIRECT_RETRIEVAL_ROLES = (
    BASELINE_BIBLIOGRAPHY_ROLE,
    *BASELINE_RELATION_ROLES,
    BASELINE_KEYWORD_FEEDBACK_ROLE,
    *BASELINE_RETRIEVAL_QUERY_ROLES[:3],
)
RETRIEVAL_STOPWORDS = {
    "a", "an", "and", "as", "at", "based", "by", "for", "from", "in",
    "large", "language", "method", "methods", "model", "models", "of", "on",
    "or", "paper", "review", "study", "the", "to", "using", "with", "multi",
    "modal", "multimodal",
}
RETRIEVAL_GENERIC_TOKENS = {
    "analysis", "benchmark", "benchmarks", "comparison", "comparisons", "dataset",
    "datasets", "encoder", "encoders", "evaluation", "evaluations", "feature",
    "features", "framework", "learning", "reasoning", "representation",
    "representations", "task", "tasks", "vision", "visual",
}
_KEYWORD_FEEDBACK_GENERIC_TOKENS = RETRIEVAL_STOPWORDS | RETRIEVAL_GENERIC_TOKENS | {
    "approach", "approaches", "comparable", "evaluation", "experimental", "find",
    "paper", "please", "protocol",
    "ranking", "recommendation", "recommender", "results", "system", "systems",
    "user", "users",
}

SelectionFunction = Callable[..., tuple[list[dict[str, str]], dict[str, Any]]]


def baseline_feedback_keywords(retrieval_plan: dict[str, Any]) -> list[str]:
    """Build short controlled terms; never send task sentences to the keyword API."""
    values: list[str] = []

    def add_named(value: Any) -> None:
        rendered = " ".join(str(value or "").split()).strip(" ,.;:")
        if not rendered:
            return
        # Method/dataset names are already controlled vocabulary. Keep at most a
        # compact four-token name and never forward explanatory prose.
        tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9+_.-]*", rendered)
        if tokens:
            values.append(" ".join(tokens[:4])[:64])

    raw_cited = retrieval_plan.get("cited_not_compared")
    if isinstance(raw_cited, list):
        for item in raw_cited:
            if not isinstance(item, dict):
                continue
            add_named(item.get("method_name") or item.get("title"))
    for key in ("current_baselines", "datasets_or_benchmarks"):
        raw = retrieval_plan.get(key)
        if isinstance(raw, list):
            for item in raw:
                add_named(item)
    for key in ("method_family", "task"):
        raw_tokens = re.findall(
            r"[A-Za-z0-9][A-Za-z0-9+_.-]*",
            str(retrieval_plan.get(key) or ""),
        )
        distinctive = [
            token
            for token in raw_tokens
            if len(token) >= 3
            and token.casefold() not in _KEYWORD_FEEDBACK_GENERIC_TOKENS
        ]
        if distinctive:
            values.append(" ".join(distinctive[:3])[:64])
    deduplicated: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if value and key not in seen:
            deduplicated.append(value)
            seen.add(key)
    return deduplicated[:8]


def arxiv_search(
    query: str,
    client: httpx.Client,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict[str, str]]:
    url = (
        "https://export.arxiv.org/api/query?search_query=all:"
        + quote_plus(query)
        + f"&start=0&max_results={RETRIEVAL_RESULTS_PER_QUERY}"
    )
    response: httpx.Response | None = None
    for attempt in range(3):
        response = client.get(
            url,
            headers={"User-Agent": "StandaloneBaselineAudit/0.1"},
        )
        if response.status_code != HTTPStatus.TOO_MANY_REQUESTS:
            break
        sleep(2 * (attempt + 1))
    if response is None:
        return []
    response.raise_for_status()
    root = etree.fromstring(response.text)
    namespace = {"atom": "http://www.w3.org/2005/Atom"}
    records: list[dict[str, str]] = []
    for entry in root.findall("atom:entry", namespace):
        title = " ".join(
            entry.findtext("atom:title", default="", namespaces=namespace).split()
        )
        summary = " ".join(
            entry.findtext("atom:summary", default="", namespaces=namespace).split()
        )
        published = entry.findtext(
            "atom:published", default="", namespaces=namespace
        )[:10]
        identifier = entry.findtext("atom:id", default="", namespaces=namespace)
        authors = [
            author.findtext("atom:name", default="", namespaces=namespace)
            for author in entry.findall("atom:author", namespace)
        ]
        if title:
            records.append(
                {
                    "title": title,
                    "authors": ", ".join(author for author in authors if author),
                    "published": published,
                    "url": identifier,
                    "summary": summary[:1100],
                    "query": query,
                    "source": "arXiv API",
                }
            )
    return records


def openalex_abstract(record: dict[str, Any]) -> str:
    positions = record.get("abstract_inverted_index") or {}
    if not isinstance(positions, dict):
        return ""
    words: list[tuple[int, str]] = []
    for word, offsets in positions.items():
        if isinstance(offsets, list):
            words.extend(
                (int(offset), str(word))
                for offset in offsets
                if isinstance(offset, int)
            )
    return " ".join(word for _, word in sorted(words))


def openalex_search(
    query: str,
    client: httpx.Client,
    *,
    review_as_of: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict[str, str]]:
    params: dict[str, str | int] = {
        "search": query,
        "per-page": RETRIEVAL_RESULTS_PER_QUERY,
    }
    if review_as_of:
        params["filter"] = (
            f"from_publication_date:1900-01-01,to_publication_date:{review_as_of}"
        )
    response: httpx.Response | None = None
    for attempt in range(3):
        response = client.get(
            "https://api.openalex.org/works",
            params=params,
            headers={"User-Agent": "StandaloneBaselineAudit/0.1"},
        )
        if response.status_code not in {
            HTTPStatus.TOO_MANY_REQUESTS,
            HTTPStatus.SERVICE_UNAVAILABLE,
        }:
            break
        sleep(1.5 * (attempt + 1))
    if response is None:
        return []
    response.raise_for_status()
    payload = response.json()
    records: list[dict[str, str]] = []
    for item in payload.get("results", []):
        if not isinstance(item, dict) or not item.get("display_name"):
            continue
        authors = []
        for authorship in item.get("authorships") or []:
            author = authorship.get("author") if isinstance(authorship, dict) else {}
            if isinstance(author, dict) and author.get("display_name"):
                authors.append(str(author["display_name"]))
        location = item.get("primary_location") or {}
        source_url = (
            location.get("landing_page_url") if isinstance(location, dict) else None
        )
        records.append(
            {
                "title": str(item["display_name"]),
                "authors": ", ".join(authors),
                "published": str(item.get("publication_date") or ""),
                "url": str(source_url or item.get("doi") or item.get("id") or ""),
                "summary": openalex_abstract(item)[:1100],
                "query": query,
                "source": "OpenAlex",
            }
        )
    return records


def parse_iso_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def meaningful_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) >= 3 and token not in RETRIEVAL_STOPWORDS
    }


def reference_title_similarity(left: str, right: str) -> float:
    normalize = lambda value: re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return SequenceMatcher(None, normalize(left), normalize(right)).ratio()


def is_same_paper_title(candidate_title: str, local_title: str) -> bool:
    candidate = meaningful_tokens(candidate_title)
    local = meaningful_tokens(local_title)
    if not candidate or not local:
        return False
    overlap = len(candidate.intersection(local)) / min(len(candidate), len(local))
    return overlap >= 0.8 or reference_title_similarity(
        candidate_title, local_title
    ) >= 0.9


def retrieval_relevance_score(
    record: dict[str, str], local_title: str
) -> tuple[int, bool]:
    title_tokens = meaningful_tokens(str(record.get("title") or ""))
    summary_tokens = meaningful_tokens(str(record.get("summary") or ""))
    local_tokens = meaningful_tokens(local_title)
    # Bibliography verification uses the candidate's exact title as its query.
    # Counting that self-query as target relevance gives every verified
    # reference a large synthetic score, even when it is unrelated to the
    # uploaded paper, and can crowd genuine external discoveries out of the
    # bounded pool.  For this role, relevance must come only from the target
    # manuscript and candidate content/evidence.
    query_tokens = (
        set()
        if str(record.get("retrieval_role") or "") == BASELINE_BIBLIOGRAPHY_ROLE
        else meaningful_tokens(str(record.get("query") or ""))
    )
    distinctive_tokens = (local_tokens | query_tokens) - RETRIEVAL_GENERIC_TOKENS
    title_overlap = len(title_tokens & local_tokens)
    query_overlap = len(title_tokens & query_tokens)
    summary_overlap = len(summary_tokens & (local_tokens | query_tokens))
    return (
        title_overlap * 3 + query_overlap * 2 + min(summary_overlap, 2),
        bool(title_tokens & distinctive_tokens),
    )


def _numeric_relevance_score(record: dict[str, Any]) -> float:
    """Return a finite pre-selector relevance score for deterministic sorting."""
    try:
        score = float(record.get("relevance_score") or 0)
    except (TypeError, ValueError):
        return 0.0
    # NaN is the only float that is not equal to itself.  Avoid importing a
    # numeric package solely for a defensive diagnostic-sort guard.
    return (
        score
        if score == score and score not in {float("inf"), float("-inf")}
        else 0.0
    )


def _normalized_retrieval_identity(title: Any) -> str:
    """Normalize a title without collapsing non-Latin identities to empty."""
    return " ".join(re.findall(r"[^\W_]+", str(title or "").casefold()))


def _candidate_evidence_score(record: dict[str, Any]) -> tuple[int, dict[str, int]]:
    """Score source-independent evidence available before semantic selection.

    A bibliography record can earn evidence points for an exact title/context
    chain, but its source label alone earns nothing.  The same rule lets a
    well-identified external discovery candidate compete in the unified pool.
    """
    fulltext_verified = bool(
        record.get("candidate_fulltext_verified") is True
        and str(record.get("candidate_fulltext_source") or "").strip()
        and (
            record.get("candidate_fulltext_evidence")
            or record.get("candidate_fulltext_sections")
        )
    )
    try:
        bibliography_similarity = float(
            record.get("bibliography_title_similarity") or 0
        )
    except (TypeError, ValueError):
        bibliography_similarity = 0.0
    exact_local_chain = bool(
        bibliography_similarity >= 0.94
        and str(record.get("bibliography_entry") or "").strip()
        and str(record.get("citation_context") or "").strip()
    )
    components = {
        "candidate_fulltext": 4 * int(fulltext_verified),
        "candidate_abstract": 2
        * int(bool(str(record.get("summary") or "").strip())),
        "stable_identity": 1
        * int(
            bool(
                str(record.get("aminer_pub_id") or "").strip()
                or str(record.get("doi") or "").strip()
            )
        ),
        "exact_local_citation_chain": 3 * int(exact_local_chain),
        "relation_identity": 1
        * int(
            bool(
                str(record.get("relation_direction") or "").strip()
                and str(record.get("aminer_pub_id") or "").strip()
            )
        ),
        "availability_evidence": 1
        * int(bool(str(record.get("availability_evidence") or "").strip())),
    }
    return sum(components.values()), components


def unified_retrieval_pool(
    candidates: list[dict[str, Any]],
    *,
    limit: int,
    allowed_roles: tuple[str, ...] | None = None,
    preserve_retained_input_order: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Rank one source-neutral pool, deduplicate identities, then apply a cap.

    Relevance is the primary order because it captures the target/query match;
    objective evidence maturity breaks ties.  Source and retrieval role are
    recorded for audit but never reserve capacity.  Normalized title and stable
    identifiers make the remaining order deterministic.
    """
    eligible: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    allowed = set(allowed_roles) if allowed_roles is not None else None
    for candidate in candidates:
        role = str(candidate.get("retrieval_role") or "")
        if allowed is not None and role not in allowed:
            unsupported.append(candidate)
            continue
        title = str(candidate.get("title") or "").strip()
        if not title:
            unsupported.append(candidate)
            continue
        eligible.append(dict(candidate))

    def rank_key(item: dict[str, Any]) -> tuple[Any, ...]:
        evidence_score, _components = _candidate_evidence_score(item)
        distinctive = str(
            item.get("has_distinctive_title_overlap") or ""
        ).strip().lower() in {"1", "true", "yes"}
        normalized_title = _normalized_retrieval_identity(item.get("title"))
        return (
            -_numeric_relevance_score(item),
            -evidence_score,
            -int(distinctive),
            normalized_title,
            str(item.get("doi") or "").casefold(),
            str(item.get("aminer_pub_id") or "").casefold(),
        )

    # Resolve duplicate title identities by the same objective rank rather than
    # silently letting whichever source happened to arrive first win.
    best_by_title: dict[str, dict[str, Any]] = {}
    duplicate_records: list[dict[str, Any]] = []
    for candidate in eligible:
        identity = _normalized_retrieval_identity(candidate.get("title"))
        previous = best_by_title.get(identity)
        if previous is None:
            best_by_title[identity] = candidate
            continue
        if rank_key(candidate) < rank_key(previous):
            kept, omitted = candidate, previous
            best_by_title[identity] = candidate
        else:
            kept, omitted = previous, candidate
        duplicate_records.append(
            {
                "identity": identity,
                "kept_title": str(kept.get("title") or ""),
                "kept_role": str(kept.get("retrieval_role") or ""),
                "omitted_title": str(omitted.get("title") or ""),
                "omitted_role": str(omitted.get("retrieval_role") or ""),
                "reason": "normalized_title_identity_duplicate",
            }
        )

    ranked = sorted(best_by_title.values(), key=rank_key)
    bounded_limit = max(0, int(limit))
    ranked_kept = ranked[:bounded_limit]
    truncated = ranked[bounded_limit:]
    if preserve_retained_input_order:
        kept_identities = {
            _normalized_retrieval_identity(item.get("title"))
            for item in ranked_kept
        }
        kept = [
            candidate
            for identity, candidate in best_by_title.items()
            if identity in kept_identities
        ]
    else:
        kept = ranked_kept

    def audit_record(item: dict[str, Any], *, rank: int) -> dict[str, Any]:
        evidence_score, components = _candidate_evidence_score(item)
        return {
            "rank": rank,
            "title": str(item.get("title") or ""),
            "retrieval_role": str(item.get("retrieval_role") or ""),
            "source": str(item.get("source") or ""),
            "relevance_score": _numeric_relevance_score(item),
            "evidence_score": evidence_score,
            "evidence_components": components,
        }

    return kept, {
        "policy": (
            "one source-neutral relevance-first pool; objective evidence breaks "
            "ties; normalized identity and title make ordering deterministic"
        ),
        "limit": bounded_limit,
        "input_count": len(candidates),
        "eligible_input_count": len(eligible),
        "unique_candidate_count": len(ranked),
        "included_count": len(kept),
        "included_candidates": [
            audit_record(item, rank=index)
            for index, item in enumerate(ranked_kept, start=1)
        ],
        "truncated_count": len(truncated),
        "truncated_candidates": [
            audit_record(item, rank=bounded_limit + index)
            for index, item in enumerate(truncated, start=1)
        ],
        "identity_duplicate_count": len(duplicate_records),
        "identity_deduplications": duplicate_records,
        "unsupported_or_untitled_count": len(unsupported),
        "source_or_role_capacity_reservations": False,
        "retained_output_order": (
            "stable_input_order"
            if preserve_retained_input_order
            else "unified_rank_order"
        ),
    }


def filter_retrieval_records(
    records: list[dict[str, str]],
    *,
    local_title: str,
    review_as_of: str,
    max_records: int = 40,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    cutoff = parse_iso_date(review_as_of)
    diagnostics: dict[str, Any] = {
        "review_as_of": review_as_of,
        "local_title_detected": bool(local_title),
        "raw_record_count": len(records),
        "duplicate_records_removed": 0,
        "self_records_removed": 0,
        "future_records_removed": 0,
        "undated_records_removed": 0,
        "low_relevance_records_removed": 0,
        "generic_only_records_removed": 0,
    }
    admissible: list[dict[str, Any]] = []
    missing_title_count = 0
    for item in records:
        title = str(item.get("title") or "").strip()
        if not title:
            missing_title_count += 1
            continue
        if local_title and is_same_paper_title(title, local_title):
            diagnostics["self_records_removed"] += 1
            continue
        time_status = publication_cutoff_status(
            str(item.get("published") or ""), review_as_of
        )
        if cutoff and time_status == "undated":
            diagnostics["undated_records_removed"] += 1
            continue
        if cutoff and time_status == "after_cutoff":
            diagnostics["future_records_removed"] += 1
            continue
        if cutoff and time_status == "uncertain_same_year":
            locally_cited = bool(
                item.get("local_citation_before_review_cutoff")
                and str(item.get("retrieval_role") or "")
                == BASELINE_BIBLIOGRAPHY_ROLE
                and item.get("bibliography_entry")
                and item.get("citation_context")
            )
            if not locally_cited:
                diagnostics["same_year_uncertain_records_removed"] = (
                    diagnostics.get("same_year_uncertain_records_removed", 0) + 1
                )
                continue
            diagnostics["same_year_locally_cited_records_admitted"] = (
                diagnostics.get("same_year_locally_cited_records_admitted", 0) + 1
            )
        relevance, distinctive = retrieval_relevance_score(item, local_title)
        entry = dict(item)
        if cutoff and time_status == "uncertain_same_year":
            entry.update(
                {
                    "cutoff_status": "admissible_via_local_citation",
                    "aminer_cutoff_status": "uncertain_same_year",
                    "aminer_publication_date_precision": "year_only",
                    "availability_evidence": (
                        "The cutoff-dated manuscript itself contains the exact TEI "
                        "bibliography entry and an inline citation context."
                    ),
                }
            )
        entry["relevance_score"] = str(relevance)
        entry["has_distinctive_title_overlap"] = str(distinctive).lower()
        admissible.append(entry)
    accepted, unified_diagnostics = unified_retrieval_pool(
        admissible,
        limit=max_records,
    )
    diagnostics["duplicate_records_removed"] = int(
        unified_diagnostics["identity_duplicate_count"]
    )
    diagnostics["missing_title_records_removed"] = missing_title_count
    included_bibliography = sum(
        str(item.get("retrieval_role") or "") == BASELINE_BIBLIOGRAPHY_ROLE
        for item in accepted
    )
    truncated_bibliography = sum(
        str(item.get("retrieval_role") or "") == BASELINE_BIBLIOGRAPHY_ROLE
        for item in unified_diagnostics["truncated_candidates"]
    )
    # Keep the historic counters for machine-readable compatibility, but their
    # values now describe the unified cap rather than a bibliography reservation.
    diagnostics["verified_bibliography_preserved_count"] = included_bibliography
    diagnostics["verified_bibliography_filter_truncated_count"] = max(
        0, truncated_bibliography
    )
    diagnostics["candidate_record_count"] = int(
        unified_diagnostics["unique_candidate_count"]
    )
    diagnostics["kept_record_count"] = len(accepted)
    diagnostics["unified_candidate_pool"] = unified_diagnostics
    diagnostics["status"] = (
        "candidates_ready" if accepted else "no_admissible_records"
    )
    diagnostics["policy"] = (
        "Records after the review cutoff and records matching the uploaded paper "
        "title are removed. Exact dates must be on or before the cutoff; year-only "
        "records in the cutoff year are withheld unless an exact TEI bibliography "
        "entry plus inline citation proves local availability before the cutoff. "
        "All admissible sources share one relevance-ranked pool; objective "
        "evidence breaks ties, no source or role reserves capacity, and a model "
        "performs final direct-baseline selection."
    )
    return accepted, diagnostics


def role_balanced_baseline_pool(
    candidates: list[dict[str, str]],
    *,
    roles: tuple[str, ...],
    per_role: int = 8,
    limit: int = 24,
) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    seen_titles: set[str] = set()
    for role in roles:
        role_candidates: list[dict[str, str]] = []
        role_seen_titles: set[str] = set()
        for candidate in candidates:
            if str(candidate.get("retrieval_role") or "") != role:
                continue
            title = str(candidate.get("title") or "").strip()
            key = " ".join(title.lower().split())
            if not title or key in seen_titles or key in role_seen_titles:
                continue
            role_seen_titles.add(key)
            role_candidates.append(candidate)

        # Planning labels every evidence-qualified bibliography item with a
        # reusable mechanism branch.  Round-robin those branches before the
        # per-role cap so a late, distinct branch is not crowded out by many
        # earlier records from one family.  Unlabelled records preserve order.
        branch_queues: dict[str, list[dict[str, str]]] = {}
        for candidate in role_candidates:
            branch = " ".join(
                str(candidate.get("mechanism_branch") or "").lower().split()
            )
            branch_queues.setdefault(branch or "__unspecified__", []).append(candidate)
        balanced: list[dict[str, str]] = []
        branch_order = list(branch_queues)
        while len(balanced) < len(role_candidates):
            progressed = False
            for branch in branch_order:
                queue = branch_queues[branch]
                if not queue:
                    continue
                balanced.append(queue.pop(0))
                progressed = True
            if not progressed:
                break

        for candidate in balanced[:per_role]:
            selected.append(candidate)
            seen_titles.add(
                " ".join(str(candidate.get("title") or "").lower().split())
            )
            if len(selected) >= limit:
                break
        if len(selected) >= limit:
            break
    return selected


def semantic_baseline_pool(
    candidates: list[dict[str, Any]],
    *,
    limit: int = MAX_DIRECT_SEMANTIC_POOL,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build one bounded direct-candidate pool without source/role quotas."""
    bibliography = [
        candidate
        for candidate in candidates
        if str(candidate.get("retrieval_role") or "") == BASELINE_BIBLIOGRAPHY_ROLE
    ]
    pool, unified_diagnostics = unified_retrieval_pool(
        candidates,
        limit=limit,
        allowed_roles=BASELINE_DIRECT_RETRIEVAL_ROLES,
    )
    kept_bibliography = sum(
        str(candidate.get("retrieval_role") or "") == BASELINE_BIBLIOGRAPHY_ROLE
        for candidate in pool
    )
    return pool, {
        "total_limit": limit,
        "verified_bibliography_count": len(bibliography),
        "verified_bibliography_included": kept_bibliography,
        "verified_bibliography_truncated": max(
            0, len(bibliography) - kept_bibliography
        ),
        "other_candidates_included": len(pool) - kept_bibliography,
        "pool_count": len(pool),
        "unified_candidate_pool": unified_diagnostics,
    }


def retrieve_baseline_candidates(
    queries: list[str],
    *,
    local_title: str,
    review_as_of: str,
    proxy: str | None,
    select_direct: SelectionFunction,
    retrieval_plan: dict[str, Any] | None = None,
    client_factory: Callable[..., Any] = httpx.Client,
    sleep: Callable[[float], None] = time.sleep,
    arxiv_search_fn: Callable[..., list[dict[str, str]]] = arxiv_search,
    openalex_search_fn: Callable[..., list[dict[str, str]]] = openalex_search,
    aminer_search_fn: Callable[..., tuple[list[dict[str, Any]], dict[str, Any]]] = search_aminer_query,
    keyword_search_fn: Callable[..., tuple[list[dict[str, Any]], dict[str, Any]]] = list_aminer_by_keywords,
    provider: str = "aminer",
    external_fallback_provider: str = "none",
    aminer_search_tier: str = "auto",
    aminer_detail_limit: int = 3,
    seed_records: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    selected_provider = provider.strip().lower()
    selected_fallback = external_fallback_provider.strip().lower()
    if selected_provider not in RETRIEVAL_PROVIDERS:
        raise ValueError(f"Unknown retrieval provider: {provider}")
    if selected_fallback not in EXTERNAL_FALLBACK_PROVIDERS:
        raise ValueError(
            f"Unknown external fallback provider: {external_fallback_provider}"
        )
    if aminer_search_tier not in AMINER_SEARCH_TIERS:
        raise ValueError(f"Unknown AMiner search tier: {aminer_search_tier}")
    if not 0 <= int(aminer_detail_limit) <= 20:
        raise ValueError("AMiner detail limit must be between 0 and 20.")
    relation_seed_records = [dict(item) for item in seed_records or []]
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    query_diagnostics: list[dict[str, Any]] = []
    api_calls: Counter[str] = Counter()
    estimated_costs: Counter[str] = Counter()

    def collect_aminer_diagnostics(aminer_diagnostic: dict[str, Any]) -> None:
        for name, count in dict(aminer_diagnostic.get("api_calls") or {}).items():
            api_calls[str(name)] += int(count)
        for name, cost in dict(
            aminer_diagnostic.get("estimated_cost_cny_by_api") or {}
        ).items():
            estimated_costs[str(name)] += float(cost)
        errors.extend(
            str(error) for error in aminer_diagnostic.get("provider_errors") or []
        )

    def external_search(
        provider_name: str, query: str, client: Any
    ) -> list[dict[str, str]]:
        if provider_name == "openalex":
            return openalex_search_fn(query, client, review_as_of=review_as_of)
        if provider_name == "arxiv":
            return arxiv_search_fn(query, client)
        return []

    plan = retrieval_plan if isinstance(retrieval_plan, dict) else {}
    raw_references = plan.get("cited_not_compared")
    reference_candidates = (
        [item for item in raw_references if isinstance(item, dict)]
        if isinstance(raw_references, list)
        else []
    )
    raw_query_specs = plan.get("query_specs")
    query_specs = (
        [item for item in raw_query_specs if isinstance(item, dict)]
        if isinstance(raw_query_specs, list)
        else []
    )
    bibliography_diagnostics: list[dict[str, Any]] = []
    bibliography_verification_queue = reference_candidates[
        :MAX_BIBLIOGRAPHY_VERIFICATIONS
    ]
    bibliography_verification_truncated = max(
        0, len(reference_candidates) - len(bibliography_verification_queue)
    )

    with client_factory(proxy=proxy, timeout=25, follow_redirects=True) as client:
        # Stage 1: verify bibliography-derived, cited-but-not-compared titles before
        # broad external discovery. A fuzzy hit is never promoted as this role.
        if selected_provider == "aminer":
            for reference in bibliography_verification_queue:
                exact_title = " ".join(str(reference.get("title") or "").split())
                if not exact_title:
                    continue
                one_diagnostic: dict[str, Any] = {
                    "stage": "bibliography_exact_title_verification",
                    "query": exact_title,
                    "primary_provider": "aminer",
                    "fallback_provider": None,
                }
                try:
                    records, aminer_diagnostic = aminer_search_fn(
                        exact_title,
                        review_as_of=review_as_of,
                        client=client,
                        api_key="",
                        tier="free",
                        detail_limit=aminer_detail_limit,
                        query_shape="exact_title",
                        desired_results=10,
                        search_field="title",
                    )
                    one_diagnostic["aminer"] = aminer_diagnostic
                    collect_aminer_diagnostics(aminer_diagnostic)
                    ranked_matches = sorted(
                        (
                            (
                                reference_title_similarity(
                                    exact_title, str(record.get("title") or "")
                                ),
                                record,
                            )
                            for record in records
                        ),
                        key=lambda pair: pair[0],
                        reverse=True,
                    )
                    verified = [
                        (score, record)
                        for score, record in ranked_matches
                        if score >= 0.94
                    ]
                    if verified:
                        score, record = verified[0]
                        entry = dict(record)
                        entry.update(
                            {
                                "query": exact_title,
                                "retrieval_role": BASELINE_BIBLIOGRAPHY_ROLE,
                                "bibliography_title": exact_title,
                                "bibliography_title_similarity": round(score, 4),
                                "citation_context": str(
                                    reference.get("citation_context") or ""
                                ),
                                "method_name": str(
                                    reference.get("method_name") or ""
                                ),
                                "mechanism_branch": str(
                                    reference.get("mechanism_branch") or ""
                                ),
                                "task_protocol_relevance": str(
                                    reference.get("task_protocol_relevance") or ""
                                ),
                                "bibliography_reason": str(reference.get("reason") or ""),
                                "bibliography_entry": str(
                                    reference.get("bibliography_entry") or ""
                                ),
                                "bibliography_tei_id": str(
                                    reference.get("bibliography_tei_id") or ""
                                ),
                                "bibliography_authors": list(
                                    reference.get("bibliography_authors") or []
                                ),
                                "bibliography_year": reference.get(
                                    "bibliography_year"
                                ),
                                "citation_ref_target": str(
                                    reference.get("citation_ref_target") or ""
                                ),
                                "citation_ref_label": str(
                                    reference.get("citation_ref_label") or ""
                                ),
                                "citation_link_method": str(
                                    reference.get("citation_link_method") or ""
                                ),
                                "citation_link_evidence": dict(
                                    reference.get("citation_link_evidence") or {}
                                ),
                                "bibliography_ordinal": reference.get(
                                    "bibliography_ordinal"
                                ),
                                "local_citation_before_review_cutoff": bool(
                                    reference.get(
                                        "local_citation_before_review_cutoff"
                                    )
                                ),
                                "experiment_comparison_status": str(
                                    reference.get("experiment_comparison_status") or ""
                                ),
                                "evidence_chain": str(
                                    reference.get("evidence_chain") or ""
                                ),
                                "bibliography_verification": "exact_title_verified",
                            }
                        )
                        results.append(entry)
                    one_diagnostic.update(
                        {
                            "record_count": len(records),
                            "verified_record_count": min(1, len(verified)),
                            "best_title_similarity": (
                                round(ranked_matches[0][0], 4)
                                if ranked_matches
                                else None
                            ),
                        }
                    )
                except Exception as exc:
                    errors.append(f"AMiner bibliography verification: {type(exc).__name__}")
                    one_diagnostic.update(
                        {"record_count": 0, "verified_record_count": 0}
                    )
                bibliography_diagnostics.append(one_diagnostic)

        # Preserve the strongest local provenance when the same AMiner paper is
        # also present in the citation graph. Exact TEI bibliography records are
        # intentionally inserted before relation and broad-search duplicates.
        results.extend(relation_seed_records)

        # Stage 2: use the planned AMiner route for broader candidate discovery.
        for index, query in enumerate(queries):
            query_records: list[dict[str, str]] = []
            spec = query_specs[index] if index < len(query_specs) else {}
            one_diagnostic: dict[str, Any] = {
                "stage": "external_discovery",
                "query": query,
                "primary_provider": selected_provider,
                "fallback_provider": None,
                "retrieval_role": (
                    str(spec.get("retrieval_role") or "")
                    or (
                        BASELINE_RETRIEVAL_QUERY_ROLES[index]
                        if index < len(BASELINE_RETRIEVAL_QUERY_ROLES)
                        else "baseline_discovery"
                    )
                ),
            }
            if selected_provider == "aminer":
                try:
                    query_records, aminer_diagnostic = aminer_search_fn(
                        query,
                        review_as_of=review_as_of,
                        client=client,
                        api_key="",
                        tier=aminer_search_tier,
                        detail_limit=aminer_detail_limit,
                        query_shape=str(spec.get("query_shape") or "auto"),
                        desired_results=int(spec.get("desired_results") or 20),
                        search_field=str(spec.get("search_field") or "keyword"),
                    )
                    one_diagnostic["aminer"] = aminer_diagnostic
                    collect_aminer_diagnostics(aminer_diagnostic)
                except Exception as exc:
                    errors.append(f"AMiner: {type(exc).__name__}")
            else:
                try:
                    query_records = external_search(selected_provider, query, client)
                except Exception as exc:
                    errors.append(f"{selected_provider}: {type(exc).__name__}")
            if not query_records and selected_fallback != "none":
                one_diagnostic["fallback_provider"] = selected_fallback
                one_diagnostic["fallback_reason"] = "primary_returned_no_records"
                try:
                    query_records = external_search(selected_fallback, query, client)
                except Exception as exc:
                    errors.append(f"{selected_fallback}: {type(exc).__name__}")
            one_diagnostic["record_count"] = len(query_records)
            query_diagnostics.append(one_diagnostic)
            role = str(one_diagnostic["retrieval_role"])
            for record in query_records:
                record.setdefault("retrieval_role", role)
            results.extend(query_records)
    query_roles = {
        query: BASELINE_RETRIEVAL_QUERY_ROLES[index]
        if index < len(BASELINE_RETRIEVAL_QUERY_ROLES)
        else "baseline_discovery"
        for index, query in enumerate(queries)
    }
    for record in results:
        if not record.get("retrieval_role"):
            record["retrieval_role"] = query_roles.get(
                str(record.get("query") or ""), "baseline_discovery"
            )
    filtered, diagnostics = filter_retrieval_records(
        results,
        local_title=local_title,
        review_as_of=review_as_of,
        max_records=80,
    )
    has_relation_seeds = bool(seed_records)
    has_bibliography_candidates = any(
        str(record.get("retrieval_role") or "") == BASELINE_BIBLIOGRAPHY_ROLE
        for record in filtered
    )
    direct_pool, semantic_pool_diagnostics = semantic_baseline_pool(filtered)
    alternative_pool = role_balanced_baseline_pool(
        filtered,
        roles=(BASELINE_ALTERNATIVE_QUERY_ROLE,),
        per_role=5,
        limit=5,
    )
    selected, selection_diagnostics = select_direct(
        direct_pool,
        local_title=local_title,
        queries=queries,
        review_as_of=review_as_of,
        retrieval_plan=retrieval_plan,
    )
    initial_effective_count = len(selected)
    initial_effective_roles = {
        str(record.get("retrieval_role") or "") for record in selected
    }
    initial_core_count = int(selection_diagnostics.get("core_candidate_count") or 0)
    if "core_candidate_count" not in selection_diagnostics:
        initial_core_count = sum(
            str(record.get("tier") or "") == "core" for record in selected
        )
    verified_cited_count = sum(
        str(record.get("retrieval_role") or "") == BASELINE_BIBLIOGRAPHY_ROLE
        and float(record.get("bibliography_title_similarity") or 0) >= 0.94
        and bool(record.get("citation_context"))
        for record in selected
    )
    bibliography_mode = "cited_not_compared" in plan
    critical_method_roles = {
        BASELINE_BIBLIOGRAPHY_ROLE,
        *BASELINE_RELATION_ROLES,
        "named_method_or_family",
        "task_and_evaluation_setting",
        "current_comparison_set",
    }
    feedback_reasons: list[str] = []
    if initial_core_count == 0:
        feedback_reasons.append("no_core_candidate_after_first_round")
    if initial_effective_count < 10:
        feedback_reasons.append("effective_candidate_count_below_evaluation_cap")
    if not initial_effective_roles.intersection(critical_method_roles):
        feedback_reasons.append("critical_method_role_missing")
    if reference_candidates and verified_cited_count == 0:
        feedback_reasons.append("no_verified_cited_candidate_selected")

    keyword_feedback_diagnostics: dict[str, Any] = {
        "attempted": False,
        "trigger_basis": "effective_coverage_after_selection_not_raw_result_count",
        "trigger_reasons": feedback_reasons,
        "round": 2,
        "max_retrieval_rounds": 2,
        "initial_effective_candidate_count": initial_effective_count,
        "initial_core_candidate_count": initial_core_count,
        "initial_verified_cited_candidate_count": verified_cited_count,
        "initial_effective_roles": sorted(initial_effective_roles),
    }
    if selected_provider == "aminer" and bibliography_mode and feedback_reasons:
        keywords = baseline_feedback_keywords(plan)
        keyword_feedback_diagnostics.update(
            {"attempted": bool(keywords), "keywords": keywords}
        )
        if keywords:
            try:
                with client_factory(
                    proxy=proxy, timeout=25, follow_redirects=True
                ) as feedback_client:
                    feedback_records, provider_diagnostics = keyword_search_fn(
                        keywords,
                        review_as_of=review_as_of,
                        client=feedback_client,
                        api_key="",
                        size=30,
                    )
                keyword_feedback_diagnostics["provider"] = provider_diagnostics
                collect_aminer_diagnostics(provider_diagnostics)
            except Exception as exc:
                feedback_records = []
                keyword_feedback_diagnostics["provider_error"] = type(exc).__name__
                errors.append(f"AMiner keyword feedback: {type(exc).__name__}")
            for record in feedback_records:
                record["retrieval_role"] = BASELINE_KEYWORD_FEEDBACK_ROLE
            keyword_feedback_diagnostics["raw_feedback_record_count"] = len(
                feedback_records
            )
            if feedback_records:
                results.extend(feedback_records)
                filtered, diagnostics = filter_retrieval_records(
                    results,
                    local_title=local_title,
                    review_as_of=review_as_of,
                    max_records=80,
                )
                has_bibliography_candidates = any(
                    str(record.get("retrieval_role") or "")
                    == BASELINE_BIBLIOGRAPHY_ROLE
                    for record in filtered
                )
                direct_pool, semantic_pool_diagnostics = semantic_baseline_pool(
                    filtered
                )
                alternative_pool = role_balanced_baseline_pool(
                    filtered,
                    roles=(BASELINE_ALTERNATIVE_QUERY_ROLE,),
                    per_role=5,
                    limit=5,
                )
                selected, selection_diagnostics = select_direct(
                    direct_pool,
                    local_title=local_title,
                    queries=queries,
                    review_as_of=review_as_of,
                    retrieval_plan=retrieval_plan,
                )
            keyword_feedback_diagnostics["final_effective_candidate_count"] = len(
                selected
            )
            keyword_feedback_diagnostics["final_core_candidate_count"] = int(
                selection_diagnostics.get("core_candidate_count") or 0
            )
            keyword_feedback_diagnostics["final_selected_roles"] = sorted(
                {
                    str(record.get("retrieval_role") or "")
                    for record in selected
                }
            )
    diagnostics["provider_errors"] = errors
    diagnostics["provider"] = selected_provider
    diagnostics["external_fallback_provider"] = selected_fallback
    diagnostics["aminer_search_tier"] = aminer_search_tier
    diagnostics["aminer_detail_limit"] = aminer_detail_limit
    diagnostics["query_diagnostics"] = query_diagnostics
    diagnostics["keyword_feedback"] = keyword_feedback_diagnostics
    diagnostics["semantic_candidate_pool"] = semantic_pool_diagnostics
    diagnostics["bibliography_first"] = {
        "enabled": bool(reference_candidates),
        "scope": "verification_order_only_not_candidate_capacity",
        "planned_title_count": len(reference_candidates),
        "verification_safety_limit": MAX_BIBLIOGRAPHY_VERIFICATIONS,
        "verification_attempted_title_count": len(
            bibliography_verification_queue
        ),
        "verification_truncated_title_count": bibliography_verification_truncated,
        "verification_truncated_titles": [
            str(item.get("title") or "")
            for item in reference_candidates[MAX_BIBLIOGRAPHY_VERIFICATIONS:]
        ],
        "verified_title_count": sum(
            int(item.get("verified_record_count") or 0)
            for item in bibliography_diagnostics
        ),
        "completed_before_external_discovery": True,
        "title_verification_diagnostics": bibliography_diagnostics,
    }
    diagnostics["api_calls"] = dict(api_calls)
    diagnostics["estimated_cost_cny_by_api"] = {
        name: round(cost, 2) for name, cost in estimated_costs.items()
    }
    diagnostics["estimated_cost_cny"] = round(sum(estimated_costs.values()), 2)
    diagnostics["external_fallback_used"] = any(
        item.get("fallback_provider") for item in query_diagnostics
    )
    diagnostics.update(selection_diagnostics)
    diagnostics["query_count"] = len(queries)
    diagnostics["retrieval_stage_order"] = [
        "bibliography_exact_title_verification",
        "external_discovery",
        "time_filter_and_deduplication",
        "two_tier_direct_baseline_selection",
        "controlled_keyword_feedback_if_effective_coverage_is_insufficient",
    ]
    diagnostics["retrieval_round_count"] = (
        2 if keyword_feedback_diagnostics.get("attempted") else 1
    )
    diagnostics["max_retrieval_rounds"] = 2
    if has_relation_seeds:
        diagnostics["relation_seed_count"] = len(seed_records or [])
    diagnostics["retrieval_scope"] = "direct_baseline_candidates_only"
    diagnostics["selection_view"] = (
        "two_tier_top10_cap"
        if str(diagnostics.get("selection_policy") or "").startswith("two_tier_")
        else "legacy_single_tier"
    )
    diagnostics["candidate_pool_by_role"] = dict(
        Counter(str(record.get("retrieval_role") or "unclassified") for record in filtered)
    )
    diagnostics["direct_candidate_pool_count"] = len(direct_pool)
    diagnostics["alternative_method_candidate_count"] = len(alternative_pool)
    diagnostics["alternative_method_candidates"] = [
        {
            key: record.get(key)
            for key in (
                "title", "authors", "published", "source", "summary", "url",
                "retrieval_role",
            )
            if record.get(key)
        }
        for record in alternative_pool
    ]
    diagnostics["role_policy"] = (
        "Exact-title-verified bibliography records, identity-verified AMiner backward "
        "references, and the first three method/task/comparison discovery roles enter "
        "one relevance/evidence-ranked direct-baseline pool. No source or role reserves "
        "capacity. Core requires a direct-performance purpose plus strict task, "
        "protocol, runnability, and candidate-full-text evidence. Extended may also "
        "contain evidence-grounded mechanism, budget, novelty, robustness, efficiency, "
        "or cross-task adaptation candidates that still require verification. Top-10 "
        "is a cap, not a quota. The fourth discovery role remains alternative-method "
        "context."
    )
    diagnostics["kept_record_count"] = len(selected)
    diagnostics["status"] = (
        "passed" if selected else "no_direct_baseline_candidates"
    )
    return selected, diagnostics
