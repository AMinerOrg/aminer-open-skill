---
name: paper-source-trace
version: 1.0.0
author: AMiner
contact: report@aminer.cn
description: >
  Use when a user provides an academic paper PDF, extracted paper text, citation contexts, or references and asks for paper source tracing, claim-centered source tracing, citation intent extraction, entity/relation extraction, contribution mapping, citation graph JSON, SVG/HTML citation maps, or optional AMiner metadata/citation enrichment.
  Do NOT use this skill for simple paper lookup by title, scholar search, or lightweight academic queries — use aminer-free-academic or aminer-academic-search for those instead.
metadata:
  {
    "openclaw":
      {
        "emoji": "🧭",
        "requires": {
          "bins": ["python3"],
          "env": []
        },
        "primaryEnv": "AMINER_API_KEY"
      }
  }
---

# Paper Source Trace

Paper Source Trace turns one target paper into grounded, claim-centered source-tracing artifacts. It keeps one canonical skill name, `paper-source-trace`.

Invoke it through natural language or `/paper-source-trace`.

## Language Routing

- Use `SKILL.zh.md` when the user mainly writes in Chinese or explicitly requests Chinese output.
- Use this `SKILL.md` for all other requests.
- Keep `json/graph/citation_graph.json` keys, intent labels, relation types, source roles, and parameter names in English in both workflows.

## English Workflow

### Standard Artifacts

Produce these artifacts when evidence and filesystem access allow:

- `analysis.md`: human-readable report.
- `json/graph/citation_graph.json`: canonical machine-readable graph following `references/schema.md`.
- `citation_map.svg`: static citation map when SVG generation is possible.
- `citation_map.html`: single-file interactive graph when graph data is available.
- `citation_map_chain.svg`: chain-style source trace SVG only when `svg: both`.
- `citation_map_spec.md`: only when SVG generation has caveats or fails.

Default output directory:

```text
outputs/paper-source-trace/<safe-paper-stem>/
```

Preferred layout:

```text
analysis.md
citation_map.svg
citation_map.html
citation_map_chain.svg          # only when svg is both
citation_map_spec.md            # only when SVG generation has caveats or fails
json/graph/citation_graph.json
json/aminer/*.json              # only when AMiner raw results are saved
json/extraction/*.json          # only when structured intermediates are saved
```

Legacy compatibility: if the user writes `mode: current`, treat it as `svg: radial`; `mode: example` as `svg: chain`; and `mode: all` as `svg: both`. If `svg` and `mode` are both supplied and conflict, ask the user to confirm the intended SVG output. `hybrid`, `interactive graph`, or `expandable knowledge graph` means the user wants the standard `citation_map.html`; it is not an SVG mode and does not change the SVG choice.

### Startup Confirmation

Before reading the paper, extracting citations, checking `AMINER_API_KEY`, calling AMiner, or generating SVG, ask the user to confirm:

- SVG output: `radial`, `chain`, or `both`.
- AMiner enrichment: `on` or `off`.

If the user already supplied one or both values, restate them as provisional and still ask for final confirmation. Stop until the user answers.

If interactive confirmation is genuinely impossible, use the recommended defaults: `svg: both` and `aminer: on`. Still follow the high-cost confirmation rule before any AMiner call estimated at `¥5` or more; if `AMINER_API_KEY` is missing, skip AMiner enrichment and continue local analysis.

### Core Rules

1. Use only supplied paper text, citation contexts, reference entries, user notes, or explicitly requested AMiner results as evidence.
2. Do not infer citation intent from domain memory alone.
3. AMiner enrichment is explicit opt-in only. Do not check `AMINER_API_KEY` unless requested.
4. AMiner may enrich IDs, URLs, candidate reference matches, and external citation relationships, but it cannot replace local citation contexts or prove intent/source traces by itself.
5. Preserve uncertainty; lower confidence when citation context, reference matching, or source role evidence is incomplete.
6. Keep `citation_sentence` and `context` in the source language of the target paper. They are original evidence anchors, not localized explanations.
7. Use the user's output language for `evidence`, `summary`, `notes`, Markdown report text, and visible SVG/HTML UI.
8. If output files can be written, do not stop at a chat-only summary.

### AMiner Enrichment

When confirmation is possible, treat AMiner as `off` unless the user confirms `aminer: on` or explicitly writes `enhance with AMiner`, `use AMiner metadata`, `complete paper_id`, or `trace AMiner citation relationships`. When confirmation is genuinely impossible, the recommended fallback is `aminer: on`.

When enabled:

1. Check only whether `AMINER_API_KEY` exists; never print the token.
2. If missing, continue local analysis and record that enrichment was skipped.
3. Use the shortest viable chain: `paper_search` or `paper_search_pro`, `paper_detail`, `paper_relation`, and `paper_info`.
4. Output a cost summary for all planned or completed AMiner calls.
5. If estimated cost is `¥5` or more, ask for explicit confirmation before paid calls.
6. Record enrichment metadata under `metadata.aminer_enrichment` in `json/graph/citation_graph.json`.

### Intent Labels

Use only these labels unless the user explicitly extends the taxonomy:

`background`, `problem`, `core-method`, `supporting-method`, `dataset`, `metric`, `baseline`, `tool-resource`, `theory`, `result-evidence`, `limitation`, `future-work`.

### Execution Steps

1. Ask the startup confirmation question and wait for the answer.
2. Resolve input evidence and output directory.
3. Extract reliable paper text, reference entries, and citation contexts.
4. Read `references/evidence_protocol.md` before important classification or source tracing.
5. Classify citations with the allowed intent labels.
6. Extract key target-paper claims or contributions when supported by text.
7. Build `source_traces[]` by linking claims to local citation contexts, cited-source roles, and evidence steps.
8. Extract entities and relations that explain the target paper.
9. If AMiner is enabled, enrich metadata without replacing local evidence.
10. Write `json/graph/citation_graph.json` before visual artifacts.
11. Write `analysis.md`; use `references/analysis_template.md` only for explicit template or fixed-format requests.
12. Generate `citation_map.html` and the confirmed SVG output with one renderer command: `python3 scripts/render_html.py --graph <output>/json/graph/citation_graph.json --output <output>/citation_map.html --svg <radial|chain|both> --language auto`.
13. Do not hand-write ad hoc SVG or HTML; both static SVG modes and the HTML `radial / chain` views must share the renderer layout, colors, language pack, text wrapping, node priority, and edge rules.
14. Validate artifacts before the final reply.

### Reference Files

- `references/schema.md`: canonical schema and JSON example.
- `references/evidence_protocol.md`: evidence and uncertainty rules.
- `references/prompts.md`: English and Chinese extraction/review prompts.
- `references/visual.md`: SVG and HTML graph rules.
- `references/analysis_template.md`: fixed report templates for explicit template mode.
- `scripts/render_html.py`: standard graph renderer. Use it for `citation_map.html`, `citation_map.svg`, and `citation_map_chain.svg`; do not hand-write ad hoc SVG or HTML.

### Quality Checks

- Every citation has `intent`, `evidence`, `confidence`, and either `reference_id` or `unmatched_reference: true`.
- Every intent label is in the allowed list.
- Key citations trace back to a citation sentence or local context.
- `citation_sentence` and `context` preserve the target paper's original language; only explanation fields are localized.
- Every entity is supported by at least one citation.
- Every source trace is grounded in at least one local citation context; AMiner metadata cannot be the sole support.
- Generate `citation_map.html` and SVG maps with `scripts/render_html.py` after `json/graph/citation_graph.json` is written. HTML and SVG must use one visible language, the same canonical group labels, the same node ranking, and the same reduced-edge layout strategy.
- Static SVG should use only useful main edges, summarize dense groups with `+N`, and avoid citation-to-citation cross-links or AMiner-only relation lines.
- `json/graph/citation_graph.json` remains complete even if Markdown, SVG, or HTML has caveats.
