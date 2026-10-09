---
name: sota-finder
description: >-
  Find recent or historical SOTA and build practical, source-aware leaderboards for a task or benchmark. Use when the user wants a benchmark survey, cross-paper comparison, open-world result discovery, or structured leaderboard artifacts from natural language, papers, URLs, repositories, tables, or existing result files. Keep comparable results in main leaderboards and retain useful non-comparable candidates as clearly labeled references.
license: MIT
metadata:
  openclaw:
    requires:
      bins: [python3]
---

# SOTA Finder

Produce a useful leaderboard first. Research notes and evidence bookkeeping support the result; they must not replace the result.

## Defaults

- Start from the user's goal and infer a broad, useful scope. Do not begin with a questionnaire.
- External search is on by default unless the user explicitly restricts the work to supplied sources.
- If a benchmark is a suite or has obvious subtasks, discover them and present separate scopes instead of forcing one universal ranking.
- When the user says “latest”, use the current date and show an absolute evidence cutoff.
- Use one final output bundle per run. Keep research inputs and drafts outside that directory; do not create duplicate bundles to simulate progress.
- Delivery outranks optional research: once the collected evidence can support a useful core across the material scopes, write the working JSON before opening more secondary sources. Repeated stalls, reconnects, or source failures are a signal to freeze the current scope and build from what is already known, not to keep expanding.
- Treat a host-provided search deadline as a hard stop for external calls. Batch related queries, allow at most one comparison-table expansion pass, and stop immediately after three consecutive source checks add no important candidate, scope, conflict resolution, or conclusion change; never start another “last check” after the stop gate fires.

## Choose the effort level

Route by expected research cost before searching: `direct / quick / standard / deep`. This is a judgment call, not a state machine.

- `direct`: the request is not actually a leaderboard task, the supplied answer is enough, or unavailable tools limit the useful deliverable to a staged structure, limitations, and a verification plan. Give that substantive answer immediately in chat. Unless the user explicitly requests files, stop there: do not load or execute the artifact workflow.
- `quick`: one named benchmark or narrow scope with an accessible official/source-native result surface. Build the useful Top 3-5 promptly; do not survey the whole field.
- `standard`: ordinary leaderboard work involving several sources, a supplied seed, multiple obvious scopes, or a practical selection decision.
- `deep`: no unified benchmark, broad historical/current coverage, many competing scopes, or consequential deployment/reproduction constraints. Search broadly, but deliver a usable core before expanding.

For recurring tracking, an initial run without a complete trusted baseline is normally `standard`, even when the benchmark name is short. A later run with a validated baseline is normally `quick`: load the prior evidence first, use it as a persistent candidate register, search for changes since its cutoff, and retain historical candidates unless primary evidence shows withdrawal, correction, or a protocol change. A partial prior run may seed the candidate register but does not turn the next run into an incremental-only pass.

Treat boundary conditions separately from effort: supplied files may be authoritative or merely seeds; an offline-only instruction disables web research; AMiner is optional; conflicts and unavailable sources should trigger graceful labeling rather than a larger workflow. Start from files/URLs when provided, then use only the source branches that can improve the answer. Reserve time for synthesis and artifacts instead of spending the whole run searching.
For an offline structured-file transformation, use the supplied path directly and preserve the payload except for requested presentation fields. Localize visible prose through `research_run.language`; keep machine keys, stable IDs, enum values, and script-facing values such as `dataset_or_subtask`, `split`, and metric name/variant/direction unchanged. User-facing topic, scope names, titles, and notes may be localized when requested. The builder localizes standard labels and displayed enum values, so prepare prose before validation and do not patch generated artifacts after a successful build.

Native search is the default discovery path. When an already-known official dynamic leaderboard or documented data endpoint does not expose row-level content, `<skill-root>/scripts/fetch_source.py <URL>` is an optional convenience for turning public text, HTML, JSON, CSV, or XML into a readable local file. It limits each request for safety but does not impose a research-call quota; if a first read reaches a landing page or wrong track, reuse it on the corrected direct result URL. Choose other available browser or file tools when they fit better, and avoid purposeless crawling or bulk downloads. Do not spend the delivery window writing a one-off scraper or parser when the helper, native search snippets, or a partial cited table can produce a useful result.

If live research is required but no native search/browser tool is available, try proportionate direct access when the environment permits. Do not hunt through unrelated local caches, proxy settings, or repository history for substitute facts. If access still fails, state the limitation once in user terms, then show a populated provisional/reference leaderboard with the useful candidates already known; scores may be unknown or marked `unverified`. Do not lead with a zero-row main table or expose proxy, MCP, plugin, or authentication diagnostics unless the user asked for troubleshooting.

## Research approach

1. **Find the result surface.** Search official benchmark/leaderboard pages and source-native structured result files first, then original papers and preprints, official or author repositories/model cards, and finally high-quality aggregators. Use several applicable discovery clusters rather than only literal `SOTA` or `record` phrases: benchmark + metric, protocol or data regime, score bands around known leaders, paper-table vocabulary, aliases, and recent date-bounded queries. Combine relevance-oriented and recency-oriented retrieval; a small newest-first result page is not broad coverage. Aggregators are for discovery and cross-checking, not sole proof of a main result.
2. **Cover scopes breadth-first.** Build a lightweight breadth-first scope inventory: benchmark/version, task or subtask, dataset, split, metric and direction, evaluation mode, training-data regime, model aggregation, evaluation operator/provenance, and only other settings that materially affect comparison. Keep an official frozen leaderboard, one evaluator's cross-vendor rerun, vendor self-reported evaluations, and incompatible protocols in separate visible layers unless the evaluator, implementation, inputs, inference settings, and scorer are demonstrably aligned. Explicitly named scopes are primary: search each directly before expanding generic scopes, and accept a gap only after the relevant official or primary result surface fails to yield a recoverable result. On the first pass, give every material scope one credible leader or a specific coverage gap. Merge scopes that share the same comparison protocol and place secondary scopes in a reference table. A scope with only one recovered row is usually not a standalone leaderboard; unless the user asked for that official winner track, fold it into a chronology, coverage table, or explicit gap.
3. **Build and expand the candidate register.** For every useful row, capture method/variant, score as reported, metric, scope, setting, publication or release date, direct source, precise locator when available, and a short caveat. Treat a supplied prior snapshot as a persistent register rather than a disposable answer: merge new evidence into it and do not delete a prior candidate merely because the current search did not rediscover it. Read the comparison tables of likely leaders and use their cited competitors to expand the register, then verify conclusion-driving rows against the original paper, official result page, or author repository. Before deepening any one scope, complete the horizontal pass across all material scopes. Then expand primary scopes to a useful Top 3-5 when evidence permits; if a source-native table exposes many rows, retain all recovered comparable rows or at least a useful Top 10. For cross-benchmark or multi-dataset requests, add a compact coverage matrix when it makes evaluated and missing combinations clearer. Treat an unresolved split, version, metric, or protocol as `unknown` or `unverified`. Do not use vague placeholders such as `commonly reported split`.
   A source-native result table is enough evidence for the score rows it directly reports. Do not open a separate paper or repository for every copied row; spend deeper verification on likely leaders, actionable reproduction candidates, material conflicts, and unclear settings. Requested metadata does not require every row to be fully enriched: use fields already present in the ranking source, verify conclusion-driving candidates first, and leave noncritical gaps `unknown` instead of performing serial model-card or license lookups. When only a few result files are needed, prefer targeted page, API, or raw-file reads over cloning a large results repository or batch-downloading papers; keep individual network attempts short and avoid manual retry loops.
   Completeness means useful leaderboard and scope coverage, not filling every metadata cell. An authoritative result surface is a strong base, not an automatic stop signal: continue when another source is likely to add recent candidates, requested source families, practical implementations, alternate tracks, or resolve material uncertainty. Use the expected value of another research action relative to the time needed for synthesis and delivery; leave low-value metadata `unknown`.
4. **Classify without deleting.** Use the user-visible groups `Main Leaderboard`, `Reference Results`, and `Conflicts / Unavailable` while keeping the machine sections `main`, `reference`, and `unavailable`.
   - `main`: same material scope, numeric score, sufficiently complete setting, and official, primary, or author-controlled evidence.
   - `reference`: useful numeric result with a different or incomplete setting, secondary/aggregated evidence, or a named candidate whose score is not available. Keep it visible with the reason. A number supported only by an aggregator is never `main`, and its `comparability_complete` flag must not be `true`.
   - `unavailable`: a relevant claim is known but the source/result cannot be accessed or reconstructed. Do not use this as a catch-all for rows that merely need a caveat.
   - `conflict`: competing values or interpretations; keep the records and explain the chosen treatment.
   - `sota=true` is only a mechanical marker for rank 1 inside the explicitly defined `main` scope. If a higher numeric reference exists, a material source family is missing, or a conflict remains unresolved, user-facing conclusions must say `best verified within this scope` rather than claim a global SOTA. Split an over-broad scope instead of promoting a lower but better-documented result over a higher credible candidate.
5. **Verify selectively.** Verify the leaders, recent SOTA claims, scope boundaries, and material conflicts. Do not delay a usable leaderboard for exhaustive paper-by-paper history. After a credible Top 3-5 exists, continue only when a new search could add a meaningful candidate, change the ranking/scope/evidence, or satisfy a named source family; do not repeat a source family that is no longer changing the result.
6. **Stop by usefulness.** Stop when each material scope has a credible table or explicit gap, major source families have been checked or marked as gaps, and new searches are no longer adding important candidates or resolving consequential uncertainty. Three consecutive no-change source checks are a mandatory stop signal. Never claim exhaustive coverage merely because searches became repetitive.

**Results first.** Keep audit language inside the structured artifacts. In chat and reports, use ordinary user-facing language, one compact caveat per material issue, and no narration of the search process. Evidence uncertainty changes a row's label; it should not make a useful candidate disappear. Prefer a useful partial leaderboard completed on time over an exhaustive investigation that produces no result. If the host supplies a deadline, treat it as a delivery constraint, not a query or source quota: work backward and begin synthesis early enough to finish.

## Final consistency and fallback

Before replying, perform one lightweight check against the finalized structured input: chat numbers and statuses match it, every `main` row has authoritative or primary evidence, no global-SOTA wording survives when coverage is partial or a higher reference candidate exists, and all four links target one directory. Call evaluations independent only when the evidence establishes separate execution; identical values in multiple author-controlled reports mean only that the reports agree. When recommending reproducible baselines, distinguish the strongest open model verified under the official protocol from newer vendor-reported open-weight candidates awaiting independent reproduction. Do not reopen generated artifacts for this check. If search or AMiner returns an authentication error, rate limit, missing server, or timeout, stop retrying, record the limitation, and finish with the evidence already collected. Never end with an empty response because an optional source failed.

If the host supports intermediate responses and the user asks for an early result, send a short provisional leaderboard after the first credible scope is found, then continue. If it does not, give the final response in leaderboard-first order; never generate duplicate formal bundles as a fake snapshot.

## Evidence and AMiner

Use the supplied files and URLs directly, then fill gaps with open-world research. Keep source roles and evidence locators in the structured input. Do not claim a query was executed, a page was checked, or coverage was complete unless the host can support that statement.

AMiner is optional. It may improve paper discovery, metadata, related work, and citation expansion, but it never replaces official, paper, repository, or web research. It must not be required to start or finish. Free or low-cost calls may run automatically; before an expected cumulative cost of about CNY 5, a large batch, or an uncertain paid plan, ask once for confirmation and record what was skipped.

## Artifacts

Skip this section for `direct`. For `quick`, `standard`, and `deep`, or when the user explicitly requests files, prepare one working JSON input outside the final output directory according to `references/data-contract.md`. Start a working research JSON as soon as a useful block of rows is available, and keep it easy to finish while research continues; do not wait for every requested metadata field to be known. Put the direct user-facing takeaway in `research_run.conclusions` so the brief report can lead with the answer rather than evidence mechanics.

Before delivery, run the validator, fix concrete errors in that same file, then run the final builder. The concise data contract is the construction guide. Do not inspect the full JSON schema or builder source unless validation reports a concrete problem. Do not add ceremonial syntax checks, dependency probes, or source inspection.

```bash
python3 "<skill-root>/scripts/build_outputs.py" \
  --input "/path/to/research-input.json" \
  --output-dir "/path/to/output/bundle" \
  --validate-only
python3 "<skill-root>/scripts/build_outputs.py" \
  --input "/path/to/research-input.json" \
  --output-dir "/path/to/output/bundle"
```

Aim for one validation and one final build. If `openpyxl` is missing, install `requirements.txt` once and retry validation. Do not inspect the builder source during a normal run. A successful builder result is authoritative for schema, labels, IDs, and cross-file consistency: only confirm the four paths exist; do not use `sed`, `rg`, `jq`, `wc`, or reopen generated files unless the user requests visual review or a concrete inconsistency appears. Reuse an existing final bundle within the same run; substantive corrections belong to a new run.
The final builder is the last work step: after it succeeds, immediately answer with the completed bundle and do not start another search or metadata pass. If a concrete error is noticed before replying, fix the structured input and rebuild; do not restart broad discovery merely to polish nonessential metadata.

The default bundle is one directory containing:

```text
brief-report.md       # expanded, readable leaderboard and candidate notes
full-report.html      # complete offline report
leaderboards.xlsx     # Index plus one sheet per scope
evidence.json         # claim/source/scope evidence registry
```

Use a new `-2`, `-3`, ... directory only for a genuinely separate run with a new `run_id` and an earlier bundle; never silently overwrite. If one artifact fails, still return the useful chat leaderboard and name the missing file instead of fabricating a link.

## Chat response

Lead with the conclusion the user is trying to obtain. If the request is broad or underspecified, infer the most useful summary from the apparent intent—for example the best-supported leader by scope, whether there is no single comparable winner, and a practical reproducible choice—rather than opening with methodology or caveats.

Then keep chat concise but useful:

1. show the main leaderboard rows for every material scope discovered; keep the full leaderboard when it remains easy to scan, and use a practical head slice only when it is genuinely long;
2. add one compact note about important paper/preprint/repository/aggregator candidates that are outside the main ranking;
3. state only metric, cutoff, conflict, or coverage-gap notes that can change how the result is interpreted;
4. link directly to the four saved files.

Use plain language. Preserve practical distinctions that can change selection, reproduction, or deployment, such as code or weight availability, license, hardware or cost, deployment constraints, and material settings. Do not expose evidence IDs, provenance bookkeeping, search process, routine validation, or defensive caveats in chat. Do not paste the full report into chat or hide a sparse result behind the word “minimal”; complete rows for long boards and detailed evidence belong in the full report, workbook, and evidence registry. Mention artifact mechanics only when something failed or needs user action.

## Portability and boundaries

Visible prose follows the user's language. JSON keys, IDs, schema values, and stable machine fields remain English. The Skill is self-contained and portable; the host may use native search/browser tools, while the bundled Python code handles local artifact mechanics. Do not build a universal benchmark rule database, alias registry, approval state machine, or fixed number of search rounds. Never mix materially incomparable open-world results into a main ranking.
