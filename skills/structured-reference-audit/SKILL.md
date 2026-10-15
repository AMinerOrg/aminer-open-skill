---
name: structured-reference-audit
version: 0.1.0
author: Community contribution
description: >
  Build an auditable reference ledger from a paper PDF with GROBID, then resolve
  structurally parsed entries through AMiner. Use when a user needs conservative
  reference-existence checking rather than a direct PDF-level FAKE verdict.
---

# Structured Reference Audit

Use this skill to check whether references can be resolved to scholarly records
without confusing PDF parsing failures with fabricated citations. It is a
companion to `pdf-citation-verifier`, not a replacement for AMiner's server-side
PDF verifier.

```text
PDF or GROBID TEI
-> GROBID bibliography entries
-> Reference Ledger: raw entry, page anchor, title/DOI/arXiv, parse warnings
-> AMiner title lookup per eligible entry
-> verified_exists / needs_human_review / not_found_in_aminer
```

## Requirements

- Python dependency: `pip install -r requirements.txt`
- For `--pdf`: a running GROBID service, default `http://127.0.0.1:8070`.
  GROBID is external and optional: users with existing TEI may pass `--tei`.
- `AMINER_API_KEY` is required for AMiner resolution, but not for parser-only
  `--skip-resolve` runs. Never print or write the token.

## Run

```bash
python3 scripts/structured_reference_audit.py \
  --pdf "/abs/path/paper.pdf" \
  --output "reference-ledger.json"
```

For a parser-only diagnostic:

```bash
python3 scripts/structured_reference_audit.py \
  --tei "/abs/path/paper.tei.xml" \
  --skip-resolve \
  --output "reference-ledger.json"
```

## Interpret Results Conservatively

- `verified_exists`: AMiner returned a high-similarity title match.
- `needs_human_review`: parsing, matching, or network evidence is insufficient.
- `not_found_in_aminer`: AMiner returned no adequate title candidate. It does
  **not** establish that the reference is fabricated.
- `parse_quality_insufficient`: do not resolve entries or issue reference-level
  conclusions until the PDF/TEI parse is inspected.

Do not label an author dishonest from this output. Keep parser fragments in the
ledger for inspection and present unresolved entries as a human review queue.
