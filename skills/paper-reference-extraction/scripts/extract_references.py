#!/usr/bin/env python
"""Step 1: paper -> raw reference entries (rule-based extraction).

Input:  PDF / .docx / .txt / .md
Output: JSON with the split reference entries (raw text + DOI / arXiv / URL / year found by rules), where each
        reference is cited in the body, the citation style, and warnings (reference section not found,
        listed-but-uncited entries, dangling markers, ...).

Title / authors / venue / kind are filled in by the agent from `raw` (see SKILL.md) and then validated and merged
by finalize_references.py.

Usage:
    python extract_references.py paper.pdf -o work/references.raw.json
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import dump_json, setup_io  # noqa: E402

_NUM_CITE = re.compile(r"[\[［]\s*(\d{1,3}(?:\s*[,，;；\-–—~]\s*\d{1,3})*)\s*[\]］]")


def _numbers(spec: str) -> list[int]:
    nums: list[int] = []
    for part in re.split(r"[,，;；]", spec):
        rng = re.split(r"\s*[\-–—~]\s*", part.strip())
        try:
            if len(rng) == 2 and 0 < int(rng[0]) <= int(rng[1]) <= int(rng[0]) + 60:
                nums.extend(range(int(rng[0]), int(rng[1]) + 1))
            elif len(rng) == 1 and rng[0]:
                nums.append(int(rng[0]))
        except ValueError:
            continue
    return nums


def dangling_numeric_markers(paragraphs, ref_ids: set[int]) -> list[int]:
    """Numeric markers that appear in the body but have no entry in the reference list."""
    if not ref_ids:
        return []
    top = max(ref_ids)
    bad: set[int] = set()
    for p in paragraphs:
        if p.kind not in ("body", "abstract", "caption"):
            continue
        for m in _NUM_CITE.finditer(p.text):
            for n in _numbers(m.group(1)):
                if n not in ref_ids and n <= top + 30:
                    bad.add(n)
    return sorted(bad)


_JOINERS = ":=_-"  # a link ending in one of these was almost certainly broken by a line wrap ("/" is ambiguous)
_PATHLIKE = re.compile(r"^[\w.%~\-/]*[\d._\-/][\w.%~\-/]*$")
_URL_AT = re.compile(r"https?://\S+")
_DOI_AT = re.compile(r"(?<![\w.])(?:doi:?\s*|https?://(?:dx\.)?doi\.org/)?(10\.\d{4,9}/\S+)", re.I)


def _extend(raw: str, start: int, end: int) -> tuple[str, int]:
    """A link broken at a line end looks like "<link ending in a joiner> + space + <rest>": glue the rest back."""
    link = raw[start:end]
    while link and (link[-1] in _JOINERS or link[-1] == "/"):
        m = re.match(r"\s+(\S+)", raw[end:])
        if not m or (link[-1] == "/" and not _PATHLIKE.match(m.group(1))):  # "…/ Accessed 2024" is not a continuation
            break
        link += m.group(1)
        end += m.end()
    return link, end


def repair_links(d: dict) -> list[str]:
    """Repair URLs / DOIs broken by line wraps (only the `url` / `doi` fields change; `raw` stays as parsed)."""
    raw, hints = d["raw"], []
    m = _URL_AT.search(raw)
    if m:
        link, end = _extend(raw, m.start(), m.end())
        link = link.rstrip(".,;)]}")
        if link.startswith(d.get("url") or link):
            d["url"] = link
        if link[-1:] in _JOINERS and not raw[end:].strip():
            hints.append("link_may_be_truncated")
    m = _DOI_AT.search(raw)
    if m:
        link, end = _extend(raw, m.start(1), m.end(1))
        link = link.rstrip(".,;)]}")
        if link.startswith(d.get("doi") or link):
            d["doi"] = link
        if link[-1:] in _JOINERS and not raw[end:].strip():
            hints.append("link_may_be_truncated")
    return hints


def build_output(doc, input_path: Path, samples: int) -> dict:
    cited: dict[int, list[dict]] = {}
    for c in doc.citations:
        for rid in c.ref_ids:
            cited.setdefault(rid, []).append(
                {"citation_id": c.id, "section": c.section, "page": c.page, "sentence": c.sentence}
            )

    has_body = bool(doc.paragraphs)
    refs = []
    for r in doc.references:
        d = asdict(r)
        hits = cited.get(r.id, [])
        d["cite_count"] = len(hits)
        d["cited_in"] = hits[:samples]
        d["hints"] = repair_links(d)
        refs.append(d)

    warnings = list(doc.warnings)
    uncited = [r["id"] for r in refs if has_body and doc.citations and r["cite_count"] == 0]
    dangling = dangling_numeric_markers(doc.paragraphs, {r.id for r in doc.references}) if has_body else []
    if doc.citation_style == "author-year":
        warnings.append("Author-year style: body citations are matched to the list by surname + year, "
                        "so cite_count / uncited are best-effort")
    if has_body and doc.references and not doc.citations:
        warnings.append("No in-text citation markers were matched; cite_count = 0 everywhere does not mean "
                        "the references are uncited")
    if not doc.references and doc.references_text:
        warnings.append("The reference section was located but could not be split by rules: read "
                        "references_text and split it by hand before structuring")

    out = {
        "source": {
            "file": str(input_path),
            "type": doc.source,
            "pages": doc.pages,
            "title": doc.title,
            "lang": doc.lang,
        },
        "citation_style": doc.citation_style,
        "stats": {
            "references": len(refs),
            "citing_sentences": len(doc.citations),
            "uncited_ref_ids": uncited,
            "dangling_markers": dangling,
            "with_doi": sum(1 for r in refs if r["doi"]),
            "with_arxiv": sum(1 for r in refs if r["arxiv"]),
            "with_url": sum(1 for r in refs if r["url"]),
            "with_year": sum(1 for r in refs if r["year"]),
        },
        "warnings": warnings,
        "references": refs,
    }
    if not refs or doc.warnings:
        out["references_text"] = doc.references_text[:30000]
    return out


def main() -> int:
    setup_io()
    ap = argparse.ArgumentParser(description="Paper -> raw reference entries (rule-based extraction)")
    ap.add_argument("input", type=Path, help="paper file: .pdf / .docx / .txt / .md")
    ap.add_argument("-o", "--output", type=Path, help="output JSON path (default ./<name>.references.raw.json)")
    ap.add_argument("--samples", type=int, default=3, help="max citing sentences kept per reference (default 3)")
    args = ap.parse_args()

    if not args.input.is_file():
        print(f"File not found: {args.input}", file=sys.stderr)
        return 2
    from pdfparse.inputs import SUPPORTED, parse_input  # noqa: E402

    if args.input.suffix.lower() not in SUPPORTED:
        print(f"Unsupported file type {args.input.suffix}; supported: {', '.join(SUPPORTED)}", file=sys.stderr)
        return 2

    doc = parse_input(args.input)
    out = build_output(doc, args.input.resolve(), args.samples)
    target = args.output or Path.cwd() / f"{args.input.stem}.references.raw.json"
    dump_json(out, target)

    st = out["stats"]
    print(f"Paper: {doc.title or args.input.name} ({doc.pages} pages, {doc.lang}, citation style {doc.citation_style})")
    print(f"References: {st['references']} | DOI {st['with_doi']} | arXiv {st['with_arxiv']} | "
          f"URL {st['with_url']} | year {st['with_year']}")
    print(f"Citing sentences: {st['citing_sentences']} | listed but uncited: {st['uncited_ref_ids'] or 'none'} | "
          f"dangling markers: {st['dangling_markers'] or 'none'}")
    for w in out["warnings"]:
        print(f"WARNING: {w}")
    for r in out["references"][:3]:
        print(f"  [{r['id']}] {r['raw'][:110]}")
    print(f"Wrote {target}")
    return 0 if out["references"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
