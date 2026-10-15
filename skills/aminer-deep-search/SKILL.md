---
name: aminer-deep-search
version: 2.2.0
author: AMiner
contact: report@aminer.cn
description: >
  Activate this skill ONLY when the user explicitly needs large-scale academic paper collection:
  building a survey/literature-review bibliography of 50+ papers, assembling a large candidate
  paper pool, or citation snowballing from seed papers.
  The words "survey" or "literature review" alone are NOT sufficient — if the user just wants a
  survey-style answer, a small reading list (<50 papers), or a single lookup, do not use this skill:
  route simple free-tier lookups to aminer-free-academic, deeper single-topic analysis or <50-paper
  searches to aminer-academic-search, and personalized recommendations to aminer-daily-paper.
  The host model (the model running this skill) drives the loop itself: it expands queries, judges
  relevance, snowballs backward references, and decides when to stop. The bundled scripts are pure
  tool commands that call documented AMiner Open Platform endpoints and print JSON tool results
  only — no extra LLM configuration is needed.
  Supports structured constraints (year range, author, institution, venue, language, exclusion
  terms, citation range) and multiple ranking goals (latest, relevance, impact, classic+latest).
metadata:
  {
    "openclaw":
      {
        "requires": {
          "bins": ["python3"],
          "env": ["AMINER_API_KEY"]
        },
        "primaryEnv": "AMINER_API_KEY"
      }
  }
---

# AMiner Deep Search

Host-model-driven survey paper collection. You (the model reading this) are the controller: run the tool scripts, read their JSON output, judge relevance yourself, and iterate until the collection target is met.

## Routing (read first)

| Task shape | Skill |
|---|---|
| Single lookup answerable by one free API (paper by title, scholar by name, venue/org normalization) | `aminer-free-academic` |
| Deep analysis of one entity, multi-condition search, or paper collection under ~50 papers | `aminer-academic-search` |
| Personalized paper recommendations | `aminer-daily-paper` |
| Large-scale candidate collection (50+ papers), survey bibliography construction, citation snowballing | **this skill** |

Do not trigger on the words "survey" / "literature review" alone; trigger on the *scale* of collection the user actually needs.

## Pre-flight

1. Check the key without printing it:

```bash
[ -z "${AMINER_API_KEY:-}" ] && echo "AMINER_API_KEY missing" || echo "AMINER_API_KEY exists"
```

If missing, stop and ask the user to set `AMINER_API_KEY` (console: https://open.aminer.cn/open/board?tab=control). Never print the key.

2. Confirm the `topic` and the `target-size` (default 400).

3. **Extract the user's hard constraints** — year range, venues, authors, institutions, language, exclusion terms, ranking goal (latest / impact / classic+latest). Record year range and required fields into the state file so `add` enforces them mechanically:

```bash
python3 scripts/paper_set.py init --topic "..." --year-from 2020 --year-to 2025 --require-fields year
```

Note: AMiner has no document-type filter (journal / conference / preprint); if the user requires one, say so and fall back to post-hoc venue filtering.

4. If your round plan is estimated to cost ¥5 or more, tell the user the estimate and get confirmation before starting.

## Tools

Both scripts live in `scripts/` under this skill directory. They print exactly one JSON document to stdout (the tool result); diagnostics and a `[cost]` line go to stderr. They never score relevance — that is your job.

### `scripts/aminer_api.py` — AMiner API calls

| Subcommand | Endpoint | Price |
|---|---|---|
| `search [--query Q] [--title T] [--abstract A] [--author NAME] [--org ORG] [--venue V] [--size 20] [--year-from Y] [--year-to Y] [--order n_citation\|year] [--max-pages 3]` | GET `/api/paper/search/pro` (100 results/page) + free `paper/info` enrichment | ¥0.01/page |
| `qa-search [--query "natural language question"] [--topic-high '[["termA","termB"],["termC"]]'] [--size 20] [--year-from Y] [--year-to Y] [--citation-sort]` | POST `/api/paper/qa/search` (always `use_topic=true`; the backend ignores `query` when `use_topic=false`) + free enrichment | ¥0.05/call |
| `qa-search-pro [--query Q] [--query-type auto\|topic\|keywords\|title\|identifier] [--authors ...] [--orgs ...] [--venues ...] [--year-from Y] [--year-to Y] [--languages en zh] [--all-terms ...] [--any-terms ...] [--exclude-terms ...] [--search-in all\|title\|title_keywords\|abstract] [--min-citations N] [--max-citations N] [--sort relevance\|balanced\|recent\|citation] [--size 10]` | POST `/api/paper/qa/searchPro` (10 results/page, cursor pagination) + free enrichment | ¥0.30/page |
| `info --ids id1 id2 ...` | POST `/api/paper/info` (batched ≤100 ids) | Free |
| `references --ids id1 id2 ... [--per-seed 20]` | GET `/api/paper/relation` per seed + free enrichment | ¥0.10/seed |

Choosing a search subcommand: `search` is the cheap bulk workhorse (¥0.01 per 100 results; fielded literal matching, year filtered client-side). `qa-search` handles natural-language questions cheaply. `qa-search-pro` is 30× the price of `search` per call and returns only 10 per page — reserve it for queries whose hard constraints `search` cannot express (language filter, exclusion terms, citation ranges, multi-value author/org/venue filters). Note: `qa-search-pro` must be enabled for the account; if it returns an HTTP 400 permission error, tell the user to enable the API in the AMiner console and fall back to `search`. If a cursor continuation page fails (the backend sometimes invalidates cursors mid-pagination), the script returns the pages already collected and prints a `[warning]` to stderr instead of failing — fewer results than `--size` after such a warning is expected, not an error.

`search` field notes: multiple fields combine with AND; matching is literal, so `--author` wants the full name ("Ashish Vaswani", not "Vaswani") — if a combined query returns 0, drop fields one at a time before giving up.

Output shape: search subcommands and `info` print `[{id, title, year?, venue?, authors?, doi?, n_citation_bucket?, abstract_slice?, url}]`; `references` additionally includes `source_paper_ids` (which seeds cited the paper). Seeds themselves are excluded from `references` output. `doi` is only available from `search` (the other endpoints do not return it).

### `scripts/paper_set.py` — cross-round state file (no network)

State file defaults to `outputs/paper_set.json` relative to the working directory. Dedup is three-way: AMiner ID, lowercased DOI, and normalized title — preprint and published versions merge into one record (published venue wins; alternate IDs kept in `alt_ids`).

```bash
# Record hard constraints once; `add` enforces them from then on
python3 scripts/paper_set.py init --topic "..." --year-from 2020 --year-to 2025 --require-fields year

# Merge kept results (pipe the filtered JSON array in); --source records provenance per paper
python3 scripts/aminer_api.py search --query "..." \
  | python3 scripts/paper_set.py add --source "search:..."
# → {"added": N, "duplicates": M, "merged_versions": K, "rejected": R, "reject_reasons": {...}, "total": T}

python3 scripts/paper_set.py stats     # totals, tiers, field completeness, by_year
python3 scripts/paper_set.py mark-expanded --ids id1 id2   # record snowballed seeds
python3 scripts/paper_set.py promote --ids id1 id2         # move papers to the curated tier
python3 scripts/paper_set.py log-round --queries "q1" "q2" --added N --rejected R  # trace
python3 scripts/paper_set.py export -o outputs/final_papers.json [--tier curated|candidate|all]
```

`add` also accepts `--ids id1 id2 ...` for bare IDs (note: bare IDs carry no year/title, so they are rejected when `init` requires those fields — pipe enriched JSON instead). Items carrying `source_paper_ids` (from `references`) automatically mark those seeds as expanded and get `references:<seed>` provenance entries.

If you want to filter before adding, read the search output first, then pipe only the kept items:

```bash
printf '%s' '[{"id":"...","title":"..."}]' | python3 scripts/paper_set.py add --source "search:..."
```

## Round Protocol (core)

### Round 0 — plan

- Derive 4–8 seed queries from the topic: synonyms, subfields, method names, datasets/benchmarks, common English abbreviations.
- Run `paper_set.py init` with the extracted hard constraints (see Pre-flight step 3).
- Pick the ranking strategy from the user's goal:
  - impact / foundational papers → `search --order n_citation`
  - latest work → `search --order year` (or `qa-search-pro --sort recent`)
  - **classic + latest** → run each seed query twice, once with `--order n_citation` and once with `--order year`, and merge (the set dedupes) — this stops new papers from being crowded out by highly cited ones
  - no stated preference → default composite ranking (omit `--order`)
- Estimate rounds and cost (search ≈ ¥0.01/page, qa-search ¥0.05, qa-search-pro ¥0.30/page, references ¥0.10/seed). If the estimate is ≥¥5, confirm with the user first.

### Each round (default budget: 12 rounds), six fixed steps

1. **Search**: run 1–4 `search` / `qa-search` calls from the pending query queue, passing the user's structured filters (`--author/--org/--venue/--year-from/--year-to`). Prefer `search` (cheapest); use `qa-search` for natural-language questions; use `qa-search-pro` only when a hard constraint (language, exclusion, citation range) cannot be expressed otherwise.
2. **Filter**: read the stdout results and judge topical relevance yourself. Hard constraints (year, required fields) are enforced by the state file; your job is the semantic judgment.
3. **Add**: pipe only the kept items into `paper_set.py add --source "search:<query>"`. Never add papers you consider off-topic. Check `rejected`/`reject_reasons` in the output — a high rejection rate means your queries are drifting out of the constraint window.
4. **Check**: run `stats` to see the total, tier counts, and field completeness.
5. **Snowball**: from this round's relevant additions pick ≤5 strong seeds (highly relevant, ranked high under `--order n_citation`, not in `expanded_seeds`) and run `references --ids ...`. Filter the output for relevance, then add it with `--source`. Run `mark-expanded` for seeds that yielded nothing addable.
6. **Log & decide**: run `log-round --queries ... --added N --rejected R` to append the trace, then choose the next move —
   - a search returned <5 results or poor quality → replace it with a reformulated query (max 2 variants per direction, then switch to snowballing);
   - references are yielding many relevant papers → keep snowballing from fresh seeds;
   - reached `target-size`, or results are exhausted, or 2 consecutive rounds added <5 papers → terminate.

### Wrap-up

Optionally `promote` the strongest papers to the curated tier. Run `export` (add `--tier curated` for a curated-only file), then report: final paper count, rejected/merged counts, total cost (sum the `[cost]` stderr lines), and the output path. The export carries full fields per paper (title, authors, year, venue, DOI when available, AMiner ID, URL, citation bucket, provenance `found_by`, tier) plus the constraints and the round trace.

## Error handling

The scripts print structured JSON errors and never mask them as empty results. An empty result set is a plain `[]` with exit code 0 — it is not an error.

| `error` value | Meaning | What to do |
|---|---|---|
| `missing_aminer_api_key` | env var not set | stop; ask the user to set it |
| `invalid_params` (40001) | bad request parameters | fix the call, don't retry as-is |
| `permission_denied` (40301) | key lacks permission / balance | stop; tell the user to check the console |
| `token_expired` (40302), `invalid_api_key` (40307), `invalid_token` (40308) | credential problem | stop; ask the user to renew the key |
| `rate_limited` (40306) | too many requests | slow down; the script already retried |
| `server_error` (50001), `http_error`, `network_error` | AMiner-side/transport failure | script retried 3×; report if persistent |

## Rules

1. Never fabricate paper IDs or titles; only cite data actually returned by the tools.
2. Free first: metadata always comes from the free `paper/info` (the scripts already do this); never call the paid `paper/detail` for bulk metadata.
3. Keep the raw tool output out of your final answer; report counts and the exported file path instead.
4. Never print or log `AMINER_API_KEY`.
5. If AMiner returns fewer papers than the target, report the real count instead of inventing papers.
6. Papers violating the user's hard constraints must never enter the result set — record constraints with `init` so this is enforced mechanically.
