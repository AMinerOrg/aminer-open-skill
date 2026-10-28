"""Offline tests: grounding checks, quality assessment, BibTeX export, and an end-to-end run on generated files.

Run: python -m pytest skills/paper-reference-extraction/tests -q
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))

import extract_references as ex  # noqa: E402
import finalize_references as fr  # noqa: E402

RAW1 = ("Lin Ai, Ziwei Gong, Harshsaiprasad Deshpande, Alexander Johnson, Emmy Phung, Ahmad Emami, and Julia "
        "Hirschberg. 2025. NovAScore: A New Automated Metric for Evaluating Document Level Novelty. In Proceedings "
        "of the 31st International Conference on Computational Linguistics. Association for Computational "
        "Linguistics, 3479–3494. https://aclanthology.org/2025.coling-main.234/")
RAW2 = ("Chris Lu, Cong Lu, Robert Tjarko Lange, Jakob Foerster, Jeff Clune, and David Ha. 2024. The AI Scientist: "
        "Towards Fully Automated Open-Ended Scientific Discovery. arXiv:2408.06292 [cs.AI] https://arxiv.org/abs/2408.06292")
RAW3 = "Vaswani A, Shazeer N, et al. Attention is all you need[C]. NeurIPS, 2017: 5998-6008."

PAPER_TXT = """Retrieval Notes

Abstract

We study how retrieval systems use evidence.

1 Introduction

Retrieval-augmented generation is widely used in question answering systems today [1].
Smith et al. [2] propose a reranker that improves recall on long documents considerably [1, 2].

References

[1] Alice Brown. Retrieval augmented generation for question answering. Journal of Retrieval, 2021. doi:10.1000/jr.2021.1
[2] John Smith, Wei Chen. Reranking long documents with sparse signals. Proceedings of IR Conference, 2022.
[3] Kim Lee. A benchmark for citation recommendation in science. Scientometrics Letters, 2020.
"""


def raw_doc(*raws: str, uncited=()) -> dict:
    refs = [{"id": i, "label": f"[{i}]", "raw": r, "doi": "", "arxiv": "", "url": "", "year": None,
             "cite_count": 0 if i in uncited else 2, "cited_in": []} for i, r in enumerate(raws, 1)]
    return {"source": {"file": "x.pdf", "type": "pdf", "pages": 1, "title": "T", "lang": "en"},
            "citation_style": "numeric",
            "stats": {"references": len(refs), "citing_sentences": 3, "uncited_ref_ids": list(uncited),
                      "dangling_markers": []},
            "warnings": [], "references": refs}


def test_grounded_fields_are_kept():
    base = raw_doc(RAW1)["references"][0]
    out, dropped = fr.apply_grounded(base, {
        "title": "NovAScore: A New Automated Metric for Evaluating Document Level Novelty",
        "authors": ["Lin Ai", "Ziwei Gong", "Julia Hirschberg"], "year": 2025,
        "venue": "Proceedings of the 31st International Conference on Computational Linguistics",
        "pages": "3479–3494", "url": "https://aclanthology.org/2025.coling-main.234/", "kind": "conference"})
    assert dropped == []
    assert out["authors"] == ["Lin Ai", "Ziwei Gong", "Julia Hirschberg"]
    assert out["year"] == 2025 and out["kind"] == "conference" and out["pages"] == "3479–3494"


def test_hallucinated_fields_are_dropped():
    base = raw_doc(RAW2)["references"][0]
    out, dropped = fr.apply_grounded(base, {
        "title": "The AI Scientist: Towards Fully Automated Open-Ended Scientific Discovery",
        "authors": ["Chris Lu", "Sakana Researcher", "David Ha"],   # the 2nd author is not in the raw text
        "year": 2023,                                               # the raw text says 2024
        "doi": "10.48550/arXiv.2408.06292",                         # no DOI in the raw text
        "venue": "Nature",                                          # not in the raw text
        "arxiv": "2408.06292", "kind": "preprint"})
    assert out["authors"] == ["Chris Lu", "David Ha"]
    assert out.get("year") != 2023 and not out.get("doi") and not out.get("venue")
    assert out["arxiv"] == "2408.06292"
    assert {"year", "doi", "venue"} <= set(dropped) and any(d.startswith("authors") for d in dropped)


def test_title_not_in_raw_is_dropped_and_falls_back():
    doc = fr.finalize(raw_doc(RAW3), {1: {"id": 1, "title": "Completely Different Paper Title Here"}})
    ref = doc["references"][0]
    assert ref["title_source"] == "fallback"
    assert "fields_dropped:title" in ref["issues"] and "title_fallback" in ref["issues"]
    assert ref["quality"] != "complete"


def test_quality_duplicates_and_uncited():
    doc = fr.finalize(
        raw_doc(RAW1, RAW1, RAW2, uncited=(3,)),
        {1: {"id": 1, "title": "NovAScore: A New Automated Metric for Evaluating Document Level Novelty",
             "authors": ["Lin Ai"], "year": 2025, "venue": "Association for Computational Linguistics"},
         2: {"id": 2, "title": "NovAScore: A New Automated Metric for Evaluating Document Level Novelty",
             "authors": ["Lin Ai"], "year": 2025, "venue": "Association for Computational Linguistics"}})
    refs = {r["id"]: r for r in doc["references"]}
    assert refs[1]["quality"] == "complete"
    assert "duplicate_of:1" in refs[2]["issues"]
    assert "uncited" in refs[3]["issues"] and doc["stats"]["duplicates"] == [2]
    assert doc["stats"]["quality"]["complete"] == 2


def test_gbt_kind_inference_and_bibtex():
    doc = fr.finalize(raw_doc(RAW3), {1: {"id": 1, "title": "Attention is all you need",
                                          "authors": ["Vaswani A", "Shazeer N"], "year": 2017, "venue": "NeurIPS"}})
    ref = doc["references"][0]
    assert ref["kind"] == "conference"
    bib = fr.to_bibtex(doc["references"])
    assert bib.startswith("@inproceedings{vaswani2017attention,")
    assert "booktitle = {NeurIPS}" in bib and "author = {Vaswani A and Shazeer N and others}" in bib


def test_bibtex_keys_are_unique_and_escaped():
    refs = [{"id": 1, "authors": ["A B"], "year": 2020, "title": "Cats & Dogs_100%", "kind": "journal", "venue": "J",
             "quality": "complete"},
            {"id": 2, "authors": ["A B"], "year": 2020, "title": "Cats & Dogs_100%", "kind": "other",
             "quality": "complete"}]
    bib = fr.to_bibtex(refs)
    assert "cats" in bib and bib.count("@") == 2
    assert r"Cats \& Dogs\_100\%" in bib
    keys = [line[line.index("{") + 1:-1] for line in bib.splitlines() if line.startswith("@")]
    assert len(set(keys)) == 2


def test_fallback_title_styles():
    acl = "Hiba Arnaout, Noy Sternlicht, and Iryna Gurevych. 2025. In-depth Research Impact Summarization through Citation Analysis. ArXiv abs/2505.14838 (2025). https://x.org/a"
    assert fr.fallback_title(acl) == "In-depth Research Impact Summarization through Citation Analysis"
    ieee = 'A. Vaswani, N. Shazeer, "Attention is all you need," in NeurIPS, 2017.'
    assert fr.fallback_title(ieee) == "Attention is all you need"
    gbt = "张三, 李四. 大语言模型在学术写作中的应用研究[J]. 计算机学报, 2023, 46(3): 1-15."
    assert fr.fallback_title(gbt) == "大语言模型在学术写作中的应用研究"


def test_repair_wrapped_links():
    d = {"raw": "A. B. 2025. T. https://api.semanticscholar.org/CorpusID: 278782245", "url": "https://api.semanticscholar.org/CorpusID:", "doi": ""}
    assert ex.repair_links(d) == []
    assert d["url"] == "https://api.semanticscholar.org/CorpusID:278782245"
    d = {"raw": "A. B. 2025. T. doi:10.1000/abc-", "url": "", "doi": "10.1000/abc"}
    assert ex.repair_links(d) == ["link_may_be_truncated"]


def run(*args) -> subprocess.CompletedProcess:
    r = subprocess.run([sys.executable, "-I", *map(str, args)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stdout + r.stderr
    return r


def test_end_to_end_txt(tmp_path):
    paper = tmp_path / "paper.txt"
    paper.write_text(PAPER_TXT, encoding="utf-8")
    raw = tmp_path / "raw.json"
    run(SKILL / "scripts" / "extract_references.py", paper, "-o", raw)
    data = fr.load_json(raw)
    assert data["stats"]["references"] == 3 and data["stats"]["uncited_ref_ids"] == [3]
    assert data["references"][0]["doi"] == "10.1000/jr.2021.1" and data["references"][0]["cite_count"] == 2

    enriched = tmp_path / "enriched.json"
    fr.dump_json([{"id": 1, "title": "Retrieval augmented generation for question answering", "authors": ["Alice Brown"],
                   "year": 2021, "venue": "Journal of Retrieval", "kind": "journal"}], enriched)
    out = tmp_path / "out"
    run(SKILL / "scripts" / "finalize_references.py", raw, "--enriched", enriched, "--outdir", out)
    final = fr.load_json(out / "references.json")
    assert final["references"][0]["quality"] == "complete" and final["stats"]["quality"]["complete"] == 1
    assert "@article{brown2021retrieval," in (out / "references.bib").read_text(encoding="utf-8")
    assert (out / "references.md").read_text(encoding="utf-8").startswith("# Structured references")


def test_end_to_end_pdf(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Retrieval Notes", fontsize=18, fontname="hebo")
    y = 130
    body = ["Retrieval-augmented generation is widely used in question answering systems today [1].",
            "Smith et al. [2] propose a reranker that improves recall on long documents considerably."]
    page.insert_text((72, y), "1 Introduction", fontsize=12, fontname="hebo")
    for line in body:
        y += 22
        page.insert_text((72, y), line, fontsize=10, fontname="helv")
    y += 40
    page.insert_text((72, y), "References", fontsize=12, fontname="hebo")
    for ref in ["[1] Alice Brown. Retrieval augmented generation for question answering. Journal of Retrieval, 2021.",
                "[2] John Smith, Wei Chen. Reranking long documents with sparse signals. IR Conference, 2022."]:
        y += 20
        page.insert_text((72, y), ref, fontsize=10, fontname="helv")
    pdf = tmp_path / "paper.pdf"
    doc.save(str(pdf))
    doc.close()

    raw = tmp_path / "raw.json"
    run(SKILL / "scripts" / "extract_references.py", pdf, "-o", raw)
    data = fr.load_json(raw)
    assert data["stats"]["references"] == 2
    assert data["references"][1]["raw"].startswith("John Smith")
