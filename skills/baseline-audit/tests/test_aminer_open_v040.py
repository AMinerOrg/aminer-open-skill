"""AMiner Open Platform v0.4.x routing and identity-resolution tests."""

from __future__ import annotations

import json

import httpx

from baseline_audit.aminer_open import (
    list_aminer_by_keywords,
    resolve_title_to_pub_id,
    search_aminer_query,
)
from baseline_audit.identity import detect_skill_runtime
from baseline_audit.retrieval import (
    filter_retrieval_records,
    retrieve_baseline_candidates,
)


def _client_factory(handler):
    def factory(**kwargs):
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    return factory


def test_free_search_uses_v15_contract_and_enriches_with_paper_info() -> None:
    identifier = "111111111111111111111111"
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        assert request.headers["authorization"] == "test-key"
        assert request.headers["x-platform"] == detect_skill_runtime()
        assert request.headers["x-skill-name"] == "baseline-audit"
        assert request.headers["x-skill-version"] == "0.5.1"
        if request.method == "GET":
            assert request.url.path.endswith("/api/paper/search")
            assert dict(request.url.params) == {
                "query": "direct comparison method",
                "year_to": "2026",
                "page": "1",
                "size": "20",
            }
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "success": True,
                    "msg": "success",
                    "log_id": "search-log",
                    "total": 1,
                    "data": [
                        {
                            "id": identifier,
                            "title": "Direct Comparison Method",
                            "first_author": "Ada Author",
                            "year": 2025,
                            "venue_name": "TestConf",
                        }
                    ],
                },
            )
        assert json.loads(request.content) == {"ids": [identifier]}
        return httpx.Response(
            200,
            json={
                "code": 200,
                "success": True,
                "data": [
                    {
                        "id": identifier,
                        "title": "Direct Comparison Method",
                        "authors": [{"name": "Ada Author"}],
                        "abstract_slice": "A direct task comparison.",
                        "year": 2025,
                    }
                ],
            },
        )

    with _client_factory(handler)(timeout=10) as client:
        records, diagnostics = search_aminer_query(
            "direct comparison method",
            review_as_of="2026-10-29",
            client=client,
            api_key="test-key",
            detail_limit=0,
        )

    assert calls == [
        "/gateway/open_platform/api/paper/search",
        "/gateway/open_platform/api/paper/info",
    ]
    assert records[0]["aminer_pub_id"] == identifier
    assert records[0]["summary"] == "A direct task comparison."
    assert records[0]["published"] == "2025"
    assert diagnostics["selected_endpoint"] == "paper_search"
    assert diagnostics["query_plan"]["resolved_query_shape"] == "short_phrase"
    assert diagnostics["attempts"][0]["request"]["parameter_names"] == [
        "query",
        "year_to",
        "page",
        "size",
    ]
    assert diagnostics["response_metadata"]["log_id"] == "search-log"
    assert diagnostics["api_calls"] == {"paper_search": 1, "paper_info": 1}
    assert diagnostics["estimated_cost_cny"] == 0.0


def test_keyword_batch_feedback_uses_public_contract_once() -> None:
    identifier = "919191919191919191919191"
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.method == "GET":
            assert request.url.path.endswith(
                "/api/paper/list/citation/by/keywords"
            )
            params = dict(request.url.params)
            assert json.loads(params["keywords"]) == [
                "sequential recommendation",
                "MIND",
                "memory denoising",
            ]
            assert params["page"] == "0"
            assert params["size"] == "30"
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "success": True,
                    "data": [
                        {
                            "id": identifier,
                            "title": "Feedback Baseline",
                            "year": 2025,
                            "abstract": "A direct comparison on MIND.",
                        }
                    ],
                },
            )
        assert request.url.path.endswith("/api/paper/info")
        assert json.loads(request.content)["ids"] == [identifier]
        return httpx.Response(
            200,
            json={
                "code": 200,
                "success": True,
                "data": [
                    {
                        "id": identifier,
                        "title": "Feedback Baseline",
                        "year": 2025,
                        "abstract": "A direct comparison on MIND.",
                    }
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        records, diagnostics = list_aminer_by_keywords(
            ["sequential recommendation", "MIND", "memory denoising"],
            review_as_of="2026-10-29",
            client=client,
            api_key="test-key",
            size=30,
        )

    assert [record["title"] for record in records] == ["Feedback Baseline"]
    assert diagnostics["api_calls"] == {
        "paper_list_by_keywords": 1,
        "paper_info": 1,
    }
    assert diagnostics["estimated_cost_cny"] == 0.1
    assert len(calls) == 2


def test_default_free_chain_never_calls_paid_paper_detail() -> None:
    identifier = "aaaaaaaaaaaaaaaaaaaaaaaa"
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/api/paper/search"):
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "success": True,
                    "data": [{"id": identifier, "title": "No Abstract", "year": 2024}],
                },
            )
        if request.url.path.endswith("/api/paper/info"):
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "success": True,
                    "data": [{"id": identifier, "title": "No Abstract", "year": 2024}],
                },
            )
        raise AssertionError("paper_detail must be explicitly enabled")

    with _client_factory(handler)(timeout=10) as client:
        records, diagnostics = search_aminer_query(
            "no abstract",
            review_as_of="2026-10-29",
            client=client,
            api_key="test-key",
            detail_limit=0,
        )
    assert len(records) == 1
    assert records[0]["summary"] == ""
    assert diagnostics["api_calls"] == {"paper_search": 1, "paper_info": 1}
    assert not any(path.endswith("/api/paper/detail") for path in calls)


def test_paid_qa_permission_failure_downgrades_only_inside_aminer() -> None:
    identifier = "222222222222222222222222"
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/api/paper/qa/searchPro"):
            return httpx.Response(
                200,
                json={
                    "code": 403,
                    "success": False,
                    "msg": "department has no API permission",
                    "log_id": "permission-log",
                },
            )
        if request.url.path.endswith("/api/paper/qa/search"):
            assert json.loads(request.content) == {
                "use_topic": True,
                "query": "complex semantic baseline request",
                "size": 20,
                "offset": 0,
            }
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "success": True,
                    "data": [
                        {"id": identifier, "title": "Fallback Result", "year": 2024}
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "code": 200,
                "success": True,
                "data": [
                    {
                        "id": identifier,
                        "title": "Fallback Result",
                        "year": 2024,
                        "abstract_slice": "Enriched result.",
                    }
                ],
            },
        )

    with _client_factory(handler)(timeout=10) as client:
        records, diagnostics = search_aminer_query(
            "complex semantic baseline request",
            review_as_of="2026-10-29",
            client=client,
            api_key="test-key",
            tier="qa-pro",
            detail_limit=0,
        )

    assert len(records) == 1
    assert diagnostics["selected_endpoint"] == "paper_qa_search"
    assert diagnostics["downgrades"] == [
        {
            "from": "paper_qa_search_pro",
            "to": "paper_qa_search",
            "reason": "permission_or_balance",
            "trigger": "error",
        }
    ]
    assert "log_id=permission-log" in diagnostics["provider_errors"][0]
    assert diagnostics["estimated_cost_cny"] == 0.35
    assert not any("openalex" in path or "arxiv" in path for path in calls)


def test_auto_routes_fielded_bulk_phrase_to_search_pro_contract() -> None:
    identifier = "555555555555555555555555"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/paper/search/pro"):
            assert dict(request.url.params) == {
                "query": "sequential recommendation denoising",
                "year_to": "2026",
                "page": "0",
                "size": "40",
            }
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "success": True,
                    "data": [
                        {
                            "id": identifier,
                            "title": "Sequential Recommendation Denoising",
                            "year": 2025,
                        }
                    ],
                },
            )
        assert request.url.path.endswith("/api/paper/info")
        return httpx.Response(
            200,
            json={
                "code": 200,
                "success": True,
                "data": [
                    {
                        "id": identifier,
                        "title": "Sequential Recommendation Denoising",
                        "abstract_slice": "Direct denoising baseline.",
                        "year": 2025,
                    }
                ],
            },
        )

    with _client_factory(handler)(timeout=10) as client:
        records, diagnostics = search_aminer_query(
            "sequential recommendation denoising",
            review_as_of="2026-10-29",
            client=client,
            api_key="test-key",
            query_shape="fielded_phrase",
            desired_results=40,
            detail_limit=0,
        )
    assert len(records) == 1
    assert diagnostics["selected_endpoint"] == "paper_search_pro"
    assert diagnostics["api_calls"] == {"paper_search_pro": 1, "paper_info": 1}
    assert diagnostics["estimated_cost_cny"] == 0.01


def test_search_pro_exact_title_keeps_title_and_page_zero() -> None:
    identifier = "575757575757575757575757"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/paper/search/pro"):
            assert dict(request.url.params) == {
                "title": "An Exact Bibliography Title",
                "year_to": "2024",
                "page": "0",
                "size": "20",
            }
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "success": True,
                    "data": [
                        {
                            "id": identifier,
                            "title": "An Exact Bibliography Title",
                            "year": 2023,
                        }
                    ],
                },
            )
        assert request.url.path.endswith("/api/paper/info")
        return httpx.Response(
            200,
            json={
                "code": 200,
                "success": True,
                "data": [
                    {
                        "id": identifier,
                        "title": "An Exact Bibliography Title",
                        "year": 2023,
                        "abstract_slice": "Exact method metadata.",
                    }
                ],
            },
        )

    with _client_factory(handler)(timeout=10) as client:
        records, diagnostics = search_aminer_query(
            "An Exact Bibliography Title",
            review_as_of="2024-06-30",
            client=client,
            api_key="test-key",
            tier="search-pro",
            query_shape="exact_title",
            detail_limit=0,
        )
    assert [record["title"] for record in records] == [
        "An Exact Bibliography Title"
    ]
    attempt = diagnostics["attempts"][0]
    assert attempt["request"]["query_parameter"] == "title"
    assert attempt["request"]["parameter_names"] == [
        "title",
        "year_to",
        "page",
        "size",
    ]


def test_search_pro_permission_fallback_uses_free_query_and_cutoff_year() -> None:
    identifier = "585858585858585858585858"
    external_calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/paper/search/pro"):
            return httpx.Response(
                200,
                json={
                    "code": 403,
                    "success": False,
                    "msg": "no permission",
                    "log_id": "pro-permission-log",
                },
            )
        if request.url.path.endswith("/api/paper/search"):
            external_calls.append("aminer-free")
            assert dict(request.url.params) == {
                "query": "sequential recommendation denoising",
                "year_to": "2025",
                "page": "1",
                "size": "20",
            }
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "success": True,
                    "data": [
                        {
                            "id": identifier,
                            "title": "AMiner Free Fallback Result",
                            "year": 2024,
                        }
                    ],
                },
            )
        assert request.url.path.endswith("/api/paper/info")
        return httpx.Response(
            200,
            json={
                "code": 200,
                "success": True,
                "data": [
                    {
                        "id": identifier,
                        "title": "AMiner Free Fallback Result",
                        "year": 2024,
                        "abstract_slice": "Same task and protocol.",
                    }
                ],
            },
        )

    with _client_factory(handler)(timeout=10) as client:
        records, diagnostics = search_aminer_query(
            "sequential recommendation denoising",
            review_as_of="2025-12-01",
            client=client,
            api_key="test-key",
            tier="search-pro",
            query_shape="fielded_phrase",
            detail_limit=0,
        )
    assert len(records) == 1
    assert diagnostics["selected_endpoint"] == "paper_search"
    assert diagnostics["downgrades"] == [
        {
            "from": "paper_search_pro",
            "to": "paper_search",
            "reason": "permission_or_balance",
            "trigger": "error",
        }
    ]
    assert external_calls == ["aminer-free"]


def test_auto_routes_semantic_sentence_to_available_legacy_qa() -> None:
    identifier = "666666666666666666666666"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/paper/qa/search"):
            body = json.loads(request.content)
            assert body["query"].startswith("Find directly comparable")
            assert body["use_topic"] is True
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "success": True,
                    "data": [
                        {"id": identifier, "title": "Direct Semantic Match", "year": 2025}
                    ],
                },
            )
        assert request.url.path.endswith("/api/paper/info")
        return httpx.Response(
            200,
            json={
                "code": 200,
                "success": True,
                "data": [
                    {
                        "id": identifier,
                        "title": "Direct Semantic Match",
                        "abstract_slice": "Same task and protocol.",
                        "year": 2025,
                    }
                ],
            },
        )

    with _client_factory(handler)(timeout=10) as client:
        records, diagnostics = search_aminer_query(
            "Find directly comparable methods for sequential recommendation under the same evaluation protocol.",
            review_as_of="2026-10-29",
            client=client,
            api_key="test-key",
            detail_limit=0,
        )
    assert len(records) == 1
    assert diagnostics["query_plan"]["resolved_query_shape"] == "semantic_sentence"
    assert diagnostics["selected_endpoint"] == "paper_qa_search"
    assert diagnostics["api_calls"] == {"paper_qa_search": 1, "paper_info": 1}


def test_default_aminer_retrieval_does_not_silently_use_external_sources() -> None:
    external_calls: list[str] = []

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def aminer(*_args, **_kwargs):
        return [], {
            "status": "failed",
            "api_calls": {"paper_search": 1},
            "estimated_cost_cny_by_api": {"paper_search": 0.0},
            "provider_errors": ["AMiner unavailable"],
        }

    def external(*_args, **_kwargs):
        external_calls.append("called")
        return []

    records, diagnostics = retrieve_baseline_candidates(
        ["baseline query"],
        local_title="Uploaded Paper",
        review_as_of="2026-10-29",
        proxy=None,
        select_direct=lambda rows, **_kwargs: (rows, {}),
        client_factory=FakeClient,
        aminer_search_fn=aminer,
        openalex_search_fn=external,
        arxiv_search_fn=external,
    )
    assert records == []
    assert external_calls == []
    assert diagnostics["provider"] == "aminer"
    assert diagnostics["external_fallback_provider"] == "none"
    assert diagnostics["external_fallback_used"] is False


def test_baseline_retrieval_verifies_bibliography_titles_before_discovery() -> None:
    calls: list[tuple[str, str]] = []

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def aminer(query, **kwargs):
        calls.append((query, str(kwargs.get("query_shape"))))
        title = (
            "Denoising Self-Attentive Sequential Recommendation"
            if kwargs.get("query_shape") == "exact_title"
            else "An External Direct Baseline"
        )
        return [
            {
                "title": title,
                "authors": "A. Author",
                "published": "2025",
                "summary": "A direct sequential recommendation baseline.",
                "query": query,
                "source": "AMiner",
                "aminer_pub_id": "777777777777777777777777",
            }
        ], {
            "status": "completed",
            "api_calls": {"paper_search": 1},
            "estimated_cost_cny_by_api": {"paper_search": 0.0},
            "provider_errors": [],
        }

    records, diagnostics = retrieve_baseline_candidates(
        ["sequential recommendation baseline"],
        local_title="Uploaded Memory Recommender",
        review_as_of="2026-10-29",
        proxy=None,
        select_direct=lambda rows, **_kwargs: (rows, {"selection_status": "completed"}),
        retrieval_plan={
            "cited_not_compared": [
                {
                    "title": "Denoising Self-Attentive Sequential Recommendation",
                    "citation_context": "Discussed as a denoising method.",
                    "reason": "Not visible in the experiment table.",
                }
            ],
            "query_specs": [
                {
                    "query": "sequential recommendation baseline",
                    "retrieval_role": "named_method_or_family",
                    "query_shape": "short_phrase",
                    "desired_results": 20,
                    "search_field": "title",
                }
            ],
        },
        client_factory=FakeClient,
        aminer_search_fn=aminer,
        aminer_detail_limit=0,
    )

    assert calls == [
        ("Denoising Self-Attentive Sequential Recommendation", "exact_title"),
        ("sequential recommendation baseline", "short_phrase"),
    ]
    assert diagnostics["bibliography_first"]["verified_title_count"] == 1
    assert diagnostics["retrieval_stage_order"][0] == (
        "bibliography_exact_title_verification"
    )
    assert any(
        record["retrieval_role"] == "cited_not_compared_reference"
        for record in records
    )


def test_title_resolution_requires_one_title_plus_author_year_match() -> None:
    correct = "333333333333333333333333"
    other = "444444444444444444444444"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "success": True,
                    "data": [
                        {"id": correct, "title": "A Safe Paper Identity", "year": 2025},
                        {"id": other, "title": "A Safe Paper Identity", "year": 2024},
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "code": 200,
                "success": True,
                "data": [
                    {
                        "id": correct,
                        "title": "A Safe Paper Identity",
                        "year": 2025,
                        "authors": [{"name": "Ada Lovelace"}],
                        "abstract_slice": "Correct record.",
                    },
                    {
                        "id": other,
                        "title": "A Safe Paper Identity",
                        "year": 2024,
                        "authors": [{"name": "Other Author"}],
                    },
                ],
            },
        )

    matched, diagnostics = resolve_title_to_pub_id(
        "A Safe Paper Identity",
        authors=["Ada Lovelace"],
        publication_year=2025,
        review_as_of="2026-10-29",
        api_key="test-key",
        client_factory=_client_factory(handler),
    )
    assert matched == correct
    assert diagnostics["status"] == "matched_unique"


def test_title_only_is_never_claimed_as_pub_id() -> None:
    matched, diagnostics = resolve_title_to_pub_id(
        "A Title Without Identity Metadata",
        authors=[],
        publication_year=None,
        review_as_of="2026-10-29",
        api_key="test-key",
        client_factory=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("network must not be called")
        ),
    )
    assert matched is None
    assert diagnostics["status"] == "unavailable_missing_author_and_year"


def test_same_cutoff_year_without_exact_date_is_withheld() -> None:
    records, diagnostics = filter_retrieval_records(
        [
            {
                "title": "Same Year Candidate",
                "authors": "A",
                "published": "2026",
                "summary": "A direct baseline task.",
                "query": "direct baseline task",
                "source": "AMiner Open Platform paper_search",
            }
        ],
        local_title="Different Uploaded Paper",
        review_as_of="2026-10-29",
    )
    assert records == []
    assert diagnostics["same_year_uncertain_records_removed"] == 1


def test_exact_cutoff_date_is_kept_but_later_date_is_removed() -> None:
    records, diagnostics = filter_retrieval_records(
        [
            {
                "title": "Eligible Exact-date Candidate",
                "published": "2026-10-29",
                "summary": "A direct baseline task.",
                "query": "direct baseline task",
                "source": "AMiner",
            },
            {
                "title": "Future Exact-date Candidate",
                "published": "2026-10-30",
                "summary": "A direct baseline task.",
                "query": "direct baseline task",
                "source": "AMiner",
            },
        ],
        local_title="Different Uploaded Paper",
        review_as_of="2026-10-29",
    )
    assert [record["title"] for record in records] == [
        "Eligible Exact-date Candidate"
    ]
    assert diagnostics["future_records_removed"] == 1
