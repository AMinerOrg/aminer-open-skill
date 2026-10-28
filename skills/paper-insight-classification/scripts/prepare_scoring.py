#!/usr/bin/env python
"""Step 2: pick the opinion sentences from the stage-1 labels, attach evidence from the cited references, and write
the stage-2 (three-dimension scoring) batches plus a section digest for section typing.

This prepares InsightEval's Stage 2/3 input: every opinion sentence o_i comes with a set of evidence E_i taken from
the references it cites; the agent compares first, writes a rationale, then scores Depth / Breadth / Height (1-5).

Usage:
    python prepare_scoring.py work/sentences.json --stage1 work/labels --evidence work/evidence.json
Output:
    work/stage2/batch_001.txt ...   opinion sentences + evidence (the agent scores them batch by batch)
    work/stage2/plan.json           selected sentences, evidence scope and evidence coverage (used by the report)
    work/sections.txt               digest of the sections that contain citations (the agent types them)
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import dump_json, load_json, setup_io  # noqa: E402
from insight_lib import load_stage1  # noqa: E402

_STOP = set("the a an of to in on for and or is are was were be been by with as at from that this these those it its we our "
            "can may not but which their they has have had also such than then into over more most".split())
_TOKEN = re.compile(r"[a-z][a-z\-]{2,}|\d+(?:\.\d+)?|[一-鿿]{1}")


def tokens(text: str) -> list[str]:
    toks = [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]
    cjk = [t for t in toks if "一" <= t <= "鿿"]
    if cjk:  # CJK uses bigrams to avoid single-character noise
        toks = [t for t in toks if not ("一" <= t <= "鿿")] + ["".join(p) for p in zip(cjk, cjk[1:])]
    return toks


def overlap(query: set[str], passage: str) -> float:
    pt = tokens(passage)
    return sum(t in query for t in set(pt)) / math.sqrt(len(pt) + 1) if pt else 0.0


def split_sents(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?。！？])\s+", text) if s.strip()]


def select_evidence(sentence: str, ev: dict, budget: int = 650) -> str:
    """Lightweight "retrieval": pick the passages / abstract sentences with the highest lexical overlap with the opinion."""
    q = set(tokens(sentence))
    passages = [p for p in (ev.get("passages") or []) if p.strip()]
    if passages:
        ranked = sorted(passages, key=lambda p: overlap(q, p), reverse=True)[:2]
        return " … ".join(p[:budget // 2] for p in ranked)
    abstract = (ev.get("abstract") or "").strip()
    if len(abstract) <= budget:
        return abstract
    sents = split_sents(abstract)
    top = sorted(range(len(sents)), key=lambda i: overlap(q, sents[i]), reverse=True)[:3]
    out = " ".join(sents[i] for i in sorted(top))
    return out if len(out) <= budget else out[:budget].rstrip() + "…"


def evidence_scope(s: dict, para_refs: dict[str, list[int]], cap: int = 5) -> tuple[str, list[int]]:
    if s["ref_ids"]:
        return "sentence", s["ref_ids"][:cap]
    pr = para_refs.get(str(s["paragraph_id"]), [])
    if pr:
        return "paragraph", pr[:cap]
    return "none", []


def ref_line(rid: int, refs: dict, evidence: dict, sentence: str) -> tuple[str, bool]:
    r = refs.get(str(rid), {})
    au = (r.get("authors") or [])
    who = (au[0].split()[-1] + (" et al." if len(au) > 1 else "")) if au else ""
    meta = ", ".join(str(x) for x in (who, r.get("year")) if x)
    head = f"[R{rid}] {r.get('title', '(unknown title)')}" + (f" ({meta})" if meta else "")
    if r.get("title_guess"):
        head += " [title is a rule-based guess]"
    ev = evidence.get(str(rid)) or {}
    if ev.get("matched") is False or not (ev.get("abstract") or ev.get("passages")):
        return f"  {head} | no abstract/full-text evidence, title only", False
    return f"  {head} | excerpt: {select_evidence(sentence, ev)}", True


def pick_even(items: list[dict], n: int) -> list[dict]:
    if n <= 0 or len(items) <= n:
        return items
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]


def render_stage2(data: dict, ids: list[int], evidence: dict, batch_size: int) -> tuple[list[tuple[str, str]], list[dict]]:
    by_id = {s["id"]: s for s in data["sentences"]}
    refs, para_refs = data["refs"], data.get("paragraph_refs", {})
    n_batches = max(1, -(-len(ids) // batch_size))
    batches, plan = [], []
    for b in range(n_batches):
        chunk = ids[b * batch_size:(b + 1) * batch_size]
        if not chunk:
            break
        lines = [
            f"# Stage 2 | batch {b + 1}/{n_batches} | {len(chunk)} opinion sentences (ids {chunk[0]}-{chunk[-1]})",
            "# Task: for each opinion sentence, compare it with the evidence, write a rationale (<= 60 words), then give "
            "depth / breadth / height as integers 1-5 plus a confidence. Rubric: references/rubric.md.",
            f'# Output: scores/stage2_{b + 1:03d}.json -- [{{"id": {chunk[0]}, "depth": 3, "breadth": 2, "height": 4, '
            '"confidence": "medium", "rationale": "..."}]',
            "",
        ]
        for sid in chunk:
            s = by_id[sid]
            scope, rids = evidence_scope(s, para_refs)
            ev_lines, with_abs = [], 0
            for rid in rids:
                line, ok = ref_line(rid, refs, evidence, s["text"])
                ev_lines.append(line)
                with_abs += ok
            plan.append({"id": sid, "scope": scope, "refs": rids, "with_evidence": with_abs})
            lines.append(f"=== [{sid}] {s['section']} (p.{s['page']}) | evidence_scope={scope} ===")
            if s["prev"]:
                lines.append(f"Previous sentence: {s['prev'][:300]}")
            lines.append(f"Opinion sentence: {s['text'][:700]}")
            if ev_lines:
                lines.append("Evidence:" + ("" if scope == "sentence" else
                                            " (this sentence has no citation marker; using references cited elsewhere in the same paragraph)"))
                lines.extend(ev_lines)
            else:
                lines.append("Evidence: none (neither this sentence nor its paragraph cites anything) -> apply the "
                             "'no evidence' rule of the rubric and set confidence to low")
            lines.append("")
        batches.append((f"batch_{b + 1:03d}.txt", "\n".join(lines)))
    return batches, plan


def render_sections(data: dict, max_sents: int = 10) -> str:
    by_sec: dict[int, list[dict]] = {}
    for s in data["sentences"]:
        by_sec.setdefault(s["section_idx"], []).append(s)
    body: list[str] = []
    n = 0
    for sec in data["sections"]:
        sents = by_sec.get(sec["idx"], [])
        if sec["citing"] < 1 or len(sents) < 3:
            continue
        n += 1
        body.append(f"=== [{sec['idx']}] {sec['title']} | {len(sents)} sentences | {sec['citing']} citing | "
                    f"{len(sec['ref_ids'])} references ===")
        body.extend(f"  - {s['text'][:180]}" for s in pick_even(sents, max_sents))
        body.append("")
    head = [
        "# Section typing (paper Table 2)",
        "# Task: type each section as descriptive (factual overview) / comparative (compares approaches) / "
        "analytical (offers insight and critical analysis).",
        '# Output: labels/sections.json -- {"3": "analytical", "4": "descriptive"} (key = section idx)',
        f"# Only sections with >= 1 citing sentence and >= 3 sentences are listed ({n} here); the others are not typed.",
        "",
    ]
    return "\n".join(head + body) + "\n"


def main() -> int:
    setup_io()
    ap = argparse.ArgumentParser(description="Build stage-2 scoring batches and the section digest")
    ap.add_argument("sentences", type=Path, help="sentences.json from prepare_sentences.py")
    ap.add_argument("--stage1", type=Path, nargs="+", required=True, help="stage-1 label files or directories")
    ap.add_argument("--evidence", type=Path, help="evidence.json from fetch_evidence.py (optional)")
    ap.add_argument("--batch-dir", type=Path, help="stage-2 batch directory (default <sentences dir>/stage2)")
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--max-opinions", type=int, default=0, help="evenly sample at most this many opinion sentences (0 = all)")
    ap.add_argument("--sections-out", type=Path, help="section digest path (default <sentences dir>/sections.txt)")
    args = ap.parse_args()

    data = load_json(args.sentences)
    labels, covered, warns = load_stage1(args.stage1)
    for w in warns:
        print(f"WARNING: {w}")
    missing = [s["id"] for s in data["sentences"] if s["id"] not in covered]
    if missing:
        print(f"WARNING: {len(missing)} sentences have no stage-1 label (e.g. {missing[:8]}); falling back to the rule prior "
              "-- consider labeling them")
    types = {s["id"]: labels.get(s["id"], s["rule"]["type"]) for s in data["sentences"]}
    opinion = [s for s in data["sentences"] if types[s["id"]] == "opinion"]
    chosen = pick_even(opinion, args.max_opinions)
    evidence = load_json(args.evidence) if args.evidence else {}

    out_dir = args.batch_dir or args.sentences.parent / "stage2"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("batch_*.txt"):
        old.unlink()
    batches, plan = render_stage2(data, [s["id"] for s in chosen], evidence, args.batch_size)
    for name, text in batches:
        (out_dir / name).write_text(text, encoding="utf-8")
    dump_json({"opinion_total": len(opinion), "selected": len(chosen), "sampled": len(chosen) < len(opinion), "items": plan},
              out_dir / "plan.json")

    sec_path = args.sections_out or args.sentences.parent / "sections.txt"
    sec_path.write_text(render_sections(data), encoding="utf-8")

    counts = {t: sum(1 for v in types.values() if v == t) for t in ("context", "citation", "opinion")}
    scopes = {k: sum(1 for p in plan if p["scope"] == k) for k in ("sentence", "paragraph", "none")}
    with_ev = sum(1 for p in plan if p["with_evidence"])
    print(f"Sentence types: context {counts['context']} | citation {counts['citation']} | opinion {counts['opinion']}")
    print(f"Opinion sentences to score {len(chosen)}/{len(opinion)} | evidence scope sentence {scopes['sentence']} / "
          f"paragraph {scopes['paragraph']} / none {scopes['none']} | with abstract or full-text evidence {with_ev}")
    print(f"Wrote {len(batches)} stage-2 batches -> {out_dir}; section digest -> {sec_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
