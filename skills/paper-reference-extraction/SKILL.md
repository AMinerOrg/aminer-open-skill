---
name: paper-reference-extraction
version: 0.1.0
author: Community contribution
description: >
  [Activation] Use this skill when the user gives a paper (PDF / Word / text) and wants its reference list turned into structured data — e.g. "extract the references of this paper", "convert the bibliography to BibTeX / JSON", "which papers does this PDF cite", "find uncited or duplicate references", "提取/解析/结构化这篇论文的参考文献", "把参考文献转成 BibTeX".
  [Capability] A rule-based script parses the PDF layout, splits the reference section, extracts DOI / arXiv / URL / year, and records where each reference is cited in the body. The agent then fills title / authors / venue / kind from each entry's raw text, and a second script verifies that every field is grounded in that raw text (anything the raw text does not contain is dropped) and exports references.json, references.bib and references.md. Runs locally; no API key, no network.
  [Routing] Do NOT use this skill to decide whether a reference EXISTS or is fabricated (`pdf-citation-verifier`, `structured-reference-audit`), or whether a citation is faithful to its source (`citation-faithfulness`). It only extracts and structures what the paper itself prints. Its output (`references.json`) is a good input for those skills and for `paper-insight-classification`.
metadata:
  {
    "openclaw":
      {
        "emoji": "📚",
        "requires": {
          "bins": ["python3"],
          "env": []
        }
      }
  }
---

# Paper Reference Extraction

Turn the reference list of a paper into **grounded, structured records**. Scripts do the deterministic work (layout parsing, splitting, DOI / arXiv / URL / year extraction, in-text citation statistics); **you** read each entry's raw text and fill in title, authors, venue and type; a validator then drops every field that the raw text does not support.

What it does not do: no web lookups, no existence checks (use `pdf-citation-verifier` / `structured-reference-audit`), no faithfulness judgments (use `citation-faithfulness`).

## Requirements

- Python ≥ 3.10 and `pip install -r requirements.txt` (PyMuPDF).
- Input: `.pdf`, `.docx`, `.txt`, `.md`. Scanned PDFs have no text layer and need OCR first (e.g. `aminer-pdf-ocr`).
- `scripts/pdfparse/` is a vendored layout-aware paper parser (PyMuPDF); no other dependencies.

## Workflow

`<work>` is a working directory of your choice (e.g. `work/<paper-name>/`); script paths are relative to this skill directory.

### 1. Extract the raw entries

```bash
python scripts/extract_references.py <paper.pdf> -o <work>/references.raw.json
```

Read the printed summary: number of references, DOI / arXiv / URL / year hits, citing sentences, listed-but-uncited ids, dangling markers, warnings.

| Situation | What to do |
| --- | --- |
| Far fewer references than expected, or the warning "could not be split by rules" | Read `references_text` in the JSON, split it by hand, and write the entries back into the `references` array as `{"id": n, "label": "[n]", "raw": "…", "doi": "", "arxiv": "", "url": "", "year": null}`; then continue |
| No extractable text | Scanned PDF. Tell the user it needs OCR. Never reconstruct a bibliography from memory |
| Author-year citation style | `cite_count` / `uncited` are matched by surname + year and are best-effort |

### 2. Structure the entries (your job)

Read `references.raw.json` and, **in batches of at most 15 entries**, fill the fields below from each entry's `raw`. Save a JSON array as `<work>/enriched.json` (or several files in `<work>/enriched/`):

```json
[{"id": 1, "title": "", "authors": ["", ""], "year": 2020, "venue": "", "doi": "", "arxiv": "", "url": "", "kind": "conference",
  "volume": "", "issue": "", "pages": "", "publisher": ""}]
```

Field rules:

- `title` — the work's own title in its original language, without quotes, authors, venue or year. Leave it empty if unsure; do not guess.
- `authors` — full names in the printed order. If the raw text says `et al.` / `等`, stop there; **never complete the list from memory**. Keep GB/T 7714 style `Vaswani A` as printed.
- `year` — an integer that appears in the raw text (`2020a` → 2020).
- `venue` — journal / conference / publisher / preprint server, copied **verbatim**; do not expand abbreviations.
- `doi` / `arxiv` / `url` — only if printed in the raw text. **Never fill a DOI from memory.** Entries already carry rule-extracted values; copy them or leave blank.
- `kind` — `journal | conference | preprint | book | thesis | report | web | software | dataset | other`. Cues: GB/T 7714 markers `[J] [C] [M] [D] [R] [EB/OL]`, "In Proceedings…", "arXiv preprint", "Ph.D. thesis", URL-only web pages or repositories.
- `volume` / `issue` / `pages` / `publisher` — optional, again only if printed.
- Entries with `hints: ["link_may_be_truncated"]` have a DOI/URL that was probably cut by a line wrap; check the original page text before trusting its tail.

### 3. Validate, merge, export

```bash
python scripts/finalize_references.py <work>/references.raw.json --enriched <work>/enriched.json --outdir <work>/out
```

This writes `references.json` (full result), `references.bib` and `references.md`, and prints every dropped field, every entry whose quality is not `complete`, and possible duplicates. Use `--lang zh|en` to force the language of `references.md` (default: the paper's language).

- Do not re-insert a dropped field in another form. If the validator rejected something that really is in the raw text (for example a title broken by hyphenation), check the raw text, fix `enriched.json`, and re-run.
- Entries without a grounded title get a rule-based placeholder title flagged `title_fallback`; say so when you report.

### 4. Report to the user

Give a short summary: paper title, number of references, quality distribution (complete / partial / poor), DOI and arXiv coverage, listed-but-uncited / dangling / duplicate entries, dropped fields, and the paths of the three outputs. Show the first 3–5 structured records so the user can spot-check.

## Output

See [references/schema.md](references/schema.md). Each record in `references.json` is a superset of a plain reference (`id, label, title, authors, year, venue, doi, arxiv, url, kind, raw`) with `volume / issue / pages / publisher / cite_count / cited_in / quality / issues` added, so it can feed other skills directly — for example `paper-insight-classification --references`.

## Known Limitations

- Two-column layouts, page breaks and footnote-style citations depend on the vendored parser; unusual layouts can be mis-split. If the count does not match the largest number cited in the text, suspect the split before the paper.
- Pure-number lines inside the reference section are treated as page numbers and filtered, so a DOI/URL whose tail wrapped onto its own line (e.g. `…emnlp.` followed by `259`) can lose that tail.
- Nothing is looked up online: whether a record is a real publication is a job for the verification skills.

## Development

```bash
python -m pytest tests -q
```
