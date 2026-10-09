---
description: Find recent or historical SOTA and build a practical multi-scope leaderboard
argument-hint: "[research goal, task, or benchmark] [output: <dir>] [sources-only: yes|no] [aminer: auto|off|on]"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch
---

# `/sota-finder`

Use the `sota-finder` Skill for `$ARGUMENTS`.

1. Parse the goal and any output, source restriction, or AMiner preference. Choose `direct`, `quick`, `standard`, or `deep` effort; treat offline/file/AMiner/failure conditions as separate branches.
2. Start immediately. Use explicit files/URLs first, then open-world discovery unless the user explicitly says `sources-only: yes`. Keep enough time to synthesize and build the final artifacts.
3. Use breadth-first scope coverage: search user-named scopes first, secure one credible leader or a specific gap for every material scope, fold isolated one-row results into a chronology/reference table, then deepen the primary scopes. Add `coverage.matrix` when it clarifies cross-benchmark or multi-dataset coverage. Search official pages, papers/preprints, author repositories/model cards, and aggregators; use aggregators for discovery and cross-checking only.
4. Prepare one working research input outside the final output directory using `references/data-contract.md`, including a short `research_run.conclusions` takeaway; validate it directly, fix concrete errors in that same file, then normally run the real builder once to `output/<topic-slug>`, retrying only for a concrete failure or inconsistency. Trust a successful build and only confirm the four paths exist; avoid ceremonial syntax/dependency/source preflights and post-build artifact re-audits.
5. Return the user's conclusion first, inferring the most useful summary when the request is broad; then show a concise leaderboard for every material scope, only interpretation-changing exceptions, and direct links to `brief-report.md`, `full-report.html`, `leaderboards.xlsx`, and `evidence.json`. Keep evidence IDs, provenance bookkeeping, repeated caveats, routine build status, and infrastructure diagnostics out of chat. If verification is unavailable, show a populated provisional/reference table rather than an empty main table.

Do not start with an unnecessary questionnaire, discard useful candidates merely because they are not main-table eligible, create duplicate final bundles, or silently overwrite an earlier bundle.
