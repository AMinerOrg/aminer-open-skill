# Skill Catalog

[← Back to README](README.en.md) · [中文](SKILLS.md)

`skills/` currently contains the following 21 triggerable skills. Click a skill name for the full skill definition. The first 7 are research workflow skills, available online in the AMiner web app; the rest target local agents and are grouped by research stage.

**Contents**:

- [Research workflows (available online in the web app)](#research-workflows-available-online-in-the-web-app)
- [Search and discovery](#search-and-discovery)
- [Reading and organizing](#reading-and-organizing)
- [Research reports](#research-reports)
- [Paper experiment checks](#paper-experiment-checks)
- [Citation checking](#citation-checking)
- [Choosing between similar skills](#choosing-between-similar-skills)
- [Design principles](#design-principles)

## Research workflows (available online in the web app)

| Skill | Status | Purpose | Triggers | Token |
| --- | --- | --- | --- | --- |
| [`aminer-paper-deep-reading`](skills/aminer-paper-deep-reading/SKILL.md) | Stable | Paper deep reading: structured close reading, sentence-by-sentence translation, reproduction-grade protocol audits; also cross-literature parameter tables and locating papers from vague descriptions | "deep-read this paper", "what is the typical value of X" | Required; free-first |
| [`aminer-journal-paper-write-review-revise`](skills/aminer-journal-paper-write-review-revise/SKILL.md) | Stable | Paper writing, review, and revision: drafting from scratch with real citations, simulated review before submission, item-by-item responses to real reviewer comments | "write the Related Work with real citations", "respond to each reviewer comment" | Required; free-first |
| [`aminer-experiment-to-paper`](skills/aminer-experiment-to-paper/SKILL.md) | Stable | From experiments to manuscript: debugging code and experiment designs, verifying method provenance, turning results into paper prose | "my experiment cannot reproduce the reported baseline, help me debug" | Required; free-first |
| [`aminer-degree-thesis-proposal-to-defense`](skills/aminer-degree-thesis-proposal-to-defense/SKILL.md) | Stable | Thesis proposal to defense: literature scan and novelty check, section-by-section drafting against the school template, working through advisor and committee comments, format compliance, defense materials | "do the literature scan for my proposal", "work through my advisor's comments" | Required; free-first |
| [`aminer-grant-application`](skills/aminer-grant-application/SKILL.md) | Stable | Project application: extract requirements from the guideline, distill the scientific question, draft section by section, run a novelty check, simulate the expert panel review | "extract the application requirements from this guideline", "review my proposal as an expert panel" | Required; free-first |
| [`aminer-topic-advisor-selection`](skills/aminer-topic-advisor-selection/SKILL.md) | Stable | Research topic and advisor selection: assess the level of competition, run a novelty check on the topic; enumerate a department's advisors, build profiles, compare, and draft outreach emails | "is this direction still worth pursuing", "list the advisors in this department" | Required; per-advisor `person_detail` ¥1.00/call — converge on free APIs before pulling details |
| [`aminer-patent-tech-intelligence`](skills/aminer-patent-tech-intelligence/SKILL.md) | Stable | Industry intelligence and patents: technology survey reports, benchmark studies, URS/SOP documents; prior-art retrieval (strict filing-date cutoff), claims and disclosure drafting, responses to office actions | "produce a technology survey of X", "retrieve prior art published before this date" | Required; free-first; watch `person_detail` unit price in bulk screening |

**Example prompts**:

- Paper deep reading (`aminer-paper-deep-reading`): Deep-read "Attention Is All You Need": summarize the problem, method, experimental design, and key numbers, and suggest directions for further exploration.
- Paper writing, review, and revision (`aminer-journal-paper-write-review-revise`): Write the Related Work section for this manuscript with real retrieved citations behind every claim, then simulate a peer review round.
- From experiments to manuscript (`aminer-experiment-to-paper`): My experiment cannot reproduce the numbers reported in this paper — help me debug it, and verify the literature basis for this metric.
- Thesis proposal to defense (`aminer-degree-thesis-proposal-to-defense`): Do the literature scan and novelty check for my thesis proposal, then work through my advisor's comments on Chapter 2 one by one.
- Project application (`aminer-grant-application`): Extract the application requirements from this guideline, help me distill the scientific question and draft section by section, then review the proposal as an expert panel.
- Research topic and advisor selection (`aminer-topic-advisor-selection`): Assess the level of competition in "retrieval-augmented generation for industrial defect detection" and run a novelty check on the topic.
- Industry intelligence and patents (`aminer-patent-tech-intelligence`): Produce a technology survey of solid-state electrolytes, and retrieve the closest prior art published before this filing date.

## Search and discovery

| Skill | Status | Purpose | Triggers | Token |
| --- | --- | --- | --- | --- |
| [`aminer-free-academic`](skills/aminer-free-academic/SKILL.md) | Stable | Zero-cost lookup of papers, scholars, institutions, venues, and patents via 7 free APIs | "find this paper by title", "the scholar's research interests and citation counts" | Free APIs, token still required |
| [`aminer-academic-search`](skills/aminer-academic-search/SKILL.md) | Stable | Full academic data queries across papers, scholars, institutions, venues, and patents, plus structured experiment retrieval (29 APIs) | "build a full scholar profile", "return the Experiment JSON" | Required; some APIs billed; experiment retrieval ¥0.10/call |
| [`aminer-daily-paper`](skills/aminer-daily-paper/SKILL.md) | Stable | Personalized paper recommendations by topic, scholar profile, or author | "recommend 8 recent highly-cited papers on X" | Required |
| [`aminer-deep-search`](skills/aminer-deep-search/SKILL.md) | Stable | Collect hundreds of candidate papers for a survey: multi-round search, deduplication, citation snowballing | "collect 200 candidate papers for a survey" | Required |
| [`sota-finder`](skills/sota-finder/SKILL.md) | Stable | Find the current or historical best result (SOTA) on a task, split incomparable scopes, build a sourced leaderboard | "what is the current SOTA on X" | Optional; only for AMiner enrichment |

**Example prompts**:

- Quick paper lookup (`aminer-free-academic`): Find 10 recent papers on long-context language models. Return the title, year, venue, citation count, and URL.
- Investigate a scholar or topic (`aminer-academic-search`): Build a research profile for Andrew Ng, including interests, representative papers, collaborators, and recent work.
- Retrieve structured experiments (`aminer-academic-search`): Return the original Experiment JSON for this paper, filtered by method and dataset name.
- Get a focused reading list (`aminer-daily-paper`): Recommend 8 papers on tool-using multimodal agents, prioritizing recent and highly cited work.
- Collect literature for a survey (`aminer-deep-search`): Collect 200 candidate papers on retrieval-augmented generation, expand from strong seed papers, remove duplicates, and export the bibliography.
- Find SOTA and build a leaderboard (`sota-finder`): Find the current DocVQA SOTA, separate incompatible evaluation scopes, and return a sourced leaderboard with the standard artifact bundle.

## Reading and organizing

| Skill | Status | Purpose | Triggers | Token |
| --- | --- | --- | --- | --- |
| [`aminer-pdf-ocr`](skills/aminer-pdf-ocr/SKILL.md) | Stable | Convert a paper PDF to full-text Markdown and extract experiment methods, datasets, and metrics | "convert this PDF to Markdown" | Required |
| [`aminer-exp-extraction`](skills/aminer-exp-extraction/SKILL.md) | Stable | Extract experiment methods, datasets, metrics, and key results from paper Markdown as JSON | "extract methods / datasets / metrics from this paper's Markdown" | Requires `BIGMODEL_API_KEY`; no AMiner token |
| [`scientific-taxonomy`](skills/scientific-taxonomy/SKILL.md) | Stable | Organize a batch of papers into a clear hierarchical taxonomy (Markdown) from titles and abstracts | "organize these papers into a coherent taxonomy" | Optional; only when AMiner fills missing metadata |
| [`paper-source-trace`](skills/paper-source-trace/SKILL.md) | Stable | Trace a paper's claims to their citation sources, explain citation intent, and generate citation maps | "trace key claims to their sources" | Optional; only for AMiner enrichment |

**Example prompts**:

- Parse a PDF and extract experiments (`aminer-pdf-ocr`): OCR this paper PDF, convert it to Markdown, and extract the experiment methods, datasets, and metrics as JSON.
- Extract experiments from Markdown (`aminer-exp-extraction`): Read this paper's Markdown file and extract the experiment methods, datasets, metrics, and key results as one JSON file.
- Organize a paper collection (`scientific-taxonomy`): Group these paper titles and abstracts into a coherent hierarchical taxonomy and save it as taxonomy.md.
- Trace a paper's sources (`paper-source-trace`): Analyze this PDF. Trace each key claim to its citation context and source, explain the citation intent, and generate the Markdown, JSON, SVG, and HTML outputs.

## Research reports

| Skill | Status | Purpose | Triggers | Token |
| --- | --- | --- | --- | --- |
| [`deep-research`](skills/deep-research/SKILL.md) | Stable | Write a cited research report where every claim traces back to an evidence ledger | "research the X industry and write a cited report" | Required; free-first, billed APIs capped (¥20 hard stop) |

**Example prompts**:

- Produce a sourced research report (`deep-research`): Research the Chinese LLM industry and write a cited report with an evidence ledger backing every claim.

## Paper experiment checks

| Skill | Status | Purpose | Triggers | Token |
| --- | --- | --- | --- | --- |
| [`baseline-finder`](skills/baseline-finder/SKILL.md) | Preview | Check a paper's experiments and citations against each other to find baselines it should have compared but didn't | "what baselines may be missing" | Model API key and AMiner token required; some API calls billed; GROBID for PDF mode |

**Example prompts**:

- Check experimental baseline coverage (`baseline-finder`): Check whether this paper may be missing direct experimental baselines, and separate evidence-backed comparisons from leads that need author verification.

## Citation checking

| Skill | Status | Purpose | Triggers | Token |
| --- | --- | --- | --- | --- |
| [`pdf-citation-verifier`](skills/pdf-citation-verifier/SKILL.md) | Stable | Verify every reference in a paper PDF actually exists; flag fabricated citations | "are the references in this PDF fabricated" | Required |
| [`structured-reference-audit`](skills/structured-reference-audit/SKILL.md) | Stable | Conservative reference audit: parse the PDF into a ledger, resolve each entry; "unresolved" is not "fabricated" | "conservatively audit the references" | AMiner resolution needs a token; GROBID or TEI required |
| [`citation-faithfulness`](skills/citation-faithfulness/SKILL.md) | Stable | Check each in-text citation actually supports the claim, catching distortions of the cited source | "does citation [12] actually support this claim" | No AMiner token; web access required |

**Example prompts**:

- Detect fabricated references (`pdf-citation-verifier`): Check every reference in this paper PDF and flag entries that are missing, suspicious, or need manual review.
- Audit parsed bibliography entries conservatively (`structured-reference-audit`): Parse this PDF into a reference ledger, then resolve each eligible reference through AMiner without treating an unresolved match as fabrication.
- Check citation faithfulness (`citation-faithfulness`): For each in-text citation in this paper, retrieve the cited source and determine whether the surrounding claim is supported by the original text.

## Choosing between similar skills

| Your need | Use | Not |
|---|---|---|
| A single-step lookup of papers, scholars, institutions, venues, or patents, at zero cost | `aminer-free-academic` | `aminer-academic-search` (only for full abstracts, scholar careers, citation relations, or combined workflows) |
| A list of hundreds of candidate papers, without a report | `aminer-deep-search` | `deep-research` |
| A cited research report backed by an evidence ledger | `deep-research` | `aminer-deep-search` |
| A few personalized reading recommendations | `aminer-daily-paper` | `aminer-deep-search` |
| A direct verdict on whether references exist | `pdf-citation-verifier` | `structured-reference-audit` |
| A conservative reference audit where "unresolved" is not "fabricated" | `structured-reference-audit` | `pdf-citation-verifier` |
| Whether a citation faithfully represents the cited source | `citation-faithfulness` | `pdf-citation-verifier` |
| Tracing claims to sources and citation intent, with a citation map | `paper-source-trace` | `citation-faithfulness` |
| Audit potentially missing direct experimental baselines | `baseline-finder` | `aminer-deep-search` (it gathers candidate papers; it does not assess baseline coverage) |
| Convert a PDF to full-text Markdown | `aminer-pdf-ocr` | `aminer-exp-extraction` (only when the input is already Markdown) |

## Design principles

Every skill in this repository follows these principles:

1. **Citation-integrity red line**: only write what was actually retrieved — say "not found" rather than fabricating; every result carries a three-state marker (verified / uncertain / not found).
2. **Academic data first**: queries about papers, scholars, institutions, venues, or patents go through the AMiner Open Platform first; free endpoints first, billed calls estimated before execution.
3. **Triage before action**: similar-looking requests are different task types; classify first, then follow the output contract for that type.
4. **Complete first answer**: the first reply delivers the full artifact for the request type instead of relying on clarifying questions.
5. **Fail loudly**: zero-output silent failures never happen; failures keep the submitted materials, and resending the same message resumes from the breakpoint.
6. **Deliveries carry next steps**: every delivery ends with continuations — dimensions, todos, or the next section.
7. **Parse and echo constraints**: word counts, item counts, year windows, and templates written into an instruction are acceptance criteria; parse and echo them before writing, and state any unfilled quota.
8. **Cross-session state**: returning to the same manuscript, project, or list weeks later is normal; continue incrementally instead of rewriting from scratch.
9. **Artifacts over hearsay**: guide users to paste their real materials (drafts, data, comments, templates) — judge by what was pasted, not what was said.
