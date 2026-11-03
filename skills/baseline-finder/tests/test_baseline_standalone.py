"""Isolation and behavior tests for the standalone Baseline Finder."""

from __future__ import annotations

import ast
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import httpx

from baseline_finder.aminer import fetch_aminer_source
from baseline_finder.audit import normalize_baseline_audit
from baseline_finder.cli import build_parser, main
from baseline_finder.config import (
    JsonModelClient,
    ModelRuntime,
    load_env_file,
    resolve_model_runtime,
)
from baseline_finder.errors import BaselineAuditError
from baseline_finder.identity import detect_skill_runtime
from baseline_finder.pipeline import AuditRequest, run_baseline_pipeline
from baseline_finder.parsing import MarkdownParseResult, prepare_pdf_source
from baseline_finder.relation import retrieve_aminer_relation_candidates
from baseline_finder.retrieval import retrieve_baseline_candidates


SKILL_ROOT = Path(__file__).resolve().parents[1]


def test_cli_uses_installed_command_name() -> None:
    assert build_parser().prog == "baseline-finder"


def test_cli_requires_exactly_one_source_mode() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["--pdf", "paper.pdf", "--pub-id", "0123456789abcdef01234567"]
        )
    assert parser.parse_args(["--pub-id", "0123456789abcdef01234567"]).pdf is None


def test_pub_id_request_rejects_pdf_only_fallback_flag(tmp_path: Path) -> None:
    with pytest.raises(BaselineAuditError, match="valid only with --pdf"):
        AuditRequest.from_values(
            pdf=None,
            pub_id="0123456789abcdef01234567",
            review_as_of="2025-01-01",
            model_profile="deepseek",
            work_root=tmp_path / "work",
            grobid_url="http://127.0.0.1:8070",
            output=None,
            force=False,
            allow_pypdf_fallback=True,
        )


def test_relation_pub_id_is_optional_for_pdf_and_defaults_for_pub_id(
    tmp_path: Path,
) -> None:
    pub_id = "0123456789abcdef01234567"
    pub_request = AuditRequest.from_values(
        pdf=None,
        pub_id=pub_id,
        review_as_of="2025-01-01",
        model_profile="deepseek",
        work_root=tmp_path / "pub-work",
        grobid_url="http://127.0.0.1:8070",
        output=None,
        force=False,
    )
    assert pub_request.relation_pub_id == pub_id

    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\nstandalone-test")
    pdf_request = AuditRequest.from_values(
        pdf=str(pdf),
        relation_pub_id=None,
        review_as_of="2025-01-01",
        model_profile="deepseek",
        work_root=tmp_path / "pdf-work",
        grobid_url="http://127.0.0.1:8070",
        output=None,
        force=False,
    )
    assert pdf_request.relation_pub_id is None

    with pytest.raises(BaselineAuditError, match="valid only with --pdf"):
        AuditRequest.from_values(
            pdf=None,
            pub_id=pub_id,
            relation_pub_id="111111111111111111111111",
            review_as_of="2025-01-01",
            model_profile="deepseek",
            work_root=tmp_path / "invalid-work",
            grobid_url="http://127.0.0.1:8070",
            output=None,
            force=False,
        )


def test_public_relation_returns_backward_references_and_keeps_same_year_uncertainty() -> None:
    target = "0123456789abcdef01234567"
    referenced_old = "111111111111111111111111"
    referenced_same_year = "222222222222222222222222"
    referenced_future = "333333333333333333333333"
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url)))
        assert request.headers["authorization"] == "test-aminer-key"
        if request.method == "GET":
            assert dict(request.url.params) == {"id": target}
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "success": True,
                    "log_id": "relation-log",
                    "data": {
                        "_id": target,
                        "cited": [
                            {"id": referenced_old},
                            {"id": referenced_same_year},
                            {"id": referenced_future},
                        ],
                    },
                },
            )
        body = json.loads(request.content)
        assert set(body["ids"]) == {
            referenced_old,
            referenced_same_year,
            referenced_future,
        }
        return httpx.Response(
            200,
            json={
                "code": 200,
                "success": True,
                "data": [
                    {
                        "id": referenced_old,
                        "title": "Referenced Old Baseline",
                        "year": 2024,
                        "authors": [{"name": "Alice"}],
                        "abstract_slice": "A comparable method.",
                        "venue": {"raw": "Test Conference"},
                    },
                    {
                        "id": referenced_same_year,
                        "title": "Referenced Same Year",
                        "year": 2025,
                    },
                    {"id": referenced_future, "title": "Future Work", "year": 2026},
                ],
            },
        )

    def client_factory(**kwargs):
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    records, diagnostics = retrieve_aminer_relation_candidates(
        target,
        review_as_of="2025-09-24",
        api_key="test-aminer-key",
        client_factory=client_factory,
    )

    assert len(calls) == 2
    assert {record["aminer_pub_id"] for record in records} == {
        referenced_old,
        referenced_same_year,
    }
    by_id = {record["aminer_pub_id"]: record for record in records}
    assert by_id[referenced_old]["relation_direction"] == "target_references_candidate"
    assert by_id[referenced_same_year]["cutoff_status"] == "uncertain_same_year"
    assert by_id[referenced_same_year]["requires_cutoff_verification"] is True
    assert by_id[referenced_old]["published"] == "2024"
    assert by_id[referenced_old]["publication_year"] == 2024
    assert by_id[referenced_old]["publication_date_precision"] == "year"
    assert by_id[referenced_old]["venue"] == "Test Conference"
    assert diagnostics["status"] == "completed"
    assert diagnostics["relation_get_count"] == 1
    assert diagnostics["relation_get_completed_count"] == 1
    assert diagnostics["paper_info_post_count"] == 1
    assert diagnostics["paper_info_post_completed_count"] == 1
    assert diagnostics["total_http_request_count"] == 2
    assert diagnostics["supported_directions"] == ["target_references_candidate"]
    assert diagnostics["forward_citations_available"] is False
    assert diagnostics["uncertain_same_year_count"] == 1
    assert diagnostics["excluded_after_cutoff_count"] == 1
    assert {
        (item["aminer_pub_id"], item["reason"])
        for item in diagnostics["excluded_records"]
    } == {
        (referenced_future, "after_cutoff"),
    }
    assert diagnostics["relation_response_metadata"]["log_id"] == "relation-log"
    assert diagnostics["estimated_cost_cny"] == 0.1


def test_relation_graph_failure_is_visible_and_nonfatal() -> None:
    target = "0123456789abcdef01234567"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.params.get("id") == target
        return httpx.Response(
            503, json={"message": "unavailable", "log_id": "failed-log"}
        )

    def client_factory(**kwargs):
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    records, diagnostics = retrieve_aminer_relation_candidates(
        target,
        review_as_of="2025-09-24",
        api_key="test-aminer-key",
        client_factory=client_factory,
    )
    assert records == []
    assert diagnostics["status"] == "failed"
    assert "log_id=failed-log" in diagnostics["provider_errors"][0]
    assert diagnostics["relation_get_count"] == 1
    assert diagnostics["relation_get_completed_count"] == 0
    assert diagnostics["paper_info_post_count"] == 0
    assert diagnostics["total_http_request_count"] == 1


def test_relation_metadata_failure_is_visible_without_raising() -> None:
    target = "0123456789abcdef01234567"
    related = "111111111111111111111111"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"code": 200, "data": {"_id": target, "cited": [related]}},
            )
        return httpx.Response(503, json={"message": "metadata unavailable"})

    def client_factory(**kwargs):
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    records, diagnostics = retrieve_aminer_relation_candidates(
        target,
        review_as_of="2025-09-24",
        api_key="test-aminer-key",
        client_factory=client_factory,
    )
    assert records == []
    assert diagnostics["status"] == "partial"
    assert diagnostics["paper_info_post_count"] == 1
    assert diagnostics["paper_info_post_completed_count"] == 0
    assert diagnostics["total_http_request_count"] == 2
    assert diagnostics["metadata_missing_ids"] == [related]
    assert diagnostics["excluded_records"] == [
        {
            "aminer_pub_id": related,
            "title": "",
            "published": "",
            "reason": "metadata_missing",
        }
    ]
    assert "paper_info" in diagnostics["provider_errors"][0]


def test_legacy_work_dir_environment_does_not_override_default(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\nstandalone-test")
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    legacy_root = tmp_path / "legacy-root"
    captured: dict[str, AuditRequest] = {}

    def fake_run(request: AuditRequest, **_kwargs):
        captured["request"] = request
        return {"status": "completed"}

    with (
        patch.dict(
            os.environ,
            {
                "HOME": str(fake_home),
                "PAPER_REVIEW_WORK_DIR": str(legacy_root),
            },
            clear=True,
        ),
        patch("baseline_finder.cli.run_baseline_pipeline", side_effect=fake_run),
    ):
        assert main(["--pdf", str(pdf)]) == 0

    expected = (fake_home / ".local" / "share" / "baseline-finder").resolve()
    assert captured["request"].work_root == expected
    assert captured["request"].work_root != legacy_root.resolve()


def test_invalid_json_retry_uses_complete_core_instruction() -> None:
    requests: list[dict[str, object]] = []
    responses = iter(
        (
            SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content="not json"))
                ],
                usage=SimpleNamespace(
                    prompt_tokens=5,
                    completion_tokens=2,
                    total_tokens=7,
                    completion_tokens_details=SimpleNamespace(reasoning_tokens=1),
                ),
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"status": "ok"}')
                    )
                ],
                usage={
                    "input_tokens": 6,
                    "output_tokens": 3,
                    "total_tokens": 9,
                    "output_tokens_details": {"reasoning_tokens": 2},
                },
            ),
        )
    )

    class FakeCompletions:
        def create(self, **request):
            requests.append(request)
            return next(responses)

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

        def close(self) -> None:
            pass

    runtime = ModelRuntime(
        profile="deepseek",
        label="test",
        model="test-model",
        api_key="test-key",
        base_url="https://example.invalid/v1",
    )
    with (
        patch("baseline_finder.config.configured_proxy", return_value=None),
        patch("baseline_finder.config.OpenAI", FakeOpenAI),
    ):
        with JsonModelClient(runtime) as client:
            assert client.json("system", "user", max_tokens=100) == {"status": "ok"}
            usage = client.model_usage_snapshot()

    retry_instruction = (
        "\n\nYour previous response was not valid JSON. Return one complete JSON object only, "
        "with no Markdown fence, commentary, or trailing text. Keep every string concise. "
        "Do not omit required keys or close the response early."
    )
    assert len(requests) == 2
    assert requests[0]["messages"][1]["content"] == "user"
    assert requests[1]["messages"][1]["content"] == "user" + retry_instruction
    assert usage == {
        "telemetry_available": True,
        "usage_status": "complete",
        "logical_json_call_count": 1,
        "request_attempt_count": 2,
        "request_count": 2,
        "response_count": 2,
        "failed_request_count": 0,
        "error_count": 1,
        "json_retry_count": 1,
        "json_parse_error_count": 1,
        "responses_with_usage_count": 2,
        "responses_without_usage_count": 0,
        "usage_reported_request_count": 2,
        "usage_missing_request_count": 0,
        "usage_incomplete_request_count": 0,
        "derived_total_tokens_request_count": 0,
        "prompt_tokens": 11,
        "completion_tokens": 5,
        "reasoning_tokens": 3,
        "total_tokens": 16,
        "reasoning_tokens_reported_response_count": 2,
        "request_seconds_sum": usage["request_seconds_sum"],
        "request_wall_seconds": usage["request_wall_seconds"],
        "request_active_wall_seconds": usage["request_active_wall_seconds"],
        "active_request_count": 0,
        "max_concurrent_requests": 1,
        "global_gate_enabled": False,
        "global_gate_capacity": 0,
        "global_gate_acquisition_count": 0,
        "global_gate_waited_acquisition_count": 0,
        "global_gate_wait_seconds_sum": 0.0,
        "global_gate_wait_seconds": 0.0,
    }
    assert usage["request_seconds_sum"] == usage["request_wall_seconds"]
    assert usage["request_wall_seconds"] >= 0
    assert usage["request_active_wall_seconds"] <= usage["request_wall_seconds"]


def test_model_usage_tracks_single_response_and_derives_missing_total() -> None:
    class FakeCompletions:
        def create(self, **_request):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"status": "ok"}')
                    )
                ],
                usage=SimpleNamespace(
                    prompt_tokens=10,
                    completion_tokens=4,
                    completion_tokens_details=SimpleNamespace(reasoning_tokens=2),
                ),
            )

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

        def close(self) -> None:
            pass

    runtime = ModelRuntime(
        profile="deepseek",
        label="test",
        model="test-model",
        api_key="test-key",
        base_url="https://example.invalid/v1",
    )
    with (
        patch("baseline_finder.config.configured_proxy", return_value=None),
        patch("baseline_finder.config.OpenAI", FakeOpenAI),
    ):
        with JsonModelClient(runtime) as client:
            assert client.json("system", "user", max_tokens=100) == {"status": "ok"}
            usage = client.model_usage_snapshot()

    assert usage["request_count"] == 1
    assert usage["logical_json_call_count"] == 1
    assert usage["request_attempt_count"] == 1
    assert usage["json_retry_count"] == 0
    assert usage["usage_status"] == "complete"
    assert usage["usage_reported_request_count"] == 1
    assert usage["usage_missing_request_count"] == 0
    assert usage["usage_incomplete_request_count"] == 0
    assert usage["derived_total_tokens_request_count"] == 1
    assert usage["prompt_tokens"] == 10
    assert usage["completion_tokens"] == 4
    assert usage["reasoning_tokens"] == 2
    assert usage["total_tokens"] == 14


def test_model_usage_handles_response_without_usage() -> None:
    class FakeCompletions:
        def create(self, **_request):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"status": "ok"}')
                    )
                ],
                usage=None,
            )

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

        def close(self) -> None:
            pass

    runtime = ModelRuntime(
        profile="deepseek",
        label="test",
        model="test-model",
        api_key="test-key",
        base_url="https://example.invalid/v1",
    )
    with (
        patch("baseline_finder.config.configured_proxy", return_value=None),
        patch("baseline_finder.config.OpenAI", FakeOpenAI),
    ):
        with JsonModelClient(runtime) as client:
            assert client.json("system", "user", max_tokens=100) == {"status": "ok"}
            usage = client.model_usage_snapshot()

    assert usage["request_count"] == 1
    assert usage["usage_status"] == "unavailable"
    assert usage["usage_reported_request_count"] == 0
    assert usage["usage_missing_request_count"] == 1
    assert usage["prompt_tokens"] is None
    assert usage["completion_tokens"] is None
    assert usage["reasoning_tokens"] is None
    assert usage["total_tokens"] is None


def test_model_usage_marks_mixed_usage_as_partial() -> None:
    responses = iter(
        (
            SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content="not json"))
                ],
                usage=None,
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"status": "ok"}')
                    )
                ],
                usage={
                    "prompt_tokens": 7,
                    "completion_tokens": 3,
                    "total_tokens": 10,
                },
            ),
        )
    )

    class FakeCompletions:
        def create(self, **_request):
            return next(responses)

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

        def close(self) -> None:
            pass

    runtime = ModelRuntime(
        profile="deepseek",
        label="test",
        model="test-model",
        api_key="test-key",
        base_url="https://example.invalid/v1",
    )
    with (
        patch("baseline_finder.config.configured_proxy", return_value=None),
        patch("baseline_finder.config.OpenAI", FakeOpenAI),
    ):
        with JsonModelClient(runtime) as client:
            assert client.json("system", "user", max_tokens=100) == {"status": "ok"}
            usage = client.model_usage_snapshot()

    assert usage["usage_status"] == "partial"
    assert usage["request_attempt_count"] == 2
    assert usage["responses_with_usage_count"] == 1
    assert usage["responses_without_usage_count"] == 1
    assert usage["total_tokens"] == 10
    assert usage["reasoning_tokens"] is None


def test_model_profiles_do_not_route_cross_provider_credentials() -> None:
    with patch.dict(
        os.environ,
        {
            "OPENAI_API_KEY": "wrong-provider-key",
            "API_KEY": "generic-key",
            "LLM_API_KEY": "generic-llm-key",
            "OPENAI_BASE_URL": "https://wrong.example/v1",
            "BASE_URL": "https://generic.example/v1",
            "LLM_BASE_URL": "https://generic-llm.example/v1",
            "AGENT_MODEL": "wrong-model",
        },
        clear=True,
    ):
        with pytest.raises(BaselineAuditError):
            resolve_model_runtime("deepseek")
        for name in ("glm", "glm53", "glm53flash"):
            with pytest.raises(BaselineAuditError):
                resolve_model_runtime(name)


def test_dedicated_provider_credentials_resolve_to_expected_destinations() -> None:
    with patch.dict(
        os.environ,
        {
            "DEEPSEEK_API_KEY": "deepseek-test-key",
            "GLM_API_KEY": "glm-test-key",
        },
        clear=True,
    ):
        deepseek = resolve_model_runtime("deepseek")
        assert deepseek.api_key == "deepseek-test-key"
        assert deepseek.base_url == "https://api.deepseek.com"
        assert deepseek.model == "deepseek-chat"

        for name in ("glm", "glm53", "glm53flash"):
            glm = resolve_model_runtime(name)
            assert glm.api_key == "glm-test-key"
            assert glm.base_url == "https://open.bigmodel.cn/api/paas/v4"


def test_gpt_requires_both_gpt_key_and_explicit_base_url() -> None:
    with patch.dict(os.environ, {"GPT_API_KEY": "gpt-test-key"}, clear=True):
        with pytest.raises(BaselineAuditError):
            resolve_model_runtime("gpt")

        os.environ["GPT_BASE_URL"] = "https://trusted-gpt.example/v1"
        runtime = resolve_model_runtime("gpt")
        assert runtime.api_key == "gpt-test-key"
        assert runtime.base_url == "https://trusted-gpt.example/v1"


def test_environment_values_take_priority_over_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / "review.env"
    env_file.write_text(
        "DEEPSEEK_API_KEY=file-key\n"
        "DEEPSEEK_BASE_URL=https://file.example/v1\n",
        encoding="utf-8",
    )
    with patch.dict(
        os.environ,
        {
            "DEEPSEEK_API_KEY": "environment-key",
            "DEEPSEEK_BASE_URL": "https://environment.example/v1",
        },
        clear=True,
    ):
        load_env_file(env_file)
        runtime = resolve_model_runtime("deepseek")
        assert runtime.api_key == "environment-key"
        assert runtime.base_url == "https://environment.example/v1"


def test_python_imports_do_not_reach_repository_runtime() -> None:
    banned = {"paper_review_core", "deepreview", "demo_evidence_reviewer"}
    for path in [*SKILL_ROOT.glob("src/**/*.py"), *SKILL_ROOT.glob("scripts/*.py")]:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", 1)[0])
        assert not imported.intersection(banned), path
        assert "parents[3]" not in path.read_text(encoding="utf-8")


def test_normalizer_requires_server_owned_anchor() -> None:
    candidates = [
        {
            "candidate_id": "B1",
            "title": "A Direct Method",
            "comparison_role": "direct_baseline",
        }
    ]
    result = normalize_baseline_audit(
        candidates,
        {
            "records": [
                {
                    "candidate_id": "B1",
                    "status": "compared_in_experiments",
                    "anchor_id": "MADE_UP",
                    "reason": "claimed",
                }
            ]
        },
        {"P2S1": {"page": 2, "quote": "The real experimental comparison."}},
    )
    assert result["records"][0]["status"] == "not_assessable"
    assert result["records"][0]["anchor"] is None


def test_target_reference_can_support_mentioned_not_compared_without_local_anchor() -> None:
    relation_evidence = {
        "provider": "AMiner pub_relation",
        "target_pub_id": "0123456789abcdef01234567",
        "related_pub_id": "111111111111111111111111",
        "direction": "target_references_candidate",
    }
    result = normalize_baseline_audit(
        [
            {
                "candidate_id": "B1",
                "title": "A Referenced Direct Baseline",
                "comparison_role": "direct_baseline",
                "relation_direction": "target_references_candidate",
                "relation_evidence": relation_evidence,
            }
        ],
        {
            "records": [
                {
                    "candidate_id": "B1",
                    "status": "mentioned_not_compared",
                    "anchor_id": "",
                    "reason": "The target reference graph includes this direct baseline.",
                }
            ]
        },
        {},
    )
    record = result["records"][0]
    assert record["status"] == "mentioned_not_compared"
    assert record["anchor"] is None
    assert record["evidence_basis"] == "aminer_citation_graph"
    assert record["relation_evidence"] == relation_evidence


def test_candidate_citing_target_cannot_prove_target_mentioned_candidate() -> None:
    result = normalize_baseline_audit(
        [
            {
                "candidate_id": "B1",
                "title": "A Later Citing Paper",
                "comparison_role": "direct_baseline",
                "relation_direction": "candidate_cites_target",
                "relation_evidence": {
                    "provider": "AMiner pub_relation",
                    "direction": "candidate_cites_target",
                },
            }
        ],
        {
            "records": [
                {
                    "candidate_id": "B1",
                    "status": "mentioned_not_compared",
                    "anchor_id": "",
                    "reason": "Unsafe direction inference.",
                }
            ]
        },
        {},
    )
    assert result["records"][0]["status"] == "not_assessable"
    assert result["records"][0]["evidence_basis"] is None


def test_explicit_openalex_provider_and_arxiv_fallback() -> None:
    calls: list[tuple[str, str]] = []

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def openalex(query, _client, *, review_as_of):
        calls.append(("openalex", query))
        if query == "query one":
            return [
                {
                    "title": "Comparable Method One",
                    "authors": "A",
                    "published": "2024-01-01",
                    "url": "https://example/one",
                    "summary": "Comparable task evaluation.",
                    "query": query,
                    "source": "OpenAlex",
                }
            ]
        return []

    def arxiv(query, _client):
        calls.append(("arxiv", query))
        return [
            {
                "title": "Comparable Method Two",
                "authors": "B",
                "published": "2023-01-01",
                "url": "https://example/two",
                "summary": "Same benchmark task.",
                "query": query,
                "source": "arXiv API",
            }
        ]

    def select_direct(records, **_kwargs):
        selected = []
        for record in records:
            entry = dict(record)
            entry["comparison_role"] = "direct_baseline"
            selected.append(entry)
        return selected, {
            "selection_status": "completed",
            "selected_record_count": len(selected),
        }

    records, diagnostics = retrieve_baseline_candidates(
        ["query one", "query two"],
        local_title="Unrelated Uploaded Work",
        review_as_of="2025-01-01",
        proxy=None,
        select_direct=select_direct,
        client_factory=FakeClient,
        sleep=lambda _seconds: None,
        openalex_search_fn=openalex,
        arxiv_search_fn=arxiv,
        provider="openalex",
        external_fallback_provider="arxiv",
    )
    assert calls == [
        ("openalex", "query one"),
        ("openalex", "query two"),
        ("arxiv", "query two"),
    ]
    assert len(records) == 2
    assert diagnostics["retrieval_scope"] == "direct_baseline_candidates_only"
    assert diagnostics["external_fallback_used"] is True
    assert "cross-task adaptation candidates" in diagnostics["role_policy"]
    assert "only records passing deterministic same-task" not in diagnostics[
        "role_policy"
    ]


def test_pipeline_builds_a_focused_json_report_without_repository_services(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\nstandalone-test")
    work_root = tmp_path / "work"
    runs_dir = work_root / "runs"
    runs_dir.mkdir(parents=True)
    work_root.chmod(0o755)
    runs_dir.chmod(0o755)
    output = tmp_path / "report.json"
    request = AuditRequest.from_values(
        pdf=str(pdf),
        relation_pub_id="0123456789abcdef01234567",
        review_as_of="2025-01-01",
        model_profile="deepseek",
        work_root=work_root,
        grobid_url="http://127.0.0.1:8070",
        output=str(output),
        force=False,
    )

    experiment_sentences = " ".join(
        f"Experiment result {index} evaluates Direct Method on Dataset X against baselines."
        for index in range(40)
    )
    opening_sentences = " ".join(
        f"This manuscript studies a concrete task with documented evidence sentence {index}."
        for index in range(40)
    )

    def parse_source(_pdf, _run_dir, **_kwargs):
        pages = [
            "Standalone Paper Title\n\n" + opening_sentences,
            experiment_sentences,
        ]
        return {
            "markdown": "\n\n".join(pages),
            "pages": pages,
            "local_title": "Standalone Paper Title",
            "source_locations": [],
            "provider": "local_pypdf",
            "grobid_tei_file": None,
            "fallback_used": True,
            "diagnostics": [
                {
                    "parser": "local_grobid_tei_hybrid",
                    "status": "fallback",
                    "message": "test fallback",
                }
            ],
        }

    def retrieve(_queries, **_kwargs):
        return [
            {
                "title": "Direct Method",
                "authors": "Researcher",
                "published": "2024-01-01",
                "source": "OpenAlex",
                "url": "https://example/direct",
                "summary": "A directly comparable method.",
                "retrieval_role": "named_method_or_family",
                "comparison_role": "direct_baseline",
                "selection_reason": "Same task and protocol.",
            }
        ], {"status": "passed", "provider_errors": []}

    class FakeModel:
        def json(self, system, _user, *, max_tokens):
            assert max_tokens > 0
            if "retrieval plans" in system:
                return {
                    "task": "Task X",
                    "datasets_or_benchmarks": ["Dataset X"],
                    "evaluation_setting": "standard protocol",
                    "method_family": "Method family",
                    "current_baselines": ["Direct Method"],
                    "queries": ["task direct method", "task dataset x"],
                }
            return {
                "records": [
                    {
                        "candidate_id": "B1",
                        "status": "compared_in_experiments",
                        "anchor_id": "P2S1",
                        "reason": "The experiment span explicitly evaluates the method.",
                    }
                ]
            }

        def model_usage_snapshot(self):
            return {
                "telemetry_available": True,
                "usage_status": "complete",
                "logical_json_call_count": 2,
                "request_attempt_count": 2,
                "request_count": 2,
                "response_count": 2,
                "failed_request_count": 0,
                "error_count": 0,
                "json_retry_count": 0,
                "json_parse_error_count": 0,
                "responses_with_usage_count": 2,
                "responses_without_usage_count": 0,
                "usage_reported_request_count": 2,
                "usage_missing_request_count": 0,
                "usage_incomplete_request_count": 0,
                "derived_total_tokens_request_count": 0,
                "prompt_tokens": 100,
                "completion_tokens": 25,
                "reasoning_tokens": 5,
                "total_tokens": 125,
                "reasoning_tokens_reported_response_count": 2,
                "request_wall_seconds": 0.75,
            }

    runtime = ModelRuntime(
        profile="deepseek",
        label="test",
        model="test-model",
        api_key="not-used",
        base_url="https://not-used.invalid",
    )
    manifest = run_baseline_pipeline(
        request,
        runtime=runtime,
        model_client=FakeModel(),
        parse_source=parse_source,
        retrieve_relations=lambda *_args, **_kwargs: (
            [],
            {
                "enabled": True,
                "status": "failed",
                "target_pub_id": "0123456789abcdef01234567",
                "candidate_record_count": 0,
                "provider_errors": ["pub_relation: HTTP 503"],
                "relation_get_count": 2,
                "relation_get_completed_count": 0,
                "paper_info_post_count": 0,
                "paper_info_post_completed_count": 0,
                "total_http_request_count": 2,
            },
        ),
        retrieve_candidates=retrieve,
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    record = report["results"]["baseline_audit"]["records"][0]
    assert manifest["mode"] == "standalone-baseline"
    assert report["capability"] == "baseline"
    assert report["run_metadata"]["grobid_fallback_used"] is True
    assert report["run_metadata"]["relation_diagnostics"]["status"] == "failed"
    assert report["run_metadata"]["model_usage"]["total_tokens"] == 125
    timing = report["run_metadata"]["timing"]
    assert timing["started_at"] <= timing["finished_at"]
    assert timing["wall_seconds"] >= 0
    assert timing["model_request_wall_seconds"] == 0.75
    assert report["status"] == "completed"
    assert "citation-graph evidence was unavailable" not in " ".join(
        report["results"]["baseline_audit"]["limitations"]
    )
    assert record["status"] == "compared_in_experiments"
    assert record["anchor"]["page"] == 2
    assert not {
        "aminer_pub_id",
        "year",
        "publication_year",
        "venue",
        "relation_direction",
        "relation_evidence",
        "evidence_basis",
    }.intersection(record)
    assert stat.S_IMODE(work_root.stat().st_mode) == 0o700
    assert stat.S_IMODE(runs_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert stat.S_IMODE(Path(manifest["report"]).stat().st_mode) == 0o600


def test_pipeline_is_partial_when_baseline_classifier_fails(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\nstandalone-test")
    request = AuditRequest.from_values(
        pdf=str(pdf),
        review_as_of="2025-01-01",
        model_profile="deepseek",
        work_root=tmp_path / "work",
        grobid_url="http://127.0.0.1:8070",
        output=None,
        force=False,
    )
    experiment_text = " ".join(
        f"Experiment result {index} evaluates Direct Method on Dataset X against baselines."
        for index in range(80)
    )

    def parse_source(_pdf, _run_dir, **_kwargs):
        return {
            "markdown": experiment_text,
            "pages": [experiment_text],
            "local_title": "Standalone Paper Title",
            "source_locations": [],
            "provider": "local_pypdf",
            "grobid_tei_file": None,
            "fallback_used": True,
            "diagnostics": [],
        }

    candidate = {
        "title": "Direct Method",
        "authors": "Researcher",
        "published": "2024-01-01",
        "source": "OpenAlex",
        "url": "https://example/direct",
        "summary": "A directly comparable method.",
        "retrieval_role": "named_method_or_family",
        "comparison_role": "direct_baseline",
        "selection_reason": "Same task and protocol.",
    }

    class FailingClassifier:
        def __init__(self):
            self.calls = 0

        def json(self, _system, _user, *, max_tokens):
            assert max_tokens > 0
            self.calls += 1
            if self.calls == 1:
                return {
                    "task": "Task X",
                    "datasets_or_benchmarks": ["Dataset X"],
                    "evaluation_setting": "standard protocol",
                    "method_family": "Method family",
                    "current_baselines": [],
                    "queries": ["task direct method"],
                }
            raise RuntimeError("classifier unavailable")

    runtime = ModelRuntime(
        profile="deepseek",
        label="test",
        model="test-model",
        api_key="not-used",
        base_url="https://not-used.invalid",
    )
    manifest = run_baseline_pipeline(
        request,
        runtime=runtime,
        model_client=FailingClassifier(),
        parse_source=parse_source,
        retrieve_candidates=lambda *_args, **_kwargs: (
            [candidate],
            {"status": "passed", "provider_errors": []},
        ),
    )
    report = json.loads(Path(manifest["report"]).read_text(encoding="utf-8"))
    audit = report["results"]["baseline_audit"]
    assert manifest["status"] == "partial"
    assert report["status"] == "partial"
    assert audit["status"] == "not_assessed"
    assert report["run_metadata"]["model_usage"]["telemetry_available"] is False
    assert report["run_metadata"]["model_usage"]["total_tokens"] is None
    assert report["run_metadata"]["timing"]["model_request_wall_seconds"] is None
    assert audit["summary"]["not_assessable"] == 1
    assert "Baseline audit model call failed" in audit["limitations"][-1]
    assert audit["candidate_source"] == "dedicated_baseline_retrieval"
    assert audit["retrieval_policy"] == (
        "AMiner Open Platform discovery with no external fallback unless explicitly requested"
    )
    assert "relation_status" not in audit
    assert "relation_graph" not in audit["retrieval_diagnostics"]
    assert "relation_pub_id" not in report["source"]
    assert "relation_pub_id" not in report["run_metadata"]
    assert "relation_diagnostics" not in report["run_metadata"]
    assert "relation_graph" not in manifest
    assert not (Path(manifest["report"]).parent / "relation_graph.json").exists()


def test_pipeline_is_partial_without_local_experiment_catalog(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\nstandalone-test")
    request = AuditRequest.from_values(
        pdf=str(pdf),
        review_as_of="2025-01-01",
        model_profile="deepseek",
        work_root=tmp_path / "work",
        grobid_url="http://127.0.0.1:8070",
        output=None,
        force=False,
    )
    body_text = " ".join(
        f"This manuscript describes a concrete scientific task with sufficient text sentence {index}."
        for index in range(80)
    )

    def parse_source(_pdf, _run_dir, **_kwargs):
        return {
            "markdown": body_text,
            "pages": [body_text],
            "local_title": "Standalone Paper Title",
            "source_locations": [],
            "provider": "local_pypdf",
            "grobid_tei_file": None,
            "fallback_used": True,
            "diagnostics": [],
        }

    candidate = {
        "title": "Direct Method",
        "authors": "Researcher",
        "published": "2024-01-01",
        "source": "OpenAlex",
        "url": "https://example/direct",
        "summary": "A directly comparable method.",
        "retrieval_role": "named_method_or_family",
        "comparison_role": "direct_baseline",
        "selection_reason": "Same task and protocol.",
    }

    class PlanningOnlyModel:
        def __init__(self):
            self.calls = 0

        def json(self, _system, _user, *, max_tokens):
            assert max_tokens > 0
            self.calls += 1
            return {
                "task": "Task X",
                "datasets_or_benchmarks": [],
                "evaluation_setting": "standard protocol",
                "method_family": "Method family",
                "current_baselines": [],
                "queries": ["task direct method"],
            }

    model = PlanningOnlyModel()
    runtime = ModelRuntime(
        profile="deepseek",
        label="test",
        model="test-model",
        api_key="not-used",
        base_url="https://not-used.invalid",
    )
    manifest = run_baseline_pipeline(
        request,
        runtime=runtime,
        model_client=model,
        parse_source=parse_source,
        retrieve_candidates=lambda *_args, **_kwargs: (
            [candidate],
            {"status": "passed", "provider_errors": []},
        ),
    )
    report = json.loads(Path(manifest["report"]).read_text(encoding="utf-8"))
    audit = report["results"]["baseline_audit"]
    assert model.calls == 1
    assert manifest["status"] == "partial"
    assert report["status"] == "partial"
    assert audit["status"] == "not_assessed"
    assert audit["summary"]["not_assessable"] == 1
    assert "No locally extracted experimental pages" in audit["limitations"][-1]


def test_pdf_mode_requires_grobid_unless_fallback_is_explicit(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\ntest")
    local = MarkdownParseResult(
        markdown="Local text",
        pages=["Local text"],
        provider="local_pypdf",
    )
    connection_error = httpx.ConnectError(
        "offline",
        request=httpx.Request("POST", "http://127.0.0.1:8070/api/processFulltextDocument"),
    )
    progress_events: list[tuple[str, str, dict[str, object] | None]] = []
    with (
        patch("baseline_finder.parsing.parse_pdf_locally", return_value=local),
        patch(
            "baseline_finder.parsing.request_grobid_fulltext",
            side_effect=connection_error,
        ),
    ):
        with pytest.raises(ValueError, match="GROBID could not produce"):
            prepare_pdf_source(
                pdf,
                tmp_path / "strict",
                grobid_url="http://127.0.0.1:8070",
            )

    with (
        patch("baseline_finder.parsing.parse_pdf_locally", return_value=local),
        patch(
            "baseline_finder.parsing.request_grobid_fulltext",
            side_effect=connection_error,
        ),
    ):
        parsed = prepare_pdf_source(
            pdf,
            tmp_path / "fallback",
            grobid_url="http://127.0.0.1:8070",
            allow_pypdf_fallback=True,
            progress=lambda phase, message, metrics: progress_events.append(
                (phase, message, metrics)
            ),
        )
    assert parsed["provider"] == "local_pypdf"
    assert parsed["fallback_used"] is True
    assert "lower-quality pypdf fallback" in progress_events[-1][1]
    assert progress_events[-1][2] == {
        "parser": "local_pypdf",
        "fallback_used": True,
    }


def test_aminer_interface_b_frozen_http_preserves_experiment_structure(
    tmp_path: Path,
) -> None:
    pub_id = "0123456789abcdef01234567"
    artifact_root = "https://paper.oss-cn-beijing.aliyuncs.com/run"
    content_url = f"{artifact_root}/paper_content_list.json"
    middle_url = f"{artifact_root}/paper_middle.json"
    markdown_url = f"{artifact_root}/paper.md"
    calls: list[tuple[str, str]] = []

    content_list = [
        {"type": "text", "text": "A Structured Paper", "text_level": 1, "page_idx": 0},
        {"type": "text", "text": "We study Task X.", "page_idx": 0, "bbox": [1, 2, 3, 4]},
        {"type": "text", "text": "Experiments", "text_level": 1, "page_idx": 1},
        {
            "type": "table",
            "table_caption": ["Table 1: Main results"],
            "table_body": "| Method | Score |\n| Direct Method | 91 |",
            "page_idx": 1,
            "bbox": [5, 6, 7, 8],
        },
        {"type": "equation", "text": "score = correct / total", "bbox": [9, 10, 11, 12]},
    ]
    middle = {"pdf_info": [{"page_size": [600, 800]}, {"page_size": [600, 800]}]}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url)))
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["pub_id"] == pub_id
            assert request.headers["authorization"] == "test-aminer-key"
            assert request.headers["x-platform"] == detect_skill_runtime()
            assert request.headers["x-skill-name"] == "baseline-finder"
            assert request.headers["x-skill-version"] == "0.5.1"
            if body.get("file_types"):
                return httpx.Response(200, json={"data": [{"md": [markdown_url]}]})
            return httpx.Response(
                200,
                json={"data": [{"json": [content_url, middle_url]}]},
            )
        if str(request.url) == content_url:
            return httpx.Response(200, json=content_list)
        if str(request.url) == middle_url:
            return httpx.Response(200, json=middle)
        if str(request.url) == markdown_url:
            return httpx.Response(200, content=b"# Provider copy\n\nProvider text")
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = fetch_aminer_source(
            pub_id,
            tmp_path,
            api_key="test-aminer-key",
            client=client,
        )

    assert len(calls) == 5
    assert result["provider"] == "aminer_interface_b_content_list"
    assert len(result["pages"]) == 2
    assert "| Direct Method | 91 |" in result["pages"][1]
    assert "score = correct / total" in result["pages"][1]
    assert result["source_locations"][1]["blocks"][-1]["page_inherited"] is True
    assert result["source_locations"][1]["page_size"] == [600, 800]
    manifest = json.loads((tmp_path / "source_manifest.json").read_text(encoding="utf-8"))
    assert manifest["structured_fallback_used"] is False
    assert manifest["provider_markdown_file"] == "source_provider.md"
    assert manifest["location_unit"] == "aminer_content_block"
    assert manifest["location_numbering"] == "physical_page_and_section_block"
    assert manifest["content_block_type_counts"]["table"] == 1
    assert manifest["page_coordinate_count"] == 3
    assert manifest["explicit_page_coordinate_count"] == 2
    assert manifest["inherited_page_block_count"] == 1
    retained = "\n".join(
        path.read_text(encoding="utf-8")
        for path in tmp_path.iterdir()
        if path.is_file()
    )
    assert "test-aminer-key" not in retained


def test_aminer_refuses_untrusted_artifact_host(tmp_path: Path) -> None:
    pub_id = "0123456789abcdef01234567"
    external_requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = json.loads(request.content)
            if body.get("file_types"):
                return httpx.Response(200, json={"data": [{"md": []}]})
            return httpx.Response(
                200,
                json={"data": [{"json": ["https://notaliyuncs.com/paper_content_list.json"]}]},
            )
        external_requests.append(str(request.url))
        return httpx.Response(200, json=[])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(BaselineAuditError, match="untrusted artifact"):
            fetch_aminer_source(
                pub_id,
                tmp_path,
                api_key="test-aminer-key",
                client=client,
            )
    assert external_requests == []


def test_aminer_markdown_fallback_and_id_normalization_are_visible(
    tmp_path: Path,
) -> None:
    pub_id = "ABCDEF0123456789ABCDEF01"
    normalized = pub_id.lower()
    markdown_url = "https://paper.oss-cn-beijing.aliyuncs.com/run/paper.md"
    posted_ids: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = json.loads(request.content)
            posted_ids.append(body["pub_id"])
            if body.get("file_types"):
                return httpx.Response(200, json={"data": [{"md": [markdown_url]}]})
            return httpx.Response(200, json={"data": [{"json": []}]})
        assert str(request.url) == markdown_url
        assert "authorization" not in request.headers
        return httpx.Response(
            200,
            content=(
                b"# Paper\n\nA manuscript paragraph.\n\n"
                b"# Experiments\n\nA visible comparison paragraph."
            ),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = fetch_aminer_source(
            pub_id,
            tmp_path,
            api_key="test-aminer-key",
            client=client,
        )

    assert posted_ids == [normalized, normalized]
    assert result["provider"] == "aminer_interface_b_markdown_fallback"
    assert result["fallback_used"] is True
    manifest = result["manifest"]
    assert manifest["structured_fallback_used"] is True
    assert manifest["structured_fallback_reason"]
    assert manifest["provider_markdown_file"] is None
    assert manifest["location_unit"] == "markdown_block"
    assert manifest["location_numbering"] == "section_local"
    assert manifest["physical_page_count"] is None
    assert manifest["logical_text_chunks"] == len(result["pages"])
    assert stat.S_IMODE((tmp_path / "source.md").stat().st_mode) == 0o600


def test_aminer_revalidates_every_redirect_before_requesting_it(
    tmp_path: Path,
) -> None:
    pub_id = "0123456789abcdef01234567"
    trusted_url = "https://paper.oss-cn-beijing.aliyuncs.com/run/paper_content_list.json"
    attacker_url = "https://attacker.example/stolen.json"
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.method == "POST":
            body = json.loads(request.content)
            if body.get("file_types"):
                return httpx.Response(200, json={"data": [{"md": []}]})
            return httpx.Response(200, json={"data": [{"json": [trusted_url]}]})
        if str(request.url) == trusted_url:
            return httpx.Response(302, headers={"location": attacker_url})
        raise AssertionError("an untrusted redirect target must never be requested")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(BaselineAuditError, match="untrusted artifact"):
            fetch_aminer_source(
                pub_id,
                tmp_path,
                api_key="test-aminer-key",
                client=client,
            )
    assert attacker_url not in requested


def test_parse_provenance_survives_a_later_model_failure(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\nstandalone-test")
    work_root = tmp_path / "work"
    request = AuditRequest.from_values(
        pdf=str(pdf),
        review_as_of="2025-01-01",
        model_profile="deepseek",
        work_root=work_root,
        grobid_url="http://127.0.0.1:8070",
        output=None,
        force=False,
        allow_pypdf_fallback=True,
    )
    text = " ".join(
        f"Experiment evidence sentence {index} compares a baseline."
        for index in range(100)
    )

    def fallback_source(_pdf, _run_dir, **_kwargs):
        return {
            "markdown": text,
            "pages": [text],
            "local_title": "Fallback Paper",
            "source_locations": [],
            "provider": "local_pypdf",
            "grobid_tei_file": None,
            "fallback_used": True,
            "diagnostics": [
                {
                    "parser": "local_grobid_tei_hybrid",
                    "status": "fallback",
                    "message": "frozen fallback",
                }
            ],
        }

    class FailingModel:
        def json(self, *_args, **_kwargs):
            raise RuntimeError("frozen model outage")

    runtime = ModelRuntime(
        profile="deepseek",
        label="test",
        model="test-model",
        api_key="not-used",
        base_url="https://not-used.invalid",
    )
    with pytest.raises(RuntimeError, match="frozen model outage"):
        run_baseline_pipeline(
            request,
            runtime=runtime,
            model_client=FailingModel(),
            parse_source=fallback_source,
        )
    run_dirs = list((work_root / "runs").iterdir())
    assert len(run_dirs) == 1
    provenance = json.loads(
        (run_dirs[0] / "source_parse.json").read_text(encoding="utf-8")
    )
    assert provenance["provider"] == "local_pypdf"
    assert provenance["fallback_used"] is True
    assert provenance["diagnostics"][0]["status"] == "fallback"


def test_pipeline_accepts_pub_id_without_pdf_or_repository_services(
    tmp_path: Path,
) -> None:
    pub_id = "0123456789abcdef01234567"
    output = tmp_path / "pub-id-report.json"
    request = AuditRequest.from_values(
        pdf=None,
        pub_id=pub_id,
        review_as_of="2025-01-01",
        model_profile="deepseek",
        work_root=tmp_path / "work",
        grobid_url="http://127.0.0.1:8070",
        output=str(output),
        force=False,
    )
    opening = " ".join(
        f"This paper describes Task X with evidence sentence {index}."
        for index in range(50)
    )
    experiments = " ".join(
        f"Experiment {index} compares Direct Method on Dataset X."
        for index in range(50)
    )

    def fetch_source(received_pub_id, _run_dir, **_kwargs):
        assert received_pub_id == pub_id
        return {
            "markdown": f"# Paper\n\n{opening}\n\n# Experiments\n\n{experiments}",
            "pages": [opening, experiments],
            "local_title": "A Pub ID Paper",
            "source_locations": [],
            "provider": "aminer_interface_b_content_list",
            "fallback_used": False,
            "diagnostics": [],
            "manifest": {
                "content_block_count": 4,
                "structured_fallback_used": False,
                "content_list_file": "source_content_list.json",
                "retrieval_interface": "aminer_interface_b",
            },
        }

    class FakeModel:
        def json(self, system, _user, *, max_tokens):
            assert max_tokens > 0
            if "retrieval plans" in system:
                return {
                    "task": "Task X",
                    "datasets_or_benchmarks": ["Dataset X"],
                    "evaluation_setting": "standard protocol",
                    "method_family": "Method family",
                    "current_baselines": ["Direct Method"],
                    "queries": ["Task X Direct Method"],
                }
            return {
                "records": [
                    {
                        "candidate_id": "B1",
                        "status": "compared_in_experiments",
                        "anchor_id": "P2S1",
                        "reason": "The experiment evidence names the comparison.",
                    }
                ]
            }

    candidate = {
        "title": "Direct Method",
        "authors": "Researcher",
        "published": "2024-01-01",
        "source": "OpenAlex",
        "url": "https://example/direct",
        "summary": "A directly comparable method.",
        "retrieval_role": "named_method_or_family",
        "comparison_role": "direct_baseline",
        "selection_reason": "Same task and protocol.",
    }
    relation_candidates = [
        {
            "aminer_pub_id": f"{index + 1:024x}",
            "title": f"Relation Candidate {index + 1}",
            "authors": f"Relation Author {index + 1}",
            "published": "2024",
            "year": 2024,
            "publication_year": 2024,
            "publication_date_precision": "year",
            "venue": "Relation Venue",
            "source": "AMiner pub_relation + paper_info",
            "url": f"https://www.aminer.cn/pub/{index + 1:024x}",
            "summary": "A relation-discovered candidate.",
            "retrieval_role": "citation_graph_reference",
            "relation_direction": "target_references_candidate",
            "relation_target_pub_id": pub_id,
            "relation_evidence": {
                "provider": "AMiner pub_relation",
                "target_pub_id": pub_id,
                "related_pub_id": f"{index + 1:024x}",
                "direction": "target_references_candidate",
            },
        }
        for index in range(8)
    ]

    def retrieve_relations(received_pub_id, **_kwargs):
        assert received_pub_id == pub_id
        return relation_candidates, {
            "enabled": True,
            "status": "completed",
            "target_pub_id": received_pub_id,
            "candidate_record_count": len(relation_candidates),
            "provider_errors": [],
        }

    runtime = ModelRuntime(
        profile="deepseek",
        label="test",
        model="test-model",
        api_key="not-used",
        base_url="https://not-used.invalid",
    )
    manifest = run_baseline_pipeline(
        request,
        runtime=runtime,
        model_client=FakeModel(),
        fetch_pub_id_source=fetch_source,
        retrieve_relations=retrieve_relations,
        retrieve_candidates=lambda *_args, **_kwargs: (
            [candidate],
            {"status": "passed", "provider_errors": []},
        ),
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert {
        key: report["source"][key]
        for key in ("filename", "input_type", "pub_id", "parser")
    } == {
        "filename": f"aminer-{pub_id}.md",
        "input_type": "aminer_pub_id",
        "pub_id": pub_id,
        "parser": "aminer_interface_b_content_list",
    }
    assert report["run_metadata"]["input_source"] == "aminer_interface_b"
    assert report["source"]["provenance"]["structured_content_list_used"] is True
    assert report["run_metadata"]["content_block_count"] == 4
    assert report["source"]["relation_pub_id"] == pub_id
    assert report["run_metadata"]["relation_diagnostics"]["status"] == "completed"
    assert report["source"]["provenance"]["relation_graph_file"] == "relation_graph.json"
    assert report["run_metadata"]["relation_graph_file"] == "relation_graph.json"
    assert (
        report["results"]["baseline_audit"]["retrieval_diagnostics"][
            "relation_graph"
        ]["candidate_record_count"]
        == 8
    )
    retained_candidates = report["run_metadata"]["relation_diagnostics"][
        "candidate_records"
    ]
    assert [item["title"] for item in retained_candidates] == [
        f"Relation Candidate {index + 1}" for index in range(8)
    ]
    assert report["results"]["baseline_audit"]["records"][0]["title"] == "Direct Method"
    assert not {
        item["title"] for item in report["results"]["baseline_audit"]["records"]
    }.intersection(item["title"] for item in relation_candidates)
    run_dir = Path(manifest["report"]).parent
    relation_graph_path = Path(manifest["relation_graph"])
    assert relation_graph_path == run_dir / "relation_graph.json"
    relation_graph = json.loads(relation_graph_path.read_text(encoding="utf-8"))
    assert relation_graph["candidate_records"] == relation_candidates
    assert relation_graph["diagnostics"]["candidate_records"] == relation_candidates
    assert stat.S_IMODE(relation_graph_path.stat().st_mode) == 0o600
    assert not (run_dir / "source.pdf").exists()
    source_parse = json.loads((run_dir / "source_parse.json").read_text(encoding="utf-8"))
    assert source_parse["input_type"] == "aminer_pub_id"
    assert source_parse["provider"] == "aminer_interface_b_content_list"
