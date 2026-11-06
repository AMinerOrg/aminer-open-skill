# Changelog

## 0.5.2 — 2026-11-06

- Enrich records still missing abstracts with one `paper_detail_batch` call instead of one `paper_detail` call per record. Billing is CNY 0.01 per returned paper (IDs not found are free); diagnostics record the requested IDs, the upper-bound estimate, and the billed fee.

## 0.5.1 — 2026-11-02

- Raise the default per-paper selector concurrency from two to three workers while retaining the proven twenty-record batch contract, original-order merging, evidence gates, and Top-10 ranking.
- Add `BASELINE_SELECTOR_BATCH_STRATEGY=balanced|fixed` for controlled latency A/B runs. The default balanced strategy makes the minimum number of contiguous batches at most twenty records and distributes records nearly equally (`49 -> 17+16+16`); fixed retains legacy chunks (`49 -> 20+20+9`). Record the strategy and realized sizes in diagnostics.
- Keep the cross-process GLM gate at six slots by default, allowing two papers to run all three selector batches concurrently without increasing the server-wide request ceiling.

## 0.5.0 — 2026-11-02

- Evaluate independent 20-record selector batches with two workers by default while preserving original batch-order merging, evidence gates, and deterministic ranking. `BASELINE_SELECTOR_MAX_WORKERS=1..3` controls the per-paper limit.
- Add a crash-safe, cross-process GLM request gate with six slots by default, configurable through `BASELINE_GLM_GLOBAL_CONCURRENCY` and `BASELINE_GLM_GATE_DIR`.
- Make shared model telemetry thread-safe and distinguish additive provider request time from the overlap-aware model critical path and global-gate wait.
- Record selector-stage and per-batch wall time, configured/effective workers, maximum observed model concurrency, and gate diagnostics for latency analysis.

## 0.4.8 telemetry-only build — 2026-10-30

- Preserve the 0.4.8 retrieval, filtering, and ranking behavior while recording cumulative model request counts, provider-reported prompt/completion/reasoning/total tokens (including structured-output retries), missing or incomplete usage, model-request wall time, and end-to-end pipeline timing in `run_metadata`.

## 0.4.8 — 2026-10-30

- Classify candidates by one or more evidence-grounded comparison purposes: direct performance, mechanism isolation, budget-matched policy, novelty boundary, robustness stress test, cross-task adaptation, and efficiency tradeoff. A different terminal task is no longer an automatic rejection when a concrete adapted component-level purpose exists.
- Fail closed when a complete selector assessment omits or provides an invalid `decision`, or omits the explicit purpose/evidence contract; a legacy `tier` alias cannot satisfy the complete contract. Retain legacy inference only for legacy `selected` responses. Treat contract failures as not-assessable diagnostics, and validate the same contract before accepting an explicit selector `reject`.
- Keep cross-task or adaptation-required candidates in Extended only; Core additionally requires a grounded `direct_performance` purpose.
- Record `discovered`, `abstract_screened`, or `fulltext_verified` evidence maturity with sources. AMiner `paper_detail`, metadata, abstracts, bibliography entries, and citation contexts never count as candidate full text, and only objectively structured candidate-full-text evidence can enter Core.
- Evaluate the complete shortlist with the deterministic Extended hard gate before applying the Top-10 cap when the semantic selector returns few or no records.
- Merge bibliography, relation, keyword-feedback, and search records into one source-neutral relevance/evidence pool before the selector; apply only visible total safety caps, with no bibliography-first or per-role capacity reservation. Assess the resulting shortlist in bounded 20-record batches, explicitly diagnose any missing assessment IDs, and rank the unified candidate pool by manuscript-grounded baseline utility rather than mechanism quotas.
- Retain withdrawn or incomplete-evaluation methods only as warning-bearing Extended checks; they remain ineligible for Core.
- Preserve `mechanism_branch`, normalized branch, task/protocol relevance, runnability, and availability warnings on final report records.
- Give the semantic selector the target task, method modules, datasets, metric/evaluation protocol, current baselines, and each candidate's complete abstract, metadata, bibliography/citation context, discovery provenance, identity, cutoff, and availability evidence.
- Require structured same-task, same-protocol, mechanism, intervention/interface, usefulness, diagnostic-value, and marginal-novelty judgments; an unsupported model claim of protocol equivalence cannot enter Core, and model prose or task-word overlap alone cannot ground mechanism-isolation or cross-task purposes.
- Rank records by grounded semantic utility, cited-not-compared evidence, availability, and marginal value before lexical/model rank. Within the two-point near-equal utility interval, prefer an uncovered explicit mechanism branch; `unspecified` receives no preference, no branch reserves capacity, and low marginal novelty is a score rather than a hard exclusion.
- Make unified-pool utility purpose-conditioned instead of globally applying direct-comparison task/protocol weights: direct performance emphasizes objective task/protocol comparability, while adapted mechanism, policy, novelty, robustness, and efficiency purposes use their relevant evidence fields. Use only the strongest grounded purpose plus a small capped multi-label bonus.
- Preserve a full utility/rank trace for every eligible candidate and a structured `evaluation_cap_omissions` record for candidates excluded only by the Top-10 cap, including selector evidence and the explicit cap decision.

## 0.4.7 — 2026-10-30

- Build cited-but-not-compared candidates from the complete structured TEI bibliography, independent of whether the planning model copied a title; recover target-less citations only with a body-visible method/full title plus matching author-year or reference label, and recover missing-`ref` GROBID text only when method/full title and author-year occur in the same sentence.
- Preserve every exact-verified bibliography candidate through the semantic verifier, replacing the upstream per-role first-10 cutoff with a visible 60-title verification/semantic safety limit and truncation diagnostics.
- Normalize mechanism aliases before branch round-robin selection and order each branch by explicit task/protocol relevance followed by model rank.
- Require explicit high/high/runnable labels for Core; `runnable` denotes an explicit verification rather than a default, missing or uncertain runnability does not enter Core, and withdrawn, retracted, or incomplete-experiment/evaluation evidence in the original bibliography entry also blocks Core.
- Add regressions for target-less TEI citations, more than ten verified references, state-space/Mamba aliases, denoising branch order, and Core availability gates.

## 0.4.6 — 2026-10-30

- Migrated free `paper_search` to the official AMiner open-skill v1.5.0 request shape: `query`, `year_to`, `page=1`, and `size<=20`.
- Migrated ordinary `paper_search_pro` discovery to `query` + `year_to` with `page=0`; preserved `title` + `year_to` for explicit exact-title Search Pro requests.
- Kept the existing AMiner QA routing and AMiner-only downgrade ladder; arXiv/OpenAlex remain disabled unless explicitly selected.
- Added request-shape, cutoff-year, exact-title Search Pro, and internal-fallback regression tests.

## 0.4.5 — 2026-10-30

- Removed the fixed first-12 truncation from cited-but-not-compared planning and exact-title verification, so later evidence-qualified mechanism branches remain eligible.
- Added reusable mechanism-branch and task/protocol-relevance labels to bibliography planning, verification provenance, and semantic Core selection.
- Let the semantic verifier approve more than six high-confidence candidates, then apply the Top-6 cap by round-robin mechanism coverage using only those model-verified records.
- Made per-role shortlist construction branch-aware so many near-duplicates from one family cannot hide a later distinct branch; retrieval remains bounded to two rounds and AMiner remains the default provider.

## 0.4.4 — 2026-10-30

- Ask the semantic direct-baseline selector to preserve task/protocol relevance while covering distinct non-generic mechanism branches, rather than allowing near-duplicate candidates from one family to fill the evaluation view.
- Expose cited-method names, bibliography reasons, and experiment-nonappearance status to the selector so mechanism decisions remain evidence-grounded.
- Reorder only model-selected high-confidence Core records for mechanism coverage; deterministic lexical logic never promotes an unselected bibliography record to Core.

## 0.4.3 — 2026-10-30

- Parse GROBID `back/listBibl` into exact-title bibliography records with TEI IDs, authors, years, complete entries, identifiers, and target/label-preserving inline citation contexts.
- Pass structured bibliography evidence into planning and verify each cited-but-not-compared title independently through AMiner.
- Restrict experiment evidence to experiment sections and strong block-level comparison signals, excluding Abstract, Introduction, and Related Work so citations are not mistaken for experimental comparisons.
- Use short controlled terms for keyword feedback and trigger the bounded second round when Core coverage, verified cited coverage, or critical method roles are missing.
- Harden the Extended gate against generic recommendation/ranking overlap by requiring exact cited-title proof, a concrete dataset/metric match, or a non-generic mechanism match.
- Admit cutoff-year, year-only AMiner metadata when the cutoff-dated manuscript itself proves availability through an exact TEI bibliography entry and inline citation, while retaining the AMiner date-precision diagnostic.

## 0.4.2 — 2026-10-29

- Replaced the single conservative shortlist with a two-tier view: high-confidence model-selected `core` candidates plus medium-confidence `extended` candidates that pass deterministic same-task and comparable-protocol gates.
- Made Top-6 an evaluation cap rather than a quota. The report now emits `insufficient_candidates` when fewer than six defensible candidates exist and keeps low-confidence records in diagnostics only.
- Preserved bibliography-first priority for exact-title-verified cited-but-not-compared methods while excluding visible current baselines, self matches, future work, surveys, datasets, and obviously non-direct items.
- Grounded cited-but-not-compared detection in an exact reference-title → body citation-context → visible experiment-baseline evidence chain, followed by one exact-title AMiner verification per method.
- Added one bounded `paper_list_by_keywords` feedback round triggered by effective selected coverage or missing critical roles, never by raw hit count; initial discovery plus feedback is capped at two retrieval rounds.
- Enforced exact review cutoffs: exact post-cutoff dates and same-cutoff-year records lacking a verifiable date are withheld from the visible view.
- Added per-candidate tier, confidence, neutral candidate label, missing status, verification, selection evidence, and fill-source provenance without removing existing report fields.

## 0.4.1 — 2026-10-29

- Corrected free `paper_search` to the official `title`, `page`, and `size` contract; removed unsupported `query` and `year_to` parameters from that endpoint.
- Added query-shape routing within AMiner: exact titles/short phrases use free search, fielded or bulk phrases use Search Pro, and natural-language discovery uses legacy QA. QA-Pro is an explicit entitlement probe with visible AMiner-only downgrade.
- Made baseline retrieval bibliography-first: exact titles cited by the manuscript but not visible in experiment comparisons are verified before broad discovery and remain explicitly marked as candidates rather than proven omissions.
- Added batched `paper_info`, bounded missing-abstract `paper_detail` enrichment, and per-attempt parameter-shape, response, downgrade, and cost diagnostics.
- Kept arXiv/OpenAlex disabled unless explicitly selected.

## 0.4.0 — 2026-10-29

- Made AMiner Open Platform the default candidate-discovery provider.
- Added free `paper_search` + `paper_info` discovery, explicitly enabled bounded `paper_detail` enrichment, optional Search Pro/QA Pro tiers, call/cost reporting, and visible in-AMiner permission/balance downgrades.
- Kept arXiv and OpenAlex as explicit primary or fallback providers; neither is used silently.
- Added conservative PDF title → AMiner `pub_id` resolution using title plus available author/year evidence; ambiguous or title-only hits are not claimed.
- Replaced the internal bidirectional `pub_relation` dependency with public `paper/relation`, which supports backward references only. Forward citations are never inferred.
- Retained cutoff-year, year-only records as `uncertain_same_year` instead of inventing a date or silently discarding them.
- Added AMiner provider, title-resolution, relation-scope, fallback, response-trace, and cost tests.

## 0.3.0

- Added standalone PDF and `pub_id` inputs, structured GROBID parsing, direct-baseline retrieval, experiment-evidence comparison, and optional AMiner relation expansion.
