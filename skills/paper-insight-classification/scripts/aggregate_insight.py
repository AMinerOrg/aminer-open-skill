#!/usr/bin/env python
"""Step 3: merge sentence types, three-dimension scores and section types into a paper-level insight report
(InsightEval Stage 4).

Output:
    insight_report.json    complete machine-readable report
    insight_report.md      human-readable report (statistics, section table, top / bottom opinion sentences)
    insight_sentences.csv  per-sentence detail (type, three scores, composite, level, dominant dimension, rationale)

Usage:
    python aggregate_insight.py work/sentences.json --stage1 work/labels --scores work/scores \
        [--sections work/labels/sections.json] [--summary work/summary.md] --outdir work/out
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import dump_json, load_json, setup_io  # noqa: E402
from insight_lib import (  # noqa: E402
    DIMS, LEVELS, SECTION_TYPES, SENT_TYPES, composite, describe, dominant, level_of, load_scores, load_section_types,
    load_stage1, parse_weights,
)


def _pct(n: int, total: int) -> float:
    return round(100 * n / total, 1) if total else 0.0


def aggregate(data: dict, labels: dict, covered: set, scores: dict, sec_types: dict, plan: dict | None,
              weights=(1, 1, 1), thresholds=(2.5, 3.5), top_k: int = 5) -> dict:
    low_th, high_th = thresholds
    sents = {s["id"]: s for s in data["sentences"]}
    caveats: list[str] = []

    types = {i: labels[i] if i in covered and i in labels else s["rule"]["type"] for i, s in sents.items()}
    unlabeled = [i for i in sents if i not in covered]
    if unlabeled:
        caveats.append(f"{len(unlabeled)} sentences have no stage-1 label and use the rule prior (e.g. {unlabeled[:6]})")
    unknown = sorted(set(labels) - set(sents))
    if unknown:
        caveats.append(f"labels refer to sentence ids that do not exist: {unknown[:10]}")

    opinion_ids = [i for i, t in types.items() if t == "opinion"]
    scored: dict[int, dict] = {}
    extra = []
    for i, sc in scores.items():
        if i not in sents or types[i] != "opinion":
            extra.append(i)
        else:
            c = composite(sc, weights)
            scored[i] = {**sc, "composite": round(c, 3), "level": level_of(c, low_th, high_th), "dominant": dominant(sc)}
    if extra:
        caveats.append(f"{len(extra)} scores belong to sentences that are not opinion (or do not exist) and were excluded: {sorted(extra)[:10]}")
    unscored = [i for i in opinion_ids if i not in scored]
    if unscored:
        caveats.append(f"{len(unscored)} opinion sentences have no score (e.g. {unscored[:8]})"
                       + ("; plan.json shows this is due to sampling" if plan and plan.get("sampled") else ""))
    if 0 < len(scored) < 10:
        caveats.append(f"only {len(scored)} opinion sentences were scored: paper-level statistics have very low confidence")
    if scored:
        n_low = sum(1 for v in scored.values() if v["confidence"] == "low")
        if n_low / len(scored) >= 0.3:
            caveats.append(f"{_pct(n_low, len(scored))}% of the scores have confidence=low (usually missing evidence)")
    if plan and plan.get("items"):
        items = [p for p in plan["items"] if p["id"] in scored]
        if items:
            no_ev = sum(1 for p in items if not p["with_evidence"])
            if no_ev / len(items) >= 0.3:
                caveats.append(f"{_pct(no_ev, len(items))}% of the scored opinion sentences have no abstract/full-text evidence; "
                               "their relative gain was judged from context only")

    # ---- paper level ----
    type_counts = {t: sum(1 for v in types.values() if v == t) for t in SENT_TYPES}
    dims_stats = {d: describe([v[d] for v in scored.values()]) for d in DIMS}
    comp_stats = describe([v["composite"] for v in scored.values()])
    hist = {d: {str(k): sum(1 for v in scored.values() if v[d] == k) for k in range(1, 6)} for d in DIMS}
    level_dist = Counter(v["level"] for v in scored.values())
    dom_dist = Counter(v["dominant"] for v in scored.values())
    conf_dist = Counter(v["confidence"] or "unspecified" for v in scored.values())
    means = {d: dims_stats[d]["mean"] for d in DIMS}
    profile = None
    if scored:
        top, bot = max(means.values()), min(means.values())
        profile = "balanced" if top - bot <= 0.3 else max(means, key=means.get)
    overall = {
        "n_scored": len(scored), "composite_mean": comp_stats["mean"],
        "level": level_of(comp_stats["mean"], low_th, high_th) if scored else None, "profile": profile,
    }

    # ---- section level ----
    sections = []
    for sec in data["sections"]:
        ids = [i for i, s in sents.items() if s["section_idx"] == sec["idx"]]
        sc_here = [scored[i] for i in ids if i in scored]
        mean_c = round(sum(v["composite"] for v in sc_here) / len(sc_here), 3) if sc_here else None
        sections.append({
            "idx": sec["idx"], "title": sec["title"], "level": sec["level"], "sentences": len(ids), "citing": sec["citing"],
            "refs": len(sec["ref_ids"]),
            "types": {t: sum(1 for i in ids if types[i] == t) for t in SENT_TYPES},
            "scored": len(sc_here),
            "means": {d: round(sum(v[d] for v in sc_here) / len(sc_here), 2) for d in DIMS} if sc_here else None,
            "composite": mean_c, "insight_level": level_of(mean_c, low_th, high_th) if mean_c is not None else None,
            "section_type": sec_types.get(sec["idx"]),
        })
    typed = [s for s in sections if s["section_type"]]
    st_dist = Counter(s["section_type"] for s in typed)
    lv_secs = [s for s in sections if s["insight_level"]]
    sec_level_dist = Counter(s["insight_level"] for s in lv_secs)

    def row(i: int) -> dict:
        s, v = sents[i], scored[i]
        return {"id": i, "section": s["section"], "page": s["page"], "text": s["text"], "ref_ids": s["ref_ids"],
                **{d: v[d] for d in DIMS}, "composite": v["composite"], "level": v["level"], "dominant": v["dominant"],
                "confidence": v["confidence"], "rationale": v["rationale"]}

    ranked = sorted(scored, key=lambda i: (-scored[i]["composite"], i))
    return {
        "source": data["source"], "lang": data["lang"],
        "config": {"weights": list(weights), "thresholds": {"low_below": low_th, "high_from": high_th}, "top_k": top_k},
        "sentence_types": {
            "total": len(sents), "counts": type_counts,
            "ratios": {t: _pct(n, len(sents)) for t, n in type_counts.items()},
            "citing_sentences": data["stats"]["citing_sentences"], "unlabeled": len(unlabeled),
        },
        "overall": overall,
        "dimensions": {"stats": dims_stats, "hist": hist, "composite": comp_stats},
        "levels": {"sentence": {k: {"n": level_dist.get(k, 0), "pct": _pct(level_dist.get(k, 0), len(scored))} for k in LEVELS},
                   "section": {k: {"n": sec_level_dist.get(k, 0), "pct": _pct(sec_level_dist.get(k, 0), len(lv_secs))} for k in LEVELS}},
        "dominant": {k: {"n": n, "pct": _pct(n, len(scored))} for k, n in dom_dist.most_common()},
        "confidence": dict(conf_dist),
        "section_types": {k: {"n": st_dist.get(k, 0), "pct": _pct(st_dist.get(k, 0), len(typed))} for k in SECTION_TYPES},
        "sections": sections,
        "top": [row(i) for i in ranked[:top_k]],
        "bottom": [row(i) for i in reversed(ranked[-top_k:])] if len(ranked) > top_k else [],  # when n <= top_k, `top` has them all
        "unscored_opinion_ids": unscored,
        "caveats": caveats,
        "sentences": [
            {"id": i, "section_idx": s["section_idx"], "type": types[i], **({k: scored[i][k] for k in
             (*DIMS, "composite", "level", "dominant", "confidence", "rationale")} if i in scored else {})}
            for i, s in sents.items()
        ],
    }


# ----------------------------------------------------------------------------- rendering
LANG = {
    "en": {
        "level": {"low": "low", "medium": "medium", "high": "high", None: "-"},
        "dom": {"depth": "Depth", "breadth": "Breadth", "height": "Height", "mixed": "mixed", "none": "no clear gain",
                "balanced": "balanced"},
        "sec": {"descriptive": "descriptive", "comparative": "comparative", "analytical": "analytical"},
        "title": "# Insight classification report: {name}",
        "unnamed": "Untitled paper",
        "disclaimer": "This report comes from an opinion-extraction -> evidence-comparison -> three-dimension-scoring "
                      "pipeline. Insight is the **gain in understanding relative to the cited references**; scores are an "
                      "LLM's relative judgments meant for locating and comparing, not a verdict on the paper's value. "
                      "Level thresholds are this skill's defaults and can be changed with --thresholds.",
        "overview": "## Overview", "metric": "Metric", "result": "Result",
        "sent_total": "Sentences", "citing": "citing", "types_row": "context / citation / opinion",
        "opinion_share": "opinions are {x}%", "scored": "Scored opinion sentences",
        "overall": "**Overall insight composite (1-5)**", "profile": "Insight profile",
        "summary_h": "## Summary",
        "summary_ph": "(not provided: write 3-5 sentences from the statistics and the top/bottom sentences, "
                      "then re-run with --summary)",
        "hist_h": "## Score distribution (sentences)", "dim": "Dimension",
        "lvl_h": "## Insight level and dominant dimension of opinion sentences", "lvl": "Level", "n": "Sentences",
        "share": "Share", "dom_h": "Dominant dimension",
        "sec_h": "## Sections",
        "sec_cols": ["#", "Section", "Sentences", "Citing", "Opinions", "Scored", "Composite", "Level", "Type"],
        "sec_dist": "Section types: ", "sec_lvl": "Section insight levels: ",
        "top": "## Highest-insight opinion sentences", "bottom": "## Lowest-insight opinion sentences",
        "composite": "composite", "sentence": "Sentence", "rationale": "Rationale", "caveats": "## Caveats",
    },
    "zh": {
        "level": {"low": "低", "medium": "中", "high": "高", None: "—"},
        "dom": {"depth": "深度", "breadth": "广度", "height": "高度", "mixed": "多维并列", "none": "无明显增量",
                "balanced": "均衡"},
        "sec": {"descriptive": "描述型", "comparative": "对比型", "analytical": "分析型"},
        "title": "# Insight 分类报告：{name}",
        "unnamed": "未命名论文",
        "disclaimer": "本报告由“观点句抽取 → 证据比对 → 三维评分”流程生成：insight 是相对于被引文献的**理解增量**，"
                      "分数是 LLM 的相对判断，用于定位与比较，不是对论文价值的终审结论；等级阈值为本 skill 的默认设定，"
                      "可通过 --thresholds 调整。",
        "overview": "## 总览", "metric": "指标", "result": "结果",
        "sent_total": "句子总数", "citing": "带引用", "types_row": "context / citation / opinion",
        "opinion_share": "观点句占 {x}%", "scored": "已评分观点句",
        "overall": "**总体 insight 综合分（1–5）**", "profile": "论文洞察画像",
        "summary_h": "## 总体评价",
        "summary_ph": "（未提供：请依据上面的统计和下面的高/低洞察句补写 3–5 句，用 --summary 重新生成。）",
        "hist_h": "## 三维得分分布（句数）", "dim": "维度",
        "lvl_h": "## 观点句洞察等级与最突出维度", "lvl": "等级", "n": "句数", "share": "占比", "dom_h": "最突出维度",
        "sec_h": "## 章节分析",
        "sec_cols": ["#", "章节", "句子", "引用句", "观点句", "已评分", "综合分", "洞察等级", "章节类型"],
        "sec_dist": "章节类型分布：", "sec_lvl": "章节洞察等级分布：",
        "top": "## 高洞察观点句", "bottom": "## 低洞察观点句",
        "composite": "综合", "sentence": "原句", "rationale": "理由", "caveats": "## 注意事项",
    },
}


def _ms(st: dict) -> str:
    return "-" if st["mean"] is None else f"{st['mean']:.2f} ± {st['std']:.2f} (median {st['median']:g})"


def _cut(s: str, n: int = 160) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def render_md(rep: dict, summary: str, lang: str = "en") -> str:
    t = LANG.get(lang, LANG["en"])
    st, ov, ds = rep["sentence_types"], rep["overall"], rep["dimensions"]
    L = [t["title"].format(name=rep["source"].get("title") or t["unnamed"]), "", f"> {t['disclaimer']}", "", t["overview"], ""]
    L += [
        f"| {t['metric']} | {t['result']} |", "|---|---|",
        f"| {t['sent_total']} | {st['total']} ({t['citing']} {st['citing_sentences']}) |",
        f"| {t['types_row']} | {st['counts']['context']} / {st['counts']['citation']} / {st['counts']['opinion']} "
        f"({t['opinion_share'].format(x=st['ratios']['opinion'])}) |",
        f"| {t['scored']} | {ov['n_scored']} |",
    ]
    if ov["n_scored"]:
        L += [
            f"| {t['overall']} | **{ov['composite_mean']:.2f} ({t['level'][ov['level']]})** |",
            f"| Depth | {_ms(ds['stats']['depth'])} |",
            f"| Breadth | {_ms(ds['stats']['breadth'])} |",
            f"| Height | {_ms(ds['stats']['height'])} |",
            f"| {t['profile']} | {t['dom'].get(ov['profile'], ov['profile'])} |",
        ]
    L += ["", t["summary_h"], "", summary.strip() if summary.strip() else t["summary_ph"], ""]

    if ov["n_scored"]:
        L += [t["hist_h"], "", f"| {t['dim']} | 1 | 2 | 3 | 4 | 5 |", "|---|---|---|---|---|---|"]
        for d in DIMS:
            L.append(f"| {d} | " + " | ".join(str(ds["hist"][d][str(k)]) for k in range(1, 6)) + " |")
        lv, dm = rep["levels"]["sentence"], rep["dominant"]
        L += ["", t["lvl_h"], "", f"| {t['lvl']} | {t['n']} | {t['share']} |", "|---|---|---|"]
        L += [f"| {t['level'][k]} | {lv[k]['n']} | {lv[k]['pct']}% |" for k in LEVELS]
        L += ["", f"| {t['dom_h']} | {t['n']} | {t['share']} |", "|---|---|---|"]
        L += [f"| {t['dom'].get(k, k)} | {v['n']} | {v['pct']}% |" for k, v in dm.items()]

    cols = t["sec_cols"]
    L += ["", t["sec_h"], "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for s in rep["sections"]:
        if not s["sentences"]:
            continue
        comp = "-" if s["composite"] is None else "%.2f" % s["composite"]
        title = s["title"].replace("|", "/")
        L.append(
            f"| {s['idx']} | {title} | {s['sentences']} | {s['citing']} | {s['types']['opinion']} | {s['scored']} | "
            f"{comp} | {t['level'][s['insight_level']]} | {t['sec'].get(s['section_type'], '-')} |"
        )
    stp = rep["section_types"]
    if any(v["n"] for v in stp.values()):
        L += ["", t["sec_dist"] + ", ".join(f"{t['sec'][k]} {v['n']} ({v['pct']}%)" for k, v in stp.items())]
    if any(v["n"] for v in rep["levels"]["section"].values()):
        L += ["", t["sec_lvl"] + ", ".join(f"{t['level'][k]} {v['n']} ({v['pct']}%)" for k, v in rep["levels"]["section"].items())]

    for key in ("top", "bottom"):
        if rep[key]:
            L += ["", f"{t[key]} (top {len(rep[key])})", ""]
            for r in rep[key]:
                L.append(f"- **[{r['id']}]** {t['composite']} {r['composite']:.2f} (D{r['depth']} B{r['breadth']} H{r['height']}, "
                         f"{t['level'][r['level']]}, {t['dom'].get(r['dominant'])}) {r['section']} p.{r['page']}")
                L.append(f"  - {t['sentence']}: {_cut(r['text'], 240)}")
                if r["rationale"]:
                    L.append(f"  - {t['rationale']}: {_cut(r['rationale'], 240)}")
    if rep["caveats"]:
        L += ["", t["caveats"], ""] + [f"- {c}" for c in rep["caveats"]]
    return "\n".join(L) + "\n"


def write_csv(rep: dict, data: dict, path: Path) -> None:
    sents = {s["id"]: s for s in data["sentences"]}
    cols = ["id", "section", "page", "type", "ref_ids", "depth", "breadth", "height", "composite", "level", "dominant",
            "confidence", "rationale", "text"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:  # utf-8-sig: opens cleanly in Excel
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rep["sentences"]:
            s = sents[r["id"]]
            w.writerow({"id": r["id"], "section": s["section"], "page": s["page"], "type": r["type"],
                        "ref_ids": " ".join(map(str, s["ref_ids"])), "text": s["text"],
                        **{k: r.get(k, "") for k in (*DIMS, "composite", "level", "dominant", "confidence", "rationale")}})


def main() -> int:
    setup_io()
    ap = argparse.ArgumentParser(description="Merge the labels into a paper-level insight classification report")
    ap.add_argument("sentences", type=Path)
    ap.add_argument("--stage1", type=Path, nargs="+", required=True, help="stage-1 label files or directories")
    ap.add_argument("--scores", type=Path, nargs="*", default=[], help="stage-2 score files or directories")
    ap.add_argument("--sections", type=Path, nargs="*", default=[], help="section type label files")
    ap.add_argument("--plan", type=Path, help="plan.json from prepare_scoring.py (default <sentences dir>/stage2/plan.json)")
    ap.add_argument("--summary", type=Path, help="overall assessment written by the agent (Markdown / plain text)")
    ap.add_argument("--weights", default="1,1,1", help="depth,breadth,height weights (default 1,1,1)")
    ap.add_argument("--thresholds", default="2.5,3.5",
                    help="level cut-offs: low < first <= medium < second <= high (default 2.5,3.5)")
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--lang", choices=["auto", "en", "zh"], default="auto",
                    help="language of insight_report.md (auto = the paper's language)")
    ap.add_argument("--outdir", type=Path, default=Path("."))
    args = ap.parse_args()

    data = load_json(args.sentences)
    labels, covered, w1 = load_stage1(args.stage1)
    scores, w2 = load_scores(args.scores) if args.scores else ({}, [])
    sec_types, w3 = load_section_types(args.sections, data["sections"]) if args.sections else ({}, [])
    plan_path = args.plan or args.sentences.parent / "stage2" / "plan.json"
    plan = load_json(plan_path) if plan_path.is_file() else None
    th = tuple(float(x) for x in args.thresholds.split(","))
    rep = aggregate(data, labels, covered, scores, sec_types, plan, parse_weights(args.weights), th, args.top_k)  # type: ignore[arg-type]
    rep["caveats"] = [*(f"[input] {w}" for w in (*w1, *w2, *w3)), *rep["caveats"]]
    if not args.scores:
        rep["caveats"].append("No score files were given: the report only contains sentence-type statistics")

    args.outdir.mkdir(parents=True, exist_ok=True)
    summary = args.summary.read_text(encoding="utf-8") if args.summary and args.summary.is_file() else ""
    lang = data.get("lang", "en") if args.lang == "auto" else args.lang
    dump_json(rep, args.outdir / "insight_report.json")
    (args.outdir / "insight_report.md").write_text(render_md(rep, summary, lang), encoding="utf-8")
    write_csv(rep, data, args.outdir / "insight_sentences.csv")

    st, ov = rep["sentence_types"], rep["overall"]
    print(f"Sentences {st['total']} | context {st['counts']['context']} | citation {st['counts']['citation']} | "
          f"opinion {st['counts']['opinion']}")
    if ov["n_scored"]:
        m = rep["dimensions"]["stats"]
        print(f"Scored {ov['n_scored']} | composite {ov['composite_mean']:.2f} ({ov['level']}) | "
              f"D {m['depth']['mean']:.2f} / B {m['breadth']['mean']:.2f} / H {m['height']['mean']:.2f} | profile {ov['profile']}")
    for c in rep["caveats"]:
        print(f"WARNING: {c}")
    print(f"Wrote {args.outdir}/insight_report.(json|md) and insight_sentences.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
