---
name: citation-faithfulness
version: 1.1.0
author: AMiner
contact: report@aminer.cn
description: >
  [Activation] Use this skill when the user gives a paper PDF and asks whether its in-text citations are FAITHFUL to what the cited sources actually say — e.g. "check if this paper misrepresents its references", "does citation [12] actually support this claim", "verify the citations are not distorting the sources", "核查引用是否忠于原文", "有没有曲解参考文献".
  [Capability] Reads the PDF locally (Read tool), extracts every in-text citation together with the specific claim it supports, retrieves each cited source from the open web (WebSearch/WebFetch; arXiv full text or abstract), and has the agent judge each claim–source pair as SUPPORTED / PARTIALLY_SUPPORTED / NOT_SUPPORTED / NOT_IN_SOURCE / UNVERIFIABLE, with an evidence quote and confidence. No API key required.
  [Routing] Do NOT use this skill to check whether a reference EXISTS / is hallucinated (a real paper vs a fabricated one) — that is `pdf-citation-verifier`. Do NOT use it for general paper search (`aminer-free-academic` / `aminer-academic-search`) or citation-intent graphing (`paper-source-trace`). This skill answers one question only: does the cited source actually back up the claim the paper attaches to it.
metadata:
  {
    "openclaw":
      {
        "emoji": "🔎",
        "requires": {
          "bins": [],
          "env": []
        },
        "primaryEnv": "AMINER_API_KEY"
      }
  }
---

# Citation Faithfulness Checker

Verify whether the in-text citations in a paper PDF are **faithful to the original sources**. For each place the paper says "according to [X], …" or "[X] reports …", this skill retrieves what X actually says and judges whether the paper's claim is genuinely supported — catching **misrepresentation, reversed conclusions, wrong attribution, mismatched numbers, and claims the source never made**.

This is **agent-driven**: there is no upload service and no bundled script. Claude reads the PDF, retrieves sources with its own web tools, and applies the judging rubric itself. Invoke via natural language or `/citation-faithfulness`.

## What This Skill Does vs. Does Not

| | This skill (`citation-faithfulness`) | `pdf-citation-verifier` |
| --- | --- | --- |
| Question | Does the cited source actually **support the claim**? | Does the reference **exist** at all? |
| Catches | Distortion, reversed meaning, wrong numbers, over-claiming | Ghost references, fabricated DOIs |
| Method | Read PDF + web-retrieve source + agent judges | Upload PDF to AMiner service |
| Key | none required | needs `AMINER_API_KEY` |

If the user actually wants existence/hallucination checking, stop and route them to `pdf-citation-verifier`.

## Verdict Labels

Each checked claim–source pair gets exactly one verdict (keep the English label in JSON/tables; explain in the user's language):

- `SUPPORTED` — the source clearly states what the paper attributes to it.
- `PARTIALLY_SUPPORTED` — the source supports part of the claim but the paper overstates, narrows, or adds qualifiers the source did not make.
- `NOT_SUPPORTED` — the source addresses the topic but says something different or opposite (a genuine misrepresentation).
- `NOT_IN_SOURCE` — the retrieved source (full text) simply does not contain the claimed fact/result.
- `UNVERIFIABLE` — the source could not be retrieved, or only an abstract was available and the claim targets a detail the abstract does not cover. **This is not an accusation** — it means "we could not check", not "the citation is wrong".

Each verdict carries: an `evidence` quote from the source (in the source's original language), a short `reason` in the user's language, a `retrieval_level` (`full_text` / `abstract_only` / `metadata_only` / `not_found`), and a `confidence` (high / medium / low). See `references/rubric.md` for the full decision policy.

## The Hard Limit — read this to the user once

Open-web retrieval frequently yields **only an abstract**, not the full body of the cited paper (paywalls, closed PDFs). Consequences you MUST honor:

- If a claim cites a number/figure/detail that lives deep in the source body and you only obtained the abstract → verdict is `UNVERIFIABLE`, never `NOT_SUPPORTED`. Do not convict a citation you could not actually read.
- This skill reliably catches **abstract-checkable** errors (reversed conclusions, wrong attribution, headline-number mismatches, claims contradicted by the abstract). It cannot guarantee catching errors buried in paywalled body text.
- The user's local Zotero library would give full text and a much stronger check, but this skill is configured for **web-only** retrieval by design.

## File Map

- `SKILL.md` / `SKILL.zh.md` — English / Chinese skill definitions (this file).
- `commands/citation-faithfulness.md` — slash command entry.
- `references/rubric.md` — the 5-verdict decision rubric (adapted from `paper-source-trace`'s evidence protocol).
- `references/output-schema.md` — the return-value contract: exact JSON shape of the report (top-level object + per-claim record + invariants).
- No scripts, no `requirements.txt`: this skill uses only the Read, WebSearch, and WebFetch tools.

## Pre-flight

Before running, confirm:

1. **PDF input** — the user supplied an existing local `.pdf` path. If they only named a paper without a file, ask for the path. **Never invent or download a paper to check.**
2. **Tools available** — this skill needs `Read`, `WebSearch`, and `WebFetch`. If the environment has no web access, stop and tell the user: faithfulness checking requires retrieving the cited sources; without web access only `UNVERIFIABLE` verdicts are possible.
3. **Scope expectation** — full coverage of a 40-reference paper means ~40+ web retrievals. Warn the user and offer to scope (see Parameters) before a large run.

`AMINER_API_KEY` is **optional**. If it is set, you MAY use `GET https://datacenter.aminer.cn/gateway/open_platform/api/paper/search?title=...` (headers `Authorization: ${AMINER_API_KEY}`, `X-Platform` = current host: `claude-code` / `cursor` / `codex` / `openclaw` / `unknown`, `X-Skill-Name: citation-faithfulness`, `X-Skill-Version` = this file's frontmatter `version`) to resolve a reference's DOI/abstract faster. This is enrichment only — the skill runs fully without it. Never print the token value.

## Procedure

Run these five stages in order. Do the work with your own tools; do not fabricate any stage.

### S0 — Ingest the PDF

Read the PDF with the `Read` tool. It renders up to 20 pages per call; for longer papers read in page ranges (e.g. `pages: "1-20"`, then `"21-40"`). Make sure you capture both the **body text** and the **reference list** (usually the last pages). If extraction is noisy (two-column tables, ligatures), note it — noisy extraction lowers confidence, per the rubric.

### S1 — Extract claim–citation pairs

Walk the body text and, for every in-text citation, record the **specific claim it supports** — not just that a citation exists. Build a list of:

```
{ claim_id, claim_text, citation_sentence, section, cited_refs: [marker...], claim_type }
```

- `citation_sentence` — the sentence where the citation appears, in the paper's **original language** (do not translate it).
- `claim_type` — one of:
  - `specific` — a fact, number, dataset, result, or method attributed to the source (**high priority, most verifiable**).
  - `method` — "we adopt / extend the approach of [X]".
  - `background` — general pointer / prior-work gesture (**low verifiability; a bare "see [X]" is often not a checkable claim** — mark it and deprioritize).

Prioritize `specific` claims. A background pointer with no attributed content should be listed but usually resolves to `UNVERIFIABLE` (nothing concrete to check) — say so rather than inventing a claim.

### S2 — Resolve the reference list

Map each in-text marker (`[12]`, `(Smith et al., 2021)`, superscript, etc.) to its full reference entry → title, authors, year, venue, DOI, arXiv id. **Deduplicate by cited work**: if `[12]` is cited five times, retrieve it once and reuse the source for all five claims. If a marker cannot be matched to a reference entry, flag `unmatched_reference: true` and set that claim `UNVERIFIABLE`.

### S3 — Retrieve each source from the web

For each **unique** cited work, retrieve the source, in this priority order, and record the `retrieval_level` you achieved:

1. **arXiv** — if the entry has an arXiv id or an arXiv search hits: `WebFetch https://arxiv.org/abs/<id>` for the abstract; when a `specific` claim needs body detail, also try `WebFetch https://arxiv.org/html/<id>` (or the `ar5iv.org/abs/<id>` HTML mirror) for full text → `full_text`.
2. **Open landing page** — else `WebSearch "<title>" <first author> <year>`, then `WebFetch` the best hit (publisher abstract page, ACL Anthology, OpenReview, PMC, semantic scholar page). Publisher pages usually give `abstract_only`; open-access HTML/PDF gives `full_text`.
3. **Optional AMiner enrichment** — if `AMINER_API_KEY` is set and web search was thin, resolve via the AMiner `paper/search` endpoint above to get title match + abstract.
4. If nothing usable is found after a reasonable attempt → `retrieval_level: not_found`.

Do not follow more than a few links per source; cap effort and move on. Never fabricate the content of a page you did not fetch.

### S4 — Judge each claim–source pair

Apply `references/rubric.md`. For each claim, compare `claim_text` against the retrieved source content and assign one verdict from the five labels, with `evidence` (quote from source, original language), `reason`, `retrieval_level`, and `confidence`.

**Iron rules** (do not violate):

- Only `full_text` retrieval can justify `NOT_IN_SOURCE`. If you only have the abstract and the claim targets body detail → `UNVERIFIABLE`.
- Only assign `NOT_SUPPORTED` when the source genuinely says something different/opposite that you can quote. Absence of confirmation ≠ contradiction.
- Never give high confidence from title/metadata alone with no retrieved source text.
- Never invent an evidence quote. If you did not retrieve it, the level is `not_found` and the verdict is `UNVERIFIABLE`.
- Preserve source quotes in their original language; write `reason` in the user's language.

### S5 — Report

Present a summary, then the **full record of every non-`SUPPORTED` claim**, sorted by severity: `NOT_SUPPORTED` and `NOT_IN_SOURCE` first, then `PARTIALLY_SUPPORTED`, then `UNVERIFIABLE`. **Always** write the complete JSON report to the `output` path (defaults to the current working directory — see Parameters). See Output Presentation.

## Parameters (from natural language or `/citation-faithfulness`)

| Field | Values | Default | Meaning |
| --- | --- | --- | --- |
| `pdf` | absolute PDF path | required | The paper to check |
| `scope` | `all` / `specific-only` / `refs:1,12,23` | `all` | `all` = every in-text citation; `specific-only` = only fact/number/result claims; `refs:...` = only these reference numbers |
| `max-refs` | integer | none | Cap the number of unique sources retrieved (cost guard) |
| `output` | path | `./citation-faithfulness-<pdf-stem>.json` | Where the full JSON report is written. **Always written**: when the user gives no path, default to the current working directory, named after the PDF's basename. |

The user chose **full coverage** by default. Offer `specific-only` or `max-refs` when a paper has many references and cost matters.

## Runtime Constraints

- **Never fabricate a verdict or an evidence quote.** A source you could not read is `UNVERIFIABLE`, full stop.
- `UNVERIFIABLE` is not a failure of the paper — always distinguish "we could not check" from "the citation is wrong" when talking to the user.
- Treat `NOT_SUPPORTED` / `NOT_IN_SOURCE` as **flags for human review**, not final accusations. The author may be citing a different version, a later section, or a source you mis-matched — say so.
- Respect web-tool limits: cap links per source, deduplicate by cited work, and report how many sources were `not_found`. Never silently drop citations you skipped — list them.
- Do not print the value of `AMINER_API_KEY`.

## Output Presentation

Lead with a summary, then the detail table.

**Summary**
- Paper title + total in-text citations found + unique sources checked.
- Verdict counts: `SUPPORTED` / `PARTIALLY_SUPPORTED` / `NOT_SUPPORTED` / `NOT_IN_SOURCE` / `UNVERIFIABLE`.
- Retrieval coverage: how many sources reached `full_text` vs `abstract_only` vs `not_found` — so the user knows how deep the check went.
- A one-line honesty note if coverage was shallow (e.g. "18/40 sources were abstract-only; body-level claims there are UNVERIFIABLE, not cleared").

**Every non-`SUPPORTED` item, in full** — not just a table row. For each `NOT_SUPPORTED` / `NOT_IN_SOURCE` / `PARTIALLY_SUPPORTED` / `UNVERIFIABLE` claim, print a complete block, in severity order (`NOT_SUPPORTED` and `NOT_IN_SOURCE` first — those are the actionable findings):
`claim_id` · section · verdict · `retrieval_level` · `confidence`, followed by the full `citation_sentence` (paper's original language), the cited work, the `evidence` quote (source's original language; state explicitly when nothing was retrieved), the `reason`, and any `notes`. Do not truncate or summarize these blocks away — the user must be able to judge every flagged citation without opening the JSON.

**`SUPPORTED` items** may be reported as counts plus a short list of highlights; their full records live in the JSON.

**Then**: **always** write the complete JSON report to the `output` path — when the user gave none, write `citation-faithfulness-<pdf-stem>.json` into the current working directory — and tell the user the path. This step is mandatory, not conditional on the user asking for it.

## Return Value

The report is assembled as a single JSON object defined in `references/output-schema.md` — top-level `paper` / `run` / `summary` / `claims[]` / `flagged` / `skipped`, with a per-claim record for each checked citation. That object is **always** written to `output` (default: `citation-faithfulness-<pdf-stem>.json` in the current working directory), and the on-screen presentation is rendered from it. Follow the schema's field names, enumerations, and invariants exactly so the return value stays stable across runs.
