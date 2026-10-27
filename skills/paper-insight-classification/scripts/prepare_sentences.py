#!/usr/bin/env python
"""Step 1: paper -> sentence table (sections, citation markers, rule priors) + stage-1 labeling batches.

This is InsightEval's Stage 1: parse the PDF keeping section boundaries and in-text citations, then hand every
sentence to the agent to classify as context / citation / opinion. The script only parses and computes a rule-based
prior; the final classification is the agent's job.

Usage:
    python prepare_sentences.py paper.pdf --references work/out/references.json -o work/sentences.json
Output:
    work/sentences.json            full sentence table (input of the later scripts)
    work/stage1/batch_001.txt ...  text batches for the agent to read and label
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import dump_json, load_json, setup_io  # noqa: E402

SKIP_SECTION = re.compile(
    r"^\s*(?:[\dA-Z]{1,3}[.\s]+)*(acknowledg|致\s*谢|references?\b|参\s*考\s*文\s*献|bibliography|appendi|附\s*录|ethic|checklist)",
    re.I,
)

_EN_STRONG = re.compile(
    r"\b(however|nevertheless|nonetheless|crucially|importantly|notably|surprisingly|interestingly|in contrast|by contrast|"
    r"we (?:argue|contend|posit|hypothesi[sz]e|believe|claim|conjecture)|we (?:suggest|propose) that|"
    r"this (?:suggests|indicates|implies|reveals|highlights|demonstrates|explains)|"
    r"these (?:findings|results|observations) (?:suggest|indicate|imply|reveal|highlight)|(?:suggests|indicates|implies) that|"
    r"a (?:key|crucial|fundamental) (?:insight|limitation|challenge|issue|observation)|"
    r"the (?:key|core|main|fundamental) (?:insight|reason|issue|limitation|challenge|difference)|"
    r"fails? to|failed to|overlooks?|neglects?|ignores?|unlike|rather than|instead of|arguably|in essence|fundamentally|"
    r"essentially|at (?:its|their) core|paradox|trade-?offs?|bottlenecks?)\b",
    re.I,
)
_EN_WEAK = re.compile(
    r"\b(because|therefore|thus|hence|whereas|although|despite|should|must|we (?:find|observe)|our (?:analysis|results|findings)|"
    r"limitations?|gaps?|can be (?:seen|viewed|understood) as|while)\b",
    re.I,
)
_ZH_STRONG = re.compile(
    r"然而|但是|不过|值得注意的是|关键在于|本文认为|我们认为|我们主张|这表明|这说明|这意味着|这揭示|由此可见|本质上|究其原因|"
    r"根本原因|相比之下|与之不同|与此不同|并非|而非|未能|忽视|忽略|局限|尚未|不足以|悖论|权衡|瓶颈"
)
_ZH_WEAK = re.compile(r"因为|因此|所以|由于|虽然|尽管|应当|必须|可以看作|我们发现|我们观察到|我们的(?:分析|结果)|差距")


def rule_prior(text: str, has_citation: bool, lang: str) -> dict:
    """Rule prior: discourse markers + whether the sentence carries a citation. A hint only; the agent may overrule it."""
    strong_re, weak_re = (_ZH_STRONG, _ZH_WEAK) if lang == "zh" else (_EN_STRONG, _EN_WEAK)
    strong = [m.group(0).lower() for m in strong_re.finditer(text)]
    weak = [m.group(0).lower() for m in weak_re.finditer(text)]
    if strong:
        return {"type": "opinion", "strength": "strong", "signals": sorted(set(strong))[:4]}
    if len(set(weak)) >= 3:
        return {"type": "opinion", "strength": "weak", "signals": sorted(set(weak))[:4]}
    return {"type": "citation" if has_citation else "context", "strength": "", "signals": sorted(set(weak))[:2]}


def _ref_title_guess(raw: str) -> str:
    raw = re.sub(r"https?://\S+|\bdoi:?\s*10\.\S+", " ", raw, flags=re.I).strip()
    m = re.search(r"[“\"](.{10,300}?)[”\"]", raw)
    if m:
        return m.group(1).strip(" ,.")
    parts = [p.strip(" .") for p in re.split(r"(?<=[a-z0-9\)])\.\s+(?=[A-Z0-9“\"])", raw) if p.strip(" .")]
    cand = [p for p in parts[1:] if not re.match(r"^\(?(?:19|20)\d{2}[a-z]?\)?$", p) and len(p) >= 8]
    return (cand[0] if cand else raw)[:300]


def _short(text: str, lang: str) -> bool:
    letters = sum(c.isalpha() for c in text)
    if letters < len(text) * 0.4:
        return True
    return len(text) < 10 if lang == "zh" else len(text.split()) < 5


def build(doc, refs_table: dict[int, dict]) -> dict:
    from pdfparse.text_utils import split_sentences  # noqa: E402

    cit = {(c.paragraph_id, c.sentence): c for c in doc.citations}
    level_of = {s.title: s.level for s in doc.sections}
    sections: list[dict] = []
    sec_idx: dict[str, int] = {}
    sentences: list[dict] = []
    para_refs: dict[int, set[int]] = {}
    skipped_short = skipped_section = 0

    for p in doc.paragraphs:
        if p.kind not in ("body", "abstract"):
            continue
        if SKIP_SECTION.match(p.section or ""):
            skipped_section += 1
            continue
        if p.section not in sec_idx:
            sec_idx[p.section] = len(sections)
            sections.append({"idx": len(sections), "title": p.section, "level": level_of.get(p.section, 1),
                             "sentences": 0, "citing": 0, "ref_ids": []})
        sec = sections[sec_idx[p.section]]
        prev = ""
        for text in split_sentences(p.text, doc.lang):
            if _short(text, doc.lang):
                skipped_short += 1
                prev = text if len(text) > 3 else prev
                continue
            c = cit.get((p.id, text))
            ref_ids = list(c.ref_ids) if c else []
            sentences.append({
                "id": len(sentences) + 1, "section_idx": sec["idx"], "section": p.section, "paragraph_id": p.id,
                "page": p.page, "text": text, "prev": prev, "markers": list(c.markers) if c else [], "ref_ids": ref_ids,
                "rule": rule_prior(text, bool(ref_ids), doc.lang),
            })
            sec["sentences"] += 1
            sec["citing"] += bool(ref_ids)
            sec["ref_ids"] = sorted(set(sec["ref_ids"]) | set(ref_ids))
            para_refs.setdefault(p.id, set()).update(ref_ids)
            prev = text

    by_rule = {t: sum(1 for s in sentences if s["rule"]["type"] == t) for t in ("context", "citation", "opinion")}
    return {
        "source": {"title": doc.title, "type": doc.source, "pages": doc.pages},
        "lang": doc.lang,
        "citation_style": doc.citation_style,
        "stats": {
            "sentences": len(sentences), "citing_sentences": sum(1 for s in sentences if s["ref_ids"]),
            "skipped_short": skipped_short, "skipped_section_paragraphs": skipped_section,
            "sections": len(sections), "references": len(refs_table), "by_rule": by_rule,
        },
        "warnings": list(doc.warnings),
        "sections": sections,
        "refs": {str(k): v for k, v in refs_table.items()},
        "paragraph_refs": {str(k): sorted(v) for k, v in para_refs.items() if v},
        "sentences": sentences,
    }


def render_stage1(data: dict, batch_size: int) -> list[tuple[str, str]]:
    sents = data["sentences"]
    n_batches = max(1, -(-len(sents) // batch_size))
    out = []
    for b in range(n_batches):
        chunk = sents[b * batch_size:(b + 1) * batch_size]
        if not chunk:
            break
        lo, hi = chunk[0]["id"], chunk[-1]["id"]
        lines = [
            f"# Stage 1 | batch {b + 1}/{n_batches} | sentences {lo}-{hi}",
            "# Task: label every sentence context / citation / opinion (definitions: SKILL.md and references/rubric.md). "
            "rule= is a rule-based prior; overrule it when the sentence says otherwise.",
            f'# Output: labels/stage1_{b + 1:03d}.json, e.g. {{"range": [{lo}, {hi}], "opinion": [..], "citation": [..]}} '
            "(ids inside the range that are not listed = context)",
            "",
        ]
        last_sec = None
        for s in chunk:
            if s["section"] != last_sec:
                lines.append(f"## {s['section']}")
                last_sec = s["section"]
            r = s["rule"]
            tag = r["type"] + (f"/{r['strength']}" if r["strength"] else "")
            refs = f" refs={s['ref_ids']}" if s["ref_ids"] else ""
            sig = f" ({', '.join(r['signals'])})" if r["signals"] and r["type"] == "opinion" else ""
            lines.append(f"[{s['id']}] rule={tag}{sig}{refs}")
            lines.append(f"    {s['text'][:700]}")
        out.append((f"batch_{b + 1:03d}.txt", "\n".join(lines) + "\n"))
    return out


def main() -> int:
    setup_io()
    ap = argparse.ArgumentParser(description="Paper -> sentence table + stage-1 labeling batches")
    ap.add_argument("input", type=Path, help="paper file: .pdf / .docx / .txt / .md")
    ap.add_argument("--references", type=Path,
                    help="references.json from paper-reference-extraction (recommended)")
    ap.add_argument("-o", "--output", type=Path, default=Path("sentences.json"))
    ap.add_argument("--batch-dir", type=Path, help="stage-1 batch directory (default <output dir>/stage1)")
    ap.add_argument("--batch-size", type=int, default=40, help="sentences per batch (default 40)")
    args = ap.parse_args()

    if not args.input.is_file():
        print(f"File not found: {args.input}", file=sys.stderr)
        return 2
    from pdfparse.inputs import parse_input  # noqa: E402
    from pdfparse.models import Reference  # noqa: E402
    from pdfparse.references import extract_citations  # noqa: E402

    doc = parse_input(args.input)

    if args.references:
        # Use the structured result of paper-reference-extraction: its ids and titles win, and the in-text
        # citations are re-matched against that list.
        rows = load_json(args.references)["references"]
        doc.references = [
            Reference(id=r["id"], raw=r.get("raw", ""), label=r.get("label", ""), title=r.get("title", ""),
                      authors=r.get("authors", []), year=r.get("year"), venue=r.get("venue", ""), doi=r.get("doi", ""),
                      arxiv=r.get("arxiv", ""), url=r.get("url", ""), kind=r.get("kind", ""))
            for r in rows
        ]
        doc.citations, doc.citation_style = extract_citations(doc.paragraphs, doc.references, doc.lang)
        title_src = {r["id"]: r.get("title_source", "") for r in rows}
    else:
        title_src = {}
    refs_table = {
        r.id: {"title": r.title or _ref_title_guess(r.raw), "title_guess": not r.title or title_src.get(r.id) == "fallback",
               "authors": r.authors, "year": r.year, "venue": r.venue, "doi": r.doi, "arxiv": r.arxiv, "url": r.url,
               "raw": r.raw[:400]}
        for r in doc.references
    }

    data = build(doc, refs_table)
    if not args.references and doc.references:
        data["warnings"].append("No --references given: reference titles are rule-based guesses and evidence retrieval "
                                "will be weaker (run paper-reference-extraction first)")
    if not data["sentences"]:
        print("No classifiable sentences were parsed (scanned PDF?)", file=sys.stderr)
        return 1
    dump_json(data, args.output)

    batch_dir = args.batch_dir or args.output.parent / "stage1"
    batch_dir.mkdir(parents=True, exist_ok=True)
    for old in batch_dir.glob("batch_*.txt"):
        old.unlink()
    batches = render_stage1(data, args.batch_size)
    for name, text in batches:
        (batch_dir / name).write_text(text, encoding="utf-8")

    st = data["stats"]
    print(f"Paper: {doc.title or args.input.name} ({doc.pages} pages, {doc.lang}, citation style {data['citation_style']})")
    print(f"Sentences {st['sentences']} (citing {st['citing_sentences']}, skipped as too short {st['skipped_short']}) | "
          f"sections {st['sections']} | references {st['references']}")
    print(f"Rule prior: context {st['by_rule']['context']} | citation {st['by_rule']['citation']} | opinion {st['by_rule']['opinion']}")
    for w in data["warnings"]:
        print(f"WARNING: {w}")
    print(f"Wrote {args.output}; {len(batches)} stage-1 batches -> {batch_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
