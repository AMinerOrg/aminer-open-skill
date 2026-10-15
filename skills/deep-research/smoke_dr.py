#!/usr/bin/env python3
"""Deep Research end-to-end smoke.

Two modes:

  --fixture (default, no key, no network)
      Loads samples/patchtst_v3_ledger.json and exercises the skill's own
      pipeline offline: the check gate returns a verdict, and render --final
      emits sections. The fixture is a schema/shape demo, not a gold-standard
      ledger, so check may legitimately flag it — what matters is the engine
      runs cleanly and emits a verdict, not that ok == True.

  --live  (needs AMINER_API_KEY, ~¥0.70)
      Runs the real engine on a question: init → probe → one live
      paper_qa_search_pro call → add the real results to the ledger → minimal
      outline + one claim → gaps → render. Proves REAL AMiner data flows
      through the whole skill pipeline. The scout/induce/iterate loop is
      model-driven and intentionally NOT reproduced here — this is a plumbing
      smoke, not a full research run.

The live mode is the credential-gated step: this script verifies the plumbing
in --fixture mode here and now; run --live with your AMINER_API_KEY to exercise
the real engine.

This smoke tests the skill's OWN pipeline (ledger → check → render) only. It
does not know about, and does not wire up, any external system that might
consume the ledger downstream — adapting the ledger to another system's schema
is that system's job, not the skill's.

Run:
    python smoke_dr.py --fixture
    AMINER_API_KEY=... python smoke_dr.py --live --question "patch tokenisation forecasting"
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
SCRIPTS = SKILL_DIR / "scripts"
EVIDENCE = SCRIPTS / "evidence.py"
AMINER = SCRIPTS / "aminer_open.py"


def _run(cmd: list[str], input_text: str | None = None) -> dict:
    """Run a python script subprocess, return parsed JSON stdout."""
    proc = subprocess.run(
        [sys.executable, *cmd],
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"command failed (exit {proc.returncode}): {' '.join(cmd)}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        # some subcommands print non-JSON status; return raw
        return {"_raw": proc.stdout.strip()}


def fixture_mode() -> int:
    """Exercise the skill's own pipeline offline on the sample ledger.

    check (the anti-fabrication gate) returns a structured verdict and
    render --final emits report sections. The fixture is a minimal shape demo,
    not a gold-standard ledger — check may legitimately flag it; we assert the
    engine *runs cleanly and emits a verdict*, not that ok == True.

    A second stage copies the fixture to a temp dir (the sample is read-only
    source) and walks the research-loop telemetry offline: tier → outline
    clamp → round → memo → decide → claim with verbatim evidence → M2
    verbatim check → verify gates → signals.
    """
    ledger_path = SKILL_DIR / "samples" / "patchtst_v3_ledger.json"
    assert ledger_path.exists(), f"fixture missing: {ledger_path}"

    # check: emits {ok, blocking, warnings, totals, spend}. Exits 1 when ok is
    # False (blocking issues) but still prints the JSON verdict to stdout.
    proc = subprocess.run(
        [sys.executable, str(EVIDENCE), "--state", str(ledger_path), "check"],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode in (0, 1), f"check crashed (exit {proc.returncode}): {proc.stderr}"
    check = json.loads(proc.stdout)
    assert "ok" in check and "blocking" in check, f"check verdict malformed: {check}"
    verdict = "PASS" if check["ok"] else "flagged (expected for the minimal fixture)"
    print(f"[fixture] check ran: {verdict}")

    # render --final: the report renderer runs on the fixture.
    render = subprocess.run(
        [sys.executable, str(EVIDENCE), "--state", str(ledger_path), "render", "--final"],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert render.returncode == 0, f"render failed (exit {render.returncode}): {render.stderr}"
    sections = [ln for ln in render.stdout.splitlines() if ln.startswith("## ")]
    assert sections, "render produced no sections"
    print(f"[fixture] render --final OK ({len(sections)} sections)")

    telemetry_smoke()
    figure_plan_smoke()
    print("\n[PASS] fixture smoke — skill pipeline (check→render→telemetry→figure plans) "
          "runs cleanly (no key needed).")
    return 0


def telemetry_smoke() -> None:
    """Offline walk of the research-loop telemetry on a copy of the fixture:
    the tier clamps the outline and the rounds, a claim's verbatim evidence is
    engine-checked, the verify gates execute, and signals prints the evaluator
    surface. Nothing here needs a key or a network."""

    def run_or_fail(args, expect_ok=True):
        p = subprocess.run([sys.executable, str(EVIDENCE), *args],
                           capture_output=True, text=True, encoding="utf-8")
        if expect_ok:
            assert p.returncode == 0, f"{args} failed: {p.stderr or p.stdout}"
            return json.loads(p.stdout) if p.stdout.strip() else {}
        assert p.returncode == 2, f"{args} should have been refused: {p.stdout}"
        return json.loads(p.stdout)

    with tempfile.TemporaryDirectory(prefix="dr_tel_") as work:
        ledger = Path(work) / "ledger.json"
        ledger.write_text((SKILL_DIR / "samples" / "patchtst_v3_ledger.json")
                          .read_text(encoding="utf-8"), encoding="utf-8")
        st = ["--state", str(ledger)]

        # tier: registers, then clamps — a second registration is refused.
        out = run_or_fail(st + ["tier", "--level", "simple",
                                "--reason", "single-paper fixture, single direction"])
        assert out["tier"] == "simple" and out["profile"]["max_directions"] == 2
        run_or_fail(st + ["tier", "--level", "complex", "--reason", "try to unclamp"],
                    expect_ok=False)

        # the material volume prints BEFORE any target exists: upstream
        # assigns chapter targets at writing time, over the full material
        # pile — the volume is the input targets are assigned from
        mat0 = subprocess.run([sys.executable, str(EVIDENCE), *st, "render",
                               "--material"], capture_output=True, text=True,
                              encoding="utf-8")
        assert mat0.returncode == 0, mat0.stderr
        assert "no writing target" in mat0.stdout and "material on file" in mat0.stdout, \
            "material view must show volumes with no target registered"

        # report-stage richness: writing targets ride the outline (DeepDive
        # assigns each chapter a target_chars by material sufficiency). The
        # fixture ledger already sits at the simple tier's 2-section cap, so
        # the targets go in through a --force re-set that keeps both ids.
        out = run_or_fail(st + ["outline", "set", "--force", "--allow-unscouted",
                                "--length-budget", "999999", "--json", json.dumps([
            {"title": "Fixture direction one", "target_chars": 2500,
             "children": [{"title": "Disagreement and open issues", "kind": "disagreement"}]},
            {"title": "Fixture direction two",
             "children": [{"title": "Disagreement and open issues", "kind": "disagreement"}]},
        ])])
        assert out["outline"][0]["target_chars"] == 2500 and out["target_total"] == 2500, out
        # a user budget is hard-capped at 80000 — clamped, not refused
        assert out["length_budget"] == 80000, out

        # round summaries: the why-stopped field is mandatory telemetry.
        run_or_fail(st + ["round", "--why-stopped", "fixture round closed",
                          "--direction", "1", "--note", "smoke"])
        run_or_fail(st + ["round", "--why-stopped", ""], expect_ok=False)

        # memo + decide: the depth slot and the decision record. The memo is
        # deliberately short — the smoke asserts the depth floor fires on it.
        run_or_fail(st + ["memo", "--section", "1", "--text", "fixture memo: mechanism, setup, numbers"])
        run_or_fail(st + ["decide", "--action", "continue", "--reason", "fixture decision"])

        # claim with verbatim evidence: the excerpt must be a substring of the
        # source's stored text — the fixture's first live source title is a
        # safe haystack for the smoke. A degenerate excerpt (single character)
        # is refused outright: it would match almost any haystack.
        state = json.loads(ledger.read_text(encoding="utf-8"))
        src = next(s for s in state["sources"] if not s.get("dropped"))
        section = state["outline"][0]["children"][0]["id"] if state["outline"][0]["children"] \
            else state["outline"][0]["id"]
        run_or_fail(st + ["claim", "--section", section, "--supports", str(src["n"]),
                          "--text", "fixture verbatim-evidence claim",
                          "--evidence", src["title"]])
        run_or_fail(st + ["claim", "--section", section, "--supports", str(src["n"]),
                          "--text", "degenerate excerpt claim", "--evidence", "算"],
                    expect_ok=False)
        gaps = run_or_fail(st + ["gaps"])
        thin = gaps["memos_thin"]
        assert any(t["section"] == "1" for t in thin), f"42-char memo must trip memos_thin, got {thin}"
        # the two discipline-drift observations exist on the warning surface
        for key in ("disagreements_without_conflict", "figure_plans_closed_untagged"):
            assert key in gaps, f"gaps missing observation key: {key}"
        gaps = run_or_fail(st + ["gaps"])
        new_claim_id = json.loads(ledger.read_text(encoding="utf-8"))["claims"][-1]["id"]
        flagged = {f["claim"] for f in gaps["claims_evidence_not_verbatim"]}
        assert new_claim_id not in flagged, \
            f"verbatim excerpt of the source title must pass M2, got {flagged}"

        # verify: judgments in, four states out, gates applied.
        out = run_or_fail(st + ["verify", "--claim", new_claim_id,
                                "--supported", "--confidence", "0.9"])
        assert out["passed"] == 1 and out["downgraded"] == 0, out

        # material view: targets vs material volume, material blocks with [@n]
        # marks, re-read list, and the uncited pool (the citable pool is the
        # whole ledger, not the claim set).
        mat = subprocess.run([sys.executable, str(EVIDENCE), *st, "render", "--material"],
                             capture_output=True, text=True, encoding="utf-8")
        assert mat.returncode == 0, mat.stderr
        assert "2500" in mat.stdout and "re-read" in mat.stdout.lower(), \
            "material view must carry the writing target and the re-read list"
        assert "uncited pool" in mat.stdout.lower(), "material view must show the uncited pool"
        assert f"[@{src['n']}]" in mat.stdout, "material blocks must cite ledger numbers"

        # renumber: the delivered report and the record-only length deviation
        # against the registered target (2500) — recorded, never a rewrite.
        para = ("The fixture report body carries enough prose units to clear the "
                "subsection floor so the renumber pass reaches its length block. ") * 20
        draft = Path(work) / "draft.md"
        draft.write_text(
            f"# Fixture report\n\n## 1. Body\n\n### 1.1 Point\n\n{para} [@{src['n']}]\n\n"
            "## References\n\n{{references}}\n", encoding="utf-8")
        ren = run_or_fail(st + ["render", "--renumber", "--draft", str(draft),
                                "--out", str(Path(work) / "out.md")])
        assert ren["length"]["target_total"] == 2500, ren["length"]
        assert ren["length"]["direction"] == "short" and ren["length"]["deviation"] < 0, ren["length"]
        # per-section lengths — the continue-writing loop aims at the thin
        # section, not the total
        assert any(s["heading"] == "1. Body" for s in ren["length"]["sections"]), ren["length"]
        # a draft may place the {{references}} placeholder without a heading
        # above it — the length cut must swallow only a *references* heading,
        # never the last body section (regression: an entire final section
        # vanished from a real run's length block)
        headless = Path(work) / "draft_headless.md"
        headless.write_text(
            f"# Fixture report\n\n## 1. Body\n\n### 1.1 Point\n\n{para} [@{src['n']}]\n\n---\n\n"
            "{{references}}\n", encoding="utf-8")
        ren2 = run_or_fail(st + ["render", "--renumber", "--draft", str(headless),
                                 "--out", str(Path(work) / "out2.md")])
        assert ren2["length"]["body_chars"] == ren["length"]["body_chars"], \
            (ren["length"], ren2["length"])
        assert any(s["heading"] == "1. Body" for s in ren2["length"]["sections"]), ren2["length"]

        # the write-time length observation persists into the ledger (upstream
        # logs its deviation post-delivery; the ledger is this fork's log) and
        # gaps echoes it — but check never gates on it (篇幅是目标不是硬约束)
        ledger_state = json.loads(ledger.read_text(encoding="utf-8"))
        assert ledger_state["length_report"]["body_chars"] == ren2["length"]["body_chars"]
        assert "length_report" in run_or_fail(st + ["gaps"])
        chk_probe = json.loads(subprocess.run(
            [sys.executable, str(EVIDENCE), *st, "check"],
            capture_output=True, text=True, encoding="utf-8").stdout)
        assert "length_report" not in chk_probe.get("blocking", {}) and \
            "length_report" not in chk_probe.get("warnings", {})

        # signals: the evaluator surface prints, unrecorded inputs say so.
        sig = run_or_fail(st + ["signals"])
        for key in ("tier", "directions", "rounds", "claims_digest", "memos",
                    "source_distribution", "retrieval_funnel", "write_targets",
                    "evidence_quality", "evaluation_history",
                    "verify_stats", "not_recorded", "absent_by_design"):
            assert key in sig, f"signals missing block: {key}"
        assert sig["retrieval_funnel"]["cited_by_live_claims"] >= 1, sig["retrieval_funnel"]
        # target/material pairing: section 1's entry carries both numbers, and
        # a target above its material surfaces as a check warning.
        assert sig["write_targets"]["sections"]["1"]["target"] == 2500, sig["write_targets"]
        assert sig["write_targets"]["sections"]["1"]["material_chars"] >= 0
        for key in ("write_targets_over_material", "sections_under_targeted_vs_material"):
            assert key in run_or_fail(st + ["gaps"]), f"gaps missing observation key: {key}"

        # recording-time volume checks: a cited source with no note blocks
        # delivery, thin notes / fragment-only evidence / yield-less rounds
        # warn (upstream's own numbers: 300-800-字 digest, 100-500-字
        # passages, forced needs_more on an empty pass)
        for key in ("cited_sources_note_thin", "claims_thin_evidence",
                    "rounds_without_yield", "sources_without_note"):
            assert key in run_or_fail(st + ["gaps"]), f"gaps missing observation key: {key}"
        chk = subprocess.run([sys.executable, str(EVIDENCE), *st, "check"],
                             capture_output=True, text=True, encoding="utf-8")
        assert chk.returncode in (0, 1), chk.stderr
        verdict = json.loads(chk.stdout)
        assert "cited_sources_without_note" in verdict["blocking"], verdict
        # L3: any live source with no note blocks (zero exemption)
        assert "sources_without_note" in verdict["blocking"], verdict

        print("[fixture] telemetry smoke OK (tier clamp → round → memo → decide → "
              "evidence → verify gates → material view → length deviation → signals)")


def figure_plan_smoke() -> None:
    """Offline walk of the figure-plan lifecycle: an abandoned plan must not
    block re-planning its own topic (the datum/figure error texts say
    "re-plan it"), the re-plan retires the dead record (one live plan per
    topic+section stays invariant), and the open/fulfilled duplicate guards
    keep refusing."""

    def run_or_fail(args, expect_ok=True):
        p = subprocess.run([sys.executable, str(EVIDENCE), *args],
                           capture_output=True, text=True, encoding="utf-8")
        if expect_ok:
            assert p.returncode == 0, f"{args} failed: {p.stderr or p.stdout}"
            return json.loads(p.stdout) if p.stdout.strip() else {}
        assert p.returncode == 2, f"{args} should have been refused: {p.stdout}"
        return json.loads(p.stdout)

    with tempfile.TemporaryDirectory(prefix="dr_fig_") as work:
        ledger = Path(work) / "ledger.json"
        ledger.write_text((SKILL_DIR / "samples" / "patchtst_v3_ledger.json")
                          .read_text(encoding="utf-8"), encoding="utf-8")
        st = ["--state", str(ledger)]
        topic = "how does accuracy scale with horizon"

        # plan → duplicate open refused (the guard's real job) → abandon
        run_or_fail(st + ["figure", "plan", "--section", "1", "--topic", topic])
        run_or_fail(st + ["figure", "plan", "--section", "1", "--topic", topic],
                    expect_ok=False)
        run_or_fail(st + ["figure", "plan", "--abandon", "fp1",
                          "--reason", "no public benchmark numbers"])

        # re-planning the abandoned topic succeeds and retires fp1
        out = run_or_fail(st + ["figure", "plan", "--section", "1", "--topic", topic])
        assert out["superseded"] == ["fp1"] and out["plan"]["id"] == "fp2", out
        state = json.loads(ledger.read_text(encoding="utf-8"))
        fp1 = next(p for p in state["figure_plans"] if p["id"] == "fp1")
        assert fp1.get("dropped") and "fp2" in fp1.get("drop_reason", ""), fp1
        # the retired record left the abandoned list (no stale limitation quote)
        gaps = run_or_fail(st + ["gaps"])
        assert not any(a["plan"] == "fp1" for a in gaps["figure_plans_abandoned"]), gaps

        # the re-planned topic walks to fulfillment; a fulfilled plan still
        # blocks same-topic re-planning (drop the figure to redo)
        for i, v in enumerate(["62.3", "58.1", "54.9"]):
            run_or_fail(st + ["datum", "add", "--source", "1", "--plan", "fp2",
                              "--metric", "MASE", "--value", v,
                              "--unit", "ratio", "--year", str(2020 + i)])
        run_or_fail(st + ["figure", "add", "--section", "1", "--type", "bar",
                          "--title", "Accuracy vs horizon",
                          "--from-datums", "d1", "d2", "d3", "--plan", "fp2"])
        run_or_fail(st + ["figure", "plan", "--section", "1", "--topic", topic],
                    expect_ok=False)

        print("[fixture] figure-plan smoke OK (plan → duplicate guard → abandon → "
              "re-plan supersedes → datums → figure closes plan)")


def live_mode(question: str) -> int:
    if not os.environ.get("AMINER_API_KEY"):
        print("ERROR: --live needs AMINER_API_KEY in env. "
              "Aborting before any paid call.", file=sys.stderr)
        return 1

    work = Path(tempfile.mkdtemp(prefix="dr_live_"))
    # The skill owns no ledger location; the host (here, this smoke script)
    # picks one. evidence.py reads $DR_LEDGER, so set it once for every child.
    os.environ["DR_LEDGER"] = str(work / "evidence-ledger.json")
    print(f"[live] workspace: {work}")
    print(f"[live] ledger: {os.environ['DR_LEDGER']}")
    print(f"[live] question: {question}")
    print(f"[live] cost estimate: ~¥0.70 (1× paper_qa_search_pro; paper_info free)")

    a = lambda *args: _run([str(AMINER), *args])

    # 1. init + probe (run evidence.py with cwd=work so any relative scratch
    #    lands there; the ledger itself is at $DR_LEDGER).
    def e_in_work(args, inp=None):
        proc = subprocess.run([sys.executable, str(EVIDENCE), *args],
                              input=inp, capture_output=True, text=True,
                              encoding="utf-8", cwd=str(work))
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr)
            raise SystemExit(f"evidence.py failed (exit {proc.returncode}): {args}")
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    e_in_work(["init", "--topic", question])
    e_in_work(["probe", "--axis", "topic", "--via", "paper_qa_search_pro", "--query", question])
    print("[live] init + probe p1 done")

    # 2. minimal outline FIRST (1 section + disagreement child) — `add --section`
    #    validates the section id against the outline, so the outline must exist
    #    before tagging. Scout/induce is model-driven; --allow-unscouted covers
    #    the smoke (we do not induce from results here).
    e_in_work(["outline", "set", "--allow-unscouted", "--json", json.dumps([
        {"title": "Overview", "from_probes": ["p1"], "children": [
            {"title": "Disagreement and open issues", "kind": "disagreement"}]}])])
    print("[live] outline set (1 section + disagreement)")

    # 3. one live paper_qa_search_pro call → pipe straight into the ledger,
    #    tagged to section 1, linked to probe p1.
    params = json.dumps({"query": question, "query_type": "auto", "sort": "balanced"})
    search_doc = a("--api", "paper_qa_search_pro", "--params", params)
    assert search_doc.get("ok"), f"search failed: {search_doc}"
    add_resp = e_in_work(["add", "--aminer", "--probe", "p1", "--section", "1"],
                         inp=json.dumps(search_doc))
    print(f"[live] added search results to ledger: {add_resp}")

    # 4. one claim grounded in the first source (source n=1). Read the ledger
    #    from $DR_LEDGER — that is where evidence.py actually persists it.
    state = json.loads(Path(os.environ["DR_LEDGER"]).read_text("utf-8"))
    first = next((s for s in state["sources"] if not s.get("dropped")), None)
    assert first, "no sources in ledger"
    claim_text = f"{first.get('title', 'This paper')} is relevant to: {question}."
    e_in_work(["claim", "--section", "1", "--supports", "1",
               "--text", claim_text, "--type", "interpretation"])
    print(f"[live] claim c1 grounded in source 1: {first.get('title','')[:50]}…")

    # 5. gaps (coverage is thin by design; check/gaps may flag — that's fine)
    gaps = e_in_work(["gaps"])
    print(f"[live] gaps: {len(gaps.get('unsupported_claims', []))} unsupported, "
          f"{len(gaps.get('sections_below_two_sources', []))} thin sections")

    # 6. render --final (proves the renderer works on real data)
    render = subprocess.run([sys.executable, str(EVIDENCE), "render", "--final"],
                            capture_output=True, text=True, encoding="utf-8", cwd=str(work))
    md = render.stdout
    assert "## " in md, "render produced no sections"
    print(f"[live] render --final OK ({len(md)} chars of markdown)")

    print("\n[PASS] live smoke — REAL AMiner data flowed through the skill pipeline "
          f"(init→probe→add→claim→render). Ledger saved: {os.environ['DR_LEDGER']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Deep Research end-to-end smoke.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fixture", action="store_true", help="no-key fixture mode (default)")
    mode.add_argument("--live", action="store_true", help="real AMiner run (needs AMINER_API_KEY, ~¥0.70)")
    parser.add_argument("--question", default="patch tokenisation long-horizon forecasting",
                        help="research question for --live")
    args = parser.parse_args()
    if args.live:
        return live_mode(args.question)
    return fixture_mode()


if __name__ == "__main__":
    sys.exit(main())
