# Output Contract

## Chat

Lead with a direct, plain-language conclusion that answers the user's actual decision. When the request is broad, summarize the best-supported leaders by scope, state when no single comparable winner exists, and identify a practical choice when the evidence supports one. Then return only:

1. the useful main leaderboard rows for every material scope discovered; show the complete leaderboard when it remains easy to scan, and use a practical head slice only when the result is genuinely long;
2. one compact note for important paper, preprint, repository, or aggregator candidates that are outside the main ranking;
3. only metric, evidence-cutoff, conflict, and coverage-gap notes that change interpretation;
4. direct links to the four files below.

Treat `sota=true` as “rank 1 inside this explicit main scope,” not as an unconditional global claim. If coverage is partial, a higher numeric reference exists, or a material conflict remains unresolved, label the row and conclusion as the best verified scope leader and surface the limiting condition. Split materially different protocols rather than selecting a lower but better-documented row as the apparent global SOTA.

Keep it short and easy to scan. Preserve practical distinctions that can change the user's choice, such as reproducibility, code or weight availability, license, hardware or cost, and deployment constraints. Do not expose evidence IDs, source bookkeeping, search narration, routine validation, or defensive caveats in chat. Do not make the leaderboard unusably sparse merely to satisfy brevity or paste the full report into chat.

## Output directory

Default:

```text
outputs/<topic-slug>/
```

If the target already contains any default artifact from an earlier research run, allocate `<topic-slug>-2`, `<topic-slug>-3`, and so on. Within one run, use one fixed final directory and do not create `bundle-2` or `bundle-3` for revisions. The explicit final directory must not already contain standard artifacts, and sibling bundles with the same `research_run.run_id` are also treated as the same run; the builder should refuse that accidental reuse rather than silently creating another bundle. Use a new run ID for a genuinely separate run. Do not overwrite silently.

## `brief-report.md`

A concise, conclusion-first expansion of the chat result containing:

- the direct user-facing conclusion, inferred from the user's intent when necessary;
- absolute evidence cutoff and a compact cross-scope leader overview;
- the complete rows of each reasonably short material leaderboard, otherwise a practical head slice with complete rows kept in the full report and workbook;
- only the most useful reference candidates and short leading-method descriptions;
- concise conflicts and gaps that change interpretation.

Do not include evidence IDs, source registries, validation warnings, search narration, or repeated defensive notes. Merge repeated one-row scopes into an overview or coverage table instead of creating many nearly empty sections.

## `full-report.html`

A self-contained offline report with no CDN dependency, including the scope definitions, complete main/reference/unavailable tables, an optional cross-scope coverage matrix, method summaries, source registry and evidence links, coverage, conflicts, and gaps.

## `leaderboards.xlsx`

An ordinary Excel/WPS-compatible workbook with an `Index` sheet, an optional coverage-matrix sheet, and one sheet per scope. Include all retained rows, label main/reference/unavailable sections clearly, preserve stable claim and evidence-source IDs, and provide filters, frozen headers, and practical widths.

## `evidence.json`

One claim-centered JSON file with stable scope/claim/source/conflict IDs, the research run and cutoff, coverage notes, gaps, AMiner use, and conflict handling. It is the evidence registry, not a substitute for the readable leaderboard.
When reports are localized, keep machine keys, IDs, enum values, and script-facing scope/metric values unchanged. Translate user-facing titles, scope names, descriptions, and notes when requested.

## Partial failure

If one artifact cannot be written, do not suppress the research answer. Return the minimal useful chat leaderboard and state exactly which file failed. Never fabricate a successful file link.

If WebSearch, WebFetch, AMiner, or another optional source fails, do not stop the whole task or return an empty response. Record the failure in `evidence.json`, use the already collected evidence, and produce the best-effort leaderboard and artifacts that remain possible.
