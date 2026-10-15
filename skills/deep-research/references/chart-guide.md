# Chart Guide — figure plans, datums, registration, rendering

The single manual for charting: deciding a chart is worth planning and picking its type, retrieving until the data composes a complete chart, registering the figure from ledger numbers, rendering and recording back, and the rules when the work is delegated to a chart-topic subagent. The controller reads this at the chart-topic stage and puts it in every chart-topic subagent's assignment as the operating manual. Under the delegation the subagent runs the research loop and returns records; the controller stays the ledger's only writer. The gates below are the same whichever form runs.

## Plan — two questions, then the selection matrix

The outline is the last input that changes shape — so the moment it settles, decide the figures. Walk each section and ask two questions: does this section carry a quantitative question a chart would answer better than prose (a comparison, a trend, a share, a count), and is data for it plausibly public (institution reports, statistics bulletins, filings, official parameter pages)? Where both hold, record a **figure plan** — the chart *topic* (the quantitative question), not a title:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" figure plan \
  --section 2 --topic "国产大模型厂商市场份额对比" --type hbar
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" figure plan \
  --section 5 --topic "历年市场规模及预测" --type line
```

This is the stage that makes numbers a retrieval objective instead of a by-product. A Genre B report with zero plans trips `figure_plans_industry_expected` — an industry report that never asked "which numbers does this report need?" is the defect the benchmark called 数字太少、太软. Plan deliberately, not greedily: every open plan is a retrieval obligation, and `figures_over_budget` still caps the report at six charts.

**Pick the type from the selection matrix, not from habit.** The left column is the kind of quantitative question you recorded as the topic; the right column is this skill's channel for it. Six shapes are templates; everything else goes through the `--code` B-script path — and a `--code` figure is a normal figure: its script must read its numbers from the registered `data` on stdin, so the number-provenance gate holds whichever path renders it.

| The quantitative question (the topic you recorded) | Channel | Type |
| --- | --- | --- |
| One metric over time — market size by year, filings per year, performance across versions | template | `line` |
| A few categories compared, short labels — revenue of the top five vendors | template | `bar` |
| Many categories compared, or long CJK labels — per-assignee patent counts | template | `hbar` |
| Shares of a whole — market-share distribution, budget allocation, population structure | template | `pie` |
| Matrix / cross-tabulated data — correlation matrices, feature relationships | template | `heatmap` |
| Dated events rather than numbers — historical events, milestones, product history, a technology evolution roadmap | template | `timeline` |
| Relationship between two variables | B script | `--code` (scatter) |
| Distribution of one variable — histogram / density | B script | `--code` |
| Multi-indicator comparison of a few entities — radar | B script | `--code` |
| Distribution and outliers across groups — box plot | B script | `--code` |
| Scheduled durations and dependencies — gantt | B script | `--code` |
| Regional data — a data map (regional distribution, density, comparison) | B script | `--code` |

Some visual content has **no channel in this skill**: real photos, architecture diagrams, flowcharts, concept diagrams, UI screenshots, location maps, mind maps. A retrieved image cannot be number-provenanced and its licensing sits with the host — express such content in prose or a table, and do not force a plan type onto it. Plan fewer for short sections (a subsection under ~1,000 characters carries at most one figure); the hard caps stay with the engine.

## Data — retrieve per plan until sufficient

Retrieve **per plan**, in rounds, until the data composes a complete chart:

- A quantitative plan (bar/hbar/line/pie/heatmap, or undecided) is engine-counted at **≥3 live datums tagged to it** — `datum add --source N --plan fp1 …` at the moment you read the number. `gaps` reports the countdown as `figure_plans_thin`; once it flips to `figure_plans_unfulfilled`, the engine considers the plan ready to chart (`figure add --from-datums … --plan fp1` closes it). But three is the floor the engine can count, not the standard of a complete chart. Completeness is judged against the question the topic asks: shares must sum to (near) the whole, a trend must cover the span the section narrates, a comparison must carry the full cast of compared entities. Floor met and the chart would still be incomplete → keep retrieving; the unfulfilled warning means *ready*, not *stop*. The tagging is what makes the countdown real: `figure add --from-datums … --plan fpN` closes a plan with whatever datums you pass it, tagged or not — but a closure with zero tagged datums means the sufficiency loop never ran and the topic closed by assembly (`check` flags it as `figure_plans_closed_untagged`). Tag each number the moment you read it, not at chart time.
- Aim the probes at number-dense documents: institution report release pages, official statistics, company filings and parameter pages, then aggregators only to locate the primary. Trace a relayed number back to the originating institution before recording it.
- A paper/patent corpus topic (filings per year, per-assignee counts) assembles from detail-level 著录 already in the ledger — but aggregation is an assembly method, not an exemption from completeness. Before charting, assess the base: how many records carry the field, and how the values spread — a filings trend needs its years covered, an assignee landscape needs distinct assignees. If the base is too thin to compose a complete chart (two patents do not make a filings trend), widen it first: more `patent_search` probes (free) and `patent_detail` calls (¥0.01) until the corpus composes the chart, then `--from-source-metadata`.
- A `--type timeline` plan runs on dated events, not datums, so datum sufficiency does not apply — close it by registering the timeline figure.
- When a topic genuinely has no public data after real attempts, do not let the plan rot open: `figure plan --abandon fp3 --reason "厂商未公开交付量，仅定性表述"`. An abandoned plan is a recorded, quotable limitation — the report's 局限 section and Appendix C both surface it; a silently missing chart is neither.

Plans and the section loop share the same rounds — a round's probes serve whatever is open: sections short of evidence, and plans short of datums. Neither retires the other.

## Register — four paths from ledger numbers

A figure is **expected for an industry report (Genre B)** and **optional for an academic review (Genre A)**. `check` warns (`figures_industry_expected`) when a Genre B report ships with zero figures, (`figures_industry_quantitative_expected`) when a Genre B report ships no quantitative chart — a `timeline` alone does not satisfy it, the thin-web case this section exists to head off — and (`figures_thin_data`) when a registered figure has too few points to plot meaningfully — a one-bar bar chart, a one-point line, a one-event timeline is a defect, not a figure. **Pick the figure from the data you actually have.** A quantitative chart (`bar` / `hbar` / `line` / `pie` / `heatmap`) runs on numbers the ledger verified; a structural `timeline` runs on *dated events* (model releases, funding rounds, policy milestones) and leans on dates and labels, not on market-share percentages. When your web retrieval came back thin on numbers — no market shares, no funding totals — there are three fallbacks before you reach for the timeline, and you do **not** skip the figure or pad it with an unsourced number:

1. **A datum-backed chart** if you captured *any* numbers at all — even a few. `figure add --from-datums d1 d2 …` assembles a quantitative chart whose numbers are source-verified by construction.
2. **A corpus-aggregation chart** from the patent / paper metadata the ledger *does* hold. `figure add --from-source-metadata --field year --sources … --type bar` counts filings per year; `--field assignee` counts per rights holder; `--field venue` counts papers per venue. The counts are source-verified by construction (the sources *are* the data), so a thin-web run that still retrieved a patent or paper corpus ships a **real quantitative chart**, not a timeline stand-in — this is the fix for the data-thin run that used to force a structural fallback.
3. **A structural `timeline`** (or the player-comparison table) only when neither of the above has enough points — dated events from the entity-and-date data you *do* have.

A figure pictures a claim (or several) — it introduces no new data. Record it only after the claims it visualizes are in, because its `--data` must come from those claims' sources and `check` flags any number in `data` that no cited source carries. Years (1900–2099) and one- and two-digit counts are not checked, so a `timeline` of dated events passes the provenance gate cleanly. If the figure fulfils a plan from the chart-topic stage, pass `--plan fpN` when you add it — the plan closes, and Appendix C can show topic → data → chart as one traceable chain.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" figure add \
  --section 2.1 --type bar --title "Reported evaluation methods, 2024–2026" \
  --sources 3 7 12 --claims c2 c5 \
  --data '[{"label":"LLM-judge","value":66},{"label":"Human eval","value":18},{"label":"Benchmark suite","value":16}]'
# structural fallback when numeric market data is thin — dates + events, no percentages:
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" figure add \
  --section 2.1 --type timeline --title "国产大模型发布与监管里程碑" \
  --sources 5 8 14 --claims c3 c9 \
  --data '[{"date":"2023-03","event":"智谱 GLM 系列开源","group":"模型"},{"date":"2023-08","event":"首批算法备案","group":"政策"},{"date":"2024-05","event":"DeepSeek-V2 发布","group":"模型"}]'
# corpus-aggregation quantitative chart — the thin-web fallback BEFORE the timeline:
# the web came back with no market numbers, but the patent corpus is in the ledger,
# so filings-per-year / per-assignee / per-venue assemble from source metadata.
# --data and --sources are assembled for you; counts are source-verified by
# construction (the sources ARE the data), so this is a real bar, not a timeline stand-in:
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" figure add \
  --section 4.1 --type bar --title "国产人形机器人专利逐年申请量" \
  --sources 19 20 21 22 23 24 25 26 27 28 29 --from-source-metadata --field year
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" figure add \
  --section 4.1 --type hbar --title "人形机器人专利主要申请人" \
  --sources 19 20 21 22 23 24 25 26 27 28 29 --from-source-metadata --field assignee
# build a figure from captured datums — --data and --sources are assembled for you,
# and the numbers are source-verified by construction (each datum already cites its source):
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" datum add --source 3 --metric 市场份额 --value 32 --unit % --year 2024 --entity 智谱
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" datum add --source 7 --metric 市场份额 --value 24 --unit % --year 2024 --entity 百度
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" figure add \
  --section 2.1 --type bar --title "国产大模型厂商市场份额" --from-datums d1 d2   # ids from `datum list`
```

`--sources` are the source numbers backing the chart's data (the same numbers a text claim would cite); `--claims` are the claim ids the chart pictures, for cross-reference. `--type` is one of `bar` / `hbar` / `line` / `pie` / `heatmap` (quantitative — numbers the ledger verified) or `timeline` (structural — a list of `{date, event, group?}` dated events, the fallback when numeric market data is thin). For a shape none of those cover, pass `--code <path>` to a host-written matplotlib script instead; `chartrender.py` runs it sandboxed (no network, locked cwd, 30 s timeout, forbidden-token scan, data on stdin) and falls back to the matching template if it crashes. Either way the numbers come from the ledger, so `check`'s data↔source gate holds regardless of which path rendered it. Prefer `--from-datums d1 d2 …` over hand-typed `--data` for any figure whose numbers you captured as datums: `--data` and `--sources` are then assembled for you, and a `from_datums` figure is exempt from `figures_with_unsourced_numbers` because each datum already cites its source — the closed loop (capture at retrieval → assemble at figure time) that makes "insufficient data" a visible gap in `gaps` rather than a silent absence at wrap-up. The same closed loop holds for `--from-source-metadata`: pass the source numbers and a `--field` (`year` / `venue` / `assignee` / `kind`) and `--data` is assembled as a count along that field — `--data` and `--sources` come for free, and a `from_metadata` figure is exempt from `figures_with_unsourced_numbers` because the counts come from the ledger's own source records. This is the chart to reach for when the web returned no market numbers but the patent or paper corpus is already in the ledger — the thin-web case that used to force a timeline.

## Render — the sibling tool, then record back

`evidence.py` never spawns a process or imports matplotlib, so the chart is rendered out-of-band by the sibling tool and recorded back:

```bash
# prints JSON: {"ok": true, "id": "f1", "path": "knowledge/figures/f1.png",
#               "rendered_by": "template", "strategy": "auto", "fallback_reason": null}
python3 "${CLAUDE_SKILL_DIR}/scripts/chartrender.py" --id f1 --out knowledge/figures/f1.png

# record the result back into the ledger (use the rendered_by the step above returned)
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" figure mark-rendered --id f1 \
  --path knowledge/figures/f1.png --by template
```

`render --final` emits a `_[FIGURE f1] …_` placeholder in the section where the figure lives, carrying the figure id, its title and its source refs. Replace that placeholder with the image embed when you assemble the report (see `references/report-format.md`). Figures are capped at 6 per report and 2 per section; `gaps` reports over-budget as a warning. Both render channels read the registered `data` — the template directly, the B script through stdin — so the numbers on the canvas are the ledger's numbers by construction, and correctness rests on the engine's data↔source gate, not on a visual check of the PNG.

## Who charts — the chart-topic subagent

**Who charts: chart-topic subagents where the host can spawn them — record deliverers, never ledger writers.** The per-plan research loop (retrieve on the topic, judge completeness) is subagent work; every state mutation is controller work. A host that can spawn subagents delegates it — one open plan to one chart-topic subagent, the third capability-tiered delegation alongside the reading subagents and the cold judges (both defined in `references/research-loop.md`), and under the same contract as both: the brief carries the inputs, the report carries record JSON, and the controller — the ledger's only writer — enters the records (`add`, `datum add --plan`, `figure add --charted-by agent`) and runs the render chain (`chartrender.py`, `figure mark-rendered`). "I'll just run it in-session" from a delegating host is the failure this section exists to prevent; so is a subagent typing `evidence.py` itself — one writer is what makes parallel plan-owners safe with no locks. A host that cannot spawn subagents keeps the whole loop in-session, unchanged, and declares it: `figure add --charted-by controller --charted-reason <why no subagent>` (the reason is required at the CLI — the exception must state itself); an undeclared figure warns `figures_charting_undeclared`, and Appendix C reports each figure's mode. The engine cannot see whether a subagent really ran — forced declaration plus visibility is the ceiling here, the same ceiling verify's "who judges" runs at. The rules:

- **One subagent per open plan, dispatched at plan time.** The subagent owns its plan's research end to end: retrieve for the topic's numbers — even when earlier evidence exists, because it may be incomplete — deliver each read as a datum record in its report, judge when the data composes a complete chart (not merely the 3-datum floor), and deliver the figure spec (type, honest title, datum set). The controller enters the records, registers the figure (`figure add --from-datums … --plan fpN --charted-by agent`), renders, and records back. The controller keeps the two planning questions, the abandon decision, the budgets and all writing — a subagent never abandons a plan itself; it reports "no public data after real attempts" with a suggested reason, and the controller decides.
- **The batch is concurrent, the budget is generous.** Dispatch every open plan's subagent in one parallel batch — one message, several agents, never one by one; sequential dispatch spends wall-clock for nothing, since parallel plan-owners are safe precisely because no subagent touches state (§Records below). And each assignment carries a retrieval budget of **at least 10 calls** (web + AMiner combined) before "no public data" is sayable: three datums is the engine's floor, not a stopping bar, and a topic closed after two or three calls was skimmed, not researched. The one exemption is the corpus closure — a plan whose numbers come from ledger metadata (patent-year counting and the like) declares that in its record instead of a call count. The subagent's report states its attempts, and the controller registers the subagent's rounds with the attempt count riding the round note — the trail stays visible even though the engine cannot count host-side calls, the same forced-declaration ceiling `charted-by` runs at.
- **The assignment is narrow.** This file as the operating manual, plus: plan id, its quantitative question, section, suggested type; the datum floor (3, engine-counted — the floor, not the standard); the retrieval budget (≥10 calls — corpus closures declare themselves instead); the leads already in the ledger for this topic (existing source numbers and datums, pasted into the brief — start from them and never re-search what earlier rounds already found, but completeness is the bar: leads that cannot compose a complete chart mean more retrieval, corpus bases included); and the round caps, which still apply — the controller registers the subagent's rounds from its report, and the tier clamps bind exactly as they bind the controller.
- **Records, not ledger writes.** The subagent never runs `evidence.py` and never touches the ledger or other runtime state: one writer (the controller) is the design, and it is what lets several plan-owners run in parallel. The deliverable is the same record JSON the controller enters verbatim. The exposure this buys is the reading subagent's — a subagent that dies mid-run delivers nothing — and it is covered the same way: the three-retry rule, plus record-shaped deliverables that make re-entry mechanical. Sufficiency is never the subagent's feeling — `figure_plans_thin` → `figure_plans_unfulfilled` is the engine's countdown, and it runs on what the controller entered.
- **The deliverable is record JSON shaped for the existing commands.** Zero new commands, zero new fields. The engine's checks judge what the controller entered exactly as they judge controller-authored records — sourcing, sufficiency, budgets, the no-source block — no exemption, and none needed.
- **Failure: retry three times, then the controller takes the plan back.** Same parameter as the reading subagent. Never fabricate a datum or register a figure from numbers nobody read to cover a failed run — the no-source block and the number-provenance check exist precisely for that.
