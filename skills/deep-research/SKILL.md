---
name: deep-research
version: 1.0.0
author: AMiner
contact: report@aminer.cn
description: >
  Produce a cited, hierarchically numbered research report from AMiner Open Platform data plus the host's native web tools — and, in the same run, an Evidence Ledger: the self-describing, versioned JSON (sources, claims, figures, probes) behind the report — reusable as-is by anything downstream.
  Activate for literature reviews, research landscapes, entity investigations, trend comparisons, industry / market surveys, or any request that needs a sourced report rather than a lookup.
  You (the host model) drive a fixed research loop — scout the question, induce the outline from what came back, retrieve per section, record every source in an evidence ledger, find the gap, iterate — no claim reaches the report without a ledger source.
  AMiner routing and prices live in scripts/aminer_open.py; web evidence comes from the host's own WebSearch and WebFetch. Free-first; estimated AMiner cost of CNY 10+ needs explicit confirmation, CNY 20 hard stop. No extra LLM service is called.
  Route elsewhere for: a single lookup (use aminer-free-academic), a survey bibliography of hundreds of papers without a report (use aminer-deep-search), or personalized recommendations (use aminer-daily-paper).
metadata:
  {
    "openclaw":
      {
        "requires": {
          "bins": ["python3"],
          "env": ["AMINER_API_KEY"]
        },
        "primaryEnv": "AMINER_API_KEY"
      }
  }
---

# Deep Research

You are the researcher, not a wrapper around a search box. Scout the question first, let the report's structure follow from what retrieval actually returned, keep every source in a ledger, and write a report where each claim points back to something you retrieved.

## Language Routing

- Use `SKILL.zh.md` when the user mainly writes in Chinese or explicitly requests Chinese output.
- Use this `SKILL.md` for all other requests.
- Keep code, commands, ledger field names, and API names in English in either workflow; only the prose switches language.

## Deep Research produces two artifacts (v6 §1.2/§7.6)

Deep Research is **not** just an end feature (a report for humans). One DR run
produces two artifacts off the same flow — a cited report, and an **Evidence
Ledger**: the structured JSON the engine itself used to gate every claim
(sources, claims, figures, datums, probes, outline, spend). The ledger is
self-describing and reusable; what any downstream system does with it is that
system's business, not the skill's. The skill does not know or name a consumer:

```text
Deep Research Engine (scripts/evidence.py + scripts/aminer_open.py)
   ↓ one run
   ├── Evidence Ledger      (scripts/evidence.py state JSON — self-describing, reusable)
   └── Report + appendices  (evidence.py render --material → --renumber → --appendix)

self-check, no external consumer: evidence.py check · evaluation/evaluate.py
```

The ledger is the engine's own state — it is **not hand-written**, it falls out
of the research loop (§7.6). It is a self-describing, versioned JSON: anyone
downstream (a context store, a RAG index, a review pipeline, or nothing at all)
may read it as-is. The skill produces it and stops — it does not export, convert,
or adapt it to any other system's schema; that specialization is the external
system's job, not the skill's.

### Submodules (v6 §7.13)

- `scripts/evidence.py` — **engine + evidence-ledger + report-renderer**: the
  research loop, the machine-consumable ledger state (`{version, topic, probes,
  outline, sources, claims, figures, datums, spend}`), `analyze()` self-check, and `render`.
- `scripts/aminer_open.py` — AMiner Open Platform retrieval (stdlib urllib, 28
  endpoints, price catalog, cost document). DR's own spend-tracking path (§7.14).
- `scripts/chartrender.py` — renders one registered figure to a PNG. Host-called
  (a sibling to `aminer_open.py`, never spawned by `evidence.py`, which stays a
  pure offline ledger): deterministic matplotlib templates (`bar` / `hbar` / `line`
  / `pie` / `heatmap`) or a host-written B script run in a best-effort sandbox (no
  network, locked cwd, 30 s timeout, forbidden-token scan, data on stdin); a B
  failure falls back to the matching template. The figure's numbers still come from
  the ledger, so `check`'s data↔source gate holds either way.
- `evaluation/evaluate.py` — quality report from `analyze()` (§7.13 5th submodule,
  §7.15 internal validation).
- `samples/patchtst_v3_ledger.json` — v3-schema sample ledger (PatchTST).
- `references/research-loop.md` — the actual procedure (read it at task start).

## Scope

- Use for: literature reviews, research landscapes, scholar / institution / venue / patent investigations, trend and comparison questions, industry / market surveys, anything needing citations.
- Route elsewhere for: a single lookup (`aminer-free-academic`), a survey bibliography of hundreds of papers (`aminer-deep-search`), personalized recommendations (`aminer-daily-paper`).

## Pre-flight

1. Answer in the user's language unless they ask otherwise.
2. Ask at most two questions, and only when different answers would change the research scope. Otherwise state your assumptions and start.
3. The AMiner key is in the shell environment as `AMINER_API_KEY` — the host exports
   it (e.g. `export AMINER_API_KEY=…` or a sourced `.env`) before invoking the skill,
   and `aminer_open.py` reads it from there and nowhere else. If the key is
   missing or invalid the script returns an auth error — then stop and point the
   user to the [AMiner Console](https://open.aminer.cn/open/board?tab=control).
   Never request, print, log, or save the token.

## Tools

| Need | Tool |
| --- | --- |
| Papers, scholars, institutions, venues, patents | `scripts/aminer_open.py` — allowlisted AMiner endpoints with prices |
| Anything the web knows and AMiner does not: project pages, docs, standards, leaderboards, releases, news | the host's native `WebSearch` and `WebFetch` |
| Probes, outline, sources, claims (with verbatim `--evidence`), datums (captured data points), coverage gaps, citation numbering, spend | `scripts/evidence.py` — offline ledger |
| The round-end decision surface: complexity tier, round summaries, direction memos, decisions, evaluator signals, citation-faithfulness verify | `scripts/evidence.py` — `tier` / `round` / `memo` / `decide` / `signals` / `verify` (all offline; the engine computes every number, gates every threshold) |
| The writing surface before drafting: per-section targets vs material on file, material blocks (claims + verbatim evidence + source notes), the ranked re-read list, the uncited pool, memos | `evidence.py render --material` (offline, engine-assembled — write the draft from it, not from memory) |
| A registered figure rendered to a PNG — charts that visualize ledger-verified numbers, or a structural timeline of dated events | `scripts/chartrender.py` — matplotlib templates (`bar` / `hbar` / `line` / `pie` / `heatmap` / `timeline`) or a sandboxed B script; record the result back with `evidence.py figure mark-rendered` |

Rules:

- Every AMiner request goes through `scripts/aminer_open.py`. Never hand-roll a request, substitute another search API, or call an endpoint outside `references/api-reference.md`.
- Web evidence uses the host's own tools; do not bundle or shell out to a scraper. Prefer `WebFetch` on the actual page over trusting a search snippet. If native web tools are unavailable, continue AMiner-only and say so in the report.
- Nothing enters the report unless it is in the ledger, and no section exists that `evidence.py render` did not print.

Read `references/api-reference.md` before choosing AMiner calls. It marks `paper_qa_search_pro` as the default topic search, explains why `query_type: "auto"` is the default and when to drop to `topic`, lists the fields that steer a drifting query, and marks which endpoints are free.

## Method

Follow `references/research-loop.md`. It is the actual procedure — read it at the start of the task, not after you have already spent money.

Shape of it:

- **Round 0 — scout, judge the tier, then induce.** Frame the question, `evidence.py init` (pass `--genre industry` for an industry / market survey — the genre is set at `init` and drives the figures-expected `check`), run 3–4 `paper_qa_search_pro` probes in `query_type: "auto"` (~¥1.20) — separated by object and structured filter, not by rewording — triage with free `paper_info`, buy `paper_detail` for the keepers, then register the complexity tier (`evidence.py tier --level simple|moderate|complex --reason …` — simple 2 directions × 1 rerun × 3 rounds, moderate 3 × 2 × 6, complex 5 × 3 × 10; from then on the engine *refuses* outline/round registrations that exceed it), and induce 2–4 numbered top-level sections from what came back, each with 2–4 subsections, exactly one of which is the `disagreement` subsection. Do not set writing targets here — upstream assigns its chapter targets at report time, over the full material pile, and the wrap-up does the same (from the material view, by material sufficiency). A user-stated length goes in now as `--length-budget` (字当量, one page ≈ 700, clamped at 80000). Do not invent section titles before retrieval.
- **Chart topics — plan after the outline settles, then retrieve until sufficient.** Walk the outline and decide where a figure is needed *and* insertable; record one `evidence.py figure plan --section <id> --topic <quantitative question> [--type]` per chart topic (a Genre B report with zero plans warns `figure_plans_industry_expected`). **Dispatch at plan time, not chart time — and all at once**: a host that can spawn subagents gives each open plan one chart-topic subagent, the whole set dispatched as one concurrent batch (never one by one), each assignment carrying a retrieval budget of at least 10 calls (web + AMiner combined) before "no public data" is sayable — under the reading-subagent contract, brief in, record JSON out; the controller (the ledger's only writer) enters the records and runs the render chain (`datum add --plan`, `figure add --charted-by agent`, `chartrender.py`, `figure mark-rendered`); rules in `references/chart-guide.md` §Who charts. The controller runs the research loop in-session only when it cannot spawn subagents, declaring itself at `figure add --charted-by controller --charted-reason <why no subagent>` (the reason is required — the exception must state itself, and Appendix C reports each figure's mode). Pick the type from the selection matrix in `references/chart-guide.md` — six template shapes for the common quantitative questions, `--code` for the rest; photos, architecture diagrams and flowcharts have no channel, so keep them in prose or a table. Each round's retrieval also serves open plans: hunt that topic's numbers (number-dense doc types first; corpus topics close from ledger metadata), capture each read as `datum add --plan fpN`, and keep going until the data composes a complete chart (≥3 tagged datums is the engine's floor, not the standard) — then chart it with `figure add --from-datums … --plan fpN`. A topic with no obtainable public data is abandoned with a recorded reason (`figure plan --abandon`), quoted in 局限.
- **Each round** — retrieve per section and per open plan (AMiner + web) → pipe results in untagged with `--probe <id>`, then tag only the keepers with `--section <id>` and `drop` the noise → read (free `paper_info` triage before paid `paper_detail`; **where the host can spawn subagents, delegate the reading**: one reading subagent per section-batch of 3–6 keepers, spawned at triage time — assignment = section topic + the round's gap + the batch's source lines + the recording disciplines, deliverable = the records themselves, piped verbatim into `add`/`claim`/`fulltext`; a failed reader is retried up to three times, then the parent reads the batch itself — never fabricated records; hosts without subagents read in-session. Either way) every keeper gets a **300–800-字 digest `note`** at the moment of reading, batch by batch — never backfilled at wrap-up (a live source with no note **blocks `check`** — read it or drop it, zero exemption; a thin cited note warns); claims carry verbatim `--evidence` excerpts as **100–500-字 passages**, fragment-only sets warn; a section read at fulltext earns its direction `memo`, 600–1200 字, the section's narrative first draft) → `evidence.py gaps` → **close the round against computed signals**: `signals` prints the evaluator surface (source diversity, evidence quality, verify stats, the last five decisions — every number computed by the engine, unrecorded inputs say so), `round --why-stopped … --direction … --next-query …` files the round summary (a round whose probes kept nothing shows as `rounds_without_yield` — say so, never report it as sufficiency), **this round's new evidenced claims get their verify judgments now** (see below — the decision that follows reads the downgrades), `decide --action stop|continue|rerun… --reason …` records the call. The decision rules live in `references/research-loop.md` §5 — effort matched to the tier, depth judged from memos, single-source dependency hunted, contradictions resolved, history not repeated, a stop reason disposing of every standing warning (fixed / accepted with grounds / named in 局限) — and the tier caps refuse further rounds past the limit.
- **Verify at the round boundary, finished before writing** — two engine gates close the loop. Verbatim evidence: every claim a citation will lean on carries `--evidence` excerpts (a sentence fragment of at least 8 characters — isolated characters or bare numbers are refused) that the engine checks as a whitespace-insensitive substring of the source's stored text; a miss is a paraphrase posing as a quote — flagged, and the claim downgraded to background info. Citation faithfulness: record `evidence.py verify --claim cN --supported|--unsupported --confidence 0-1 --reason …` (疑罪从无 — only flag clear contradictions: wrong number, wrong entity, wrong time; an unsupported verdict must carry its reason, and reasons are written per claim, not one template across the batch — the engine flags boilerplate). **Who judges:** a host that can spawn subagents cold-judges every evidenced claim — the judge sees exactly the claim (≤1200 chars), its verbatim excerpts (≤1500 chars each) and the sources' titles (no topic, no other claims, no expected verdict), one claim per judge where affordable (a judge seeing a batch sees siblings — a declared compromise, kept small), works to the same 疑罪从无 scale, and its `--batch` JSON enters the ledger verbatim; a judge that fails, times out or returns garbage is recorded as inconclusive — never as a pass, and never re-judged by hand; all-or-nothing per run, and the method prose states which form ran. Hosts without subagents self-judge and say so — the engine gates (0.6 / half-cap) apply unchanged either way. The engine applies the gates: below confidence 0.6 a "not supported" reads as *not sure* and passes; one verify batch never downgrades more than half its claims. Downgraded claims are marked in `render --final` and must not carry citations; `check` warns `claims_awaiting_verify` until every evidenced claim has a judgment, and Appendix C reports the pass/downgrade/inconclusive distribution. **Timing** (upstream runs its verify at every wave boundary, *before* the evaluator, so downgrades trigger re-retrieval): each round's new evidenced claims are judged at its close, before `signals`/`decide` — the wrap-up pass is only the tail that empties the list.
- **Wrap-up** — `evidence.py check` must exit 0, then `evidence.py render --final` gives the ledger view (numbering, claims per section, stable ledger source numbers) and `evidence.py render --material` gives the **writing surface**: per section the material it holds (assign `target_chars` **now** — upstream's report-time timing; re-register with `outline set --force` over the identical structure, section ids are positional so tags survive. **The total comes first**: with no user length it is normally 2–3 万, 5 万 at most, thoroughness over padding — material then *distributes* it, 各章不必等长， thick sections writing long and thin ones short; material is a distributor, never a cap — do not arithmetically shave targets to a fraction of each pile, and the one legal reason to lower the total is material that cannot cover the topic, named in 局限 (thin material gets retrieval, not a smaller target); `check` observes both broken couplings, `write_targets_over_material` and `sections_under_targeted_vs_material`), the material blocks (claims with `[@n]` marks, verbatim evidence, source notes — the detail channel), the ranked re-read list (at most 5 core originals per section by claim-citation count; re-read them with your web tools before writing that section), the **uncited pool** (sources tagged to the section that no claim cites — the citable pool is the whole ledger, not the claim set; read a pool source before citing it or `drop` it; a chart's corpus sources are pool members too — the prose interpreting the chart cites its constituents, upstream has no figure-only class), and the latest memo. **Write the draft one top-level section at a time — before each section, only its material blocks, its uncited pool and its target; write it, move to the next (upstream generates chapter by chapter, each chapter's prompt carrying exactly that chapter's material — a whole-pile one-pass draft is where thin sections come from), citing sources as `[@n]` placeholders (one or two marks per source per section, on the sentence carrying its key fact — transitions and your own synthesis carry none; each core item gets a full paragraph, minor items merge into one sentence), never pasting `render --final` into the body** (no `c1` ids, no `_来源：` lines, no `_（分歧）_` tags, no raw `冲突：` bullets), ending with a references heading that holds one `{{references}}` line. The claims are the skeleton, not the ceiling: each subsection develops them into full paragraphs carrying the mechanism, numbers and detail already paid for in the ledger (paper abstracts, patent fulltext notes, web page facts) and written toward the section's target — claim restatements are a defect, and `render --renumber` hard-errors on any subsection under 300 prose units just as it does on a citation pointing at nothing. `render --renumber --draft <path> --out <path>` then swaps the placeholders for dense ascending citation numbers (adjacent citations spaced `[3] [7]`), fills the references slot with a cited-only bibliography, writes a citation-map sidecar next to the delivered report, and records the body length against the registered targets into the ledger (`length_report` — ±20% tolerance, total and per-section, record-only: observation for post-run review and the next run's targets, never a gate) — an `[@n]` naming an unknown or dropped source is a hard error. **A section beyond tolerance while its material holds more is not finished: continue writing it from the material blocks and uncited pool, re-run `render --renumber`, measure again — do not deliver a half-target report.** Finally `render --appendix --out auto --citation-map <sidecar>` writes the appendix tables (D carries the report↔ledger number map) and returns the one line the report quotes — it renders last, from the closed ledger: any entry recorded after it (a late claim, verify or figure) means re-running it, never hand-editing its tables. If the report has figures, the `figure add` → `chartrender.py` → `figure mark-rendered` chain must have run first — controller-side, from chart-topic subagent records, during the rounds, which is the normal path; arriving here with plans still uncharted and no `--charted-by controller --charted-reason` declaration means the chart-topic dispatch was skipped — fix the process (dispatch, or declare the exception) before wrapping up. `render --final` emits a `_[FIGURE fN] …_` placeholder per registered figure, which you replace with the image embed when assembling the draft. For an industry report, figures and a player-comparison table are expected, not optional.

Quick start:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" init --topic "RAG evaluation"
# industry / market survey:
# python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" init --topic "中国大模型行业调研" --genre industry

python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" probe --axis topic --via paper_qa_search_pro \
  --query "retrieval augmented generation evaluation"
python3 "${CLAUDE_SKILL_DIR}/scripts/aminer_open.py" --api paper_qa_search_pro \
  --params '{"query":"retrieval augmented generation evaluation","query_type":"auto","year_from":2023,"sort":"balanced"}' \
  | python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" add --aminer --probe p1
python3 "${CLAUDE_SKILL_DIR}/scripts/aminer_open.py" --api paper_info --params '{"ids":["<id>","<id>"]}' \
  | python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" add --aminer
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" drop --source 7 9 --reason "off topic"
python3 "${CLAUDE_SKILL_DIR}/scripts/aminer_open.py" --api paper_detail --params '{"id":"<id>"}' \
  | python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" add --aminer

python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" outline set --json '[
  {"title":"Evaluation methods","from_probes":["p1"],"children":[
    {"title":"LLM-judge metrics"},
    {"title":"Disagreement: judge validity","kind":"disagreement"}]}]'

python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" add --section 1.1 --json '[{"kind":"paper","id":"<id>","title":"..."}]'
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" claim --section 1.1 --supports 1 4 \
  --text "LLM-judge metrics dominate reported RAG evaluation since 2023"
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" gaps
```

## Invoking the scripts — and where the ledger lives

Invoke scripts via `${CLAUDE_SKILL_DIR}` so the script path does not depend on
cwd. The skill **owns no ledger location** — the path is the host's choice. When
nothing else has chosen, default the run's workspace to a per-run directory
`outputs/<topic-slug>-<YYYYMMDD-HHMM>/` under the current project (ledger at its
root, figures under `figures/`; one directory per run — runs never overwrite
each other), resolve it to an absolute path, and tell the user where the ledger
lives — a default the host applies, not one the engine assumes. Set
it once, `export DR_LEDGER=<workspace>/evidence-ledger.json`, and every
`evidence.py` / `evaluate.py` call reads it from `$DR_LEDGER` (or take `--state`
/ `--ledger` explicitly). The skill assumes no `knowledge/`, `.zscience/`, or
any directory — persistence and scratch are the host's job; the ledger is the
skill's output (and an optional input), not a file the skill owns. Never write
the ledger under `${CLAUDE_SKILL_DIR}` (the skill tree is read-only source).

The ledger *is* the skill's structured output — a self-describing, versioned
JSON. The skill produces it and stops: it does not export, convert, or adapt it
to any other system's schema. Anything that wants the research in another shape
(a context store, a RAG index, a brief) reads the ledger and does that itself,
outside the skill.

```bash
# the ledger view — the content reference to draft against (numbers are ledger n)
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" render --final
# the writing surface — per section: target, material blocks (claims + evidence
# + source notes), the ranked re-read list, the memo; write the draft from this
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" render --material
# the delivered report: [@n] placeholders become ascending [N], the references
# slot becomes a cited-only bibliography, and a citation-map sidecar is written
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" render --renumber \
  --draft <draft.md> --out <report.md>
# the appendices (retrieval log / cost / data & methods / citation map) next to the ledger
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" render --appendix --out auto \
  --citation-map <report-citation-map.json>
# the skill's own quality report on the ledger (§7.13)
python3 "${CLAUDE_SKILL_DIR}/evaluation/evaluate.py" --ledger "$DR_LEDGER"
```

## Cost control

- Free first: free discovery and disambiguation endpoints before anything paid; free `paper_info` before paid `paper_detail`.
- **Route by query shape.** `paper_qa_search_pro` at ¥0.30 is the default for topic and multi-filter search, and what Round 0 scout uses. Drop to `paper_search_pro` at ¥0.01 whenever the query is already a structured filter (author, org, venue, or a single controlled keyword with citation or year ordering).
- **Send the query in `query_type: "auto"` — query mode.** ~5 s vs ~0.4 s for non-LLM modes, well inside the 30 s timeout (no automatic retry on a paid endpoint), better recall. Drop to `topic` only for literal term matching, and pin the concept with `all_terms` when you do. Separate probes by object and filter, never by rewording.
- **Read what you cite — fulltext first.** Search results carry no abstract; a free `paper_info` slice is ~190 chars; `paper_detail` is ¥0.01 for the full abstract + keywords; and the open-access **original** (arXiv PDF/HTML/TeX, Google Patents, publisher OA) is read with the host's web tools and recorded via `evidence.py fulltext --source N --url … --via …` — free, outside the AMiner bill; numbers lifted from the original go in the read's `--note`, which the number-provenance check searches. When no open copy exists, record the downgrade: `fulltext --unavailable`. `check` warns with `cited_sources_without_detail` when a claim leans on a source never read properly, and with `cited_sources_without_fulltext` when a cited paper or patent is neither read at fulltext nor marked unavailable — a silent degrade is indistinguishable from not looking.
- **Patent quality is screened, not sorted.** The patent channel returns plain relevance (no citation/date ordering like the paper channel), so widen the pool at retrieval (`size` up to 100, paginate) and screen by tier once `patent_detail` has run: granted invention > assigned application > utility model / unassigned application. `check` warns `claims_weak_patent_sole_support` when a quantitative claim's only anchor is a weak tier, and `render --renumber` returns `weak_patent_numbers` for prose sentences whose every citation is one — cross-validate the number, or label it a single filer's design assertion.
- **Check `warnings` and `total` on every result.** `aminer_open.py` hoists them out of the response; a warning means the query that ran is not the query you sent.
- Estimate the whole planned chain with `--dry-run` or `--batch` before paid calls. `add --aminer` accumulates actual spend into the ledger; a paid call whose hits you discarded still needs `evidence.py spend`.
- A full scholar profile is about ¥6.00. At ¥10.00 show the call plan and wait for confirmation, then pass `--confirm-high-cost`. At ¥20.00 accumulated, `check` blocks — stop and hand over partial results.

## Budgets

2–4 top-level sections · 2–4 subsections each, one being the disagreement subsection · 3–4 probes (~¥1.20) · a complexity tier registered with `evidence.py tier` before the outline (simple 2×1×3 · moderate 3×2×6 default · complex 5×3×10 — directions × reruns × rounds; the engine refuses over-quota registrations, `--wasted` rounds are recorded but not charged) · ≤2 paid `paper_qa_search_pro` calls and ≤3 web calls per round, ¥0.01 `paper_search_pro` unlimited · ≤8 candidates per top-level section · ≤50 paid detail calls per task · ≤5 `paper_relation` expansions · ≤6 figures per report (≤2 per section; optional for Genre A, ≥1 expected for Genre B; no cost — rendered locally by `chartrender.py`, `timeline` template runs on dated events when numeric data is thin) · ¥10.00 confirmation threshold · ¥20.00 hard stop. A typical run lands near ¥2–3, and searches are ~83% of it — ration searches, not abstracts.

## Failure handling

- **Empty search**: reformulate once on a *different axis* — a different topic phrase or structured filter, not a reworded synonym — then report the gap instead of a third attempt.
- **Ambiguous entity**: show the top candidates and ask the user to pick. Never buy details for every candidate.
- **API error**: report the public endpoint name and an actionable message; never surface headers or credentials.
- **Starving section**: merge it into a neighbour rather than buying searches for symmetry. A thin subsection gets written thin and labelled thin.
- **Thin evidence**: `check` fails, so narrow the claims and ship a clearly limited report. Never fill a gap from memory.
- **No web tools**: continue with AMiner and record the limitation in the report's Limitations section.

## Output

Write the final report per `references/report-format.md`. Two genres, picked from the task framing: an **academic review** (default — literature reviews, research landscapes, entity investigations) and an **industry report** (industry / market surveys: "行业调研", "市场格局", "竞争格局"). For either genre the report is **prose you write from the ledger's claims — not `render --final` pasted into the body.** `render --final` is the ledger view: take from one run the section / subsection numbering, the claim set per section in order, and the stable ledger source numbers; write each subsection as flowing prose carrying its `[@n]` citation placeholders, and use tables when comparing several entities. `render --renumber` turns the draft into the delivered report — ascending `[N]` numbers by first appearance, a cited-only bibliography, and a citation-map sidecar. Do not paste the ledger scaffold — claim ids (`c1`), source-pool lines (`_来源：`), the `_（分歧）_` / `_（解读）_` tags, or raw `冲突：` bullets — into the report; those are ledger internals. The appendices are **not** part of the report: `render --appendix --out auto` writes Appendix A (retrieval log), B (calls and cost) and C (data and methods) to a file next to the ledger, and you append to Appendix C the few method facts the ledger cannot know. Probe ids, retrieval axes, API names, prices and screening counts live in that file, never in the report. For an **industry report**, the skeleton is the consulting shape (executive summary / market size / player landscape with a comparison table / competitive dynamics / technology & patents / supply chain & compute / policy / outlook), retrieval is web-first (market data, funding, chips, policy) with AMiner as the tech / IP channel, and at least one figure (market share / player / timeline) plus a player-comparison table are expected, not optional. `render` emits its headings in the language of the ledger's topic; copy the reference heading and entries as printed rather than translating them.

## Rules

- **Nothing in the report that is not in the ledger.** No section exists that `render` did not print; no claim appears without ledger sources.
- **Two senses of "figure".** A lowercase *figure* (as in `claims_with_unsourced_numbers`) means a number quoted in a claim — it must appear in a cited source. A registered *Figure* (`figure add`, id `f1…`) means a chart rendered to a PNG — its `data` is checked by the same number-provenance rule (`figures_unsupported_numbers`). Both draw from ledger numbers; neither may show a number the ledger does not vouch for.
- **Adversarial verification is mandatory.** Every top-level section has a `disagreement` subsection; every key claim is checked against a source that could contradict it.
- **Evidence is verbatim, and verified as it lands.** A claim that carries a citation records `--evidence` excerpts the engine checks against the source's stored text, and receives a `verify` judgment (supported / not, with confidence) at its round's close, while retrieval can still repair a downgrade. A claim downgraded by either gate — excerpt not verbatim, or verify-downgraded — is background information: it stays in the ledger but never carries a citation in the report.
- **No fabricated citations.** Every citation must be a real entity returned by `aminer_open.py` or a page actually fetched via `WebFetch`.
- **File output for large results.** When search results exceed 20 items or raw API output exceeds 5000 characters, write intermediate results to a scratch path the host chooses (e.g. `$DR_WORKDIR/scratch/`) instead of keeping them in context. The skill assumes no `.zscience/` or other scratch directory. Stdout only short status: `"Found N results, saved to <path>"`.
