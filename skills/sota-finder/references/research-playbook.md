# SOTA Finder Research Playbook

Use this as a lightweight guide for non-trivial searches. It is not a fixed workflow or a required number of rounds.

Choose the lightest useful effort level before searching: `quick` for a narrow benchmark with a clear result surface, `standard` for ordinary multi-source or multi-scope work, and `deep` for open-world or consequential decisions. A non-leaderboard request is `direct`. Files, offline restrictions, AMiner availability, and source failures are branches within those levels, not reasons to perform a full audit. Secure a usable result early and reserve enough run time to synthesize and build the deliverables.

When the host exposes no working native web tool, confirm that once and stop network probing. Do not search caches or system configuration for substitute evidence. Produce a compact reference result from responsibly known candidates, mark it provisional/unverified, and keep the missing-live-verification note to one sentence.

## Search seeds

Start with a small, diverse set of searches:

- task/benchmark + `leaderboard`, `benchmark`, `state of the art`, or `SOTA`;
- benchmark + metric + split or `results`;
- recent benchmark/survey paper + reported leaders;
- named method + paper, project, GitHub, model card, or results;
- challenge name + results, rules, or evaluation protocol;
- Chinese name, English full name, abbreviation, and common aliases when relevant; put each named term in an actual query, but combine them in a high-recall query when possible. Use separate literal queries only when a distinct alias surface is missed or the user explicitly names it.

Search official result pages first, then original papers/preprints, author or official repositories, and aggregators. An authoritative result surface is a strong base, not an automatic stopping point. Expand when another query can add an important or recent candidate, clarify a scope, resolve a material conflict, surface a practical implementation, or satisfy a named source family. Balance that expected value against the time needed to synthesize and deliver. Finish the research input before the build gate; validate first and normally perform one final artifact build, retrying only to correct a concrete failure or inconsistency.


## Baseline and incremental tracking

For an initial tracking run without a complete trusted baseline, use `standard` even when the request names one benchmark. Establish a reusable baseline rather than optimizing only for the first plausible leader. For later runs, load the latest validated snapshot as a candidate register and use the last complete successful snapshot as the comparison baseline. A partial snapshot can seed discovery, but it cannot lower the effort level or replace the comparison baseline.

An incremental run keeps prior candidates unless primary evidence shows withdrawal, correction, or a material protocol change. Search the interval after the prior evidence cutoff, recheck source-native result tables and current leaders, and carry unresolved candidates forward with their status. This prevents a transient search miss from appearing as a removal.

## Candidate discovery and citation expansion

Use multiple applicable discovery clusters: benchmark and metric, evaluation/training protocol, score bands around the current leaders, table vocabulary, aliases, and date-bounded recent work. Combine relevance and recency retrieval. Do not treat a newest-first top-N query, a generic repository search, or a list of preselected paper IDs as sufficient open-world coverage.

Prefer source-native structured result tables when available. From each likely leader, inspect its comparison table or closely related-results table, collect credible higher or neighboring results, and verify conclusion-driving candidates at their original paper, official result page, author repository, or model card. Record the coverage status of applicable source families under `research_control.source_coverage`; missing material families belong in `coverage.gaps`.

## Scope lattice and leader semantics

For broad benchmarks, test the material axes before ranking: evaluation mode (for example zero-shot, frozen, or fine-tuned), training-data regime, single model versus weight averaging or ensemble, benchmark version/split/metric, and any resolution/model-size/training distinction that changes interpretation. Split materially different protocols before ranking rather than demoting credible high scores into one broad reference bucket.

The normalized `sota` boolean means rank 1 within one explicit main scope. It is not proof of global coverage. When coverage is partial, a higher numeric reference remains, or a material conflict is unresolved, phrase the result as the best verified leader within that scope and make the limitation visible in the conclusion.

## Breadth-first scope coverage

For multi-scope work, make a small scope inventory before detailed verification. Treat every scope explicitly named by the user as primary and search it directly before expanding generic scopes. Breadth-first pass: give every material scope one credible leader or a specific, user-meaningful coverage gap. Before deepening one scope, cover the others at this minimum level.

Merge scopes that share the same comparison protocol. Move secondary scopes into a reference table rather than creating many one-row leaderboards. A single recovered winner is usually better shown in a chronology or coverage table unless the user explicitly requested that official winner track. After breadth is secured, deepen primary scopes to a useful Top 3-5; copy a larger comparable block when an official or source-native table makes that inexpensive. For cross-benchmark or multi-dataset work, use a compact coverage matrix via optional `coverage.matrix` from `references/data-contract.md` when it exposes missing evaluations more clearly than separate sparse tables.

Do not infer a missing split, benchmark version, metric variant, or protocol. Record it as `unknown` or `unverified`, and keep the row as reference when appropriate; never hide uncertainty behind wording such as `commonly reported split`.

## What to capture

For each useful candidate, preserve:

- method and variant;
- numeric score and raw score wording when available;
- benchmark/version, task/subtask, dataset, split, metric and direction;
- material settings such as training data, shots, retrieval, ensemble, or model-size track;
- paper/release year;
- direct source and table/row/section/commit locator;
- a short comparability or uncertainty note.

If an official or source-native table is accessible, copy a useful block of rows, not only the top row. If a result has a number but incomplete metadata, keep it as a reference row. If only a method/candidate is known, keep the candidate name as reference without inventing a score.

## Scope and evidence

Keep rows together only when the benchmark, split, metric, protocol, and material settings are sufficiently aligned. Use separate scopes for public test vs validation, different tasks, different metrics, or materially different tracks.

- Official leaderboard/server: strongest ranking evidence.
- Paper/preprint result table: primary evidence for the reported setting.
- Author repository/model card: useful author-controlled evidence.
- Aggregator, survey, blog, or search snippet: discovery/cross-check only.

Use `main` for a comparable, numerically reported row with authoritative evidence. A number supported only by an aggregator, search snippet, or blog is `reference` (or `unavailable` if it cannot be reconstructed), never `main`; do not mark such a row `comparability_complete`. Use `reference` for other informative but incomplete or differently configured rows. Record conflicts instead of silently selecting a convenient number.

## Stopping and limitations

Stop when each material scope has a useful table or an explicit gap, important source families have been covered or marked unavailable, and further search is unlikely to add an important candidate or change interpretation. When a host supplies a deadline, stop external calls at that deadline; batch related queries, perform at most one comparison-table expansion pass, and treat three consecutive source checks with no material change as a mandatory stop. A stable top row alone is not sufficient when the request asks for broad coverage, but a repeated “last check” is not additional coverage.

State the user's practical conclusion before limitations. If the request is broad, infer a useful summary from the evidence: leaders by scope, whether a single winner is invalid, and a reproducible or deployable choice when supported. Separate official frozen rankings, evaluator-controlled cross-vendor reruns, vendor self-reports, and incompatible protocols unless their evaluation provenance is demonstrably aligned. Call reports independent only when separate execution is evidenced; matching values in multiple author-controlled reports show agreement, not necessarily independent replication. For reproducibility, distinguish an official-protocol open-model leader from a newer vendor-reported open-weight candidate awaiting independent reproduction. State the absolute evidence cutoff and only limitations or conflicts that materially change interpretation. Keep detailed source bookkeeping in `evidence.json` and the full report; do not repeat it as defensive prose or narrate the search process in chat or the brief report. Do not call the search exhaustive unless the evidence genuinely supports that claim.

Before the final response, compare the chat claims with the final structured records. If a correction changes a claim's status, update the structured record before the one final build; do not leave an earlier bundle with contradictory IDs in the delivered output. If a tool fails or is rate-limited, record the failure and complete a partial but useful result rather than retrying until the run ends empty.
