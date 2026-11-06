"""Command-line interface for the standalone Baseline Finder."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import APIError

from . import __version__
from .aminer_open import AMINER_SEARCH_TIERS
from .config import MODEL_PROFILES, load_env_file
from .errors import BaselineAuditError
from .pipeline import AuditRequest, run_baseline_pipeline
from .retrieval import EXTERNAL_FALLBACK_PROVIDERS, RETRIEVAL_PROVIDERS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="baseline-finder",
        description=(
            "Audit a local PDF or AMiner pub_id for plausible direct experimental "
            "baselines found through time-bounded scholarly search and optional "
            "AMiner backward-reference expansion."
        )
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--pdf", help="Absolute or relative path to a local PDF")
    source.add_argument(
        "--pub-id",
        help="24-character hexadecimal AMiner publication identifier",
    )
    parser.add_argument(
        "--relation-pub-id",
        help=(
            "PDF-only optional 24-character AMiner ID for citation-graph expansion; "
            "--pub-id mode automatically uses its input ID. PDF mode otherwise "
            "attempts a strict title + author/year match."
        ),
    )
    parser.add_argument(
        "--retrieval-provider",
        choices=RETRIEVAL_PROVIDERS,
        default=None,
        help="Paper discovery provider (default: AMiner Open Platform)",
    )
    parser.add_argument(
        "--external-fallback-provider",
        choices=EXTERNAL_FALLBACK_PROVIDERS,
        default=None,
        help=(
            "Explicit external fallback after an empty primary result; default none. "
            "AMiner never silently falls back to arXiv/OpenAlex."
        ),
    )
    parser.add_argument(
        "--aminer-search-tier",
        choices=AMINER_SEARCH_TIERS,
        default=None,
        help=(
            "AMiner search tier: auto routes exact titles to free search, fielded "
            "phrases to Search Pro, and natural-language requests to legacy QA; "
            "qa-pro explicitly probes QA Pro and visibly downgrades inside AMiner"
        ),
    )
    parser.add_argument(
        "--aminer-detail-limit",
        type=int,
        choices=range(0, 21),
        default=None,
        metavar="0..20",
        help=(
            "Maximum records per query still missing abstracts after paper_info "
            "to enrich with one paid paper_detail_batch call, CNY 0.01 per returned "
            "paper (default: 3; use 0 to disable)"
        ),
    )
    parser.add_argument(
        "--no-auto-resolve-pub-id",
        action="store_true",
        help="Disable strict PDF title + author/year AMiner ID resolution",
    )
    parser.add_argument(
        "--review-as-of",
        default=datetime.now(timezone.utc).date().isoformat(),
        help="Retrieval cutoff in YYYY-MM-DD form (default: today UTC)",
    )
    parser.add_argument(
        "--model-profile",
        default="deepseek",
        choices=MODEL_PROFILES,
    )
    parser.add_argument(
        "--env-file",
        action="append",
        help="Optional KEY=VALUE file; may be repeated",
    )
    parser.add_argument(
        "--work-dir",
        help="Private run root; defaults to BASELINE_AUDIT_WORK_DIR",
    )
    parser.add_argument(
        "--grobid-url",
        help="GROBID service URL; defaults to GROBID_URL or http://127.0.0.1:8070",
    )
    parser.add_argument(
        "--allow-pypdf-fallback",
        action="store_true",
        help=(
            "Allow a visibly reported lower-quality pypdf parse when GROBID fails; "
            "PDF runs otherwise require GROBID"
        ),
    )
    parser.add_argument("--output", help="Optional copy of the full report JSON")
    parser.add_argument("--force", action="store_true", help="Replace --output if it exists")
    return parser


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        for env_file in args.env_file or []:
            load_env_file(Path(env_file))
        work_value = (
            args.work_dir
            or os.environ.get("BASELINE_AUDIT_WORK_DIR")
        )
        work_root = (
            Path(work_value).expanduser()
            if work_value
            else Path.home() / ".local" / "share" / "baseline-finder"
        )
        grobid_url = (
            args.grobid_url
            or os.environ.get("GROBID_URL")
            or "http://127.0.0.1:8070"
        )
        request = AuditRequest.from_values(
            pdf=args.pdf,
            pub_id=args.pub_id,
            relation_pub_id=args.relation_pub_id,
            review_as_of=args.review_as_of,
            model_profile=args.model_profile,
            work_root=work_root,
            grobid_url=grobid_url,
            retrieval_provider=(
                args.retrieval_provider
                or os.environ.get("BASELINE_RETRIEVAL_PROVIDER")
                or "aminer"
            ),
            external_fallback_provider=(
                args.external_fallback_provider
                or os.environ.get("BASELINE_EXTERNAL_FALLBACK_PROVIDER")
                or "none"
            ),
            aminer_search_tier=(
                args.aminer_search_tier
                or os.environ.get("BASELINE_AMINER_SEARCH_TIER")
                or "auto"
            ),
            aminer_detail_limit=(
                args.aminer_detail_limit
                if args.aminer_detail_limit is not None
                else int(os.environ.get("BASELINE_AMINER_DETAIL_LIMIT") or "3")
            ),
            auto_resolve_pub_id=not args.no_auto_resolve_pub_id,
            output=args.output,
            force=args.force,
            allow_pypdf_fallback=args.allow_pypdf_fallback,
        )

        def progress(
            phase: str, message: str, metrics: dict[str, Any] | None = None
        ) -> None:
            metric_text = f" {json.dumps(metrics, ensure_ascii=False)}" if metrics else ""
            print(f"[{phase}] {message}{metric_text}", file=sys.stderr, flush=True)

        _print_json(run_baseline_pipeline(request, progress=progress))
        return 0
    except (
        BaselineAuditError,
        OSError,
        ValueError,
        json.JSONDecodeError,
        APIError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
