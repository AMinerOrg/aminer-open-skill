#!/usr/bin/env python
"""Step 2: merge the agent's structured fields back into the raw entries, check every field against the
original text, and export JSON / BibTeX / Markdown.

Core rule: every structured field must be grounded in the entry's own `raw` text. A DOI / year / author / venue that
the raw text does not contain is dropped -- an LLM "helpfully completing" a DOI is itself a hallucination.

Usage:
    python finalize_references.py work/references.raw.json --enriched work/enriched.json --outdir work/out
    # --enriched may be repeated, or point to a directory (all *.json inside are merged)
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import dump_json, load_json, setup_io  # noqa: E402

KINDS = ("journal", "conference", "preprint", "book", "thesis", "report", "web", "software", "dataset", "other")
_CJK = re.compile(r"[一-鿿㐀-䶿]")
_DOI = re.compile(r"^10\.\d{4,9}/\S+$")
_ARXIV = re.compile(r"^(?:\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?$")


# ----------------------------------------------------------------------------- normalization
def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^\w一-鿿]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def compact(s: str) -> str:
    return re.sub(r"\s+", "", fold(s))


def raw_compact(s: str) -> str:
    """Whitespace-free form that keeps punctuation (for DOI / URL / page comparisons)."""
    s = (s or "").replace("–", "-").replace("—", "-").replace("‑", "-")
    return re.sub(r"\s+", "", s).lower()


def coverage(needle: str, hay_tokens: set[str]) -> float:
    toks = [t for t in fold(needle).split() if t]
    return sum(t in hay_tokens for t in toks) / len(toks) if toks else 0.0


# ----------------------------------------------------------------------------- grounding checks
def _title_ok(title: str, raw: str) -> bool:
    nt = fold(title)
    if len(nt) < 4:
        return False
    nr = fold(raw)
    return nt in nr or compact(title) in compact(raw) or (
        len(nt.split()) >= 3 and coverage(title, set(nr.split())) >= 0.9
    )


def _author_ok(name: str, raw: str, raw_tokens: set[str]) -> bool:
    name = name.strip()
    if not name or re.search(r"\bet\.?\s*al\b|^等$", name, re.I):
        return False
    if _CJK.search(name):
        return compact(name) in compact(raw)
    toks = [t for t in fold(name).split() if len(t) >= 2]
    if not toks:
        return False
    key = max(toks, key=len)  # the surname, or the longest name fragment
    return key in raw_tokens or key in compact(raw)


def apply_grounded(base: dict, item: dict) -> tuple[dict, list[str]]:
    """Copy of `base` updated with the fields of `item` that are grounded in base['raw']; returns (entry, dropped field names)."""
    out = dict(base)
    raw = base.get("raw", "")
    rtoks = set(fold(raw).split())
    rcmp = raw_compact(raw)
    dropped: list[str] = []

    def drop(name: str) -> None:
        if item.get(name) not in (None, "", [], "null"):
            dropped.append(name)

    title = str(item.get("title") or "").strip().strip("“”\"'")[:400]
    if title:
        if _title_ok(title, raw):
            out["title"] = title
            out["title_source"] = "agent"
        else:
            drop("title")

    authors = []
    for a in item.get("authors") or []:
        a = str(a).strip()
        if _author_ok(a, raw, rtoks):
            authors.append(a)
    if authors:
        out["authors"] = authors[:50]
        n_claimed = len([a for a in item.get("authors") or [] if str(a).strip()])
        if n_claimed > len(authors):
            dropped.append(f"authors×{n_claimed - len(authors)}")
    elif item.get("authors"):
        dropped.append("authors")
    out["authors_truncated"] = bool(re.search(r"\bet\.?\s*al\b|等", raw, re.I))

    if item.get("year") not in (None, "", "null"):
        try:
            y = int(item["year"])
            if 1900 <= y <= 2100 and str(y) in raw:
                out["year"] = y
            else:
                dropped.append("year")
        except (TypeError, ValueError):
            dropped.append("year")

    venue = str(item.get("venue") or "").strip()[:250]
    if venue:
        nv = fold(venue)
        if nv in fold(raw) or compact(venue) in compact(raw) or coverage(venue, rtoks) >= 0.8:
            out["venue"] = venue
        else:
            dropped.append("venue")

    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", str(item.get("doi") or "").strip(), flags=re.I).rstrip(".,;")
    if doi:
        if _DOI.match(doi) and doi.lower() in rcmp:
            out["doi"] = doi
        else:
            dropped.append("doi")

    arx = re.sub(r"^arxiv:\s*", "", str(item.get("arxiv") or "").strip(), flags=re.I)
    if arx:
        if _ARXIV.match(arx) and arx.lower() in rcmp:
            out["arxiv"] = arx
        else:
            dropped.append("arxiv")

    url = str(item.get("url") or "").strip().rstrip(".,;")
    if url:
        if url.lower().startswith("http") and raw_compact(url) in rcmp:
            out["url"] = url[:400]
        else:
            dropped.append("url")

    for name in ("volume", "issue", "pages", "publisher"):
        val = str(item.get(name) or "").strip()
        if val:
            if raw_compact(val) in rcmp or compact(val) in compact(raw):
                out[name] = val
            else:
                dropped.append(name)

    kind = str(item.get("kind") or "").strip().lower()
    if kind:
        out["kind"] = kind if kind in KINDS else "other"
    return out, dropped


# ----------------------------------------------------------------------------- fallbacks and quality
_YEAR_ONLY = re.compile(r"^\(?(?:19|20)\d{2}[a-z]?\)?\.?$")


def fallback_title(raw: str) -> str:
    """Placeholder guess used when the agent gave no (grounded) title; flagged as title_fallback."""
    raw = re.sub(r"https?://\S+|\bdoi:?\s*10\.\S+", " ", raw, flags=re.I).strip()
    m = re.search(r"[“\"](.{10,300}?)[”\"]", raw)
    if m:
        return m.group(1).strip(" ,.")
    m = re.search(r"(?:^|[.．]\s*)([^.．\[\]]{6,300}?)\s*\[(?:J|C|M|D|R|EB/OL|DB/OL|OL)\]", raw)  # GB/T 7714
    if m:
        return m.group(1).strip(" ,.")
    parts = [p.strip(" .") for p in re.split(r"(?<=[a-z0-9\)])\.\s+(?=[A-Z0-9“\"])", raw) if p.strip(" .")]
    cand = [p for p in parts[1:] if not _YEAR_ONLY.match(p) and len(p) >= 8]  # part 0 = authors: "Authors. Year. Title. Venue."
    if cand:
        return cand[0][:300]
    zh = re.split(r"[.．。]", raw)
    return (zh[1] if len(zh) > 1 else raw).strip()[:300]


def infer_kind(ref: dict) -> str:
    raw = ref.get("raw", "")
    gbt = re.search(r"\[(J|C|M|D|R|EB/OL|DB/OL|OL|A|N|S|P)\]", raw)
    if gbt:
        return {"J": "journal", "C": "conference", "M": "book", "D": "thesis", "R": "report",
                "EB/OL": "web", "DB/OL": "web", "OL": "web"}.get(gbt.group(1), "other")
    if ref.get("arxiv") or re.search(r"arxiv", raw, re.I):
        return "preprint"
    if re.search(r"\bIn:\s|\bIn\s+(?:Proceedings|Proc\.|Findings|the\s+\d)|\b(?:workshop|symposium)\b", raw) \
            or re.search(r"\b(?:proceedings of the .{0,60}conference|international conference|annual meeting)\b", raw, re.I):
        return "conference"
    if re.search(r"\bph\.?d\.? thesis|dissertation|master'?s thesis", raw, re.I):
        return "thesis"
    if ref.get("url") and not ref.get("doi"):
        return "web"
    return ""


def assess(ref: dict) -> None:
    issues = ref.setdefault("issues", [])
    if not ref.get("title"):
        issues.append("no_title")
    if not ref.get("authors"):
        issues.append("no_authors")
    if not ref.get("year"):
        issues.append("no_year")
    has_locator = bool(ref.get("venue") or ref.get("doi") or ref.get("arxiv") or ref.get("url"))
    if not has_locator:
        issues.append("no_venue_or_locator")
    if ref.get("title_source") == "fallback":
        issues.append("title_fallback")
    if ref.get("title") and ref.get("authors") and ref.get("year") and has_locator and ref.get("title_source") != "fallback":
        ref["quality"] = "complete"
    elif ref.get("title") and (ref.get("authors") or ref.get("year")):
        ref["quality"] = "partial"
    else:
        ref["quality"] = "poor"


def mark_duplicates(refs: list[dict]) -> None:
    seen: dict[str, int] = {}
    for r in refs:
        keys = []
        if r.get("doi"):
            keys.append("doi:" + r["doi"].lower())
        if r.get("arxiv"):
            keys.append("arxiv:" + re.sub(r"v\d+$", "", r["arxiv"].lower()))
        if r.get("title") and len(fold(r["title"])) >= 20:
            keys.append("t:" + fold(r["title"]))
        dup = next((seen[k] for k in keys if k in seen), None)
        if dup is not None:
            r["issues"].append(f"duplicate_of:{dup}")
        for k in keys:
            seen.setdefault(k, r["id"])


# ----------------------------------------------------------------------------- merge
def load_enriched(paths: list[Path]) -> dict[int, dict]:
    files: list[Path] = []
    for p in paths:
        files.extend(sorted(p.glob("*.json")) if p.is_dir() else [p])
    merged: dict[int, dict] = {}
    for f in files:
        data = load_json(f)
        if isinstance(data, dict):
            data = data.get("references") or data.get("items") or [dict(v, id=k) for k, v in data.items() if isinstance(v, dict)]
        for it in data:
            if not isinstance(it, dict):
                continue
            try:
                rid = int(it.get("id"))
            except (TypeError, ValueError):
                continue
            merged.setdefault(rid, {}).update({k: v for k, v in it.items() if v not in (None, "")})
    return merged


def finalize(raw_doc: dict, enriched: dict[int, dict]) -> dict:
    refs_out: list[dict] = []
    unknown_ids = sorted(set(enriched) - {r["id"] for r in raw_doc["references"]})
    uncited = set(raw_doc["stats"].get("uncited_ref_ids", []))
    for base in raw_doc["references"]:
        ref = {k: base.get(k, v) for k, v in
               (("id", None), ("label", ""), ("title", ""), ("authors", []), ("year", None), ("venue", ""),
                ("doi", ""), ("arxiv", ""), ("url", ""), ("kind", ""), ("raw", ""))}
        for extra in ("volume", "issue", "pages", "publisher"):
            if base.get(extra):
                ref[extra] = base[extra]
        ref["title_source"] = "source" if ref["title"] else ""
        ref["cite_count"] = base.get("cite_count", 0)
        ref["cited_in"] = base.get("cited_in", [])
        ref["issues"] = list(base.get("hints", []))
        item = enriched.get(base["id"])
        if item:
            ref, dropped = apply_grounded(ref, item)
            ref["enriched"] = True
            if dropped:
                ref["issues"].append("fields_dropped:" + ",".join(dropped))
        else:
            ref["enriched"] = bool(ref["title"])
        if not ref["title"]:
            ref["title"] = fallback_title(ref["raw"])
            ref["title_source"] = "fallback"
        if not ref["kind"]:
            ref["kind"] = infer_kind(ref) or ""
        if base["id"] in uncited:
            ref["issues"].append("uncited")
        assess(ref)
        refs_out.append(ref)
    mark_duplicates(refs_out)

    quality: dict[str, int] = {"complete": 0, "partial": 0, "poor": 0}
    for r in refs_out:
        quality[r["quality"]] += 1
    stats = dict(raw_doc["stats"])
    stats.update({
        "quality": quality,
        "agent_enriched": sum(1 for r in refs_out if r.get("enriched")),
        "needs_review": [r["id"] for r in refs_out if r["quality"] != "complete"],
        "duplicates": [r["id"] for r in refs_out if any(i.startswith("duplicate_of") for i in r["issues"])],
        "unknown_enriched_ids": unknown_ids,
    })
    return {
        "source": raw_doc["source"],
        "citation_style": raw_doc["citation_style"],
        "stats": stats,
        "warnings": raw_doc.get("warnings", []),
        "references": refs_out,
    }


# ----------------------------------------------------------------------------- export
_BIB_ESC = {"&": r"\&", "%": r"\%", "#": r"\#", "_": r"\_"}


def _esc(s: str) -> str:
    return "".join(_BIB_ESC.get(c, c) for c in s)


def _ascii(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in s if not unicodedata.combining(c)).lower())


def _surname(name: str) -> str:
    name = name.strip()
    if _CJK.search(name):
        return name[:1] if len(name) <= 4 else name[:2]
    if "," in name:
        return name.split(",")[0]
    parts = name.split()
    # GB/T 7714 style "Vaswani A": a trailing initial means the surname comes first
    if len(parts) >= 2 and re.fullmatch(r"[A-Z]{1,3}", parts[-1]):
        return parts[0]
    return parts[-1] if parts else ""


def bib_key(ref: dict, used: set[str]) -> str:
    first = _ascii(_surname(ref["authors"][0])) if ref.get("authors") else "anon"
    stop = {"a", "an", "the", "on", "of", "for", "and", "in", "to", "with", "towards", "toward"}
    word = next((w for w in re.findall(r"[a-z0-9]+", fold(ref.get("title", ""))) if w not in stop), "")
    base = f"{first or 'anon'}{ref.get('year') or ''}{word}"
    key, n = base, 0
    while key in used:
        n += 1
        key = base + chr(ord("a") + (n - 1) % 26) + (str(n // 26) if n >= 26 else "")
    used.add(key)
    return key


def to_bibtex(refs: list[dict]) -> str:
    used: set[str] = set()
    chunks = []
    for r in refs:
        kind = r.get("kind") or "other"
        etype = {"journal": "article", "conference": "inproceedings", "book": "book", "thesis": "phdthesis",
                 "report": "techreport"}.get(kind, "misc")
        fields: list[tuple[str, str]] = []
        if r.get("authors"):
            fields.append(("author", " and ".join(r["authors"]) + (" and others" if r.get("authors_truncated") else "")))
        fields.append(("title", r.get("title", "")))
        venue = r.get("venue", "")
        if venue:
            fields.append({"article": ("journal", venue), "inproceedings": ("booktitle", venue)}.get(etype, ("howpublished", venue)))
        if r.get("year"):
            fields.append(("year", str(r["year"])))
        for name in ("volume", "pages", "publisher"):
            if r.get(name):
                fields.append((name, r[name].replace("-", "--") if name == "pages" and "--" not in r[name] else r[name]))
        if r.get("issue"):
            fields.append(("number", r["issue"]))
        if r.get("doi"):
            fields.append(("doi", r["doi"]))
        if r.get("arxiv"):
            fields.append(("eprint", r["arxiv"]))
            fields.append(("archivePrefix", "arXiv"))
        if r.get("url"):
            fields.append(("url", r["url"]))
        fields.append(("note", f"ref id {r['id']}" + ("; needs manual review" if r["quality"] != "complete" else "")))
        body = ",\n".join(f"  {k} = {{{v if k in ('url', 'doi', 'eprint') else _esc(v)}}}" for k, v in fields)
        chunks.append(f"@{etype}{{{bib_key(r, used)},\n{body}\n}}")
    return "\n\n".join(chunks) + "\n"


MD = {
    "en": {
        "title": "# Structured references: {name}",
        "source": "- Source: `{file}` ({type}, {pages} pages, citation style {style})",
        "counts": "- {n} references | complete {c} | partial {p} | poor {q} | with DOI {doi} | with arXiv {arx}",
        "cites": "- Citing sentences {cs} | listed but uncited {unc} | dangling markers {dang} | duplicates {dup}",
        "none": "none",
        "cols": ["#", "Authors", "Year", "Title", "Venue", "Identifier", "Kind", "Cited", "Quality"],
        "et_al": " et al.",
        "review": "## Entries that need attention",
    },
    "zh": {
        "title": "# 参考文献结构化结果：{name}",
        "source": "- 来源：`{file}`（{type}，{pages} 页，引用制式 {style}）",
        "counts": "- 共 {n} 条｜完整 {c}｜部分 {p}｜较差 {q}｜含 DOI {doi}｜含 arXiv {arx}",
        "cites": "- 正文引用句 {cs}｜列而未引 {unc}｜悬空编号 {dang}｜重复 {dup}",
        "none": "无",
        "cols": ["#", "作者", "年份", "标题", "出处", "标识", "类型", "被引", "质量"],
        "et_al": " 等",
        "review": "## 需要人工留意的条目",
    },
}


def to_markdown(doc: dict, lang: str = "en") -> str:
    t = MD.get(lang, MD["en"])
    st, src = doc["stats"], doc["source"]
    refs = doc["references"]
    lines = [
        t["title"].format(name=src.get("title") or Path(src["file"]).name),
        "",
        t["source"].format(file=Path(src["file"]).name, type=src["type"], pages=src["pages"], style=doc["citation_style"]),
        t["counts"].format(n=st["references"], c=st["quality"]["complete"], p=st["quality"]["partial"], q=st["quality"]["poor"],
                           doi=sum(1 for r in refs if r["doi"]), arx=sum(1 for r in refs if r["arxiv"])),
        t["cites"].format(cs=st["citing_sentences"], unc=st["uncited_ref_ids"] or t["none"],
                          dang=st["dangling_markers"] or t["none"], dup=st["duplicates"] or t["none"]),
        "",
    ]
    for w in doc["warnings"]:
        lines.append(f"> WARNING: {w}")
    if doc["warnings"]:
        lines.append("")
    lines += ["| " + " | ".join(t["cols"]) + " |", "|" + "---|" * len(t["cols"])]

    def cell(s: str) -> str:
        return (s or "").replace("|", "\\|").replace("\n", " ")

    for r in refs:
        au = ", ".join(r["authors"][:3]) + (t["et_al"] if len(r["authors"]) > 3 or r.get("authors_truncated") else "")
        ident = r["doi"] and f"doi:{r['doi']}" or r["arxiv"] and f"arXiv:{r['arxiv']}" or r["url"] or ""
        lines.append(
            f"| {r['id']} | {cell(au)} | {r['year'] or ''} | {cell(r['title'])} | {cell(r['venue'])} | {cell(ident)} "
            f"| {r['kind']} | {r['cite_count']} | {r['quality']} |"
        )
    review = [r for r in refs if r["issues"]]
    if review:
        lines += ["", t["review"], ""]
        for r in review:
            lines.append(f"- [{r['id']}] {', '.join(r['issues'])} -- {cell(r['raw'][:140])}")
    return "\n".join(lines) + "\n"


def main() -> int:
    setup_io()
    ap = argparse.ArgumentParser(description="Merge the agent's structured fields, verify grounding, export")
    ap.add_argument("raw", type=Path, help="JSON written by extract_references.py")
    ap.add_argument("--enriched", type=Path, action="append", default=[],
                    help="structured JSON written by the agent (file or directory, repeatable)")
    ap.add_argument("--outdir", type=Path, default=Path("."), help="output directory (default: current directory)")
    ap.add_argument("--formats", default="json,bib,md", help="comma-separated: json,bib,md")
    ap.add_argument("--lang", choices=["auto", "en", "zh"], default="auto",
                    help="language of references.md (auto = the paper's language)")
    args = ap.parse_args()

    raw_doc = load_json(args.raw)
    enriched = load_enriched(args.enriched) if args.enriched else {}
    doc = finalize(raw_doc, enriched)

    args.outdir.mkdir(parents=True, exist_ok=True)
    fmts = {f.strip() for f in args.formats.split(",")}
    lang = doc["source"].get("lang", "en") if args.lang == "auto" else args.lang
    written = []
    if "json" in fmts:
        dump_json(doc, args.outdir / "references.json")
        written.append("references.json")
    if "bib" in fmts:
        (args.outdir / "references.bib").write_text(to_bibtex(doc["references"]), encoding="utf-8")
        written.append("references.bib")
    if "md" in fmts:
        (args.outdir / "references.md").write_text(to_markdown(doc, lang), encoding="utf-8")
        written.append("references.md")

    st = doc["stats"]
    q = st["quality"]
    print(f"{st['references']} references | complete {q['complete']} | partial {q['partial']} | poor {q['poor']} | "
          f"structured by agent {st['agent_enriched']}")
    for r in doc["references"]:
        for issue in r["issues"]:
            if issue.startswith("fields_dropped"):
                print(f"  [{r['id']}] not found in the raw text, dropped: {issue.split(':', 1)[1]}")
    if st["unknown_enriched_ids"]:
        print(f"  WARNING: enriched file has ids that are not in the reference list: {st['unknown_enriched_ids']}")
    if st["needs_review"]:
        print(f"  Needs attention (quality is not 'complete'): {st['needs_review']}")
    if st["duplicates"]:
        print(f"  Possible duplicates: {st['duplicates']}")
    print("Wrote " + ", ".join(str(args.outdir / w) for w in written))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
