"""Two-tier baseline evaluation-view behavior introduced in v0.4.2."""

from __future__ import annotations

from pathlib import Path
import json
import threading

import pytest

from baseline_finder.anchors import anchor_catalog_text, experiment_anchor_catalog
from baseline_finder.audit import normalize_baseline_audit, select_baseline_candidates
from baseline_finder.config import ModelRuntime
from baseline_finder.parsing import parse_grobid_fulltext
from baseline_finder.pipeline import AuditRequest, run_baseline_pipeline
from baseline_finder.planning import (
    _comparison_purpose_utility_details,
    _comparison_purposes,
    _extended_diversity_reorder,
    build_baseline_retrieval_plan,
    select_direct_baseline_records,
)
from baseline_finder.retrieval import (
    baseline_feedback_keywords,
    filter_retrieval_records,
    retrieve_baseline_candidates,
    semantic_baseline_pool,
)


def _candidate(
    title: str,
    role: str,
    *,
    summary: str,
    published: str = "2025-01-01",
    relevance_score: str = "6",
    **extra,
):
    return {
        "title": title,
        "authors": "Test Author",
        "published": published,
        "source": "AMiner Open Platform",
        "url": "https://example.invalid/paper",
        "summary": summary,
        "query": "sequential recommendation memory denoising MIND",
        "retrieval_role": role,
        "relevance_score": relevance_score,
        "has_distinctive_title_overlap": "true",
        # Most unit fixtures exercise selector/tier policy rather than evidence
        # acquisition, so they explicitly stand in for structured full-text-
        # verified candidates. Evidence-level tests override this flag.
        "candidate_fulltext_verified": True,
        "candidate_fulltext_source": "structured_test_fixture",
        "candidate_fulltext_evidence": {
            "method_and_experiment": "Verified fixture evidence."
        },
        **extra,
    }


def _plan():
    return {
        "task": "sequential recommendation",
        "datasets_or_benchmarks": ["MIND"],
        "evaluation_setting": "MIND ranking protocol",
        "method_family": "memory denoising",
        "current_baselines": ["GLORY"],
        "cited_not_compared": [],
    }


def test_comparison_purpose_normalizer_splits_pipe_delimited_list_items():
    assert _comparison_purposes(
        ["mechanism_isolation|cross_task_adaptation", "novelty_boundary"]
    ) == [
        "mechanism_isolation",
        "novelty_boundary",
        "cross_task_adaptation",
    ]


def test_purpose_conditioned_utility_does_not_apply_direct_protocol_bias_to_cross_task():
    common = {
        "same_task": "low",
        "same_protocol": "low",
        "mechanism_match": "high",
        "intervention_interface_match": "high",
        "fair_baseline_usefulness": "medium",
        "claim_diagnostic_value": "high",
        "marginal_novelty": "medium",
        "comparison_purpose_evidence": {
            "cross_task_adaptation": "Supplied mechanism evidence.",
            "direct_performance": "Supplied direct-comparison evidence.",
        },
        "objective_mechanism_evidence_supported": True,
        "objective_protocol_evidence_supported": False,
    }
    cross_task = _comparison_purpose_utility_details(
        {
            **common,
            "grounded_comparison_purposes": ["cross_task_adaptation"],
        }
    )
    direct = _comparison_purpose_utility_details(
        {
            **common,
            "grounded_comparison_purposes": ["direct_performance"],
        }
    )

    assert cross_task["strongest_purpose"] == "cross_task_adaptation"
    assert cross_task["total"] == 30.0
    assert direct["total"] == 5.28
    assert direct["field_contributions"]["direct_performance"][
        "same_protocol"
    ] == 0.0


def test_purpose_conditioned_utility_uses_strongest_grounded_purpose_with_bounded_bonus():
    details = _comparison_purpose_utility_details(
        {
            "grounded_comparison_purposes": [
                "direct_performance",
                "mechanism_isolation",
                "novelty_boundary",
                "cross_task_adaptation",
                "efficiency_tradeoff",
            ],
            "same_task": "low",
            "same_protocol": "low",
            "mechanism_match": "high",
            "intervention_interface_match": "high",
            "fair_baseline_usefulness": "medium",
            "claim_diagnostic_value": "high",
            "marginal_novelty": "medium",
            "comparison_purpose_evidence": {
                purpose: f"Supplied evidence for {purpose}."
                for purpose in (
                    "direct_performance",
                    "mechanism_isolation",
                    "novelty_boundary",
                    "cross_task_adaptation",
                    "efficiency_tradeoff",
                )
            },
            "objective_mechanism_evidence_supported": True,
            "objective_protocol_evidence_supported": False,
        }
    )

    assert details["strongest_purpose"] in {
        "mechanism_isolation",
        "cross_task_adaptation",
    }
    assert details["strongest_purpose_score"] == 30.0
    assert details["multi_purpose_bonus"] == 1.5
    assert details["total"] == 31.5


def test_direct_purpose_rewards_protocol_only_when_objectively_supported():
    judgment = {
        "grounded_comparison_purposes": ["direct_performance"],
        "same_task": "high",
        "same_protocol": "high",
        "fair_baseline_usefulness": "high",
        "intervention_interface_match": "high",
        "comparison_purpose_evidence": {
            "direct_performance": "Supplied task and protocol evidence."
        },
        "objective_task_evidence_supported": True,
    }
    unsupported = _comparison_purpose_utility_details(
        {**judgment, "objective_protocol_evidence_supported": False}
    )
    supported = _comparison_purpose_utility_details(
        {**judgment, "objective_protocol_evidence_supported": True}
    )

    assert unsupported["total"] == 18.6
    assert supported["total"] == 30.0


def test_non_direct_purposes_use_their_own_dominant_evidence_fields():
    cases = {
        "mechanism_isolation": ("mechanism_match", 12.0),
        "budget_matched_policy": ("intervention_interface_match", 12.0),
        "cross_task_adaptation": ("mechanism_match", 12.0),
        "novelty_boundary": ("marginal_novelty", 18.0),
        "robustness_stress_test": ("claim_diagnostic_value", 18.0),
        "efficiency_tradeoff": ("fair_baseline_usefulness", 15.0),
    }
    for purpose, (dominant_field, expected) in cases.items():
        judgment = {
            "grounded_comparison_purposes": [purpose],
            "comparison_purpose_evidence": {
                purpose: f"Supplied evidence for {purpose}."
            },
            "same_task": "low",
            "same_protocol": "low",
            "mechanism_match": "low",
            "intervention_interface_match": "low",
            "fair_baseline_usefulness": "low",
            "claim_diagnostic_value": "low",
            "marginal_novelty": "low",
            "objective_mechanism_evidence_supported": True,
            dominant_field: "high",
        }
        details = _comparison_purpose_utility_details(judgment)
        assert details["strongest_purpose"] == purpose
        assert details["total"] == expected


def test_real_shape_tei_reference_context_experiment_chain_is_structured():
    fixture = Path(__file__).parent / "fixtures" / "baseline_bibliography.tei.xml"
    parsed = parse_grobid_fulltext(fixture.read_text(), physical_pages=["", "", ""])

    entries = parsed.bibliography_entries or []
    contexts = parsed.citation_contexts or []
    assert [entry["tei_id"] for entry in entries] == ["b0", "b1", "b2", "b3", "b4"]
    assert entries[0]["title"] == "Rec-R1: Reinforcement Learning for Recommendation"
    assert entries[0]["authors"] == ["Ada Author"]
    assert entries[0]["year"] == 2025
    assert entries[0]["entry"].startswith("Ada Author. 2025.")
    assert contexts[0]["target"] == "#b0"
    assert contexts[0]["label"] == "[1]"
    assert "Rec-R1" in contexts[0]["context"]

    experiment_catalog = experiment_anchor_catalog(
        parsed.pages, parsed.source_locations
    )
    experiment_evidence = anchor_catalog_text(experiment_catalog)
    assert "CurrentNet" in experiment_evidence
    assert "Rec-R1" not in experiment_evidence
    assert "ELASTIC" not in experiment_evidence
    assert {
        entry["section"] for entry in experiment_catalog.values()
    } == {"Experiments"}

    expected_methods = ["Rec-R1", "ELASTIC", "RaSeRec", "SSDRec", "PDRec"]
    plan = build_baseline_retrieval_plan(
        parsed.markdown,
        experiment_evidence=experiment_evidence,
        bibliography_evidence="",
        bibliography_entries=entries,
        citation_contexts=contexts,
        review_as_of="2026-10-29",
        llm_json=lambda *_args, **_kwargs: {
            "task": "long-history recommendation",
            "datasets_or_benchmarks": ["MIND"],
            "evaluation_setting": "NDCG@10 ranking",
            "method_family": "memory compression and denoising",
            "current_baselines": ["CurrentNet", "StrongBase"],
            "cited_not_compared": [
                {
                    "title": entry["title"],
                    "method_name": method,
                    "reason": "Cited as a method but absent from the experiment table.",
                }
                for method, entry in zip(expected_methods, entries)
            ],
            "queries": ["q1", "q2", "q3", "q4"],
        },
    )

    assert [item["method_name"] for item in plan["cited_not_compared"]] == expected_methods
    assert [item["bibliography_tei_id"] for item in plan["cited_not_compared"]] == [
        "b0", "b1", "b2", "b3", "b4"
    ]
    assert all(item["citation_ref_target"] for item in plan["cited_not_compared"])
    assert all(item["citation_ref_label"] for item in plan["cited_not_compared"])
    assert all(
        item["local_citation_before_review_cutoff"]
        for item in plan["cited_not_compared"]
    )
    assert all(
        item["experiment_comparison_status"] == "not_observed"
        for item in plan["cited_not_compared"]
    )


def test_real_shape_tei_evidence_flows_through_pipeline(tmp_path: Path):
    fixture = Path(__file__).parent / "fixtures" / "baseline_bibliography.tei.xml"
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\nfixture")
    output = tmp_path / "report.json"
    request = AuditRequest.from_values(
        pdf=str(pdf),
        review_as_of="2026-10-29",
        model_profile="glm",
        work_root=tmp_path / "work",
        grobid_url="http://127.0.0.1:8070",
        output=str(output),
        force=False,
        auto_resolve_pub_id=False,
    )
    captured_plan = {}
    exact_title_calls: list[str] = []

    def parse_source(_pdf, _run_dir, **_kwargs):
        parsed = parse_grobid_fulltext(
            fixture.read_text(), physical_pages=["", "", ""]
        )
        return {
            "markdown": parsed.markdown,
            "pages": parsed.pages,
            "local_title": "Structured Baseline Finder Fixture",
            "local_authors": [],
            "local_publication_year": 2026,
            "source_locations": parsed.source_locations,
            "bibliography_entries": parsed.bibliography_entries,
            "citation_contexts": parsed.citation_contexts,
            "provider": parsed.provider,
            "grobid_tei_file": "fixture.tei.xml",
            "fallback_used": False,
            "diagnostics": [],
        }

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def retrieve(queries, **kwargs):
        captured_plan.update(kwargs["retrieval_plan"])
        cited = kwargs["retrieval_plan"]["cited_not_compared"]
        assert [item["method_name"] for item in cited] == [
            "Rec-R1", "ELASTIC", "RaSeRec", "SSDRec", "PDRec"
        ]

        def search(query, **search_kwargs):
            if search_kwargs.get("query_shape") == "exact_title":
                exact_title_calls.append(query)
                return [
                    _candidate(
                        query,
                        "named_method_or_family",
                        summary="A directly comparable recommendation method on MIND.",
                        published="2025",
                    )
                ], {"api_calls": {"paper_search": 1}, "provider_errors": []}
            return [], {"api_calls": {"paper_search": 1}, "provider_errors": []}

        def select_direct(records, **_kwargs):
            selected = []
            for record in records:
                if record.get("retrieval_role") != "cited_not_compared_reference":
                    continue
                entry = dict(record)
                entry.update(
                    {
                        "comparison_role": "direct_baseline",
                        "selection_reason": "Exact cited title with body context.",
                        "tier": "core",
                        "confidence": "high",
                        "missing_status": "cited_not_compared",
                    }
                )
                selected.append(entry)
            return selected[:10], {
                "selection_status": "completed",
                "selected_record_count": min(10, len(selected)),
                "core_candidate_count": min(10, len(selected)),
                "extended_candidate_count": 0,
            }

        return retrieve_baseline_candidates(
            queries,
            local_title=kwargs["local_title"],
            review_as_of=kwargs["review_as_of"],
            proxy=None,
            select_direct=select_direct,
            retrieval_plan=kwargs["retrieval_plan"],
            client_factory=FakeClient,
            aminer_search_fn=search,
            keyword_search_fn=lambda *_args, **_kwargs: ([], {}),
            aminer_detail_limit=0,
        )

    class FakeModel:
        def json(self, system, _user, *, max_tokens):
            assert max_tokens > 0
            if "retrieval plans" in system:
                parsed = parse_grobid_fulltext(
                    fixture.read_text(), physical_pages=["", "", ""]
                )
                methods = ["Rec-R1", "ELASTIC", "RaSeRec", "SSDRec", "PDRec"]
                return {
                    "task": "long-history recommendation",
                    "datasets_or_benchmarks": ["MIND"],
                    "evaluation_setting": "NDCG@10 ranking",
                    "method_family": "memory compression and denoising",
                    "current_baselines": ["CurrentNet", "StrongBase"],
                    "cited_not_compared": [
                        {"title": entry["title"], "method_name": method}
                        for method, entry in zip(
                            methods, parsed.bibliography_entries or []
                        )
                    ],
                    "queries": [],
                }
            return {
                "records": [
                    {
                        "candidate_id": "B1",
                        "status": "not_assessable",
                        "anchor_id": "",
                        "reason": "Not present in the experiment table.",
                    }
                ]
            }

    runtime = ModelRuntime(
        profile="glm",
        label="test",
        model="glm-5.3",
        api_key="not-used",
        base_url="https://not-used.invalid",
    )
    manifest = run_baseline_pipeline(
        request,
        runtime=runtime,
        model_client=FakeModel(),
        parse_source=parse_source,
        retrieve_candidates=retrieve,
    )

    report = json.loads(output.read_text())
    run_dir = Path(manifest["report"]).parent
    assert (run_dir / "bibliography_evidence.json").is_file()
    assert report["run_metadata"]["bibliography_entry_count"] == 5
    assert report["run_metadata"]["inline_citation_context_count"] == 5
    assert captured_plan["current_baselines"] == ["CurrentNet", "StrongBase"]
    assert captured_plan["query_generation"] == {
        "llm_query_count": 0,
        "deterministic_fallback_count": 4,
        "expected_query_count": 4,
    }
    assert exact_title_calls == [
        item["title"] for item in captured_plan["cited_not_compared"]
    ]
    assert "b0" in {
        record.get("bibliography_tei_id")
        for record in report["results"]["baseline_audit"]["records"]
    }


def test_bibliography_to_context_to_experiment_chain_extracts_named_methods():
    titles = {
        "Rec-R1": "Rec-R1: Reinforcement Learning for Recommendation",
        "ELASTIC": "ELASTIC: Efficient Long-history Compression for Recommendation",
        "RaSeRec": "RaSeRec: Retrieval-augmented Sequential Recommendation",
        "SSDRec": "SSDRec: Self-supervised Denoising for Sequential Recommendation",
    }
    body = (
        "We discuss Rec-R1 [1], ELASTIC [2], RaSeRec [3], and SSDRec [4] "
        "as directly related recommendation methods.\n\n"
        "## Experiments\nTable 1 compares GLORY and Mamba4Rec on MIND.\n\n"
    )
    references = "\n".join(
        f"[{index}] A. Author. {title}. 2025."
        for index, title in enumerate(titles.values(), start=1)
    )
    markdown = f"{body}## References\n{references}"

    plan = build_baseline_retrieval_plan(
        markdown,
        experiment_evidence="Table 1 compares GLORY and Mamba4Rec on MIND.",
        bibliography_evidence=f"## References\n{references}",
        review_as_of="2026-10-29",
        llm_json=lambda *_args, **_kwargs: {
            "task": "sequential recommendation",
            "datasets_or_benchmarks": ["MIND"],
            "evaluation_setting": "ranking protocol",
            "method_family": "memory compression and denoising",
            "current_baselines": ["GLORY", "Mamba4Rec", "HallucinatedBaseline"],
            "cited_not_compared": [
                {
                    "title": title,
                    "method_name": method,
                    "citation_context": f"We discuss {method} as related work.",
                    "reason": "Cited but absent from Table 1.",
                }
                for method, title in titles.items()
            ],
            "queries": ["q1", "q2", "q3", "q4"],
        },
    )

    assert plan["current_baselines"] == ["GLORY", "Mamba4Rec"]
    assert [item["method_name"] for item in plan["cited_not_compared"]] == list(
        titles
    )
    assert all(
        item["experiment_comparison_status"] == "not_observed"
        for item in plan["cited_not_compared"]
    )
    assert all(item["citation_context"] for item in plan["cited_not_compared"])
    assert all(
        item["evidence_chain"].startswith("exact_bibliography_title")
        for item in plan["cited_not_compared"]
    )


def test_each_cited_not_compared_method_gets_its_own_exact_title_verification():
    titles = [
        f"StateRec {index}: State-space Sequential Recommendation"
        for index in range(1, 13)
    ] + ["ProfileRec: Sparse Profile Sequential Recommendation"]
    calls: list[tuple[str, str]] = []
    selector_titles: list[str] = []

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def search(query, **kwargs):
        shape = str(kwargs.get("query_shape"))
        calls.append((query, shape))
        title = query if shape == "exact_title" else "External Direct Baseline"
        return [
            _candidate(
                title,
                "named_method_or_family",
                summary="A sequential recommendation method evaluated on MIND.",
            )
        ], {"api_calls": {"paper_search": 1}, "provider_errors": []}

    def select_direct(records, **_kwargs):
        selector_titles.extend(str(record.get("title") or "") for record in records)
        selected = []
        for record in records:
            entry = dict(record)
            entry["comparison_role"] = "direct_baseline"
            selected.append(entry)
        return selected[:10], {
            "selection_status": "completed",
            "selected_record_count": min(len(selected), 10),
        }

    retrieve_baseline_candidates(
        ["sequential recommendation MIND"],
        local_title="Uploaded Memory Recommender",
        review_as_of="2026-10-29",
        proxy=None,
        select_direct=select_direct,
        retrieval_plan={
            **_plan(),
            "cited_not_compared": [
                {
                    "title": title,
                    "method_name": title.split(":", 1)[0],
                    "mechanism_branch": (
                        "sparse profile"
                        if title.startswith("ProfileRec")
                        else "state space"
                    ),
                    "task_protocol_relevance": "high",
                    "citation_context": "Visible body citation.",
                    "reason": "Not present in the experiment table.",
                }
                for title in titles
            ],
            "query_specs": [],
        },
        client_factory=FakeClient,
        aminer_search_fn=search,
        keyword_search_fn=lambda *_args, **_kwargs: ([], {}),
        aminer_detail_limit=0,
    )

    assert [query for query, shape in calls if shape == "exact_title"] == titles
    assert set(titles).issubset(selector_titles)
    assert all(selector_titles.count(title) == 1 for title in titles)


def test_planner_preserves_a_late_distinct_branch_beyond_twelve_references():
    titles = [
        f"StateRec {index}: State-space Sequential Recommendation"
        for index in range(1, 13)
    ] + ["ProfileRec: Sparse Profile Sequential Recommendation"]
    methods = [f"StateRec{index}" for index in range(1, 13)] + ["ProfileRec"]
    body = "\n".join(
        f"We discuss {method} [{index}]."
        for index, method in enumerate(methods, start=1)
    )
    references = "\n".join(
        f"[{index}] A. Author. {title}. 2025."
        for index, title in enumerate(titles, start=1)
    )
    markdown = f"{body}\n\n## Experiments\nWe compare GLORY on MIND.\n\n## References\n{references}"

    plan = build_baseline_retrieval_plan(
        markdown,
        experiment_evidence="We compare GLORY on MIND.",
        bibliography_evidence=f"## References\n{references}",
        review_as_of="2026-10-29",
        llm_json=lambda *_args, **_kwargs: {
            "task": "sequential recommendation",
            "datasets_or_benchmarks": ["MIND"],
            "evaluation_setting": "ranking protocol",
            "method_family": "state-space and sparse-profile modeling",
            "current_baselines": ["GLORY"],
            "cited_not_compared": [
                {
                    "title": title,
                    "method_name": method,
                    "mechanism_branch": (
                        "sparse profile" if index == 13 else "state space"
                    ),
                    "task_protocol_relevance": "high",
                    "reason": "Same task and absent from the experiment table.",
                }
                for index, (title, method) in enumerate(
                    zip(titles, methods), start=1
                )
            ],
            "queries": ["q1", "q2", "q3", "q4"],
        },
    )

    assert len(plan["cited_not_compared"]) == 13
    assert plan["cited_not_compared"][-1]["title"] == titles[-1]
    assert plan["cited_not_compared"][-1]["mechanism_branch"] == "sparse profile"


def test_structured_bibliography_recovers_targetless_acronym_author_year_citation():
    title = "SSDRec: Self-Augmented Sequence Denoising for Recommendation"
    context = (
        "SSDRec (Smith et al., 2024) removes noisy interactions before "
        "sequential recommendation [7]."
    )
    plan = build_baseline_retrieval_plan(
        (
            "## Related Work\n"
            f"{context}\n\n"
            "## Experiments\nTable 1 compares CurrentNet on MIND."
        ),
        experiment_evidence="Table 1 compares CurrentNet on MIND.",
        bibliography_evidence="",
        bibliography_entries=[
            {
                "tei_id": "b6",
                "ordinal": 7,
                "title": title,
                "authors": ["Ada Smith"],
                "year": 2024,
                "entry": f"Ada Smith. 2024. {title}.",
                "citation_contexts": [],
            }
        ],
        citation_contexts=[
            {
                "target": "",
                "target_ids": [],
                "label": "[7]",
                "context": context,
                "section": "Related Work",
            }
        ],
        review_as_of="2026-10-29",
        llm_json=lambda *_args, **_kwargs: {
            "task": "sequential recommendation",
            "datasets_or_benchmarks": ["MIND"],
            "evaluation_setting": "ranking protocol",
            "method_family": "history denoising",
            "current_baselines": ["CurrentNet"],
            # Regression: structured candidates must not depend on the model
            # remembering to copy this title into its planning response.
            "cited_not_compared": [],
            "queries": ["q1", "q2", "q3", "q4"],
        },
    )

    assert [item["title"] for item in plan["cited_not_compared"]] == [title]
    recovered = plan["cited_not_compared"][0]
    assert recovered["method_name"] == "SSDRec"
    assert recovered["citation_context"] == context
    assert recovered["citation_link_method"] == (
        "targetless_method_name_plus_author_year_and_label"
    )
    assert recovered["experiment_comparison_status"] == "not_observed"


def test_real_p2_shape_recovers_plain_text_citations_without_ref_nodes():
    """P2 keeps three method citations as plain ``s`` text, not TEI refs."""
    tei = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader><fileDesc><titleStmt><title>P2 shape</title></titleStmt>
    <publicationStmt><p>fixture</p></publicationStmt>
    <sourceDesc><p>fixture</p></sourceDesc></fileDesc></teiHeader>
  <text>
    <body>
      <div><head>Related Work</head>
        <p><s>PDRec <ref type="bibr" target="#b0">[1]</ref> models personalized diffusion.</s></p>
        <p><s>ELASTIC (Chen et al., 2023) compresses long recommendation histories.</s></p>
        <p><s>RaSeRec (Wang et al., 2024) augments sequential recommendation with retrieval.</s></p>
        <p><s>SSDRec (Fan et al., 2022) denoises noisy interaction sequences.</s></p>
      </div>
      <div><head>Experiments</head><p><s>Table 1 compares CurrentNet on MIND.</s></p></div>
    </body>
    <back><div type="references"><listBibl>
      <biblStruct xml:id="b0"><analytic>
        <title level="a" type="main">Plug-In Diffusion Model for Sequential Recommendation</title>
        <author><persName><forename>Ada</forename><surname>Lee</surname></persName></author>
      </analytic><monogr><imprint><date type="published" when="2024">2024</date></imprint></monogr>
        <note type="raw_reference">Ada Lee. 2024. Plug-In Diffusion Model for Sequential Recommendation.</note>
      </biblStruct>
      <biblStruct xml:id="b1"><analytic>
        <title level="a" type="main">ELASTIC: Efficient Long-History Compression for Recommendation</title>
        <author><persName><forename>Bo</forename><surname>Chen</surname></persName></author>
      </analytic><monogr><imprint><date type="published" when="2023">2023</date></imprint></monogr>
        <note type="raw_reference">Bo Chen. 2023. ELASTIC: Efficient Long-History Compression for Recommendation. Withdrawn from arXiv due to incomplete experiments.</note>
      </biblStruct>
      <biblStruct xml:id="b2"><analytic>
        <title level="a" type="main">RaSeRec: Retrieval-Augmented Sequential Recommendation</title>
        <author><persName><forename>Cy</forename><surname>Wang</surname></persName></author>
      </analytic><monogr><imprint><date type="published" when="2024">2024</date></imprint></monogr>
        <note type="raw_reference">Cy Wang. 2024. RaSeRec: Retrieval-Augmented Sequential Recommendation.</note>
      </biblStruct>
      <biblStruct xml:id="b3"><analytic>
        <title level="a" type="main">SSDRec: Self-Supervised Denoising for Sequential Recommendation</title>
        <author><persName><forename>Dee</forename><surname>Fan</surname></persName></author>
      </analytic><monogr><imprint><date type="published" when="2022">2022</date></imprint></monogr>
        <note type="raw_reference">Dee Fan. 2022. SSDRec: Self-Supervised Denoising for Sequential Recommendation.</note>
      </biblStruct>
      <biblStruct xml:id="b4"><analytic>
        <title level="a" type="main">Uncited Background Model</title>
        <author><persName><forename>Eve</forename><surname>Smith</surname></persName></author>
      </analytic><monogr><imprint><date type="published" when="2021">2021</date></imprint></monogr>
        <note type="raw_reference">Eve Smith. 2021. Uncited Background Model.</note>
      </biblStruct>
    </listBibl></div></back>
  </text>
</TEI>
"""
    parsed = parse_grobid_fulltext(tei, physical_pages=["", "", ""])
    assert len(parsed.citation_contexts or []) == 1

    plan = build_baseline_retrieval_plan(
        parsed.markdown,
        experiment_evidence="Table 1 compares CurrentNet on MIND.",
        bibliography_evidence="",
        bibliography_entries=parsed.bibliography_entries,
        citation_contexts=parsed.citation_contexts,
        review_as_of="2026-10-29",
        llm_json=lambda *_args, **_kwargs: {
            "task": "sequential recommendation",
            "datasets_or_benchmarks": ["MIND"],
            "evaluation_setting": "ranking protocol",
            "method_family": "compression, retrieval, diffusion, and denoising",
            "current_baselines": ["CurrentNet"],
            # The deterministic inventory must not depend on model title recall.
            "cited_not_compared": [],
            "queries": ["q1", "q2", "q3", "q4"],
        },
    )

    assert [item["method_name"] for item in plan["cited_not_compared"]] == [
        "PDRec",
        "ELASTIC",
        "RaSeRec",
        "SSDRec",
    ]
    assert [item["citation_link_method"] for item in plan["cited_not_compared"]] == [
        "tei_target",
        "body_method_name_plus_author_year_without_tei_ref",
        "body_method_name_plus_author_year_without_tei_ref",
        "body_method_name_plus_author_year_without_tei_ref",
    ]
    inventory = plan["bibliography_inventory"]
    assert inventory["deterministically_linked_structured_entry_count"] == 4
    assert inventory["unlinked_structured_entry_count"] == 1
    assert inventory["model_omission_cannot_remove_structured_candidate"] is False


def test_two_tier_view_keeps_core_and_only_hard_gated_extended_candidates():
    candidates = [
        _candidate(
            "Denoising Sequential Recommendation on MIND",
            "cited_not_compared_reference",
            summary="A memory denoising method evaluated for sequential recommendation on MIND.",
            bibliography_title="Denoising Sequential Recommendation on MIND",
            bibliography_title_similarity=1.0,
            bibliography_reason="Same sequential recommendation task and MIND protocol.",
            citation_context="Discussed as a denoising recommender.",
        ),
        _candidate(
            "GLORY: Graph-enhanced News Recommendation",
            "named_method_or_family",
            summary="A current MIND sequential recommendation baseline.",
        ),
        _candidate(
            "A Survey of Sequential Recommendation",
            "named_method_or_family",
            summary="A survey of recommendation methods.",
        ),
        _candidate(
            "Future Memory Recommender",
            "named_method_or_family",
            summary="Sequential recommendation on MIND with memory denoising.",
            published="2027-01-01",
        ),
        _candidate(
            "Uploaded Memory Recommender",
            "named_method_or_family",
            summary="Sequential recommendation on MIND with memory denoising.",
        ),
        _candidate(
            "Memory-aware Sequential Ranking",
            "task_and_evaluation_setting",
            summary="Memory denoising for sequential recommendation under the MIND ranking protocol.",
        ),
        _candidate(
            "Unrelated Vision Segmentation",
            "task_and_evaluation_setting",
            summary="Image segmentation on a medical vision dataset.",
            relevance_score="0",
        ),
        _candidate(
            "Protocol-aligned Denoising Recommender",
            "current_comparison_set",
            summary="A denoising sequential recommendation method evaluated with MIND ranking.",
        ),
    ]

    selected, diagnostics = select_direct_baseline_records(
        candidates,
        local_title="Uploaded Memory Recommender",
        queries=["q1", "q2", "q3", "q4"],
        review_as_of="2026-10-29",
        retrieval_plan=_plan(),
        llm_json=lambda *_args, **_kwargs: {
            "assessments": [
                {
                    "candidate_id": "R1",
                    "decision": "core",
                    "reason": "Same task, dataset, and evaluation protocol.",
                    "confidence": "high",
                    "comparison_purposes": ["direct_performance"],
                    "comparison_purpose_evidence": {
                        "direct_performance": "Same task and supplied MIND protocol."
                    },
                    "same_task": "high",
                    "same_protocol": "high",
                    "mechanism_match": "high",
                    "intervention_interface_match": "high",
                    "fair_baseline_usefulness": "high",
                    "claim_diagnostic_value": "high",
                    "marginal_novelty": "high",
                    "task_protocol_relevance": "high",
                    "mechanism_branch": "denoising",
                    "runnability": "runnable",
                },
                *[
                    {
                        "candidate_id": candidate_id,
                        "decision": "reject",
                        "reason": "Objectively excluded or clearly different task.",
                        "confidence": "low",
                        "same_task": "low",
                        "same_protocol": "unknown",
                        "mechanism_match": "low",
                        "intervention_interface_match": "low",
                        "fair_baseline_usefulness": "low",
                        "claim_diagnostic_value": "low",
                        "marginal_novelty": "low",
                        "mechanism_branch": "excluded",
                        "task_protocol_relevance": "low",
                        "runnability": "uncertain",
                    }
                    for candidate_id in ("R2", "R3", "R4", "R5", "R7")
                ],
                *[
                    {
                        "candidate_id": candidate_id,
                        "decision": "extended",
                        "reason": "Same task and protocol; manual verification remains.",
                        "confidence": "medium",
                        "comparison_purposes": ["direct_performance"],
                        "comparison_purpose_evidence": {
                            "direct_performance": "Same task and supplied MIND protocol."
                        },
                        "same_task": "high",
                        "same_protocol": "high",
                        "mechanism_match": "high",
                        "intervention_interface_match": "medium",
                        "fair_baseline_usefulness": "medium",
                        "claim_diagnostic_value": "medium",
                        "marginal_novelty": "medium",
                        "mechanism_branch": "denoising",
                        "task_protocol_relevance": "medium",
                        "runnability": "uncertain",
                    }
                    for candidate_id in ("R6", "R8")
                ],
            ]
        },
    )

    assert [item["tier"] for item in selected] == ["core", "extended", "extended"]
    assert [item["confidence"] for item in selected] == ["high", "medium", "medium"]
    assert selected[0]["missing_status"] == "cited_not_compared"
    assert all(item["candidate_label"] == "candidate_to_check" for item in selected)
    assert all("selection_evidence" in item for item in selected)
    assert all("verification" in item for item in selected)
    assert not {
        "GLORY: Graph-enhanced News Recommendation",
        "A Survey of Sequential Recommendation",
        "Future Memory Recommender",
        "Uploaded Memory Recommender",
        "Unrelated Vision Segmentation",
    }.intersection(item["title"] for item in selected)
    assert diagnostics["evaluation_view_cap"] == 10
    assert diagnostics["evaluation_view_status"] == "insufficient_candidates"
    assert diagnostics["insufficient_candidates"] is True
    assert diagnostics["core_candidate_count"] == 1
    assert diagnostics["extended_candidate_count"] == 2
    assert diagnostics["low_confidence_internal_audit_count"] == 5


def test_top_ten_is_a_cap_and_never_forces_low_confidence_padding():
    candidates = [
        _candidate(
            "Unrelated Vision Segmentation",
            "named_method_or_family",
            summary="Image segmentation on a medical vision dataset.",
            relevance_score="0",
        )
    ]
    selected, diagnostics = select_direct_baseline_records(
        candidates,
        local_title="Uploaded Memory Recommender",
        queries=["q1"],
        review_as_of="2026-10-29",
        retrieval_plan=_plan(),
        llm_json=lambda *_args, **_kwargs: {
            "assessments": [
                {
                    "candidate_id": "R1",
                    "decision": "extended",
                    "reason": "Generic recommendation overlap only.",
                    "confidence": "medium",
                    "same_task": "medium",
                    "same_protocol": "unknown",
                    "mechanism_match": "low",
                    "intervention_interface_match": "low",
                    "fair_baseline_usefulness": "low",
                    "claim_diagnostic_value": "low",
                    "marginal_novelty": "low",
                    "mechanism_branch": "generic recommendation",
                    "task_protocol_relevance": "medium",
                    "runnability": "uncertain",
                }
            ]
        },
    )

    assert selected == []
    assert diagnostics["selection_status"] == "no_eligible_candidates"
    assert diagnostics["evaluation_view_status"] == "insufficient_candidates"
    assert diagnostics["low_confidence_internal_audit_count"] == 1


def test_selector_is_prompted_for_relevance_first_mechanism_diversity():
    candidates = [
        _candidate(
            "Generic Sequential Model A",
            "cited_not_compared_reference",
            summary="A directly comparable sequential recommendation model on MIND.",
            bibliography_reason="Same-task model cited but not compared.",
            method_name="GenericA",
            experiment_comparison_status="not_observed",
        ),
        _candidate(
            "Diffusion Denoising Recommender A",
            "cited_not_compared_reference",
            summary="A directly comparable diffusion denoising recommender on MIND.",
            bibliography_reason="Diffusion method cited but not compared.",
            method_name="DiffA",
            experiment_comparison_status="not_observed",
        ),
        _candidate(
            "Diffusion Denoising Recommender B",
            "cited_not_compared_reference",
            summary="Another directly comparable diffusion denoising recommender on MIND.",
            bibliography_reason="Diffusion method cited but not compared.",
            method_name="DiffB",
            experiment_comparison_status="not_observed",
        ),
        _candidate(
            "Generic Sequential Model B",
            "cited_not_compared_reference",
            summary="A directly comparable sequential recommendation model on MIND.",
            bibliography_reason="Same-task model cited but not compared.",
            method_name="GenericB",
            experiment_comparison_status="not_observed",
        ),
        _candidate(
            "Generic Sequential Model C",
            "cited_not_compared_reference",
            summary="A directly comparable sequential recommendation model on MIND.",
            bibliography_reason="Same-task model cited but not compared.",
            method_name="GenericC",
            experiment_comparison_status="not_observed",
        ),
        _candidate(
            "Latent History Compression Recommender",
            "cited_not_compared_reference",
            summary="A directly comparable latent history compression method on MIND.",
            bibliography_reason="Compression method cited but not compared.",
            method_name="CompressRec",
            experiment_comparison_status="not_observed",
        ),
        _candidate(
            "Sparse Memory Recommender",
            "cited_not_compared_reference",
            summary="A directly comparable sparse memory method on MIND.",
            bibliography_reason="Memory method cited but not compared.",
            method_name="MemoryRec",
            experiment_comparison_status="not_observed",
        ),
    ]
    captured_prompt = ""

    def select(_system, prompt, **_kwargs):
        nonlocal captured_prompt
        captured_prompt = prompt
        # Simulate a relevance-first selector that keeps the unique compression
        # branch instead of a third same-family diffusion candidate.
        return {
            "selected": [
                {
                    "candidate_id": candidate_id,
                    "reason": "Direct and comparable.",
                    "confidence": "high",
                    "task_protocol_relevance": "high",
                    "mechanism_branch": branch,
                    "runnability": "runnable",
                }
                for candidate_id, branch in (
                    ("R1", "sequential modeling"),
                    ("R2", "diffusion denoising"),
                    ("R4", "sequential modeling"),
                    ("R5", "sequential modeling"),
                    ("R6", "latent compression"),
                    ("R7", "sparse memory"),
                )
            ]
        }

    plan = {
        **_plan(),
        "method_family": "sparse memory latent compression diffusion denoising",
    }
    selected, diagnostics = select_direct_baseline_records(
        candidates,
        local_title="Uploaded Memory Compression Recommender",
        queries=["q1", "q2", "q3", "q4"],
        review_as_of="2026-10-29",
        retrieval_plan=plan,
        llm_json=select,
    )

    titles = [item["title"] for item in selected]
    assert "Latent History Compression Recommender" in titles
    assert "Sparse Memory Recommender" in titles
    assert "Diffusion Denoising Recommender B" not in titles
    assert "Mechanism branches are descriptive evidence, not quotas" in captured_prompt
    assert '"bibliography_reason": "Compression method cited but not compared."' in captured_prompt
    assert '"method_name": "CompressRec"' in captured_prompt
    assert diagnostics["mechanism_diversity"]["candidate_set_preserved"] is True
    assert set(diagnostics["mechanism_diversity"]["covered_mechanism_terms"]) >= {
        "compression",
        "memory",
    }


def test_top_ten_round_robins_across_model_verified_mechanism_branches():
    candidates = [
        _candidate(
            f"State-space Recommender {index}",
            "cited_not_compared_reference",
            summary="A directly comparable state-space recommender on MIND.",
        )
        for index in range(1, 13)
    ] + [
        _candidate(
            "Sparse Profile Recommender",
            "cited_not_compared_reference",
            summary="A directly comparable sparse-profile recommender on MIND.",
        ),
        _candidate(
            "Diffusion Denoising Recommender",
            "cited_not_compared_reference",
            summary="A directly comparable diffusion recommender on MIND.",
        ),
        _candidate(
            "Retrieval-Augmented Recommender",
            "cited_not_compared_reference",
            summary="A directly comparable retrieval-augmented recommender on MIND.",
        ),
    ]
    branches = ["state space"] * 12 + [
        "sparse profile",
        "diffusion denoising",
        "retrieval augmentation",
    ]

    selected, diagnostics = select_direct_baseline_records(
        candidates,
        local_title="Uploaded Sequential Recommender",
        queries=["q1", "q2", "q3", "q4"],
        review_as_of="2026-10-29",
        retrieval_plan=_plan(),
        llm_json=lambda *_args, **_kwargs: {
            "selected": [
                {
                    "candidate_id": f"R{index}",
                    "reason": "Same task and comparable MIND protocol.",
                    "confidence": "high",
                    "mechanism_branch": branch,
                    "task_protocol_relevance": "high",
                    "runnability": "runnable",
                    "same_task": "high",
                    "same_protocol": "high",
                    "intervention_interface_match": "high",
                    "fair_baseline_usefulness": "high",
                    "claim_diagnostic_value": "high",
                    "marginal_novelty": "high",
                }
                for index, branch in enumerate(branches, start=1)
            ]
        },
    )

    assert len(selected) == 10
    assert {item["mechanism_branch"] for item in selected} >= {
        "state space",
        "sparse profile",
        "diffusion denoising",
        "retrieval augmentation",
    }
    assert diagnostics["model_selected_count"] == 15
    assert diagnostics["model_selected_retained_count"] == 10
    assert diagnostics["mechanism_diversity"]["only_model_selected_candidates"] is True


def test_selector_contract_keeps_full_evidence_and_unsupported_protocol_out_of_core():
    captured_prompt = ""
    long_summary = (
        "A same-task sequential recommendation method with a distinct memory module. "
        + "evidence " * 140
        + "FULL_ABSTRACT_END"
    )
    candidate = _candidate(
        "Protocol-Unverified Memory Candidate",
        "cited_not_compared_reference",
        summary=long_summary,
        bibliography_title="Protocol-Unverified Memory Candidate",
        bibliography_title_similarity=1.0,
        bibliography_entry="A. Author. 2025. Protocol-Unverified Memory Candidate.",
        citation_context="The manuscript cites this same-task memory method.",
        bibliography_reason="Cited but absent from the experimental comparison list.",
        method_name="MemoryCandidate",
    )

    def selector(_system, prompt, **_kwargs):
        nonlocal captured_prompt
        captured_prompt = prompt
        return {
            "selected": [
                {
                    "candidate_id": "R1",
                    "reason": "Same task, but protocol evidence is only asserted.",
                    "confidence": "high",
                    "tier": "core",
                    "same_task": "high",
                    "same_protocol": "high",
                    "mechanism_match": "high",
                    "intervention_interface_match": "high",
                    "fair_baseline_usefulness": "high",
                    "claim_diagnostic_value": "high",
                    "marginal_novelty": "high",
                    "mechanism_branch": "memory augmentation",
                    "task_protocol_relevance": "high",
                    "runnability": "runnable",
                    "protocol_evidence": "No dataset or metric is supplied.",
                }
            ]
        }

    selected, _diagnostics = select_direct_baseline_records(
        [candidate],
        local_title="Uploaded Sequential Recommender",
        queries=["q1", "q2", "q3", "q4"],
        review_as_of="2026-10-29",
        retrieval_plan=_plan(),
        llm_json=selector,
    )

    assert "FULL_ABSTRACT_END" in captured_prompt
    for field in (
        "same_task",
        "same_protocol",
        "intervention_interface_match",
        "fair_baseline_usefulness",
        "claim_diagnostic_value",
        "marginal_novelty",
    ):
        assert field in captured_prompt
    assert selected[0]["tier"] == "extended"
    verification = selected[0]["verification"]
    assert "same_protocol_lacks_supplied_evidence" in verification["core_blockers"]
    assert verification["selector_semantic_judgments"][
        "objective_protocol_evidence_supported"
    ] is False


def test_same_branch_uses_interface_and_marginal_value_without_hard_rejection():
    candidates = [
        _candidate(
            "Generic Diffusion Candidate",
            "cited_not_compared_reference",
            summary="Diffusion sequential recommendation evaluated on MIND ranking.",
        ),
        _candidate(
            "Plug-In Intervention Candidate",
            "cited_not_compared_reference",
            summary="Plug-in diffusion sequential recommendation evaluated on MIND ranking.",
        ),
        _candidate(
            "Redundant Diffusion Candidate",
            "cited_not_compared_reference",
            summary="Another diffusion sequential recommendation evaluated on MIND ranking.",
        ),
    ]
    judgments = [
        ("medium", "medium", "medium"),
        ("high", "high", "high"),
        ("high", "medium", "low"),
    ]
    selected, diagnostics = select_direct_baseline_records(
        candidates,
        local_title="Uploaded Plug-In Recommender",
        queries=["q1", "q2", "q3", "q4"],
        review_as_of="2026-10-29",
        retrieval_plan={**_plan(), "method_family": "plug-in diffusion memory"},
        llm_json=lambda *_args, **_kwargs: {
            "selected": [
                {
                    "candidate_id": f"R{index}",
                    "reason": "Same task and MIND ranking protocol.",
                    "confidence": "high",
                    "tier": "core",
                    "same_task": "high",
                    "same_protocol": "high",
                    "mechanism_match": "high",
                    "intervention_interface_match": interface,
                    "fair_baseline_usefulness": "high",
                    "claim_diagnostic_value": diagnostic,
                    "marginal_novelty": marginal,
                    "mechanism_branch": "diffusion recommendation",
                    "task_protocol_relevance": "high",
                    "runnability": "runnable",
                }
                for index, (interface, diagnostic, marginal) in enumerate(
                    judgments, start=1
                )
            ]
        },
    )

    assert [item["title"] for item in selected] == [
        "Plug-In Intervention Candidate",
        "Redundant Diffusion Candidate",
        "Generic Diffusion Candidate",
    ]
    assert diagnostics["evaluation_view_mechanism_diversity"][
        "branch_diversity_policy"
    ] == "near_equal_semantic_utility_tie_break_only"


def test_complete_selector_contract_batches_every_id_and_marks_omissions(
    monkeypatch,
):
    monkeypatch.delenv("BASELINE_SELECTOR_MAX_WORKERS", raising=False)
    monkeypatch.delenv("BASELINE_SELECTOR_BATCH_STRATEGY", raising=False)
    candidates = [
        _candidate(
            f"Assessed Memory Candidate {index}",
            "cited_not_compared_reference",
            summary="Memory sequential recommendation evaluated on MIND ranking.",
        )
        for index in range(1, 22)
    ]
    calls: list[list[str]] = []
    active_calls = 0
    max_active_calls = 0
    call_lock = threading.Lock()
    first_two_started = threading.Barrier(2)
    second_batch_completed = threading.Event()
    completion_order: list[int] = []

    def assess(_system, prompt, **_kwargs):
        nonlocal active_calls, max_active_calls
        batch = json.loads(
            prompt.split("Candidate records in the current assessment batch:\n", 1)[1]
        )
        ids = [str(item["candidate_id"]) for item in batch]
        with call_lock:
            calls.append(ids)
            active_calls += 1
            max_active_calls = max(max_active_calls, active_calls)
        try:
            first_two_started.wait(timeout=5)
            if ids[0] == "R1":
                assert second_batch_completed.wait(timeout=5)
                with call_lock:
                    completion_order.append(1)
            else:
                with call_lock:
                    completion_order.append(2)
                second_batch_completed.set()
            return {
                "assessments": [
                    {
                        "candidate_id": candidate_id,
                        "decision": "core",
                        "reason": "Same task and MIND ranking protocol.",
                        "confidence": "high",
                        "same_task": "high",
                        "same_protocol": "high",
                        "comparison_purposes": ["direct_performance"],
                        "comparison_purpose_evidence": {
                            "direct_performance": (
                                "Same task and MIND ranking protocol."
                            )
                        },
                        "mechanism_match": "high",
                        "intervention_interface_match": "high",
                        "fair_baseline_usefulness": "high",
                        "claim_diagnostic_value": "high",
                        "marginal_novelty": "high",
                        "mechanism_branch": "memory recommendation",
                        "task_protocol_relevance": "high",
                        "runnability": "runnable",
                    }
                    for candidate_id in ids
                    if candidate_id != "R21"
                ]
            }
        finally:
            with call_lock:
                active_calls -= 1

    selected, diagnostics = select_direct_baseline_records(
        candidates,
        local_title="Uploaded Memory Recommender",
        queries=["q1", "q2", "q3", "q4"],
        review_as_of="2026-10-29",
        retrieval_plan=_plan(),
        llm_json=assess,
    )

    assert sorted(len(batch) for batch in calls) == [10, 11]
    assert max_active_calls == 2
    assert completion_order == [2, 1]
    assert len(selected) == 10
    assert diagnostics["selector_contract"] == "complete_batched_assessments"
    assert diagnostics["selector_batch_strategy"] == "balanced"
    assert diagnostics["selector_batch_sizes"] == [11, 10]
    assert diagnostics["selector_configured_workers"] == 3
    assert diagnostics["selector_effective_workers"] == 2
    assert diagnostics["selector_stage_wall_seconds"] >= 0
    assert diagnostics["selector_batch_wall_seconds_sum"] >= 0
    assert [batch["batch"] for batch in diagnostics["selector_batches"]] == [1, 2]
    assert diagnostics["selector_assessed_candidate_count"] == 20
    assert diagnostics["selector_not_assessed_candidate_ids"] == ["R21"]
    assert any(
        audit.get("candidate_id") == "R21"
        and audit.get("decision") == "selector_not_assessed"
        for audit in diagnostics["low_confidence_internal_audit"]
    )


def test_selector_worker_override_can_force_serial_batches(monkeypatch):
    monkeypatch.setenv("BASELINE_SELECTOR_MAX_WORKERS", "1")
    monkeypatch.setenv("BASELINE_SELECTOR_BATCH_STRATEGY", "balanced")
    candidates = [
        _candidate(
            f"Serial Override Candidate {index}",
            "cited_not_compared_reference",
            summary="Memory sequential recommendation evaluated on MIND ranking.",
        )
        for index in range(1, 22)
    ]
    calls: list[list[str]] = []

    def assess(_system, prompt, **_kwargs):
        batch = json.loads(
            prompt.split("Candidate records in the current assessment batch:\n", 1)[1]
        )
        calls.append([str(item["candidate_id"]) for item in batch])
        return {"selected": []}

    _, diagnostics = select_direct_baseline_records(
        candidates,
        local_title="Uploaded Memory Recommender",
        queries=["q1", "q2", "q3", "q4"],
        review_as_of="2026-10-29",
        retrieval_plan=_plan(),
        llm_json=assess,
    )

    assert [len(batch) for batch in calls] == [11, 10]
    assert diagnostics["selector_batch_strategy"] == "balanced"
    assert diagnostics["selector_batch_sizes"] == [11, 10]
    assert diagnostics["selector_configured_workers"] == 1
    assert diagnostics["selector_effective_workers"] == 1


def test_selector_batch_failure_does_not_cancel_other_batches(monkeypatch):
    monkeypatch.setenv("BASELINE_SELECTOR_BATCH_STRATEGY", "fixed")
    candidates = [
        _candidate(
            f"Failure Isolation Candidate {index}",
            "cited_not_compared_reference",
            summary="Memory sequential recommendation evaluated on MIND ranking.",
        )
        for index in range(1, 42)
    ]
    called_batches: list[tuple[str, ...]] = []
    call_lock = threading.Lock()

    def assess(_system, prompt, **_kwargs):
        batch = json.loads(
            prompt.split("Candidate records in the current assessment batch:\n", 1)[1]
        )
        ids = tuple(str(item["candidate_id"]) for item in batch)
        with call_lock:
            called_batches.append(ids)
        if ids[0] == "R21":
            raise RuntimeError("isolated batch failure")
        return {
            "assessments": [
                {
                    "candidate_id": candidate_id,
                    "decision": "core",
                    "reason": "Same task and MIND ranking protocol.",
                    "confidence": "high",
                    "same_task": "high",
                    "same_protocol": "high",
                    "comparison_purposes": ["direct_performance"],
                    "comparison_purpose_evidence": {
                        "direct_performance": (
                            "Same task and MIND ranking protocol."
                        )
                    },
                    "mechanism_match": "high",
                    "intervention_interface_match": "high",
                    "fair_baseline_usefulness": "high",
                    "claim_diagnostic_value": "high",
                    "marginal_novelty": "high",
                    "mechanism_branch": "memory recommendation",
                    "task_protocol_relevance": "high",
                    "runnability": "runnable",
                }
                for candidate_id in ids
            ]
        }

    selected, diagnostics = select_direct_baseline_records(
        candidates,
        local_title="Uploaded Memory Recommender",
        queries=["q1", "q2", "q3", "q4"],
        review_as_of="2026-10-29",
        retrieval_plan=_plan(),
        llm_json=assess,
    )

    assert {batch[0] for batch in called_batches} == {"R1", "R21", "R41"}
    assert len(selected) == 10
    assert diagnostics["selector_error"] == "RuntimeError"
    assert diagnostics["selector_batch_strategy"] == "fixed"
    assert diagnostics["selector_batch_sizes"] == [20, 20, 1]
    assert diagnostics["selector_assessed_candidate_count"] == 21
    assert set(diagnostics["selector_not_assessed_candidate_ids"]) == {
        f"R{index}" for index in range(21, 41)
    }
    assert [batch["batch"] for batch in diagnostics["selector_batches"]] == [1, 2, 3]
    assert diagnostics["selector_batches"][1]["contract"] == "failed"
    assert diagnostics["selector_batches"][1]["error"] == "RuntimeError"
    assert diagnostics["selector_batches"][0]["assessed_count"] == 20
    assert diagnostics["selector_batches"][2]["assessed_count"] == 1


@pytest.mark.parametrize(
    ("strategy", "expected_sizes", "expected_first_ids"),
    [
        ("fixed", [20, 20, 9], ["R1", "R21", "R41"]),
        ("balanced", [17, 16, 16], ["R1", "R18", "R34"]),
    ],
)
def test_three_selector_workers_support_fixed_and_balanced_ab_batches(
    monkeypatch,
    strategy,
    expected_sizes,
    expected_first_ids,
):
    monkeypatch.setenv("BASELINE_SELECTOR_MAX_WORKERS", "3")
    monkeypatch.setenv("BASELINE_SELECTOR_BATCH_STRATEGY", strategy)
    candidates = [
        _candidate(
            f"A B Candidate {index:02d}",
            "cited_not_compared_reference",
            summary="Memory sequential recommendation evaluated on MIND ranking.",
        )
        for index in range(1, 50)
    ]
    expected_batch_by_first_id = {
        candidate_id: index
        for index, candidate_id in enumerate(expected_first_ids, start=1)
    }
    all_started = threading.Barrier(3)
    later_batches_completed = [threading.Event(), threading.Event()]
    state_lock = threading.Lock()
    calls: list[list[str]] = []
    completion_order: list[int] = []
    active_calls = 0
    max_active_calls = 0

    def assess(_system, prompt, **_kwargs):
        nonlocal active_calls, max_active_calls
        batch = json.loads(
            prompt.split("Candidate records in the current assessment batch:\n", 1)[1]
        )
        ids = [str(item["candidate_id"]) for item in batch]
        batch_index = expected_batch_by_first_id[ids[0]]
        with state_lock:
            calls.append(ids)
            active_calls += 1
            max_active_calls = max(max_active_calls, active_calls)
        try:
            all_started.wait(timeout=5)
            if batch_index == 3:
                with state_lock:
                    completion_order.append(3)
                later_batches_completed[1].set()
            elif batch_index == 2:
                assert later_batches_completed[1].wait(timeout=5)
                with state_lock:
                    completion_order.append(2)
                later_batches_completed[0].set()
            else:
                assert later_batches_completed[0].wait(timeout=5)
                with state_lock:
                    completion_order.append(1)
            return {
                "assessments": [
                    {
                        "candidate_id": candidate_id,
                        "decision": "core",
                        "reason": "Same task and MIND ranking protocol.",
                        "confidence": "high",
                        "same_task": "high",
                        "same_protocol": "high",
                        "comparison_purposes": ["direct_performance"],
                        "comparison_purpose_evidence": {
                            "direct_performance": (
                                "Same task and MIND ranking protocol."
                            )
                        },
                        "mechanism_match": "high",
                        "intervention_interface_match": "high",
                        "fair_baseline_usefulness": "high",
                        "claim_diagnostic_value": "high",
                        "marginal_novelty": "high",
                        "mechanism_branch": "memory recommendation",
                        "task_protocol_relevance": "high",
                        "runnability": "runnable",
                    }
                    for candidate_id in ids
                ]
            }
        finally:
            with state_lock:
                active_calls -= 1

    selected, diagnostics = select_direct_baseline_records(
        candidates,
        local_title="Uploaded Memory Recommender",
        queries=["q1", "q2", "q3", "q4"],
        review_as_of="2026-10-29",
        retrieval_plan=_plan(),
        llm_json=assess,
    )

    observed_by_first_id = {ids[0]: len(ids) for ids in calls}
    assert observed_by_first_id == dict(zip(expected_first_ids, expected_sizes))
    assert max_active_calls == 3
    assert completion_order == [3, 2, 1]
    assert diagnostics["selector_batch_strategy"] == strategy
    assert diagnostics["selector_batch_sizes"] == expected_sizes
    assert diagnostics["selector_configured_workers"] == 3
    assert diagnostics["selector_effective_workers"] == 3
    assert diagnostics["selector_assessed_candidate_count"] == 49
    assert diagnostics["selector_not_assessed_candidate_ids"] == []
    assert [item["title"] for item in selected] == [
        f"A B Candidate {index:02d}" for index in range(1, 11)
    ]


def test_selector_batch_strategy_rejects_unknown_value(monkeypatch):
    monkeypatch.setenv("BASELINE_SELECTOR_BATCH_STRATEGY", "unknown")
    candidates = [
        _candidate(
            "Invalid Strategy Candidate",
            "cited_not_compared_reference",
            summary="Memory sequential recommendation evaluated on MIND ranking.",
        )
    ]

    with pytest.raises(
        ValueError,
        match="BASELINE_SELECTOR_BATCH_STRATEGY must be 'balanced' or 'fixed'",
    ):
        select_direct_baseline_records(
            candidates,
            local_title="Uploaded Memory Recommender",
            queries=["q1", "q2", "q3", "q4"],
            review_as_of="2026-10-29",
            retrieval_plan=_plan(),
            llm_json=lambda *_args, **_kwargs: {"assessments": []},
        )


def test_branch_only_breaks_near_equal_utility_and_never_beats_large_utility_gap():
    candidates = [
        _candidate(
            "Primary Diffusion Candidate",
            "cited_not_compared_reference",
            summary="Diffusion recommendation evaluated on MIND ranking.",
            relevance_score="10",
        ),
        _candidate(
            "Complementary Diffusion Candidate",
            "cited_not_compared_reference",
            summary="Complementary diffusion recommendation evaluated on MIND ranking.",
            relevance_score="10",
        ),
        _candidate(
            "Near-Equal Memory Candidate",
            "cited_not_compared_reference",
            summary="Memory recommendation evaluated on MIND ranking.",
            relevance_score="0",
        ),
        _candidate(
            "Low-Utility Attention Candidate",
            "cited_not_compared_reference",
            summary="Attention recommendation evaluated on MIND ranking.",
            relevance_score="0",
        ),
    ]
    assessments = []
    for index, branch in enumerate(
        ("diffusion", "diffusion", "memory augmentation", "attention encoder"),
        start=1,
    ):
        low = index == 4
        assessments.append(
            {
                "candidate_id": f"R{index}",
                "decision": "extended" if low else "core",
                "reason": "Evidence-grounded assessment.",
                "confidence": "medium" if low else "high",
                "comparison_purposes": ["direct_performance"],
                "comparison_purpose_evidence": {
                    "direct_performance": "Same task and supplied MIND protocol."
                },
                "same_task": "medium" if low else "high",
                "same_protocol": "high",
                "mechanism_match": "low" if low else "high",
                "intervention_interface_match": "low" if low else "high",
                "fair_baseline_usefulness": "low" if low else "high",
                "claim_diagnostic_value": "low" if low else "high",
                "marginal_novelty": "medium" if low else "high",
                "mechanism_branch": branch,
                "task_protocol_relevance": "medium" if low else "high",
                "runnability": "uncertain" if low else "runnable",
            }
        )

    selected, diagnostics = select_direct_baseline_records(
        candidates,
        local_title="Uploaded Diffusion Memory Recommender",
        queries=["q1", "q2", "q3", "q4"],
        review_as_of="2026-10-29",
        retrieval_plan={**_plan(), "method_family": "diffusion memory"},
        llm_json=lambda *_args, **_kwargs: {"assessments": assessments},
    )

    titles = [item["title"] for item in selected]
    assert titles[:3] == [
        "Primary Diffusion Candidate",
        "Near-Equal Memory Candidate",
        "Complementary Diffusion Candidate",
    ]
    assert (
        "Low-Utility Attention Candidate" not in titles
        or titles.index("Complementary Diffusion Candidate")
        < titles.index("Low-Utility Attention Candidate")
    )
    diversity = diagnostics["evaluation_view_mechanism_diversity"]
    assert diversity["semantic_utility_tie_band"] == 2.0
    assert diversity["branch_diversity_policy"] == (
        "near_equal_semantic_utility_tie_break_only"
    )


def test_unspecified_branch_gets_no_near_equal_diversity_preference():
    def item(title: str, branch: str, lexical_score: str, rank: int):
        return {
            "title": title,
            "tier": "extended",
            "fill_source": "model_selection_downgraded_extended",
            "confidence": "medium",
            "comparison_purposes": ["direct_performance"],
            "comparison_purpose_evidence": {
                "direct_performance": "Supplied task and protocol evidence."
            },
            "task_protocol_relevance": "high",
            "runnability": "runnable",
            "evidence_level": "fulltext_verified",
            "fulltext_verified": True,
            "missing_status": "cited_not_compared",
            "relevance_score": lexical_score,
            "mechanism_branch": branch,
            "_selection_input_rank": rank,
            "verification": {
                "strong_evidence": {
                    "exact_bibliography_verification": True,
                    "specific_dataset_or_metric_match": True,
                    "non_generic_mechanism_match": True,
                },
                "selector_semantic_judgments": {
                    "grounded_comparison_purposes": ["direct_performance"],
                    "comparison_purpose_evidence": {
                        "direct_performance": (
                            "Supplied task and protocol evidence."
                        )
                    },
                    "same_task": "high",
                    "same_protocol": "high",
                    "mechanism_match": "high",
                    "intervention_interface_match": "high",
                    "fair_baseline_usefulness": "high",
                    "claim_diagnostic_value": "high",
                    "marginal_novelty": "high",
                    "objective_task_evidence_supported": True,
                    "objective_protocol_evidence_supported": True,
                    "objective_mechanism_evidence_supported": True,
                },
            },
        }

    selected, diagnostics = _extended_diversity_reorder(
        [
            item("Known Branch A", "memory", "20", 1),
            item("Known Branch B", "memory", "20", 2),
            item("Unspecified Branch", "", "0", 3),
        ],
        limit=2,
    )

    assert [entry["title"] for entry in selected] == [
        "Known Branch A",
        "Known Branch B",
    ]
    trace = diagnostics["candidate_utility_trace"]
    assert [entry["title"] for entry in trace] == [
        "Known Branch A",
        "Known Branch B",
        "Unspecified Branch",
    ]
    unspecified_trace = trace[-1]
    assert unspecified_trace["branch_diversity_eligible"] is False
    assert unspecified_trace["branch_previously_selected"] is False


def test_normalized_title_duplicate_is_explicitly_audited():
    base = {
        "tier": "extended",
        "fill_source": "model_selection_downgraded_extended",
        "confidence": "medium",
        "comparison_purposes": ["novelty_boundary"],
        "comparison_purpose_evidence": {
            "novelty_boundary": "Exact cited-title novelty evidence."
        },
        "task_protocol_relevance": "medium",
        "runnability": "uncertain",
        "evidence_level": "abstract_screened",
        "fulltext_verified": False,
        "missing_status": "cited_not_compared",
        "verification": {
            "strong_evidence": {
                "exact_bibliography_verification": True,
                "specific_dataset_or_metric_match": False,
                "non_generic_mechanism_match": True,
            },
            "selector_semantic_judgments": {
                "grounded_comparison_purposes": ["novelty_boundary"],
                "comparison_purpose_evidence": {
                    "novelty_boundary": "Exact cited-title novelty evidence."
                },
                "marginal_novelty": "high",
                "mechanism_match": "high",
                "claim_diagnostic_value": "high",
                "objective_mechanism_evidence_supported": True,
            },
        },
    }
    selected, diagnostics = _extended_diversity_reorder(
        [
            {**base, "title": "Foo-Bar", "_selection_input_rank": 1},
            {**base, "title": "Foo Bar", "_selection_input_rank": 2},
        ],
        limit=10,
    )

    assert [entry["title"] for entry in selected] == ["Foo-Bar"]
    assert diagnostics["identity_deduplication_count"] == 1
    duplicate = diagnostics["identity_deduplications"][0]
    assert duplicate["candidate_id"] == "R2"
    assert duplicate["canonical_title"] == "Foo-Bar"
    assert duplicate["decision"] == "eligible_duplicate_merged_before_ranking"


def test_mechanism_aliases_share_a_branch_and_utility_tie_break_keeps_rank_stable():
    candidates = [
        _candidate(
            title,
            "cited_not_compared_reference",
            summary="A directly comparable sequential recommender on MIND.",
        )
        for title in (
            "State Candidate A",
            "Denoising Candidate A",
            "State Candidate B",
            "Denoising Candidate B",
            "State Candidate C",
            "Sparse Profile Candidate",
            "Retrieval Candidate",
        )
    ]
    # The response order is the model rank; candidate IDs deliberately do not
    # follow title/input order.
    ranked = [
        ("R3", "Mamba / SSM"),
        ("R4", "self-supervised denoising"),
        ("R1", "state-space sequence model"),
        ("R2", "sequence denoise"),
        ("R6", "sparse profile"),
        ("R7", "retrieval augmentation"),
        ("R5", "state space model"),
    ]

    selected, diagnostics = select_direct_baseline_records(
        candidates,
        local_title="Uploaded Sequential Recommender",
        queries=["q1", "q2", "q3", "q4"],
        review_as_of="2026-10-29",
        retrieval_plan=_plan(),
        llm_json=lambda *_args, **_kwargs: {
            "selected": [
                {
                    "candidate_id": candidate_id,
                    "reason": "Same task and comparable MIND protocol.",
                    "confidence": "high",
                    "mechanism_branch": branch,
                    "task_protocol_relevance": "high",
                    "runnability": "runnable",
                    "same_task": "high",
                    "same_protocol": "high",
                    "intervention_interface_match": "high",
                    "fair_baseline_usefulness": "high",
                    "claim_diagnostic_value": "high",
                    "marginal_novelty": "high",
                }
                for candidate_id, branch in ranked
            ]
        },
    )

    selected_titles = [item["title"] for item in selected]
    assert set(selected_titles) == {
        "State Candidate A",
        "Denoising Candidate A",
        "State Candidate B",
        "Denoising Candidate B",
        "State Candidate C",
        "Sparse Profile Candidate",
        "Retrieval Candidate",
    }
    assert selected_titles.index("State Candidate B") < selected_titles.index(
        "State Candidate A"
    )
    assert selected_titles.index("Denoising Candidate B") < selected_titles.index(
        "Denoising Candidate A"
    )
    normalized_branches = [item["mechanism_branch_normalized"] for item in selected]
    assert set(normalized_branches) == {
        "state_space_sequence_model",
        "denoising",
        "sparse_profile",
        "retrieval_augmentation",
    }
    assert normalized_branches.count("state_space_sequence_model") == 3
    assert normalized_branches.count("denoising") == 2
    assert diagnostics["mechanism_diversity"]["normalized_branch_count"] == 4
    final_policy = diagnostics["evaluation_view_mechanism_diversity"]
    assert set(final_policy["covered_mechanism_branches"]) == {
        "state_space_sequence_model",
        "denoising",
        "sparse_profile",
        "retrieval_augmentation",
    }
    assert final_policy["branch_diversity_policy"] == (
        "near_equal_semantic_utility_tie_break_only"
    )


def test_empty_selector_is_fail_closed_and_never_backfills_unassessed_candidates():
    def exact_candidate(
        title: str,
        branch: str,
        relevance: str,
        lexical_score: str,
        *,
        bibliography_entry: str | None = None,
    ):
        return _candidate(
            title,
            "cited_not_compared_reference",
            summary=(
                "A directly comparable long-sequence recommendation method on "
                "MIND using memory compression, retrieval, diffusion, or denoising."
            ),
            relevance_score=lexical_score,
            bibliography_title=title,
            bibliography_title_similarity=1.0,
            bibliography_entry=(
                bibliography_entry
                or f"A. Author. 2025. {title}."
            ),
            citation_context=f"We discuss {title} for the same task.",
            bibliography_reason="Exact cited method absent from experiment comparisons.",
            method_name=title.split()[0],
            experiment_comparison_status="not_observed",
            mechanism_branch=branch,
            task_protocol_relevance=relevance,
        )

    candidates = [
        exact_candidate(
            "Compact Memory Candidate",
            "long-history compression",
            "high",
            "10",
            bibliography_entry=(
                "A. Author. 2025. Compact Memory Candidate. "
                "Evaluation incomplete; results are provisional."
            ),
        ),
        exact_candidate(
            "Retrieval Candidate",
            "retrieval-augmented preference memory",
            "medium",
            "8",
        ),
        exact_candidate(
            "Diffusion Exact Candidate",
            "diffusion-based recommendation",
            "medium",
            "5",
        ),
        _candidate(
            "Diffusion Lexical Candidate",
            "cited_not_compared_reference",
            summary=(
                "Diffusion memory denoising for long-sequence recommendation on MIND."
            ),
            relevance_score="99",
            mechanism_branch="diffusion recommendation",
            task_protocol_relevance="medium",
        ),
        exact_candidate(
            "Denoising Candidate",
            "sequence denoising",
            "medium",
            "7",
        ),
        exact_candidate(
            "State Space Candidate",
            "Mamba / SSM",
            "medium",
            "6",
        ),
        exact_candidate(
            "Second Diffusion Candidate",
            "generative diffusion",
            "medium",
            "4",
        ),
        exact_candidate(
            "Third Diffusion Candidate",
            "diffusion model",
            "medium",
            "3",
        ),
        exact_candidate(
            "Attention Candidate",
            "attention encoder",
            "medium",
            "4",
        ),
        exact_candidate(
            "Graph Candidate",
            "graph collaborative filtering",
            "medium",
            "4",
        ),
        exact_candidate(
            "Contrastive Candidate",
            "contrastive learning",
            "medium",
            "4",
        ),
        exact_candidate(
            "Transformer Candidate",
            "transformer sequence model",
            "medium",
            "4",
        ),
    ]

    selected, diagnostics = select_direct_baseline_records(
        candidates,
        local_title="Uploaded Long-History Recommender",
        queries=["q1", "q2", "q3", "q4"],
        review_as_of="2026-10-29",
        retrieval_plan={
            **_plan(),
            "task": "long-sequence recommendation",
            "method_family": "memory compression retrieval diffusion denoising state space",
            "cited_not_compared": [],
        },
        llm_json=lambda *_args, **_kwargs: {"selected": []},
    )

    assert selected == []
    assert diagnostics["selector_contract"] == "legacy_selected_only_fail_closed"
    assert diagnostics["selector_assessed_candidate_count"] == 0
    assert len(diagnostics["selector_not_assessed_candidate_ids"]) == 12
    assert diagnostics["deterministic_fill_count"] == 0
    assert all(
        audit.get("decision") == "selector_not_assessed"
        for audit in diagnostics["low_confidence_internal_audit"]
    )


def test_high_relevance_warning_extended_competes_in_unified_final_view():
    branches = [
        "diffusion recommendation",
        "diffusion recommendation",
        "sequence denoising",
        "attention encoder",
        "Mamba / SSM",
        "long-sequence architecture",
        "retrieval-augmented memory",
    ]
    titles = [
        "Auxiliary Diffusion Candidate",
        "Plug-In Diffusion Candidate",
        "Denoising Candidate",
        "Attention Candidate",
        "State Space Candidate",
        "Long Architecture Candidate",
        "Retrieval Memory Candidate",
    ]
    candidates = [
        _candidate(
            title,
            "cited_not_compared_reference",
            summary=(
                f"{title} solves long-sequence recommendation on MIND with "
                f"{branch}."
            ),
            relevance_score=str(30 - index),
            bibliography_title=title,
            bibliography_title_similarity=1.0,
            bibliography_entry=f"A. Author. 2025. {title}.",
            citation_context=f"We cite {title} for the same task.",
            bibliography_reason="Cited but absent from experiment comparisons.",
            mechanism_branch=branch,
            task_protocol_relevance="medium",
        )
        for index, (title, branch) in enumerate(zip(titles, branches), start=1)
    ]
    candidates.append(
        _candidate(
            "Incomplete Compression Candidate",
            "cited_not_compared_reference",
            summary="Long-history compression for recommendation on MIND.",
            relevance_score="20",
            bibliography_title="Incomplete Compression Candidate",
            bibliography_title_similarity=1.0,
            bibliography_entry=(
                "A. Author. 2025. Incomplete Compression Candidate. "
                "Evaluation incomplete; results are provisional."
            ),
            citation_context="We cite this compression method for the same task.",
            bibliography_reason="Cited but absent from experiment comparisons.",
            mechanism_branch="long-history compression",
            task_protocol_relevance="high",
        )
    )

    selected, diagnostics = select_direct_baseline_records(
        candidates,
        local_title="Uploaded Plug-In Sparse Memory Recommender",
        queries=["q1", "q2", "q3", "q4"],
        review_as_of="2026-10-29",
        retrieval_plan={
            **_plan(),
            "task": "long-sequence recommendation",
            "method_family": (
                "plug-in sparse memory compression diffusion denoising retrieval "
                "state space"
            ),
            "cited_not_compared": [],
        },
        llm_json=lambda *_args, **_kwargs: {
            "assessments": [
                {
                    "candidate_id": f"R{index}",
                    "decision": "core",
                    "reason": "Same task and directly comparable protocol.",
                    "confidence": "high",
                    "comparison_purposes": ["direct_performance"],
                    "comparison_purpose_evidence": {
                        "direct_performance": "Same task and supplied MIND protocol."
                    },
                    "mechanism_branch": branch,
                    "task_protocol_relevance": "high",
                    "runnability": "runnable",
                }
                for index, branch in enumerate(branches, start=1)
            ]
                + [
                    {
                        "candidate_id": "R8",
                        "decision": "extended",
                        "reason": "Direct compression diagnostic with incomplete evaluation.",
                        "confidence": "medium",
                        "comparison_purposes": ["mechanism_isolation"],
                        "comparison_purpose_evidence": {
                            "mechanism_isolation": "Compression mechanism diagnostic."
                        },
                        "same_task": "high",
                        "same_protocol": "unknown",
                        "mechanism_match": "high",
                        "intervention_interface_match": "high",
                        "fair_baseline_usefulness": "high",
                        "claim_diagnostic_value": "high",
                        "marginal_novelty": "high",
                        "mechanism_branch": "long-history compression",
                        "task_protocol_relevance": "high",
                        "runnability": "not_runnable",
                    }
                ]
        },
    )

    by_title = {item["title"]: item for item in selected}
    assert "Incomplete Compression Candidate" in by_title
    assert by_title["Incomplete Compression Candidate"]["tier"] == "extended"
    assert by_title["Incomplete Compression Candidate"]["availability_warnings"] == [
        "incomplete_experimental_evidence"
    ]
    assert "Plug-In Diffusion Candidate" in by_title
    assert by_title["Auxiliary Diffusion Candidate"]["tier"] == "core"
    assert "Denoising Candidate" in by_title
    assert "Retrieval Memory Candidate" in by_title
    assert diagnostics["core_candidate_count"] == 7
    assert diagnostics["extended_candidate_count"] == 1
    assert diagnostics["evaluation_view_mechanism_diversity"]["applied"] is True


def test_core_requires_explicit_double_high_and_runnable_nonwithdrawn_evidence():
    candidates = [
        _candidate(
            "Missing Confidence Candidate",
            "cited_not_compared_reference",
            summary="Memory denoising for sequential recommendation on MIND.",
        ),
        _candidate(
            "Missing Relevance Candidate",
            "cited_not_compared_reference",
            summary="Memory denoising for sequential recommendation on MIND.",
            # A planning-stage hint must not substitute for the selector's
            # explicit double-high decision.
            task_protocol_relevance="high",
        ),
        _candidate(
            "Withdrawn Candidate",
            "cited_not_compared_reference",
            summary="Memory denoising for sequential recommendation on MIND.",
            bibliography_entry=(
                "Withdrawn from arXiv due to incomplete experiments."
            ),
        ),
        _candidate(
            "Unrunnable Candidate",
            "cited_not_compared_reference",
            summary="Memory denoising for sequential recommendation on MIND.",
        ),
        _candidate(
            "Missing Runnability Candidate",
            "cited_not_compared_reference",
            summary="Memory denoising for sequential recommendation on MIND.",
        ),
        _candidate(
            "Verified Runnable Candidate",
            "cited_not_compared_reference",
            summary="Memory denoising for sequential recommendation on MIND.",
        ),
    ]
    responses = [
        {
            "candidate_id": "R1",
            "reason": "Direct task match.",
            "mechanism_branch": "denoising",
            "task_protocol_relevance": "high",
            "runnability": "runnable",
        },
        {
            "candidate_id": "R2",
            "reason": "Direct task match.",
            "confidence": "high",
            "mechanism_branch": "denoising",
            "runnability": "runnable",
        },
        {
            "candidate_id": "R3",
            "reason": "Direct task match.",
            "confidence": "high",
            "mechanism_branch": "denoising",
            "task_protocol_relevance": "high",
            "runnability": "runnable",
        },
        {
            "candidate_id": "R4",
            "reason": "The required artifact is unavailable, so it cannot be run.",
            "confidence": "high",
            "mechanism_branch": "denoising",
            "task_protocol_relevance": "high",
            "runnability": "not_runnable",
        },
        {
            "candidate_id": "R5",
            "reason": "Direct task match, but runnability was not verified.",
            "confidence": "high",
            "mechanism_branch": "denoising",
            "task_protocol_relevance": "high",
        },
        {
            "candidate_id": "R6",
            "reason": "Direct task match with an executable public protocol.",
            "confidence": "high",
            "mechanism_branch": "denoising",
            "task_protocol_relevance": "high",
            "runnability": "runnable",
        },
    ]

    selected, diagnostics = select_direct_baseline_records(
        candidates,
        local_title="Uploaded Memory Recommender",
        queries=["q1", "q2", "q3", "q4"],
        review_as_of="2026-10-29",
        retrieval_plan=_plan(),
        llm_json=lambda *_args, **_kwargs: {"selected": responses},
    )

    core = [item for item in selected if item["tier"] == "core"]
    assert [item["title"] for item in core] == ["Verified Runnable Candidate"]
    downgraded = {item["title"]: item for item in selected if item["tier"] == "extended"}
    assert {
        "Missing Confidence Candidate",
        "Missing Relevance Candidate",
        "Withdrawn Candidate",
        "Unrunnable Candidate",
        "Missing Runnability Candidate",
    }.issubset(downgraded)
    assert downgraded["Withdrawn Candidate"]["verification"]["core_blockers"] == [
        "withdrawn_or_retracted",
        "incomplete_experimental_evidence",
    ]
    assert downgraded["Unrunnable Candidate"]["verification"]["core_blockers"] == [
        "model_marked_not_runnable"
    ]
    assert downgraded["Missing Runnability Candidate"]["verification"][
        "core_blockers"
    ] == ["runnability_not_explicit_runnable"]
    assert diagnostics["core_double_high_required"] is True


def test_uncertain_runnability_cannot_enter_core():
    candidate = _candidate(
        "Uncertain Runnability Candidate",
        "cited_not_compared_reference",
        summary="Memory denoising for sequential recommendation on MIND.",
    )
    selected, _diagnostics = select_direct_baseline_records(
        [candidate],
        local_title="Uploaded Memory Recommender",
        queries=["q1"],
        review_as_of="2026-10-29",
        retrieval_plan=_plan(),
        llm_json=lambda *_args, **_kwargs: {
            "selected": [
                {
                    "candidate_id": "R1",
                    "reason": "Direct task match with uncertain availability.",
                    "confidence": "high",
                    "mechanism_branch": "denoising",
                    "task_protocol_relevance": "high",
                    "runnability": "uncertain",
                }
            ]
        },
    )

    assert selected[0]["tier"] == "extended"
    assert selected[0]["verification"]["core_blockers"] == [
        "runnability_not_explicit_runnable"
    ]


def test_incomplete_experiment_bibliography_note_cannot_enter_core():
    candidate = _candidate(
        "Incomplete Evaluation Candidate",
        "cited_not_compared_reference",
        summary="Memory denoising for sequential recommendation on MIND.",
        bibliography_entry=(
            "Preprint notice: evaluation incomplete; results are provisional."
        ),
    )
    selected, _diagnostics = select_direct_baseline_records(
        [candidate],
        local_title="Uploaded Memory Recommender",
        queries=["q1"],
        review_as_of="2026-10-29",
        retrieval_plan=_plan(),
        llm_json=lambda *_args, **_kwargs: {
            "selected": [
                {
                    "candidate_id": "R1",
                    "reason": "Direct task and protocol match.",
                    "confidence": "high",
                    "mechanism_branch": "denoising",
                    "task_protocol_relevance": "high",
                    "runnability": "runnable",
                }
            ]
        },
    )

    assert selected[0]["tier"] == "extended"
    assert selected[0]["verification"]["core_blockers"] == [
        "incomplete_experimental_evidence"
    ]


def test_mechanism_reorder_never_promotes_an_unselected_reference_to_core():
    candidates = [
        _candidate(
            f"Selected Direct Model {index}",
            "cited_not_compared_reference",
            summary="A directly comparable recommendation method on MIND.",
        )
        for index in range(1, 11)
    ]
    candidates.append(
        _candidate(
            "Unique Memory Compression Background Reference",
            "cited_not_compared_reference",
            summary="Memory compression terminology appears in this background citation.",
        )
    )

    selected, diagnostics = select_direct_baseline_records(
        candidates,
        local_title="Uploaded Memory Compression Recommender",
        queries=["q1", "q2", "q3", "q4"],
        review_as_of="2026-10-29",
        retrieval_plan={
            **_plan(),
            "method_family": "sparse memory latent compression diffusion denoising",
        },
        llm_json=lambda *_args, **_kwargs: {
            "selected": [
                {
                    "candidate_id": f"R{index}",
                    "reason": "Direct and comparable.",
                    "confidence": "high",
                    "task_protocol_relevance": "high",
                    "mechanism_branch": "direct comparable family",
                    "runnability": "runnable",
                    "same_task": "high",
                    "same_protocol": "high",
                    "intervention_interface_match": "high",
                    "fair_baseline_usefulness": "high",
                    "claim_diagnostic_value": "high",
                    "marginal_novelty": "high",
                }
                for index in range(1, 11)
            ]
            + [
                {
                    "candidate_id": "R11",
                    "decision": "reject",
                    "reason": "Background-only terminology is not a fair baseline.",
                    "confidence": "low",
                    "same_task": "low",
                    "same_protocol": "unknown",
                    "mechanism_match": "low",
                    "intervention_interface_match": "low",
                    "fair_baseline_usefulness": "low",
                    "claim_diagnostic_value": "low",
                    "marginal_novelty": "low",
                    "mechanism_branch": "background",
                    "task_protocol_relevance": "low",
                    "runnability": "uncertain",
                }
            ]
        },
    )

    assert len(selected) == 10
    assert "Unique Memory Compression Background Reference" not in {
        item["title"] for item in selected
    }
    assert diagnostics["core_candidate_count"] == 10
    assert diagnostics["model_selected_count"] == 10
    assert diagnostics["model_selected_retained_count"] == 10
    assert diagnostics["fill_sources"] == {
        "model_selection": 10,
        "unified_shortlist_hard_gate": 0,
    }


def test_extended_gate_rejects_cross_domain_generic_recommendation_overlap():
    candidates = [
        _candidate(
            "Hard Negative Sampling for Generic Recommendation",
            "task_and_evaluation_setting",
            summary=(
                "A user-item ranking system using negative sampling for a generic "
                "recommendation benchmark."
            ),
            relevance_score="8",
        )
    ]
    selected, diagnostics = select_direct_baseline_records(
        candidates,
        local_title="Memory Denoising for Long-History Recommendation",
        queries=["q1"],
        review_as_of="2026-10-29",
        retrieval_plan=_plan(),
        llm_json=lambda *_args, **_kwargs: {
            "assessments": [
                {
                    "candidate_id": "R1",
                    "decision": "extended",
                    "reason": "Generic recommendation overlap only.",
                    "confidence": "medium",
                    "same_task": "medium",
                    "same_protocol": "unknown",
                    "mechanism_match": "low",
                    "intervention_interface_match": "low",
                    "fair_baseline_usefulness": "low",
                    "claim_diagnostic_value": "low",
                    "marginal_novelty": "low",
                    "mechanism_branch": "generic recommendation",
                    "task_protocol_relevance": "medium",
                    "runnability": "uncertain",
                }
            ]
        },
    )

    assert selected == []
    audit = diagnostics["low_confidence_internal_audit"]
    assert audit[0]["decision"] == "selector_contract_not_assessable"
    assert audit[0]["reasons"] == [
        "selector_incomplete_comparison_purpose_contract"
    ]


def test_complete_assessment_missing_purpose_contract_fails_closed_but_legacy_selected_infers():
    candidate = _candidate(
        "Direct Memory Candidate",
        "cited_not_compared_reference",
        summary="Memory denoising for sequential recommendation on MIND.",
    )
    legacy_item = {
        "candidate_id": "R1",
        "reason": "Same task and supplied MIND protocol.",
        "confidence": "high",
        "same_task": "high",
        "same_protocol": "high",
        "mechanism_match": "high",
        "intervention_interface_match": "high",
        "fair_baseline_usefulness": "high",
        "claim_diagnostic_value": "high",
        "marginal_novelty": "high",
        "mechanism_branch": "denoising",
        "task_protocol_relevance": "high",
        "runnability": "runnable",
    }

    complete_selected, complete_diagnostics = select_direct_baseline_records(
        [candidate],
        local_title="Uploaded Memory Recommender",
        queries=["q1"],
        review_as_of="2026-10-29",
        retrieval_plan=_plan(),
        llm_json=lambda *_args, **_kwargs: {
            "assessments": [{**legacy_item, "decision": "core"}]
        },
    )
    legacy_selected, _legacy_diagnostics = select_direct_baseline_records(
        [candidate],
        local_title="Uploaded Memory Recommender",
        queries=["q1"],
        review_as_of="2026-10-29",
        retrieval_plan=_plan(),
        llm_json=lambda *_args, **_kwargs: {"selected": [legacy_item]},
    )

    assert complete_selected == []
    assert complete_diagnostics["low_confidence_internal_audit"][0][
        "decision"
    ] == "selector_contract_not_assessable"
    assert complete_diagnostics["low_confidence_internal_audit"][0][
        "reasons"
    ] == ["selector_incomplete_comparison_purpose_contract"]
    assert [item["tier"] for item in legacy_selected] == ["core"]
    assert legacy_selected[0]["comparison_purposes"] == ["direct_performance"]
    assert legacy_selected[0]["verification"]["selector_semantic_judgments"][
        "comparison_purpose_source"
    ] == "legacy_semantic_inference"


def test_explicit_selector_reject_is_terminal_even_with_grounded_purpose():
    candidate = _candidate(
        "Rejected but Relevant Candidate",
        "cited_not_compared_reference",
        summary="Memory denoising for sequential recommendation on MIND.",
    )
    selected, diagnostics = select_direct_baseline_records(
        [candidate],
        local_title="Uploaded Memory Recommender",
        queries=["q1"],
        review_as_of="2026-10-29",
        retrieval_plan=_plan(),
        llm_json=lambda *_args, **_kwargs: {
            "assessments": [
                {
                    "candidate_id": "R1",
                    "decision": "reject",
                    "reason": "Selector explicitly excludes this record.",
                    "confidence": "high",
                    "comparison_purposes": ["direct_performance"],
                    "comparison_purpose_evidence": {
                        "direct_performance": "Same task and supplied MIND protocol."
                    },
                    "same_task": "high",
                    "same_protocol": "high",
                    "mechanism_match": "high",
                    "intervention_interface_match": "high",
                    "fair_baseline_usefulness": "high",
                    "claim_diagnostic_value": "high",
                    "marginal_novelty": "high",
                    "mechanism_branch": "denoising",
                    "task_protocol_relevance": "high",
                    "runnability": "runnable",
                }
            ]
        },
    )

    assert selected == []
    assert diagnostics["model_selected_count"] == 0
    audit = diagnostics["low_confidence_internal_audit"]
    assert audit[0]["decision"] == "selector_explicit_reject"
    assert audit[0]["reason"] == "Selector explicitly excludes this record."


def test_complete_selector_contract_requires_decision_before_accepting_or_rejecting():
    candidates = [
        _candidate(
            "Missing Decision Candidate",
            "cited_not_compared_reference",
            summary="Memory denoising for sequential recommendation on MIND.",
        ),
        _candidate(
            "Contract-Free Reject Candidate",
            "cited_not_compared_reference",
            summary="Memory denoising for sequential recommendation on MIND.",
        ),
    ]
    selected, diagnostics = select_direct_baseline_records(
        candidates,
        local_title="Uploaded Memory Recommender",
        queries=["q1"],
        review_as_of="2026-10-29",
        retrieval_plan=_plan(),
        llm_json=lambda *_args, **_kwargs: {
            "assessments": [
                {
                    "candidate_id": "R1",
                    "reason": "Missing the required decision field.",
                    "confidence": "high",
                    "comparison_purposes": ["direct_performance"],
                    "comparison_purpose_evidence": {
                        "direct_performance": "Same task and MIND protocol."
                    },
                    "same_task": "high",
                    "same_protocol": "high",
                    "fair_baseline_usefulness": "high",
                    "task_protocol_relevance": "high",
                    "runnability": "runnable",
                },
                {
                    "candidate_id": "R2",
                    "decision": "reject",
                    "reason": "Reject without the required purpose contract.",
                    "confidence": "low",
                },
            ]
        },
    )

    assert selected == []
    audits = {
        item["candidate_id"]: item
        for item in diagnostics["low_confidence_internal_audit"]
    }
    assert audits["R1"]["decision"] == "selector_contract_not_assessable"
    assert audits["R1"]["reasons"] == [
        "selector_invalid_or_missing_decision"
    ]
    assert audits["R2"]["decision"] == "selector_contract_not_assessable"
    assert audits["R2"]["reasons"] == [
        "selector_incomplete_comparison_purpose_contract"
    ]


def test_complete_selector_contract_does_not_accept_legacy_tier_as_decision():
    candidate = _candidate(
        "Legacy Tier Alias Candidate",
        "cited_not_compared_reference",
        summary="Memory denoising for sequential recommendation on MIND.",
    )
    selected, diagnostics = select_direct_baseline_records(
        [candidate],
        local_title="Uploaded Memory Recommender",
        queries=["q1"],
        review_as_of="2026-10-29",
        retrieval_plan=_plan(),
        llm_json=lambda *_args, **_kwargs: {
            "assessments": [
                {
                    "candidate_id": "R1",
                    "tier": "core",
                    "reason": "Legacy alias must not satisfy the new contract.",
                    "confidence": "high",
                    "comparison_purposes": ["direct_performance"],
                    "comparison_purpose_evidence": {
                        "direct_performance": "Same task and MIND protocol."
                    },
                    "same_task": "high",
                    "same_protocol": "high",
                    "fair_baseline_usefulness": "high",
                    "task_protocol_relevance": "high",
                    "runnability": "runnable",
                }
            ]
        },
    )

    assert selected == []
    audit = diagnostics["low_confidence_internal_audit"][0]
    assert audit["decision"] == "selector_contract_not_assessable"
    assert audit["reasons"] == ["selector_invalid_or_missing_decision"]


def test_model_prose_cannot_ground_unrelated_cross_task_candidate():
    candidate = _candidate(
        "Bird Image Classifier",
        "task_and_evaluation_setting",
        summary="A convolutional image classifier for identifying bird species.",
        source="AMiner paper_detail abstract metadata",
        candidate_fulltext_verified=False,
    )
    selected, diagnostics = select_direct_baseline_records(
        [candidate],
        local_title="Uploaded Predictive User Profiler",
        queries=["ranking reward query policy"],
        review_as_of="2026-10-29",
        retrieval_plan={
            **_plan(),
            "task": "predictive user profiling",
            "method_family": "reinforcement query policy ranking reward retrieval",
            "evaluation_setting": "fixed retrieval-call budget",
            "cited_not_compared": [],
        },
        llm_json=lambda *_args, **_kwargs: {
            "assessments": [
                {
                    "candidate_id": "R1",
                    "decision": "extended",
                    "reason": "Unsupported model-authored analogy.",
                    "confidence": "medium",
                    "comparison_purposes": ["cross_task_adaptation"],
                    "comparison_purpose_evidence": {
                        "cross_task_adaptation": "The model claims it can be adapted."
                    },
                    "same_task": "low",
                    "same_protocol": "low",
                    "mechanism_match": "high",
                    "intervention_interface_match": "high",
                    "fair_baseline_usefulness": "high",
                    "claim_diagnostic_value": "high",
                    "mechanism_evidence": "Unverified model prose.",
                    "task_protocol_relevance": "medium",
                    "runnability": "uncertain",
                }
            ]
        },
    )

    assert selected == []
    audit = diagnostics["low_confidence_internal_audit"][0]
    assert audit["decision"] == "selector_purpose_not_assessable"
    assert audit["reasons"] == [
        "selector_no_objectively_supported_comparison_purpose"
    ]


def test_same_task_tokens_do_not_count_as_objective_mechanism_support():
    candidate = _candidate(
        "Predictive User Profiling with Logistic Regression",
        "task_and_evaluation_setting",
        summary=(
            "A conventional classifier for predictive user profiling from "
            "demographic summary statistics and logistic features."
        ),
        source="AMiner paper_detail abstract metadata",
        candidate_fulltext_verified=False,
    )
    selected, diagnostics = select_direct_baseline_records(
        [candidate],
        local_title="Learning to Profile for Predictive User Modeling",
        queries=["predictive user profiling"],
        review_as_of="2026-10-01",
        retrieval_plan={
            **_plan(),
            "task": "predictive user profiling",
            "method_family": "reinforcement policy action interface",
            "evaluation_setting": "fixed retrieval-call budget",
            "cited_not_compared": [],
        },
        llm_json=lambda *_args, **_kwargs: {
            "assessments": [
                {
                    "candidate_id": "R1",
                    "decision": "extended",
                    "reason": "Model-authored cross-task analogy.",
                    "confidence": "medium",
                    "comparison_purposes": ["cross_task_adaptation"],
                    "comparison_purpose_evidence": {
                        "cross_task_adaptation": "Could be adapted to the target."
                    },
                    "same_task": "high",
                    "same_protocol": "unknown",
                    "mechanism_match": "high",
                    "intervention_interface_match": "high",
                    "fair_baseline_usefulness": "medium",
                    "claim_diagnostic_value": "high",
                    "mechanism_evidence": "Unsupported selector prose.",
                    "task_protocol_relevance": "medium",
                    "runnability": "uncertain",
                }
            ]
        },
    )

    assert selected == []
    audit = diagnostics["low_confidence_internal_audit"][0]
    assert audit["decision"] == "selector_purpose_not_assessable"
    assert audit["reasons"] == [
        "selector_no_objectively_supported_comparison_purpose"
    ]
    judgments = audit["selector_semantic_judgments"]
    assert judgments["objective_mechanism_evidence_supported"] is False


def test_cross_task_rl_candidates_are_adaptation_required_extended_purposes():
    candidates = [
        _candidate(
            "ConvSearch-R1: Reinforcement Learning for Query Reformulation",
            "cited_not_compared_reference",
            summary=(
                "Reinforcement learning generates conversational-search queries "
                "for personalized retrieval under a fixed retrieval-call budget."
            ),
            source="AMiner paper_detail abstract metadata",
            candidate_fulltext_verified=False,
        ),
        _candidate(
            "DeepRetrieval: Reinforcement Learning for Search Queries",
            "cited_not_compared_reference",
            summary=(
                "A ranking-reward policy generates multiple search queries for "
                "retrieval but does not construct predictive user profiles."
            ),
            source="AMiner paper_detail abstract metadata",
            candidate_fulltext_verified=False,
        ),
        _candidate(
            "Rec-R1: Reinforcement Learning for Recommender Systems",
            "cited_not_compared_reference",
            summary=(
                "A reinforcement-learning ranking policy generates retrieval "
                "actions under a fixed retrieval-call budget."
            ),
            source="AMiner paper_detail abstract metadata",
            candidate_fulltext_verified=False,
        ),
    ]
    purpose_evidence = {
        "budget_matched_policy": "The abstract supplies an RL query policy that can be screened under a fixed retrieval-call budget.",
        "novelty_boundary": "The abstract supplies a closely related ranking-reward query-generation mechanism.",
        "cross_task_adaptation": "The terminal task differs, so inputs and actions require explicit adaptation.",
    }
    selected, diagnostics = select_direct_baseline_records(
        candidates,
        local_title="Learning to Profile for Predictive User Modeling",
        queries=["RL query generation retrieval budget"],
        review_as_of="2026-10-01",
        retrieval_plan={
            **_plan(),
            "task": "predictive user profiling for personalized retrieval",
            "method_family": (
                "reinforcement learning multi-round query generation ranking reward"
            ),
            "evaluation_setting": "fixed retrieval-call budget with Recall and NDCG",
            "cited_not_compared": [],
        },
        llm_json=lambda *_args, **_kwargs: {
            "assessments": [
                {
                    "candidate_id": f"R{index}",
                    "decision": "extended",
                    "reason": "Potential adapted component-level comparison.",
                    "confidence": "medium",
                    "comparison_purposes": list(purpose_evidence),
                    "comparison_purpose_evidence": purpose_evidence,
                    "adaptation_required": True,
                    "adaptation_note": (
                        "Adapt the query-policy input and output interface while "
                        "holding the retrieval-call budget fixed."
                    ),
                    "same_task": "low",
                    "same_protocol": "unknown",
                    "mechanism_match": "medium",
                    "intervention_interface_match": "medium",
                    "fair_baseline_usefulness": "medium",
                    "claim_diagnostic_value": "high",
                    "marginal_novelty": "high",
                    "mechanism_branch": "ranking-reward query generation",
                    "task_protocol_relevance": "medium",
                    "runnability": "uncertain",
                }
                for index in (1, 2, 3)
            ]
        },
    )

    assert {item["title"].split(":", 1)[0] for item in selected} == {
        "ConvSearch-R1",
        "DeepRetrieval",
        "Rec-R1",
    }
    for item in selected:
        assert item["tier"] == "extended"
        assert item["candidate_label"] == "candidate_to_verify"
        assert item["evidence_level"] == "abstract_screened"
        assert item["fulltext_verified"] is False
        assert item["adaptation_required"] is True
        assert item["comparison_purposes"] == list(purpose_evidence)
        assert "direct_performance_purpose_missing" in item["verification"][
            "core_blockers"
        ]
        assert "adaptation_required" in item["verification"]["core_blockers"]
        assert "candidate_fulltext_not_verified" in item["verification"][
            "core_blockers"
        ]
    assert diagnostics["comparison_purpose_counts"]["cross_task_adaptation"] == 3
    assert diagnostics["candidate_to_verify_count"] == 3


def test_purpose_conditioned_ranking_keeps_high_value_cross_task_and_audits_cap_omissions():
    titles = [
        "Adapted Query-Policy Candidate",
        *[f"Generic Same-Task Candidate {index}" for index in range(1, 11)],
        "Weak Cross-Task Candidate",
    ]
    candidates = [
        _candidate(
            title,
            "cited_not_compared_reference",
            summary=(
                "A reinforcement-learning query policy with ranking rewards and "
                "retrieval actions."
                if index in {1, 12}
                else "A generic neural method for sequential recommendation."
            ),
            bibliography_title=title,
            bibliography_title_similarity=1.0,
            bibliography_entry=f"A. Author. 2025. {title}.",
            citation_context=f"The manuscript cites {title} as prior work.",
            bibliography_reason="Cited but not compared in the experiments.",
            candidate_fulltext_verified=index != 1,
            candidate_fulltext_source=(
                "structured_test_fixture" if index != 1 else ""
            ),
            candidate_fulltext_evidence=(
                {"method_and_experiment": "Verified fixture evidence."}
                if index != 1
                else {}
            ),
        )
        for index, title in enumerate(titles, start=1)
    ]
    assessments = [
        {
            "candidate_id": "R1",
            "decision": "extended",
            "reason": "High-value adapted mechanism comparison.",
            "confidence": "medium",
            "comparison_purposes": ["mechanism_isolation"],
            "comparison_purpose_evidence": {
                "mechanism_isolation": (
                    "The cited abstract exposes a ranking-reward query policy "
                    "that isolates the retrieval-action mechanism."
                )
            },
            "same_task": "low",
            "same_protocol": "low",
            "mechanism_match": "high",
            "intervention_interface_match": "high",
            "fair_baseline_usefulness": "medium",
            "claim_diagnostic_value": "high",
            "marginal_novelty": "high",
            "mechanism_evidence": "Abstract describes the RL query policy.",
            "usefulness_evidence": "Citation context identifies the mechanism.",
            "mechanism_branch": "ranking-reward query policy",
            "task_protocol_relevance": "medium",
            "runnability": "uncertain",
        },
        *[
            {
                "candidate_id": f"R{index}",
                "decision": "extended",
                "reason": "Generic same-task lead without protocol evidence.",
                "confidence": "medium",
                "comparison_purposes": ["direct_performance"],
                "comparison_purpose_evidence": {
                    "direct_performance": "Same broad task, protocol unverified."
                },
                "same_task": "high",
                "same_protocol": "unknown",
                "mechanism_match": "low",
                "intervention_interface_match": "low",
                "fair_baseline_usefulness": "medium",
                "claim_diagnostic_value": "low",
                "marginal_novelty": "low",
                "mechanism_branch": "generic recommendation model",
                "task_protocol_relevance": "high",
                "runnability": "runnable",
            }
            for index in range(2, 12)
        ],
        {
            "candidate_id": "R12",
            "decision": "extended",
            "reason": "Weak cross-task overlap.",
            "confidence": "medium",
            "comparison_purposes": ["cross_task_adaptation"],
            "comparison_purpose_evidence": {
                "cross_task_adaptation": "A distant task might be adapted."
            },
            "same_task": "low",
            "same_protocol": "low",
            "mechanism_match": "low",
            "intervention_interface_match": "low",
            "fair_baseline_usefulness": "low",
            "claim_diagnostic_value": "low",
            "marginal_novelty": "low",
            "mechanism_branch": "distant query policy",
            "task_protocol_relevance": "low",
            "runnability": "uncertain",
        },
    ]

    selected, diagnostics = select_direct_baseline_records(
        candidates,
        local_title="Uploaded Predictive User Profiler",
        queries=["ranking reward query policy"],
        review_as_of="2026-10-29",
        retrieval_plan={
            **_plan(),
            "task": "predictive user profiling",
            "method_family": "reinforcement query policy ranking reward retrieval",
            "evaluation_setting": "fixed retrieval-call budget",
            "cited_not_compared": [],
        },
        llm_json=lambda *_args, **_kwargs: {"assessments": assessments},
    )

    assert len(selected) == 10
    assert selected[0]["title"] == "Adapted Query-Policy Candidate"
    trace = diagnostics["evaluation_candidate_utility_trace"]
    assert len(trace) == 12
    assert [item["final_rank"] for item in trace] == list(range(1, 13))
    assert sum(item["retained"] for item in trace) == 10
    assert trace[0]["utility_details"]["purpose"]["strongest_purpose"] == (
        "mechanism_isolation"
    )
    assert trace[0]["base_utility"] > next(
        item["base_utility"]
        for item in trace
        if item["title"] == "Generic Same-Task Candidate 1"
    )
    omissions = diagnostics["evaluation_cap_omissions"]
    assert diagnostics["evaluation_cap_omission_count"] == 2
    assert len(omissions) == 2
    assert {item["decision"] for item in omissions} == {
        "eligible_but_omitted_by_evaluation_cap"
    }
    assert all(item["candidate_id"].startswith("R") for item in omissions)
    assert all(item["comparison_purposes"] for item in omissions)
    assert all(item["comparison_purpose_evidence"] for item in omissions)
    assert all(item["selector_decision"] == "extended" for item in omissions)
    assert all(item["selector_reason"] for item in omissions)
    assert all(item["selection_evidence"] for item in omissions)
    assert all(item["selector_semantic_judgments"] for item in omissions)


def test_core_requires_objective_candidate_fulltext_not_model_claim():
    candidates = [
        _candidate(
            "Abstract-Only Direct Candidate",
            "cited_not_compared_reference",
            summary="Memory denoising for sequential recommendation on MIND.",
            source="AMiner paper_detail abstract metadata",
            evidence_sources=["paper_detail"],
            candidate_fulltext_verified=False,
        ),
        _candidate(
            "Structured-Fulltext Direct Candidate",
            "cited_not_compared_reference",
            summary="Memory denoising for sequential recommendation on MIND.",
        ),
    ]

    selected, diagnostics = select_direct_baseline_records(
        candidates,
        local_title="Uploaded Memory Recommender",
        queries=["memory denoising MIND"],
        review_as_of="2026-10-29",
        retrieval_plan=_plan(),
        llm_json=lambda *_args, **_kwargs: {
            "assessments": [
                {
                    "candidate_id": f"R{index}",
                    "decision": "core",
                    "reason": "Potential direct performance comparison.",
                    "confidence": "high",
                    "comparison_purposes": ["direct_performance"],
                    "comparison_purpose_evidence": {
                        "direct_performance": "Same task and supplied MIND protocol evidence."
                    },
                    # A selector claim cannot upgrade candidate provenance.
                    "fulltext_verified": True,
                    "same_task": "high",
                    "same_protocol": "high",
                    "mechanism_match": "high",
                    "intervention_interface_match": "high",
                    "fair_baseline_usefulness": "high",
                    "claim_diagnostic_value": "high",
                    "marginal_novelty": "high",
                    "mechanism_branch": "denoising",
                    "task_protocol_relevance": "high",
                    "runnability": "runnable",
                }
                for index in (1, 2)
            ]
        },
    )

    by_title = {item["title"]: item for item in selected}
    abstract_only = by_title["Abstract-Only Direct Candidate"]
    verified = by_title["Structured-Fulltext Direct Candidate"]
    assert abstract_only["tier"] == "extended"
    assert abstract_only["candidate_label"] == "candidate_to_verify"
    assert abstract_only["evidence_level"] == "abstract_screened"
    assert abstract_only["fulltext_verified"] is False
    assert "candidate_fulltext_not_verified" in abstract_only["verification"][
        "core_blockers"
    ]
    assert verified["tier"] == "core"
    assert verified["evidence_level"] == "fulltext_verified"
    assert verified["fulltext_verified"] is True
    assert diagnostics["fulltext_verified_candidate_count"] == 1


def test_explicit_purpose_without_purpose_evidence_is_rejected():
    candidate = _candidate(
        "Ungrounded Purpose Candidate",
        "task_and_evaluation_setting",
        summary="A generic retrieval system.",
    )
    selected, diagnostics = select_direct_baseline_records(
        [candidate],
        local_title="Uploaded Memory Recommender",
        queries=["q1"],
        review_as_of="2026-10-29",
        retrieval_plan=_plan(),
        llm_json=lambda *_args, **_kwargs: {
            "assessments": [
                {
                    "candidate_id": "R1",
                    "decision": "extended",
                    "reason": "Unsupported purpose label.",
                    "confidence": "medium",
                    "comparison_purposes": [
                        "mechanism_isolation",
                        "not_a_supported_purpose",
                    ],
                    "comparison_purpose_evidence": {},
                    "same_task": "low",
                    "same_protocol": "unknown",
                    "mechanism_match": "low",
                    "intervention_interface_match": "low",
                    "fair_baseline_usefulness": "low",
                    "claim_diagnostic_value": "low",
                    "marginal_novelty": "low",
                    "task_protocol_relevance": "low",
                    "runnability": "uncertain",
                }
            ]
        },
    )

    assert selected == []
    assert diagnostics["low_confidence_internal_audit"][0][
        "decision"
    ] == "selector_purpose_not_assessable"
    assert diagnostics["low_confidence_internal_audit"][0]["reasons"] == [
        "selector_no_grounded_comparison_purpose"
    ]


def test_same_year_exact_local_citation_is_admissible_but_external_is_not():
    cited = _candidate(
        "Locally Cited Same-Year Method",
        "cited_not_compared_reference",
        summary="Memory denoising on MIND.",
        published="2026",
        bibliography_entry="A. Author. 2026. Locally Cited Same-Year Method.",
        citation_context="We apply the locally cited method [7].",
        local_citation_before_review_cutoff=True,
    )
    external = _candidate(
        "External Same-Year Method",
        "task_and_evaluation_setting",
        summary="Memory denoising on MIND.",
        published="2026",
    )

    kept, diagnostics = filter_retrieval_records(
        [cited, external],
        local_title="Uploaded Memory Recommender",
        review_as_of="2026-10-29",
    )

    assert [item["title"] for item in kept] == ["Locally Cited Same-Year Method"]
    assert kept[0]["cutoff_status"] == "admissible_via_local_citation"
    assert kept[0]["aminer_cutoff_status"] == "uncertain_same_year"
    assert diagnostics["same_year_locally_cited_records_admitted"] == 1
    assert diagnostics["same_year_uncertain_records_removed"] == 1


def test_unified_preselector_pool_keeps_high_value_external_after_many_references():
    bibliography_candidates = [
        _candidate(
            f"Generic Prior Method {index:02d}",
            "cited_not_compared_reference",
            summary="A generic prior method with no target-specific evidence.",
            # Real exact-title bibliography verification records use their own
            # title as the retrieval query. That self-query must not count as
            # target-paper relevance.
            query=f"Generic Prior Method {index:02d}",
            bibliography_title=f"Generic Prior Method {index:02d}",
            bibliography_title_similarity=1.0,
            bibliography_entry=(
                f"A. Author. 2025. Generic Prior Method {index:02d}."
            ),
            citation_context="The manuscript cites this generic prior method.",
        )
        for index in range(1, 61)
    ]
    external_candidates = [
        _candidate(
            f"External Memory Denoising Candidate {index:02d}",
            "task_and_evaluation_setting",
            summary=(
                "A sequential recommendation method using memory denoising "
                "under the MIND ranking protocol."
            ),
            query="sequential recommendation memory denoising MIND",
        )
        for index in range(1, 21)
    ]
    high_value_external = external_candidates[0]

    filtered, filter_diagnostics = filter_retrieval_records(
        [*bibliography_candidates, *external_candidates],
        local_title="Uploaded Memory Denoising Recommender",
        review_as_of="2026-10-29",
        max_records=80,
    )
    direct_pool, semantic_diagnostics = semantic_baseline_pool(filtered)
    selector_prompts: list[str] = []

    def selector(_system, prompt, **_kwargs):
        selector_prompts.append(prompt)
        # The test concerns the bounded candidate pool presented to the
        # selector, not the selector's downstream semantic decisions.
        return {"assessments": []}

    _selected, selection_diagnostics = select_direct_baseline_records(
        direct_pool,
        local_title="Uploaded Memory Denoising Recommender",
        queries=["sequential recommendation memory denoising MIND"],
        review_as_of="2026-10-29",
        retrieval_plan=_plan(),
        llm_json=selector,
    )

    assert len(filtered) == 80
    assert filter_diagnostics["unified_candidate_pool"]["truncated_count"] == 0
    assert {
        item["relevance_score"]
        for item in filtered
        if item["retrieval_role"] == "cited_not_compared_reference"
    } == {"0"}
    assert semantic_diagnostics["pool_count"] == 80
    preselector = selection_diagnostics["preselector_unified_pool"]
    assert preselector["included_count"] == 60
    assert preselector["truncated_count"] == 20
    assert preselector["source_or_role_capacity_reservations"] is False
    included_titles = {
        item["title"] for item in preselector["included_candidates"]
    }
    assert high_value_external["title"] in included_titles
    # It appears once in the complete shortlist index and again in the first
    # actual assessment batch, proving it reaches the Selector payload.
    assert selector_prompts[0].count(high_value_external["title"]) >= 2
    assert selection_diagnostics["bibliography_candidates_sent_to_model"] == 40
    assert selection_diagnostics["bibliography_candidates_truncated"] == 20


def test_keyword_feedback_uses_short_controlled_terms_not_task_sentences():
    keywords = baseline_feedback_keywords(
        {
            "task": (
                "Please find methods for long-history sequential recommendation "
                "with a comparable ranking protocol"
            ),
            "method_family": "profile-aware key-value memory and diffusion denoising",
            "datasets_or_benchmarks": ["MIND"],
            "current_baselines": ["Mamba4Rec"],
            "cited_not_compared": [
                {"method_name": "ELASTIC"},
                {"method_name": "SSDRec"},
            ],
        }
    )

    assert keywords[:4] == ["ELASTIC", "SSDRec", "Mamba4Rec", "MIND"]
    assert all(len(keyword.split()) <= 4 for keyword in keywords)
    assert all("Please" not in keyword for keyword in keywords)


def test_extended_normalization_explains_cross_task_purpose_candidates():
    audit = normalize_baseline_audit(
        [
            {
                "candidate_id": "B1",
                "title": "Cross-Task Query Policy",
                "tier": "extended",
                "confidence": "medium",
                "candidate_label": "candidate_to_verify",
                "comparison_purposes": ["cross_task_adaptation"],
                "adaptation_required": True,
                "missing_status": "unknown",
                "selection_reason": (
                    "Potential cross-task query-policy comparison requiring adaptation."
                ),
            }
        ],
        {
            "records": [
                {
                    "candidate_id": "B1",
                    "status": "mentioned_not_compared",
                    "anchor_id": "",
                    "reason": "No experimental comparison was observed.",
                }
            ]
        },
        {},
    )

    assert audit["records"][0]["status"] == "candidate_to_check"
    assert audit["records"][0]["tier"] == "extended"
    assert audit["summary"]["tiers"] == {"core": 0, "extended": 1}
    assert any(
        "evidence/comparison-purpose gate" in limitation
        and "cross-task" in limitation
        for limitation in audit["limitations"]
    )
    assert audit["evaluation_view"] == {
        "max_candidates": 10,
        "status": "insufficient_candidates",
        "candidate_ids": ["B1"],
    }


def test_keyword_feedback_is_triggered_by_effective_coverage_not_raw_hits():
    keyword_calls: list[list[str]] = []

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def search(query, **_kwargs):
        # Many raw hits can collapse to one effective title after deduplication.
        return [
            _candidate(
                "One Repeated Search Result",
                "named_method_or_family",
                summary="Sequential recommendation on MIND.",
            )
            for _ in range(20)
        ], {"api_calls": {"paper_search_pro": 1}, "provider_errors": []}

    def keyword_search(keywords, **_kwargs):
        keyword_calls.append(list(keywords))
        return [
            _candidate(
                "Feedback Denoising Recommender",
                "keyword_batch_feedback",
                summary="Denoising sequential recommendation on MIND ranking.",
            )
        ], {
            "api_calls": {"paper_list_by_keywords": 1},
            "estimated_cost_cny_by_api": {"paper_list_by_keywords": 0.1},
            "provider_errors": [],
        }

    def select_direct(records, **_kwargs):
        selected = []
        for record in records:
            entry = dict(record)
            entry["comparison_role"] = "direct_baseline"
            selected.append(entry)
        return selected[:10], {
            "selection_status": "insufficient_candidates",
            "selected_record_count": min(len(selected), 10),
        }

    records, diagnostics = retrieve_baseline_candidates(
        ["q1", "q2", "q3", "q4"],
        local_title="Uploaded Memory Recommender",
        review_as_of="2026-10-29",
        proxy=None,
        select_direct=select_direct,
        retrieval_plan={
            **_plan(),
            "query_specs": [],
        },
        client_factory=FakeClient,
        aminer_search_fn=search,
        keyword_search_fn=keyword_search,
        aminer_detail_limit=0,
    )

    assert len(keyword_calls) == 1
    assert diagnostics["keyword_feedback"]["attempted"] is True
    assert diagnostics["keyword_feedback"]["trigger_basis"] == (
        "effective_coverage_after_selection_not_raw_result_count"
    )
    assert diagnostics["retrieval_round_count"] == 2
    assert diagnostics["max_retrieval_rounds"] == 2
    assert any(
        record.get("retrieval_role") == "keyword_batch_feedback"
        for record in records
    )


def test_ten_extended_candidates_do_not_suppress_second_round():
    keyword_calls: list[list[str]] = []

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def search(query, **_kwargs):
        return [
            _candidate(
                f"Candidate {index} for {query}",
                "task_and_evaluation_setting",
                summary="Sequential recommendation on MIND.",
            )
            for index in range(10)
        ], {"api_calls": {"paper_search_pro": 1}, "provider_errors": []}

    def select_direct(records, **_kwargs):
        selected = []
        for record in records[:10]:
            entry = dict(record)
            entry.update(
                {
                    "comparison_role": "direct_baseline",
                    "tier": "extended",
                }
            )
            selected.append(entry)
        return selected, {
            "selection_status": "completed",
            "selected_record_count": len(selected),
            "core_candidate_count": 0,
            "extended_candidate_count": len(selected),
        }

    retrieve_baseline_candidates(
        ["memory denoising"],
        local_title="Uploaded Memory Recommender",
        review_as_of="2026-10-29",
        proxy=None,
        select_direct=select_direct,
        retrieval_plan={**_plan(), "query_specs": []},
        client_factory=FakeClient,
        aminer_search_fn=search,
        keyword_search_fn=lambda keywords, **_kwargs: (
            keyword_calls.append(list(keywords)) or [],
            {"api_calls": {"paper_list_by_keywords": 1}, "provider_errors": []},
        ),
        aminer_detail_limit=0,
    )

    assert len(keyword_calls) == 1
