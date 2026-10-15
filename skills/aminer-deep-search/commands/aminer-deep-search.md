---
description: AMiner deep multi-round paper collection for survey references (50+ papers)
argument-hint: "[research topic | topic: ... target-size: 400 year-from: 2020 year-to: 2025 venues: ... exclude: ...]"
allowed-tools: Read, Bash, Glob, Grep
---

# /aminer-deep-search - AMiner Deep Search

User invoked the AMiner deep paper collection skill with the following arguments:

```text
$ARGUMENTS
```

## Your task

Follow `${CLAUDE_PLUGIN_ROOT}/SKILL.md`. You are the controller: run the tool scripts, read their JSON output, judge relevance yourself, and iterate. There is no external LLM mode and nothing to configure beyond `AMINER_API_KEY`.

**Gate check first**: this command is only for large-scale collection — 50+ candidate papers, survey bibliography construction, or citation snowballing. If the user actually wants a single lookup, a survey-style *answer*, or a small reading list, say so and point them to `aminer-free-academic` / `aminer-academic-search` instead of running the loop.

### 1. Parse `$ARGUMENTS`

- `topic`: required research topic. Preserve the user's wording. If absent or too vague, ask for a concrete topic.
- `target-size`: optional final paper target, default 400.
- `max-rounds`: optional round budget, default 12.
- Structured constraints (all optional): `year-from` / `year-to`, `venues`, `authors`, `orgs`, `languages`, `exclude` (exclusion terms), `sort-goal` (`latest` | `impact` | `classic+latest`). Also extract any of these stated in free text.

### 2. Pre-flight

```bash
[ -z "${AMINER_API_KEY:-}" ] && echo "AMINER_API_KEY missing" || echo "AMINER_API_KEY exists"
```

If missing, stop and tell the user to set `AMINER_API_KEY`. Never print the key. The scripts are pure stdlib — no dependency installation is needed.

Record the hard constraints so every `add` enforces them:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/paper_set.py" init --topic "..." \
  --year-from 2020 --year-to 2025 --require-fields year
```

### 3. Run the round protocol

Execute the Round Protocol from `${CLAUDE_PLUGIN_ROOT}/SKILL.md`:

- Round 0: derive 4–8 seed queries, pick the ranking strategy from `sort-goal` (for `classic+latest`, run each query under both `--order n_citation` and `--order year`), estimate cost; confirm with the user if the estimate is ≥¥5.
- Each round (max `max-rounds`): search via
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aminer_api.py" search --query "..." [--author ... --org ... --venue ... --year-from ... --year-to ...] --order n_citation`
  (use `qa-search-pro` only for constraints `search` cannot express: languages, exclusion terms, citation ranges),
  filter results for relevance yourself, add the kept items via
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/paper_set.py" add --source "search:<query>"`,
  snowball with `references --ids ...` on ≤5 strong unexpanded seeds, check `stats`,
  and log the round with `log-round --queries ... --added N --rejected R`.
- Stop when `target-size` is reached, results are exhausted, or 2 consecutive rounds add <5 papers.

Keep the state file and exports under the current working directory (`outputs/`).

### 4. Present the result

Optionally `promote` the strongest papers, then run `export` (add `--tier curated` for a curated-only file) and report: the final paper count, rejected/merged counts, the total cost (sum of `[cost]` stderr lines), and the output path. The export includes full per-paper fields (authors, year, venue, DOI when available, URL, provenance, tier) plus constraints and the round trace. If the run fails due to missing configuration or API errors, show the actionable structured error without exposing secrets. Never fabricate papers.
