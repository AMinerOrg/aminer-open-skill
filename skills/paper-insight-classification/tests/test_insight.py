"""Offline tests: rule prior, label readers, scoring formulas, aggregation, evidence matching, and an end-to-end run
on a plain-text paper.

Run: python -m pytest skills/paper-insight-classification/tests -q
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))

import aggregate_insight as ag  # noqa: E402
import fetch_evidence as fe  # noqa: E402
import insight_lib as lib  # noqa: E402
import prepare_scoring as ps  # noqa: E402
import prepare_sentences as pre  # noqa: E402

PAPER = """Insight Study of Retrieval

Abstract

We study how retrieval systems use evidence.

1 Introduction

Retrieval-augmented generation is widely used in question answering systems today [1].
Smith et al. [2] propose a reranker that improves recall on long documents considerably.
However, these systems fail to explain why the retrieved passages matter for the final answer [1, 2].
We argue that the real bottleneck is evidence selection rather than model size, because small readers do well with good passages.
The experiments below use three public datasets with standard splits for evaluation.

2 Related Work

Lee [3] introduces a benchmark for citation recommendation across several domains of science.
Chen and Wu [2] compare sparse and dense retrievers on the same benchmark and report similar accuracy.
This suggests that the choice of retriever matters less than how the passages are filtered and combined.

References

[1] Alice Brown. Retrieval augmented generation for question answering. Journal of Retrieval, 2021.
[2] John Smith, Wei Chen. Reranking long documents with sparse signals. Proceedings of IR Conference, 2022.
[3] Kim Lee. A benchmark for citation recommendation in science. Scientometrics Letters, 2020.
"""


# ----------------------------------------------------------------------------- pure functions
def test_rule_prior():
    assert pre.rule_prior("However, this is not true.", False, "en")["type"] == "opinion"
    assert pre.rule_prior("Smith et al. propose a reranker [2].", True, "en")["type"] == "citation"
    assert pre.rule_prior("Retrieval is widely used in industry today.", False, "en")["type"] == "context"
    assert pre.rule_prior("然而，现有方法忽视了证据选择。", False, "zh")["type"] == "opinion"
    weak = pre.rule_prior("Because we find that it works, therefore it should be used.", False, "en")
    assert weak["type"] == "context" or weak["strength"] == "weak"  # fewer than 3 weak signals must not become an opinion


def test_stage1_formats_and_alias(tmp_path):
    (tmp_path / "stage1_001.json").write_text(json.dumps({"range": [1, 5], "opinion": [2], "引用句": [4]}), encoding="utf-8")
    (tmp_path / "stage1_002.json").write_text(json.dumps({"6": "viewpoint", "7": "bogus"}), encoding="utf-8")
    (tmp_path / "stage1_003.json").write_text(json.dumps([{"id": 8, "type": "citation"}]), encoding="utf-8")
    (tmp_path / "sections.json").write_text(json.dumps({"2": "analytical"}), encoding="utf-8")  # directory scans must ignore it
    labels, covered, warns = lib.load_stage1([tmp_path])
    assert labels[1] == "context" and labels[2] == "opinion" and labels[4] == "citation"
    assert labels[6] == "opinion" and labels[8] == "citation" and 7 not in labels
    assert covered == {1, 2, 3, 4, 5, 6, 8}
    assert len(warns) == 1 and "bogus" in warns[0]


def test_scores_validation(tmp_path):
    f = tmp_path / "s.json"
    f.write_text(json.dumps([
        {"id": 1, "depth": 3, "breadth": 2, "height": 4, "confidence": "HIGH", "rationale": "x"},
        {"id": 2, "depth": 3.4, "breadth": 2, "height": 4},
        {"id": 3, "depth": 6, "breadth": 2, "height": 4},
        {"id": 4, "depth": 3, "breadth": 2},
    ]), encoding="utf-8")
    scores, warns = lib.load_scores([f])
    assert set(scores) == {1, 2} and scores[1]["confidence"] == "high" and scores[2]["depth"] == 3
    assert len(warns) == 3  # rounded float + out of range + missing dimension


def test_formulas():
    sc = {"depth": 2, "breadth": 3, "height": 5}
    assert lib.composite(sc) == pytest.approx(10 / 3)
    assert lib.composite(sc, (1, 0, 0)) == 2 and lib.composite(sc, (2, 1, 1)) == pytest.approx(3.0)
    assert [lib.level_of(x) for x in (2.49, 2.5, 3.49, 3.5)] == ["low", "medium", "medium", "high"]
    assert lib.dominant({"depth": 2, "breadth": 1, "height": 2}) == "none"
    assert lib.dominant({"depth": 4, "breadth": 4, "height": 2}) == "mixed"
    assert lib.dominant({"depth": 2, "breadth": 3, "height": 5}) == "height"
    with pytest.raises(ValueError):
        lib.parse_weights("1,1")


def test_select_evidence_prefers_overlapping_passages():
    ev = {"passages": ["Cats purr softly at night.", "Evidence selection matters more than reader size for retrieval."]}
    out = ps.select_evidence("evidence selection is the bottleneck for retrieval readers", ev)
    assert out.startswith("Evidence selection")


def test_evidence_matching_rules():
    ref = {"title": "Reranking long documents with sparse signals", "year": 2022, "authors": ["John Smith", "Wei Chen"]}
    good = {"title": "Reranking Long Documents with Sparse Signals", "year": 2023, "authors": ["J. Smith", "W. Chen"]}
    assert fe._accept(ref, good)
    assert not fe._accept(ref, {**good, "title": "Reranking short documents with dense signals and more"})
    assert not fe._accept(ref, {**good, "year": 2015})
    assert not fe._accept(ref, {**good, "authors": ["Maria Garcia"]})


def test_lookup_prefers_a_candidate_with_abstract(monkeypatch):
    no_abs = {"title": "T", "abstract": "", "year": 2020, "venue": "", "source": "arxiv", "authors": []}
    with_abs = {"title": "T", "abstract": "An abstract.", "year": 2020, "venue": "V", "source": "openalex", "authors": []}
    monkeypatch.setattr(fe, "from_arxiv", lambda ref: no_abs)
    monkeypatch.setattr(fe, "from_openalex", lambda ref: with_abs)
    monkeypatch.setattr(fe, "from_s2", lambda ref: pytest.fail("should not be called"))
    assert fe.lookup({"title": "T"})["abstract"] == "An abstract."
    monkeypatch.setattr(fe, "from_openalex", lambda ref: None)
    monkeypatch.setattr(fe, "from_s2", lambda ref: None)
    out = fe.lookup({"title": "T"})
    assert out["matched"] and not out["abstract"] and "no abstract" in out["note"]
    monkeypatch.setattr(fe, "from_arxiv", lambda ref: None)
    assert fe.lookup({"title": "T"}) == {"matched": False}


# ----------------------------------------------------------------------------- end to end
def run(script: str, *args) -> subprocess.CompletedProcess:
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True,
                       encoding="utf-8")
    assert r.returncode == 0, r.stdout + r.stderr
    return r


def test_end_to_end_on_text_paper(tmp_path):
    paper = tmp_path / "paper.txt"
    paper.write_text(PAPER, encoding="utf-8")
    sent = tmp_path / "sentences.json"
    run("prepare_sentences.py", paper, "-o", sent)
    data = json.loads(sent.read_text(encoding="utf-8"))

    texts = {s["id"]: s for s in data["sentences"]}
    assert data["stats"]["references"] == 3 and data["stats"]["citing_sentences"] >= 4
    assert not any("Alice Brown" in s["text"] for s in texts.values())          # the reference list is not classified
    fail_id = next(i for i, s in texts.items() if s["text"].startswith("However, these systems fail"))
    assert texts[fail_id]["ref_ids"] == [1, 2] and texts[fail_id]["rule"]["type"] == "opinion"
    assert (tmp_path / "stage1" / "batch_001.txt").exists()

    # play the agent: the rule prior becomes the labels
    labels = tmp_path / "labels"
    labels.mkdir()
    ids = list(texts)
    (labels / "stage1_001.json").write_text(json.dumps({
        "range": [ids[0], ids[-1]],
        "opinion": [i for i, s in texts.items() if s["rule"]["type"] == "opinion"],
        "citation": [i for i, s in texts.items() if s["rule"]["type"] == "citation"]}), encoding="utf-8")
    opinions = [i for i, s in texts.items() if s["rule"]["type"] == "opinion"]
    assert len(opinions) >= 2

    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"1": {"title": "RAG for QA", "abstract": "We study retrieval augmented generation.", "matched": True},
                                    "2": {"matched": False}}), encoding="utf-8")
    run("prepare_scoring.py", sent, "--stage1", labels, "--evidence", evidence)
    plan = json.loads((tmp_path / "stage2" / "plan.json").read_text(encoding="utf-8"))
    assert plan["selected"] == len(opinions) and not plan["sampled"]
    batch = (tmp_path / "stage2" / "batch_001.txt").read_text(encoding="utf-8")
    assert "[R1]" in batch and "title only" in batch and "evidence_scope=sentence" in batch
    assert "citing" in (tmp_path / "sections.txt").read_text(encoding="utf-8")

    scores = tmp_path / "scores"
    scores.mkdir()
    rows = [{"id": i, "depth": 2 + (k % 3), "breadth": 3, "height": 4, "confidence": "medium", "rationale": f"r{i}"}
            for k, i in enumerate(opinions)]
    (scores / "stage2_001.json").write_text(json.dumps(rows), encoding="utf-8")
    (labels / "sections.json").write_text(json.dumps({"1 Introduction": "analytical"}), encoding="utf-8")

    out = tmp_path / "out"
    run("aggregate_insight.py", sent, "--stage1", labels, "--scores", scores, "--sections", labels / "sections.json",
        "--outdir", out, "--top-k", "1")
    rep = json.loads((out / "insight_report.json").read_text(encoding="utf-8"))
    assert rep["sentence_types"]["counts"]["opinion"] == len(opinions)
    assert rep["overall"]["n_scored"] == len(opinions)
    expect = sum((2 + k % 3 + 3 + 4) / 3 for k in range(len(opinions))) / len(opinions)
    assert rep["overall"]["composite_mean"] == pytest.approx(expect, abs=1e-3)
    assert rep["section_types"]["analytical"]["n"] == 1
    assert len(rep["top"]) == 1 and rep["unscored_opinion_ids"] == []
    assert (out / "insight_report.md").read_text(encoding="utf-8").startswith("# Insight classification report")
    assert (out / "insight_sentences.csv").read_bytes().startswith(b"\xef\xbb\xbf")

    run("aggregate_insight.py", sent, "--stage1", labels, "--scores", scores, "--outdir", out, "--lang", "zh")
    assert (out / "insight_report.md").read_text(encoding="utf-8").startswith("# Insight 分类报告")


def test_aggregate_flags_gaps():
    """Missing batches, scores on non-opinion sentences and unscored opinions must all show up in caveats."""
    data = {"source": {"title": "T"}, "lang": "en", "stats": {"citing_sentences": 0},
            "sections": [{"idx": 0, "title": "S", "level": 1, "sentences": 3, "citing": 0, "ref_ids": []}],
            "sentences": [{"id": i, "section_idx": 0, "section": "S", "paragraph_id": 1, "page": 1, "text": f"sentence {i}",
                           "prev": "", "markers": [], "ref_ids": [], "rule": {"type": "context", "strength": "", "signals": []}}
                          for i in (1, 2, 3)]}
    labels = {1: "opinion", 2: "opinion"}
    scores = {1: {"id": 1, "depth": 3, "breadth": 3, "height": 3, "confidence": "low", "rationale": ""},
              3: {"id": 3, "depth": 5, "breadth": 5, "height": 5, "confidence": "", "rationale": ""}}
    rep = ag.aggregate(data, labels, {1, 2}, scores, {}, None)
    text = " ".join(rep["caveats"])
    assert "no stage-1 label" in text and "excluded" in text and "no score" in text and "only 1 opinion" in text
    assert rep["overall"]["n_scored"] == 1 and rep["unscored_opinion_ids"] == [2]
