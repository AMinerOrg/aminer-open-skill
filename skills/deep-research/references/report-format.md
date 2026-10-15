# Report Format

Two genres, picked from the task framing: an **academic review** (default — literature reviews, research landscapes, scholar / venue / patent investigations) and an **industry report** (when the prompt asks for an industry or market survey: "行业调研", "industry report", "市场格局", "竞争格局", "产业研究"). Use the user's language for every heading and every line of prose. Keep JSON keys, API names, probe ids, and source titles untranslated when they must be shown — which, in the report itself, is never.

Write the report only after `python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" check` exits 0.

**The report is drafted against `render --final`, numbered by `render --renumber`.** `--final` is the ledger view — the section / subsection numbering, the claim set per section in order, and every source's stable ledger number — not the body. Write the analysis as prose from those claims, citing sources as `[@n]` placeholders keyed to ledger numbers, and end the draft with a references heading holding one `{{references}}` placeholder line. Then `render --renumber --draft <path> --out <path>` replaces the placeholders with dense ascending numbers by first appearance in your text, fills the references slot with a cited-only bibliography, and writes a citation-map sidecar next to the delivered report. A placeholder naming an unknown or dropped source is a hard error — a citation pointing at nothing never reaches the page. The appendices do not go in the report: write them with `render --appendix --out auto --citation-map <sidecar>` and quote the single `pointer` line it returns.

## Structure

The report ends at the reference list. Everything after it is a one-line pointer to the appendix file.

### Genre A — academic review (default)

| Part | Heading (zh) | Numbered? |
| --- | --- | --- |
| Title | `# <具体标题>` | — |
| Abstract | `## 摘要` | no |
| Introduction | `## 引言` | no |
| The analysis | `## 1. …`, `### 1.1 …` | yes |
| Discussion | `## 讨论` | no |
| Limitations | `## 局限` | no |
| References | `## 参考文献` | no |
| Appendix pointer | one line, no heading | no |

### Genre B — industry report

| Part | Heading (zh) | Numbered? |
| --- | --- | --- |
| Title | `# <具体标题>` | — |
| Executive summary | `## 执行摘要` | no |
| Market size & growth | `## 1. 市场规模与增长` | yes |
| Player landscape | `## 2. 玩家格局` (with a comparison table) | yes |
| Competitive dynamics & business models | `## 3. 竞争动态与商业模式` | yes |
| Technology & patents | `## 4. 技术路线与专利布局` | yes |
| Supply chain & compute | `## 5. 算力与供应链` | yes |
| Policy & compliance | `## 6. 政策与合规` | yes |
| Outlook & open questions | `## 7. 展望与未决` | yes |
| References | `## 参考文献` | no |
| Appendix pointer | one line, no heading | no |

For Genre B the section set is **induced from retrieval** (see `references/research-loop.md`), not fixed — drop a section the evidence does not support and name the gap in 局限; the table above is the expected shape, and an industry report that omits market size, players, or supply chain without saying why is incomplete. Each numbered section ends with a `风险 / 争议` (risk / dispute) subsection carrying counter-evidence — the industry analogue of the disagreement subsection.

Subsections are numbered `###` headings as the tables prescribe; **never a bolded line standing in for a heading** — when something needs to be a heading level, make it a real one (`###` / `####`). Fake headings are invisible to numbering, to `render`'s per-section measurement, and to any later edit that anchors on headings.

## Write prose, not ledger scaffolding

`render --final` prints the ledger as a scaffold: claim bullets like `- **c1** … [10]`, source-pool lines like `_来源：[10] [25]_`, tags like `_（分歧）_` / `_（解读）_`, and raw `冲突：` bullets. **None of that appears in the report.** They are ledger internals. From that scaffold you write:

- **Flowing prose — claims are the skeleton, the sources are the flesh.** Each subsection develops its claims in full paragraphs: the claim states the finding, the paragraphs carry the mechanism, the numbers and the concrete detail already paid for in the ledger (a paper's abstract, a patent's fulltext note, a web page's facts). A subsection that restates its claims in one-line summaries is a defect even when every sentence is cited — `render --renumber` hard-errors on any subsection under 300 prose units (CJK characters or Latin words; citations, headings, images and tables excluded). Group claims under their subsection; lead with the finding, not with the source or the claim id. Figures never substitute for text: a report measured only on its charts grows figures over sentences.
- **No enumeration-style writing — "one sentence per item" is the named defect.** Each core item the section leans on (a paper, a company, a patent) gets at least one full paragraph, 3–5 sentences: what problem it solves, how the mechanism actually works (not just "proposed / implemented"), its key numbers, and how it relates to what came before or after it. Minor items merge into one comparative sentence instead of being listed one by one — retrieval that is name-checked but not digested is spend the report never banks.
- **Paraphrase, don't paste.** Source wording is restated in the report's own words; quote an original verbatim only when a sentence is classic and too compressed to rewrite — in quotation marks, immediately followed by its citation — **at most one such quote per section**, never a pasted passage.
- **A disagreement / risk subsection as a prose paragraph** that states the counter-evidence and cites it ("DeepSeek's technical report [25] claims X; third-party comparisons [13] [11] find Y"), **not** a `冲突：` bullet.
- **Tables when comparing several entities** (players, models, market share, funding). Build every cell from numbers a cited source carries — never invent a cell. A player-comparison table (company / flagship model / positioning / open or closed / market share or funding) is expected in Genre B.

Keep inline citations as plain bracketed numbers `[3]`, or `[3] [7]` for several; reuse the same number for the same source. The link lives in the reference entry. Draft in `[@n]` ledger placeholders and let `render --renumber` assign the delivered numbers — hand-typed `[N]` cannot be validated and will drift from the citation map.

`render` emits the `## 参考文献` heading and the reference entries in the topic's language; copy those verbatim. It does not emit prose — that is your job.

Figures sit inside the analysis, not in a separate gallery. `render --final` prints a `_[FIGURE fN] {title} — sources: [n]…_` placeholder in the section the figure belongs to, using stable ledger numbers; replace it with the image embed when you assemble the draft, and cite the figure's data sources in its caption with the same `[@n]` placeholders — `render --renumber` numbers them together with the prose (see **Figures and tables** below).

1. **Title** — specific, not "Research Report" / "调研报告".
2. **Abstract / Executive summary** — 200–300 words: the question, how it was investigated, what was found, what remains open. No citations, no method narration beyond one sentence.
3. **Introduction** (Genre A) / market context (Genre B) — the research object, the time window, why it is worth asking now. May cite.
4. **The analysis** — section numbers and ordering from `render --final`; **prose you write** from the ledger's claims (above), one top-level section at a time (each written from its own material blocks and target, not from a whole-pile one-pass view — see research-loop.md §Write from material). Do not renumber, reorder, or write a section `render` did not print. Sentences carrying key facts, numbers or conclusions carry citations; transitions and your own synthesis carry none — but no section goes entirely uncited.
5. **Discussion / Outlook** — what the sections mean together: cross-cutting patterns, what the disagreements imply, open questions. The only part that may reason beyond a single section, and it still cites.
6. **Limitations** — missing data, unavailable web access, unresolved ambiguity, shallow retrieval, drifting probes, title-level evidence, and industry elements you could not source. Name them; do not soften them.
7. **References** — the cited-only list `render --renumber` generated in the `{{references}}` slot, verbatim.
8. **Appendix pointer** — the `pointer` string returned by `render --appendix --out auto`, verbatim, one line. Do not restate the cost, the call counts, or the file's contents around it; the sentence already says what the file holds.

The fixed parts stay unnumbered on purpose. Numbering them would push the analysis to start later, and those numbers come from the ledger — renumbering by hand desyncs the report from `render` and from every citation.

## The appendix file

`render --appendix --out auto` writes Appendix A, B and C to `<ledger stem>-appendix.md` next to the ledger and returns `{"path": ..., "pointer": ...}`. The reader gets findings; the file gets the bookkeeping. Pass `--citation-map <sidecar>` (the file `render --renumber` wrote next to the delivered report) and the appendix speaks the report's numbers: the figure-source column switches to `[N]`, Appendix D is appended with the full report↔ledger map, and the returned pointer mentions it.

**The appendix is written last, from the closed ledger.** Upstream's report chain is a single ordered pass and its appendix is assembled from the final state, so it cannot go stale by construction; in this architecture the same property is a sequencing rule: any entry recorded after the appendix was rendered — a late claim, a verify judgment, a figure — makes it stale, and the answer is to re-run `render --appendix`, not to hand-edit its tables. A methods section that under-reports the verifies the ledger holds (33 written, 37 true) is the one part of the report that was supposed to be mechanically faithful.

| Appendix | Contents | Written by |
| --- | --- | --- |
| A — Retrieval log | every search's axis, query, returned/kept/discarded counts, drop reasons | `render` |
| B — Calls and cost | calls and cost per endpoint, total, hard limit | `render` |
| C — Data and methods | searches by axis, screened/retained/discarded, reading-depth distribution, academic vs web counts, claim and conflict counts, coverage, **and a figures subtable (id / type / sources / rendered by)** when any figure is registered | `render` |
| D — Citation number map | the delivered report's `[N]` ↔ ledger `n` ↔ title for every retained source (`*` = never cited); the figure-source column switches to report numbers | `render` (needs `--citation-map`) |

Appendix C's table is the machine-checkable half of the methods. **Append 2–4 sentences of prose to the file under it** for what the ledger cannot know:

- sources of evidence (AMiner public academic data; first-party web pages where the question is about current practice),
- inclusion and exclusion criteria — the counts themselves are already in the table,
- the retrieval time window and year filter, and the date retrieval was run,
- the language strategy, including whether the Chinese corpus was reached,
- evidence grading: how many sources were read at open-access full text (the reading-depth row in the table above states it), what the rest degraded to, and which claims rest on a truncated slice or a title alone.
- the verification form: whether every evidenced claim was judged by a context-free subagent against its verbatim evidence, or self-judged by the session that recorded it — a reader weighing a citation deserves to know which independence it carries. The same sentence states the reading form: whether the sources were read and recorded by delegated reading subagents (deliverable = the ledger records) or by the session itself.

Two rules about the prose itself: it lives **in this file, under the template's instruction line** — a run that leaves that line bare has skipped it, and moving the substance into the report's Limitations section is not a substitute (Limitations names limits; this is the methods statement). And **every count in it is copied from the Appendix C table above** — the verify distribution, the depth counts, the figure counts are all sitting in the table; a number written from memory (a measured run wrote "45 claims verified" over a table reading 44) is the 33-vs-37 defect in miniature: the mechanically faithful part of the report must actually be mechanical.

If the ledger has `unscouted` set, say plainly there — and in Limitations — that the outline was not induced from a scout.

## Figures and tables

- **Genre B (industry): figures and at least one comparison table are expected, not optional.** Register at least one chart and include a player-comparison table in §2. Figures are planned, not scavenged: once the outline settles, decide where a chart is needed and insertable (`figure plan` per topic), retrieve that topic's numbers until sufficient, and only then chart — see research-loop.md §Chart topics. Topics given up as unobtainable are recorded with their reason (`figure plan --abandon`); quote them in 局限 and let Appendix C list them — a chart the report lacks *because no public data exists* is an honest limitation, while one it lacks because nobody looked is the 数字太少 defect. A quantitative chart (`bar` / `hbar` / `line` / `pie` / `heatmap`) runs on numbers the ledger verified (market share, funding, GPU cost); when web retrieval came back thin on numbers, aggregate the patent / paper corpus the ledger *does* hold into a quantitative chart (`figure add --from-source-metadata --field year/assignee/venue`) **before** you fall back to a structural `timeline`, which runs on dated events (releases, funding rounds, policy milestones). The timeline is the last resort, not the first — a thin-web run that still retrieved a corpus ships a real bar chart, not a timeline stand-in. `check` warns (`figures_industry_expected`) when a Genre B report ships with zero figures, (`figures_industry_quantitative_expected`) when it ships no quantitative chart — a `timeline` alone does not satisfy it — and (`figures_thin_data`) when a registered figure has too few points to plot meaningfully; a Genre B report with no charts is a defect to disclose in 局限, not a default.
- **Genre A (academic review): figures optional.** Add one only where a chart says something the prose cannot — a distribution, a trend, a comparison across more entities than a sentence can hold. A report with no figures is acceptable for Genre A.
- Every number shown in a chart or table is in one of its cited sources. `check` reports `figures_unsupported_numbers` / `claims_with_unsourced_numbers` when it is not — fix the citation or the data, the way you would fix a claim's citation. A chart may never show a number the ledger does not vouch for.
- Never hand-draw a figure. Every figure is `figure add`-registered and `chartrender.py`-rendered from the registered `data`; there is no hand-drawn figure. If a figure was not `mark-rendered`, it has no image — leave the section without it, or render it before writing.
- **A figure's constituent corpus sources are cited in the prose that interprets it.** Upstream's every finding carries a source the prose cites — an aggregation chart is no bypass. The sentence narrating the chart's pattern (application trend, who files, which technical directions) cites the corpus it aggregates; sources that exist only inside a figure's source list never reach the reference list, and a reference list that omits them undercounts the corpus the report actually stands on.
- Render internals stay in the appendix. Figure ids (`f1`), render paths, and `rendered_by` (script / template) appear only in Appendix C, never in the body. The body shows the image, a caption, and a table — nothing more.

## The disagreement / risk subsection

Every top-level section ends with its `disagreement` (Genre A) or `风险 / 争议` (Genre B) subsection. Two acceptable forms, no third:

- Report the counter-evidence you actually retrieved, with citations.
- State plainly that retrieval found no direct disagreement, then name the nearest tension in the evidence — with a citation for it.

"No disagreements were found." on its own is not one of them. If the subsection has no claims in the ledger, it has nothing to say and should have been merged up.

## Citations

- Inline citations are plain bracketed numbers: `[3]`, or `[3] [7]` for several — never adjacent, always a space between them (write `[3] [7]`, not `[3][7]`). The link lives in the reference entry, not in the body.
- Reuse the same number for repeated citations to the same source.
- **Citation frequency is the first principle: one source, one or two marks per section.** Put the mark on the sentence that carries that source's key fact, number or conclusion — its most load-bearing sentence — not on every sentence the source vaguely backs. A number stamped fourteen times says less than a number stamped once, at the claim it carries.
- **Not every sentence carries a citation.** General narration, transitions and your own synthesis carry no mark; only sentences carrying key facts, numbers or conclusions do — but a section's body must have citation support: no section goes entirely uncited.
- **Cite the source that supports the clause.** When a statement rests on one source, cite that one; a material block's `[@n]` marks list everything available to it — select what each clause actually rests on, and when one statement is supported by several sources, place their marks adjacent on that sentence.
- **Numbers come from `render --renumber`, never from your hand.** In the draft cite `[@n]` (the ledger number); the delivered file shows `[N]`, ascending at first appearance. Within one citation group (a caption, a table cell) numbers reflect first-appearance order, not sorted order — cite only the key sources if you want a tidy group. Do not use range notation (`[1]-[20]`): expand ranges into explicit placeholders.
- The delivered reference list carries **only the cited sources**; sources the report never cites stay in the ledger and appear in Appendix D's `*` rows. Re-run `--renumber` after any edit that adds or removes a citation — it is deterministic on the same draft.
- A claim recorded as `--type interpretation` must read as analysis ("this suggests", "the evidence points to"), not as a reported fact.
- A claim with one source says so ("a single 2026 study reports…"). Do not present it as consensus.
- Never cite a URL that was inferred rather than returned by AMiner or opened with `WebFetch`.
- An abstract is not full text; do not describe abstract-level evidence as a result you read in the paper. A `paper_qa_search_pro` result carries no abstract at all — a title is not a finding.
- Every number in the body or in a table is in a cited source. `check` reports `claims_with_unsourced_numbers` when it does not — fix the citation rather than the wording.
- Never invent an author, organization, venue, patent, URL, quote, date, or missing field. A gap in the ledger is a gap in the report.

## What the report may not contain

The report carries findings. All of this goes in the appendix file instead:

- probe ids, queries, retrieval axes, and the number of searches run,
- API names, endpoint prices, CNY amounts, call counts, `evidence.py` command names,
- screening counts (screened / retained / discarded) and the reading-depth distribution,
- figure ids (`f1`), render paths, and `rendered_by` / `strategy` — these live in the Appendix C figure table, not the body,
- **claim ids (`c1`) and source-pool lines (`_来源：`) — these are ledger scaffolding and never appear in the body**,
- the appendix tables themselves.

A reader of the analysis should not be able to tell which endpoint returned which paper, nor how much the run cost. Method belongs in the appendix file, not in a body section — there is deliberately no "Data and methods" heading in the report.

**Do not translate**, in the appendix file or anywhere else: API names (`paper_detail`, `paper_qa_search_pro`), probe ids (`p1`), `axis` values (`topic`, `keyword`, `web`), source titles, and venue names. They are controlled vocabulary and real metadata; a translated endpoint name no longer names an endpoint. Only the labels `render` emits follow the user's language, and `render` already handles those.

Appendix B states explicitly when every call was free.

## Tone

- Concise prose; tables when comparing several entities.
- State uncertainty directly instead of hedging everywhere.
- Do not reproduce raw tool output or narrate hidden reasoning.
