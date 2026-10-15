#!/usr/bin/env python3
"""Evaluation submodule — §7.13 5th submodule of the Deep Research Engine.

Wraps the v3 Evidence Ledger's ``analyze()`` into a structured quality report
for a completed (or in-progress) Deep Research run. This is the §7.15 internal
self-check surface (citation completeness / source support / unsourced numbers)
exposed as an eval; cross-skill QC stays with ``research-gate``.

The report groups v3's flat ``analyze()`` signals into evaluation dimensions:

    citation_completeness  — unsupported claims, unsourced numbers, single-source claims
    coverage               — thin sections, sections without claims, uncited sources
    retrieval_quality      — low-yield / drifting probes, untagged / probeless sources
    conflicts              — unresolved disagreements
    spend                  — total CNY vs the hard limit (§7.14)
    overall                — blocking-gate pass/fail + a 0–1 composite score

Stdlib only. Run:
    python evaluate.py --ledger path/to/evidence.json
    python evaluate.py --ledger path/to/evidence.json --out report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import evidence as _ev  # noqa: E402


def evaluate(state: dict) -> dict:
    """Build the quality report from a v3 ledger state."""
    a = _ev.analyze(state)
    totals = a.get("totals", {})
    spend = a.get("spend", {}) or {}

    blocking = {
        "outline_missing": a.get("outline_missing", False),
        "unsupported_claims": a.get("unsupported_claims", []),
        "sections_below_two_sources": a.get("sections_below_two_sources", []),
        "spend_over_hard_limit": a.get("spend_over_hard_limit", False),
    }
    blocking_count = (
        (1 if blocking["outline_missing"] else 0)
        + len(blocking["unsupported_claims"])
        + len(blocking["sections_below_two_sources"])
        + (1 if blocking["spend_over_hard_limit"] else 0)
        + (1 if totals.get("sources", 0) == 0 else 0)
        + (1 if totals.get("claims", 0) == 0 else 0)
    )

    warnings = {
        "subsections_below_two_sources": a.get("subsections_below_two_sources", []),
        "sections_missing_disagreement": a.get("sections_missing_disagreement", []),
        "sections_from_single_probe": a.get("sections_from_single_probe", []),
        "low_yield_probes": a.get("low_yield_probes", []),
        "drifting_probes": a.get("drifting_probes", []),
        "sections_without_claims": a.get("sections_without_claims", []),
        "untagged_sources": a.get("untagged_sources", []),
        "sources_without_probe": a.get("sources_without_probe", []),
        "cited_sources_without_detail": a.get("cited_sources_without_detail", []),
        "cited_sources_without_fulltext": a.get("cited_sources_without_fulltext", []),
        "figure_plans_thin": a.get("figure_plans_thin", []),
        "figure_plans_unfulfilled": a.get("figure_plans_unfulfilled", []),
        "figure_plans_abandoned": a.get("figure_plans_abandoned", []),
        "figure_plans_industry_expected": a.get("figure_plans_industry_expected", False),
        "single_source_claims": a.get("single_source_claims", []),
        "claims_with_unsourced_numbers": a.get("claims_with_unsourced_numbers", []),
        "uncited_sources": a.get("uncited_sources", []),
    }
    warning_count = sum(len(v) for v in warnings.values() if isinstance(v, list))

    conflicts = a.get("unresolved_conflicts", [])

    # ── composite score (0–1) ──
    # Start full; dock for each quality problem. Bounded to [0, 1].
    score = 1.0
    live_sources = totals.get("sources", 0)
    live_claims = totals.get("claims", 0)
    if live_sources > 0:
        score -= 0.15 * (len(warnings["uncited_sources"]) / live_sources)
        score -= 0.10 * (len(warnings["cited_sources_without_detail"]) / max(live_sources, 1))
    if live_claims > 0:
        score -= 0.20 * (len(blocking["unsupported_claims"]) / live_claims)
        score -= 0.10 * (len(warnings["single_source_claims"]) / live_claims)
        score -= 0.10 * (len(warnings["claims_with_unsourced_numbers"]) / live_claims)
    score -= 0.05 * len(warnings["low_yield_probes"])
    score -= 0.05 * len(warnings["drifting_probes"])
    score -= 0.05 * len(conflicts)
    if blocking["spend_over_hard_limit"]:
        score -= 0.20
    score = max(0.0, min(1.0, score))

    return {
        "topic": a.get("topic", state.get("topic", "")),
        "overall": {
            "ok": blocking_count == 0,
            "blocking_count": blocking_count,
            "warning_count": warning_count,
            "score": round(score, 3),
        },
        "totals": totals,
        "blocking": blocking,
        "warnings": warnings,
        "conflicts": conflicts,
        "spend": {
            "total_cny": spend.get("total_cny", 0.0),
            "hard_limit_cny": spend.get("hard_limit_cny", 20.0),
            "over_limit": a.get("spend_over_hard_limit", False),
            "by_api": spend.get("by_api", {}),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate a v3 Deep Research Evidence Ledger (§7.13 evaluation submodule).")
    parser.add_argument("--ledger", required=True, help="Path to v3 evidence ledger JSON")
    parser.add_argument("--out", default=None, help="Write report JSON to this path (default: stdout)")
    args = parser.parse_args()

    state = _ev.load_state(Path(args.ledger))
    if state is None:
        print(f"Could not load ledger: {args.ledger}", file=sys.stderr)
        return 1

    report = evaluate(state)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text + "\n", "utf-8")
        print(f"Wrote {args.out}")
    else:
        print(text)
    return 0 if report["overall"]["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
