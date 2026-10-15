---
name: sota-finder
version: 1.0.0
author: AMiner
contact: report@aminer.cn
description: >
  Find recent or historical state-of-the-art results and build practical, source-aware leaderboards for a task or benchmark. Use for benchmark surveys, cross-paper result comparison, open-world SOTA discovery, or structured leaderboard artifacts from natural language, papers, URLs, repositories, tables, and existing result files. Keep comparable results in the main leaderboard and useful non-comparable candidates in a clearly labeled reference section.
  Do NOT use this skill for a general literature review with no result comparison, or for extracting one supplied paper's tables without broader SOTA discovery.
metadata:
  {
    "openclaw":
      {
        "emoji": "🏆",
        "requires": {
          "bins": ["python3"],
          "env": []
        }
      }
  }
---

# SOTA Finder

Find the useful answer first. Evidence supports the leaderboard; it must not crowd out the result.

## Route the request

Choose the lightest effort that can answer the user:

- `direct`: no real leaderboard research is needed, or supplied material already answers the request. Reply in chat; create files only when requested.
- `quick`: one named benchmark or narrow scope with an accessible official or primary results surface.
- `standard`: the default for several sources, multiple obvious scopes, a supplied seed, or a practical model-selection question.
- `deep`: no unified benchmark, broad historical coverage, many competing scopes, or consequential deployment and reproduction constraints.

Treat inputs and tools as independent branches: use supplied files and URLs first; an offline-only request disables web research; AMiner is optional. Unless the user restricts sources, search externally by default. Reserve enough time to synthesize and deliver instead of spending the whole run on discovery.

## Research and build the leaderboard

1. Search the task name, full name, abbreviation, aliases, datasets, metrics, and major subtasks. Cover official leaderboards or benchmark pages, papers and preprints, author repositories or model cards, and aggregators. Use aggregators to discover candidates, then verify important rows from stronger sources when practical.
2. Cover the material scopes before deepening one of them. Split suites, subtasks, test sets, metric variants, and materially different settings when a single ranking would be misleading. There may be no universal winner.
3. Classify each useful result:
   - **Main Leaderboard**: same benchmark or dataset, split, metric, direction, and material evaluation setting, with a numeric score and a credible row-level source.
   - **Reference Results**: useful recent or historical candidates that are not directly comparable, are only partially verified, or use a different protocol.
   - **Conflicts / Unavailable**: contradictory, corrected, withdrawn, or inaccessible claims that affect interpretation.
4. Prefer official result pages and primary artifacts for ranking claims. Record enough source, date, method, score, setting, code or weight availability, and practical constraints to explain the conclusion. Leave noncritical fields unknown rather than withholding useful results.
5. Stop expanding when further checks are unlikely to change an important leader, scope, conflict, or practical recommendation. State only limitations that materially change interpretation.

For a known public HTML, JSON, CSV, XML, or text result endpoint whose rows are hard to read with native tools, the optional bounded helper can save one local copy:

```bash
python3 "<skill-root>/scripts/fetch_source.py" "<URL>"
```

Do not turn this helper into a crawler or delay delivery to write one-off scraping infrastructure.

## AMiner

AMiner may help with paper discovery, metadata, and related work, but it never replaces official pages, papers, repositories, or general web research. The Skill must start and finish without AMiner. Before paid or uncertain calls are expected to total about CNY 5 or more, ask once for confirmation.

## Build the artifacts

Skip artifacts for `direct` unless the user requests them. Otherwise prepare one working JSON file outside the final output directory using [references/data-contract.md](references/data-contract.md), then validate and build:

```bash
python3 "<skill-root>/scripts/build_outputs.py" \
  --input "/path/to/research-input.json" \
  --output-dir "/path/to/output/bundle" \
  --validate-only
python3 "<skill-root>/scripts/build_outputs.py" \
  --input "/path/to/research-input.json" \
  --output-dir "/path/to/output/bundle"
```

Install `requirements.txt` if `openpyxl` is unavailable. The final directory contains:

- `brief-report.md`: concise expanded report;
- `full-report.html`: complete self-contained report;
- `leaderboards.xlsx`: index plus leaderboard sheets;
- `evidence.json`: structured results and evidence.

Fix concrete validation errors in the working JSON and rebuild. If an artifact fails, still return the useful chat result and identify the missing file.

## Chat response

Lead with the conclusion the user wants: the best-supported leader by scope, whether no single comparable winner exists, and the most practical reproducible option when relevant. Then:

1. show the main leaderboard for every material scope; show the full table when it is still easy to scan;
2. mention important non-comparable paper, preprint, repository, or aggregator candidates compactly;
3. include only metric, cutoff-date, conflict, or coverage notes that can change the conclusion;
4. link the four artifacts when they were created.

Use plain language. Keep evidence IDs, search logs, routine validation, and defensive boilerplate out of chat. Preserve practical information that can change selection or deployment, including code or weights, license, hardware, cost, and material settings.

## Boundaries

Use the user's language for visible prose while keeping JSON keys, IDs, enum values, metric names, and other stable machine fields in English. Do not mix materially incomparable results into one main ranking, invent missing scores, or build a universal benchmark rule database inside the Skill.
