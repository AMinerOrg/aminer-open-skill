# Research Loop

You are the controller. Round 0 scouts the question and induces the report's outline from what came back; every later round fills that outline. Nothing enters the report that is not in the ledger, and no section exists that `evidence.py render` did not print.

## Round 0 — scout, then induce

Do not decide the report's topics before retrieval. Find out what the literature actually contains, then let the outline follow.

1. Write down the research object, time window, audience, and output language. State assumptions instead of asking about optional constraints.

2. Create the ledger. Pick the genre from the task framing — it drives `check`'s figures-expected rule, so set it here, not later: `academic` (default — literature reviews, research landscapes, entity investigations) or `industry` (industry / market surveys: "行业调研", "市场格局", "竞争格局"). An industry topic initialised as `academic` will **not** warn when it ships without figures, so the genre must be set at `init` and cannot be added to an existing ledger without re-init.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" init --topic "LLM agent long-term memory"
# industry / market survey:
# python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" init --topic "中国大模型行业调研" --genre industry
```

3. **Scout with 3–4 topic probes.** `paper_qa_search_pro` is the search of record: ¥0.70 per call, about ¥2.80 for the whole scout. Register each probe before you run it — the ledger uses the registration to measure whether the probe earned its keep.

**Send the query in `query_type: "auto"` — query mode — unless you need literal term matching.** `auto` runs a server-side LLM over your text and parses it into topic, filters, translation and sort intent. Measured: about 5 s per call against about 0.4 s for the non-LLM modes — slower, but comfortably inside the uniform 30 s timeout. You pay that latency for recall, and the recall is the point.

`query_type: "topic"` skips the LLM and matches `title` / `title_zh` / `keywords` / `abstract` **literally** — which means a multi-concept phrase gets pulled toward whichever term dominates the index. Measured on the same subject:

| Query | Mode | Result |
| --- | --- | --- |
| `"efficient large language model architecture mixture of experts long context"` | `topic` | ten long-context inference papers, **zero** on mixture-of-experts |
| `"mixture of experts sparse activation in large language models"` | `auto` | ten MoE-on-LLM papers including two dedicated surveys |
| `"sparse expert routing in language model backbones"` + `all_terms:["mixture of experts"]` | `topic` | ten MoE routing papers; `total` narrowed from `gte 10000` to `eq 1058` |

Query mode recovered a subfield that literal matching had silently dropped. `topic` recovers it too — but only once `all_terms` pins the concept, which is the point of that field.

**Separate probes by object and filter, not by wording.** What makes a second probe worth ¥0.70 is a different topic phrase, a different entity, or a different structured filter — `all_terms` / `any_terms` / `venues` / `year_from` / `min_citations`. The two MoE probes above differ that way and returned 19 distinct papers out of 20, overlapping on one. Two probes that differ only in phrasing do the opposite: `auto` normalises differently-worded questions down to the same parsed topic, so "how is long-term memory implemented in LLM agents" and "how is long-term memory in LLM agents evaluated" came back with 8 of the same 10 papers. Rephrasing is not a second probe; `gaps` reports it as `low_yield_probes`.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" probe --axis topic --via paper_qa_search_pro \
  --query "long-term memory for LLM agents"
python3 "${CLAUDE_SKILL_DIR}/scripts/aminer_open.py" --api paper_qa_search_pro \
  --params '{"query":"long-term memory for LLM agents","query_type":"auto","year_from":2024,"sort":"balanced"}' \
  | python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" add --aminer --probe p1

python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" probe --axis topic --via paper_qa_search_pro \
  --query "memory poisoning and privacy in agents"
python3 "${CLAUDE_SKILL_DIR}/scripts/aminer_open.py" --api paper_qa_search_pro \
  --params '{"query":"agent memory security","query_type":"auto","any_terms":["poisoning","privacy","injection"],"year_from":2024}' \
  | python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" add --aminer --probe p2
```

Three properties of this endpoint shape the scout:

- **Page size is fixed at 10.** Do not send `size`. Four probes give about forty results — enough to induce an outline, not enough to be the whole evidence base. Paginating with `cursor` costs another ¥0.70 per page, and a cursor request may carry nothing but the cursor.
- **Search results carry no abstract** — only `paper_id`, `title`, `title_zh`, `authors[].name`, `year`. Step 4 is not optional.
- **Read `warnings` and `total`.** `aminer_open.py` hoists both onto the result. A warning such as `QUERY_CONDITION_IGNORED` means the query that ran is not the query you sent.

`total` tells you how thin your slice is, and it has a required response:

| `total` | What it means | What to do |
| --- | --- | --- |
| `{"relation":"gte","value":10000}` | your ten results are under 0.1% of the field | narrow with `all_terms` / `venues` / `min_citations` / a tighter `year_from`, or spend one ¥0.70 `cursor` page — and say in Limitations that the slice was thin |
| `{"relation":"eq","value":9666}` | still a broad field, same treatment | as above |
| `{"relation":"eq","value":34}` | you have nearly all of it | move on; no more spending on this axis |

**If the request is in Chinese, run at least one probe against the Chinese corpus** — `language_preference` or `has_chinese_title` — or record in Limitations that only English-language literature was retrieved. English topic phrases against an English index silently exclude the Chinese half of the corpus.

Add one or two `WebSearch` / `WebFetch` probes for framing that papers do not carry (vendor positions, standards, leaderboards). Register them like any other probe:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" probe --axis web --via WebFetch --query "AI Index 2026 technical performance"
```

**Industry-report genre (when the task framing is an industry / market survey — "行业调研", "industry report", "市场格局").** The spine of evidence is the web, not papers. Run **3–5 web probes in Round 0**, one per industry dimension: market size and growth (IDC / 艾瑞 / 亿欧 / Statita), the player set and their funding or valuation (company filings, IT 桔子 / Crunchbase-style data, news), supply chain and compute (US export controls, H800 / H100, domestic chips such as 华为昇腾, 智算中心 capacity), and the policy frame. **Delegate these web probes where the host can spawn subagents** — one dimension per subagent, the whole set dispatched in one concurrent batch: the fourth capability-tiered delegation alongside the reading subagents, the cold judges and the chart-topic subagents, under the same contract (brief in, records out; the controller stays the ledger's only writer). Register each probe yourself first, then hand the subagent its dimension: the probe's query, the pages to fetch, and the recording disciplines — per page a note plus every citable number as a datum record — and pipe what comes back into `add --json` / `datum add` verbatim. Web probes are the tier worth delegating because each is a bundle of independent fetches with no shared state; paper and patent probes stay in-session — their triage feeds the outline induction, which is controller work. Put every number you will cite or plot into the ledger as a **datum** — a first-class data point, not free text in a `note` — the moment you read the page: `evidence.py datum add --source N --metric "市场规模" --value 410 --unit 亿元 --year 2024 --entity 中国`. Datums are addressable by id (`d1`, `d2`…), so `gaps` can enumerate exactly which numbers you have and which you lack, and `check` warns (`industry_web_sources_without_datums`) when a web source was fetched but no number was extracted from it — the page is in the ledger but its quantitative content evaporated, which is the precise failure mode that starves figures. The web source's `note` may still hold the surrounding sentence for context, but the number itself must be a datum. Capture at retrieval time, not at wrap-up: a number left in context is, by figure time, gone. Once the outline settles, the chart-topic stage (§Chart topics) gives those captures their targets — datums tagged to a plan are the ones the report is waiting on. `paper_qa_search_pro` is still the search of record for the academic slices of an industry report (technology evolution, evaluation) and patents are the IP channel, but they are de-emphasised, not displaced. Induce the outline from what came back: the Genre B skeleton in `references/report-format.md` is the expected shape, but drop a section the evidence does not support rather than pad it — an industry report that silently omits market size, players, or supply chain is incomplete. The ledger was initialised with `--genre industry` in step 2; that is what makes `check` warn `figures_industry_expected` if the report ships without a figure — the figures-expected rule is enforced by `check`, not just advised here.

Scout hits go in untagged — the outline does not exist yet. They land in `untagged_sources` until you tag or drop them.

4. **Triage free, then read the keepers properly.** Retire the drift first:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" drop --source 21 23 --reason "domain application, memory not the object of study"
```

A dropped source keeps its number — renumbering would repoint every citation — but leaves the reference list and every coverage count. (The ledger itself never renumbers; the delivered report's dense ascending numbers are assigned by `render --renumber` from the draft, and citing a dropped source in a draft is a hard error.) `drop` refuses a source a claim already relies on, and re-adding a source later revives it.

**Watch what the drop rate says about the probe.** A probe can return ten brand-new papers and still have failed: if triage throws eight of them away, the query matched a vocabulary that belongs to another field. `gaps` reports this as `drifting_probes`, separately from `low_yield_probes` — duplication and drift are different failures and have different fixes.

The fix for drift is to pin the concept, not to reword:

```bash
# 8 of 10 hits were retinopathy / wave-segmentation uses of Mamba, not LLM backbones
python3 "${CLAUDE_SKILL_DIR}/scripts/aminer_open.py" --api paper_qa_search_pro --params '{
  "query":"sparse expert routing in language model backbones",
  "query_type":"topic",
  "all_terms":["mixture of experts"],
  "exclude_terms":["segmentation","retinopathy","forecasting"],
  "year_from":2025}'
```

`all_terms` forces every result to contain the concept you actually meant; `exclude_terms` kills the domain vocabulary that hijacked the probe. That is what "change the retrieval axis" means in practice — reaching for a synonym instead buys the same ten papers again.

Then read in two steps, cheapest first:

```bash
# free, truncated abstract slices — enough to sort papers into clusters
python3 "${CLAUDE_SKILL_DIR}/scripts/aminer_open.py" --api paper_info --params '{"ids":["...","..."]}' \
  | python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" add --aminer

# ¥0.01 each, full abstract and keywords — required for anything a claim will cite
python3 "${CLAUDE_SKILL_DIR}/scripts/aminer_open.py" --api paper_detail --params '{"id":"..."}' \
  | python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" add --aminer
```

The ledger records how deeply each source was read as `depth`: `search` from a search response, `slice` from `paper_info`, `detail` from `paper_detail` — and `fulltext` above all three, the open-access original. A slice is truncated mid-sentence — about 190 characters against roughly 1,400 in the full abstract — so it tells you what a paper is about but not what it found. `check` warns with `cited_sources_without_detail` for any non-web source a claim leans on that never reached `detail`. At ¥0.01 a call there is no cost argument for leaving one there.

**Fulltext first — if the original is obtainable, read the original.** AMiner never serves paper or patent bodies, so `detail` is the API's ceiling, not the reading ceiling. For every source a claim will lean on, resolve the open-access original with your own web tools and read it: papers on arXiv (the abstract page, the HTML full text, the PDF, or the TeX source — whichever the host's fetch handles best; search by arXiv id from the record, or by exact title), patents on Google Patents (full claims and description; `patents.google.com/patent/<publication-number>` — the number is already in the ledger: `patent_detail` persists `pub_num` / `app_num` / `pub_kind`, the two number fields swap places between records, so take the ~9-digit one and build `CN{digits}{pub_kind}`), and any publisher open-access page in between. Then record the read:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" fulltext --source 12 \
  --url "https://arxiv.org/abs/2501.12948" --via arxiv-html
```

`--via` is one of `arxiv-pdf` / `arxiv-html` / `arxiv-tex` / `google-patents` / `publisher` / `other`. The ledger keeps no body text, so a number you lifted from the original must ride in the read's `--note` (e.g. `--note "loss 2.13 on MMLU; 37B active params"`) — that note is what the number-provenance check searches, and without it every fulltext-derived number reads as unsourced. When no open copy exists — paywalled, or the patent has no published full text — degrade to `detail` and say so: `fulltext --source 14 --unavailable --note "paywalled at IEEE"`; if a recorded read turns out wrong (the "open" copy was paywalled after all), `--unavailable` also undoes the read and restores the source's AMiner depth. `check` warns with `cited_sources_without_fulltext` for every cited paper or patent that is neither read at fulltext nor marked unavailable: it cannot tell "could not" from "did not", and neither can a reader, unless the downgrade is recorded. Reading the original is free — it goes through the host's web tools — so there is no budget argument against it either.

5. **Judge the effort tier, then induce the outline from what survived.** The complexity judgment is yours; the caps that follow are the engine's, and they bind from registration on. `simple` (2 directions × 1 rerun each × 3 rounds) fits single-point or factual questions; `moderate` (3 × 2 × 6) is the default for standard comparisons and small reviews; `complex` (5 × 3 × 10) fits wide multi-dimensional surveys. Register with the reason you judged it:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" tier --level moderate --reason "对比型问题，两条技术主线"
```

From then on the engine refuses what exceeds the tier: `outline set` / `outline add-top` past the direction cap, `round` past the global or per-direction caps. A round registered `--wasted` (the query the API did not understand, the aborted axis) is on record but not charged against the caps. Re-judging needs `--force` and the change is kept on record. Without a registered tier nothing is clamped and `check` warns `tier_missing`.

Then group the remaining titles and abstracts into 2–4 top-level sections, each with 2–4 subsections (a `complex` tier may justify up to 5). Every top-level section carries exactly one `"kind":"disagreement"` subsection — that is where counter-evidence and unresolved tension go, and it is what replaces the old practice of picking opposing angles up front. Each section cites the probes it was induced from. A section added mid-run (a genuinely uncovered dimension) is `outline add-top --title …`, and the tier cap applies there too.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" outline set --json '[
  {"title":"Memory architectures","from_probes":["p1","p2"],"children":[
    {"title":"Hierarchical and multi-store designs"},
    {"title":"Write-time consolidation policies"},
    {"title":"Disagreement: explicit memory vs long context","kind":"disagreement"}]},
  {"title":"Evaluation","from_probes":["p3"],"children":[
    {"title":"Benchmarks in use"},
    {"title":"Disagreement: contested benchmark validity","kind":"disagreement"}]}]'
```

Section ids are assigned by the script, never by you. `outline set` refuses a section with no `from_probes`; if you genuinely could not scout, pass `--allow-unscouted` and the report must disclose it.

Each top-level section will carry a **`target_chars` writing target** — the length its prose should reach, in Chinese-character equivalents (a Latin word ≈ 1.7), assigned at writing time (next paragraph). **The total comes first, anchored to upstream's default carried whole** — anchor and qualifier together, never the number alone: with no user length given, plan **normally 2–3 万字当量, at most 5 万, thoroughness over padding** (prompts/report.py:854). The material's job is to **distribute that total across sections, never to cap each section at a fraction of its pile**: 各章不必等长——素材厚、论证重的章多写，素材薄的章少写 (:855). An even split is one defect (five sections at ~4,000 over material ranging 2,400–49,800); **the arithmetic shave is the other** — reading `material_chars` and targeting each section at "roughly half its pile" uses the pile as a cap instead of a distributor (measured: a run holding 65.5k of material, its own stop reason calling the pile 充足， totaled its targets at 11,600). **Lowering the total has exactly one legal reason** — the material cannot cover the topic, and then that is named in 局限； when material is too thin to carry the default, the answer is more retrieval (the pre-writing checklist), never a smaller target. Patent-corpus material is not a small cap either: its prose form is the 格局 narrative — application trends, who is filing, which technical directions — a section sitting on 40k of corpus material has a story to tell, not a 2,800-char corner. `check` observes both broken couplings: `write_targets_over_material` (target above the pile) and `sections_under_targeted_vs_material` (target under a quarter of it — the inverted anchor). This is the difference between a floor and a goal — the 300-unit subsection floor stops a report from collapsing; the targets are what make it substantial. If the user stated a length, convert it to 字当量 (one page ≈ 700) and register it with `--length-budget` (the engine clamps at 80000); the section targets should sum near it. A missing target is a warning (`sections_without_target_chars`), not a refusal.

Upstream assigns its chapter targets at report time, over the full material pile — carry that timing over: Round 0 registers the outline **structure**; the targets are assigned **at writing time**, after retrieval, once `render --material` has put each section's material volume on the desk (it prints the volume with or without a target — the volume is the input targets are assigned from). Re-register them with `outline set --force` over the identical structure: section ids are positional, so section tags, rounds and claims all survive, and a registered `--length-budget` persists untouched. Assigned at that moment, by the material each section actually holds, a target above its material should not arise; `check` warns `write_targets_over_material` when one does, and upstream's rule decides the response: the target follows the material — re-base it, never pad. The mirror defect — a target far *under* the pile — is the inverted anchor (see above): material distributes thickness, it does not license a shave; `check` observes it as `sections_under_targeted_vs_material`. Retrieval is never driven by a length number (upstream's evaluator sees no length at all): if the material cannot carry the target, write to coverage completeness.

6. `--dry-run` the paid chain for the rounds ahead and check the total against the budget.

## Patents (industry-report tasks only)

Apply this section only when the task framing identifies an industry report. Literature reviews and other genres skip it entirely — patents are not mandatory there. The task framing comes from the prompt that started the run; if it does not say "industry report", do not run patent probes.

An industry report treats patents as a second evidence channel alongside papers, not as a standalone chapter. Patents are mandatory for an industry report — wherever they strengthen the analysis (technology ownership, enterprise portfolios, filing trends, or anywhere else a claim leans on technical reality), retrieve and cite them. Do not decide in advance which sections will use patents; scout the field first and let the outline follow where the patent evidence actually lands, the same rule as paper probes.

- **Round 0 scout.** In addition to the 3–4 paper probes, run 1–4 `patent_search` probes (free, no budget impact) — at least one is mandatory, and more are warranted when the field splits along distinct technology lines or applicant camps. `patent_search` exposes only `query`/`page`/`size`, so unlike paper probes you cannot steer it with structured filters — the only honest way to make a second patent probe worth running is a different technology line or applicant direction, not a reworded query. One probe with `size: 20` on the core technology term is the floor; split into 2–4 only when the scout reveals genuinely distinct technology branches. Register each like any probe:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" probe --axis patent --via patent_search \
  --query "autonomous driving lidar"
python3 "${CLAUDE_SKILL_DIR}/scripts/aminer_open.py" --api patent_search \
  --params '{"query":"autonomous driving lidar","size":20}' \
  | python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" add --aminer --probe p4
```

A `patent_search` result carries `paper_id`-style `id`, `title`, `title_zh`, `inventor_name`, `app_year`, `pub_year` — enough to triage, not enough to cite a finding. Page size defaults to 8; raise `size` (max 100) and take `page: 1` when the first page comes back full — the channel offers no sort by quality or date (papers can be ordered by citations or year; patents come back by relevance only), so a wider candidate pool is the one retrieval-side quality lever there is.

- **Each round, retrieve.** Run `patent_search` (free) as a dual source alongside `paper_qa_search_pro` on any axis where patent evidence is relevant — do not pre-assign patents to fixed sections; let each section's evidence needs decide. Separate patent probes by technology term or applicant, not by rewording — the same rule as paper probes.

- **Read what you cite.** `patent_info` (free) triages a batch of IDs; `patent_detail` (¥0.01) gives the full abstract, assignee, IPC/CPC, and dates. A claim that leans on a patent must reach `patent_detail`, the same way a paper claim must reach `paper_detail` — `check` warns with `cited_sources_without_detail` for either. And `detail` is the floor, not the ceiling: patents are public documents, so read the original on Google Patents (claims + description) and record it with `fulltext --via google-patents` before a claim leans on it; `--unavailable` only when there is genuinely no published copy.

- **Quality screening — the channel cannot sort, so you must.** `pub_kind` and `assignee`, both persisted by `patent_detail`, are the quality signals: a granted invention (`pub_kind` ending B) sat substantive examination; a published application (A) has not yet; a utility model (U) never does — and an application with no assignee has no organisation staking its claims. Screen the widened pool by tier before spending detail calls: granted and corporate-assigned patents first; utility models and unassigned applications serve corpus statistics and supplementary colour, not load-bearing assertions. Two engine surfaces hold that line: `check` warns `claims_weak_patent_sole_support` when a quantitative claim's only anchor is a utility model or an unassigned application, and `render --renumber` returns `weak_patent_numbers` — prose sentences whose every citation is a weak patent — because engineering parameters ride into the report from fulltext notes, under claims that stay qualitative multi-source aggregates. Cross-validate the number, or label it in the report as one filer's design assertion; the limitation section is a legitimate answer, silence is not.

- **Enterprise portfolios.** A `patent_detail` call persists each patent's `assignee` / applicant (the primary rights holder), so a per-assignee corpus chart assembles straight from the ledger — `figure add --from-source-metadata --field assignee --sources … --type hbar` — once the detail calls have run. For a *named* organization's full portfolio, `org_search` (free) → `org_patent_relation` (¥0.10) still retrieves its patent set with the org dimension intact:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/aminer_open.py" --api org_search --params '{"orgs":["华为"]}'
python3 "${CLAUDE_SKILL_DIR}/scripts/aminer_open.py" --api org_patent_relation \
  --params '{"id":"<org_id>","page":1,"page_size":100}' \
  | python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" add --aminer
```

Otherwise record the assignee in the claim `--text` or a web-source `note` at retrieval time; never reconstruct it from memory.

- **Filing trends.** `evidence.py` coerces a patent's `app_year` / `pub_year` string and `app_date` / `pub_date` epoch into an integer `year`, so a filings-per-year chart assembles from the ledger — `figure add --from-source-metadata --field year --sources … --type bar`. A patent added by `patent_search` alone (scout, no detail call) ships a year only when its `app_year` is present; reach `patent_detail` for any patent you intend to chart.

## Chart topics: plan after the outline, then retrieve until sufficient

The outline is the last input that changes shape — the moment it settles, decide the figures. Walk each section and ask two questions: does this section carry a quantitative question a chart would answer better than prose, and is data for it plausibly public? Where both hold, record a figure plan — `evidence.py figure plan --section <id> --topic <the quantitative question> [--type]` — and from then on the topic's numbers are a retrieval objective: capture each as a datum tagged to the plan (`datum add --plan fpN`) the moment you read it, and chart the plan when its data composes a complete chart — the ≥3-datum countdown is the engine's floor, not the standard (`references/chart-guide.md` §Data).

The charting manual — the `--type` selection matrix, the ≥3-datum sufficiency loop and abandonment, the four registration paths, the thin-data fallback ladder, rendering with `chartrender.py` and the record-back, and the chart-topic subagent's rules — lives in **`references/chart-guide.md`**. Read it when planning chart topics and before registering a figure; a chart-topic subagent's assignment includes it as the operating manual. **Plans are dispatched, not just recorded**: a host that can spawn subagents gives each open plan one chart-topic subagent at plan time — all plans in one concurrent batch, each assignment carrying a retrieval budget of at least 10 calls before "no public data" is sayable (the rules in `references/chart-guide.md` §Who charts) — the same tier and the same contract as the reading subagents and the cold judges: brief in, record JSON out, and the controller (the ledger's only writer) enters the records and runs the render chain; parallel plan-owners are safe because no subagent touches state, so dispatch them concurrently, never one by one. The in-session loop is the no-subagent fallback, and it declares itself (`figure add --charted-by controller --charted-reason …`; an undeclared figure warns `figures_charting_undeclared`, and Appendix C reports each figure's mode). Plans and the section loop share the same rounds — a round's probes serve whatever is open: sections short of evidence, and plans short of datums. Neither retires the other.

## Each round (rounds capped by the registered tier)

### 1. Retrieve

Per round, run at most **2 paid `paper_qa_search_pro` calls** plus any number of ¥0.01 `paper_search_pro` calls, and at most 3 native web calls, spread across sections that still need evidence.

The cap sits on the ¥0.70 endpoint because that is where the money goes. A real run spent ¥6.09: ¥5.60 on eight searches and ¥0.49 on forty-nine full abstracts. Rationing abstracts protects pennies while an unnecessary search costs seventy times as much.

**Two searches in the same round must be semantically distant: a different outline section *and* a different retrieval axis** — time window, subfield, named entity, venue, or method-versus-critique framing. Rewording the same question is not a second search.

This is not a style rule. In a real run, two near-synonym `paper_qa_search_pro` queries at ¥0.70 each ("architectures for X" and "benchmarks for X") returned 10 results of which 9 were identical: ¥0.70 bought one new source. `gaps` reports this as `low_yield_probes`. When it fires, change the axis — do not retry the phrasing.

Route by query shape, not by habit:

- **Topic or multi-filter search** → `paper_qa_search_pro` at ¥0.70, the default. Send the query in `query_type: "auto"`; drop to `"topic"` only for literal term matching, and pin the concept with `all_terms` when you do. Page size is fixed at 10 and search results carry no abstract, so pair it with `paper_info`, then `paper_detail` for whatever a claim will cite.
- **Structured filter** (author / org / venue / keyword, with citation or year ordering) → `paper_search_pro` at ¥0.01, when you already know exactly what you are filtering on. **After the scout you usually do know** — establishing the field's controlled vocabulary is what the scout was for, so later axes should reach for the ¥0.01 endpoint first and escalate to Pro only when a single filter cannot express the query. It matches terms, not questions: a single controlled term for `keyword`, a two- or three-word phrase for `title` / `abstract`. A sentence answers 200 with `"msg": "no data"` and still bills — `add --aminer` reports that as `paid_calls_without_hits`.
  Short is not the same as precise. Use a term only the target literature uses: in a real run `keyword=agent memory` returned 2004–2014 multi-agent traffic simulation because that phrase predates LLM agents, while `keyword=agentic memory` returned the intended work. A drifting probe tells you about the field's vocabulary; it is not a reason to spend again.
- Free discovery endpoints first for entities; see `references/api-reference.md`.
- Native `WebSearch` and `WebFetch` are the source of record for anything AMiner does not hold: first-party project pages, model or standard documentation, release notes, benchmark leaderboards, current news. Use `WebFetch` on the specific page rather than trusting a search snippet. If native web tools are unavailable, continue AMiner-only and record that limitation now, not at the end.

### 2. Record

**Pipe results in untagged, then tag the keepers by number.** A search returns relevance and noise together; `add --aminer --section 3.2` would tag the whole batch, and noise tagged into a section inflates that section's coverage with papers no claim will ever cite.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/aminer_open.py" --api paper_qa_search_pro \
  --params '{"query":"how is agent memory evaluated","sort":"balanced","year_from":2024}' \
  | python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" add --aminer --probe p3

# read the titles, then place only what belongs
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" add --section 2.1 --json '[{"kind":"paper","id":"<id>","title":"..."}]'
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" drop --source 49 61 --reason "off topic for this question"
```

Re-adding a source that is already in the ledger merges the new section tag onto it — that is the intended way to place a hit after the fact. If a bulk add over-tagged, `evidence.py untag --source N --section 3.2` removes just that tag.

Web evidence is recorded the same way — and **put the figures you are going to cite into `note`**. A web source stores only what you record; a number lifted from a fetched page and never written down cannot be checked by anything afterwards, and `check` will flag the claim as `claims_with_unsourced_numbers`:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" add --via WebFetch --section 2.2 --probe p5 --json \
  '[{"kind":"web","title":"Benchmark documentation — metric definitions","url":"https://...",
     "note":"opened 2026-08-06; reports 66.3% on OSWorld, 89.4% on RLBench, 12% on real household tasks"}]'
```

**A note is a digest, not a tag.** When a source survives triage, its `note` is the paragraph the writing stage will be served — upstream asks a **review-grade digest of 300–800 字** per finding, covering, as they apply: the background or problem, how the mechanism actually works (not just that it does), the key numbers **in the source's own wording**, the conclusion, and how it relates to the neighbouring sources. The one-line example above shows the number-provenance habit, not the whole note — the numbers ride *inside* the digest. `check` blocks delivery on **any live source with no note at all** (`sources_without_note` — zero exemption: a datum carrier or corpus-aggregation source needs its note too; read it or drop it, keeping it unrecorded is not a state), and warns on a thin cited one (`cited_sources_note_thin`, under 300 字) — the measurement that motivated this: a real run held 63 live sources, 15 notes, median 263 chars, and was then asked to write a report from raw abstracts.

**Record at the moment of reading, batch by batch.** Upstream's reader cannot return from a pass without its digests — the record *is* the pass's output, written while the original is still in context. The equivalent here: read a batch of keepers, land their notes and claims, then move on to the next batch. Reading everything first and backfilling notes at wrap-up is the exact hop where material evaporates — by then the originals are out of context, and a source whose reading was never written down reads as never having been read. `check` blocks on every live source with no note (`sources_without_note`, zero exemption) precisely so that hole surfaces at the stop decision, not after — upstream gets the same property by construction; here the check is the construction.

**Who reads: reading subagents where the host can spawn them.** Upstream's reading is never done by the coordinator — its retrieval subagents read and return findings, and the finding's fields *are* the record; the coordinator never holds the originals. A host that can spawn subagents ports that shape; a host that cannot keeps reading in-session (the discipline above, unchanged). The rules that keep the delegated read honest:

- **One subagent per section-batch, spawned at triage time.** Upstream delegates one direction's pass to one reader who returns 3–6 findings; the port is one reading subagent per batch of keepers from one section (3–6 sources), spawned the moment the batch survives triage — the same moment L1 says "record now". The parent never sits on an unread pile.
- **The reader's assignment.** The subagent gets: the section's topic and the concrete gap this round hunts, the batch's source lines (ledger `n`, kind, title, URL, publication number), how to reach the original with its own web tools (the fulltext ladder — arXiv / publisher OA for papers, Google Patents for patents), and the recording disciplines verbatim (the 300–800-字 five-element note; verbatim 100–500-字 evidence passages; claims with their evidence). It does not get the whole research question or other sections' material — upstream's retrieval subagent likewise sees its direction instruction, not the study. This is about focus, not coldness: the reader is a worker with an assignment, not a judge.
- **The deliverable is the records, piped verbatim.** The subagent returns structured records — per source: the note (and the `fulltext` read when it opened an original); per claim: text + verbatim evidence + supporting source numbers — and the parent enters them through the existing commands exactly as returned (`add --json` merges the note into its source, `claim --evidence …`, `fulltext --source … --url …`). Rewriting the reader's words in transit puts the coordinator back between the reading and the ledger — the failure M14's verbatim `--batch` rule exists to prevent.
- **Failure: retry three times, then the parent reads.** A reader that fails, times out or returns garbage is retried up to three times (a parameter of this port, not an upstream number); still failing, the parent reads that batch itself or drops the sources with a reason. Never fabricate records to cover a failed reader — a source left noteless is exactly what `sources_without_note` blocks on, by design.
- **The roles stay separate.** The reading subagent records; the round-boundary cold judge verifies what was recorded; the parent dispatches, pipes and judges sufficiency. A session that reads and verifies its own claims is the self-judged tier and says so.

`add --aminer` reads the paid cost out of the response and accumulates it, so the running total is always in the ledger. A search that returned nothing usable still cost money — it shows up as `paid_calls_without_hits`, and a paid call you never piped through `add` needs `evidence.py spend --api <name> --cny <price>`.

A ledger full of padding is worse than a short one.

### 3. Read

- Free `paper_info` gives a truncated abstract slice for a batch of IDs; use it to triage before paying.
- Then buy `paper_detail` at ¥0.01 for every item the report will lean on (default: at most 50 across the whole task — an outline of four sections needs at least twenty-four, so a tighter cap just forces an overrun). A slice is roughly 190 characters and stops mid-sentence; the full abstract is around 1,400 and is where the actual findings are. `check` warns with `cited_sources_without_detail` for anything you cite without it.
- **Then go one deeper when the original is open: fulltext first.** For every cited paper or patent, resolve the open-access original and read it — papers on arXiv (HTML / PDF / TeX, by id from the record or by exact title), patents on Google Patents (claims + description, by publication number), or a publisher OA page — and record the read with `evidence.py fulltext --source N --url … --via arxiv-html|arxiv-pdf|arxiv-tex|google-patents|publisher|other`. The fetch costs nothing (host web tools, not AMiner). When no open copy exists, record the downgrade instead: `fulltext --source N --unavailable --note "paywalled at …"`. `check` warns with `cited_sources_without_fulltext` for a cited source that is neither read at fulltext nor marked unavailable — a silent degrade is indistinguishable from not looking.
- Both AMiner calls store their text in the ledger, so `evidence.py source show --source 12` gives you the abstract back later without a second purchase, and the citation checks have something to compare against. The fulltext itself stays in the host's context or scratch — the ledger records where it was read, not the body.
- Record what each source actually supports — and record, with each claim a citation will lean on, the **verbatim excerpt** it rests on (`--evidence`, repeatable). The excerpt must be the source's own words, a whitespace-insensitive substring of its stored text, **and a sentence fragment at least 8 characters long** — isolated characters or a bare number are substrings of almost anything and prove nothing (registration refuses them). Upstream's excerpts are **passages, not tags: 1–3 per claim, each 100–500 字** — a claim whose every excerpt is under 100 warns as `claims_thin_evidence`; the 8-character floor is the anti-degenerate floor, not the target length. A claim several sources support lists them all — upstream's finding carries every source it rests on, and the writer picks per clause. A quote lifted from an open-access original rides in the fulltext read's `--note` (the same rule as numbers), because the note is what the check searches. An excerpt that matches nothing is a paraphrase posing as a quote — `check` flags it and the claim is downgraded to background info (§ Verify at the round boundary):

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" claim --section 2.1 --supports 3 7 \
  --text "Reference-free LLM-judge metrics are the dominant reported evaluation method since 2024" \
  --evidence "reference-free LLM-judge metrics dominate reported evaluation" 
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" claim --section 2.2 --type interpretation --supports 3 \
  --conflict "source 9 reports the opposite trend" \
  --text "Judge agreement with humans is likely overstated on long-form answers"
```

A section's claims are the natural unit of work, so record them together rather than one subprocess at a time:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" claim --batch --json '[
  {"section":"2.1","supports":[3,7],"text":"..."},
  {"section":"2.2","supports":[3],"type":"interpretation","conflict":"source 9 disagrees","text":"..."}]'
```

`--batch` records what validates and reports the rest under `failed`; it exits 1 if anything failed, so nothing is silently skipped.

Mark analysis as `--type interpretation`. Never state an interpretation as an observation. A claim must name a section — a claim that belongs nowhere in the outline cannot be written anywhere in the report.

**When two sources disagree, record the tension on the claim** (`--conflict`), at the moment you see it. The disagreement subsection is where the tension surfaces in the report, but the tension itself lives on the claim — that is what `render`, `check` and the 局限 section quote. A 风险与争议 subsection written over claims with zero recorded conflicts is disagreement as decoration; `check` flags it (`disagreements_without_conflict`). Cross-validate with a third source, or report the disagreement explicitly — never smooth it over silently.

**Check the figures.** `gaps` reports `claims_with_unsourced_numbers` for any decimal or 3-plus-digit number in a claim that appears in none of the sources it cites. This is the one error that used to be invisible: in a real run two claims carried benchmark figures from a web page while citing papers, and only a manual reread caught it. Unit and language conversions land here too ("4 million" written as "400 万"), so read the finding before acting — but read it.

When a citation is wrong, withdraw the claim and record it again — the id stays reserved, so nothing renumbers:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" retract --claim c4 --reason "cited source 30, meant 32"
```

**Write the direction memo after reading deep.** A top-level section whose sources you read at fulltext deserves a memo — the depth layer between the originals and the claims, 600–1200 characters of mechanism, experiment setups, data tables, comparisons:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" memo --section 2 --text "该方向的深度底稿：核心系统如何做到（机制）、实验设置、关键数据、与邻工作的对比……"
```

You are the only one who has read these originals in full. The memo is where that depth survives the hop into evaluation and writing; what you do not write down here is lost at this hop, forever — a claim is one sentence, the memo is what lets the report say more than the claims. It is not bookkeeping: the writing surface hands the latest memo to the writer verbatim — upstream's phrase is a 深度叙述底稿，原样提供给报告撰写者, the section's narrative first draft. `check` warns `sections_without_memo` for a direction with no memo, and `memos_thin` when the latest memo is under 600 characters — a memo that short fills the slot without carrying the depth; the round-end signals read the memo (latest per section) to judge depth, not just breadth.

### 3b. Figure

Registering and rendering follow `references/chart-guide.md` §Register / §Render — the four registration paths from ledger numbers, the thin-data fallback ladder for a thin web harvest, `chartrender.py`, then `figure mark-rendered` to record the result back. The engine gates hold whoever charts: a sourceless figure blocks (`figures_with_no_sources`), every number in `data` must appear in a cited source (`figures_unsupported_numbers`), and a registered figure is not done until rendered and recorded back (`figures_without_render`).

### 4. Find the gap

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" gaps
```

Read the output as a work list:

**Blocking:**

- `sections_below_two_sources` → a top-level section has no evidence. Fill it or merge it into a neighbour.
- `unsupported_claims` → cite it or drop it.
- `figures_with_no_sources` → a figure's `data` cites no source (directly or via its claims). Add `--sources`, or drop the figure.
- `figures_in_unrendered_section` → the figure's `--section` is not in the outline. Re-tag it or drop it; a figure with nowhere to live cannot appear in `render`.
- `spend_over_hard_limit` → stop and hand over what you have.

**Warnings, in rough order of what they cost you:**

- `drifting_probes` → the probe returned new work, but triage threw most of it away: the query matched another field's vocabulary. Pin the concept with `all_terms` and cut the noise with `exclude_terms`. Ignoring this is how a whole subfield ends up with no evidence.
- `low_yield_probes` → that probe rephrased an earlier one. Change the axis.
- `paid_calls_without_hits` (reported by `add --aminer`, not by `gaps`) → you paid for a query the API did not understand. Shorten the term; do not record the topic as empty.
- `sections_from_single_probe` → one query fed a whole section; its blind spots are the section's blind spots. Add a distant axis.
- `claims_with_unsourced_numbers` → a figure in the claim is in none of the sources it cites. Fix the citation, or record the figure in the web source's `note` where it came from.
- `figures_unsupported_numbers` → same check, applied to a figure's `data` blob: a number in the chart appears in none of its sources. Fix the `data` or the `--sources`; like the claim version, conversions can false-trip it, so read first.
- `figures_without_render` → a figure is registered but not yet `mark-rendered`. Run `chartrender.py`, then `figure mark-rendered`, or drop it before `--final`.
- `figures_over_budget` / `sections_over_figure_budget` → more than 6 figures, or more than 2 in one section. Drop the weakest; a report clotted with charts reads as padding.
- `figure_plans_thin` → an open chart topic still short of 3 tagged datums. This is the topic-driven retrieval work list: probe for that topic's numbers (number-dense doc types first), and capture each as `datum add --plan fpN` the moment you read it.
- `figure_plans_unfulfilled` → a plan has ≥3 datums and no figure. Stop retrieving — chart it (`figure add --from-datums … --plan fpN`).
- `figure_plans_abandoned` → topics given up with a recorded reason. Not actionable — but quote them in 局限; Appendix C lists them too.
- `figure_plans_industry_expected` → a Genre B run planned zero chart topics. The outline is settled; walk it and decide where a figure is needed and insertable.
- `figure_code_divergence` → a B script's `code_path` holds literals that look like data but are not in the registered `data`. Hardcoded values defeat the data↔source gate; pull them from `data` on stdin.
- `subsections_below_two_sources` → write it thin and say so, or merge it up. Do not pad it.
- `sections_without_claims` → you retrieved for it but concluded nothing.
- `untagged_sources` → Round 0 scout hits you never placed. Tag them into a section or `drop` them.
- `cited_sources_without_detail` → a claim leans on a paper you only saw the title or a slice of. Buy the ¥0.01 detail or narrow the claim.
- `cited_sources_without_fulltext` → a claim leans on a paper or patent whose open-access original you neither read (arXiv, Google Patents, publisher OA — `fulltext --url … --via …`) nor marked unavailable (`fulltext --unavailable`). Reading the original is free; only a paywalled or unpublished original justifies stopping at the abstract — recorded, not silent.
- `sources_without_probe` → provenance is missing, so the overlap analytics are blind.
- `single_source_claims` → find an independent source or downgrade the claim.
- `claims_weak_patent_sole_support` → a quantitative claim's only anchor is a utility model (never substantively examined) or an unassigned published application. Cross-validate with a second anchor, or say in the report that it is one filer's design assertion. `render --renumber`'s `weak_patent_numbers` carries the same rule to prose sentences the claim-level check cannot see.
- `unresolved_conflicts` → resolve with a third source or report the disagreement explicitly.
- `uncited_sources` → use them or drop them.
- `web_sources` of 0 on a question about current practice → the picture is probably stale.

### 5. Read the signals, then decide

The round ends the way a mature harness ends a wave: read a code-computed signal surface, decide against it, and record the decision. Whether the evidence is sufficient is never a feeling — every number the decision rests on comes out of the engine:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" signals
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" round --why-stopped "方向2仍缺机制细节；轮预算内" \
  --direction 2 --probe p5 p6 --next-query "Switch Routing 的负载均衡损失具体形式"
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" verify --batch --json '[…]'   # this round's new evidenced claims — before signals/decide, so the decision sees the downgrades
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" decide --action continue --reason "方向2证据不足，补一轮机制级深挖"
```

`signals` prints the evaluator input surface: the tier and its caps, per-direction source diversity (the single-source dependency check), evidence quality (verbatim-evidence coverage, verify downgrades), the citable scholarly count against the academic ≥15 soft target, the last five decisions, the last round's summary, unresolved conflicts, and the round/direction budget left. Blocks you never registered print as **not recorded** — never a misleading 0. `round` closes the round: which directions it served (counted against each one's rerun cap), which probes ran (their yield is already in the ledger), why it stopped — the one signal the engine cannot compute — and the concrete gap the next round should hunt. `decide` logs the call itself, so the next `signals` replays the last five decisions.

**Decision rules** — these are the harness evaluator's rules at their original strength, renamed for this ledger (claims for findings, top-level sections for directions, `rerun`/`add-top`/定向补搜 for its rerun_direction / add_direction / patch_search). Every line is load-bearing:

- **The report-writing stage has no retrieval ability.** The final report can only use what the ledger already holds. If a piece of information is necessary for the report and currently missing, fill it now — a rerun, a targeted patch search, or a new section — never "look it up while writing" and never leave the gap for the writing stage to handle.
- **Match effort to the tier.** For a `simple` question: if the current claims already answer it, decide `stop` as early as possible — do **not** grow a simple question by adding sections; if a key gap remains, prefer a rerun of an existing section over a new one. For a `complex` question: opening new dimensions with `add-top` is legitimate, still within the tier caps.
- **Judge sufficiency on breadth and depth together.** The claims digest shows breadth — are the question's main dimensions covered? The memos show depth — does each direction's narrative carry concrete data, methods and comparisons, or does it stay at the surface? Web-snippet-grade claims plus a memo with no academic citations or concrete numbers is *insufficient* — keep going. Judge on what was *digested*, never on what was retrieved: `sources_without_note` names the keepers nobody wrote a word about (and blocks `check` until each is read or dropped), and a direction called "sufficient" while its sources carry no notes is a direction nobody read.
- **An empty pass never reads as sufficient.** Upstream forces `needs_more` when a pass produced no findings or none with sources; here a round whose probes kept nothing shows as `rounds_without_yield` — its `--why-stopped` must say so plainly, and the next decision either retries with a new query or closes honestly with the gap named. Never let "we ran the rounds" stand in for "the evidence is there".
- **The verify stats are a reliability signal, not decoration.** Many downgrades, or a high share of claims without verbatim evidence, means this round's statements outran their evidence: rerun the direction to open the key sources at fulltext and add verifiable evidence, rather than stopping. This is why the round's new claims are judged at its close, before this decision — the evaluator that reads the damage must be one that can still order the repair.
- **Progressive deepening first.** Whether a direction keeps being dug is your call. When the just-closed round's `--next-query` names a concrete gap, the next round hunts exactly that gap, on the same section, reusing those queries (with a better strategy in the instruction if you have one) — not a new direction.
- **Mechanism-level digging.** If a direction's memo holds only abstract-level facts about its core papers — what was proposed, what was concluded, but no method detail, no experiment setup, no data tables — and the direction matters for the question, rerun it with an instruction that demands the mechanism from the fulltext: *how* it is done, the experimental setup, the key numbers — not abstract restatement.
- **Single-source dependency.** Check every direction in the diversity block: claims resting on fewer than 2 distinct sources are one source's retelling. Rerun to hunt **independent third-party corroboration or an opposing view** — change the query, change the source class — rather than stopping. (The "all weak classes" arm of the check fires for the academic genre, where web-only backing means the peer-reviewed literature was never opened; for an industry report the web is the spine — institutional pages, rankings and policy texts are first-class evidence there, and honesty rides on the number checks instead.)
- **Lightweight contradiction critic.** Actively scan the claims for conclusions that contradict each other (two claims giving conflicting readings of the same fact), and for question sub-dimensions with no coverage at all. Resolve those first — cross-validate the contradiction with a rerun, fill the blank with a new section — before stopping.
- **Do not repeat history.** The last five decisions are in the signals. Do not re-issue a direction or a near-identical instruction that already ran, unless that round clearly failed (it was marked wasted, or returned almost nothing).
- **Every action carries queries and an instruction.** A rerun without specific queries, an instruction without the concrete gap, is not an action. "Look deeper" is not an instruction.
- **A stop reason disposes of every standing warning.** The `gaps`/`signals` at stop time name what is still open — single-source claims, fragment-only evidence, unresolved conflicts, abandoned figure plans. The stop reason addresses each with one of three dispositions: fixed this round (say how), accepted after weighing (give the grounds), or handed to the report (named in 局限 or the methods prose). A reason that recites only the met bars — cited share, verifies passed, figures rendered — is selective: the decision record is the only audit trail for "why stop here", and *accepted after weighing* and *never looked at* must not leave the same trace.
- **Stop** when `gaps` shows no blocking items and the signals show no direction below sufficiency — or when the tier cap refuses further rounds: then write the report from what the ledger holds. Registering `decide --action stop --reason …` is the formal end of retrieval.

The older heuristics still hold inside this frame: a search that returned nothing useful gets one reformulation **on a different axis** and then moves on; a section still empty after two attempts merges into a neighbour or is declared a gap — never more searches for symmetry; an ambiguous entity goes to the user with candidates, never details for each.

## Verify at the round boundary, finished before writing

Two gates stand between the ledger and the report. Both are engine-enforced; the second takes your judgment as input.

**Verbatim evidence — the engine checks it.** Every claim a citation will lean on carries at least one verbatim excerpt (`claim --evidence`, recorded at claim time). The engine checks each excerpt, whitespace-insensitively with typographic variants folded, against the supporting source's stored text; one that matches nothing is a paraphrase posing as a quote. `check` reports these as `claims_evidence_not_verbatim`, `render --final` marks the claim `_(证据非逐字——背景信息，不得引用)_` / `_(evidence not verbatim — background info, do not cite)_`: the claim keeps its place in the ledger as background material but must not carry a citation. The fix is always the same — quote the source's actual words, or retract the claim. The verdict is recomputed live, so a re-`add` that merges a richer abstract in can clear it without touching the claim.

**Citation faithfulness — you judge, the engine gates.** The verbatim check proves the quote is real; it cannot prove the quote *supports the statement* — the number is from a different table, the claim names entity A while the source measured entity B, the year is off. Walk the claims one by one before wrap-up and record the judgment:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" verify --claim c3 --unsupported --confidence 0.8 \
  --reason "数字来自另一张表，非该结论所引实验"
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" verify --batch --json \
  '[{"claim":"c1","supported":true,"confidence":0.9},
    {"claim":"c2","supported":false,"confidence":0.8,"reason":"时点错位：数据是 2023 的"}]'
```

The scale is **疑罪从无** — benefit of the doubt. Only flag what is *clearly* contradicted: a number the source does not contain, a claim about entity A citing a result about entity B, a time-point mismatch, a causal claim the source only correlates. "I would have phrased it differently" is not a contradiction; when you are not sure, say so with a low confidence instead of forcing a verdict.

Write the reason **per claim, in its own words** — what you checked and what matched. The engine watches reason diversity: an unsupported verdict without a reason is refused outright, and a single template string stretched across the batch shows up as `verify_reasons_boilerplate` (40 identical "数字/实体/时点均一致" reasons is the signature of stamping, not checking — a real pass produces varied reasons because claims fail in different ways).

What happens next is not your call, and that is the point. A "not supported" below confidence 0.6 reads as *not sure* and the claim passes (recorded inconclusive). One verify batch never downgrades more than half its claims — a systematically harsh judge cannot wipe the reference list — while a lone confident hallucination still cannot survive (the cap's floor is 1). Downgraded claims are marked `_(核验降级——背景信息，不得引用)_` in `render --final`, excluded from the citable counts, and reported by `check`; Appendix C carries the pass/downgrade/inconclusive distribution as a methods fact. `check` warns `claims_awaiting_verify` while claims with recorded evidence still lack a judgment — the report is not ready until that list is empty. Write prose against a downgraded claim's *topic* if you must, but never a citation on its assertion.

**When: at the round boundary, not saved for wrap-up.** Upstream runs the verify pass at every wave boundary, *before* the evaluator — deliberately, so that downgraded findings enter the evaluator's source distribution as 「无有效来源」 and naturally trigger a rerun to replace them (orchestrator.py: the verify call sits ahead of `evaluate_actions` at each wave). A verification that only happens after retrieval is over can only downgrade; it can no longer repair. The port: **at each round close, judge that round's new evidenced claims** (same cold form the run uses), *then* run `signals` and `decide` — the decision sees this round's damage while budget remains to act on it, and the next round's `--next-query` can name the replacement hunt. The wrap-up pass is the tail that empties whatever `claims_awaiting_verify` still lists, not the whole pass.

**Who judges: cold subagents where the host can spawn them.** Upstream's verify is an independent judge LLM whose entire world is built by code — the claim, its verbatim evidence, the sources' titles, and nothing else; it never sees the research question, the other claims, or the orchestrator's expectations (prompts/verify.py: `build_faithfulness_verify_prompt(detail, evidence_blocks)` — that is the whole input). Hosts that can spawn subagents reproduce that coldness; hosts that cannot keep the self-judged form. The rules that keep the cold form cold:

- **The judge's input is exactly the claim and its evidence.** Per claim: the claim text (upstream caps it at 1200 chars into the judge), each verbatim excerpt (capped at 1500 chars each), the supporting sources' titles and ledger numbers — nothing else. No topic, no question, no section plan, no other claims, no expectation of the verdict. Adding any of those is the confirmation bias the cold judge exists to remove.
- **One judgment, one context.** Upstream makes one LLM call per finding — the judge never sees sibling claims (concurrency 12, 30 s per call). The faithful shape here is one subagent per claim; a subagent judging a batch sees its siblings and can rubber-stamp within the batch — the engine's reason-diversity check catches the stamping, but the isolation loss is yours to declare, so batch only for cost and keep it small.
- **The judge works to the same scale** — 疑罪从无, only clear contradictions or fabrications, per-claim reasons in its own words. Paste the scale into the judge's task, not your conclusion about the claim.
- **A failed judge is not a pass.** Upstream's timeout/failure/malformed-output fallback passes best-effort but is recorded *inconclusive* — "did not get verified" must never masquerade as "verified and passed". Here: a claim whose judge failed, timed out or returned garbage is recorded `--unsupported` with low confidence and a reason saying the judge failed — the engine reads that as 未定论, the claim passes, and the failure stays visible. Never re-judge that claim yourself to "fill it in".
- **Judgments enter the ledger verbatim.** The judge returns the `--batch` JSON array (`claim`/`supported`/`confidence`/`reason`); pipe it into `evidence.py verify --batch` unchanged — re-typing or "adjusting" numbers by hand puts the coordinator back between the judge and the ledger.
- **All or nothing per run** (a guard this fork needs; upstream has only one judge form). Every evidenced claim is cold-judged, or the run is self-judged — mixing the two calibrates confidence on two scales in one report.
- **The method prose states which form ran** (same fork guard): "each evidenced claim was judged by a context-free subagent against its verbatim evidence" / "claims were self-judged by the same session that recorded them".

The declared gap: upstream's judge runs inside a code-enforced bounded batch (semaphore, hard timeouts); a host subagent has neither, so batch size and patience are prompt discipline here. The engine gates (0.6 / half-cap / four-state) apply to the judgments unchanged — the gate does not care who judged.

## Write from material, not from memory

A report written from one-line claims comes out one line thick. The ledger holds far more than the claims: verbatim evidence, the notes you took while reading originals, the memos. Before writing, run the one command that puts all of it on the desk:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" render --material
```

Per section it prints the **material the section actually holds** — and, once a target is assigned, the target next to it (a target that outruns its material is a broken coupling, not a writing ambition — the target follows the material: re-base it on what the section holds; `check` warns `write_targets_over_material`), the **material blocks** — each claim with its `[@n]` citation marks, its verbatim evidence excerpts, and the supporting sources' notes (the notes are the detail channel: the mechanism, setups and numbers you captured while reading) — the **re-read list**, the **uncited pool**, and the latest **memo**. Six disciplines follow from it:

**Write one section at a time.** Upstream generates its report chapter by chapter: each chapter's prompt is assembled by code from exactly that chapter's material, so "the material was on the desk" can only mean "it was in the prompt". The port: write the draft top-level section by top-level section — before section *k*, take only its material blocks, its uncited pool, its re-read list and its target; write it; move to the next. A one-pass draft over the whole-pile view is the shape that leaves a section's material half-written (measured: a section holding 7,889 chars of material delivered 3,308 while the pile sat in one long view).

**Compose from the material blocks, not from the claim lines.** The claim is the skeleton; the paragraphs carry what the notes and evidence hold. A claim restated with a citation glued on is a defect even when it clears every gate. Development is depth per item, not coverage by listing: each core item the section leans on gets at least one full paragraph (3–5 sentences — the problem, the mechanism, the numbers, the comparison); minor items merge into one sentence. Restate source wording in your own words — a verbatim quote only for the classic, unrewritable sentence, at most one per section.

**Re-read the originals on the re-read list before writing that section.** The engine ranks them by how many of the section's claims cite them (at most 5 per section; an original already listed for an earlier section keeps its slot at half weight; across the whole report at most 12 distinct originals, and over that the one-shot slate at the end names the priority 12). The ledger stores no document bodies — the note is your compressed record, and compression is exactly what the re-read undoes: the sentence around the number, the mechanism the abstract skipped, the table the claim flattened. Open the originals with your web tools, then write. In the academic genre a non-scholarly original on the list carries the background-only tag — context for framing, never a citation.

**The uncited pool is citable — read it or drop it.** The pool lists every source tagged to the section that none of its claims cites. The citable pool is the whole ledger, not the claim set: citing any live source is engine-legal, and a run's references otherwise collapse to exactly its claim set (measured: report citations == claim supports, entry for entry). A pool source you can use: read it first, record what you lean on (claim + evidence as always), then cite. A pool source you cannot use: `drop` it with a reason. Retrieval that never surfaces anywhere is spend for nothing.

**Corpus sources are pool members too — there is no figure-only class.** Upstream's every finding carries a source the prose cites (measured: 68/68 in its report); a fork run left 16 patents inside a chart's source list and out of the reference list entirely. The prose form of corpus material is the 格局 narrative: the section hosting an aggregation chart names its constituents in the sentence that interprets it — application trend, who is filing, which technical directions, cited — never a chart fed by 18 invisible patents.

**Cite the load-bearing sentence — one source, one or two marks per section.** Upstream's first principle of citation frequency: the mark goes on the sentence carrying that source's key fact, number or conclusion, not on every sentence it vaguely backs. General narration, transitions and your own synthesis carry no mark — but no section goes entirely uncited. A statement resting on one source cites that source; a material block's marks list everything available, and you select what each clause actually rests on. Full rules in `references/report-format.md` §Citations.

**Write, measure, continue — do not deliver a half-target report.** After `render --renumber`, the payload's `length` block reports the total against the registered targets (±20% tolerance) **and every `##` section's length**. Pair each report section with its outline target (you wrote the draft; the engine measures but does not pair). A section beyond tolerance while its material holds more is not finished: go back to its material blocks and the uncited pool, develop it further, re-run `render --renumber`, and measure again — the equivalent of upstream's truncation-continuation rounds. Deviation is recorded, never rewritten by the engine; the continuation is yours.

The length observation at delivery is record-only: `render --renumber` reports the body's length against the registered targets (±20% tolerance, both directions, body only) and persists it into the ledger as `length_report` — the port of upstream's post-delivery deviation log (只观测、不重写：篇幅是目标不是硬约束，为凑字数重写正文既贵又容易注水/砍论证， report.py:810-841), read at post-run review and by the next run's target-setting, never gating delivery. Nothing rewrites prose for length — padding to hit a number is the enumerated-list defect wearing a longer coat. Write to the target because the material supports it; when the material cannot carry the target, coverage completeness governs — retrieval answers missing content (the pre-writing checklist), never a length number.

## Wrap-up

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" verify --batch --json '[…]'   # the tail of the faithfulness pass: rounds verified their new claims at close, this empties claims_awaiting_verify
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" check           # exit 1 means not report-ready
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" render --final   # the ledger view: numbering, claims-per-section, ledger source numbers — NOT the report body
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" render --material   # the writing surface: per-section material volumes, material blocks, re-read list, uncited pool, memo — write from this
# assign target_chars NOW (upstream's report-time timing): outline set --force over the identical structure — ids are positional, tags survive; TOTAL FIRST (normally 2–3 万, 5 万 at most, or the user's budget — thoroughness over padding), material then distributes it (各章不必等长，厚节多写薄节少写 — a distributor, never a cap: no arithmetic shave to a fraction of each pile); never retrieval for a length
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" render --renumber --draft <draft.md> --out <report.md>   # delivers ascending [N] from your [@n] draft (written section by section) + cited-only bibliography + citation-map sidecar (+ length deviation recorded into the ledger as length_report — observation only, never a gate)
# out-of-tolerance section with material remaining → continue writing it, re-run renumber, measure again — do not deliver
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" render --appendix --out auto --citation-map <report-citation-map.json>   # writes Appendix A, B, C and D to a file; returns the line to quote — LAST, from the closed ledger: any entry recorded after it (late claim / verify / figure) means re-running it, never hand-editing its tables
```

`check` fails on a missing outline, an unsupported claim, a **top-level** section with fewer than two sources, a live source with no note, an empty ledger, or spend at the hard limit. A thin **subsection** is a warning, not a failure: write it thin and say it is thin, or merge it up — do not pad it and do not write around a failing check.

Then write the report per `references/report-format.md`. `render --final` is the ledger view — take from it the section numbers, the claim set per section in order, and the stable ledger source numbers; **write the analysis as prose from those claims, citing sources as `[@n]` placeholders — do not paste the `c1` claim ids, the `_来源：` source-pool lines, the `_（分歧）_` / `_（解读）_` tags, or the raw `冲突：` bullets into the body. Those are ledger scaffolding.** The claims are the skeleton, not the ceiling: each subsection's paragraphs carry the mechanism, numbers and detail the ledger already holds — a paper's abstract, a patent's fulltext note, a web page's facts. Claim restatements are a defect even when every sentence is cited; `render --renumber` hard-errors on any subsection under 300 prose units (CJK characters or Latin words, citations and structural lines excluded), so a thin draft cannot reach the page. The delivered report's numbers are assigned by `render --renumber` from where each placeholder first appears in your draft — never hand-type them; a `[@n]` naming an unknown or dropped source is a hard error, and the references list carries only cited sources. The appendices stay in the file `--out auto` wrote (D maps report numbers back to ledger numbers); the report ends with the reference list plus the returned `pointer` line. For an industry report, also ship at least one figure (registered + `chartrender.py` + `figure mark-rendered`) and a player-comparison table before you call it done — a Genre B report with no charts or player table is a defect, not a complete report.

## Budgets

| Item | Default |
| --- | --- |
| Top-level sections | 2–4 (a `complex` tier may justify 5); capped by the tier at registration |
| Subsections per section | 2–4, exactly one of them the disagreement subsection |
| Round 0 scout probes | 3–4 probes × ¥0.70 `paper_qa_search_pro` (~¥2.80) |
| Complexity tier | `evidence.py tier` at Round 0, with a reason — simple 2 directions × 1 rerun × 3 rounds · moderate 3 × 2 × 6 (default) · complex 5 × 3 × 10; the engine refuses over-quota outline/round registrations, `--wasted` rounds are recorded but not charged |
| Rounds | capped by the tier (3 / 6 / 10 effective rounds); stop earlier whenever the signals say sufficient |
| Paid `paper_qa_search_pro` calls per round | 2 |
| ¥0.01 `paper_search_pro` calls per round | unlimited |
| Native web calls per round | 3 |
| Candidates kept per top-level section | 8 |
| Paid detail calls, whole task | 50 |
| Open-access fulltext reads | unlimited and free — the host's web tools, not AMiner; every cited paper/patent either read at fulltext or marked `fulltext --unavailable` |
| `paper_relation` seed expansions | 5 |
| Patent probes (industry-report only) | 1–4 `patent_search` in Round 0 (≥1 mandatory), free; widen `size` (no quality sort exists on the channel) and split by technology line, not rewording; `patent_detail` ¥0.01 shares the 50-detail budget |
| Figures | Genre A (academic): optional. Genre B (industry): ≥1 expected (market-share / player / timeline) + a player-comparison table. Cap: ≤6 per report, ≤2 per section; `bar` / `hbar` / `line` / `pie` / `heatmap` (quantitative) or `timeline` (structural, dated events) templates, or a `--code` B script; no LLM cost, rendered by `chartrender.py` |
| Cost confirmation threshold | ¥10.00 estimated |
| Hard stop, whole task | ¥20.00 accumulated (`check` blocks) |

A typical run lands near ¥4–6, and the shape of the bill matters more than the total. A measured run came to ¥6.09: **¥5.60 for eight searches, ¥0.49 for forty-nine full abstracts.** Searches are 92% of the cost, so that is the line to ration — one avoided ¥0.70 search pays for seventy abstracts. Read everything you cite, at the deepest level you can actually obtain — the open-access original first, the abstract only as a recorded downgrade; think twice before every Pro search, and check whether ¥0.01 `paper_search_pro` can express the query first.

Raise a budget only when the user asks for broader coverage or a stated requirement cannot otherwise be met, and re-estimate cost first.
