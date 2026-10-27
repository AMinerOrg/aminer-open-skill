#!/usr/bin/env python
"""(Optional) Step 3: build evidence for the opinion sentences by looking up the cited references online.

For every reference used by an opinion sentence, find its abstract through free scholarly APIs
(arXiv by id -> OpenAlex title search -> Semantic Scholar title match) and write evidence.json.
No API key is needed. Only a candidate whose title matches the reference (similarity >= 0.9, and year / first author
not contradicting it) is accepted; otherwise the reference is marked matched=false. The script never substitutes
"the closest other paper" as evidence.

You can also skip this script and write evidence.json yourself in the same format, e.g. when you have the full text
of the cited papers:
    {"4": {"title": "...", "abstract": "...", "passages": ["paragraph from the full text", "..."], "source": "pdf", "matched": true}}

Usage:
    python fetch_evidence.py work/sentences.json --stage1 work/labels -o work/evidence.json

Environment (all optional): SCHOLAR_MAILTO (polite pool for OpenAlex), SEMANTIC_SCHOLAR_API_KEY (higher rate limit).
Requires network access; honors HTTPS_PROXY.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import dump_json, load_json, setup_io  # noqa: E402
from insight_lib import load_stage1  # noqa: E402

UA = "paper-insight-classification/0.1 (aminer-open-skill)"
TITLE_SIM = 0.9


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", re.sub(r"[^\w一-鿿]+", " ", s)).strip()


def title_sim(a: str, b: str) -> float:
    a, b = norm(a), norm(b)
    return difflib.SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def http_get(url: str, params: dict | None = None, headers: dict | None = None, timeout: float = 20, retries: int = 2):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code in (429, 500, 502, 503) and attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            return None
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt < retries:
                time.sleep(1 + attempt)
                continue
            return None
    return None


def _accept(ref: dict, cand: dict) -> bool:
    """Candidate must match the reference title and must not contradict year / first author."""
    if title_sim(ref.get("title", ""), cand.get("title", "")) < TITLE_SIM:
        return False
    y, cy = ref.get("year"), cand.get("year")
    if y and cy and abs(int(y) - int(cy)) > 2:
        return False
    authors = ref.get("authors") or []
    if authors and cand.get("authors"):  # first author: any name part (>= 2 chars) shared with some candidate author
        ref_tokens = {t for t in norm(authors[0]).split() if len(t) >= 2}
        cand_tokens = {t for a in cand["authors"] for t in norm(a).split()}
        if ref_tokens and not (ref_tokens & cand_tokens):
            return False
    return True


# ----------------------------------------------------------------------------- sources
def from_arxiv(ref: dict) -> dict | None:
    if not ref.get("arxiv"):
        return None
    txt = http_get("http://export.arxiv.org/api/query", {"id_list": re.sub(r"v\d+$", "", ref["arxiv"]), "max_results": 1})
    if not txt:
        return None
    try:
        entry = ET.fromstring(txt).find("{http://www.w3.org/2005/Atom}entry")
    except ET.ParseError:
        return None
    if entry is None:
        return None
    ns = "{http://www.w3.org/2005/Atom}"
    title = " ".join((entry.findtext(ns + "title") or "").split())
    if not title or title.lower() == "error":
        return None
    cand = {"title": title, "abstract": " ".join((entry.findtext(ns + "summary") or "").split()),
            "year": int((entry.findtext(ns + "published") or "0")[:4] or 0) or None, "venue": "arXiv",
            "authors": [a.findtext(ns + "name") or "" for a in entry.findall(ns + "author")], "source": "arxiv"}
    # an explicit arXiv id is strong evidence: only a loose title check is needed (a guessed reference title may carry
    # extra junk such as "arXiv:2408.06292 [cs.AI]", so containment also counts)
    ref_title = ref.get("title", "")
    loose = not ref_title or title_sim(ref_title, title) >= 0.8 or norm(title) in norm(ref_title)
    return cand if loose else None


def _oa_abstract(inv: dict | None) -> str:
    if not inv:
        return ""
    pos = sorted((i, w) for w, idxs in inv.items() for i in idxs)
    return " ".join(w for _, w in pos)


def from_openalex(ref: dict) -> dict | None:
    if not ref.get("title"):
        return None
    params = {"search": ref["title"][:300], "per-page": 5,
              "select": "title,publication_year,abstract_inverted_index,authorships,primary_location"}
    if os.environ.get("SCHOLAR_MAILTO"):
        params["mailto"] = os.environ["SCHOLAR_MAILTO"]
    txt = http_get("https://api.openalex.org/works", params)
    if not txt:
        return None
    try:
        results = json.loads(txt).get("results", [])
    except json.JSONDecodeError:
        return None
    for w in results:
        cand = {"title": w.get("title") or "", "abstract": _oa_abstract(w.get("abstract_inverted_index")),
                "year": w.get("publication_year"),
                "venue": ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or "",
                "authors": [(a.get("author") or {}).get("display_name", "") for a in w.get("authorships", [])],
                "source": "openalex"}
        if _accept(ref, cand):
            return cand
    return None


def from_s2(ref: dict) -> dict | None:
    if not ref.get("title"):
        return None
    headers = {"x-api-key": os.environ["SEMANTIC_SCHOLAR_API_KEY"]} if os.environ.get("SEMANTIC_SCHOLAR_API_KEY") else {}
    txt = http_get("https://api.semanticscholar.org/graph/v1/paper/search/match",
                   {"query": ref["title"][:300], "fields": "title,abstract,year,venue,authors"}, headers)
    if not txt:
        return None
    try:
        data = json.loads(txt).get("data") or []
    except json.JSONDecodeError:
        return None
    for p in data:
        cand = {"title": p.get("title") or "", "abstract": p.get("abstract") or "", "year": p.get("year"),
                "venue": p.get("venue") or "", "authors": [a.get("name", "") for a in p.get("authors", [])],
                "source": "semanticscholar"}
        if _accept(ref, cand):
            return cand
    return None


def lookup(ref: dict) -> dict:
    best = None
    for source in (from_arxiv, from_openalex, from_s2):
        try:
            cand = source(ref)
        except Exception:  # noqa: BLE001  one failing source must not sink the lookup
            cand = None
        if cand and (best is None):
            best = cand
        if cand and cand["abstract"]:
            best = cand
            break
    if best is None:
        return {"matched": False}
    out = {k: best[k] for k in ("title", "abstract", "year", "venue", "source")}
    out["matched"] = True
    if not best["abstract"]:
        out["note"] = "matched a record but it has no abstract"
    return out


# ----------------------------------------------------------------------------- driver
def target_ref_ids(data: dict, opinion_ids: set[int] | None, cap: int) -> list[int]:
    """References used by the opinion sentences (default: all citing sentences): own citations + the paragraph's citations
    for opinion sentences that carry no marker themselves."""
    para_refs = data.get("paragraph_refs", {})
    ids: dict[int, int] = {}
    for s in data["sentences"]:
        if opinion_ids is not None and s["id"] not in opinion_ids:
            continue
        for rid in (s["ref_ids"] or para_refs.get(str(s["paragraph_id"]), [])):
            ids[rid] = ids.get(rid, 0) + 1
    return [rid for rid, _ in sorted(ids.items(), key=lambda kv: (-kv[1], kv[0]))][:cap]


def main() -> int:
    setup_io()
    ap = argparse.ArgumentParser(description="Fetch titles + abstracts of the references cited by opinion sentences")
    ap.add_argument("sentences", type=Path)
    ap.add_argument("--stage1", type=Path, nargs="*", default=[],
                    help="stage-1 labels; when given, only references used by opinion sentences are fetched")
    ap.add_argument("-o", "--output", type=Path, default=Path("evidence.json"))
    ap.add_argument("--max-refs", type=int, default=80)
    ap.add_argument("--concurrency", type=int, default=3)
    args = ap.parse_args()

    data = load_json(args.sentences)
    opinion = None
    if args.stage1:
        labels, _covered, _ = load_stage1(args.stage1)
        opinion = {s["id"] for s in data["sentences"] if labels.get(s["id"], s["rule"]["type"]) == "opinion"}
    rids = target_ref_ids(data, opinion, args.max_refs)
    if not rids:
        print("No references to look up (no opinion sentence has a citation)")
        dump_json({}, args.output)
        return 0

    print(f"Looking up {len(rids)} cited references ...")
    refs = {rid: data["refs"].get(str(rid), {}) for rid in rids}
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        results = list(pool.map(lambda rid: lookup(refs[rid]), rids))
    evidence = dict(sorted(((str(rid), res) for rid, res in zip(rids, results)), key=lambda kv: int(kv[0])))
    dump_json(evidence, args.output)

    ok = sum(1 for v in evidence.values() if v.get("abstract"))
    no_abs = sum(1 for v in evidence.values() if v.get("matched") and not v.get("abstract"))
    miss = [k for k, v in evidence.items() if not v.get("matched")]
    print(f"With abstract {ok} | matched without abstract {no_abs} | not matched {len(miss)}"
          + (f" (ids {miss[:15]})" if miss else ""))
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
