# Output schema

## `references.raw.json` (extract_references.py)

```jsonc
{
  "source": {"file": ".../paper.pdf", "type": "pdf|docx|text", "pages": 6, "title": "...", "lang": "en|zh"},
  "citation_style": "numeric | author-year | superscript | unknown",
  "stats": {
    "references": 27, "citing_sentences": 25,
    "uncited_ref_ids": [15],          // in the list but never cited in the body (only reported when citation markers were matched)
    "dangling_markers": [31],         // cited in the body but missing from the list (numeric style)
    "with_doi": 7, "with_arxiv": 9, "with_url": 16, "with_year": 27
  },
  "warnings": ["..."],
  "references": [
    {
      "id": 1, "label": "[1]", "raw": "full text of the entry",
      "doi": "", "arxiv": "", "url": "", "year": 2025,        // rule-based extraction
      "title": "", "authors": [], "venue": "", "kind": "",     // empty: you fill them in
      "hints": ["link_may_be_truncated"],
      "cite_count": 3,
      "cited_in": [{"citation_id": 4, "section": "Introduction", "page": 1, "sentence": "..."}]   // at most --samples items
    }
  ],
  "references_text": "raw text of the reference section (only when no entries were split or there are warnings)"
}
```

## `enriched.json` (written by the agent)

An array with one object per reference. `id` is required; every other field may be omitted (omitted = not provided, not "empty").

| Field | Type | Grounding check (must be supported by `raw`) |
| --- | --- | --- |
| `title` | string | normalized title is a substring of the raw text, or ≥ 90 % of its words occur in it |
| `authors` | string[] | each author's surname (longest name fragment) occurs in the raw text; `et al.` entries are dropped |
| `year` | int | 1900–2100 and the digits occur in the raw text |
| `venue` | string | normalized venue is a substring of the raw text, or ≥ 80 % of its words occur in it |
| `doi` | string | looks like `10.xxxx/...` and occurs in the raw text (whitespace ignored) |
| `arxiv` | string | new-style `2104.08836` or old-style `cs/0112017`, occurring in the raw text |
| `url` | string | starts with http and occurs in the raw text (whitespace ignored) |
| `volume` `issue` `pages` `publisher` | string | occurs in the raw text (whitespace ignored) |
| `kind` | enum | `journal conference preprint book thesis report web software dataset other`; inferred from cues when omitted |

## `references.json` (finalize_references.py)

Same top level as `references.raw.json`; each `references[]` item becomes:

```jsonc
{
  "id": 1, "label": "[1]", "title": "...", "authors": ["..."], "authors_truncated": false,
  "year": 2025, "venue": "...", "doi": "", "arxiv": "", "url": "", "kind": "conference",
  "volume": "", "issue": "", "pages": "", "publisher": "",
  "raw": "...", "cite_count": 2, "cited_in": [],
  "title_source": "agent | source | fallback",
  "enriched": true,
  "quality": "complete | partial | poor",
  "issues": ["no_authors", "fields_dropped:doi,venue", "title_fallback", "uncited", "duplicate_of:3", "link_may_be_truncated"]
}
```

`quality`:

- `complete` — title, authors, year and a locator (venue / DOI / arXiv / URL), and the title is not a fallback guess
- `partial` — a title plus at least one of authors / year
- `poor` — anything else

Top-level `stats` additionally has `quality` (counts per level), `agent_enriched`, `needs_review`, `duplicates`, `unknown_enriched_ids`.

## `references.bib`

`journal → @article`, `conference → @inproceedings`, `book → @book`, `thesis → @phdthesis`, `report → @techreport`, everything else `@misc`. Keys are `surname + year + first title word` (de-duplicated with letter suffixes). `note` carries `ref id N`, plus "needs manual review" when quality is not `complete`. Author lists truncated by `et al.` end with `and others`.

## `references.md`

Summary table (first 3 authors, title, venue, DOI/arXiv/URL, kind, cite count, quality) plus a list of entries that need attention. Use `--lang zh|en` to choose the language.
