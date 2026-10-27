---
name: paper-insight-classification
version: 0.1.0
author: Community contribution
description: >
  [Activation] Use this skill when the user gives a paper (PDF / Word / text) and asks how insightful it is relative to the literature it cites — e.g. "evaluate the insight of this paper", "how much does this paper add beyond its references", "extract and classify the opinion sentences", "compare the depth of human-written and AI-generated surveys", "评估论文的 insight / 洞察 / 见解", "抽取观点句并分类", or mentions InsightEval.
  [Capability] Implements the InsightEval method (SIGIR'26 demo). Scripts parse the paper into sentences with sections and citation markers and build labeling batches; the agent classifies every sentence as context / citation / opinion, then scores each opinion sentence against evidence from the references it cites on Depth / Breadth / Height (1-5) and types each section as descriptive / comparative / analytical. A final script produces a paper-level insight report (JSON / Markdown / CSV) with composite scores, low / medium / high levels, distributions, top and bottom sentences and caveats. Optional evidence lookup uses free scholarly APIs; no API key required.
  [Routing] Do NOT use this skill to check whether citations are faithful to their sources (`citation-faithfulness`), whether references exist (`pdf-citation-verifier`, `structured-reference-audit`), or to extract the reference list itself (`paper-reference-extraction`, whose `references.json` is the recommended input here). It judges the text relative to its cited references; it does not judge whether the experiments or conclusions are correct.
metadata:
  {
    "openclaw":
      {
        "emoji": "💡",
        "requires": {
          "bins": ["python3"],
          "env": []
        }
      }
  }
---

# Paper Insight Classification (InsightEval method)

Insight is not novelty: it is the **gain in understanding a paper provides over the references it cites**. The workflow follows the four stages of InsightEval:

1. **Sentences** — every sentence becomes `context` (background), `citation` (only summarizes prior work) or `opinion` (the author's interpretation, critique or synthesis).
2. **Evidence** — for each opinion sentence, collect the title and abstract of the references it cites.
3. **Scoring** — compare each opinion sentence with its evidence and score **Depth / Breadth / Height** (1–5); combine into a composite and a `low / medium / high` level.
4. **Report** — paper-level statistics, section types and levels, top and bottom sentences, an overall assessment.

Scripts do the parsing, batching, evidence lookup and aggregation. **You** do the classification and scoring, which need judgment. Read [references/rubric.md](references/rubric.md) before labeling: it has the definitions, edge cases, scoring anchors and worked examples.

## Requirements

- Python ≥ 3.10 and `pip install -r requirements.txt` (PyMuPDF).
- Input: `.pdf`, `.docx`, `.txt`, `.md`. Scanned PDFs need OCR first (e.g. `aminer-pdf-ocr`).
- Network only for the optional evidence lookup (`fetch_evidence.py`).

## Workflow

`<work>` is a working directory (e.g. `work/<paper-name>/`); script paths are relative to this skill directory.

### 0. (Recommended) Get structured references first

Run `paper-reference-extraction` to produce `<work>/out/references.json`. With it, evidence lookup uses verified titles instead of rule-based guesses.

### 1. Parse and batch

```bash
python scripts/prepare_sentences.py <paper.pdf> --references <work>/out/references.json -o <work>/sentences.json
```

Writes `sentences.json` and `<work>/stage1/batch_NNN.txt` (40 sentences each, in reading order). Read the summary: sentence count, citing sentences, rule-prior distribution, warnings. Zero sentences usually means a scanned PDF — say so.

### 2. Stage 1 — sentence types (you)

Read each `stage1/batch_NNN.txt` and write one `<work>/labels/stage1_NNN.json` per batch:

```json
{"range": [1, 40], "opinion": [3, 14, 16], "citation": [22, 23, 25]}
```

Ids inside `range` that are not listed are `context`; `range` declares which sentences the file covers, so a forgotten batch is flagged in the report. `rule=` is only a prior: review every `rule=opinion`, and watch for explanatory, comparative or critical sentences it missed.

### 3. (Optional, online) Fetch the cited abstracts

```bash
python scripts/fetch_evidence.py <work>/sentences.json --stage1 <work>/labels -o <work>/evidence.json
```

Looks up only the references used by opinion sentences (arXiv id → OpenAlex → Semantic Scholar). A record is accepted only when its title matches (similarity ≥ 0.9) and the year / first author do not contradict it; otherwise `matched=false`. The nearest other paper is never substituted. Without network access, or if you hold the cited papers' full text, write `evidence.json` yourself in the format of [references/output-schema.md](references/output-schema.md) (`passages` are supported). Skipping this step is allowed, but confidence will be lower and the report says so.

### 4. Build the scoring batches

```bash
python scripts/prepare_scoring.py <work>/sentences.json --stage1 <work>/labels --evidence <work>/evidence.json
```

Writes `<work>/stage2/batch_NNN.txt` (8 opinion sentences each, with the previous sentence and evidence excerpts), `stage2/plan.json` and `<work>/sections.txt`. For papers with many opinion sentences (> 60) add `--max-opinions 60` to sample evenly, and state in your final report that scoring was sampled.

### 5. Stage 2 — three-dimension scoring (you)

Read each `stage2/batch_NNN.txt`. For every opinion sentence: compare it with the evidence, write a rationale, then give integer `depth` / `breadth` / `height` (1–5) and a `confidence`. One file per batch, `<work>/scores/stage2_NNN.json`:

```json
[{"id": 18, "depth": 2, "breadth": 3, "height": 4, "confidence": "medium",
  "rationale": "Against R10 and R18: generalizes two novelty-assessment papers into 'relative understanding gain'; the abstracts do not state that framing. Cannot tell how many sources were really synthesized."}]
```

Discipline (details in the rubric): compare only with the evidence; reward added content, not confident tone; anything the evidence already states scores Depth ≤ 2; with no evidence set `confidence: low` and never give a 5; name the `R#` you compared against in the rationale.

### 6. Section types (you)

Read `<work>/sections.txt` and type each listed section `descriptive`, `comparative` or `analytical`; write `<work>/labels/sections.json`:

```json
{"2": "analytical", "4": "descriptive"}
```

Keys are section `idx` values. Only listed sections (with citations, ≥ 3 sentences) enter the section-type statistics.

### 7. Aggregate, add an overall assessment, re-run

```bash
python scripts/aggregate_insight.py <work>/sentences.json --stage1 <work>/labels --scores <work>/scores \
  --sections <work>/labels/sections.json --summary <work>/summary.md --outdir <work>/out
```

On the first run `summary.md` does not exist yet and the report shows a placeholder. Read the statistics, section table and top / bottom sentences, write a 3–5 sentence overall assessment (which dimension leads, strong and weak sections, how solid the evidence was, the caveats that must travel with the numbers), save it as `<work>/summary.md`, and run the same command again. Outputs: `insight_report.json`, `insight_report.md` (language follows the paper; `--lang zh|en` overrides), `insight_sentences.csv`. Optional: `--weights 1,1,1`, `--thresholds 2.5,3.5`, `--top-k 5`.

### 8. Report to the user

Give: paper title, sentence-type distribution, number of scored opinion sentences (and whether sampled), composite score and level, the three dimension means and the profile, section type / level distributions, the 2–3 highest and lowest opinion sentences with rationales, **every caveat** (evidence coverage, share of `confidence=low`, default thresholds), and the output paths. Frame it as "insight signal relative to the cited references", not a verdict on the paper.

## Conventions

- Composite = weighted mean of the three scores (equal weights by default, kept on the 1–5 scale). Levels: `< 2.5` low, `< 3.5` medium, otherwise high. The paper reports level shares but publishes no thresholds, so these are this skill's defaults — say so when you report.
- For orientation, the paper's Table 1 (survey papers, Qwen3-32B) has means around Depth 2.9–3.0, Breadth 2.5, Height 2.8–3.0.

## Related skills

- `paper-reference-extraction` — produces the `references.json` used in step 1.
- `citation-faithfulness` — asks whether a citation is *supported* by its source; this skill asks what the author *adds* beyond the sources. The two are complementary; do not mix their conclusions.

## Development

Scripts need only the standard library plus PyMuPDF (through the vendored parser in `scripts/pdfparse/`).

```bash
python -m pytest tests -q
```
