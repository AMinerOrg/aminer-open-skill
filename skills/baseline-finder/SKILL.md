---
name: baseline-finder
name_zh: 实验基线核查
description: Audit whether a local PDF or AMiner pub_id visibly compares plausible direct experimental baselines discovered through time-bounded AMiner search and public backward references; use for missing-baseline questions, not general related-work coverage or acceptance prediction.
homepage: https://github.com/AMinerOrg/aminer-open-skill/tree/main/skills/baseline-finder
metadata:
  version: "0.5.2"
---

# Baseline Finder

Audit a local PDF or AMiner `pub_id` for plausible direct experimental baselines that may warrant an author check. This standalone Skill parses the manuscript, builds experiment anchors, generates task-specific searches, retrieves candidates, and checks them against visible experiment evidence. It does not run a complete review, general related-work coverage, novelty positioning, or acceptance prediction.

The package is self-contained: it does not import a repository Core, Demo server, or another Skill. Install it in an isolated Python 3.10+ environment:

```bash
python -m pip install /path/to/baseline-finder
```

Then supply exactly one input:

```bash
baseline-finder --env-file /secure/review.env \
  --pdf /absolute/path/paper.pdf --review-as-of 2026-10-29 \
  --model-profile glm53 --output /private/reports/baseline.json

baseline-finder --env-file /secure/review.env \
  --pub-id 0123456789abcdef01234567 --review-as-of 2026-10-29 \
  --model-profile glm53 --output /private/reports/baseline.json
```

`python /path/to/baseline-finder/scripts/run.py` accepts the same arguments. A PDF must be non-empty and no larger than 20 MiB. A `pub_id` is a 24-character hexadecimal AMiner identifier.

## Retrieval and identity policy

Every AMiner gateway request sends the `baseline-finder` skill name and package version. The platform header is detected from the host (`claude-code`, `cursor`, `codex`, or `openclaw`) and falls back to `unknown`; set `AMINER_SKILL_RUNTIME` in the environment file only when detection needs an override.

AMiner Open Platform is the default paper-discovery provider:

1. Before broad discovery, the Skill walks the complete structured TEI bibliography rather than relying on the model to copy titles. Targeted inline citations are linked directly; target-less citations require a body-visible acronym/full title plus matching author-year or reference label. If GROBID emits no citation node at all, recovery requires the acronym/full title and matching author-year in the same body sentence. Entries visibly compared in experiments are removed, and the remaining exact titles are verified one by one through free `paper_search(query=<title>, year_to=<cutoff year>, page=1, size<=20)`. Verification has a visible 60-title safety limit with truncation diagnostics; there is no hidden first-10/first-12 cutoff. Verified bibliography, relation, keyword-feedback, and search records then compete in one bounded, source-neutral pre-selector pool; no source or retrieval role reserves capacity.
2. The `auto` router selects an AMiner endpoint by query shape: exact titles and short phrases use free `paper_search` with canonical `query` + `year_to`; controlled field phrases or requests above 20 results use `paper_search_pro` with `query` + `year_to`; natural-language semantic requests use the currently available legacy `paper_qa_search`. When Search Pro is explicitly used for `exact_title`, it may use its documented `title` field with `year_to` and `page=0`.
3. `--aminer-search-tier qa-pro` explicitly probes `paper_qa_search_pro`. Permission, balance, provider, or empty-result failures downgrade visibly inside AMiner to legacy QA, Search Pro, then free search. `auto` does not repeatedly probe an unavailable QA-Pro entitlement.
4. `paper_info` batch-enriches returned IDs with authors and abstract slices. Records still missing abstracts are enriched with one `paper_detail_batch` call (¥0.01 per returned paper; IDs not found are free), bounded by `--aminer-detail-limit` (default 3 per query, `0` disables it).
5. Every endpoint attempt records the query shape, HTTP method, parameter names, result cap, response `log_id`, fallback reason, unit price, and estimated cost. No credential is retained.

arXiv and OpenAlex remain explicit adapters, not silent fallbacks. Select one as the primary with `--retrieval-provider arxiv|openalex`, or opt into a fallback with `--external-fallback-provider arxiv|openalex`. The default is `--retrieval-provider aminer --external-fallback-provider none`; AMiner endpoint downgrades do not activate an external provider.

For PDF input without `--relation-pub-id`, the Skill searches the extracted title and accepts an AMiner ID only when title similarity plus available author/year evidence yields exactly one verified match. A title alone, fuzzy candidates, or multiple verified candidates never activates relations. Use `--no-auto-resolve-pub-id` to disable this check. An explicit `--relation-pub-id` remains available when identity has already been verified externally.

## Citation scope

The default relation endpoint is the documented public request:

`GET /gateway/open_platform/api/paper/relation?id=<pub_id>`

It returns only papers cited by the target (`target_references_candidate`, backward references). It does **not** provide later papers that cite the target. The Skill never fabricates or labels forward citations. Returned IDs are batch-enriched through `paper_info` in groups of at most 100.

A backward edge may support `mentioned_not_compared` because it shows that the target cites the candidate; it never proves an experimental comparison or that the baseline is required. Exact publication dates after the review cutoff are removed. If AMiner supplies only a publication year equal to the cutoff year, the candidate is withheld from the visible evaluation view because its eligibility cannot be proven; no January 1 date is invented.

## Input quality

- PDF mode requires GROBID by default and retains TEI sections, physical-page alignment, tables, formulas, and block locations. Use `GROBID_URL` or `--grobid-url`; the default is `http://127.0.0.1:8070`.
- `--allow-pypdf-fallback` permits a visibly reported lower-quality text-only parse. It is never silent and is rejected with `--pub-id`.
- `pub_id` input remains supported by the packaged AMiner Interface-B source adapter, which requires the corresponding account scope. This acquisition adapter is separate from the public discovery/relation path and is reported in source provenance.

Inspect `source_parse.json`, `source.provenance`, `run_metadata.pub_id_resolution`, `run_metadata.relation_diagnostics`, and `results.baseline_audit.retrieval_diagnostics`. The latter exposes `bibliography_first`, `query_diagnostics`, endpoint attempts, downgrades, and costs. The report records provider-reported request/token totals in `run_metadata.model_usage`. `run_metadata.timing.model_request_wall_seconds` is the overlap-aware model critical path, while `model_request_seconds_sum` preserves total provider request occupancy; a missing provider `usage` object is reported explicitly rather than estimated.

## Model concurrency

The complete selector shortlist remains divided into batches of at most twenty records. Version 0.5.1 evaluates up to three independent batches concurrently by default, so the current sixty-record safety cap can be assessed in one wave. `BASELINE_SELECTOR_BATCH_STRATEGY=balanced` (the default) divides the shortlist into the minimum number of near-equal contiguous batches; for example, 49 records become `17+16+16`. Set it to `fixed` for the legacy consecutive twenty-record chunks (`20+20+9` for 49 records), which supports a controlled A/B latency comparison. Both strategies preserve candidate order, make the same number of selector requests, and merge results in original batch order before the unchanged evidence gates and Top-10 ranking. Set `BASELINE_SELECTOR_MAX_WORKERS=1` or `2` to reduce per-paper concurrency. Diagnostics record the selected strategy, batch sizes, per-batch wall time, and effective worker count.

All GLM SDK requests, including structured-output retries, share a cross-process gate with six slots by default. Configure `BASELINE_GLM_GLOBAL_CONCURRENCY`, or set it to `0` to disable the gate. Processes on one host use a private temporary gate directory automatically; containers or hosts that must share one limit need the same `BASELINE_GLM_GATE_DIR` on a filesystem with working file locks. `BASELINE_GLM_GATE_TIMEOUT_SECONDS` and `BASELINE_GLM_GATE_POLL_SECONDS` control acquisition. Concurrency reduces per-paper wall time only; it does not reduce model requests, tokens, or cost.

## Candidate tiers and evaluation view

The report exposes at most ten baseline candidates. Ten is a cap, not a target:

- `core` requires a grounded `direct_performance` purpose, explicit model `confidence=high`, `task_protocol_relevance=high`, `same_task=high`, `same_protocol=high`, `fair_baseline_usefulness=high`, and `runnability=runnable`, plus candidate-side dataset/metric/evaluation evidence, objectively verified structured candidate full text, and no withdrawn, retracted, or incomplete-experiment/evaluation evidence. A model assertion cannot override these objective gates. AMiner `paper_detail`, metadata, abstracts, target-side bibliography entries, and citation contexts are not candidate full text.
- `extended` contains medium-confidence records with at least one evidence-grounded comparison purpose: `direct_performance`, `mechanism_isolation`, `budget_matched_policy`, `novelty_boundary`, `robustness_stress_test`, `cross_task_adaptation`, or `efficiency_tradeoff`. Cross-task and adaptation-required records remain Extended even when useful. Non-full-text records are labelled `candidate_to_verify`; these are neutral leads, not claims that a comparison is required or directly runnable.
- Low-confidence or obviously non-direct records remain only in retrieval diagnostics. Current baselines, the manuscript itself, work after the cutoff, surveys, and datasets are not used to fill the view.

The selector evaluates the complete bounded shortlist in batches and returns one structured assessment per candidate ID. Missing IDs are reported as `selector_not_assessed` and are not assigned default weak semantics. Every assessment records multi-label comparison purposes and purpose evidence, adaptation requirements, same-task/protocol evidence, intervention/interface fit, claim-diagnostic value, fair-baseline usefulness, availability, and marginal novelty. A complete assessment must contain a valid `decision` and its explicit purpose/evidence fields; legacy `tier` aliases cannot satisfy that contract, and failures remain `not_assessable`. Only genuine legacy `selected` responses may use the legacy direct-purpose inference. An explicit selector `reject` is terminal only after the same contract validation and remains visible in diagnostics. Common aliases such as state-space/SSM/Mamba and denoise/denoising are normalized for diagnostics, not for mechanism quotas.

For Extended selection, every assessed shortlist record is evaluated by the deterministic evidence and comparison-purpose gate before any cap is applied. Core and Extended then enter one visible candidate pool. Utility is purpose-conditioned: `direct_performance` emphasizes objectively supported same-task/protocol comparability; mechanism isolation, budget-matched policy, and cross-task adaptation require deterministic non-generic mechanism support and emphasize mechanism, intervention/interface, and diagnostic value; novelty, robustness, and efficiency use their corresponding evidence fields. Model-authored purpose prose and task-word overlap alone cannot ground a mechanism purpose. Only the strongest grounded purpose contributes its full score, with a small bounded multi-purpose bonus, so label count cannot game the ranking and low same-task similarity does not automatically suppress a valuable adapted mechanism check. Objective citation/mechanism evidence, evidence maturity, availability, and runnability remain visible scoring inputs; unsupported protocol claims earn no protocol utility. Within a two-point near-equal utility interval, an as-yet-uncovered explicit mechanism branch is preferred; `unspecified` receives no such preference and there is no hard branch quota. Only then is the Top-10 cap applied; the cap is not a quota. Withdrawn, incomplete-evaluation, explicitly unrunnable, or runnability-uncertain candidates receive explicit penalties and can remain warning-bearing Extended checks when their diagnostic value is still strong; they never enter Core.

Every visible candidate records `tier`, `confidence`, `candidate_label`, `comparison_purposes`, `comparison_purpose_evidence`, `adaptation_required`, `evidence_level`, `evidence_sources`, `fulltext_verified`, `missing_status`, `verification`, `selection_evidence`, `fill_source`, `mechanism_branch`, `mechanism_branch_normalized`, `task_protocol_relevance`, and `runnability`; availability warnings are retained when present. Diagnostics preserve every eligible candidate's purpose-conditioned utility components, utility rank, final tie-broken rank, and retention decision. Candidates that pass all gates but fall outside Top-10 remain in `evaluation_cap_omissions` with their selector evidence and `eligible_but_omitted_by_evaluation_cap`, rather than disappearing into low-confidence audit. `missing_status` is one of `uncited`, `cited_not_compared`, `already_compared`, or `unknown`; broad search alone remains `unknown` and never proves that a paper is uncited. When fewer than ten candidates pass, `evaluation_view_status` is `insufficient_candidates` rather than padding the result.

Bibliography-first detection follows an evidence chain: complete structured reference inventory, deterministic body-citation link (including guarded target-less recovery), visible experiment baseline names, then exact-title AMiner verification for each cited-but-not-compared method. If the first-round effective candidates—not merely raw search hits—remain below the cap or lack critical evidence roles, the Skill may make one bounded `paper_list_by_keywords` feedback call. Initial discovery plus that feedback is the two-round maximum; results still pass cutoff, deduplication, evidence/comparison-purpose, availability, and tier gates.

## Credentials and configuration

- AMiner discovery is the default, so configure `AMINER_API_KEY`. It is also required for public relations and `--pub-id` acquisition. The key is never written to reports.
- DeepSeek: `DEEPSEEK_API_KEY`; optional `DEEPSEEK_BASE_URL`.
- GLM: `GLM_API_KEY`; optional `GLM_BASE_URL`.
- GPT-compatible: `GPT_API_KEY` and an explicitly trusted `GPT_BASE_URL`.
- A restricted network may require `HTTPS_PROXY` or `HTTP_PROXY`.

Generic cross-provider credentials such as `OPENAI_API_KEY`, `API_KEY`, and `LLM_API_KEY` are not accepted. Process environment values take priority; repeated `--env-file` arguments only fill variables still unset. Never commit real keys.

## Data boundaries and interpretation

Before using an unpublished manuscript, confirm each destination is permitted:

- The selected model receives bounded manuscript and experiment context, retrieval candidates, and evidence anchors.
- AMiner receives exact bibliography titles selected for verification, manuscript-derived discovery queries, and API parameters. During identity resolution it receives the extracted manuscript title; public relation lookup receives only the verified ID.
- arXiv/OpenAlex receive manuscript-derived queries only when explicitly selected.
- GROBID receives the complete PDF; the default endpoint is local.
- Configured proxies can observe routed AMiner, model, and optional external-provider traffic.

Always report the cutoff, providers, API costs, downgrades, and limitations. `candidate_to_check` and `candidate_to_verify` are neutral author-review prompts, not proof that a baseline is missing, required, or directly runnable. Preserve `not_assessable` when evidence is insufficient.

Runs are private under `~/.local/share/baseline-finder/runs/<run_id>/` by default. PDF runs retain `source.pdf`; AMiner runs retain normalized provider artifacts. Delete a specific run directory after diagnosis when retention is unnecessary.
