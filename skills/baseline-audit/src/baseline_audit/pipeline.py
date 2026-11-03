"""Self-contained application pipeline for one Baseline Audit run."""

from __future__ import annotations

import json
import secrets
import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .aminer import fetch_aminer_source, normalize_pub_id
from .aminer_open import AMINER_SEARCH_TIERS, resolve_title_to_pub_id
from .anchors import (
    anchor_catalog_text,
    assess_input_viability,
    build_anchor_catalog,
    experiment_anchor_catalog,
)
from .audit import run_baseline_audit
from .config import JsonModelClient, ModelRuntime, configured_proxy, resolve_model_runtime
from .errors import BaselineAuditError
from .parsing import extract_local_title, prepare_pdf_source
from .planning import (
    bibliography_context,
    build_baseline_retrieval_plan,
    select_direct_baseline_records,
)
from .relation import retrieve_aminer_relation_candidates
from .retrieval import (
    EXTERNAL_FALLBACK_PROVIDERS,
    RETRIEVAL_PROVIDERS,
    filter_retrieval_records,
    retrieve_baseline_candidates,
)


MAX_PDF_BYTES = 20 * 1024 * 1024
BASELINE_RETRIEVAL_POLICY = (
    "AMiner Open Platform discovery with no external fallback unless explicitly requested"
)
BASELINE_RELATION_RETRIEVAL_POLICY = (
    "AMiner Open Platform discovery plus public backward-reference expansion; "
    "forward citations are unavailable"
)
ProgressCallback = Callable[[str, str, dict[str, Any] | None], None]


def model_usage_snapshot(client: Any) -> dict[str, Any]:
    """Read optional model telemetry without coupling the pipeline to one client."""
    snapshotter = getattr(client, "model_usage_snapshot", None)
    if callable(snapshotter):
        try:
            snapshot = snapshotter()
        except Exception:
            snapshot = None
        if isinstance(snapshot, dict):
            return dict(snapshot)
    return {
        "telemetry_available": False,
        "usage_status": "unavailable",
        "logical_json_call_count": None,
        "request_attempt_count": None,
        "request_count": None,
        "response_count": None,
        "failed_request_count": None,
        "error_count": None,
        "json_retry_count": None,
        "json_parse_error_count": None,
        "responses_with_usage_count": None,
        "responses_without_usage_count": None,
        "usage_reported_request_count": None,
        "usage_missing_request_count": None,
        "usage_incomplete_request_count": None,
        "derived_total_tokens_request_count": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "reasoning_tokens": None,
        "total_tokens": None,
        "reasoning_tokens_reported_response_count": None,
        "request_seconds_sum": None,
        "request_wall_seconds": None,
        "request_active_wall_seconds": None,
        "active_request_count": None,
        "max_concurrent_requests": None,
        "global_gate_enabled": None,
        "global_gate_capacity": None,
        "global_gate_acquisition_count": None,
        "global_gate_waited_acquisition_count": None,
        "global_gate_wait_seconds_sum": None,
        "global_gate_wait_seconds": None,
    }


def utf8_safe(value: Any) -> str:
    return str(value).encode("utf-8", errors="replace").decode("utf-8")


@dataclass(frozen=True)
class AuditRequest:
    pdf: Path | None
    pub_id: str | None
    relation_pub_id: str | None
    review_as_of: str
    model_profile: str
    work_root: Path
    grobid_url: str
    retrieval_provider: str = "aminer"
    external_fallback_provider: str = "none"
    aminer_search_tier: str = "auto"
    aminer_detail_limit: int = 3
    auto_resolve_pub_id: bool = True
    allow_pypdf_fallback: bool = False
    output: Path | None = None
    force: bool = False

    @classmethod
    def from_values(
        cls,
        *,
        pdf: str | None,
        pub_id: str | None = None,
        relation_pub_id: str | None = None,
        review_as_of: str,
        model_profile: str,
        work_root: Path,
        grobid_url: str,
        output: str | None,
        force: bool,
        retrieval_provider: str = "aminer",
        external_fallback_provider: str = "none",
        aminer_search_tier: str = "auto",
        aminer_detail_limit: int = 3,
        auto_resolve_pub_id: bool = True,
        allow_pypdf_fallback: bool = False,
    ) -> "AuditRequest":
        pdf_value = str(pdf or "").strip()
        pub_id_value = str(pub_id or "").strip()
        if bool(pdf_value) == bool(pub_id_value):
            raise BaselineAuditError("Provide exactly one input: --pdf or --pub-id.")
        if pub_id_value and allow_pypdf_fallback:
            raise BaselineAuditError(
                "--allow-pypdf-fallback is valid only with --pdf input."
            )
        path: Path | None = None
        normalized_pub_id: str | None = None
        normalized_relation_pub_id: str | None = None
        if pdf_value:
            path = Path(pdf_value).expanduser().resolve()
            if not path.is_file() or path.suffix.lower() != ".pdf":
                raise BaselineAuditError(f"PDF not found or not a .pdf file: {path}")
            if not 0 < path.stat().st_size <= MAX_PDF_BYTES:
                raise BaselineAuditError("PDF must be non-empty and no larger than 20 MiB.")
        else:
            normalized_pub_id = normalize_pub_id(pub_id_value)
        relation_value = str(relation_pub_id or "").strip()
        if pub_id_value and relation_value:
            raise BaselineAuditError(
                "--relation-pub-id is valid only with --pdf; --pub-id input "
                "automatically reuses its own AMiner identifier."
            )
        if relation_value:
            normalized_relation_pub_id = normalize_pub_id(relation_value)
        elif normalized_pub_id:
            normalized_relation_pub_id = normalized_pub_id
        try:
            cutoff = date.fromisoformat(review_as_of).isoformat()
        except ValueError as exc:
            raise BaselineAuditError("--review-as-of must use YYYY-MM-DD.") from exc
        if not model_profile.strip():
            raise BaselineAuditError("A model profile is required.")
        normalized_provider = retrieval_provider.strip().lower()
        if normalized_provider not in RETRIEVAL_PROVIDERS:
            raise BaselineAuditError(
                f"Retrieval provider must be one of: {', '.join(RETRIEVAL_PROVIDERS)}."
            )
        normalized_fallback = external_fallback_provider.strip().lower()
        if normalized_fallback not in EXTERNAL_FALLBACK_PROVIDERS:
            raise BaselineAuditError(
                "External fallback provider must be one of: "
                f"{', '.join(EXTERNAL_FALLBACK_PROVIDERS)}."
            )
        normalized_tier = aminer_search_tier.strip().lower()
        if normalized_tier not in AMINER_SEARCH_TIERS:
            raise BaselineAuditError(
                f"AMiner search tier must be one of: {', '.join(AMINER_SEARCH_TIERS)}."
            )
        try:
            normalized_detail_limit = int(aminer_detail_limit)
        except (TypeError, ValueError) as exc:
            raise BaselineAuditError("AMiner detail limit must be an integer.") from exc
        if not 0 <= normalized_detail_limit <= 20:
            raise BaselineAuditError(
                "AMiner detail limit must be between 0 and 20."
            )
        return cls(
            pdf=path,
            pub_id=normalized_pub_id,
            relation_pub_id=normalized_relation_pub_id,
            review_as_of=cutoff,
            model_profile=model_profile.strip().lower(),
            work_root=work_root.expanduser().resolve(),
            grobid_url=grobid_url.rstrip("/"),
            retrieval_provider=normalized_provider,
            external_fallback_provider=normalized_fallback,
            aminer_search_tier=normalized_tier,
            aminer_detail_limit=normalized_detail_limit,
            auto_resolve_pub_id=bool(auto_resolve_pub_id),
            allow_pypdf_fallback=bool(allow_pypdf_fallback),
            output=Path(output).expanduser().resolve() if output else None,
            force=force,
        )


def write_json(path: Path, payload: Any, *, force: bool) -> Path:
    normalized = path.expanduser().resolve()
    if normalized.exists() and not force:
        raise BaselineAuditError(
            f"Output already exists; use --force to replace it: {normalized}"
        )
    normalized.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=normalized.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(rendered)
    temporary.chmod(0o600)
    temporary.replace(normalized)
    normalized.chmod(0o600)
    return normalized


def run_baseline_pipeline(
    request: AuditRequest,
    *,
    progress: ProgressCallback | None = None,
    runtime: ModelRuntime | None = None,
    model_client: Any | None = None,
    parse_source: Callable[..., dict[str, Any]] | None = None,
    fetch_pub_id_source: Callable[..., dict[str, Any]] | None = None,
    resolve_pub_id: Callable[..., tuple[str | None, dict[str, Any]]] | None = None,
    retrieve_candidates: Callable[..., tuple[list[dict[str, str]], dict[str, Any]]] | None = None,
    retrieve_relations: Callable[..., tuple[list[dict[str, Any]], dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Run parsing, planning, retrieval, local comparison and report generation."""
    pipeline_started_at = datetime.now(timezone.utc)
    pipeline_started_monotonic = time.monotonic()
    resolved_runtime = runtime or resolve_model_runtime(request.model_profile)
    client = model_client or JsonModelClient(resolved_runtime)
    owns_client = model_client is None
    parser = parse_source or prepare_pdf_source
    pub_id_fetcher = fetch_pub_id_source or fetch_aminer_source
    pub_id_resolver = resolve_pub_id or resolve_title_to_pub_id
    retriever = retrieve_candidates or retrieve_baseline_candidates
    relation_retriever = retrieve_relations or retrieve_aminer_relation_candidates

    request.work_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    request.work_root.chmod(0o700)
    runs_dir = request.work_root / "runs"
    runs_dir.mkdir(mode=0o700, exist_ok=True)
    runs_dir.chmod(0o700)
    run_id = secrets.token_hex(6)
    run_dir = runs_dir / run_id
    run_dir.mkdir(mode=0o700)
    local_pdf: Path | None = None
    if request.pdf is not None:
        local_pdf = run_dir / "source.pdf"
        shutil.copyfile(request.pdf, local_pdf)
        local_pdf.chmod(0o600)

    def emit(phase: str, message: str, metrics: dict[str, Any] | None = None) -> None:
        if progress:
            progress(phase, message, metrics)

    try:
        emit("parsing", "Preparing the manuscript for the Baseline Audit.")
        if local_pdf is not None:
            parsed = parser(
                local_pdf,
                run_dir,
                grobid_url=request.grobid_url,
                allow_pypdf_fallback=request.allow_pypdf_fallback,
                progress=progress,
            )
        else:
            parsed = pub_id_fetcher(
                request.pub_id or "",
                run_dir,
                proxy=configured_proxy(),
                progress=progress,
            )
        manifest = (
            dict(parsed.get("manifest"))
            if isinstance(parsed.get("manifest"), dict)
            else {}
        )
        input_source = (
            "uploaded_pdf" if request.pdf is not None else "aminer_interface_b"
        )
        raw_bibliography_entries = parsed.get("bibliography_entries")
        bibliography_entries = (
            [dict(item) for item in raw_bibliography_entries if isinstance(item, dict)]
            if isinstance(raw_bibliography_entries, list)
            else []
        )
        raw_citation_contexts = parsed.get("citation_contexts")
        citation_contexts = (
            [dict(item) for item in raw_citation_contexts if isinstance(item, dict)]
            if isinstance(raw_citation_contexts, list)
            else []
        )
        bibliography_evidence_path: Path | None = None
        if bibliography_entries or citation_contexts:
            bibliography_evidence_path = write_json(
                run_dir / "bibliography_evidence.json",
                {
                    "schema_version": "0.2",
                    "source": "grobid_tei_back_and_inline_bibr_refs",
                    "bibliography_entries": bibliography_entries,
                    "citation_contexts": citation_contexts,
                },
                force=True,
            )
        source_parse_path = write_json(
            run_dir / "source_parse.json",
            {
                "input_type": (
                    "pdf" if request.pdf is not None else "aminer_pub_id"
                ),
                "pub_id": request.pub_id,
                "input_source": input_source,
                "provider": parsed.get("provider"),
                "local_title": parsed.get("local_title"),
                "local_authors": list(parsed.get("local_authors") or []),
                "local_publication_year": parsed.get("local_publication_year"),
                "fallback_used": bool(parsed.get("fallback_used")),
                "pypdf_fallback_authorized": (
                    request.allow_pypdf_fallback
                    if request.pdf is not None
                    else None
                ),
                "grobid_tei_file": parsed.get("grobid_tei_file"),
                "bibliography_evidence_file": (
                    bibliography_evidence_path.name
                    if bibliography_evidence_path is not None
                    else None
                ),
                "bibliography_entry_count": len(bibliography_entries),
                "inline_citation_context_count": len(citation_contexts),
                "aminer_source_manifest_file": (
                    "source_manifest.json" if manifest else None
                ),
                "aminer_structured_fallback_used": (
                    bool(manifest.get("structured_fallback_used"))
                    if manifest
                    else None
                ),
                "aminer_structured_fallback_reason": manifest.get(
                    "structured_fallback_reason"
                ),
                "diagnostics": list(parsed.get("diagnostics") or []),
            },
            force=True,
        )
        pages = [utf8_safe(page) for page in parsed.get("pages", [])]
        markdown = utf8_safe(parsed.get("markdown") or "")
        raw_locations = parsed.get("source_locations")
        source_locations = (
            [dict(item) for item in raw_locations if isinstance(item, dict)]
            if isinstance(raw_locations, list)
            else []
        )
        full_catalog = build_anchor_catalog(
            pages, source_locations=source_locations
        )
        diagnostic = assess_input_viability(
            pages, anchor_count=len(full_catalog)
        )
        first_location = next(
            (item for item in source_locations if isinstance(item, dict)), {}
        )
        if first_location:
            location_unit = str(
                first_location.get("location_unit") or "grobid_tei_block"
            )
            has_physical_pages = isinstance(
                first_location.get("physical_page"), int
            )
            diagnostic.update(
                {
                    "location_granularity": (
                        "physical_page_section_block_sentence"
                        if has_physical_pages
                        else "section_block_sentence"
                    ),
                    "location_numbering": first_location.get(
                        "location_numbering", "physical_page_and_section_block"
                    ),
                    "location_unit": location_unit,
                    "source_unit_count": len(pages),
                    "physical_page_count": len(pages) if has_physical_pages else None,
                    "logical_text_chunks": None if has_physical_pages else len(pages),
                    "input_source": input_source,
                    "parser": str(parsed.get("provider") or "local_pypdf"),
                }
            )
        diagnostic["input_source"] = input_source
        diagnostic["parser"] = str(parsed.get("provider") or "local_pypdf")
        if not diagnostic.get("reviewable"):
            raise BaselineAuditError(
                "The manuscript text is not sufficiently reviewable for this audit."
            )
        local_title = str(parsed.get("local_title") or "").strip() or extract_local_title(pages)
        local_authors = [
            str(value)
            for value in parsed.get("local_authors") or []
            if str(value).strip()
        ]
        try:
            local_publication_year = int(parsed.get("local_publication_year"))
        except (TypeError, ValueError):
            local_publication_year = None
        effective_relation_pub_id = request.relation_pub_id
        if request.pub_id:
            pub_id_resolution: dict[str, Any] = {
                "enabled": False,
                "status": "input_pub_id",
                "matched_pub_id": request.pub_id,
            }
        elif request.relation_pub_id:
            pub_id_resolution = {
                "enabled": False,
                "status": "explicit_relation_pub_id",
                "matched_pub_id": request.relation_pub_id,
            }
        elif request.auto_resolve_pub_id:
            emit(
                "baseline_audit",
                "Safely resolving the PDF title to an AMiner publication ID.",
                {"title_detected": bool(local_title)},
            )
            try:
                effective_relation_pub_id, pub_id_resolution = pub_id_resolver(
                    local_title,
                    authors=local_authors,
                    publication_year=local_publication_year,
                    review_as_of=request.review_as_of,
                    proxy=configured_proxy(),
                )
            except Exception as exc:
                effective_relation_pub_id = None
                pub_id_resolution = {
                    "enabled": True,
                    "status": "failed",
                    "matched_pub_id": None,
                    "provider_errors": [
                        f"Unexpected title-resolution failure: {type(exc).__name__}"
                    ],
                }
        else:
            pub_id_resolution = {
                "enabled": False,
                "status": "disabled",
                "matched_pub_id": None,
            }
        experiment_catalog = experiment_anchor_catalog(pages, source_locations)
        experiment_evidence = anchor_catalog_text(experiment_catalog)

        relation_candidates: list[dict[str, Any]] = []
        relation_graph_path: Path | None = None
        relation_diagnostics: dict[str, Any] = {
            "enabled": False,
            "status": "not_requested",
            "target_pub_id": None,
            "candidate_record_count": 0,
            "provider_errors": [],
            "relation_get_count": 0,
            "relation_get_completed_count": 0,
            "paper_info_post_count": 0,
            "paper_info_post_completed_count": 0,
            "total_http_request_count": 0,
        }
        if effective_relation_pub_id:
            emit(
                "baseline_audit",
                "Expanding AMiner backward references through the public API.",
                {"relation_pub_id": effective_relation_pub_id},
            )
            try:
                relation_candidates, relation_diagnostics = relation_retriever(
                    effective_relation_pub_id,
                    review_as_of=request.review_as_of,
                    proxy=configured_proxy(),
                )
            except Exception as exc:
                relation_candidates = []
                relation_diagnostics = {
                    "enabled": True,
                    "status": "failed",
                    "target_pub_id": effective_relation_pub_id,
                    "candidate_record_count": 0,
                    "relation_get_count": 0,
                    "relation_get_completed_count": 0,
                    "paper_info_post_count": 0,
                    "paper_info_post_completed_count": 0,
                    "total_http_request_count": 0,
                    "provider_errors": [
                        f"Unexpected citation-graph failure: {type(exc).__name__}"
                    ],
                }
            relation_candidates = [
                dict(candidate)
                for candidate in relation_candidates
                if isinstance(candidate, dict)
            ]
            relation_diagnostics = dict(relation_diagnostics)
            relation_diagnostics["candidate_record_count"] = len(
                relation_candidates
            )
            relation_diagnostics["candidate_records"] = relation_candidates
            relation_graph_path = write_json(
                run_dir / "relation_graph.json",
                {
                    "schema_version": "0.1",
                    "provider": "AMiner Open Platform paper_relation + paper_info",
                    "direction_scope": "backward_references_only",
                    "target_pub_id": effective_relation_pub_id,
                    "review_as_of": request.review_as_of,
                    "status": relation_diagnostics.get("status"),
                    "diagnostics": relation_diagnostics,
                    "candidate_records": relation_candidates,
                },
                force=True,
            )
            emit(
                "baseline_audit",
                "AMiner backward-reference expansion finished.",
                {
                    "status": relation_diagnostics.get("status"),
                    "relation_candidates": len(relation_candidates),
                },
            )

        emit(
            "baseline_audit",
            "Generating evidence-grounded direct-baseline queries.",
            {"experiment_anchor_count": len(experiment_catalog)},
        )
        retrieval_plan = build_baseline_retrieval_plan(
            markdown,
            experiment_evidence=experiment_evidence,
            bibliography_evidence=bibliography_context(markdown),
            bibliography_entries=(
                bibliography_entries if bibliography_entries else None
            ),
            citation_contexts=citation_contexts,
            review_as_of=request.review_as_of,
            llm_json=client.json,
        )
        raw_queries = retrieval_plan.get("queries")
        queries = (
            [str(query) for query in raw_queries if str(query).strip()]
            if isinstance(raw_queries, list)
            else []
        )
        raw_cited_not_compared = retrieval_plan.get("cited_not_compared")
        has_cited_not_compared = bool(
            isinstance(raw_cited_not_compared, list)
            and any(
                isinstance(item, dict) and str(item.get("title") or "").strip()
                for item in raw_cited_not_compared
            )
        )
        emit(
            "baseline_audit",
            "Retrieving direct-baseline candidates.",
            {"baseline_queries_generated": len(queries)},
        )
        if queries or relation_candidates or has_cited_not_compared:
            retrieval_arguments: dict[str, Any] = {
                "local_title": local_title,
                "review_as_of": request.review_as_of,
                "retrieval_plan": retrieval_plan,
                "proxy": configured_proxy(),
                "provider": request.retrieval_provider,
                "external_fallback_provider": request.external_fallback_provider,
                "aminer_search_tier": request.aminer_search_tier,
                "aminer_detail_limit": request.aminer_detail_limit,
                "select_direct": lambda records, **kwargs: select_direct_baseline_records(
                    records,
                    **kwargs,
                    llm_json=client.json,
                ),
            }
            if effective_relation_pub_id:
                retrieval_arguments["seed_records"] = relation_candidates
            candidates, retrieval_diagnostics = retriever(
                queries,
                **retrieval_arguments,
            )
        else:
            candidates, retrieval_diagnostics = filter_retrieval_records(
                [],
                local_title=local_title,
                review_as_of=request.review_as_of,
            )
        if effective_relation_pub_id:
            retrieval_diagnostics["relation_graph"] = relation_diagnostics
        emit(
            "baseline_audit",
            "Classifying candidate coverage from local experiment evidence.",
            {
                "baseline_candidates_retrieved": len(candidates),
                "retrieval_status": retrieval_diagnostics.get("status"),
            },
        )
        audit = run_baseline_audit(
            baseline_candidates=candidates,
            pages=pages,
            source_locations=source_locations,
            local_title=local_title,
            retrieval_plan=retrieval_plan,
            retrieval_queries=queries,
            retrieval_diagnostics=retrieval_diagnostics,
            llm_json=client.json,
        )
        audit["review_as_of"] = request.review_as_of
        audit["retrieval_policy"] = (
            BASELINE_RELATION_RETRIEVAL_POLICY
            if effective_relation_pub_id
            else BASELINE_RETRIEVAL_POLICY
        )
        if effective_relation_pub_id:
            audit["relation_status"] = relation_diagnostics.get("status")
        report_status = "completed" if audit.get("status") == "completed" else "partial"
        provider = str(parsed.get("provider") or "local_pypdf")
        pipeline_finished_at = datetime.now(timezone.utc)
        usage = model_usage_snapshot(client)
        model_request_seconds_sum = usage.get("request_seconds_sum")
        if model_request_seconds_sum is None:
            model_request_seconds_sum = usage.get("request_wall_seconds")
        model_request_active_wall_seconds = usage.get(
            "request_active_wall_seconds"
        )
        if model_request_active_wall_seconds is None:
            # Backward-compatible custom clients expose only the v0.4.9
            # additive field. In a serial client, sum and active wall agree.
            model_request_active_wall_seconds = usage.get("request_wall_seconds")
        pipeline_timing = {
            "started_at": pipeline_started_at.isoformat(),
            "finished_at": pipeline_finished_at.isoformat(),
            "wall_seconds": round(
                max(0.0, time.monotonic() - pipeline_started_monotonic),
                6,
            ),
            "model_request_wall_seconds": model_request_active_wall_seconds,
            "model_request_seconds_sum": model_request_seconds_sum,
            "global_gate_wait_seconds_sum": usage.get(
                "global_gate_wait_seconds_sum"
            ),
        }
        report = {
            "schema_version": "1.0",
            "kind": "focused_paper_audit",
            "run_id": run_id,
            "capability": "baseline",
            "capability_description": (
                "Retrieve plausible direct baselines and check visible experimental comparisons."
            ),
            "status": report_status,
            "source": {
                "filename": (
                    request.pdf.name
                    if request.pdf is not None
                    else f"aminer-{request.pub_id}.md"
                ),
                "input_type": "pdf" if request.pdf is not None else "aminer_pub_id",
                "pub_id": request.pub_id,
                "parser": provider,
                "provenance": {
                    "input_source": input_source,
                    "source_provider": provider,
                    "retrieval_interface": manifest.get("retrieval_interface"),
                    "structured_content_list_used": bool(
                        manifest.get("content_list_file")
                    ),
                    "pypdf_fallback_authorized": (
                        request.allow_pypdf_fallback
                        if request.pdf is not None
                        else None
                    ),
                    "pypdf_fallback_used": (
                        bool(parsed.get("fallback_used"))
                        if request.pdf is not None
                        else None
                    ),
                    "source_parse_file": source_parse_path.name,
                    "bibliography_evidence_file": (
                        bibliography_evidence_path.name
                        if bibliography_evidence_path is not None
                        else None
                    ),
                },
            },
            "run_metadata": {
                "model_profile": resolved_runtime.profile,
                "model_requested": resolved_runtime.model,
                "review_as_of": request.review_as_of,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "pages_or_chunks": len(pages),
                "work_dir": str(run_dir),
                "source_parse_file": source_parse_path.name,
                "input_source": input_source,
                "parser": provider,
                "grobid_tei_file": parsed.get("grobid_tei_file"),
                "bibliography_evidence_file": (
                    bibliography_evidence_path.name
                    if bibliography_evidence_path is not None
                    else None
                ),
                "bibliography_entry_count": len(bibliography_entries),
                "inline_citation_context_count": len(citation_contexts),
                "grobid_required": (
                    request.pdf is not None and not request.allow_pypdf_fallback
                ),
                "pypdf_fallback_authorized": (
                    request.allow_pypdf_fallback
                    if request.pdf is not None
                    else None
                ),
                "grobid_fallback_used": (
                    bool(parsed.get("fallback_used"))
                    if request.pdf is not None
                    else None
                ),
                "source_manifest_file": (
                    "source_manifest.json" if manifest else None
                ),
                "source_provider": (
                    manifest.get("source_provider") or provider
                ),
                "physical_page_count": (
                    manifest.get("physical_page_count")
                    if manifest
                    else len(pages)
                ),
                "logical_text_chunks": (
                    manifest.get("logical_text_chunks") if manifest else None
                ),
                "content_block_count": (
                    manifest.get("content_block_count", 0)
                ),
                "content_block_type_counts": (
                    manifest.get("content_block_type_counts", {})
                ),
                "page_coordinate_count": (
                    manifest.get("page_coordinate_count", 0)
                ),
                "explicit_page_coordinate_count": (
                    manifest.get("explicit_page_coordinate_count", 0)
                ),
                "inherited_page_block_count": (
                    manifest.get("inherited_page_block_count", 0)
                ),
                "aminer_structured_fallback_used": (
                    bool(manifest.get("structured_fallback_used"))
                    if manifest
                    else False
                ),
                "aminer_structured_fallback_reason": manifest.get(
                    "structured_fallback_reason"
                ),
                "structured_block_count": sum(
                    len(location.get("blocks") or [])
                    for location in source_locations
                ),
                "parse_diagnostics": list(parsed.get("diagnostics") or []),
                "retrieval_provider": request.retrieval_provider,
                "external_fallback_provider": request.external_fallback_provider,
                "aminer_search_tier": request.aminer_search_tier,
                "aminer_detail_limit": request.aminer_detail_limit,
                "pub_id_resolution": pub_id_resolution,
                "model_usage": usage,
                "timing": pipeline_timing,
            },
            "input_diagnostic": diagnostic,
            "results": {"baseline_audit": audit},
        }
        report["source"]["provenance"]["pub_id_resolution"] = pub_id_resolution
        if effective_relation_pub_id:
            report["source"]["relation_pub_id"] = effective_relation_pub_id
            report["source"]["provenance"]["relation_graph_file"] = (
                relation_graph_path.name if relation_graph_path else None
            )
            report["run_metadata"]["relation_pub_id"] = effective_relation_pub_id
            report["run_metadata"]["relation_diagnostics"] = relation_diagnostics
            report["run_metadata"]["relation_graph_file"] = (
                relation_graph_path.name if relation_graph_path else None
            )
        report_path = write_json(
            run_dir / "capability-report.json", report, force=True
        )
        if request.output:
            write_json(request.output, report, force=request.force)
        emit("finalizing", "Baseline Audit report is ready.", {"status": report_status})
        result = {
            "run_id": run_id,
            "mode": "standalone-baseline",
            "capability": "baseline",
            "status": report_status,
            "report": str(report_path),
            "requested_output": str(request.output) if request.output else None,
            "result_statuses": {"baseline_audit": str(audit.get("status") or "unknown")},
            "work_root": str(request.work_root),
        }
        if relation_graph_path:
            result["relation_graph"] = str(relation_graph_path)
        return result
    finally:
        if owns_client:
            client.close()
