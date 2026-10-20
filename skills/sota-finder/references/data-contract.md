# Research Input and Evidence Contract

The host model prepares one working JSON file for a run. `scripts/build_outputs.py` normalizes IDs and common shorthand, validates material invariants, ranks `main` rows within each scope, and writes the final four artifacts. Fix validation errors in that input before the final build; repeat the build only to correct a concrete failure or inconsistency rather than using repeated builds as an editing workflow. This contract describes the data shape; it is not a demand for a rigid research state machine.

## Top-level input

```json
{
  "research_run": {},
  "coverage": {},
  "scopes": [],
  "sources": [],
  "claims": [],
  "conflicts": []
}
```

## `research_run`

Required:

- `topic`: human-readable topic;
- `query`: original or normalized user goal;
- `evidence_checked_through`: absolute ISO date (`YYYY-MM-DD`);
- `language`: `en`, `zh`, or a locale beginning with one of them;
- `aminer.used`: boolean.

Optional fields include `topic_slug`, `generated_at`, `search_notes`, `conclusions`, `baseline_seed`, and AMiner purpose/cost/skipped-reason notes. In recurring or user-requested follow-up tracking, `baseline_seed` may record the prior run ID, prior evidence cutoff, and prior snapshot state; it is provenance for a reused candidate register, not proof that the current run refreshed those sources. `conclusions` may be a string or a short list of plain-language user-facing conclusions. Use it to answer the user's actual decision first; when omitted, the builder derives a minimal conclusion from the leading main claims. `research_control` is optional provenance only; it is not a workflow state machine and must not be used to invent observed search telemetry.

## `coverage`

`searched_source_types`, `queries`, `stop_reason`, and `gaps` describe the work actually performed in this run. Preserve the exact submitted search strings in `queries`, record only source types that were actually opened or queried, and make `stop_reason` name the concrete stopping condition (for example, source-family coverage reached, consecutive no-change checks, external-call deadline, or a tool limitation). Do not copy planned queries into these fields. A complete open-world snapshot with evidence sources must not leave `searched_source_types` or `queries` empty; if live verification could not be performed, record a specific gap and deliver the result as partial.


## Optional `research_control.source_coverage`

Broad open-world and recurring tracking runs should record the applicable discovery families in `research_control.source_coverage`. Suggested keys are `official_or_source_native`, `primary_papers`, `author_repositories_or_model_cards`, `comparison_table_expansion`, and `recent_open_search`; each value should state `observed`, `partial`, `not_observed`, or `not_auditable`, with a short safe note when useful. This is coverage provenance, not fabricated telemetry. A missing material family must also appear as a user-meaningful item in `coverage.gaps`.

When a prior snapshot is supplied, its claims and sources form a persistent candidate register. Preserve their stable IDs where possible, merge new evidence into them, and remove or downgrade a prior claim only when the current run has evidence for withdrawal, correction, unavailability, or a changed comparison protocol.

## Optional `coverage.matrix`

For cross-benchmark or multi-dataset work, `coverage.matrix` can carry one compact user-facing table:

```json
{
  "title": "Cross-benchmark coverage",
  "columns": ["Method", "Benchmark A", "Benchmark B"],
  "rows": [
    ["Method A", "92.4", "not evaluated"],
    ["Method B", "91.0", "88.2"]
  ],
  "notes": ["Use source-native score wording; do not imply missing evaluations are zero."]
}
```

`columns` needs at least two labels, every row must have the same number of scalar cells, and `notes` is optional. Use the matrix to show coverage, not to average incomparable metrics.

## `scopes[]`

Each scope needs a local `key`, `name`, `task`, and `metric`:

```json
{
  "key": "benchmark-standard-test-top1",
  "name": "Benchmark standard test",
  "task": "classification",
  "benchmark": "Benchmark X",
  "benchmark_version": "1.0",
  "dataset_or_subtask": "test",
  "split": "test",
  "metric": {
    "name": "accuracy",
    "variant": "top-1",
    "unit": "%",
    "direction": "higher"
  },
  "evaluation_protocol": "official server",
  "material_axes": [
    {"name": "external_data", "value": "not allowed"}
  ]
}
```

`metric.direction` must be `higher` or `lower`. Add material axes only when they change the meaning of a comparison.

## `sources[]`

Each source needs `key`, `type`, `title`, `authority`, `accessed_date`, and a boolean `available`. `authority` is one of `official`, `primary`, `author`, `secondary`, or `aggregator`. Include `url`, publication date, version, authors, and notes when available.

## `claims[]`

Each claim is a ranked result or a retained candidate:

- `key`, `scope_key`, `section`, and `method` are required;
- `section` is `main`, `reference`, or `unavailable`;
- `score_numeric` is required for `main`, but may be omitted for reference/unavailable candidates;
- `score_display` preserves the source's visible wording;
- `evidence_source_keys` links to the source registry;
- `comparability_complete` is boolean;
- optional fields include `variant`, `paper_title`, `year`, `setting`, `evidence_locators`, `method_summary`, and `notes`. For concise inputs, `setting` may be a string and each locator may be a string; the builder converts these to objects.

A main claim must have a numeric score, complete enough comparability, evidence, and at least one official/primary/author source. A numeric result with incomplete setting or secondary evidence belongs in `reference`, not `unavailable`. A named candidate with no recovered score can still be a `reference` row. The builder does not decide research truth; it enforces these declared mechanical gates.

## `conflicts[]`

A conflict needs `key`, `scope_key`, `summary`, and `status` (`resolved`, `unresolved`, or `unavailable`). It may reference claim and source keys and include a resolution. Its primary `scope_key` determines where the conflict is displayed, while `claim_keys` may intentionally include claims from other scopes when the conflict is about ambiguous protocol or scope assignment.

## Stable IDs and final JSON

Use short local lowercase keys. The builder converts them to stable `scope-`, `src-`, `clm-`, `conflict-`, and `run-` IDs. The final `evidence.json` contains normalized run metadata, scopes, claims, sources, conflicts, coverage/gaps, and validation warnings. Machine keys, stable IDs, enum values, and script-facing values such as `dataset_or_subtask`, `split`, and metric name/variant/direction remain unchanged and in English even when visible reports are Chinese. Set `research_run.language` for localized labels; user-facing topic, scope names, titles, descriptions, and notes may be translated when requested.
