#!/usr/bin/env python3
"""Cross-round paper-set state file for aminer-deep-search (no network access).

Hundreds of collected papers do not fit in the host model's context, so this
CLI keeps them in a JSON state file. Deduplication is three-way: AMiner paper
ID, lowercased DOI, and normalized title (preprint and published versions of
the same paper merge into one record, preferring the published venue).

Subcommands (stdout is always a single JSON document):
  init           record hard constraints (year range, required fields) for `add` to enforce
  add            merge papers from stdin (JSON array) or --ids into the state file
  promote        move papers to the curated tier
  mark-expanded  record seed IDs whose references were expanded
  log-round      append one round's structured trace record
  stats          totals, tiers, field completeness, year distribution
  export         write the full candidate list (all stored fields) and report path + count
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

DEFAULT_STATE_FILE = "outputs/paper_set.json"
TITLE_KEY_MIN_LEN = 16  # don't title-dedupe on very short titles
PAPER_URL_TEMPLATE = "https://www.aminer.cn/pub/{}"
PREPRINT_MARKERS = ("arxiv", "biorxiv", "medrxiv", "ssrn", "preprint", "corr")
VALID_TIERS = ("candidate", "curated")


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"papers": {}, "expanded_seeds": [], "constraints": {}, "rounds": []}
    with path.open("r", encoding="utf-8") as file:
        state = json.load(file)
    state.setdefault("papers", {})
    state.setdefault("expanded_seeds", [])
    state.setdefault("constraints", {})
    state.setdefault("rounds", [])
    return state


def _save_state(path: Path, state: dict[str, Any]) -> None:
    # Write-then-rename so a crash mid-write can never corrupt the state file:
    # hundreds of collected papers (and their API cost) live in it.
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _normalize_items(raw_items: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_items, list):
        raise ValueError("input must be a JSON array of papers")
    items: list[dict[str, Any]] = []
    for raw in raw_items:
        if isinstance(raw, str):
            items.append({"id": raw.strip()})
        elif isinstance(raw, dict):
            items.append(raw)
    return items


def _norm_title(title: Any) -> str:
    """Case/punctuation/whitespace-insensitive title key for cross-version dedup."""
    return "".join(ch for ch in str(title or "").lower() if ch.isalnum())


def _norm_doi(doi: Any) -> str:
    return str(doi or "").strip().lower()


def _is_preprint_venue(venue: Any) -> bool:
    text = str(venue or "").lower()
    return any(marker in text for marker in PREPRINT_MARKERS)


def _build_indexes(papers: dict[str, dict[str, Any]]) -> tuple[dict[str, str], dict[str, str]]:
    """Rebuild doi->id and normalized-title->id indexes from the stored papers."""
    doi_index: dict[str, str] = {}
    title_index: dict[str, str] = {}
    for paper_id, paper in papers.items():
        doi = _norm_doi(paper.get("doi"))
        if doi:
            doi_index.setdefault(doi, paper_id)
        title_key = _norm_title(paper.get("title"))
        if len(title_key) >= TITLE_KEY_MIN_LEN:
            title_index.setdefault(title_key, paper_id)
    return doi_index, title_index


def _check_constraints(item: dict[str, Any], constraints: dict[str, Any]) -> str | None:
    """Return a rejection reason, or None if the item passes all hard constraints."""
    for field in constraints.get("require_fields") or []:
        if item.get(field) in (None, "", []):
            return f"missing_{field}"
    year = item.get("year")
    if year:
        year = int(year)
        year_from = constraints.get("year_from")
        year_to = constraints.get("year_to")
        if (year_from and year < int(year_from)) or (year_to and year > int(year_to)):
            return "year_out_of_range"
    return None


def _merge_into(existing: dict[str, Any], item: dict[str, Any]) -> None:
    """Merge a duplicate/alternate version into the stored record."""
    incoming_id = str(item.get("id") or item.get("_id") or "").strip()
    if incoming_id and incoming_id != existing.get("id"):
        alt_ids = existing.setdefault("alt_ids", [])
        if incoming_id not in alt_ids:
            alt_ids.append(incoming_id)
    # Prefer the published version: if the stored record points at a preprint
    # venue and the incoming one doesn't, take the incoming venue/year/doi.
    if (_is_preprint_venue(existing.get("venue"))
            and item.get("venue") and not _is_preprint_venue(item.get("venue"))):
        for key in ("venue", "year", "doi", "n_citation_bucket"):
            if item.get(key) not in (None, "", []):
                existing[key] = item[key]
    for key, value in item.items():
        if key in ("source_paper_ids", "id", "found_by") and key in existing:
            continue
        if value not in (None, "", []):
            existing.setdefault(key, value)


def _record_sources(record: dict[str, Any], item: dict[str, Any], source: str | None) -> None:
    found_by = record.setdefault("found_by", [])
    entries = []
    if source:
        entries.append(source)
    entries.extend(f"references:{seed}" for seed in item.get("source_paper_ids") or [])
    for entry in entries:
        if entry not in found_by:
            found_by.append(entry)


def cmd_init(args: argparse.Namespace) -> dict[str, Any]:
    state_path = Path(args.file)
    state = _load_state(state_path)
    constraints: dict[str, Any] = {}
    if args.topic:
        constraints["topic"] = args.topic
    if args.year_from:
        constraints["year_from"] = args.year_from
    if args.year_to:
        constraints["year_to"] = args.year_to
    if args.require_fields:
        fields = [f.strip() for f in args.require_fields.split(",") if f.strip()]
        if fields:
            constraints["require_fields"] = fields
    state["constraints"] = constraints
    _save_state(state_path, state)
    return {"constraints": constraints, "total": len(state["papers"])}


def cmd_add(args: argparse.Namespace) -> dict[str, Any]:
    if args.ids:
        items = [{"id": paper_id} for paper_id in args.ids]
    else:
        stdin_text = sys.stdin.read().strip()
        if not stdin_text:
            raise ValueError("no input: pipe a JSON array to stdin or pass --ids")
        items = _normalize_items(json.loads(stdin_text))

    state_path = Path(args.file)
    state = _load_state(state_path)
    papers: dict[str, dict[str, Any]] = state["papers"]
    expanded: set[str] = set(state["expanded_seeds"])
    constraints: dict[str, Any] = state["constraints"]
    doi_index, title_index = _build_indexes(papers)

    added = 0
    duplicates = 0
    merged = 0
    rejected = 0
    reject_reasons: dict[str, int] = {}
    for item in items:
        paper_id = str(item.get("id") or item.get("_id") or "").strip()
        if not paper_id:
            continue
        # source_paper_ids on an item means those seeds have been expanded
        for seed_id in item.get("source_paper_ids") or []:
            expanded.add(str(seed_id))

        existing_id: str | None = None
        via_alt_key = False
        if paper_id in papers:
            existing_id = paper_id
        else:
            doi = _norm_doi(item.get("doi"))
            title_key = _norm_title(item.get("title"))
            if doi and doi in doi_index:
                existing_id, via_alt_key = doi_index[doi], True
            elif len(title_key) >= TITLE_KEY_MIN_LEN and title_key in title_index:
                existing_id, via_alt_key = title_index[title_key], True

        if existing_id:
            record = papers[existing_id]
            _merge_into(record, item)
            _record_sources(record, item, args.source)
            if via_alt_key:
                merged += 1
            else:
                duplicates += 1
            continue

        reason = _check_constraints(item, constraints)
        if reason:
            rejected += 1
            reject_reasons[reason] = reject_reasons.get(reason, 0) + 1
            continue

        record = {
            key: value for key, value in item.items()
            if key != "source_paper_ids" and value not in (None, "", [])
        }
        record.setdefault("url", PAPER_URL_TEMPLATE.format(paper_id))
        record.setdefault("tier", "candidate")
        _record_sources(record, item, args.source)
        papers[paper_id] = record
        doi = _norm_doi(record.get("doi"))
        if doi:
            doi_index.setdefault(doi, paper_id)
        title_key = _norm_title(record.get("title"))
        if len(title_key) >= TITLE_KEY_MIN_LEN:
            title_index.setdefault(title_key, paper_id)
        added += 1

    state["expanded_seeds"] = sorted(expanded)
    _save_state(state_path, state)
    result: dict[str, Any] = {
        "added": added,
        "duplicates": duplicates,
        "merged_versions": merged,
        "rejected": rejected,
        "total": len(papers),
    }
    if reject_reasons:
        result["reject_reasons"] = reject_reasons
    return result


def cmd_promote(args: argparse.Namespace) -> dict[str, Any]:
    state_path = Path(args.file)
    state = _load_state(state_path)
    papers = state["papers"]
    promoted = 0
    missing: list[str] = []
    for raw_id in args.ids:
        paper_id = str(raw_id).strip()
        if paper_id in papers:
            papers[paper_id]["tier"] = "curated"
            promoted += 1
        elif paper_id:
            missing.append(paper_id)
    _save_state(state_path, state)
    result: dict[str, Any] = {"promoted": promoted,
                              "curated_total": sum(1 for p in papers.values()
                                                   if p.get("tier") == "curated")}
    if missing:
        result["missing_ids"] = missing
    return result


def cmd_mark_expanded(args: argparse.Namespace) -> dict[str, Any]:
    state_path = Path(args.file)
    state = _load_state(state_path)
    expanded = set(state["expanded_seeds"])
    expanded.update(str(paper_id).strip() for paper_id in args.ids if str(paper_id).strip())
    state["expanded_seeds"] = sorted(expanded)
    _save_state(state_path, state)
    return {"expanded_seeds": state["expanded_seeds"]}


def cmd_log_round(args: argparse.Namespace) -> dict[str, Any]:
    state_path = Path(args.file)
    state = _load_state(state_path)
    record: dict[str, Any] = {
        "round": len(state["rounds"]) + 1,
        "total_after": len(state["papers"]),
    }
    if args.queries:
        record["queries"] = args.queries
    for key in ("added", "rejected", "duplicates", "merged"):
        value = getattr(args, key)
        if value is not None:
            record[key] = value
    if args.note:
        record["note"] = args.note
    state["rounds"].append(record)
    _save_state(state_path, state)
    return record


def cmd_stats(args: argparse.Namespace) -> dict[str, Any]:
    state = _load_state(Path(args.file))
    papers = state["papers"]
    by_year: dict[str, int] = {}
    tiers: dict[str, int] = {}
    missing = {"title": 0, "year": 0, "doi": 0, "abstract": 0, "authors": 0, "venue": 0}
    field_of = {"title": "title", "year": "year", "doi": "doi",
                "abstract": "abstract_slice", "authors": "authors", "venue": "venue"}
    for paper in papers.values():
        year = paper.get("year")
        key = str(year) if year else "unknown"
        by_year[key] = by_year.get(key, 0) + 1
        tier = paper.get("tier") or "candidate"
        tiers[tier] = tiers.get(tier, 0) + 1
        for label, field in field_of.items():
            if paper.get(field) in (None, "", []):
                missing[label] += 1
    return {
        "total": len(papers),
        "tiers": tiers,
        "constraints": state["constraints"],
        "rounds_logged": len(state["rounds"]),
        "expanded_seeds": state["expanded_seeds"],
        "field_completeness": {f"missing_{label}": count for label, count in missing.items()},
        "by_year": dict(sorted(by_year.items(), reverse=True)),
    }


def cmd_export(args: argparse.Namespace) -> dict[str, Any]:
    state = _load_state(Path(args.file))
    papers = [
        dict(paper, id=paper_id)
        for paper_id, paper in state["papers"].items()
        if paper.get("title")
        and (args.tier == "all" or (paper.get("tier") or "candidate") == args.tier)
    ]
    document = {
        "constraints": state["constraints"],
        "rounds": state["rounds"],
        "count": len(papers),
        "papers": papers,
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as file:
        json.dump(document, file, ensure_ascii=False, indent=2)
    return {"count": len(papers), "tier": args.tier, "path": str(out_path)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deduplicated paper-set state file (stdout: JSON only, no network)."
    )
    parser.add_argument("--file", default=DEFAULT_STATE_FILE,
                        help=f"State file path (default {DEFAULT_STATE_FILE}).")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Record hard constraints enforced by `add`.")
    p_init.add_argument("--topic", default=None, help="Research topic (stored for the trace).")
    p_init.add_argument("--year-from", type=int, default=None,
                        help="Reject papers published before this year.")
    p_init.add_argument("--year-to", type=int, default=None,
                        help="Reject papers published after this year.")
    p_init.add_argument("--require-fields", default=None,
                        help="Comma-separated fields a paper must carry, e.g. year,title.")
    p_init.set_defaults(func=cmd_init)

    p_add = sub.add_parser("add", help="Merge papers from stdin JSON array or --ids.")
    p_add.add_argument("--ids", nargs="*", default=None,
                       help="Add bare paper IDs instead of reading stdin.")
    p_add.add_argument("--source", default=None,
                       help='Retrieval source tag recorded per paper, e.g. "search:graph rag".')
    p_add.set_defaults(func=cmd_add)

    p_promote = sub.add_parser("promote", help="Move papers to the curated tier.")
    p_promote.add_argument("--ids", nargs="+", required=True)
    p_promote.set_defaults(func=cmd_promote)

    p_mark = sub.add_parser("mark-expanded", help="Record seed IDs whose references were expanded.")
    p_mark.add_argument("--ids", nargs="+", required=True)
    p_mark.set_defaults(func=cmd_mark_expanded)

    p_round = sub.add_parser("log-round", help="Append one round's trace record.")
    p_round.add_argument("--queries", nargs="*", default=None, help="Queries run this round.")
    p_round.add_argument("--added", type=int, default=None)
    p_round.add_argument("--rejected", type=int, default=None)
    p_round.add_argument("--duplicates", type=int, default=None)
    p_round.add_argument("--merged", type=int, default=None)
    p_round.add_argument("--note", default=None)
    p_round.set_defaults(func=cmd_log_round)

    p_stats = sub.add_parser("stats", help="Totals, tiers, field completeness, year distribution.")
    p_stats.set_defaults(func=cmd_stats)

    p_export = sub.add_parser("export", help="Write the full candidate list with all stored fields.")
    p_export.add_argument("-o", "--output", default="outputs/final_papers.json")
    p_export.add_argument("--tier", choices=["all", *VALID_TIERS], default="all",
                          help="Export only one tier (default all).")
    p_export.set_defaults(func=cmd_export)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = args.func(args)
    except (ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": "invalid_input", "message": str(exc)},
                         ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
