#!/usr/bin/env python3
"""Evidence ledger for aminer-deep-research. No network access.

The ledger is the single source of truth for what the report may cite, and for
the shape the report takes. Round 0 registers the scout probes that were
actually run; the numbered outline is induced from what they returned; every
source and claim hangs off a script-assigned section id; and `check` fails the
run when a claim has no source or a top-level section has no evidence.

    python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" init --topic "..."
    python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" probe --axis keyword --via paper_search_pro --query "..."
    python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" outline set --json '[{"title":"...","from_probes":["p1"],
        "target_chars":5000,"children":[{"title":"..."},{"title":"...","kind":"disagreement"}]}]'
    python3 "${CLAUDE_SKILL_DIR}/scripts/aminer_open.py" --api paper_qa_search_pro --params '{...}' \
        | python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" add --aminer --section 1.1 --probe p1
    python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" claim --text "..." --supports 1 3 --section 1.1 \
        --evidence "..."   # verbatim excerpt M2 checks against the source text
    python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" tier --level moderate --reason "..."
    python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" round --why-stopped "..." --direction 1 --probe p2
    python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" memo --section 1 --text "..."
    python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" decide --action continue --reason "..."
    python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" signals
    python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" verify --claim c1 --unsupported --confidence 0.8
    python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" gaps
    python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" check
    python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" render --material   # the writing-preparation surface
    python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" render --renumber --draft report-draft.md --out report.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any


# The ledger path is the host's choice, never the skill's. Resolve in order:
# --state <path>, then the $DR_LEDGER env var; neither set is an error. The
# skill owns no directory — it does not know "knowledge/", ".zscience/", or
# any location. Persistence and scratch are the host's job; the ledger is the
# skill's output (and an optional input), not a file the skill owns. Never
# write the ledger under ${CLAUDE_SKILL_DIR} (the skill tree is read-only).
DEFAULT_STATE = os.environ.get("DR_LEDGER")  # None unless the host sets it
STATE_VERSION = 2

KINDS = ("paper", "scholar", "patent", "venue", "org", "project", "web")
CLAIM_TYPES = ("observed", "interpretation")
SECTION_KINDS = ("topic", "disagreement")
# Chart types the A template path can render. A figure whose chart_type is not
# here must carry a B script (code_path); the template path refuses it.
FIGURE_TYPES = ("bar", "hbar", "line", "pie", "heatmap", "timeline")
# Quantitative chart shapes — they carry real numbers a report verifies. The
# structural `timeline` runs on dated events and is the fallback when the web
# returned no numbers. A Genre B report ships at least one quantitative figure;
# `figures_industry_quantitative_expected` warns when it ships none.
QUANTITATIVE_TYPES = ("bar", "hbar", "line", "pie", "heatmap")
FIGURE_BUDGET_PER_REPORT = 6
FIGURE_BUDGET_PER_SECTION = 2
# A planned quantitative figure topic is "data-sufficient" once this many live
# datums cite it — below that the topic-driven retrieval keeps running. A
# timeline-intent plan is exempt: its raw material is dated events, not datums,
# so the registered figure itself closes it.
PLAN_MIN_DATUMS = 3
PROBE_AXES = ("topic", "question", "keyword", "title", "abstract", "author", "org", "venue", "time", "web", "patent", "other")

# ── Research-loop economy, ported from the DeepDive harness ──────────────────
# Source: test_cwd/autoglm/app/aminer/deepdive/ — prompts/evaluate.py (the
# evaluator input surface), config.py (thresholds), verify.py (the citation
# faithfulness gates). The judgments stay with the host; every threshold, cap
# and mapping below executes here. In DeepDive a "direction" is a research
# angle explored by runs; in this ledger the top-level outline sections play
# that role (the loop already retrieves per section), so directions need no
# collection of their own — the outline IS the direction registry.
TIERS = ("simple", "moderate", "complex")
DEFAULT_TIER = "moderate"  # config.DEFAULT_COMPLEXITY
# config.COMPLEXITY_PROFILES, numbers verbatim. The budget_scale / wall-clock /
# tool-turn fields do not port: this engine has no tool-budget economy (a
# recorded architectural difference — round summaries carry a self-reported
# "why stopped" instead of a forced-stop signal).
TIER_PROFILES = {
    "simple":   {"max_directions": 2, "max_runs_per_direction": 1, "max_rounds": 3},
    "moderate": {"max_directions": 3, "max_runs_per_direction": 2, "max_rounds": 6},
    "complex":  {"max_directions": 5, "max_runs_per_direction": 3, "max_rounds": 10},
}
# A direction whose citable evidence rests on fewer distinct sources than this
# is a restatement of one source, not research (config.SINGLE_SOURCE_MIN_DISTINCT).
SINGLE_SOURCE_MIN_DISTINCT = 2
# Soft target for the academic genre: scholarly sources the report could cite.
# Best-effort like upstream — it pushes retrieval wider, never blocks and never
# justifies fabrication (config.SCHOLARLY_MIN_REFS comment).
SCHOLARLY_MIN_REFS = 15
# A memo is shown to the evaluator truncated at this many chars
# (config.EVALUATE_MEMO_MAX_CHARS); the full text stays in the ledger.
MEMO_MAX_CHARS = 2000
# The discipline asks 600–1200 chars of mechanism, setups, numbers,
# comparisons. The slot is structural; this floor is the observation that
# keeps the discipline honest — a memo under it is a placeholder, not depth.
MEMO_MIN_CHARS = 600
# A verbatim excerpt shorter than this (after folding) proves nothing: a
# single character or a bare number is a substring of almost any haystack.
# Upstream never needed this floor — its evidence is sliced from the fetched
# document by code — but our excerpts are host-typed, and a run was caught
# decomposing a phrase into one-character "excerpts" to slide past the
# substring check. An excerpt must quote a sentence fragment.
EVIDENCE_MIN_CHARS = 8
# Recording-time volume floors, from upstream's subagent prompt
# (prompts/subagent.py:437-447): finding detail is a review-grade paragraph
# of 建议 300-800 字; each verbatim excerpt is a passage of 100-500 字.
# Upstream enforces none of this in code — prompt discipline plus a
# self-reported memo_word_count. These engine observations are a declared
# beyond-upstream enforcement that uses upstream's own numbers: a cited
# source with no note at all blocks delivery; a thin note and
# fragment-only evidence warn.
NOTE_MIN_CHARS = 300
EVIDENCE_PARAGRAPH_CHARS = 100
# Verify judgments whose reasons collapse to one template string are
# signatures of rubber-stamping, not of per-claim checking. Observation, not
# a gate: this many identical reasons at this share triggers a warning so the
# boilerplate is at least visible.
VERIFY_BOILERPLATE_MIN = 5
VERIFY_BOILERPLATE_SHARE = 0.8
# One-line claim digests shown by `signals`, most recent last
# (config.EVALUATE_FINDINGS_SHOWN).
SIGNALS_CLAIMS_SHOWN = 40
# Citation-faithfulness gates (verify.py), two of them, 疑罪从无 throughout:
# 1) a "not supported" judgment only downgrades the claim when the judge is
#    confident (>= this); a low-confidence False means "not sure" and passes;
# 2) a batch never downgrades more than VERIFY_MAX_DOWNGRADE_RATIO of its
#    candidates — a systematically harsh judge cannot wipe the reference list.
#    The floor of 1 is deliberate: with 1-2 candidates floor(ratio·n) is 0 and
#    a confident hallucination would be un-downgradable, defeating the gate.
VERIFY_DOWNGRADE_MIN_CONFIDENCE = 0.6
VERIFY_MAX_DOWNGRADE_RATIO = 0.5
VERIFY_STATES = ("passed", "downgraded", "inconclusive")
DECISION_ACTIONS = ("stop", "continue", "add_section", "rerun", "patch")

# ── Report-stage richness, ported from the DeepDive harness ──────────────────
# Source: config.py (REPORT_* block), utils.py (cjk_equivalent_len,
# _LEN_BUDGET_MAX, LENGTH_TOLERANCE), prompts/report.py
# (_select_chapter_raw_docs, the chapter material assembly). What motivated
# the port: a report 1/3 the length with 2/5 the references of a DeepDive
# report, on a ledger holding MORE sources — the loss is all report-stage
# (original → one-line claim → prose). DeepDive's own words for the mechanism:
# the raw-doc channel exists to fix "原文->摘要->finding->报告 逐跳压缩导致的
# 深度信息丢失". Three pieces port verbatim below: the writing targets, the
# write-time deviation observation, and the read-back/material view.
# Length metric, same口径 as utils.cjk_equivalent_len: CJK characters count 1
# each, ASCII words × this factor, punctuation/whitespace excluded, citation
# marks and bare URLs stripped first (markup, not prose).
LENGTH_WORD_TO_CJK = 1.7  # utils._WORD_TO_CJK
# config.py: the outline stage assigns each chapter a target by material
# sufficiency (thick chapters get more; they need not be equal). Default full
# text 2–3万 characters with this soft ceiling; a user budget is hard-capped
# at utils._LEN_BUDGET_MAX ("超过 8 万字按 8 万算" — clamped, not refused).
TARGET_TOTAL_SOFT_MAX = 50000
LENGTH_BUDGET_HARD_MAX = 80000
# utils.LENGTH_TOLERANCE — the target is a goal, not a constraint; deviation
# inside ±20% counts as on-target (and outside it is recorded, never rewritten).
LENGTH_TOLERANCE = 0.2
# Beyond-upstream observation threshold (declared): upstream has no
# per-section material metric at all — its outline plans the total by
# thoroughness and material only distributes chapter thickness. A target
# under this share of the section's material is the inverted-anchor defect
# made visible (measured: a section holding 48,440 chars of patent-corpus
# material was targeted at 2,800 — the host used material as a cap to
# arithmetic its way down, instead of as a distributor of thickness).
TARGET_MATERIAL_FLOOR_SHARE = 0.25
# Read-back channel (config.REPORT_CHAPTER_RAW_DOCS_MAX / REPORT_BODY_RAW_DOCS_MAX,
# the non-long-context values): at most this many core originals per section,
# and at most this many distinct originals across the whole-report view. A
# source already listed for an earlier section keeps its slot at half weight —
# same original again beats none, but new originals rank first.
READBACK_PER_SECTION_MAX = 5
READBACK_GLOBAL_MAX = 12

# Stop and hand over partial results rather than spending past this on one task.
HARD_LIMIT_CNY = 20.0

# A probe whose hits are mostly already in the ledger asked the same question
# twice. Rewording is not a second search; change the retrieval axis instead.
LOW_YIELD_MIN_RETURNED = 5
LOW_YIELD_RATIO = 3

# A different failure from low yield: the probe returned plenty of *new* work
# that turned out to be off-object, so triage threw most of it away. A run that
# only measured duplication scored an 80%-discarded probe as healthy, and the
# subfield it was meant to cover ended up with no evidence at all.
DRIFT_MIN_RETURNED = 5
DRIFT_RATIO = 0.5

# Numbers are where a citation goes wrong invisibly: the claim reads well, the
# figure came from a different source than the one cited. Single- and two-digit
# values are too common to check, so only decimals and 3-plus-digit integers are
# compared against the stored text of the sources a claim leans on.
NUMBER_PATTERN = re.compile(r"\d+(?:[.,]\d+)?")
DIGIT_RUN_PATTERN = re.compile(r"(?<=\d)[\s,](?=\d)")
# "400 万" is 4 million in the source it came from: a myriad unit means the
# figure was rescaled on its way into the prose, so a literal match can never
# succeed and flagging it is pure noise.
MYRIAD_UNITS = "万亿兆"
# Engineering quantities the provenance check cannot see: "8 m/s" and "6 kg"
# are one- and two-digit runs, below NUMBER_PATTERN's 3-digit floor, yet they
# are exactly the parameters a weak patent should not vouch for alone. A digit
# run scoped to a unit is quantitative wherever it appears.
UNIT_SCOPED_NUMBER = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:"
    r"m/s|kHz|MHz|GHz|MPa|kPa|rpm|mAh|Nm|DoF|dof|"
    r"mm|cm|km|kg|mg|ms|us|ns|Hz|"
    r"m|g|N|s|h|V|A|W|%|°|"
    r"度|毫米|厘米|千米|公斤|千克|克|吨|牛|帕|巴|赫兹|赫|转|安培|安|伏|瓦|毫安|秒|微秒|纳秒|小时|升|毫升|分贝|个?自由度"
    r")"
)

# Kinds absent from this map have no public AMiner page; they stay link-free.
URL_TEMPLATES = {
    "paper": "https://www.aminer.cn/pub/{id}",
    "scholar": "https://www.aminer.cn/profile/{id}",
    "patent": "https://www.aminer.cn/patent/{id}",
    "venue": "https://www.aminer.cn/open/journal/detail/{id}",
}

TITLE_KEYS = ("title", "title_zh", "name", "name_zh", "titles")
ID_KEYS = ("paper_id", "id", "patent_id", "person_id", "venue_id", "org_id")


class LedgerError(ValueError):
    """User-facing ledger error."""


# --------------------------------------------------------------------------- state


def _empty_state() -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "topic": "",
        "genre": "academic",
        "probes": [],
        "outline": [],
        "sources": [],
        "claims": [],
        "figures": [],
        "figure_plans": [],
        "datums": [],
        # Research-loop telemetry (DeepDive evaluate/verify input surface):
        # tier = the host-judged effort level the engine clamps against;
        # rounds = per-round summaries; memos = per-direction depth notes;
        # decisions = the host's stop/continue calls, replayed by `signals`.
        "tier": "",
        "rounds": [],
        "memos": [],
        "decisions": [],
        "spend": {},
    }


def _upgrade_v1(state: dict[str, Any]) -> dict[str, Any]:
    """Lift a v1 ledger (flat angles) onto the v2 outline so a run in progress
    does not lose sources that were already paid for."""
    angles = [a for a in (state.pop("angles", None) or []) if isinstance(a, str)]
    section_of = {angle: str(i) for i, angle in enumerate(angles, start=1)}
    state["outline"] = [
        {
            "id": str(i),
            "title": angle,
            "from_probes": [],
            "children": [{
                "id": f"{i}.1",
                "title": "Disagreement and counter-evidence",
                "kind": "disagreement",
                "from_probes": [],
            }],
        }
        for i, angle in enumerate(angles, start=1)
    ]
    for source in state.get("sources", []):
        source["sections"] = [section_of[a] for a in source.pop("angles", None) or [] if a in section_of]
        source.setdefault("probes", [])
    for claim in state.get("claims", []):
        claim["section"] = section_of.get(claim.pop("angle", "") or "", "")
    state.setdefault("probes", [])
    state.setdefault("spend", {})
    state["migrated_from"] = {"version": 1, "angles": angles}
    state["unscouted"] = True
    state["version"] = STATE_VERSION
    return state


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _empty_state()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LedgerError(f"State file {path} is not valid JSON: {exc.msg}") from None
    if not isinstance(state, dict):
        raise LedgerError(f"State file {path} must contain a JSON object")
    version = state.get("version", 1)
    if isinstance(version, int) and version > STATE_VERSION:
        raise LedgerError(
            f"State file {path} is version {version}; this script understands {STATE_VERSION}"
        )
    if version < STATE_VERSION or "angles" in state:
        state = _upgrade_v1(state)
    base = _empty_state()
    base.update(state)
    return base


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- probes


def _probe_index(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {probe["id"]: probe for probe in state["probes"]}


def _add_probe(state: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    query = args.query.strip()
    if not query:
        raise LedgerError("A probe needs a non-empty --query")
    probe = {
        "id": f"p{len(state['probes']) + 1}",
        "axis": args.axis,
        "query": query,
        "via": args.via.strip(),
        "returned": 0,
        "new": 0,
        "dup": 0,
    }
    if args.note:
        probe["note"] = args.note.strip()
    state["probes"].append(probe)
    return probe


# --------------------------------------------------------------------------- outline


def _assign_outline(nodes: Any, probe_ids: set[str], require_probes: bool) -> list[dict[str, Any]]:
    """Build the outline from a titles-only tree. Ids are ours, not the caller's,
    so the model cannot cite a section that the report skeleton will not print."""
    if not isinstance(nodes, list) or not nodes:
        raise LedgerError("Outline needs a non-empty JSON array of top-level sections")
    outline: list[dict[str, Any]] = []
    for i, node in enumerate(nodes, start=1):
        if not isinstance(node, dict):
            raise LedgerError("Each outline section must be a JSON object with a title")
        title = str(node.get("title") or "").strip()
        if not title:
            raise LedgerError(f"Outline section {i} needs a title")
        from_probes = [str(p) for p in (node.get("from_probes") or [])]
        unknown = [p for p in from_probes if p not in probe_ids]
        if unknown:
            raise LedgerError(f"Section {i} cites unknown probe(s): {', '.join(unknown)}")
        if require_probes and not from_probes:
            raise LedgerError(
                f"Section {i} '{title}' needs from_probes — run the Round 0 scout and record it "
                f"with `evidence.py probe` first, or pass --allow-unscouted and disclose it in the report"
            )
        children: list[dict[str, Any]] = []
        seen: set[str] = set()
        for j, kid in enumerate(node.get("children") or [], start=1):
            if not isinstance(kid, dict):
                raise LedgerError(f"Subsections of section {i} must be JSON objects")
            kid_title = str(kid.get("title") or "").strip()
            if not kid_title:
                raise LedgerError(f"Subsection {i}.{j} needs a title")
            if kid_title.lower() in seen:
                raise LedgerError(f"Duplicate subsection title '{kid_title}' under section {i}")
            seen.add(kid_title.lower())
            kind = str(kid.get("kind") or "topic")
            if kind not in SECTION_KINDS:
                raise LedgerError(f"Subsection kind must be one of: {', '.join(SECTION_KINDS)}")
            if kid.get("children"):
                raise LedgerError(f"Outline depth is 2; subsection {i}.{j} cannot have children")
            kid_probes = [str(p) for p in (kid.get("from_probes") or [])]
            unknown = [p for p in kid_probes if p not in probe_ids]
            if unknown:
                raise LedgerError(f"Subsection {i}.{j} cites unknown probe(s): {', '.join(unknown)}")
            children.append({
                "id": f"{i}.{j}",
                "title": kid_title,
                "kind": kind,
                "from_probes": kid_probes,
            })
        if not any(kid["kind"] == "disagreement" for kid in children):
            raise LedgerError(
                f"Section {i} '{title}' needs one subsection with \"kind\":\"disagreement\" — "
                f"the counter-evidence subsection every top-level section carries"
            )
        # Optional per-section writing target (DeepDive's outline assigns each
        # chapter a target_chars by material sufficiency; thick chapters get
        # more, they need not be equal). Missing targets are tolerated — the
        # observation surface (`sections_without_target_chars`) carries the
        # pressure, and old outlines stay valid.
        section = {"id": str(i), "title": title, "from_probes": from_probes, "children": children}
        target = node.get("target_chars")
        if target is not None:
            try:
                target = int(target)
            except (TypeError, ValueError):
                raise LedgerError(
                    f"Section {i} '{title}': target_chars must be an integer (字当量), got {target!r}"
                ) from None
            if target <= 0:
                raise LedgerError(f"Section {i} '{title}': target_chars must be positive, got {target}")
            section["target_chars"] = target
        outline.append(section)
    return outline


def _section_index(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for top in state["outline"]:
        index[top["id"]] = top
        for kid in top["children"]:
            index[kid["id"]] = kid
    return index


def _require_sections(state: dict[str, Any], ids: list[str]) -> list[str]:
    index = _section_index(state)
    if not index:
        raise LedgerError("No outline yet — run the Round 0 scout, then `evidence.py outline set`")
    unknown = [i for i in ids if i not in index]
    if unknown:
        raise LedgerError(
            f"Unknown section id(s): {', '.join(unknown)}. Valid ids: {', '.join(index)}"
        )
    return list(dict.fromkeys(ids))


def _find_top(state: dict[str, Any], section_id: str) -> dict[str, Any]:
    for top in state["outline"]:
        if top["id"] == section_id:
            return top
    raise LedgerError(
        f"Unknown top-level section '{section_id}'. "
        f"Valid ids: {', '.join(t['id'] for t in state['outline']) or 'none'}"
    )


def _next_sub_id(top: dict[str, Any]) -> str:
    used = [int(kid["id"].split(".")[1]) for kid in top["children"]]
    return f"{top['id']}.{max(used, default=0) + 1}"


# --------------------------------------------------------------------------- sources


def _normalize_url(url: str) -> str:
    text = url.strip().lower()
    for prefix in ("https://", "http://"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    if text.startswith("www."):
        text = text[4:]
    return text.rstrip("/")


def _source_key(kind: str, ident: str, url: str) -> str:
    if ident:
        return f"{kind}:{ident.strip()}"
    if url:
        return f"url:{_normalize_url(url)}"
    raise LedgerError("A source needs an id or a url")


def _coerce_source(
    raw: Any,
    default_via: str,
    default_sections: list[str],
    default_probe: str | None,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise LedgerError("Each source must be a JSON object")
    kind = str(raw.get("kind") or "paper").strip()
    if kind not in KINDS:
        raise LedgerError(f"Unsupported source kind '{kind}'; use one of: {', '.join(KINDS)}")
    ident = str(raw.get("id") or "").strip()
    title = str(raw.get("title") or "").strip()
    url = str(raw.get("url") or "").strip()
    if not url and ident and kind in URL_TEMPLATES:
        url = URL_TEMPLATES[kind].format(id=ident)
    if not title:
        raise LedgerError("Each source needs a title")
    if not url and not ident:
        raise LedgerError(f"Source '{title}' needs a url or an id")
    own = [str(s) for s in (raw.get("sections") or [])]
    probe = str(raw.get("probe") or default_probe or "").strip()
    source = {
        "key": _source_key(kind, ident, url),
        "kind": kind,
        "id": ident,
        "title": title,
        "url": url,
        "via": str(raw.get("via") or default_via or "").strip(),
        "sections": list(dict.fromkeys(own or default_sections)),
        "probes": [probe] if probe else [],
        "depth": str(raw.get("depth") or "search"),
    }
    for optional in ("year", "venue", "authors", "assignee", "pub_num", "app_num", "pub_kind",
                     "note", "abstract", "abstract_slice", "keywords",
                     "fulltext", "fulltext_unavailable", "fulltext_note"):
        if raw.get(optional) not in (None, "", []):
            source[optional] = raw[optional]
    if source["depth"] not in DEPTHS:
        raise LedgerError(
            f"Source '{title}' has unknown depth '{source['depth']}'; use one of: {', '.join(DEPTHS)}"
        )
    if source["depth"] == "fulltext":
        read = source.get("fulltext") or {}
        if not (isinstance(read, dict) and read.get("url") and read.get("via")):
            raise LedgerError(
                f"Source '{title}': depth 'fulltext' needs its url and via; record fulltext reads "
                "with the fulltext verb (--url --via), not add"
            )
    return source


def _add_sources(
    state: dict[str, Any],
    items: list[Any],
    via: str,
    sections: list[str],
    probe: str | None,
) -> dict[str, Any]:
    known = {item["key"]: item for item in state["sources"]}
    added: list[int] = []
    duplicates: list[int] = []
    for raw in items:
        candidate = _coerce_source(raw, via, sections, probe)
        existing = known.get(candidate["key"])
        if existing:
            for field in ("sections", "probes"):
                for tag in candidate[field]:
                    if tag not in existing[field]:
                        existing[field].append(tag)
            if DEPTH_RANK.get(candidate.get("depth", "search"), 0) > DEPTH_RANK.get(existing.get("depth", "search"), 0):
                existing["depth"] = candidate["depth"]
                if candidate["depth"] == "fulltext":
                    # a re-ingested recorded read outranks, and cancels, a recorded downgrade
                    existing["fulltext"] = candidate["fulltext"]
                    existing.pop("fulltext_unavailable", None)
                    existing.pop("fulltext_note", None)
            # A `paper_detail` hit on a source already found by search arrives here
            # as a duplicate. Its abstract is the thing that was paid for, so
            # merge the richer text in rather than discarding it. `note` is the
            # only content a web source has, so it merges the same way.
            for field in ("authors", "assignee", "abstract", "abstract_slice", "keywords", "year", "venue",
                          "pub_num", "app_num", "pub_kind", "note"):
                incoming = candidate.get(field)
                if not incoming:
                    continue
                current = existing.get(field)
                if not current or len(str(incoming)) > len(str(current)):
                    existing[field] = incoming
            # Retrieving it again on purpose overrides an earlier triage call.
            if existing.pop("dropped", None) is not None:
                existing.pop("drop_reason", None)
            duplicates.append(existing["n"])
            continue
        candidate["n"] = len(state["sources"]) + 1
        state["sources"].append(candidate)
        known[candidate["key"]] = candidate
        added.append(candidate["n"])
    return {"added": added, "duplicates": duplicates, "total": len(state["sources"])}


def _drop_sources(state: dict[str, Any], numbers: list[int], reason: str) -> dict[str, Any]:
    """Retire scout noise without disturbing citation numbers.

    A broad probe buys relevance and noise in the same call. Dropped sources
    keep their slot — renumbering would silently repoint every citation — but
    leave the reference list and every coverage count.
    """
    by_number = {source["n"]: source for source in state["sources"]}
    unknown = [n for n in numbers if n not in by_number]
    if unknown:
        raise LedgerError(f"Unknown source number(s): {', '.join(str(n) for n in unknown)}")
    cited: dict[int, list[str]] = {}
    for claim in state["claims"]:
        for n in claim.get("supports", []):
            cited.setdefault(n, []).append(claim["id"])
    blocked = [n for n in numbers if n in cited]
    if blocked:
        detail = "; ".join(f"{n} supports {', '.join(cited[n])}" for n in blocked)
        raise LedgerError(f"Cannot drop a source a claim relies on: {detail}")
    dropped: list[int] = []
    for n in dict.fromkeys(numbers):
        source = by_number[n]
        if source.get("dropped"):
            continue
        source["dropped"] = True
        if reason:
            source["drop_reason"] = reason
        dropped.append(n)
    return {"dropped": dropped, "remaining": len(_live_sources(state))}


def _mark_fulltext(
    state: dict[str, Any],
    number: int,
    url: str,
    via: str | None,
    unavailable: bool,
    note: str,
) -> dict[str, Any]:
    """Record an open-access fulltext read — or why it was not possible.

    AMiner serves no paper or patent bodies, so the deepest read the API can
    give is the abstract. The host reads the original with its own web tools
    (arXiv PDF/HTML/TeX, Google Patents, a publisher OA page) and records that
    read here. ``--unavailable`` records the downgrade — the original is
    paywalled or has no open copy — so ``check`` can tell "could not" from
    "did not".
    """
    by_number = {source["n"]: source for source in state["sources"]}
    if number not in by_number:
        raise LedgerError(f"Unknown source number: {number}")
    source = by_number[number]
    if source.get("dropped"):
        raise LedgerError(
            f"Source {number} is dropped; re-add it before recording a fulltext read"
        )
    if source["kind"] not in ("paper", "patent"):
        raise LedgerError(
            f"Source {number} is a {source['kind']}; fulltext applies to paper and patent "
            "sources (a web source is already a full-page read)"
        )
    if unavailable:
        if url or via:
            raise LedgerError(
                "--unavailable takes --note only; --url/--via record a read, not a downgrade"
            )
        # A recorded read and a recorded downgrade are mutually exclusive.
        # Marking unavailable after a read is the correction path when an
        # "open" copy turns out paywalled: undo the read, restore the depth
        # the AMiner ladder had given the source before it.
        prior_read = source.pop("fulltext", None) or {}
        if source.get("depth") == "fulltext":
            source["depth"] = prior_read.get("prev_depth") or "detail"
        source["fulltext_unavailable"] = True
        if note:
            source["fulltext_note"] = note
        return {"source": number, "unavailable": True, "note": note}
    if not url or not via:
        raise LedgerError(
            "Recording a fulltext read needs --url and --via (or --unavailable to "
            "record why there is no open copy)"
        )
    if not url.startswith(("http://", "https://")):
        raise LedgerError("--url must be the http(s) address the fulltext was fetched from")
    prev_depth = source.get("depth", "search")
    if prev_depth == "fulltext":  # re-recording a read: keep the original ladder level
        prev_depth = (source.get("fulltext") or {}).get("prev_depth", "detail")
    source["fulltext"] = {
        "url": url,
        "via": via,
        # kept so a later --unavailable can undo this read honestly
        "prev_depth": prev_depth,
        **({"note": note} if note else {}),
    }
    source["depth"] = "fulltext"
    source.pop("fulltext_unavailable", None)
    source.pop("fulltext_note", None)
    return {"source": number, "depth": "fulltext", "via": via, "url": url}


def _live_sources(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [source for source in state["sources"] if not source.get("dropped")]


def _untag_sources(state: dict[str, Any], numbers: list[int], section: str) -> dict[str, Any]:
    """Remove a section tag that a bulk `add --section` applied too broadly."""
    by_number = {source["n"]: source for source in state["sources"]}
    unknown = [n for n in numbers if n not in by_number]
    if unknown:
        raise LedgerError(f"Unknown source number(s): {', '.join(str(n) for n in unknown)}")
    _require_sections(state, [section])
    changed: list[int] = []
    for n in dict.fromkeys(numbers):
        source = by_number[n]
        if section in source.get("sections", []):
            source["sections"].remove(section)
            changed.append(n)
    return {"untagged": changed, "section": section}


def _retract_claims(state: dict[str, Any], ids: list[str], reason: str) -> dict[str, Any]:
    """Withdraw a mis-recorded claim. The id stays reserved so nothing renumbers.

    A wrong citation is the one error `check` cannot see, so correcting it has to
    be cheap: retract, then record the claim again.
    """
    by_id = {claim["id"]: claim for claim in state["claims"]}
    unknown = [i for i in ids if i not in by_id]
    if unknown:
        raise LedgerError(
            f"Unknown claim id(s): {', '.join(unknown)}. "
            f"Valid ids: {', '.join(by_id) or 'none'}"
        )
    retracted: list[str] = []
    for cid in dict.fromkeys(ids):
        claim = by_id[cid]
        if claim.get("retracted"):
            continue
        claim["retracted"] = True
        if reason:
            claim["retract_reason"] = reason
        retracted.append(cid)
    return {"retracted": retracted, "remaining": len(_live_claims(state))}


def _live_claims(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [claim for claim in state["claims"] if not claim.get("retracted")]


# --------------------------------------------------------------------------- spend


def _record_spend(state: dict[str, Any], api: str, unit_cny: float, calls: int = 1) -> None:
    if calls <= 0 or unit_cny < 0:
        return
    entry = state["spend"].setdefault(api, {"calls": 0, "unit_cny": unit_cny, "subtotal": 0.0})
    entry["calls"] += calls
    entry["unit_cny"] = unit_cny
    entry["subtotal"] = round(entry["calls"] * unit_cny, 4)


def _spend_from_aminer(state: dict[str, Any], payload: Any) -> None:
    """A paid call is a paid call whether or not its hits were worth keeping."""
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return
    for result in results:
        if not isinstance(result, dict) or result.get("dry_run"):
            continue
        api = str(result.get("api") or "").strip()
        cost = result.get("unit_cost_cny")
        if api and isinstance(cost, (int, float)) and cost > 0:
            _record_spend(state, api, float(cost))


def _spend_total(state: dict[str, Any]) -> float:
    return round(sum(entry["subtotal"] for entry in state["spend"].values()), 4)


def _paid_calls_without_hits(payload: Any, kind_override: str | None) -> list[dict[str, Any]]:
    """Paid calls that returned nothing usable.

    A query the API does not understand still answers 200 and still bills. Left
    unreported it reads as 'this angle has no literature' when it actually means
    'that query shape was wrong' — so surface it at the moment it happens.
    """
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return []
    empty: list[dict[str, Any]] = []
    for result in results:
        if not isinstance(result, dict) or not result.get("ok") or result.get("dry_run"):
            continue
        cost = result.get("unit_cost_cny")
        if not isinstance(cost, (int, float)) or cost <= 0:
            continue
        if not extract_from_aminer({"results": [result]}, kind_override):
            data = result.get("data")
            empty.append({
                "api": str(result.get("api") or ""),
                "cost_cny": float(cost),
                "msg": str(data.get("msg") or "") if isinstance(data, dict) else "",
            })
    return empty


# --------------------------------------------------------------------------- aminer extraction


def _str_from_value(value: Any) -> str:
    """First usable string out of an AMiner field. `paper_*` returns plain
    strings; `patent_detail` wraps `title` / `abstract` as {"en": [...],
    "zh": [...]} — without descending into that dict the record has no title,
    fails entity detection, and the paid call lands as a no-hit."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, list) and value and isinstance(value[0], str) and value[0].strip():
        return value[0].strip()
    if isinstance(value, dict):
        for sub in (value.get("zh"), value.get("en"), value.get("name"), value.get("raw")):
            got = _str_from_value(sub)
            if got:
                return got
    return ""


def _first_str(record: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        got = _str_from_value(record.get(key))
        if got:
            return got
    return ""


def _looks_like_entity(record: dict[str, Any]) -> bool:
    return bool(_first_str(record, ID_KEYS)) and bool(_first_str(record, TITLE_KEYS))


def _absorb_content(node: dict[str, Any], entry: dict[str, Any]) -> None:
    """Keep the text the call actually paid for.

    A `paper_detail` abstract costs money and a `paper_info` slice costs a free
    call; dropping either on the floor means the ledger cannot show what a claim
    rests on, cannot check a citation, and cannot survive a restart. Stored here,
    never printed by `render` or `gaps` — use `source show` to read one.
    """
    authors = node.get("authors")
    if isinstance(authors, list):
        names = [a["name"].strip() for a in authors
                 if isinstance(a, dict) and isinstance(a.get("name"), str) and a["name"].strip()]
        if not names:
            names = [a.strip() for a in authors if isinstance(a, str) and a.strip()]
        if names:
            entry["authors"] = names
    for key in ("abstract", "abstract_slice"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            entry[key] = value.strip()
        elif isinstance(value, dict):
            # patent_detail abstracts arrive as {"en": [...], "zh": [...]} with
            # NOVELTY / USE / ADVANTAGE sections as separate list items.
            for sub in (value.get("zh"), value.get("en")):
                if isinstance(sub, list):
                    text = " ".join(p.strip() for p in sub if isinstance(p, str) and p.strip())
                    if text:
                        entry[key] = text
                        break
    keywords = node.get("keywords")
    if isinstance(keywords, str) and keywords.strip():
        entry["keywords"] = keywords.strip()
    elif isinstance(keywords, list):
        words = [k.strip() for k in keywords if isinstance(k, str) and k.strip()]
        if words:
            entry["keywords"] = words
    # Patents carry the rights holder under `assignee` / `applicant` as a list of
    # {name, raw_address_info, sequence}; papers never have it. Mirroring the
    # authors extraction so a `patent_detail` hit persists the assignee a player
    # table and a per-assignee corpus chart both need.
    for key in ("assignee", "applicant"):
        holder = node.get(key)
        if isinstance(holder, list):
            names = [h["name"].strip() for h in holder
                     if isinstance(h, dict) and isinstance(h.get("name"), str) and h["name"].strip()]
            if names:
                entry["assignee"] = names
                break
        elif isinstance(holder, str) and holder.strip():
            entry["assignee"] = [holder.strip()]
            break
    # Patents: the publication/application numbers the raw node carries. AMiner
    # swaps `pub_num` / `app_num` inconsistently between records, so both are
    # kept verbatim — the Google Patents slug assembles from the 9-digit one
    # (`CN{digits}{pub_kind}`), whichever field it landed in.
    for key in ("pub_num", "app_num", "pub_kind"):
        number = node.get(key)
        if isinstance(number, str) and number.strip():
            entry[key] = number.strip()


def _coerce_year(value: Any) -> int | None:
    """Normalise a year from whatever an AMiner node carries: a paper's `year`
    int, a patent_search `app_year` / `pub_year` string ("2024"), or a
    patent_detail epoch dict {"seconds": 1640908800}. Returns None when nothing
    parses — the source ships without a year rather than with a fabricated one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 1000 <= value <= 2999 else None
    if isinstance(value, str):
        m = re.search(r"\b(1[0-9]{3}|20[0-9]{2}|2[1-9]\d{2})\b", value)
        return int(m.group(1)) if m else None
    if isinstance(value, dict):
        seconds = value.get("seconds")
        if isinstance(seconds, (int, float)) and not isinstance(seconds, bool):
            try:
                return time.gmtime(seconds).tm_year
            except (OverflowError, ValueError, OSError):
                return None
    return None


def _walk(node: Any, via: str, kind: str, found: list[dict[str, Any]], depth: int = 0) -> None:
    if depth > 8:
        return
    if isinstance(node, list):
        for item in node:
            _walk(item, via, kind, found, depth + 1)
        return
    if not isinstance(node, dict):
        return
    if _looks_like_entity(node):
        entry: dict[str, Any] = {
            "kind": kind,
            "id": _first_str(node, ID_KEYS),
            "title": _first_str(node, TITLE_KEYS),
            "via": via,
            "depth": _depth_for_api(via),
        }
        year = _coerce_year(
            node.get("year") or node.get("app_year") or node.get("pub_year")
            or node.get("app_date") or node.get("pub_date")
        )
        if year is not None:
            entry["year"] = year
        venue = node.get("venue")
        if isinstance(venue, str) and venue.strip():
            entry["venue"] = venue.strip()
        elif isinstance(venue, dict):
            name = _first_str(venue, ("name", "name_zh", "raw"))
            if name:
                entry["venue"] = name
        elif isinstance(node.get("venue_name"), str) and node["venue_name"].strip():
            entry["venue"] = node["venue_name"].strip()
        _absorb_content(node, entry)
        found.append(entry)
        return
    for value in node.values():
        _walk(value, via, kind, found, depth + 1)


# How deeply a source has actually been read, named after where the data came
# from. A search result is a title; a `paper_info` slice is a truncated
# abstract; only `paper_detail` is the whole abstract and keywords. Claims must
# not rest on the first two. `fulltext` sits above the AMiner ladder: the
# open-access original, fetched with the host's own web tools — AMiner serves
# no paper or patent bodies — and recorded with `evidence.py fulltext`. When
# the original is obtainable it must be read; degrading to the abstract is
# legitimate only when it is not, and the degradation itself is recorded
# (`fulltext --unavailable`) so `check` can tell "could not" from "did not".
DEPTHS = ("search", "slice", "detail", "fulltext")
DEPTH_RANK = {name: i for i, name in enumerate(DEPTHS)}
DEPTH_BY_API = {"paper_info": "slice", "paper_detail": "detail", "patent_detail": "detail"}
# Channels an open-access fulltext can arrive through; `fulltext --via` records
# which one was used, so the appendix can say how the original was obtained.
FULLTEXT_CHANNELS = (
    "arxiv-pdf", "arxiv-html", "arxiv-tex", "google-patents", "publisher", "other",
)


def _depth_for_api(api: str) -> str:
    return DEPTH_BY_API.get(api, "search")


KIND_BY_API = {
    "person_search": "scholar",
    "person_detail": "scholar",
    "person_figure": "scholar",
    "org_person_relation": "scholar",
    "person_project": "project",
    "org_search": "org",
    "org_detail": "org",
    "org_disambiguate": "org",
    "org_disambiguate_pro": "org",
    "venue_search": "venue",
    "venue_detail": "venue",
}


def _kind_for_api(api: str) -> str:
    """Entity kind the API returns. Pass --kind for anything not covered here."""
    if api in KIND_BY_API:
        return KIND_BY_API[api]
    if "patent" in api:
        return "patent"
    return "paper"


def extract_from_aminer(payload: Any, kind_override: str | None = None) -> list[dict[str, Any]]:
    """Pull entity records out of an aminer_open.py result document."""
    found: list[dict[str, Any]] = []
    results = payload.get("results") if isinstance(payload, dict) else None
    if isinstance(results, list):
        for result in results:
            if not isinstance(result, dict) or not result.get("ok"):
                continue
            api = str(result.get("api") or "")
            _walk(result.get("data"), api, kind_override or _kind_for_api(api), found)
    else:
        _walk(payload, "", kind_override or "paper", found)
    unique: dict[str, dict[str, Any]] = {}
    for item in found:
        unique.setdefault(f"{item['kind']}:{item['id']}", item)
    return list(unique.values())


# --------------------------------------------------------------------------- claims and analysis


def _add_claim(state: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    return _record_claim(
        state,
        text=args.text or "",
        section=args.section or "",
        supports=list(args.supports),
        claim_type=args.type,
        conflict=args.conflict or "",
        allow_unsupported=args.allow_unsupported,
        evidence=list(getattr(args, "evidence", None) or []),
    )


def _record_claim(
    state: dict[str, Any],
    text: str,
    section: str,
    supports: list[int],
    claim_type: str = "observed",
    conflict: str = "",
    allow_unsupported: bool = False,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise LedgerError("A claim needs non-empty --text")
    if claim_type not in CLAIM_TYPES:
        raise LedgerError(f"Unsupported claim type '{claim_type}'; use one of: {', '.join(CLAIM_TYPES)}")
    numbers = {source["n"] for source in state["sources"]}
    unknown = [n for n in supports if n not in numbers]
    if unknown:
        raise LedgerError(f"Unknown source number(s): {', '.join(str(n) for n in unknown)}")
    if not supports and not allow_unsupported:
        raise LedgerError("A claim needs at least one --supports source (use --allow-unsupported for an open question)")
    section = _require_sections(state, [section])[0]
    claim = {
        "id": f"c{len(state['claims']) + 1}",
        "text": text,
        "supports": sorted(set(supports)),
        "type": claim_type,
        "section": section,
    }
    if conflict:
        claim["conflict"] = conflict.strip()
    # Verbatim excerpts the claim rests on. An excerpt must be a substring of
    # one of the supporting sources' stored text (whitespace-insensitively) —
    # `check` enforces it and downgrades failures to background info. Quotes
    # lifted from an open-access original ride in the fulltext read's --note
    # (the same rule as numbers): the note is what this check searches.
    # Degenerate excerpts are refused here rather than flagged later: a
    # single character or a bare number matches almost any source, so a
    # too-short "quote" is not evidence at all.
    excerpts = [str(e).strip() for e in (evidence or []) if str(e).strip()]
    for excerpt in excerpts:
        if len(_fold_for_match(excerpt)) < EVIDENCE_MIN_CHARS:
            raise LedgerError(
                f"Evidence excerpt {excerpt!r} is too short to be evidence (minimum "
                f"{EVIDENCE_MIN_CHARS} characters after folding) — quote the sentence "
                "fragment from the source text, not isolated characters or bare numbers"
            )
    if excerpts:
        claim["evidence"] = excerpts
    state["claims"].append(claim)
    return claim


def _add_claims_batch(state: dict[str, Any], payload: Any) -> dict[str, Any]:
    """Record many claims in one call.

    A section's worth of claims is the normal unit of work; one subprocess per
    claim pushed every caller into writing their own driver loop.
    """
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        raise LedgerError("Batch input must be a JSON array of claim objects")
    recorded: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for position, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            failed.append({"position": position, "error": "not a JSON object"})
            continue
        try:
            recorded.append(_record_claim(
                state,
                text=str(item.get("text") or ""),
                section=str(item.get("section") or ""),
                supports=[int(n) for n in (item.get("supports") or [])],
                claim_type=str(item.get("type") or "observed"),
                conflict=str(item.get("conflict") or ""),
                allow_unsupported=bool(item.get("allow_unsupported")),
                evidence=[str(e) for e in (item.get("evidence") or [])],
            ))
        except (LedgerError, TypeError, ValueError) as exc:
            failed.append({"position": position, "text": str(item.get("text") or "")[:80], "error": str(exc)})
    return {"claims": recorded, "failed": failed}


def _rollup(state: dict[str, Any]) -> tuple[dict[str, set[int]], dict[str, list[str]], dict[str, set[str]]]:
    """Sources and claims per section id, with children rolled into the parent.

    The model tags mostly at subsection level, so a parent gate that ignored
    children would block a section that is in fact well covered.
    """
    sources_by: dict[str, set[int]] = {}
    claims_by: dict[str, list[str]] = {}
    live = {source["n"] for source in state["sources"] if not source.get("dropped")}
    for top in state["outline"]:
        for sid in (top["id"], *(kid["id"] for kid in top["children"])):
            sources_by.setdefault(sid, set())
            claims_by.setdefault(sid, [])
    for source in state["sources"]:
        if source.get("dropped"):
            continue
        for sid in source.get("sections", []):
            if sid in sources_by:
                sources_by[sid].add(source["n"])
    for claim in state["claims"]:
        if claim.get("retracted"):
            continue
        sid = claim.get("section", "")
        if sid in claims_by:
            claims_by[sid].append(claim["id"])
            # A source a section's claim leans on covers that section, whether or
            # not it was also tagged there.
            for n in claim.get("supports", []):
                if n in live:
                    sources_by[sid].add(n)

    probes_by_top: dict[str, set[str]] = {}
    for top in state["outline"]:
        own_sources = set(sources_by[top["id"]])
        own_claims = list(claims_by[top["id"]])
        for kid in top["children"]:
            own_sources |= sources_by[kid["id"]]
            own_claims += claims_by[kid["id"]]
        sources_by[top["id"]] = own_sources
        claims_by[top["id"]] = own_claims
        probes_by_top[top["id"]] = {
            p for s in state["sources"] if s["n"] in own_sources for p in s.get("probes", [])
        }
    return sources_by, claims_by, probes_by_top


def analyze(state: dict[str, Any]) -> dict[str, Any]:
    sources = _live_sources(state)
    dropped = [s["n"] for s in state["sources"] if s.get("dropped")]
    claims = _live_claims(state)
    retracted = [c["id"] for c in state["claims"] if c.get("retracted")]
    cited: set[int] = set()
    for claim in claims:
        cited.update(claim.get("supports", []))

    sources_by, claims_by, probes_by_top = _rollup(state)
    tops = [top["id"] for top in state["outline"]]
    subs = [kid for top in state["outline"] for kid in top["children"]]
    spend_total = _spend_total(state)
    figures = _live_figures(state)
    fig_sections = _figures_by_section(state)
    known_sections = set(_section_index(state))
    plans = _live_plans(state)
    reason_stats = _verify_reason_stats(claims)
    funnel = _retrieval_funnel(state)
    targets = _write_targets(state)

    return {
        "topic": state.get("topic", ""),
        "genre": state.get("genre", "academic"),
        "totals": {
            "sources": len(sources),
            "dropped_sources": len(dropped),
            "claims": len(claims),
            "retracted_claims": len(retracted),
            "sections": len(tops),
            "subsections": len(subs),
            "probes": len(state["probes"]),
            "cited_sources": len(cited),
            "figures": len(figures),
            "figure_plans": len(plans),
            "datums": len(_live_datums(state)),
            "rounds": len(state.get("rounds", [])),
            "effective_rounds": len(_effective_rounds(state)),
            "memos": len(state.get("memos", [])),
            "decisions": len(state.get("decisions", [])),
            # the report-stage richness funnel: how much retrieval survives to
            # claim-grounded use (observation only — upstream reports this
            # pair, it never thresholds it)
            "sources_with_abstract": funnel["with_abstract"],
            "sources_with_note": funnel["with_note"],
            "sources_fulltext": funnel["fulltext"],
            "cited_share": funnel["cited_share"],
        },
        "sections": [
            {
                "id": top["id"],
                "title": top["title"],
                "sources": len(sources_by[top["id"]]),
                "claims": len(claims_by[top["id"]]),
                "probes": sorted(probes_by_top[top["id"]]),
                "children": [
                    {
                        "id": kid["id"],
                        "title": kid["title"],
                        "kind": kid["kind"],
                        "sources": len(sources_by[kid["id"]]),
                        "claims": len(claims_by[kid["id"]]),
                    }
                    for kid in top["children"]
                ],
            }
            for top in state["outline"]
        ],
        # blocking
        "outline_missing": not state["outline"],
        "sections_below_two_sources": [t for t in tops if len(sources_by[t]) < 2],
        "unsupported_claims": [c["id"] for c in claims if not c.get("supports")],
        "spend_over_hard_limit": spend_total >= HARD_LIMIT_CNY,
        # warnings
        "subsections_below_two_sources": [k["id"] for k in subs if len(sources_by[k["id"]]) < 2],
        "sections_missing_disagreement": [
            top["id"] for top in state["outline"]
            if not any(kid["kind"] == "disagreement" for kid in top["children"])
        ],
        "sections_from_single_probe": [
            t for t in tops if len(sources_by[t]) >= 2 and len(probes_by_top[t]) == 1
        ],        "low_yield_probes": [
            {
                "probe": p["id"], "axis": p.get("axis", ""), "query": p.get("query", ""),
                "new": p.get("new", 0), "returned": p.get("returned", 0),
            }
            for p in state["probes"]
            if p.get("returned", 0) >= LOW_YIELD_MIN_RETURNED
            and p.get("new", 0) * LOW_YIELD_RATIO < p.get("returned", 0)
        ],
        "drifting_probes": _drifting_probes(state),
        "sections_without_claims": [t for t in tops if not claims_by[t]],
        "untagged_sources": [s["n"] for s in sources if not s.get("sections")],
        "sources_without_probe": [s["n"] for s in sources if not s.get("probes")],
        "cited_sources_without_detail": [
            s["n"] for s in sources
            if s["n"] in cited and s["kind"] != "web"
            and DEPTH_RANK.get(s.get("depth", "search"), 0) < DEPTH_RANK["detail"]
        ],
        # Fulltext-first: a cited paper or patent the host neither read at
        # fulltext nor marked `fulltext --unavailable`. An open-access original
        # (arXiv, Google Patents, publisher OA) must be read before claims lean
        # on it; only a paywalled or nonexistent copy justifies stopping at the
        # abstract — and that downgrade has to be recorded, not silent.
        "cited_sources_without_fulltext": [
            s["n"] for s in sources
            if s["n"] in cited and s["kind"] in ("paper", "patent")
            and DEPTH_RANK.get(s.get("depth", "search"), 0) < DEPTH_RANK["fulltext"]
            and not s.get("fulltext_unavailable")
        ],
        "single_source_claims": [c["id"] for c in claims if len(c.get("supports", [])) == 1],
        "claims_weak_patent_sole_support": _claims_weak_patent_sole_support(state),
        "claims_with_unsourced_numbers": _claims_with_unsourced_numbers(state),
        # ── research-loop economy warnings (DeepDive port) ──
        # No tier registered means the direction/round clamps never bound —
        # an unclamped run is the thing the tier exists to prevent.
        "tier_missing": bool(state["outline"]) and not state.get("tier"),
        "sections_without_memo": [
            top["id"] for top in state["outline"]
            if not any(m.get("section") == top["id"] for m in state.get("memos", []))
        ],
        "sections_single_sourced": [
            d["section"] for d in _direction_source_diversity(state) if d["warning"].startswith("single-source")
        ],
        "claims_evidence_not_verbatim": _claims_evidence_not_verbatim(state),
        "claims_verify_downgraded": [
            c["id"] for c in claims if c.get("verify_status") == "downgraded"
        ],
        "claims_awaiting_verify": [
            c["id"] for c in claims
            if c.get("evidence") and not c.get("verified") and not _claim_downgraded(state, c)
        ],
        # A memo under the depth floor is a placeholder wearing the slot.
        "memos_thin": _memos_thin(state),
        # Controversy-shaped structure with no recorded tension. The
        # disagreement subsection is where counter-evidence surfaces in the
        # report, but the *tension itself* lives on the claim (`--conflict`) —
        # that is what render, check and the report quote. A section whose
        # counter-evidence subsection carries claims while no claim under it
        # records a conflict is presenting disagreement as decoration (a rerun
        # shipped five 风险与争议 subsections and zero conflicts).
        "disagreements_without_conflict": [
            top["id"] for top in state["outline"]
            if any(claims_by.get(kid["id"]) for kid in top["children"]
                   if kid["kind"] == "disagreement")
            and not any(c.get("conflict") for c in claims
                        if str(c.get("section", "")).startswith(f"{top['id']}."))
        ],
        # A quantitative plan closed by a from-datums figure while zero datums
        # were ever tagged to it: the sufficiency countdown never ran, and the
        # topic closed by assembly rather than by data. Corpus plans closed via
        # --from-source-metadata and timeline plans are exempt by design.
        "figure_plans_closed_untagged": [
            {"plan": p["id"], "topic": p.get("topic", ""), "figure": p.get("figure_id")}
            for p in plans
            if p.get("status") == "fulfilled" and p.get("figure_id")
            and next((f for f in figures if f["id"] == p["figure_id"]), {}).get("from_datums")
            and not _plan_datums(state, p["id"])
        ],
        # Duplicated reason strings covering the verify batch: the form is
        # satisfied, the checking probably was not. Measured on *any* repeated
        # reason, not the single top one — splitting one template into two
        # must not dodge it. Advisory: it makes the rubber-stamp visible, it
        # cannot force real scrutiny.
        "verify_reasons_boilerplate": (
            {key: reason_stats[key] for key in (
                "distinct_reasons", "duplicated_reason_share",
                "top_confidence", "top_confidence_share")}
            if reason_stats.get("verified", 0) >= VERIFY_BOILERPLATE_MIN
            and reason_stats["duplicated_reason_share"] >= VERIFY_BOILERPLATE_SHARE
            else None
        ),
        # ── report-stage richness warnings (DeepDive port) ──
        # Upstream's outline carries a writing target per chapter, assigned by
        # material sufficiency; a section without one gets written to whatever
        # the floor allows, which is how a 99-source ledger yields a 27-source
        # report. Observation, not a gate: old outlines stay valid.
        "sections_without_target_chars": [
            top["id"] for top in state["outline"] if not top.get("target_chars")
        ],
        # Beyond-upstream observation (annotated in the migration doc):
        # upstream's 5万 ceiling lives in the outline prompt ("最多不超过 5
        # 万字") with no engine check of its own; we surface a plan that
        # breaks it rather than police it. The user's registered budget
        # replaces the default ceiling, same priority as upstream's parse.
        "write_targets_over_max": (
            {"total": targets["total"], "max": (
                targets["budget"] if targets["budget"] else TARGET_TOTAL_SOFT_MAX
            ), "budget": targets["budget"]}
            if targets["total"] is not None and targets["total"] > (
                targets["budget"] if targets["budget"] else TARGET_TOTAL_SOFT_MAX
            ) else None
        ),
        # A section whose target outruns ALL the material it holds (claims,
        # evidence, abstracts, notes) is a broken coupling made visible —
        # upstream never creates one, because material sufficiency is the
        # INPUT to target assignment (按素材充分度), and an insufficient pile
        # writes to coverage completeness rather than padding (素材不足时以
        # 覆盖完整为准，不必注水拉长 — prompts/report.py:627). Observation
        # only: the engine assigns no targets, and length never drives
        # retrieval upstream (the evaluator sees no length at all).
        "write_targets_over_material": [
            {
                "section": top["id"],
                "target": top.get("target_chars"),
                "material_chars": targets["sections"][top["id"]]["material_chars"],
            }
            for top in state["outline"]
            if top.get("target_chars")
            and top["target_chars"] > targets["sections"][top["id"]]["material_chars"]
        ],
        # The mirror image of write_targets_over_material, and the more
        # damaging one in practice: a target far UNDER the section's material
        # means the pile was used as an excuse to write thin (material is the
        # distributor of thickness, never a cap to beat down). Observation
        # only, beyond upstream (which has no material metric) — declared.
        "sections_under_targeted_vs_material": [
            {
                "section": top["id"],
                "target": top.get("target_chars"),
                "material_chars": targets["sections"][top["id"]]["material_chars"],
            }
            for top in state["outline"]
            if top.get("target_chars") and targets["sections"][top["id"]]["material_chars"] > 0
            and top["target_chars"] < TARGET_MATERIAL_FLOOR_SHARE
            * targets["sections"][top["id"]]["material_chars"]
        ],
        # The persisted write-time length observation (written by
        # `render --renumber`, mirroring upstream's post-delivery deviation
        # log). Observation only — never a check key, never a gate: upstream
        # states 篇幅是目标不是硬约束 and tunes prompts with the deviation
        # instead of rewriting the prose.
        "length_report": state.get("length_report") or {},
        # ── recording-time volume (upstream subagent discipline, enforced) ──
        # Upstream's finding carries a 300-800-字 review-grade digest and 1-3
        # verbatim passages of 100-500 字 each (prompts/subagent.py:437-447);
        # the note and the evidence array are those channels here. Upstream
        # checks none of it in code — these observations use upstream's own
        # numbers. A cited source with NO note blocks delivery (the note is
        # the provenance channel the number checks search); thin notes and
        # fragment-only evidence warn.
        "cited_sources_without_note": [
            s["n"] for s in sources if s["n"] in cited and not (s.get("note") or "").strip()
        ],
        "cited_sources_note_thin": [
            {"n": s["n"], "chars": len(s.get("note") or "")}
            for s in sources
            if s["n"] in cited and (s.get("note") or "").strip()
            and len(s.get("note") or "") < NOTE_MIN_CHARS
        ],
        "claims_thin_evidence": [
            c["id"] for c in _live_claims(state)
            if c.get("evidence")
            and all(
                len(e) < EVIDENCE_PARAGRAPH_CHARS
                for e in (c["evidence"] if isinstance(c["evidence"], list)
                          else [c["evidence"]])
            )
        ],
        "rounds_without_yield": _rounds_without_yield(state),
        # Live-but-undigested: kept sources with no note at all. Upstream's
        # reader cannot return from a pass without its digests — the record
        # IS the pass's output — so "retrieved, kept, never written down"
        # has no upstream equivalent. Here it is spend that never becomes
        # material (measured: a run kept 28 patent details and wrote 9
        # notes). Blocking since 2026-08-30 (user decision, zero exemption:
        # datum carriers and corpus-aggregation sources need a note too) —
        # read the source or drop it; keeping it unrecorded is not a state.
        "sources_without_note": [
            {"n": s["n"], "kind": s.get("kind", ""), "sections": s.get("sections", [])}
            for s in sources if not (s.get("note") or "").strip()
        ],
        "figures_with_no_sources": [f["id"] for f in figures if not f.get("source_ids")],
        "figures_unsupported_numbers": _figures_with_unsourced_numbers(state),
        "figures_in_unrendered_section": [
            f["id"] for f in figures if f.get("section", "") not in known_sections
        ],
        "figures_without_render": [f["id"] for f in figures if not f.get("rendered")],
        "figures_over_budget": len(figures) > FIGURE_BUDGET_PER_REPORT,
        "figures_industry_expected": (
            state.get("genre") == "industry" and len(figures) == 0
        ),
        "figures_industry_quantitative_expected": (
            state.get("genre") == "industry"
            and not any(
                f.get("chart_type") in QUANTITATIVE_TYPES
                or (f.get("code_path") and f.get("chart_type") != "timeline")
                for f in figures
            )
        ),
        "figures_thin_data": _figures_thin_data(state),
        # Who charted. The engine cannot see whether a chart-topic subagent
        # was actually dispatched — the ceiling here, as with verify's "who
        # judges", is forced declaration plus visibility: `figure add` demands
        # --charted-by (controller mode demands its reason right there), an
        # undeclared figure (old ledger, hand-edited state) warns, and
        # Appendix C reports each figure's mode. Advisory by design: it makes
        # in-session charting by a delegating host visible; it cannot catch
        # a false declaration.
        "figures_charting_undeclared": [
            f["id"] for f in figures if not f.get("charted_by")
        ],
        "figures_charted_in_controller": [
            {"figure": f["id"], "reason": f.get("charted_reason", "")}
            for f in figures if f.get("charted_by") == "controller"
        ],
        # Figure plans: the chart-topic stage. A quantitative plan is the
        # retrieval obligation "hunt this topic's numbers until >=PLAN_MIN_DATUMS
        # live datums cite it"; timeline-intent plans close via their figure.
        "figure_plans_thin": [
            {
                "plan": p["id"], "topic": p.get("topic", ""),
                "datums": len(_plan_datums(state, p["id"])),
                "minimum_datums": PLAN_MIN_DATUMS,
            }
            for p in plans if p.get("status") == "open"
            and p.get("chart_type", "") != "timeline"
            and len(_plan_datums(state, p["id"])) < PLAN_MIN_DATUMS
        ],
        "figure_plans_unfulfilled": [
            p["id"] for p in plans if p.get("status") == "open"
            and p.get("chart_type", "") != "timeline"
            and len(_plan_datums(state, p["id"])) >= PLAN_MIN_DATUMS
        ],
        "figure_plans_abandoned": [
            {"plan": p["id"], "topic": p.get("topic", ""), "reason": p.get("reason", "")}
            for p in plans if p.get("status") == "abandoned"
        ],
        "figure_plans_industry_expected": (
            state.get("genre") == "industry" and len(plans) == 0
        ),
        "sections_over_figure_budget": [
            sid for sid, fids in fig_sections.items() if len(fids) > FIGURE_BUDGET_PER_SECTION
        ],
        "figure_code_divergence": _figure_code_divergence(state),
        "unresolved_conflicts": [
            {"claim": c["id"], "conflict": c["conflict"]} for c in claims if c.get("conflict")
        ],
        "uncited_sources": [s["n"] for s in sources if s["n"] not in cited],
        "datums_without_source": [
            d["id"] for d in _live_datums(state)
            if d.get("source") not in {s["n"] for s in sources}
        ],
        "industry_web_sources_without_datums": (
            [s["n"] for s in sources if s["kind"] == "web"
             and s["n"] not in {d["source"] for d in _live_datums(state)}]
            if state.get("genre") == "industry" else []
        ),
        "web_sources": sum(1 for s in sources if s["kind"] == "web"),
        "aminer_sources": sum(1 for s in sources if s["kind"] != "web"),
        "spend": {
            "total_cny": spend_total,
            "hard_limit_cny": HARD_LIMIT_CNY,
            "by_api": state["spend"],
        },
        "unscouted": bool(state.get("unscouted")),
    }


def _source_text(source: dict[str, Any]) -> str:
    """Everything the ledger has actually read about one source, as one blob."""
    parts: list[str] = []
    for key in ("title", "abstract", "abstract_slice", "note", "venue"):
        value = source.get(key)
        if isinstance(value, str):
            parts.append(value)
    for key in ("keywords", "authors"):
        value = source.get(key)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(str(v) for v in value)
    year = source.get("year")
    if year:
        parts.append(str(year))
    # The fulltext body stays out of the ledger, so numbers lifted from the
    # original ride in the read's --note; without this the provenance check
    # would flag every fulltext-derived number as unsourced.
    read_note = (source.get("fulltext") or {}).get("note")
    if isinstance(read_note, str):
        parts.append(read_note)
    return DIGIT_RUN_PATTERN.sub("", " ".join(parts))


def _checkable_numbers(text: str) -> list[str]:
    out: list[str] = []
    for match in NUMBER_PATTERN.finditer(text):
        # A digit run glued to a letter is part of an identifier, not a
        # figure: TOP500, H800, SW26010, A100. Checking "500" against a
        # source that names the TOP500 list without the digits glued to
        # anything is a false positive (a rerun was flagged on exactly that).
        before = text[match.start() - 1] if match.start() else ""
        after = text[match.end():match.end() + 1]
        if (before and before.isascii() and before.isalpha()) or \
           (after and after.isascii() and after.isalpha()):
            continue
        normalised = match.group().replace(",", ".")
        digits = normalised.replace(".", "")
        if "." not in normalised and len(digits) < 3:
            continue  # one- and two-digit values are too common to mean anything
        if "." not in normalised and len(digits) == 4 and 1900 <= int(digits) <= 2099:
            continue  # a bare year is prose, not a reported figure
        if text[match.end():match.end() + 3].lstrip()[:1] in MYRIAD_UNITS:
            continue  # rescaled by a myriad unit, so a literal match can never succeed
        out.append(normalised)
    return list(dict.fromkeys(out))


def _claims_with_unsourced_numbers(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Figures in a claim that appear in none of the sources it cites.

    This is the one error `check` used to be blind to: the prose is fine, the
    citation points at the wrong source. A warning, not a gate — a figure the
    model converted into another unit or another language ("4 million" written as
    "400 万") lands here too, and that is still worth a second look.
    """
    by_number = {source["n"]: source for source in state["sources"]}
    findings: list[dict[str, Any]] = []
    for claim in _live_claims(state):
        supports = [by_number[n] for n in claim.get("supports", []) if n in by_number]
        haystacks = [_source_text(s) for s in supports]
        if not any(h.strip() for h in haystacks):
            continue  # nothing was ever read for these sources; other warnings cover that
        blob = DIGIT_RUN_PATTERN.sub("", " ".join(haystacks))
        missing = [n for n in _checkable_numbers(claim["text"]) if n not in blob]
        if missing:
            findings.append({
                "claim": claim["id"],
                "section": claim.get("section", ""),
                "supports": claim.get("supports", []),
                "numbers_not_in_any_cited_source": missing,
            })
    return findings


def _patent_tier(source: dict[str, Any]) -> str:
    """Legal-strength class of a patent, from bibliographic fields already held.

    A granted invention (`pub_kind` ending in B) sat substantive examination;
    a published application (A) has not yet; a utility model (U) never does.
    Empty for non-patents and for records that reached the ledger without a
    `pub_kind` — an unknown kind is not a weak one, and the check stays quiet.
    """
    if source.get("kind") != "patent":
        return ""
    code = str(source.get("pub_kind") or "").strip().upper()
    if code.endswith("U"):
        return "utility"
    if code.endswith("B"):
        return "granted"
    if code.endswith("A"):
        return "application"
    return ""


SENTENCE_SPLIT = re.compile(r"[。！？!?\n；;]+")


def _weak_patent_number_segments(text: str, live: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """Report numbers whose only citations in a sentence are low-tier patents.

    The claim-level check cannot see these: engineering parameters ride into
    the ledger inside fulltext notes and are woven into prose at writing time,
    while the claim above them stays a qualitative multi-source aggregate.
    Sentence granularity keeps the attribution honest — a number counts as
    weakly anchored only when every citation in its own sentence is a weak
    patent; a paper, web page or granted patent alongside it is an anchor.
    Advisory, not a gate: it surfaces in the renumber payload for the host to
    weigh, because cross-validation versus an honest "design assertion" label
    is a judgement call, and the limitation section is a legitimate answer.
    """
    findings: list[dict[str, Any]] = []
    for segment in SENTENCE_SPLIT.split(text):
        cited = sorted({int(m.group(1)) for m in CITE_TOKEN.finditer(segment)})
        if not cited:
            continue
        numbers = _checkable_numbers(segment)
        if not numbers:
            numbers = [m.group() for m in UNIT_SCOPED_NUMBER.finditer(segment)]
        if not numbers:
            continue
        tiers = {n: _patent_tier(live[n]) for n in cited}
        weak = {
            n: t for n, t in tiers.items()
            if t == "utility" or (t == "application" and not live[n].get("assignee"))
        }
        if weak and len(weak) == len(cited):
            findings.append({
                "sentence": segment.strip()[:120],
                "numbers": numbers,
                "sources": [{"n": n, "tier": t} for n, t in weak.items()],
            })
    return findings


def _claims_weak_patent_sole_support(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Quantitative claims whose only anchor is a low-tier patent.

    The patent channel cannot sort by quality (papers order by citations or
    year; `patent_search` returns plain relevance), so quality screening has
    to happen after ingestion — and this check is its teeth. A number vouched
    for solely by a utility model, never substantively examined, or by an
    unassigned published application is a design assertion, not a verified
    parameter: cross-validate it, or let the report say which it is.
    """
    by_number = {source["n"]: source for source in state["sources"]}
    findings: list[dict[str, Any]] = []
    for claim in _live_claims(state):
        supports = claim.get("supports", [])
        if len(supports) != 1:
            continue
        source = by_number.get(supports[0])
        if not source or source.get("kind") != "patent":
            continue
        numbers = _checkable_numbers(claim["text"])
        units = [m.group() for m in UNIT_SCOPED_NUMBER.finditer(claim["text"])]
        if not (numbers or units):
            continue  # a qualitative claim may rest where it likes; a number may not
        tier = _patent_tier(source)
        if tier == "utility" or (tier == "application" and not source.get("assignee")):
            findings.append({
                "claim": claim["id"],
                "section": claim.get("section", ""),
                "source": source["n"],
                "tier": tier,
                "assignee": bool(source.get("assignee")),
                "numbers": numbers or units,
            })
    return findings


# --------------------------------------------------------------------------- figures


def _live_figures(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [f for f in state["figures"] if not f.get("dropped")]


def _figure_index(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f["id"]: f for f in state["figures"] if f.get("id")}


def _record_figure(
    state: dict[str, Any],
    section: str,
    chart_type: str,
    title: str,
    data: Any,
    sources: list[int],
    claims: list[str],
    code_path: str,
    from_datums: bool = False,
    from_metadata: bool = False,
    plan: str = "",
    charted_by: str = "",
    charted_reason: str = "",
) -> dict[str, Any]:
    if not title.strip():
        raise LedgerError("A figure needs a non-empty --title")
    # Who ran this chart's loop. The engine cannot see whether a subagent was
    # actually dispatched, so the declaration is the ceiling — same shape as
    # verify's "who judges": forced at entry, reported by Appendix C. The
    # controller-session form is the exception that must state itself.
    if charted_by not in ("", "agent", "controller"):
        raise LedgerError("--charted-by must be 'agent' or 'controller'")
    if charted_reason and not charted_by:
        raise LedgerError("--charted-reason needs --charted-by (which mode ran this loop)")
    if charted_by == "controller" and not charted_reason.strip():
        raise LedgerError(
            "Charting in the controller session is the exception, not the default — "
            "it needs --charted-reason (why no chart-topic subagent ran this plan); "
            "see references/chart-guide.md §Who charts"
        )
    section = _require_sections(state, [section])[0]
    numbers = {source["n"] for source in state["sources"]}
    unknown = [n for n in sources if n not in numbers]
    if unknown:
        raise LedgerError(f"Unknown source number(s): {', '.join(str(n) for n in unknown)}")
    if not sources:
        raise LedgerError("A figure needs at least one --supports source (its data must be sourced)")
    claim_ids = {c["id"] for c in state["claims"]}
    bad_claims = [c for c in claims if c not in claim_ids]
    if bad_claims:
        raise LedgerError(f"Unknown claim id(s): {', '.join(bad_claims)}")
    if not code_path and chart_type not in FIGURE_TYPES:
        raise LedgerError(
            f"No template for chart_type '{chart_type}'. Supported: {', '.join(FIGURE_TYPES)}; "
            f"for other shapes supply --code <path> (a B script)."
        )
    figure = {
        "id": f"f{len(state['figures']) + 1}",
        "section": section,
        "chart_type": chart_type,
        "title": title.strip(),
        "data": data,
        "source_ids": sorted(set(sources)),
        "claim_ids": sorted(set(claims)),
        "rendered": False,
        "rendered_by": None,
        "from_datums": from_datums,
        "from_metadata": from_metadata,
    }
    if code_path:
        figure["code_path"] = code_path
    if charted_by:
        figure["charted_by"] = charted_by
        if charted_reason.strip():
            figure["charted_reason"] = charted_reason.strip()
    state["figures"].append(figure)
    if plan:
        _link_figure_plan(state, figure, plan)
    return figure


def _mark_figure_rendered(state: dict[str, Any], fid: str, path: str, by: str) -> dict[str, Any]:
    by_id = _figure_index(state)
    figure = by_id.get(fid)
    if figure is None:
        raise LedgerError(f"Unknown figure id '{fid}'. Valid ids: {', '.join(by_id) or 'none'}")
    if by not in ("script", "template"):
        raise LedgerError("--by must be 'script' or 'template'")
    figure["render_path"] = path
    figure["rendered"] = True
    figure["rendered_by"] = by
    return figure


def _drop_figures(state: dict[str, Any], ids: list[str], reason: str) -> dict[str, Any]:
    by_id = _figure_index(state)
    unknown = [i for i in ids if i not in by_id]
    if unknown:
        raise LedgerError(f"Unknown figure id(s): {', '.join(unknown)}. Valid: {', '.join(by_id) or 'none'}")
    dropped: list[str] = []
    for fid in dict.fromkeys(ids):
        figure = by_id[fid]
        if figure.get("dropped"):
            continue
        figure["dropped"] = True
        if reason:
            figure["drop_reason"] = reason
        dropped.append(fid)
        # the plan's data did not vanish with the figure — reopen it so the
        # topic can be re-charted without re-planning
        plan_id = figure.get("plan")
        if plan_id:
            plan = next((p for p in state.get("figure_plans", []) if p.get("id") == plan_id), None)
            if plan and plan.get("status") == "fulfilled":
                plan["status"] = "open"
                plan["figure_id"] = None
    return {"dropped": dropped, "remaining": len(_live_figures(state))}


def _datum_numeric(value: Any) -> float | None:
    """A datum value as a float, resolving 万 / 亿 myriad suffixes. None if not
    numeric — a non-numeric datum belongs in a timeline, not a bar."""
    if value is None:
        return None
    s = str(value).strip()
    try:
        return float(s)
    except ValueError:
        pass
    for suffix, mult in (("万", 1e4), ("亿", 1e8)):
        if s.endswith(suffix):
            try:
                return float(s[: -len(suffix)]) * mult
            except ValueError:
                return None
    return None


def _live_datums(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [d for d in state.get("datums", []) if not d.get("dropped")]


def _public_datum(datum: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in datum.items() if k != "dropped"}


def _record_datum(
    state: dict[str, Any],
    source: int,
    metric: str,
    value: str,
    unit: str,
    year: str,
    entity: str,
    plan: str = "",
) -> dict[str, Any]:
    if not metric.strip():
        raise LedgerError("A datum needs a non-empty --metric (what the number measures)")
    if not str(value).strip():
        raise LedgerError("A datum needs a non-empty --value")
    numbers = {s["n"] for s in state["sources"]}
    if source not in numbers:
        raise LedgerError(f"Unknown source number: {source}")
    if plan:
        planned = _require_plan(state, plan)
        if planned.get("status") == "abandoned":
            raise LedgerError(
                f"{plan} is abandoned ({planned.get('reason')}); if this number shows the topic "
                "is obtainable after all, re-plan the topic (the new plan retires this dead "
                "record) instead of feeding a dead plan"
            )
    datum = {
        "id": f"d{len(state.get('datums', [])) + 1}",
        "source": source,
        "metric": metric.strip(),
        "value": str(value).strip(),
        "unit": unit.strip(),
        "year": year.strip(),
        "entity": entity.strip(),
    }
    if plan:
        datum["plan"] = plan
    state.setdefault("datums", []).append(datum)
    return datum


def _drop_datums(state: dict[str, Any], ids: list[str], reason: str) -> dict[str, Any]:
    by_id = {d["id"]: d for d in state.get("datums", []) if d.get("id")}
    unknown = [i for i in ids if i not in by_id]
    if unknown:
        raise LedgerError(f"Unknown datum id(s): {', '.join(unknown)}. Valid: {', '.join(by_id) or 'none'}")
    dropped: list[str] = []
    for did in dict.fromkeys(ids):
        datum = by_id[did]
        if datum.get("dropped"):
            continue
        datum["dropped"] = True
        if reason:
            datum["drop_reason"] = reason
        dropped.append(did)
    return {"dropped": dropped, "remaining": len(_live_datums(state))}


# ── figure plans: the chart-topic stage between outline and retrieval ──
# The user-facing contract: once the outline is settled, the agent walks it and
# decides where a figure is needed AND insertable, records one plan per chart
# topic, then retrieves on that topic until the data is sufficient (or gives up
# with a recorded reason). Plans make "which numbers to hunt" a ledger-visible
# obligation instead of an afterthought at figure time.


def _live_plans(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in state.get("figure_plans", []) if not p.get("dropped")]


def _plan_datums(state: dict[str, Any], plan_id: str) -> list[dict[str, Any]]:
    return [d for d in _live_datums(state) if d.get("plan") == plan_id]


def _require_plan(state: dict[str, Any], plan_id: str) -> dict[str, Any]:
    by_id = {p["id"]: p for p in state.get("figure_plans", []) if p.get("id")}
    if plan_id not in by_id:
        raise LedgerError(
            f"Unknown figure plan id: {plan_id}. Valid: {', '.join(by_id) or 'none'}"
        )
    return by_id[plan_id]


def _add_figure_plan(
    state: dict[str, Any], section: str, topic: str, chart_type: str,
) -> tuple[dict[str, Any], list[str]]:
    if not topic.strip():
        raise LedgerError("A figure plan needs a non-empty --topic (the quantitative question the chart answers)")
    section = _require_sections(state, [section])[0]
    if chart_type and chart_type not in FIGURE_TYPES:
        raise LedgerError(f"Unknown chart type '{chart_type}'; use one of: {', '.join(FIGURE_TYPES)}")
    plan_id = f"fp{len(state.get('figure_plans', [])) + 1}"
    superseded: list[str] = []
    for plan in _live_plans(state):
        if plan.get("topic", "").strip() != topic.strip() or plan.get("section") != section:
            continue
        if plan.get("status") != "abandoned":
            raise LedgerError(
                f"{plan['id']} already plans '{topic.strip()}' for section {section}"
            )
        # An abandoned plan must not block re-planning its own topic: the
        # datum/figure error texts tell the user to re-plan, so the re-plan
        # has to work. Retire the dead record (one live plan per topic+
        # section stays invariant; the retire reason keeps the trail) —
        # dropped-plan plumbing was already honoured by every consumer,
        # only the setter was missing.
        plan["dropped"] = True
        plan["drop_reason"] = f"superseded by {plan_id} (topic re-planned)"
        superseded.append(plan["id"])
    plan = {
        "id": plan_id,
        "section": section,
        "topic": topic.strip(),
        "chart_type": chart_type,
        "status": "open",
        "reason": "",
        "figure_id": None,
    }
    state.setdefault("figure_plans", []).append(plan)
    return plan, superseded


def _abandon_figure_plan(state: dict[str, Any], plan_id: str, reason: str) -> dict[str, Any]:
    plan = _require_plan(state, plan_id)
    if not reason.strip():
        raise LedgerError(
            "Abandoning a figure plan needs a --reason — an unobtainable topic must be "
            "recorded, not silently dropped (the report's limitations quote it)"
        )
    if plan.get("status") == "fulfilled":
        raise LedgerError(
            f"{plan_id} is already fulfilled by {plan.get('figure_id')}; drop that figure "
            "first if the plan must reopen"
        )
    plan["status"] = "abandoned"
    plan["reason"] = reason.strip()
    return plan


def _link_figure_plan(state: dict[str, Any], figure: dict[str, Any], plan_id: str) -> None:
    plan = _require_plan(state, plan_id)
    if plan.get("status") == "abandoned":
        raise LedgerError(
            f"{plan_id} is abandoned ({plan.get('reason')}); plan the topic again (the new "
            "plan retires this dead record) instead of fulfilling a "
            "recorded-as-unobtainable plan"
        )
    figure["plan"] = plan_id
    plan["status"] = "fulfilled"
    plan["figure_id"] = figure["id"]


def _assemble_figure_data(
    state: dict[str, Any], datum_ids: list[str], chart_type: str,
) -> tuple[Any, list[int]]:
    """Build a figure's --data and its source list from captured datums. Each
    datum already cites a source, so the assembled numbers are source-verified
    by construction — the figure is exempt from figures_with_unsourced_numbers."""
    by_id = {d["id"]: d for d in _live_datums(state)}
    unknown = [i for i in datum_ids if i not in by_id]
    if unknown:
        raise LedgerError(f"Unknown datum id(s): {', '.join(unknown)}. Valid: {', '.join(by_id) or 'none'}")
    datums = [by_id[i] for i in dict.fromkeys(datum_ids)]
    if chart_type in ("bar", "hbar", "pie"):
        out = []
        for d in datums:
            v = _datum_numeric(d.get("value"))
            if v is None:
                raise LedgerError(
                    f"datum {d['id']} value {d.get('value')!r} is not numeric; "
                    f"use --type timeline for non-numeric / dated data"
                )
            out.append({"label": d.get("entity") or d.get("metric", ""), "value": v})
        data: Any = out
    elif chart_type == "timeline":
        data = [
            {
                "date": d.get("year") or d.get("value", ""),
                "event": f"{d.get('entity') or d.get('metric', '')}: {d.get('value', '')}{d.get('unit', '')}",
                "group": d.get("metric", ""),
            }
            for d in datums
        ]
    elif chart_type == "line":
        series: dict[str, list[dict[str, Any]]] = {}
        for d in datums:
            v = _datum_numeric(d.get("value"))
            if v is None:
                raise LedgerError(
                    f"datum {d['id']} value {d.get('value')!r} is not numeric; "
                    f"use --type timeline for non-numeric / dated data"
                )
            series.setdefault(d.get("metric", ""), []).append({"x": d.get("year", ""), "y": v})
        data = [
            {"series": m, "points": sorted(pts, key=lambda p: str(p["x"]))}
            for m, pts in series.items()
        ]
    else:
        raise LedgerError(
            f"--from-datums assembles bar / hbar / pie / line / timeline, not '{chart_type}'; "
            f"for {chart_type} pass --data directly"
        )
    sources = sorted({d["source"] for d in datums})
    return data, sources


def _source_metadata_label(source: dict[str, Any], field: str) -> str | None:
    """One aggregation label for a source along a metadata field, or None when
    the source carries no value for it. `year` and `venue` are scalars; the
    patent rights-holder lives under `assignee` (a list of names) — its primary
    holder is the label, the way a player table would file it."""
    if field == "year":
        y = source.get("year")
        return str(y) if isinstance(y, int) else None
    if field == "venue":
        v = source.get("venue")
        return v.strip() if isinstance(v, str) and v.strip() else None
    if field == "assignee":
        holders = source.get("assignee")
        if isinstance(holders, list) and holders and isinstance(holders[0], str):
            return holders[0].strip() or None
        if isinstance(holders, str) and holders.strip():
            return holders.strip()
        return None
    if field == "kind":
        k = source.get("kind")
        return k.strip() if isinstance(k, str) and k.strip() else None
    return None


def _assemble_metadata_figure(
    state: dict[str, Any], source_nums: list[int], field: str, chart_type: str,
) -> tuple[Any, list[int]]:
    """Build a figure's --data by counting how the given sources fall along a
    metadata field — patents per application year, filings per assignee, papers
    per venue. The counts come from the ledger's own source records, so the
    numbers are source-verified by construction and the figure is exempt from
    `figures_with_unsourced_numbers` (the same exemption `--from-datums` gets)."""
    if field not in ("year", "venue", "assignee", "kind"):
        raise LedgerError(
            f"--from-source-metadata aggregates by year / venue / assignee / kind, not '{field}'"
        )
    by_number = {s["n"]: s for s in state["sources"]}
    counts: dict[str, int] = {}
    used: list[int] = []
    for n in dict.fromkeys(source_nums):
        source = by_number.get(n)
        if source is None:
            raise LedgerError(f"Unknown source number(s): {n}")
        label = _source_metadata_label(source, field)
        if not label:
            continue
        counts[label] = counts.get(label, 0) + 1
        used.append(n)
    if not counts:
        raise LedgerError(
            f"None of the given sources carry a '{field}' value to aggregate; "
            f"capture the field first (patents need a patent_detail call)"
        )
    if chart_type not in ("bar", "hbar", "pie"):
        raise LedgerError(
            f"--from-source-metadata assembles bar / hbar / pie, not '{chart_type}'; "
            f"for {chart_type} pass --data directly"
        )
    items = [{"label": label, "value": value} for label, value in counts.items()]
    if field == "year":
        items.sort(key=lambda it: it["label"])            # chronological left→right
    else:
        items.sort(key=lambda it: (-it["value"], it["label"]))  # count desc, then name
    data: Any = items
    sources = sorted(set(used))
    return data, sources


def _figure_data_text(figure: dict[str, Any]) -> str:
    """Serialise a figure's data to text so the number-provenance check can
    run over it with the same machinery it uses for claim prose."""
    return json.dumps(figure.get("data"), ensure_ascii=False)


def _figure_source_numbers(state: dict[str, Any], figure: dict[str, Any]) -> list[int]:
    """Every source number a figure's data leans on: its own source_ids plus
    the supports of the claims it visualises. Same haystack a claim uses."""
    by_id = {c["id"]: c for c in state["claims"]}
    nums = set(figure.get("source_ids", []))
    for cid in figure.get("claim_ids", []):
        claim = by_id.get(cid)
        if claim:
            nums.update(claim.get("supports", []))
    return sorted(nums)


def _figures_with_unsourced_numbers(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Figures whose data carries numbers that appear in none of their sources.

    The same check `claims_with_unsourced_numbers` runs over claim prose, now
    over a figure's serialised data — so a chart cannot smuggle in a number the
    ledger never sourced. A warning, not a gate, for the same reason as claims:
    a unit conversion or a myriad-unit rescale lands here too.
    """
    by_number = {source["n"]: source for source in state["sources"]}
    findings: list[dict[str, Any]] = []
    for figure in _live_figures(state):
        if figure.get("from_datums") or figure.get("from_metadata"):
            continue  # assembled from captured datums / ledger metadata; counts are source-verified by construction
        nums = _figure_source_numbers(state, figure)
        haystacks = [by_number[n] for n in nums if n in by_number]
        texts = [_source_text(s) for s in haystacks]
        if not any(t.strip() for t in texts):
            continue  # nothing was ever read for these sources; other warnings cover that
        blob = DIGIT_RUN_PATTERN.sub("", " ".join(texts))
        missing = [n for n in _checkable_numbers(_figure_data_text(figure)) if n not in blob]
        if missing:
            findings.append({
                "figure": figure["id"],
                "section": figure.get("section", ""),
                "source_ids": nums,
                "numbers_not_in_any_cited_source": missing,
            })
    return findings


def _figures_thin_data(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Figures whose data has too few points to plot meaningfully.

    `figures_with_unsourced_numbers` asks whether a figure's numbers are
    sourced; this asks whether there are enough of them to be a chart at all —
    a one-bar bar chart or a one-point line is a defect, not a figure. A
    structural figure (timeline) needs >=2 events. A custom B-script shape (no
    matching template type) is not structurally checked here; the provenance
    and divergence checks still apply to it.
    """
    findings: list[dict[str, Any]] = []
    for figure in _live_figures(state):
        ct = figure.get("chart_type", "")
        data = figure.get("data")
        thin = False
        if ct in ("bar", "hbar", "pie"):
            if isinstance(data, dict) and isinstance(data.get("items"), list):
                # grouped bar: {series, items:[{label, values}]} — thin if <2 items
                thin = len(data["items"]) < 2
            else:
                thin = not isinstance(data, list) or len(data) < 2
        elif ct == "line":
            if isinstance(data, list):
                series_list = data
            elif isinstance(data, dict):
                series_list = [data]
            else:
                series_list = []
            pts = sum(len(s.get("points", [])) for s in series_list if isinstance(s, dict))
            thin = pts < 2
        elif ct == "heatmap":
            rows = len(data.get("rows", [])) if isinstance(data, dict) else 0
            cols = len(data.get("cols", [])) if isinstance(data, dict) else 0
            thin = rows < 2 or cols < 2
        elif ct == "timeline":
            thin = not isinstance(data, list) or len(data) < 2
        else:
            continue  # custom B-script shape: structure unknown, other checks apply
        if thin:
            findings.append({
                "figure": figure["id"],
                "section": figure.get("section", ""),
                "chart_type": ct,
                "minimum_points": 2,
            })
    return findings


def _figure_code_divergence(state: dict[str, Any]) -> list[dict[str, Any]]:
    """A B script that hardcodes a number the registered data does not carry.

    Heuristic and deliberately a warning, not a gate: it reads the script text
    and flags 3-plus-digit literals absent from the figure's data blob. A real
    divergence check would hook the script's plotting calls; this catches the
    obvious 'the script baked in a different figure' without running anything.
    Figures without a code_path are unaffected.
    """
    findings: list[dict[str, Any]] = []
    for figure in _live_figures(state):
        code_path = figure.get("code_path")
        if not code_path:
            continue
        path = Path(code_path)
        if not path.exists():
            continue
        data_blob = _figure_data_text(figure)
        script_text = path.read_text(encoding="utf-8")
        extra = [n for n in _checkable_numbers(script_text) if n not in data_blob]
        if extra:
            findings.append({
                "figure": figure["id"],
                "code_path": code_path,
                "numbers_in_script_not_in_data": extra,
            })
    return findings


def _figures_by_section(state: dict[str, Any]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for top in state["outline"]:
        for sid in (top["id"], *(kid["id"] for kid in top["children"])):
            grouped.setdefault(sid, [])
    for figure in _live_figures(state):
        sid = figure.get("section", "")
        if sid in grouped:
            grouped[sid].append(figure["id"])
    return grouped


def _probe_yield(state: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Per-probe kept/dropped counts, read off the sources themselves.

    Derived rather than counted at add time so it stays correct after `drop`,
    which is exactly when drift becomes visible.
    """
    tally: dict[str, dict[str, int]] = {p["id"]: {"kept": 0, "dropped": 0} for p in state["probes"]}
    for source in state["sources"]:
        bucket = "dropped" if source.get("dropped") else "kept"
        for pid in source.get("probes", []):
            if pid in tally:
                tally[pid][bucket] += 1
    return tally


def _drifting_probes(state: dict[str, Any]) -> list[dict[str, Any]]:
    tally = _probe_yield(state)
    out: list[dict[str, Any]] = []
    for probe in state["probes"]:
        counts = tally[probe["id"]]
        returned = counts["kept"] + counts["dropped"]
        if returned < DRIFT_MIN_RETURNED:
            continue
        rate = counts["dropped"] / returned
        if rate >= DRIFT_RATIO:
            out.append({
                "probe": probe["id"],
                "axis": probe.get("axis", ""),
                "query": probe.get("query", ""),
                "returned": returned,
                "kept": counts["kept"],
                "dropped": counts["dropped"],
                "drop_rate": round(rate, 2),
            })
    return out


# ────────────────────────────────────────────────── research-loop telemetry
# The evaluate half of the DeepDive quality chain, translated to this ledger:
# judgments are the host's, but every number the host judges against is
# computed here (`signals`), every stop/continue call is recorded (`decide`),
# every round ends with a summary (`round`), and the tier the host picks caps
# directions and rounds by refusal (`tier`). Kernels ported from
# prompts/evaluate.py keep their thresholds; the read side is adapted to this
# ledger's collections (top-level sections = directions, claims = findings).


def _tier_profile(state: dict[str, Any]) -> dict[str, int] | None:
    tier = state.get("tier") or ""
    return TIER_PROFILES.get(tier)


def _effective_rounds(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Rounds that count against the tier caps. A round the host marks wasted
    (a failed reformulation, an aborted axis) consumed budget but produced
    nothing — DeepDive's orchestrator likewise does not charge a wasted run
    against a direction's effective rounds."""
    return [r for r in state.get("rounds", []) if not r.get("wasted")]


def _register_tier(state: dict[str, Any], level: str, reason: str, force: bool) -> dict[str, Any]:
    """Record the host's complexity judgment. The engine never judges
    complexity itself — but once the tier is registered, the outline and round
    clamps bind, which is the orchestrator half of the port. Re-judging is
    refused without --force: an unbound upgrade would quietly un-clamp a run
    already in flight. A forced re-judgment is kept in tier_changes for audit."""
    if level not in TIERS:
        raise LedgerError(f"Unknown tier '{level}'; use one of: {', '.join(TIERS)}")
    if not reason.strip():
        raise LedgerError("Registering a tier needs a --reason — the judgment must be on record")
    current = state.get("tier") or ""
    if current and current != level and not force:
        raise LedgerError(
            f"Tier already registered as '{current}'; re-judging needs --force "
            "(the clamps are bound to the registered tier)"
        )
    state["tier"] = level
    state["tier_reason"] = reason.strip()
    if current and current != level:
        state.setdefault("tier_changes", []).append({"from": current, "to": level, "reason": reason.strip()})
    return {"ok": True, "tier": level, "profile": TIER_PROFILES[level]}


def _check_direction_cap(state: dict[str, Any], would_be: int) -> None:
    """The directions clamp: outline top-level sections are the directions,
    and an outline that exceeds the registered tier's ceiling is refused —
    the engine equivalent of DeepDive's orchestrator refusing to schedule
    directions past max_directions. Without a registered tier there is no
    clamp; `check` warns tier_missing instead."""
    profile = _tier_profile(state)
    if profile and would_be > profile["max_directions"]:
        raise LedgerError(
            f"Tier '{state.get('tier')}' allows at most {profile['max_directions']} top-level "
            f"sections (directions); this outline would have {would_be}. Register a higher "
            f"tier with --force if the question genuinely grew, or merge sections."
        )


def _register_round(
    state: dict[str, Any],
    why_stopped: str,
    next_queries: list[str],
    directions: list[str],
    probes: list[str],
    wasted: bool,
    note: str,
) -> dict[str, Any]:
    """Close a retrieval round with a summary. This is the telemetry that
    replaces DeepDive's just-completed-run block (stop_reason / tool_stats /
    new_queries): which sections the round served, which probes ran (their
    yield is already in the probe records), why the round ended, and what the
    next round should hunt. The global and per-direction caps refuse a round
    that would exceed the registered tier — the rounds clamp of the port.

    There is no wall clock and no tool budget in this architecture, so a
    "forced stop" cannot be observed by the engine; --why-stopped is the
    self-reported approximation, and a round cut short by circumstances says
    so there (recorded as a design difference, not faked as a signal)."""
    why_stopped = why_stopped.strip()
    if not why_stopped:
        raise LedgerError(
            "A round summary needs a non-empty --why-stopped — 'why did this round end' "
            "is the one signal the engine cannot compute"
        )
    tops = {top["id"] for top in state["outline"]}
    unknown = [d for d in directions if d not in tops]
    if unknown:
        raise LedgerError(
            f"--direction must be top-level section ids (directions): {', '.join(unknown)} "
            f"is not one. Valid: {', '.join(sorted(tops)) or 'none'}"
        )
    probe_ids = {p["id"] for p in state["probes"]}
    unknown_p = [p for p in probes if p not in probe_ids]
    if unknown_p:
        raise LedgerError(f"Unknown probe id(s): {', '.join(unknown_p)}")

    rounds = state.setdefault("rounds", [])
    effective = _effective_rounds(state)
    profile = _tier_profile(state)
    if profile and not wasted:
        if len(effective) >= profile["max_rounds"]:
            raise LedgerError(
                f"Tier '{state.get('tier')}' caps the run at {profile['max_rounds']} effective "
                f"rounds and {len(effective)} are already registered. Write the report from "
                f"what the ledger holds (or register a higher tier with --force if the "
                f"question genuinely grew)."
            )
        used_by_direction: dict[str, int] = {}
        for r in effective:
            for d in r.get("directions", []):
                used_by_direction[d] = used_by_direction.get(d, 0) + 1
        over = [d for d in directions if used_by_direction.get(d, 0) >= profile["max_runs_per_direction"]]
        if over:
            raise LedgerError(
                f"Tier '{state.get('tier')}' caps each direction at "
                f"{profile['max_runs_per_direction']} effective rounds; exceeded for section(s) "
                f"{', '.join(over)}. Serve the remaining sections without them, or re-judge "
                f"the tier with --force."
            )

    entry = {
        "n": len(rounds) + 1,
        "directions": list(dict.fromkeys(directions)),
        "probes": list(dict.fromkeys(probes)),
        "why_stopped": why_stopped,
        "next_queries": [q.strip() for q in next_queries if q.strip()],
    }
    if wasted:
        entry["wasted"] = True
    if note.strip():
        entry["note"] = note.strip()
    rounds.append(entry)
    return {
        "ok": True,
        "round": entry,
        "effective_rounds": len(_effective_rounds(state)),
        "rounds_cap": profile["max_rounds"] if profile else None,
    }


def _add_memo(state: dict[str, Any], section: str, text: str) -> dict[str, Any]:
    """The direction-level depth memo — the slot DeepDive gives its sub-agents
    so the depth gained by reading the originals survives into evaluation and
    writing. The engine guarantees the slot and the existence signal
    (`sections_without_memo`); what goes in it is prompt discipline, stated in
    research-loop.md: you are the only one who read the originals in full —
    what you do not write down here is lost at this hop forever."""
    text = text.strip()
    if not text:
        raise LedgerError("A memo needs non-empty --text")
    top = _find_top(state, section)
    memo = {
        "id": f"m{len(state.get('memos', [])) + 1}",
        "section": top["id"],
        "text": text,
    }
    state.setdefault("memos", []).append(memo)
    return {"ok": True, "memo": memo}


def _record_decision(state: dict[str, Any], action: str, direction: str, reason: str) -> dict[str, Any]:
    """Log one 'read the signals, then decided' call. The decision is the
    host's; recording it is what lets the next `signals` replay the last five
    decisions — the anti-repeat half of the DeepDive evaluation history."""
    if action not in DECISION_ACTIONS:
        raise LedgerError(f"Unknown action '{action}'; use one of: {', '.join(DECISION_ACTIONS)}")
    reason = reason.strip()
    if not reason:
        raise LedgerError("A decision needs a non-empty --reason")
    if direction:
        _find_top(state, direction)
    decision = {
        "n": len(state.get("decisions", [])) + 1,
        "action": action,
        "reason": reason,
    }
    if direction:
        decision["direction"] = direction
    state.setdefault("decisions", []).append(decision)
    return {"ok": True, "decision": decision}


def _apply_verify(state: dict[str, Any], entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Record citation-faithfulness judgments and execute the gates.

    The judgment is the host's — for each claim, does the evidence actually
    support the statement (numbers line up, right entity, right time)? The
    gates are the engine's, ported from verify.py: a "not supported" verdict
    only downgrades when confidence >= VERIFY_DOWNGRADE_MIN_CONFIDENCE, and a
    batch never downgrades more than VERIFY_MAX_DOWNGRADE_RATIO of its
    candidates (floor 1) — beyond the cap only the most confident failures
    downgrade, the rest fall back to inconclusive (NOT passed: the judge was
    sure, the backstop spared them). One `verify` call is one batch, the
    unit the ratio guard sees.
    """
    by_id = {claim["id"]: claim for claim in state["claims"]}
    if not entries:
        raise LedgerError("verify needs judgments: pass --claim/--supported/--confidence or --batch JSON")
    checked: list[dict[str, Any]] = []
    for pos, item in enumerate(entries, start=1):
        if not isinstance(item, dict):
            raise LedgerError(f"verify entry {pos} must be a JSON object")
        cid = str(item.get("claim") or "").strip()
        claim = by_id.get(cid)
        if claim is None:
            raise LedgerError(f"verify entry {pos}: unknown claim '{cid}'. Valid: {', '.join(by_id) or 'none'}")
        if claim.get("retracted"):
            raise LedgerError(f"verify entry {pos}: claim {cid} is retracted; verify live claims")
        supported = bool(item.get("supported"))
        try:
            confidence = float(item.get("confidence"))
        except (TypeError, ValueError):
            raise LedgerError(
                f"verify entry {pos} (claim {cid}): confidence must be a number in [0, 1]"
            ) from None
        if not 0.0 <= confidence <= 1.0:
            raise LedgerError(f"verify entry {pos} (claim {cid}): confidence must be in [0, 1]")
        reason = str(item.get("reason") or "").strip()
        if not supported and not reason:
            # A downgrade without a stated why is unauditable — the reader of
            # the appendix cannot tell a caught hallucination from a grudge.
            raise LedgerError(
                f"verify entry {pos} (claim {cid}): an unsupported verdict needs a --reason"
            )
        checked.append({
            "claim": claim,
            "supported": supported,
            "confidence": confidence,
            "reason": reason,
        })

    # Gate 1 — 疑罪从无: only a confident "not supported" is a downgrade
    # candidate; a low-confidence False is "not sure" and passes.
    confident_fail: list[tuple[dict[str, Any], float]] = []
    stats = {"checked": 0, "passed": 0, "downgraded": 0, "inconclusive": 0}
    for item in checked:
        claim = item["claim"]
        claim["verified"] = True
        claim["verify_confidence"] = item["confidence"]
        claim["verify_reason"] = item["reason"]
        stats["checked"] += 1
        if item["supported"]:
            claim["verify_status"] = "passed"
            stats["passed"] += 1
        elif item["confidence"] >= VERIFY_DOWNGRADE_MIN_CONFIDENCE:
            confident_fail.append((claim, item["confidence"]))
            claim["verify_status"] = "downgraded"  # gate 2 may still spare it
        else:
            claim["verify_status"] = "inconclusive"
            stats["inconclusive"] += 1

    # Gate 2 — the ratio backstop: cap = max(1, floor(ratio × candidates)) so
    # the reference list is never wiped by a systematically harsh judge, while
    # a lone confident hallucination still cannot survive.
    if confident_fail:
        cap = max(1, int(VERIFY_MAX_DOWNGRADE_RATIO * len(checked)))
        to_downgrade = confident_fail
        if len(confident_fail) > cap:
            ranked = sorted(confident_fail, key=lambda x: x[1], reverse=True)
            to_downgrade = ranked[:cap]
            for claim, _conf in ranked[cap:]:
                claim["verify_status"] = "inconclusive"
                stats["inconclusive"] += 1
        for claim, _conf in to_downgrade:
            stats["downgraded"] += 1

    return {"ok": True, **stats,
            "gates": {"min_confidence": VERIFY_DOWNGRADE_MIN_CONFIDENCE,
                      "max_downgrade_ratio": VERIFY_MAX_DOWNGRADE_RATIO}}


# ─────────────────────────────────────────────────────── the signals surface
# `signals` prints the evaluator input surface: every block is computed here,
# none of it is asserted by the host. Kernels below keep their upstream
# thresholds and comments (prompts/evaluate.py); what changed is only the
# collections they read. Blocks whose input was never registered report null
# — "not recorded", never a misleading 0.


def _fold_for_match(text: str) -> str:
    """Whitespace-insensitive comparison key with typographic variants folded:
    curly/straight quotes, dashes, ellipses, middle dots, and commas — both
    widths, both uses ("1,000" ≡ "1000" is a formatting variant, the same rule
    the number matcher applies; a full-width clause comma ， in the source
    becoming an ASCII , in a retyped quote is the same class of noise). A
    quote retyped by the host must still match the source text that paid for
    it; a run was forced into retracts over exactly these variants."""
    folded = text.casefold()
    for src, dst in (("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"'),
                     ("„", '"'), ("–", "-"), ("—", "-"), ("―", "-"),
                     ("…", "..."), ("·", "."), ("・", ".")):
        folded = folded.replace(src, dst)
    folded = folded.replace(",", "").replace("，", "")
    return re.sub(r"\s+", "", folded)


def _claims_evidence_not_verbatim(state: dict[str, Any]) -> list[dict[str, Any]]:
    """M2 — claims whose recorded evidence is not a verbatim substring.

    The evidence field is nominally a quote from the source; a paraphrase or
    a rewrite typed from memory defeats the whole point. Each excerpt must
    appear (whitespace-insensitively, typographic variants folded) in at
    least one supporting source's stored text. Failing claims are downgraded
    to background information — marked in `render --final`, reported by
    `check`, excluded from the citable counts — not deleted: the judgment is
    "unusable as evidence", not "false". Computed live, never stored: a
    re-`add` that merges a richer abstract in can clear it, and the verdict
    must always reflect the ledger as it stands, not as it was.

    Degenerate excerpts — shorter than EVIDENCE_MIN_CHARS once folded — fail
    the same way: a one-character "quote" is a substring of nearly everything
    and proves nothing. Registration refuses them now; this arm catches
    ledgers written before that floor existed."""
    by_number = {source["n"]: source for source in state["sources"]}
    findings: list[dict[str, Any]] = []
    for claim in _live_claims(state):
        excerpts = claim.get("evidence") or []
        if not excerpts:
            continue
        supports = [by_number[n] for n in claim.get("supports", []) if n in by_number]
        haystack = _fold_for_match(" ".join(_source_text(s) for s in supports))
        failed = [e for e in excerpts if _fold_for_match(e) not in haystack]
        degenerate = [e for e in excerpts if len(_fold_for_match(e)) < EVIDENCE_MIN_CHARS]
        if failed or degenerate:
            findings.append({
                "claim": claim["id"],
                "section": claim.get("section", ""),
                "failed_evidence": [e[:120] for e in failed],
                "degenerate_evidence": [e[:120] for e in degenerate],
            })
    return findings


def _citable_scholarly_count(state: dict[str, Any]) -> int:
    """Scholarly sources that would actually enter the bibliography.

    Ported from _scholarly_citable_count: counting all academic sources
    over-counts — uncited ones, sources only a downgraded claim leans on, and
    (upstream) the same paper behind several URLs would all inflate the
    tally and the evaluator would judge "≥15, stop" early. Here a source
    counts when a live, non-downgraded claim cites it and it is not web.
    Dedup by URL is already done at ingestion by _source_key."""
    scholarly: set[int] = set()
    for claim in _live_claims(state):
        if _claim_downgraded(state, claim):
            continue
        for n in claim.get("supports", []):
            source = next((s for s in state["sources"] if s["n"] == n), None)
            if source and not source.get("dropped") and source.get("kind") != "web":
                scholarly.add(n)
    return len(scholarly)


def _claim_downgraded(state: dict[str, Any], claim: dict[str, Any]) -> bool:
    """A claim is background information when the host's verify gate
    downgraded it, or when its evidence failed the verbatim check — either
    way it must not carry a citation in the report."""
    if claim.get("verify_status") == "downgraded":
        return True
    if not claim.get("evidence"):
        return False
    return any(f["claim"] == claim["id"] for f in _claims_evidence_not_verbatim(state))


def _scholarly_ref_directive(state: dict[str, Any]) -> str:
    """The ≥15 soft target, ported from _scholarly_ref_directive: injected
    into evaluation while below target to push academic retrieval wider —
    best-effort, never a gate, never a license to fabricate. Academic genre
    only: an industry report's spine is the web and does not carry the
    scholarly target."""
    if state.get("genre", "academic") != "academic":
        return ""
    have = _citable_scholarly_count(state)
    if have >= SCHOLARLY_MIN_REFS:
        return ""
    return (
        f"Scholarly target for this genre: >= {SCHOLARLY_MIN_REFS} citable scholarly sources, "
        f"currently {have}. If not yet sufficient, prefer retrieval rounds that add academic "
        f"sources before judging the evidence sufficient; only wind up when genuinely no more "
        f"are obtainable (never pad the count with fabricated sources)."
    )


def _source_class(kind: str) -> str:
    """Upstream sorts sources into peer_reviewed/preprint/blog/web tiers; this
    ledger has no preprint split (an arXiv paper enters as a paper), so the
    diversity check works with three classes: academic, web, other. The
    weak-only rule maps to web-only — the recorded adaptation."""
    if kind in ("paper", "patent"):
        return "academic"
    if kind == "web":
        return "web"
    return "other"


def _direction_source_diversity(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-direction source diversity, ported from _direction_source_diversity:
    a direction whose citable claims rest on fewer than
    SINGLE_SOURCE_MIN_DISTINCT distinct sources, or on weak classes only, is
    single-source dependent — a restatement, not research. Upstream counts
    distinct normalized URLs per finding; this ledger already dedupes
    sources at ingestion (_source_key), so distinct source numbers are the
    same measure."""
    by_number = {source["n"]: source for source in state["sources"]}
    out: list[dict[str, Any]] = []
    for top in state["outline"]:
        nums: set[int] = set()
        n_claims = 0
        for claim in _live_claims(state):
            sid = claim.get("section", "")
            if sid != top["id"] and not sid.startswith(f"{top['id']}."):
                continue
            if _claim_downgraded(state, claim):
                continue
            n_claims += 1
            nums.update(n for n in claim.get("supports", []) if n in by_number)
        classes: dict[str, int] = {}
        for n in nums:
            cls = _source_class(by_number[n].get("kind", "paper"))
            classes[cls] = classes.get(cls, 0) + 1
        warn = ""
        # The weak-class arm is academic-genre only. Upstream's weak classes
        # are preprints and blogs — unreviewed prose; this ledger cannot see
        # that split, so "web" stands in for it. For an industry report that
        # stand-in is wrong: institutional pages, rankings and policy texts
        # are the spine of the genre, not a weakness, and flagging every
        # market/player/policy section as weak produced warnings a correct
        # run could only ignore. There, honesty rides on the number checks
        # (datums, provenance) instead of the class tally.
        weak_class_applies = state.get("genre", "academic") != "industry"
        if n_claims:
            if len(nums) < SINGLE_SOURCE_MIN_DISTINCT:
                warn = "single-source dependency — hunt independent corroboration or a counter-view, do not stop"
            elif weak_class_applies and classes and all(c in ("web", "other") for c in classes):
                warn = "all weak classes (web/other) — cross-validate with academic sources"
        out.append({
            "section": top["id"],
            "title": top["title"],
            "claims": n_claims,
            "distinct_sources": len(nums),
            "source_classes": classes,
            "warning": warn,
        })
    return out


def _evidence_quality(state: dict[str, Any]) -> dict[str, Any]:
    """Ported from _evidence_quality: breadth alone flatters a thin run —
    these counters let the evaluator judge depth and reliability instead:
    how many claims carry verbatim evidence, how many carry none, and how
    many were downgraded by the verify gates (a high downgrade count means
    statements kept outrunning their evidence)."""
    claims = _live_claims(state)
    sourced = [c for c in claims if c.get("supports")]
    with_ev = [c for c in sourced if c.get("evidence")]
    total_ev = sum(len(c.get("evidence") or []) for c in sourced)
    downgraded = [c for c in claims if _claim_downgraded(state, c)]
    return {
        "claims": len(claims),
        "sourced": len(sourced),
        "with_verbatim_evidence": len(with_ev),
        "without_verbatim_evidence": len(sourced) - len(with_ev),
        "avg_evidence_per_claim": round(total_ev / len(sourced), 1) if sourced else 0.0,
        "downgraded": len(downgraded),
    }


def _evaluation_history_view(state: dict[str, Any]) -> list[dict[str, Any]]:
    """The last five decisions, ported from _evaluation_history's window of 5:
    replaying them keeps the host from re-issuing a direction or a
    near-identical instruction that already failed."""
    decisions = state.get("decisions", [])
    return [
        {
            "n": d.get("n"),
            "action": d.get("action"),
            "direction": d.get("direction"),
            "sufficient": d.get("action") == "stop",
            "reason": (d.get("reason") or "")[:80],
        }
        for d in decisions[-5:]
    ]


def _verify_reason_stats(claims: list[dict[str, Any]]) -> dict[str, Any]:
    """Observation stats over verify reasons and confidences. Real per-claim
    checking produces varied reasons — claims fail in different ways. The
    rubber-stamp signature is *duplicated* reasons, not the single top one:
    a host that learns the top-reason warning exists just splits one template
    into two (a rerun did exactly that: ×14 '数字…锚定' + ×14 '证据摘录…锚定',
    top share 0.47, duplicated share 0.93). Confidence uniformity — every
    judgment at the same value — is the same signature on a second axis."""
    verified = [c for c in claims if c.get("verified")]
    if not verified:
        return {"verified": 0}
    counts: dict[str, int] = {}
    for c in verified:
        reason = c.get("verify_reason") or ""
        counts[reason] = counts.get(reason, 0) + 1
    duplicated = sum(n for n in counts.values() if n >= 2)
    conf_counts: dict[float, int] = {}
    for c in verified:
        conf = round(float(c.get("verify_confidence") or 0.0), 2)
        conf_counts[conf] = conf_counts.get(conf, 0) + 1
    top_conf, top_conf_n = max(conf_counts.items(), key=lambda kv: kv[1])
    return {
        "verified": len(verified),
        "distinct_reasons": len(counts),
        "duplicated_reason_share": round(duplicated / len(verified), 3),
        "top_reason_share": round(max(counts.values()) / len(verified), 3),
        "top_confidence": top_conf,
        "top_confidence_share": round(top_conf_n / len(verified), 3),
    }


def _memos_thin(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Directions whose latest memo is under the depth floor. The memo slot
    is structural; the discipline asks 600–1200 chars of mechanism, setups,
    numbers. A 400-char memo passes the existence check and still carries no
    depth — the same blind spot the prose floor closed for report bodies, so
    it closes the same way: the engine observes, `check` warns."""
    latest: dict[str, dict[str, Any]] = {}
    for memo in state.get("memos", []):
        latest[memo.get("section", "")] = memo
    return [
        {"section": sid, "memo": m.get("id"), "chars": len(m.get("text") or "")}
        for sid, m in latest.items()
        if len(m.get("text") or "") < MEMO_MIN_CHARS
    ]


def _signals(state: dict[str, Any]) -> dict[str, Any]:
    """The evaluator input surface — what the host reads before deciding
    whether to stop, rerun a section, or add one. Every number is computed
    here; blocks whose input was never registered are null ("not recorded"),
    never 0. Two upstream blocks are absent by design and say so: the user
    template outline (not yet a ledger concept) and mid-run user guidance
    (this architecture covers it natively — the user interjects, the host
    re-evaluates)."""
    profile = _tier_profile(state)
    effective = _effective_rounds(state)
    rounds = state.get("rounds", [])
    last_round = rounds[-1] if rounds else None

    claims = _live_claims(state)
    shown = claims[-SIGNALS_CLAIMS_SHOWN:]
    digest = []
    for claim in shown:
        digest.append({
            "id": claim["id"],
            "section": claim.get("section", ""),
            "text": (claim["text"][:100] + "…") if len(claim["text"]) > 100 else claim["text"],
            "supports": len(claim.get("supports", [])),
            "single_source": len(claim.get("supports", [])) == 1,
            "evidence": len(claim.get("evidence") or []),
            "downgraded": _claim_downgraded(state, claim),
        })

    tops = [top["id"] for top in state["outline"]]
    latest_memo: dict[str, dict[str, Any]] = {}
    for memo in state.get("memos", []):
        latest_memo[memo.get("section", "")] = memo  # reruns deepen; latest wins
    memos_view = [
        {
            "section": sid,
            "chars": len(m["text"]),
            "thin": len(m["text"]) < MEMO_MIN_CHARS,
            "text": (m["text"][:MEMO_MAX_CHARS] + "…") if len(m["text"]) > MEMO_MAX_CHARS else m["text"],
            "truncated": len(m["text"]) > MEMO_MAX_CHARS,
        }
        for sid, m in latest_memo.items()
    ]

    used_by_direction: dict[str, int] = {}
    for r in effective:
        for d in r.get("directions", []):
            used_by_direction[d] = used_by_direction.get(d, 0) + 1

    return {
        "ok": True,
        "topic": state.get("topic", ""),
        "genre": state.get("genre", "academic"),
        "tier": {
            "level": state.get("tier") or None,
            "profile": profile,
            "reason": state.get("tier_reason") or None,
        },
        "directions": _direction_source_diversity(state),
        "rounds": {
            "registered": len(rounds),
            "effective": len(effective),
            "wasted": len(rounds) - len(effective),
            "cap": profile["max_rounds"] if profile else None,
            "by_direction": {d: used_by_direction.get(d, 0) for d in tops},
            "per_direction_cap": profile["max_runs_per_direction"] if profile else None,
            "last": last_round,
        },
        "claims_digest": {
            "shown": digest,
            "omitted_older": max(0, len(claims) - len(shown)),
        },
        "memos": {
            "by_direction": memos_view,
            "without_memo": [d for d in tops if d not in latest_memo],
        },
        "source_distribution": {
            "academic": sum(1 for s in _live_sources(state) if _source_class(s.get("kind", "paper")) == "academic"),
            "web": sum(1 for s in _live_sources(state) if s.get("kind") == "web"),
            "other": sum(1 for s in _live_sources(state) if _source_class(s.get("kind", "paper")) == "other"),
            "unsupported_claims": sum(1 for c in claims if not c.get("supports")),
            # the citable count is the anti-overcounting view: live,
            # non-downgraded claims only, scholarly kinds only
            "citable_scholarly": _citable_scholarly_count(state),
        },
        "scholarly_ref_directive": _scholarly_ref_directive(state),
        # The report-stage funnel: how much of retrieval survives to
        # claim-grounded use. Numbers only, no threshold — the decision it
        # feeds is "write from the 74% the ledger holds but the claims never
        # reached", and that is a writing-stage call, not a retrieval one.
        "retrieval_funnel": _retrieval_funnel(state),
        # The writing plan the report stage will be held to (per-section
        # targets and the user budget, if registered).
        "write_targets": _write_targets(state),
        "evidence_quality": _evidence_quality(state),
        "evaluation_history": _evaluation_history_view(state),
        "unresolved_conflicts": [
            {"claim": c["id"], "conflict": c["conflict"]} for c in claims if c.get("conflict")
        ],
        "verbatim_check": _claims_evidence_not_verbatim(state),
        "verify_stats": {
            "checked": sum(1 for c in claims if c.get("verified")),
            "passed": sum(1 for c in claims if c.get("verify_status") == "passed"),
            "downgraded": sum(1 for c in claims if c.get("verify_status") == "downgraded"),
            "inconclusive": sum(1 for c in claims if c.get("verify_status") == "inconclusive"),
            "awaiting_verify": sum(
                1 for c in claims if c.get("evidence") and not c.get("verified")
                and not _claim_downgraded(state, c)
            ),
            # Reason diversity is the visible trace of real per-claim
            # checking: one template string across the batch is a signature
            # of rubber-stamping, and it shows up here either way.
            **_verify_reason_stats(claims),
        },
        "spend_total_cny": _spend_total(state),
        "not_recorded": [
            *([] if state.get("tier") else ["tier"]),
            *([] if rounds else ["rounds"]),
            *([] if state.get("decisions") else ["decisions"]),
            *(["memos"] if not state.get("memos") else []),
            *(["write_targets"] if _write_targets(state)["total"] is None else []),
        ],
        "absent_by_design": [
            "user template outline (outline registration is a later migration batch)",
            "mid-run user guidance (the user interjects natively in this architecture)",
        ],
    }


# ------------------------------------------------- report-stage richness helpers
# The three pieces below are one port: DeepDive's report stage gets its length
# from mechanisms this ledger lacked — per-chapter writing targets, a write-time
# deviation observation, and a material/read-back surface that hands the writer
# substance (claim evidence, source notes, and a ranked list of originals to
# re-read) instead of one-line claims. Selection rules and constants come from
# the source verbatim; what cannot port (the engine holds no document bodies, so
# it lists originals for the host to re-open rather than injecting fulltexts) is
# the already-recorded architectural difference.

_CITE_MARK = re.compile(r"\[@\d+\]|\[\d+\]|\[\[\d+\]\([^)]*\)\]|\[\[\d+\]\]")
_BARE_URL = re.compile(r"https?://\S+")
_ASCII_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\-]*")
_CJK_CHAR = re.compile(r"[㐀-䶿一-鿿぀-ヿ가-힯]")


def _cjk_equivalent_len(text: str) -> int:
    """Report length in Chinese-character equivalents — the口径 upstream uses
    for every length decision (utils.cjk_equivalent_len). CJK characters count
    1 each, ASCII words × LENGTH_WORD_TO_CJK, punctuation and whitespace count
    nothing, and citation marks / bare URLs are stripped first: they are
    markup, and counting them fattens citation-dense prose without adding a
    word of substance. (A different unit from `_prose_units`, which floors
    subsections at word-granularity; targets and deviations are 当量.)"""
    if not text:
        return 0
    cleaned = _BARE_URL.sub(" ", _CITE_MARK.sub(" ", text))
    cjk = len(_CJK_CHAR.findall(cleaned))
    words = len(_ASCII_WORD.findall(cleaned))
    return int(round(cjk + words * LENGTH_WORD_TO_CJK))


def _retrieval_funnel(state: dict[str, Any]) -> dict[str, Any]:
    """How much of what retrieval brought survives to claim-grounded use.
    Upstream reports exactly this pair (telemetry.py: candidate sources
    "含未进入最终参考文献的来源，故与 cited 可以不等") and never thresholds it —
    observation only, no warning, no genre-specific reference floor (the one
    soft target that exists upstream is scholarly-only, already ported as
    `scholarly_ref_directive`). The report-side count lands in the renumber
    citation map; this is the ledger-side funnel."""
    sources = _live_sources(state)
    cited = set()
    for claim in _live_claims(state):
        cited.update(claim.get("supports", []))
    total = len(sources)
    return {
        "sources_total": total,
        "with_abstract": sum(1 for s in sources if s.get("abstract")),
        "with_note": sum(1 for s in sources if s.get("note")),
        "fulltext": sum(1 for s in sources if s.get("depth") == "fulltext"),
        "cited_by_live_claims": len(cited & {s["n"] for s in sources}),
        "cited_share": round(len(cited & {s["n"] for s in sources}) / total, 3) if total else None,
    }


def _rounds_without_yield(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Effective rounds whose probes hold no live source — the observable
    shadow of upstream's forced `needs_more` (a pass with empty findings or
    all-unsourced ones must not report sufficient, prompts/subagent.py:428).
    The engine cannot see a round's findings, but it can see that every probe
    the round served kept nothing: that round's --why-stopped owes the run an
    honest 'nothing landed' and the next decide owes it a retry, not a wrap."""
    probes_with_sources = {
        p for s in _live_sources(state) for p in (s.get("probes") or [])
    }
    return [
        {"round": r["n"], "probes": r["probes"]}
        for r in _effective_rounds(state)
        if r.get("probes") and not (set(r["probes"]) & probes_with_sources)
    ]


def _section_material_volume(state: dict[str, Any], top: dict[str, Any]) -> int:
    """Everything the section's writing can draw on, in characters: its live
    claims' text and verbatim evidence, plus the abstracts and notes of the
    sources tagged to it. This is the number '素材充分度' refers to — upstream
    assigns each chapter's target BY this sufficiency, so the coupling between
    a target and the material behind it is part of the mechanism, not an
    afterthought. A raw-character approximation of 字当量 (CJK ≈ 1), good
    enough to see a target that outruns its entire material."""
    section_ids = {top["id"], *(kid["id"] for kid in top["children"])}
    volume = 0
    for claim in _live_claims(state):
        if claim.get("section", "") in section_ids:
            volume += len(claim.get("text", ""))
            volume += sum(len(e) for e in claim.get("evidence") or [])
    for source in _live_sources(state):
        if set(source.get("sections", [])) & section_ids:
            volume += len(source.get("abstract") or "")
            volume += len(source.get("note") or "")
    return volume


def _write_targets(state: dict[str, Any]) -> dict[str, Any]:
    """The registered writing plan: per-section target lengths (each shown next
    to the material the section actually holds — the target/material pairing IS
    the mechanism upstream calls 按素材充分度分配) and the user's overall
    budget, if any."""
    sections: dict[str, dict[str, Any]] = {}
    for top in state["outline"]:
        sections[top["id"]] = {
            "target": top.get("target_chars"),
            "material_chars": _section_material_volume(state, top),
        }
    registered = [s["target"] for s in sections.values() if s["target"]]
    return {
        "budget": state.get("length_budget") or None,
        "sections": sections,
        "total": sum(registered) if registered else None,
    }


def _section_readback(state: dict[str, Any]) -> dict[str, Any]:
    """Rank the core originals each section should re-read before writing —
    the port of _select_chapter_raw_docs. Hits are claim citations within the
    section; a source already listed for an earlier section keeps its slot at
    half weight (same original again beats none, but new originals rank first).
    Scholarly genre (upstream review/proposal): citable academic originals get
    priority into the limited slots and non-academic ones carry the
    background-only tag, so high-hit web pages cannot crowd out the only
    citable paper. Industry genre ranks by hits alone — web evidence is
    first-class there."""
    claims_by_section: dict[str, list[dict[str, Any]]] = {}
    for claim in _live_claims(state):
        claims_by_section.setdefault(claim.get("section", ""), []).append(claim)
    scholarly = state.get("genre", "academic") != "industry"
    listed: set[int] = set()
    per_section: dict[str, list[dict[str, Any]]] = {}
    for top in state["outline"]:
        section_claims = list(claims_by_section.get(top["id"], []))
        for kid in top["children"]:
            section_claims += claims_by_section.get(kid["id"], [])
        hits: dict[int, float] = {}
        for claim in section_claims:
            for n in claim.get("supports", []):
                hits[n] = hits.get(n, 0.0) + (0.5 if n in listed else 1.0)
        live = {s["n"]: s for s in _live_sources(state)}
        # A claim may still name a source that was dropped later; a dead source
        # must not consume a slot, so live membership filters before the rank.
        hits = {n: w for n, w in hits.items() if n in live}
        ranked = sorted(
            hits,
            key=lambda n: (
                1 if scholarly and _source_class(live[n].get("kind", "paper")) == "academic" else 0,
                hits[n],
            ),
            reverse=True,
        )[:READBACK_PER_SECTION_MAX]
        picked = []
        for n in ranked:
            picked.append({
                "n": n,
                "hits": hits[n],
                "reused": n in listed,
                "background": scholarly and _source_class(live[n].get("kind", "paper")) != "academic",
            })
            listed.add(n)
        per_section[top["id"]] = picked
    return {
        "per_section": per_section,
        "distinct": sorted(listed),
        "global_cap": READBACK_GLOBAL_MAX,
        "over_global_cap": len(listed) > READBACK_GLOBAL_MAX,
    }


def _material_markdown(state: dict[str, Any], lang: str = "auto") -> str:
    """The writing-preparation surface — what the host reads before writing
    each section, the port of DeepDive's chapter material assembly. Upstream
    renders each finding as a material block (citation mark + full detail +
    evidence excerpt) and injects ranked core originals per chapter; the
    writer composes from material, not from one-line claims. Here the same
    block is claim text + `[@n]` marks + verbatim evidence + the source's
    note (the detail channel of this ledger), and the originals the engine
    cannot inject are a ranked re-read list instead — the host re-opens them
    with its own tools. Per-section writing targets head each section so the
    target is on the desk before the first sentence."""
    lab = _labels(state, lang)
    live = {s["n"]: s for s in _live_sources(state)}
    claims_by_section: dict[str, list[dict[str, Any]]] = {}
    for claim in _live_claims(state):
        claims_by_section.setdefault(claim.get("section", ""), []).append(claim)
    latest_memo: dict[str, dict[str, Any]] = {}
    for memo in state.get("memos", []):
        latest_memo[memo.get("section", "")] = memo
    readback = _section_readback(state)
    targets = _write_targets(state)
    lines: list[str] = []

    for top in state["outline"]:
        target = top.get("target_chars")
        head = lab["m_target"].format(n=target) if target else lab["m_no_target"]
        # The material volume prints with or without a target: upstream
        # assigns targets at report time BY material sufficiency, so the
        # volume is the input the targets are assigned from — it must be
        # on the desk before any target exists. Once a target is set, the
        # pairing is the mechanism, and a target that outruns its material
        # is a broken coupling — the target follows the material, it is not
        # an instruction to retrieve for a length.
        material_chars = _section_material_volume(state, top)
        head += f" · {lab['m_material'].format(n=material_chars)}"
        lines += [f"## {top['id']}. {top['title']} — {head}", ""]

        section_claims = list(claims_by_section.get(top["id"], []))
        for kid in top["children"]:
            section_claims += claims_by_section.get(kid["id"], [])
        lines += [lab["m_blocks"], ""]
        if not section_claims:
            lines += [lab["no_claims"], ""]
        for claim in section_claims:
            marks = " ".join(f"[@{n}]" for n in claim.get("supports", []))
            marker = lab["downgraded"] if _claim_downgraded(state, claim) else ""
            lines.append(f"- [{claim['id']}] {claim['text']}{(' ' + marks) if marks else ''}{marker}")
            for excerpt in claim.get("evidence") or []:
                lines.append(f"  - {lab['m_evidence']}\"{excerpt}\"")
            for n in claim.get("supports", []):
                note = (live.get(n) or {}).get("note")
                if note:
                    lines.append(f"  - {lab['m_note'].format(n=n)}{note}")
        lines.append("")

        lines += [lab["m_readback"], ""]
        picked = readback["per_section"].get(top["id"], [])
        if not picked:
            lines += [lab["m_no_readback"], ""]
        for entry in picked:
            src = live[entry["n"]]
            flags = ""
            if entry["reused"]:
                flags += lab["m_reused"]
            if entry["background"]:
                flags += lab["m_background"]
            hits_text = lab["m_hits"].format(n=f"{entry['hits']:g}")
            lines.append(
                f"- [@{entry['n']}] {src.get('title', '')} — {src.get('url', '')} "
                f"({hits_text}{flags})"
            )
        lines.append("")

        # The uncited pool — the port of upstream's 全局参考文献清单: its
        # writer gets a numbered list of EVERY retrieved source (built from
        # state.sources, unfiltered), so a source no finding leaned on is still
        # on the desk. Here the equivalent is per-section: sources tagged to
        # this section that no claim of this section cites. They are invisible
        # in the blocks above and rank last-never in the read-back list (zero
        # hits); without this pool a run's citations collapse to its claim set
        # exactly (measured twice: 26 == 26, 27 == 27).
        section_cited: set[int] = set()
        for claim in section_claims:
            section_cited.update(claim.get("supports", []))
        section_ids = {top["id"], *(kid["id"] for kid in top["children"])}
        pool = [
            s for s in live.values()
            if set(s.get("sections", [])) & section_ids and s["n"] not in section_cited
        ]
        lines += [lab["m_uncited"], ""]
        if not pool:
            lines += [lab["m_uncited_none"], ""]
        for s in sorted(pool, key=lambda s: s["n"]):
            abstract = s.get("abstract") or ""
            snippet = (abstract[:120] + "…") if len(abstract) > 120 else abstract
            lines.append(f"- [@{s['n']}] {s.get('title', '')} — {s.get('url', '')}")
            if snippet:
                lines.append(f"  {snippet}")
        lines.append("")

        memo = latest_memo.get(top["id"])
        lines += [lab["m_memo"], ""]
        lines += [memo["text"] if memo else lab["m_no_memo"], ""]

    datums = _live_datums(state)
    lines += [lab["m_datums"], ""]
    if not datums:
        lines += [lab["m_no_datums"], ""]
    for d in datums:
        lines.append(
            f"- {d['id']} · {d.get('entity', '')} / {d.get('metric', '')} = "
            f"{d.get('value', '')}{d.get('unit', '')}"
            f"{(' (' + str(d['year']) + ')') if d.get('year') else ''} [@{d.get('source')}]"
        )
    lines.append("")

    distinct = len(readback["distinct"])
    lines.append(
        lab["m_global"].format(x=distinct, cap=READBACK_GLOBAL_MAX)
    )
    # Sources that never got a section tag sit outside every pool above; the
    # desk stays complete only if they are named too.
    untagged = [s for s in live.values() if not s.get("sections")]
    if untagged:
        lines += ["", lab["m_untagged"].format(n=len(untagged)), ""]
        lines += [f"- [@{s['n']}] {s.get('title', '')}" for s in sorted(untagged, key=lambda s: s["n"])]
    if readback["over_global_cap"]:
        total_hits: dict[int, int] = {}
        for claim in _live_claims(state):
            for n in claim.get("supports", []):
                if n in live:
                    total_hits[n] = total_hits.get(n, 0) + 1
        slate = sorted(total_hits, key=lambda n: total_hits[n], reverse=True)[:READBACK_GLOBAL_MAX]
        lines += ["", lab["m_over_cap"].format(cap=READBACK_GLOBAL_MAX), ""]
        lines += [
            f"- [@{n}] {live[n].get('title', '')} ({lab['m_hits'].format(n=total_hits[n])})"
            for n in slate
        ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------- render labels

# The report follows the user's language, so the renderer has to as well: a
# Chinese report used to come back wearing an English skeleton (`## References`,
# `Drop rate`, `_(disagreement)_`) because every label here was a literal.
#
# What is *not* translated is as deliberate as what is. API names, probe ids and
# `axis` values are controlled vocabulary shared with the CLI and the API
# catalog; source titles and venues are real metadata. Translating any of them
# would break the link between the report and the thing it cites.
_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")

_LABELS_EN = {
    "sources_prefix": "Sources: ",
    "sources_none": "none",
    "disagreement": " _(disagreement)_",
    "interpretation": " _(interpretation)_",
    "downgraded": " _(verify-downgraded — background info, do not cite)_",
    "not_verbatim": " _(evidence not verbatim — background info, do not cite)_",
    "conflict": "conflict: ",
    "unsupported": "[unsupported]",
    "no_outline": "_No outline: run the Round 0 scout, then `evidence.py outline set`._",
    "no_claims": "_No claims recorded — do not write this subsection._",
    "references": "## References",
    "no_sources": "_No sources recorded._",
    "unplaced": "## Unplaced claims",
    "unplaced_note": "section '{section}' no longer exists",
    "figure_placeholder": "_[FIGURE {id}] {title} — sources: {sources}_",
    "unplaced_figures": "## Unplaced figures",
    "appendix_a": "## Appendix A — Retrieval log",
    "appendix_a_head": (
        "| Probe | Axis | Tool | Query | Returned | Kept | Dropped | Drop rate | Reasons for dropping |"
    ),
    "no_probes": "_No probes registered._",
    "appendix_b": "## Appendix B — Calls and cost",
    "appendix_b_head": "| API | Calls | Unit price (CNY) | Subtotal (CNY) |",
    "total": "**Total**",
    "all_free": "_Every call in this run was free._",
    "cost_note": (
        "Free endpoints are not billed and therefore do not appear above. "
        "Hard stop for one task: CNY {limit:.2f}."
    ),
    "appendix_c": "## Appendix C — Data and methods",
    "appendix_c_head": "| Item | Value |",
    "c_searches": "Searches run (by axis)",
    "c_searches_fmt": "{n} ({axes})",
    "c_screened": "Records screened / retained / discarded",
    "c_depth": "Reading depth of retained sources",
    "c_kinds": "Academic sources / web sources",
    "c_claims": "Claims recorded (of which interpretation)",
    "c_claims_fmt": "{n} ({part})",
    "c_conflicts": "Claims carrying a recorded conflict",
    "c_coverage": "Top-level sections / subsections",
    "c_figures": "Figures recorded",
    "c_tier": "Complexity tier (directions × reruns × rounds)",
    "c_tier_missing": "not registered",
    "c_rounds": "Research rounds (effective + wasted)",
    "c_verify": "Citation faithfulness (passed / downgraded / inconclusive)",
    "c_verify_missing": "not verified",
    "c_depth_names": {
        "fulltext": "open-access full text",
        "detail": "full abstract",
        "slice": "abstract slice",
        "search": "title only",
    },
    "appendix_c_figures": "### Figures",
    "appendix_c_figures_head": "| Figure | Type | Sources | Rendered by | Charted by |",
    "c_chart_agent": "chart-topic subagent",
    "c_chart_controller": "controller session",
    "c_chart_undeclared": "undeclared",
    "appendix_c_plans": "### Figure plans (chart topics)",
    "appendix_c_plans_head": "| Plan | Topic | Section | Intended | Status | Datums | Figure |",
    "c_plan_status": {
        "open": "open — retrieving",
        "fulfilled": "fulfilled",
        "abandoned": "abandoned",
    },
    "c_plan_no_type": "—",
    "c_plan_none": "—",
    "c_prose_todo": (
        "_Add below, in prose: inclusion and exclusion criteria, the retrieval time "
        "window and year filter, the language strategy, and the evidence level — "
        "how many sources were read at open-access full text (the row above) and "
        "what the rest degraded to. The ledger cannot know the rest._"
    ),
    "pointer": (
        "Appendices are written to `{path}`: Appendix A records each search's axis, "
        "query, returned/kept/discarded counts and the reasons for discarding; "
        "Appendix B records calls and cost per endpoint; Appendix C records the "
        "screening counts, reading-depth distribution and coverage statistics."
    ),
    "appendix_d": "## Appendix D — Citation number map",
    "appendix_d_head": "| Report | Ledger | Title |",
    "appendix_d_note": (
        "_Report numbers are the ascending first-appearance numbers of the report "
        "delivered with this map (see its `*-citation-map.json` sidecar). `*` marks a "
        "retained source the report never cites; such sources appear in figure-source "
        "columns as `43*`, i.e. by ledger number._"
    ),
    "pointer_with_map": (
        "Appendices are written to `{path}`: Appendix A records each search's axis, "
        "query, returned/kept/discarded counts and the reasons for discarding; "
        "Appendix B records calls and cost per endpoint; Appendix C records the "
        "screening counts, reading-depth distribution and coverage statistics; "
        "Appendix D maps the report's citation numbers to ledger source numbers."
    ),
    # --material: the writing-preparation surface
    "m_target": "target {n} 字当量",
    "m_no_target": "no writing target registered",
    "m_blocks": "### Material blocks — write from these, not from memory",
    "m_evidence": "evidence: ",
    "m_note": "note [@{n}]: ",
    "m_readback": "### Re-read before writing — ranked by this section's claim citations; already-listed originals carry half weight",
    "m_no_readback": "_No claim-grounded originals in this section — nothing to rank._",
    "m_hits": "cited by {n} claim(s)",
    "m_reused": "; listed for an earlier section",
    "m_background": "; background only — context, never a citation",
    "m_memo": "### Memo (latest for this direction)",
    "m_no_memo": "_No memo recorded for this section._",
    "m_datums": "### Data material (datums, report-wide)",
    "m_no_datums": "_No datums recorded._",
    "m_global": "Distinct originals listed for re-read: {x}/{cap} (whole-report cap).",
    "m_over_cap": "One-shot writing slate — the global top {cap} by total claim citations:",
    "m_material": "material on file ~{n} chars",
    "m_uncited": "### Uncited pool — tagged to this section, cited by none of its claims; read before citing, or drop",
    "m_uncited_none": "_Nothing tagged here is uncited — every retrieved source in this section carries a claim._",
    "m_untagged": "### Untagged live sources ({n}) — outside every section pool; tag or drop",
}

_LABELS_ZH = {
    "sources_prefix": "来源：",
    "sources_none": "无",
    "disagreement": " _（分歧）_",
    "interpretation": " _（解读）_",
    "downgraded": " _（核验降级——背景信息，不得引用）_",
    "not_verbatim": " _（证据非逐字——背景信息，不得引用）_",
    "conflict": "冲突：",
    "unsupported": "[无来源]",
    "no_outline": "_尚无大纲：先做第 0 轮扫描，再执行 `evidence.py outline set`。_",
    "no_claims": "_未记录任何论断——本子节不得写入报告。_",
    "references": "## 参考文献",
    "no_sources": "_未记录任何来源。_",
    "unplaced": "## 未归位论断",
    "unplaced_note": "章节 '{section}' 已不存在",
    "figure_placeholder": "_[FIGURE {id}] {title} — 来源：{sources}_",
    "unplaced_figures": "## 未归位图表",
    "appendix_a": "## 附录 A — 检索明细",
    "appendix_a_head": "| 探针 | 检索轴 | 工具 | 查询 | 返回 | 保留 | 丢弃 | 丢弃率 | 丢弃原因 |",
    "no_probes": "_未登记任何探针。_",
    "appendix_b": "## 附录 B — 调用与费用",
    "appendix_b_head": "| 接口 | 调用次数 | 单价（元） | 小计（元） |",
    "total": "**合计**",
    "all_free": "_本次运行的所有调用均为免费接口。_",
    "cost_note": "免费接口不计费，故不在上表中。单个任务的强制停止线：{limit:.2f} 元。",
    "appendix_c": "## 附录 C — 数据与方法",
    "appendix_c_head": "| 项目 | 数值 |",
    "c_searches": "检索次数（按检索轴）",
    "c_searches_fmt": "{n}（{axes}）",
    "c_screened": "筛查 / 保留 / 丢弃条数",
    "c_depth": "保留来源的读取深度",
    "c_kinds": "学术来源 / 网页来源",
    "c_claims": "论断条数（其中解读类）",
    "c_claims_fmt": "{n}（{part}）",
    "c_conflicts": "记录了冲突的论断",
    "c_coverage": "一级章节 / 子节",
    "c_figures": "已记录图表",
    "c_tier": "复杂度档位（方向 × 补轮 × 总轮）",
    "c_tier_missing": "未登记",
    "c_rounds": "研究轮次（有效 + 浪费）",
    "c_verify": "引证核验（通过 / 降级 / 未定论）",
    "c_verify_missing": "未核验",
    "c_depth_names": {
        "fulltext": "开放获取全文",
        "detail": "完整摘要",
        "slice": "摘要片段",
        "search": "仅题目",
    },
    "appendix_c_figures": "### 图表",
    "appendix_c_figures_head": "| 图表 | 类型 | 来源 | 渲染方式 | 作图形态 |",
    "c_chart_agent": "图表子代理",
    "c_chart_controller": "主会话",
    "c_chart_undeclared": "未声明",
    "appendix_c_plans": "### 图表规划（图表主题）",
    "appendix_c_plans_head": "| 规划 | 主题 | 节 | 意向图型 | 状态 | 数据点 | 成图 |",
    "c_plan_status": {
        "open": "进行中——检索中",
        "fulfilled": "已成图",
        "abandoned": "已放弃",
    },
    "c_plan_no_type": "—",
    "c_plan_none": "—",
    "c_prose_todo": (
        "_请在下方以散文补足台账无法知道的部分：纳入与排除标准、检索时间窗与年份过滤、"
        "语言策略，以及证据层级——多少来源读了开放获取全文（上表行）、其余降级到了哪一档。_"
    ),
    "pointer": (
        "附录已写入 `{path}`：附录 A 记录每次检索的检索轴、查询与返回／保留／丢弃条数"
        "及丢弃原因，附录 B 记录各接口的调用次数与费用小计，附录 C 记录筛查计数、"
        "证据读取深度分布与覆盖统计。"
    ),
    "appendix_d": "## 附录 D — 引用编号对照",
    "appendix_d_head": "| 报告编号 | 台账编号 | 标题 |",
    "appendix_d_note": (
        "_报告编号是随本映射交付的那份报告中按正文首现递增的编号（sidecar 为 "
        "`*-citation-map.json`）。`*` 标记报告未引用、仅台账留存的来源；这类来源在图表"
        "来源列中以 `43*` 形式按台账编号出现。_"
    ),
    "pointer_with_map": (
        "附录已写入 `{path}`：附录 A 记录每次检索的检索轴、查询与返回／保留／丢弃条数"
        "及丢弃原因，附录 B 记录各接口的调用次数与费用小计，附录 C 记录筛查计数、"
        "证据读取深度分布与覆盖统计，附录 D 给出报告引用号与台账编号的对照。"
    ),
    # --material：写作准备面
    "m_target": "写作目标 {n} 字当量",
    "m_no_target": "未登记写作目标",
    "m_blocks": "### 素材块——从这些出发写作，不凭记忆",
    "m_evidence": "证据：",
    "m_note": "笔记 [@{n}]：",
    "m_readback": "### 写前回读清单——按本节 claim 引用次数排序；前节已列的原文半权",
    "m_no_readback": "_本节没有 claim 支撑的原文——无可排序。_",
    "m_hits": "被 {n} 条 claim 引用",
    "m_reused": "；前节已列",
    "m_background": "；仅作背景——只供语境，不得引用",
    "m_memo": "### 备忘录（本方向最新）",
    "m_no_memo": "_本节无备忘录。_",
    "m_datums": "### 数据素材（datums，全报告）",
    "m_no_datums": "_无 datum 记录。_",
    "m_global": "回读清单去重原文共 {x}/{cap}（全稿上限）。",
    "m_over_cap": "一次成稿优先名单——按全稿 claim 引用次数取全局前 {cap}：",
    "m_material": "现有素材 ~{n} 字",
    "m_uncited": "### 未引用池——挂在本节、本节论断均未引用；要用先读，不用就 drop",
    "m_uncited_none": "_本节没有未引用来源——挂节来源全部有论断承载。_",
    "m_untagged": "### 未挂节来源（{n} 个）——不在任何节的池里；挂节或 drop",
}


def _labels(state: dict[str, Any], lang: str = "auto") -> dict[str, Any]:
    """Label table for the render. `auto` follows the ledger's topic.

    Auto-detection rather than a flag: the language of the report is already
    decided by the request, and a flag the model has to remember is a flag the
    model eventually forgets — which is exactly how the English skeleton got
    into a Chinese report.
    """
    if lang == "auto":
        lang = "zh" if _CJK.search(state.get("topic") or "") else "en"
    return _LABELS_ZH if lang == "zh" else _LABELS_EN


def _bibliography_line(source: dict[str, Any], number: int) -> str:
    """One reference in academic form: authors, title, venue, year, link.

    Tool provenance (`via paper_qa_search_pro`) is deliberately absent — it is
    retrieval bookkeeping, not bibliographic data, and belongs in the appendix.
    """
    bits: list[str] = []
    authors = source.get("authors")
    if isinstance(authors, list) and authors:
        shown = ", ".join(str(a) for a in authors[:3])
        bits.append(f"{shown}, et al." if len(authors) > 3 else f"{shown}.")
    elif isinstance(authors, str) and authors.strip():
        bits.append(f"{authors.strip()}.")
    bits.append(f"{source['title'].rstrip('.')}.")
    tail = [str(source[key]) for key in ("venue", "year") if source.get(key)]
    if tail:
        bits.append(", ".join(tail) + ".")
    if source.get("url"):
        bits.append(source["url"])
    return f"[{number}] " + " ".join(bits)


CITE_TOKEN = re.compile(r"\[@(\d+)\]")
REFERENCES_PLACEHOLDER = "{{references}}"
# Adjacent citations must read spaced ([3] [7], report-format.md §citations),
# never glued ([3][7] — a reading defect). Drafts glue [@n] tokens freely; the
# delivered file normalizes the seam between two citation-shaped brackets.
GLUED_CITES = re.compile(r"(\[\d+\])(?=\[)")
# The delivered report is substance, not claim restatement. Figures have a
# whole sufficiency machinery (plans, budgets, `check` warnings); prose had
# none, and a report measured only on its charts grows five figures over
# three sentences. `render --renumber` is the one engine pass that reads the
# draft, so the floor lives here: a subsection under this many prose units
# (CJK characters or Latin words, citations and structural lines excluded)
# never reaches the page.
MIN_SUBSECTION_PROSE = 300


def _prose_units(text: str) -> int:
    body = re.sub(r"\[@\d+\]|\[\d+\]", " ", text)
    cjk = len(re.findall(r"[㐀-鿿]", body))
    words = len(re.findall(r"[A-Za-z][A-Za-z'-]*", body))
    return cjk + words


def _subsection_prose(text: str) -> list[tuple[str, int]]:
    """Prose volume of each `###` subsection, headings/images/tables/quotes
    and the reference block excluded — the unit `render --renumber` floors."""
    units: list[tuple[str, int]] = []
    current: str | None = None
    buf: list[str] = []
    for line in text.splitlines():
        if line.startswith("#"):
            if current is not None:
                units.append((current, _prose_units("\n".join(buf))))
            current = line[4:].strip() if line.startswith("### ") else None
            buf = []
            continue
        if current is not None and not line.lstrip().startswith(("!", "|", ">")):
            buf.append(line)
    if current is not None:
        units.append((current, _prose_units("\n".join(buf))))
    return units


def _renumber_draft(state: dict[str, Any], draft: Path, out: Path, lang: str = "auto",
                    ledger: str = "") -> dict[str, Any]:
    """Assign the report's ascending citation numbers from the draft itself.

    Engine-side numbers (ledger n — stable, never renumbered, a dropped source
    keeps its slot) and reader-side numbers (first appearance in the delivered
    text) are strictly separated. The draft carries [@n] placeholders keyed to
    ledger numbers; this pass assigns dense ascending numbers by where each
    token first appears, substitutes them, fills the `{{references}}` slot with
    a cited-only bibliography, and writes the mapping to a sidecar the appendix
    consumes. A placeholder naming an unknown or dropped source is a hard error
    — a citation pointing at nothing must not reach the page.
    """
    text = draft.read_text(encoding="utf-8")
    live = {source["n"]: source for source in _live_sources(state)}
    dropped = {source["n"] for source in state["sources"] if source.get("dropped")}

    unknown = sorted({int(m.group(1)) for m in CITE_TOKEN.finditer(text)} - set(live))
    if unknown:
        dead = [n for n in unknown if n in dropped]
        missing = [n for n in unknown if n not in dropped]
        parts = []
        if missing:
            parts.append(
                "unknown source number(s) "
                + ", ".join(f"[@{n}]" for n in missing)
                + " — nothing in the ledger matches"
            )
        if dead:
            parts.append(
                "dropped source(s) "
                + ", ".join(f"[@{n}]" for n in dead)
                + " — a dropped source cannot be cited"
            )
        raise LedgerError("; ".join(parts) + ". Fix the draft; the ledger is not edited here.")

    thin = [(title, n) for title, n in _subsection_prose(text) if n < MIN_SUBSECTION_PROSE]
    if thin:
        detail = "; ".join(f"'{title}' has {n}" for title, n in thin)
        raise LedgerError(
            f"Report is substance, not claim restatement — thin subsection(s): {detail} prose "
            f"units (CJK characters or Latin words; citations, headings, images and tables "
            f"excluded), minimum {MIN_SUBSECTION_PROSE}. Develop each subsection's claims in "
            "full paragraphs drawing on the abstracts and fulltext notes already in the "
            "ledger; a report measured only on its charts grows figures over sentences."
        )

    # Write-time length observation (the _log_length_deviation port): the
    # registered targets are goals, not constraints — deviation is recorded in
    # both directions and the prose is never rewritten for length. Denominator
    # is the body only: the generated references block (and the heading the
    # host may have put above the placeholder) is markup, not what the reader
    # asked for. No targets registered → the block reports the length alone,
    # so old ledgers lose nothing.
    body_end = text.find(REFERENCES_PLACEHOLDER)
    if body_end != -1:
        # Cut at a *references* heading directly above the placeholder —
        # never at "the last heading before it": a draft may place the
        # placeholder without any heading, and cutting at the last heading
        # swallowed a whole final section (measured: an entire 局限性
        # section vanished from the length block of a real run).
        head = re.search(
            r"^(#{1,6}[ \t]*(?:references|bibliography|参考文献|引用文献|参考资料)[^\n]*)\n\s*$",
            text[:body_end], flags=re.M | re.I,
        )
        body_end = head.start() if head else body_end
    body_for_length = text[:body_end] if body_end != -1 else text
    body_chars = _cjk_equivalent_len(body_for_length)
    targets = _write_targets(state)
    length_block: dict[str, Any] = {"body_chars": body_chars}
    # Per-`##`-section lengths, so the continue-writing loop can aim at the
    # thin section instead of the total: a -51% total hides a section that
    # wrote 43% of its target next to one that wrote 90%. The engine measures
    # and names headings; the draft's author is the one who knows which
    # heading belongs to which outline section.
    section_chunks = re.split(r"^## ", body_for_length, flags=re.M)
    length_block["sections"] = [
        {
            "heading": chunk.split("\n", 1)[0].strip(),
            "chars": _cjk_equivalent_len(chunk),
        }
        for chunk in section_chunks[1:]
    ]
    if targets["total"] is not None:
        deviation = (body_chars - targets["total"]) / targets["total"]
        length_block.update({
            "target_total": targets["total"],
            "deviation": round(deviation, 3),
            "within_tolerance": abs(deviation) <= LENGTH_TOLERANCE,
            "direction": "short" if deviation < 0 else "long",
        })
    if targets["budget"]:
        length_block["budget"] = targets["budget"]
        length_block["over_budget"] = body_chars > targets["budget"]

    weak_numbers = _weak_patent_number_segments(text, live)

    order: list[int] = []
    seen: set[int] = set()
    for match in CITE_TOKEN.finditer(text):
        n = int(match.group(1))
        if n not in seen:
            seen.add(n)
            order.append(n)
    external = {n: i for i, n in enumerate(order, start=1)}

    replaced = GLUED_CITES.sub(r"\1 ", CITE_TOKEN.sub(lambda m: f"[{external[int(m.group(1))]}]", text))
    if REFERENCES_PLACEHOLDER not in replaced:
        raise LedgerError(
            "Draft has no {{references}} placeholder under its references heading. "
            "`render --renumber` fills that slot with the cited-only bibliography; "
            "it never invents the section. Add the placeholder line and re-run."
        )
    entries = [_bibliography_line(live[n], external[n]) for n in order]
    replaced = replaced.replace(REFERENCES_PLACEHOLDER, "\n".join(entries))

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(replaced if replaced.endswith("\n") else replaced + "\n", encoding="utf-8")

    # Upstream logs its length deviation after delivery and tunes prompts with
    # it (_log_length_deviation, report.py:810-841 — 只观测、不重写). The ledger
    # is this fork's log: persist the observation so post-run review and the
    # next run's target-setting can read it. It never gates delivery.
    state["length_report"] = {**length_block, "report": out.as_posix()}
    if ledger:
        save_state(Path(ledger), state)

    map_path = out.with_name(f"{out.stem}-citation-map.json")
    payload = {
        "version": 1,
        "ledger": ledger,
        "report": out.as_posix(),
        "cited": len(order),
        "length": length_block,
        "external_to_ledger": {str(i): n for n, i in external.items()},
        "ledger_to_external": {str(n): i for n, i in external.items()},
    }
    map_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "out": out.as_posix(),
        "map_path": map_path.as_posix(),
        "cited": len(order),
        "entries": len(entries),
        "first_five": [f"[{external[n]}]={n}" for n in order[:5]],
        "weak_patent_numbers": weak_numbers,
        # Record-only: the target was a goal; rewriting for length would pad
        # prose and cut arguments (upstream's stated reason for log-only).
        "length": length_block,
    }


def _appendix_markdown(state: dict[str, Any], lang: str = "auto",
                       citation_map: dict[str, Any] | None = None) -> str:
    """Appendix A (retrieval), B (calls and cost), C (data and methods) and,
    when a citation map is supplied, D (report number -> ledger number).

    Everything the report's prose is not allowed to carry: probe ids, queries,
    yields, API names, prices, and the screening counts that used to sit in a
    "Data and methods" section in the body. With a map, source references the
    reader can chase (the figure-source column) switch to the report's external
    numbers; ledger numbers stay canonical everywhere the reader cannot see.
    """
    lab = _labels(state, lang)
    tally = _probe_yield(state)
    drop_reasons: dict[str, list[str]] = {}
    for source in state["sources"]:
        if not source.get("dropped"):
            continue
        for pid in source.get("probes", []):
            reason = source.get("drop_reason") or ""
            if reason and reason not in drop_reasons.setdefault(pid, []):
                drop_reasons[pid].append(reason)

    lines = [lab["appendix_a"], ""]
    if not state["probes"]:
        lines += [lab["no_probes"], ""]
    else:
        lines += [
            lab["appendix_a_head"],
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
        for probe in state["probes"]:
            counts = tally[probe["id"]]
            returned = counts["kept"] + counts["dropped"]
            rate = f"{counts['dropped'] / returned:.0%}" if returned else "—"
            reasons = "; ".join(drop_reasons.get(probe["id"], [])) or "—"
            lines.append(
                f"| {probe['id']} | {probe.get('axis', '')} | {probe.get('via', '') or '—'} "
                f"| {probe.get('query', '')} | {returned} | {counts['kept']} | {counts['dropped']} "
                f"| {rate} | {reasons} |"
            )
        lines.append("")

    lines += [lab["appendix_b"], ""]
    spend = state.get("spend") or {}
    if not spend:
        lines += [lab["all_free"], ""]
    else:
        lines += [lab["appendix_b_head"], "| --- | ---: | ---: | ---: |"]
        total = 0.0
        for api in sorted(spend):
            entry = spend[api]
            subtotal = float(entry.get("subtotal", 0.0))
            total += subtotal
            lines.append(f"| {api} | {entry.get('calls', 0)} | {entry.get('unit_cny', 0)} | {subtotal:.2f} |")
        lines += [f"| {lab['total']} | | | **{total:.2f}** |", ""]
        lines += [lab["cost_note"].format(limit=HARD_LIMIT_CNY), ""]

    lines += _appendix_c_lines(state, lab, citation_map)
    if citation_map:
        ext = {int(k): v for k, v in citation_map["ledger_to_external"].items()}
        lines += [lab["appendix_d"], "", lab["appendix_d_head"], "| --- | --- | --- |"]
        for source in _live_sources(state):
            n = source["n"]
            number = ext.get(n)
            report_col = f"[{number}]" if number is not None else "—"
            mark = "" if number is not None else "*"
            lines.append(f"| {report_col} | {n}{mark} | {source['title']} |")
        lines += ["", lab["appendix_d_note"], ""]
    return "\n".join(lines)


def _appendix_c_lines(state: dict[str, Any], lab: dict[str, Any],
                      citation_map: dict[str, Any] | None = None) -> list[str]:
    """Appendix C — the methods facts the ledger can actually vouch for.

    These used to be narrated from memory in a body section. Everything here is
    counted off the ledger instead; what the ledger cannot know (criteria, time
    window, language strategy) is left to prose, and said so.
    """
    live = _live_sources(state)
    claims = _live_claims(state)

    axes: dict[str, int] = {}
    for probe in state["probes"]:
        axis = probe.get("axis", "") or "—"
        axes[axis] = axes.get(axis, 0) + 1
    axis_text = ", ".join(f"{axis} {n}" for axis, n in sorted(axes.items())) or "—"

    depths: dict[str, int] = {}
    for source in live:
        depths[source.get("depth", "search")] = depths.get(source.get("depth", "search"), 0) + 1
    names = lab["c_depth_names"]
    depth_text = ", ".join(
        f"{names.get(d, d)} {depths[d]}"
        for d in ("fulltext", "detail", "slice", "search") if depths.get(d)
    ) or "—"

    web = sum(1 for s in live if s.get("kind") == "web")
    interpretations = sum(1 for c in claims if c.get("type") == "interpretation")
    conflicts = sum(1 for c in claims if c.get("conflict"))
    subs = sum(len(top["children"]) for top in state["outline"])

    profile = _tier_profile(state)
    tier_text = (
        f"{state.get('tier')} ({profile['max_directions']} × {profile['max_runs_per_direction']} × "
        f"{profile['max_rounds']})" if profile else lab["c_tier_missing"]
    )
    rounds_all = state.get("rounds", [])
    rounds_text = (
        f"{len(_effective_rounds(state))} + {len(rounds_all) - len(_effective_rounds(state))}"
        if rounds_all else "0"
    )
    verified = [c for c in claims if c.get("verified")]
    verify_text = (
        f"{sum(1 for c in verified if c.get('verify_status') == 'passed')} / "
        f"{sum(1 for c in verified if c.get('verify_status') == 'downgraded')} / "
        f"{sum(1 for c in verified if c.get('verify_status') == 'inconclusive')}"
        if verified else lab["c_verify_missing"]
    )

    rows = [
        (lab["c_searches"], lab["c_searches_fmt"].format(n=len(state["probes"]), axes=axis_text)),
        (lab["c_screened"], f"{len(state['sources'])} / {len(live)} / {len(state['sources']) - len(live)}"),
        (lab["c_depth"], depth_text),
        (lab["c_kinds"], f"{len(live) - web} / {web}"),
        (lab["c_claims"], lab["c_claims_fmt"].format(n=len(claims), part=interpretations)),
        (lab["c_conflicts"], str(conflicts)),
        (lab["c_coverage"], f"{len(state['outline'])} / {subs}"),
        (lab["c_figures"], str(len(_live_figures(state)))),
        (lab["c_tier"], tier_text),
        (lab["c_rounds"], rounds_text),
        (lab["c_verify"], verify_text),
    ]
    lines = [lab["appendix_c"], "", lab["appendix_c_head"], "| --- | --- |"]
    lines += [f"| {item} | {value} |" for item, value in rows]
    figures = _live_figures(state)
    if figures:
        lines += ["", lab["appendix_c_figures"], "", lab["appendix_c_figures_head"],
                  "| --- | --- | --- | --- | --- |"]
        ext = citation_map["ledger_to_external"] if citation_map else None
        for f in figures:
            ftype = f.get("chart_type") or "—"
            nums = sorted(_figure_source_numbers(state, f))
            if ext:
                fsrc = ", ".join(f"[{ext[str(n)]}]" if str(n) in ext else f"{n}*"
                                 for n in nums) or "—"
            else:
                fsrc = ", ".join(str(n) for n in nums) or "—"
            fby = f.get("rendered_by") or "—"
            if f.get("charted_by") == "agent":
                fmode = lab["c_chart_agent"]
            elif f.get("charted_by") == "controller":
                fmode = lab["c_chart_controller"]
                if f.get("charted_reason"):
                    fmode = f"{fmode} — {f['charted_reason']}"
            else:
                fmode = lab["c_chart_undeclared"]
            lines.append(f"| {f['id']} | {ftype} | {fsrc} | {fby} | {fmode} |")
    plans = _live_plans(state)
    if plans:
        st = lab["c_plan_status"]
        lines += ["", lab["appendix_c_plans"], "", lab["appendix_c_plans_head"],
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for p in plans:
            status = st.get(p.get("status", "open"), p.get("status", "open"))
            if p.get("status") == "abandoned" and p.get("reason"):
                status = f"{status} — {p['reason']}"
            lines.append(
                f"| {p['id']} | {p.get('topic', '')} | {p.get('section', '')} "
                f"| {p.get('chart_type') or lab['c_plan_no_type']} | {status} "
                f"| {len(_plan_datums(state, p['id']))} "
                f"| {p.get('figure_id') or lab['c_plan_none']} |"
            )
    return lines + ["", lab["c_prose_todo"], ""]


def render_markdown(state: dict[str, Any], final: bool = False, lang: str = "auto") -> str:
    lab = _labels(state, lang)
    sources_by, claims_by, _ = _rollup(state)
    by_id = {claim["id"]: claim for claim in state["claims"]}
    index = _section_index(state)
    lines: list[str] = []

    live = _live_sources(state)
    # Citation numbers here are raw ledger numbers (stable across renders, never
    # renumbered — a drop keeps its slot). The ascending, reader-facing numbers
    # live only in the delivered report and are assigned by `render --renumber`
    # from the draft's [@n] placeholders; `--final` is the content reference the
    # host writes prose against, not the numbering source.
    fig_by_id = {f["id"]: f for f in state["figures"]}
    figures_by = _figures_by_section(state)

    # Downgraded claims (verify gate, or evidence that failed the verbatim
    # check) stay in the ledger as background information — marked here so
    # the host drafting prose knows not to lean a citation on them.
    not_verbatim_ids = {f["claim"] for f in _claims_evidence_not_verbatim(state)}

    def claim_bullet(claim_id: str) -> list[str]:
        claim = by_id[claim_id]
        refs = " ".join(f"[{n}]" for n in claim["supports"]) or lab["unsupported"]
        marker = "" if claim["type"] == "observed" else lab["interpretation"]
        if claim.get("verify_status") == "downgraded":
            marker += lab["downgraded"]
        elif claim_id in not_verbatim_ids:
            marker += lab["not_verbatim"]
        out = [f"- **{claim['id']}**{marker} {claim['text']} {refs}"]
        if claim.get("conflict"):
            out.append(f"  - {lab['conflict']}{claim['conflict']}")
        return out

    def source_refs(section_id: str) -> str:
        return " ".join(f"[{n}]" for n in sorted(sources_by[section_id])) or lab["sources_none"]

    def fig_placeholder(fid: str) -> str:
        figure = fig_by_id.get(fid, {})
        refs = " ".join(
            f"[{n}]" for n in sorted(_figure_source_numbers(state, figure))
        ) or lab["sources_none"]
        return lab["figure_placeholder"].format(id=fid, title=figure.get("title", ""), sources=refs)

    if not state["outline"]:
        lines += [lab["no_outline"], ""]
    for top in state["outline"]:
        lines += [
            f"## {top['id']}. {top['title']}", "",
            f"_{lab['sources_prefix']}{source_refs(top['id'])}_", "",
        ]
        own = [cid for cid in claims_by[top["id"]] if by_id[cid].get("section") == top["id"]]
        if own:
            lines += [line for cid in own for line in claim_bullet(cid)]
        for fid in figures_by.get(top["id"], []):
            lines.append(fig_placeholder(fid))
        if own or figures_by.get(top["id"]):
            lines.append("")
        for kid in top["children"]:
            tag = lab["disagreement"] if kid["kind"] == "disagreement" else ""
            lines += [
                f"### {kid['id']} {kid['title']}{tag}", "",
                f"_{lab['sources_prefix']}{source_refs(kid['id'])}_", "",
            ]
            body = [line for cid in claims_by[kid["id"]] for line in claim_bullet(cid)]
            lines += body or [lab["no_claims"]]
            for fid in figures_by.get(kid["id"], []):
                lines.append(fig_placeholder(fid))
            lines.append("")

    lines += [lab["references"], ""]
    if not live:
        lines.append(lab["no_sources"])
    for source in live:
        if final:
            lines.append(_bibliography_line(source, source["n"]))
            continue
        bits = [f"[{source['n']}]"]
        title = source["title"]
        bits.append(f"[{title}]({source['url']})" if source["url"] else title)
        meta = [str(source[k]) for k in ("year", "venue") if source.get(k)]
        if source.get("via"):
            meta.append(f"via {source['via']}")
        if meta:
            bits.append("— " + ", ".join(meta))
        lines.append(" ".join(bits))

    orphans = [c for c in _live_claims(state) if c.get("section") not in index]
    if orphans:
        lines += ["", lab["unplaced"], ""] + [
            f"- **{c['id']}** {c['text']} "
            f"({lab['unplaced_note'].format(section=c.get('section', ''))})"
            for c in orphans
        ]
    orphan_figs = [f for f in _live_figures(state) if f.get("section") not in index]
    if orphan_figs:
        lines += ["", lab["unplaced_figures"], ""] + [
            f"- {f['id']} ({lab['unplaced_note'].format(section=f.get('section', ''))})"
            for f in orphan_figs
        ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- CLI


def _read_payload(args: argparse.Namespace) -> Any:
    raw = args.json if args.json else sys.stdin.read()
    if not raw.strip():
        raise LedgerError("No input: pipe JSON on stdin or pass --json")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LedgerError(f"Input is not valid JSON: {exc.msg}") from None


def _items_from_payload(payload: Any, args: argparse.Namespace) -> list[Any]:
    if args.aminer:
        return extract_from_aminer(payload, args.kind)
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        raise LedgerError("Input must be a JSON array of sources")
    if args.kind:
        for item in payload:
            if isinstance(item, dict):
                item.setdefault("kind", args.kind)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deep-research evidence ledger (offline)")
    parser.add_argument("--state", default=DEFAULT_STATE,
                        help="Ledger file — your workspace decides where; "
                             "defaults to $DR_LEDGER if set")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create or reset the ledger")
    init.add_argument("--topic", default="")
    init.add_argument("--genre", choices=["academic", "industry"], default="academic",
                      help="Report genre: academic (default) or industry (web-first, figures expected)")
    init.add_argument("--force", action="store_true", help="Overwrite an existing ledger")

    probe = sub.add_parser("probe", help="Register a Round 0 scout probe before running it")
    probe.add_argument("--query", required=True)
    probe.add_argument("--axis", required=True, choices=PROBE_AXES, help="Retrieval axis this probe uses")
    probe.add_argument("--via", default="", help="Tool or API the probe runs on")
    probe.add_argument("--note", default="")

    outline = sub.add_parser("outline", help="Create or revise the numbered outline")
    outline_sub = outline.add_subparsers(dest="outline_command", required=True)

    outline_set = outline_sub.add_parser("set", help="Induce the outline from the scout (stdin JSON, or --json)")
    outline_set.add_argument("--json", help="Inline JSON instead of stdin")
    outline_set.add_argument("--force", action="store_true", help="Replace an existing outline")
    outline_set.add_argument("--allow-unscouted", action="store_true",
                             help="Build the outline without probes; the report must disclose it")
    outline_set.add_argument("--length-budget", type=int, default=0,
                             help="User-stated total length budget in 字当量 (Chinese-character "
                                  "equivalents); hard-capped at 80000 like upstream. The outline's "
                                  "per-section target_chars should sum near it")

    outline_add = outline_sub.add_parser("add-sub", help="Append a subsection to a top-level section")
    outline_add.add_argument("--parent", required=True)
    outline_add.add_argument("--title", required=True)
    outline_add.add_argument("--kind", choices=SECTION_KINDS, default="topic")

    outline_add_top = outline_sub.add_parser(
        "add-top", help="Add a top-level section mid-run (a new direction); capped by the registered tier")
    outline_add_top.add_argument("--title", required=True)
    outline_add_top.add_argument("--from-probes", nargs="*", default=[])
    outline_add_top.add_argument("--disagreement", default="",
                                 help="Title of the mandatory disagreement child (default: Disagreement and counter-evidence)")
    outline_add_top.add_argument("--target-chars", type=int, default=0,
                                 help="Writing target for this section in 字当量, assigned by material sufficiency")

    outline_retitle = outline_sub.add_parser("retitle", help="Rename a section without changing its id")
    outline_retitle.add_argument("--section", required=True)
    outline_retitle.add_argument("--title", required=True)

    outline_sub.add_parser("show", help="Print the outline with per-section counts")

    add = sub.add_parser("add", help="Add sources (stdin JSON array, or --json)")
    add.add_argument("--json", help="Inline JSON instead of stdin")
    add.add_argument("--aminer", action="store_true", help="Input is aminer_open.py output; extract entity records")
    add.add_argument("--kind", choices=KINDS, help="Force the source kind")
    add.add_argument("--via", default="", help="How the source was obtained (api name, WebSearch, WebFetch)")
    add.add_argument("--section", action="append", default=[], help="Outline section id; repeatable")
    add.add_argument("--probe", default="", help="Probe id these hits came from")

    claim = sub.add_parser("claim", help="Record a claim and its supporting sources")
    claim.add_argument("--text")
    claim.add_argument("--section", help="Outline section id (see `outline show`)")
    claim.add_argument("--supports", nargs="*", type=int, default=[], help="Source numbers")
    claim.add_argument("--type", choices=CLAIM_TYPES, default="observed")
    claim.add_argument("--conflict", default="", help="Describe an unresolved disagreement between sources")
    claim.add_argument("--allow-unsupported", action="store_true", help="Record an open question with no source")
    claim.add_argument("--evidence", action="append", default=[],
                       help="Verbatim excerpt from a supporting source's stored text; repeatable. "
                            "check verifies a whitespace-insensitive substring match and downgrades failures "
                            "to background info")
    claim.add_argument("--batch", action="store_true",
                       help="Read a JSON array of {section,text,supports,type?,conflict?,evidence?} from --json or stdin")
    claim.add_argument("--json", help="Inline JSON for --batch instead of stdin")

    source = sub.add_parser("source", help="Inspect one source's stored text")
    source_sub = source.add_subparsers(dest="source_command", required=True)
    source_show = source_sub.add_parser("show", help="Print what the ledger read for a source")
    source_show.add_argument("--source", nargs="+", type=int, required=True, help="Source numbers")

    spend = sub.add_parser("spend", help="Record a paid call whose hits were not added")
    spend.add_argument("--api", required=True)
    spend.add_argument("--cny", required=True, type=float, help="Unit price of one call")
    spend.add_argument("--calls", type=int, default=1)

    drop = sub.add_parser("drop", help="Retire scout noise; the citation number stays reserved")
    drop.add_argument("--source", nargs="+", type=int, required=True, help="Source numbers to drop")
    drop.add_argument("--reason", default="")

    fulltext = sub.add_parser(
        "fulltext",
        help="Record an open-access fulltext read (arXiv, Google Patents, publisher OA), or why none exists",
    )
    fulltext.add_argument("--source", type=int, required=True, help="Source number")
    fulltext.add_argument("--url", help="http(s) address the fulltext was fetched from")
    fulltext.add_argument("--via", choices=FULLTEXT_CHANNELS,
                          help="Channel the fulltext came through")
    fulltext.add_argument("--unavailable", action="store_true",
                          help="No open fulltext exists (paywalled); record the downgrade to abstract-level")
    fulltext.add_argument("--note", default="")

    untag = sub.add_parser("untag", help="Remove one section tag from sources a bulk add over-tagged")
    untag.add_argument("--source", nargs="+", type=int, required=True)
    untag.add_argument("--section", required=True)

    retract = sub.add_parser("retract", help="Withdraw a mis-recorded claim; record the corrected one after")
    retract.add_argument("--claim", nargs="+", required=True)
    retract.add_argument("--reason", default="")

    tier = sub.add_parser(
        "tier", help="Register the complexity tier (host-judged); the engine then caps directions "
                     "(top-level sections) and rounds by refusing over-quota registrations")
    tier.add_argument("--level", required=True, choices=TIERS)
    tier.add_argument("--reason", required=True, help="Why this tier — the judgment goes on record")
    tier.add_argument("--force", action="store_true",
                      help="Re-judge an already-registered tier (the change is recorded)")

    round_p = sub.add_parser(
        "round", help="Close a retrieval round: which directions it served, why it stopped, "
                      "what the next round should hunt")
    round_p.add_argument("--why-stopped", required=True,
                         help="Why the round ended — the one signal the engine cannot compute")
    round_p.add_argument("--next-query", action="append", default=[],
                         help="Gap the next round should hunt (progressive deepening reuses these); repeatable")
    round_p.add_argument("--direction", action="append", default=[],
                         help="Top-level section id(s) this round served; repeatable — counts against each one's rerun cap")
    round_p.add_argument("--probe", action="append", default=[], help="Probes that ran this round; repeatable")
    round_p.add_argument("--wasted", action="store_true",
                         help="The round produced nothing; recorded but not charged against tier caps")
    round_p.add_argument("--note", default="")

    memo = sub.add_parser(
        "memo", help="Record the direction-level depth memo (per top-level section; the latest one is what "
                     "evaluation and writing read)")
    memo.add_argument("--section", required=True, help="Top-level section id")
    memo.add_argument("--text", required=True,
                      help="The depth narrative: mechanisms, setups, numbers — what only a full read of the "
                           "originals knows")

    decide = sub.add_parser(
        "decide", help="Record one read-the-signals-then-decided call; signals replays the last five")
    decide.add_argument("--action", required=True, choices=DECISION_ACTIONS,
                        help="stop / continue / add_section / rerun / patch")
    decide.add_argument("--reason", required=True)
    decide.add_argument("--direction", default="", help="Top-level section id, for add_section / rerun / patch")

    verify = sub.add_parser(
        "verify", help="Record citation-faithfulness judgments (supported? confidence?) per claim; "
                       "the engine applies the gates: confidence floor, downgrade-ratio cap")
    verify.add_argument("--claim", help="Single form: claim id")
    verdict = verify.add_mutually_exclusive_group()
    verdict.add_argument("--supported", action="store_true")
    verdict.add_argument("--unsupported", action="store_true")
    verify.add_argument("--confidence", type=float, help="0.0–1.0, how sure the evidence supports the claim")
    verify.add_argument("--reason", default="")
    verify.add_argument("--batch", action="store_true",
                        help="Read a JSON array of {claim,supported,confidence,reason} from --json or stdin")
    verify.add_argument("--json", help="Inline JSON for --batch instead of stdin")

    sub.add_parser("signals", help="Print the evaluator input surface — every number computed by the engine, "
                                   "unrecorded inputs reported as not-recorded, never 0")

    figure = sub.add_parser("figure", help="Record a chart that visualizes ledger claims, then render it")
    figure_sub = figure.add_subparsers(dest="figure_command", required=True)

    figure_add = figure_sub.add_parser("add", help="Register a figure against a section's claims")
    figure_add.add_argument("--section", required=True, help="Outline section id (see `outline show`)")
    figure_add.add_argument("--type", choices=FIGURE_TYPES,
                            help="Template shape; required unless --code is given")
    figure_add.add_argument("--title", required=True)
    figure_add.add_argument("--data", help="JSON the chart plots (pass '-' to read stdin); required unless --from-datums")
    figure_add.add_argument("--sources", nargs="+", type=int,
                            help="Source numbers backing the figure's data; required unless --from-datums (which supplies them)")
    figure_add.add_argument("--claims", nargs="*", default=[], help="Claim ids the figure visualizes")
    figure_add.add_argument("--code", default="",
                            help="Path to a host-written B render script (custom shape; sandboxed by chartrender.py)")
    figure_add.add_argument("--from-datums", nargs="+", default=[],
                            help="Assemble --data (and --sources) from captured datum ids; bar/hbar/pie/line/timeline; "
                                 "numbers are source-verified by construction")
    figure_add.add_argument("--from-source-metadata", action="store_true",
                            help="Assemble --data by counting the given --sources along a metadata field "
                                 "(--field year/venue/assignee/kind); bar/hbar/pie; counts are source-verified by construction")
    figure_add.add_argument("--field", default="",
                            help="Metadata field to aggregate --from-source-metadata by: year, venue, assignee, kind")
    figure_add.add_argument("--plan", default="",
                            help="Figure plan id (fpN) this chart fulfills; closes the plan")
    figure_add.add_argument("--charted-by", choices=("agent", "controller"), default="",
                            help="Who ran this chart's loop: 'agent' (a chart-topic subagent, the "
                                 "default for hosts that can spawn them) or 'controller' (in-session, "
                                 "the exception — requires --charted-reason)")
    figure_add.add_argument("--charted-reason", default="",
                            help="With --charted-by controller (required there): why no chart-topic "
                                 "subagent ran this plan")

    figure_mark = figure_sub.add_parser("mark-rendered", help="Record that chartrender.py produced the PNG")
    figure_mark.add_argument("--id", required=True)
    figure_mark.add_argument("--path", required=True, help="Rendered PNG path")
    figure_mark.add_argument("--by", choices=("script", "template"), required=True)

    figure_sub.add_parser("list", help="Print all figures with their render status")

    figure_drop = figure_sub.add_parser("drop", help="Retire mis-recorded figures")
    figure_drop.add_argument("--id", nargs="+", required=True)
    figure_drop.add_argument("--reason", default="")

    figure_plan = figure_sub.add_parser(
        "plan",
        help="Plan a chart topic after the outline settles: what the figure should answer, "
             "and where; retrieval then hunts that topic's numbers until sufficient")
    figure_plan.add_argument("--section", default="", help="Outline section id the figure would live in")
    figure_plan.add_argument("--topic", default="",
                             help="The quantitative question the chart answers (not its title)")
    figure_plan.add_argument("--type", choices=FIGURE_TYPES, default="",
                             help="Intended shape; timeline plans are exempt from datum sufficiency")
    figure_plan.add_argument("--abandon", default="",
                             help="Plan id to give up on instead of creating one")
    figure_plan.add_argument("--reason", default="",
                             help="With --abandon (required): why no obtainable data exists")

    datum = sub.add_parser("datum", help="Record a number extracted from a source — the data point a figure plots")
    datum_sub = datum.add_subparsers(dest="datum_command", required=True)
    datum_add = datum_sub.add_parser("add", help="Capture one extracted number against a source")
    datum_add.add_argument("--source", type=int, required=True, help="Source number the number was read from")
    datum_add.add_argument("--metric", required=True, help="What the number measures (e.g. 市场规模, 融资额, 市场份额)")
    datum_add.add_argument("--value", required=True, help="The number (e.g. 410, 32.5, 1.2万)")
    datum_add.add_argument("--unit", default="", help="Unit (亿元, %, 亿美元)")
    datum_add.add_argument("--year", default="", help="Year or date the value applies to")
    datum_add.add_argument("--entity", default="", help="Entity the value is about (company, model, region)")
    datum_add.add_argument("--plan", default="", help="Figure plan id (fpN) this number feeds")
    datum_sub.add_parser("list", help="Print captured datums")
    datum_drop = datum_sub.add_parser("drop", help="Retire a mis-captured datum")
    datum_drop.add_argument("--id", nargs="+", required=True)
    datum_drop.add_argument("--reason", default="")

    sub.add_parser("gaps", help="Report coverage gaps before writing")
    sub.add_parser("stats", help="Print ledger totals")
    sub.add_parser("check", help="Exit non-zero when the ledger is not report-ready")
    render = sub.add_parser("render", help="Print the numbered outline, its claims, and the reference list")
    render.add_argument("--final", action="store_true",
                       help="Academic bibliography form; the content reference to write prose against "
                            "(numbers are stable ledger numbers)")
    render.add_argument("--material", action="store_true",
                       help="The writing-preparation surface: per section — writing target, material "
                            "blocks (claims with [@n] marks, verbatim evidence, source notes), a "
                            "ranked re-read list of core originals (per-section cap 5, half weight if "
                            "already listed for an earlier section), and the latest memo. Run this "
                            "before writing; compose from material, not from one-line claims")
    render.add_argument("--appendix", action="store_true",
                       help="Print Appendix A (retrieval log), B (calls and cost) and C (data and methods) instead")
    render.add_argument("--renumber", action="store_true",
                       help="Assign the report's ascending citation numbers: read --draft (prose with "
                            "[@n] placeholders), substitute them, fill the {{references}} slot with a "
                            "cited-only bibliography, and write the delivered report plus a citation-map "
                            "sidecar to --out")
    render.add_argument("--draft", default="",
                       help="With --renumber: the draft markdown to read")
    render.add_argument("--citation-map", default="",
                       help="With --appendix: translate source references to the report's external "
                            "numbers and append Appendix D (the map)")
    render.add_argument("--lang", choices=("auto", "en", "zh"), default="auto",
                       help="Label language; auto follows the ledger topic")
    render.add_argument("--out", default="",
                       help="With --appendix: write the appendices to this file instead of stdout, "
                            "and return the path plus a one-line pointer to quote in the report "
                            "(pass 'auto' for <ledger stem>-appendix.md next to the ledger). "
                            "With --renumber: the delivered report path (required)")
    return parser


def _run_outline(state: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    if args.outline_command == "set":
        if state["outline"] and not args.force:
            raise LedgerError(
                "An outline already exists; pass --force to replace it "
                "(sources keep their old section ids and may become unplaced)"
            )
        nodes = _read_payload(args)
        state["outline"] = _assign_outline(
            nodes, set(_probe_index(state)), require_probes=not args.allow_unscouted
        )
        # Top-level sections are the run's directions; a registered tier
        # caps how many may exist.
        _check_direction_cap(state, len(state["outline"]))
        if args.allow_unscouted:
            state["unscouted"] = True
        response: dict[str, Any] = {"ok": True, "outline": state["outline"],
                                    "unscouted": bool(state.get("unscouted"))}
        # A user-stated length budget (字当量). Upstream hard-caps the parsed
        # budget at 8万 ("超过 8 万字按 8 万算" — clamped, not refused); same here.
        if args.length_budget:
            budget = int(args.length_budget)
            if budget <= 0:
                raise LedgerError("--length-budget must be a positive integer (字当量)")
            if budget > LENGTH_BUDGET_HARD_MAX:
                budget = LENGTH_BUDGET_HARD_MAX
            state["length_budget"] = budget
            response["length_budget"] = budget
        targets = _write_targets(state)
        if targets["total"] is not None:
            response["target_total"] = targets["total"]
        return response

    if args.outline_command == "add-top":
        # Mid-run direction addition (DeepDive's add_direction lands here).
        # A new top-level section carries the disagreement child every
        # top-level section carries — same shape the v1 upgrade builds.
        title = args.title.strip()
        if not title:
            raise LedgerError("A top-level section needs a non-empty --title")
        from_probes = [str(p) for p in (args.from_probes or [])]
        unknown = [p for p in from_probes if p not in _probe_index(state)]
        if unknown:
            raise LedgerError(f"Section cites unknown probe(s): {', '.join(unknown)}")
        _check_direction_cap(state, len(state["outline"]) + 1)
        top = {
            "id": str(len(state["outline"]) + 1),
            "title": title,
            "from_probes": from_probes,
            "children": [{
                "id": f"{len(state['outline']) + 1}.1",
                "title": args.disagreement.strip() or "Disagreement and counter-evidence",
                "kind": "disagreement",
                "from_probes": [],
            }],
        }
        if args.target_chars:
            if args.target_chars <= 0:
                raise LedgerError("--target-chars must be positive (字当量)")
            top["target_chars"] = args.target_chars
        state["outline"].append(top)
        return {"ok": True, "section": top}

    if args.outline_command == "add-sub":
        top = _find_top(state, args.parent)
        title = args.title.strip()
        if not title:
            raise LedgerError("A subsection needs a non-empty --title")
        kid = {"id": _next_sub_id(top), "title": title, "kind": args.kind, "from_probes": []}
        top["children"].append(kid)
        return {"ok": True, "section": kid}

    if args.outline_command == "retitle":
        index = _section_index(state)
        node = index.get(args.section)
        if node is None:
            raise LedgerError(
                f"Unknown section id '{args.section}'. Valid ids: {', '.join(index) or 'none'}"
            )
        title = args.title.strip()
        if not title:
            raise LedgerError("A section needs a non-empty --title")
        node["title"] = title
        return {"ok": True, "section": {"id": node["id"], "title": node["title"]}}

    return {"ok": True, "sections": analyze(state)["sections"]}


def _public_figure(figure: dict[str, Any]) -> dict[str, Any]:
    """Trim a figure for JSON output — drop the (possibly large) `data` blob
    and the `dropped` bookkeeping flag; everything the host needs to cite and
    re-render the figure stays."""
    return {
        key: figure[key] for key in (
            "id", "section", "chart_type", "title", "source_ids", "claim_ids",
            "rendered", "rendered_by", "render_path", "code_path", "from_datums",
            "from_metadata", "plan", "charted_by", "charted_reason",
        ) if key in figure
    }


def _run_figure(state: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    if args.figure_command == "plan":
        if args.abandon:
            plan = _abandon_figure_plan(state, args.abandon, args.reason.strip())
            return {"ok": True, "plan": plan}
        if not args.section or not args.topic:
            raise LedgerError(
                "A figure plan needs --section and --topic (or --abandon <id> --reason …)"
            )
        plan, superseded = _add_figure_plan(state, args.section, args.topic, args.type or "")
        return {
            "ok": True,
            "plan": plan,
            "superseded": superseded,
            "needs_datums": (
                PLAN_MIN_DATUMS if (args.type or "") != "timeline" else None
            ),
            # The dispatch moment is plan time, not chart time — say so where
            # the controller is looking right now (references/chart-guide.md
            # §Who charts).
            "dispatch": (
                "one chart-topic subagent per open plan, now — a host that can "
                "spawn subagents delegates the plan's research loop; the "
                "subagent delivers record JSON (brief in, records out, never "
                "touching the ledger) and the controller, the only writer, "
                "enters it (datum add --plan, figure add --charted-by agent) "
                "and runs the render chain (chartrender, mark-rendered). The "
                "controller researches in-session only when it cannot spawn "
                "subagents (figure add --charted-by controller "
                "--charted-reason …)"
            ),
        }
    if args.figure_command == "add":
        from_datums = list(args.from_datums or [])
        from_metadata = bool(args.from_source_metadata)
        if from_datums and from_metadata:
            raise LedgerError("Use --from-datums or --from-source-metadata, not both")
        if from_datums:
            if not args.type:
                raise LedgerError("--from-datums requires --type (bar / hbar / pie / line / timeline)")
            data, sources = _assemble_figure_data(state, from_datums, args.type)
        elif from_metadata:
            if not args.type:
                raise LedgerError("--from-source-metadata requires --type (bar / hbar / pie)")
            if not args.field:
                raise LedgerError("--from-source-metadata requires --field (year / venue / assignee / kind)")
            if not args.sources:
                raise LedgerError("--from-source-metadata needs --sources to aggregate")
            data, sources = _assemble_metadata_figure(state, list(args.sources), args.field, args.type)
        else:
            if not args.data:
                raise LedgerError("A figure needs --data JSON, or --from-datums <ids>, or --from-source-metadata")
            raw = sys.stdin.read() if args.data == "-" else args.data
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise LedgerError(f"--data is not valid JSON: {exc.msg}") from None
            if not args.sources:
                raise LedgerError("A figure needs --sources, or --from-datums / --from-source-metadata to supply them")
            sources = list(args.sources)
        figure = _record_figure(
            state,
            section=args.section,
            chart_type=args.type or "",
            title=args.title,
            data=data,
            sources=sources,
            claims=list(args.claims),
            code_path=args.code or "",
            from_datums=bool(from_datums),
            from_metadata=from_metadata,
            plan=(args.plan or "").strip(),
            charted_by=(args.charted_by or "").strip(),
            charted_reason=(args.charted_reason or "").strip(),
        )
        return {"ok": True, "figure": _public_figure(figure)}
    if args.figure_command == "mark-rendered":
        figure = _mark_figure_rendered(state, args.id, args.path, args.by)
        return {"ok": True, "figure": _public_figure(figure)}
    if args.figure_command == "drop":
        result = _drop_figures(state, list(args.id), args.reason.strip())
        return {"ok": True, **result}
    return {
        "ok": True,
        "figures": [_public_figure(f) for f in _live_figures(state)],
        "figure_plans": [dict(p) for p in _live_plans(state)],
    }


def _run_datum(state: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    if args.datum_command == "add":
        datum = _record_datum(
            state, args.source, args.metric, args.value, args.unit, args.year, args.entity,
            plan=(args.plan or "").strip(),
        )
        return {"ok": True, "datum": _public_datum(datum)}
    if args.datum_command == "drop":
        result = _drop_datums(state, list(args.id), args.reason.strip())
        return {"ok": True, **result}
    return {"ok": True, "datums": [_public_datum(d) for d in _live_datums(state)]}


def run(args: argparse.Namespace) -> tuple[Any, int]:
    if not args.state:
        raise LedgerError(
            "No ledger path given. Set $DR_LEDGER (e.g. "
            "export DR_LEDGER=<workspace>/evidence-ledger.json) or pass "
            "--state <path>. The skill owns no default location."
        )
    path = Path(args.state)

    if args.command == "init":
        if path.exists() and not args.force:
            raise LedgerError(f"{path} already exists; pass --force to reset it")
        state = _empty_state()
        state["topic"] = args.topic
        state["genre"] = args.genre
        save_state(path, state)
        return {"ok": True, "state": str(path), "topic": state["topic"],
                "genre": state["genre"], "outline": []}, 0

    state = load_state(path)

    if args.command == "probe":
        probe = _add_probe(state, args)
        save_state(path, state)
        return {"ok": True, "probe": probe}, 0

    if args.command == "outline":
        payload = _run_outline(state, args)
        if args.outline_command != "show":
            save_state(path, state)
        return payload, 0

    if args.command == "add":
        payload = _read_payload(args)
        sections = _require_sections(state, args.section) if args.section else []
        probe = None
        if args.probe:
            probe = _probe_index(state).get(args.probe)
            if probe is None:
                raise LedgerError(
                    f"Unknown probe '{args.probe}'; register it with `evidence.py probe` first"
                )
        result = _add_sources(state, _items_from_payload(payload, args), args.via, sections, args.probe)
        wasted: list[dict[str, Any]] = []
        if args.aminer:
            _spend_from_aminer(state, payload)
            wasted = _paid_calls_without_hits(payload, args.kind)
        if probe is not None:
            probe["new"] += len(result["added"])
            probe["dup"] += len(result["duplicates"])
            probe["returned"] += len(result["added"]) + len(result["duplicates"])
        save_state(path, state)
        payload_out = {"ok": True, **result, "spend_total_cny": _spend_total(state)}
        if wasted:
            payload_out["paid_calls_without_hits"] = wasted
        return payload_out, 0

    if args.command == "claim":
        if args.batch:
            result = _add_claims_batch(state, _read_payload(args))
            save_state(path, state)
            return {"ok": not result["failed"], **result}, 0 if not result["failed"] else 1
        if not args.text or not args.section:
            raise LedgerError("A single claim needs --text and --section (or pass --batch)")
        claim = _add_claim(state, args)
        save_state(path, state)
        return {"ok": True, "claim": claim}, 0

    if args.command == "source":
        by_number = {source["n"]: source for source in state["sources"]}
        unknown = [n for n in args.source if n not in by_number]
        if unknown:
            raise LedgerError(f"Unknown source number(s): {', '.join(str(n) for n in unknown)}")
        shown = []
        for n in args.source:
            source = by_number[n]
            shown.append({
                key: source[key] for key in (
                    "n", "kind", "id", "title", "url", "year", "venue", "authors", "assignee",
                    "pub_num", "app_num", "pub_kind",
                    "keywords", "abstract", "abstract_slice", "note", "depth", "fulltext",
                    "fulltext_unavailable", "fulltext_note", "sections",
                    "probes", "via", "dropped", "drop_reason",
                ) if key in source
            })
        return {"ok": True, "sources": shown}, 0

    if args.command == "spend":
        _record_spend(state, args.api, args.cny, args.calls)
        save_state(path, state)
        return {"ok": True, "spend": state["spend"], "total_cny": _spend_total(state)}, 0

    if args.command == "drop":
        result = _drop_sources(state, args.source, args.reason.strip())
        save_state(path, state)
        return {"ok": True, **result}, 0

    if args.command == "fulltext":
        result = _mark_fulltext(
            state, args.source,
            url=(args.url or "").strip(), via=args.via,
            unavailable=args.unavailable, note=args.note.strip(),
        )
        save_state(path, state)
        return {"ok": True, **result}, 0

    if args.command == "untag":
        result = _untag_sources(state, args.source, args.section)
        save_state(path, state)
        return {"ok": True, **result}, 0

    if args.command == "retract":
        result = _retract_claims(state, args.claim, args.reason.strip())
        save_state(path, state)
        return {"ok": True, **result}, 0

    if args.command == "tier":
        result = _register_tier(state, args.level, args.reason.strip(), args.force)
        save_state(path, state)
        return result, 0

    if args.command == "round":
        result = _register_round(
            state, args.why_stopped, list(args.next_query), list(args.direction),
            list(args.probe), args.wasted, args.note,
        )
        save_state(path, state)
        return result, 0

    if args.command == "memo":
        result = _add_memo(state, args.section, args.text)
        save_state(path, state)
        return result, 0

    if args.command == "decide":
        result = _record_decision(state, args.action, args.direction.strip(), args.reason)
        save_state(path, state)
        return result, 0

    if args.command == "verify":
        if args.batch:
            entries = _read_payload(args)
            if isinstance(entries, dict):
                entries = [entries]
        else:
            if not args.claim or args.confidence is None or not (args.supported or args.unsupported):
                raise LedgerError(
                    "verify needs --claim, --supported|--unsupported and --confidence "
                    "(or --batch with a JSON array of judgments)"
                )
            entries = [{
                "claim": args.claim,
                "supported": bool(args.supported),
                "confidence": args.confidence,
                "reason": args.reason,
            }]
        result = _apply_verify(state, entries)
        save_state(path, state)
        return result, 0

    if args.command == "signals":
        # Read-only: the evaluator input surface never mutates the ledger.
        return _signals(state), 0

    if args.command == "figure":
        payload = _run_figure(state, args)
        if args.figure_command not in ("list",):
            save_state(path, state)
        return payload, 0

    if args.command == "datum":
        payload = _run_datum(state, args)
        if args.datum_command not in ("list",):
            save_state(path, state)
        return payload, 0

    if args.command == "stats":
        report = analyze(state)
        return {"ok": True, **report["totals"], "spend_total_cny": report["spend"]["total_cny"]}, 0

    if args.command == "gaps":
        return {"ok": True, **analyze(state)}, 0

    if args.command == "check":
        report = analyze(state)
        blocking = {
            "outline_missing": report["outline_missing"],
            "unsupported_claims": report["unsupported_claims"],
            "sections_below_two_sources": report["sections_below_two_sources"],
            "spend_over_hard_limit": report["spend_over_hard_limit"],
            "figures_with_no_sources": report["figures_with_no_sources"],
            "figures_in_unrendered_section": report["figures_in_unrendered_section"],
            # A cited source with no note at all: the note is the digest the
            # material surface serves and the channel the number-provenance
            # checks search — a citation leaning on an unrecorded read is a
            # claim the ledger cannot vouch for. Binary and unambiguous, so
            # it blocks; thin notes only warn.
            "cited_sources_without_note": report["cited_sources_without_note"],
            # L3 (user decision 2026-08-30, zero exemption): a live keeper
            # nobody wrote a word about is retrieval spend that never became
            # material — read it (note) or drop it; datum carriers and
            # corpus-aggregation sources get no carve-out. Upstream has this
            # by construction (its reader's output schema IS the record);
            # here the check is the construction.
            "sources_without_note": report["sources_without_note"],
        }
        failed = (
            any(blocking.values())
            or report["totals"]["sources"] == 0
            or report["totals"]["claims"] == 0
        )
        return {
            "ok": not failed,
            "blocking": blocking,
            "warnings": {key: report[key] for key in (
                "subsections_below_two_sources",
                "sections_missing_disagreement",
                "sections_from_single_probe",
                "low_yield_probes",
                "drifting_probes",
                "sections_without_claims",
                "untagged_sources",
                "sources_without_probe",
                "cited_sources_without_detail",
                "cited_sources_without_fulltext",
                "single_source_claims",
                "claims_weak_patent_sole_support",
                "claims_with_unsourced_numbers",
                "tier_missing",
                "sections_without_memo",
                "sections_single_sourced",
                "claims_evidence_not_verbatim",
                "claims_verify_downgraded",
                "claims_awaiting_verify",
                "memos_thin",
                "verify_reasons_boilerplate",
                "disagreements_without_conflict",
                "figure_plans_closed_untagged",
                "sections_without_target_chars",
                "write_targets_over_max",
                "write_targets_over_material",
                "sections_under_targeted_vs_material",
                "cited_sources_note_thin",
                "claims_thin_evidence",
                "rounds_without_yield",
                "figures_unsupported_numbers",
                "figures_without_render",
                "figures_over_budget",
                "figures_industry_expected",
                "figures_industry_quantitative_expected",
                "figures_thin_data",
                "figures_charting_undeclared",
                "figures_charted_in_controller",
                "figure_plans_thin",
                "figure_plans_unfulfilled",
                "figure_plans_abandoned",
                "figure_plans_industry_expected",
                "sections_over_figure_budget",
                "figure_code_divergence",
                "uncited_sources",
                "datums_without_source",
                "industry_web_sources_without_datums",
                "unresolved_conflicts",
            )},
            "totals": report["totals"],
            "spend": report["spend"],
        }, 1 if failed else 0

    if args.command == "render":
        if args.renumber:
            if args.final or args.appendix or args.material:
                raise LedgerError("--renumber cannot be combined with --final, --appendix or --material")
            if not args.draft or not args.out:
                raise LedgerError("render --renumber needs --draft <path> and --out <path>")
            return _renumber_draft(state, Path(args.draft), Path(args.out), args.lang,
                                   ledger=path.as_posix()), 0
        if args.material:
            if args.final or args.appendix:
                raise LedgerError("--material cannot be combined with --final or --appendix")
            return _material_markdown(state, args.lang), 0
            if not args.draft or not args.out:
                raise LedgerError("render --renumber needs --draft <path> and --out <path>")
            return _renumber_draft(state, Path(args.draft), Path(args.out), args.lang,
                                   ledger=path.as_posix()), 0
        if args.appendix:
            citation_map = None
            if args.citation_map:
                map_path = Path(args.citation_map)
                try:
                    citation_map = json.loads(map_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise LedgerError(f"Cannot read citation map {map_path}: {exc}") from None
                if not isinstance(citation_map.get("ledger_to_external"), dict):
                    raise LedgerError(
                        f"Citation map {map_path} carries no ledger_to_external table; "
                        "it is written by `render --renumber` next to the delivered report"
                    )
            markdown = _appendix_markdown(state, args.lang, citation_map)
            if not args.out:
                return markdown, 0
            # The appendices are bookkeeping, not reading matter: writing them
            # out keeps probe ids, endpoint names and CNY amounts off the page
            # the reader actually gets, and leaves one quotable line behind.
            out = path.with_name(f"{path.stem}-appendix.md") if args.out == "auto" else Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(markdown if markdown.endswith("\n") else markdown + "\n", encoding="utf-8")
            lab = _labels(state, args.lang)
            pointer_key = "pointer_with_map" if citation_map else "pointer"
            pointer = lab[pointer_key].format(path=out.as_posix())
            return {"ok": True, "path": out.as_posix(), "pointer": pointer}, 0
        return render_markdown(state, final=args.final, lang=args.lang), 0

    raise LedgerError(f"Unknown command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        payload, code = run(parser.parse_args(argv))
    except LedgerError as exc:
        print(json.dumps({"ok": False, "error": "invalid_request", "message": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    if isinstance(payload, str):
        print(payload, end="")
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
