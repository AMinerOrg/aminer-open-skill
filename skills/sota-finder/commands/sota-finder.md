---
description: Find recent or historical SOTA and build a practical multi-scope leaderboard
argument-hint: "[task or benchmark] [output: <dir>] [sources-only: yes|no] [aminer: auto|off|on]"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch
---

# `/sota-finder`

Use the `sota-finder` Skill for `$ARGUMENTS`.

- Choose `direct`, `quick`, `standard`, or `deep` from the actual research cost; treat supplied files, offline mode, AMiner, and source failures as separate conditions.
- Use supplied files and URLs first, then search official result pages, papers and preprints, author repositories or model cards, and aggregators unless the user restricts sources.
- Cover material scopes before deepening one. Keep comparable rows in the main leaderboard and useful non-comparable candidates in reference results.
- For artifact-producing runs, prepare the working JSON with `references/data-contract.md`, validate it, and build the four standard files with `scripts/build_outputs.py`.
- Return the conclusion first, followed by readable scope-specific leaderboards, only interpretation-changing notes, and direct artifact links.

Do not replace the result with search logs, evidence bookkeeping, defensive boilerplate, or an empty table when useful provisional results are available.
