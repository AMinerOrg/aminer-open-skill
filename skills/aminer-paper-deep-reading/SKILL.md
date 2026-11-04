---
name: aminer-paper-deep-reading
name_zh: 读论文
version: 1.0.0
author: AMiner
contact: report@aminer.cn
description: >
  [Scope · by task essence] Answer parameter/metric/reference-range/performance-value landscapes (deliverable = a cross-literature comparison table, one row per paper, anchored on ≥5 papers); assemble literature lists by topic (deliverable = numbered list with links, honoring the user's named journals/years/counts); reverse-locate a paper from a description or vague memory (exact match first, source links as returned by the API).
  [Activation] Paper reading — the single-paper deep-reading executor. Use when the user says "deep-read this paper: {title}", "read this paper and summarize background, introduction, methods, results, discussion", "translate sentence by sentence and explain", "compress to 2 pages of markdown", "I want to follow {title}", or pastes a bare title / raw reference string / accession number / single academic concept, uploads a figure saying "answer after checking the original text", or sends "continue" to resume a stalled reading.
  [Scenarios] Single-paper loop: structured deep reading, reproduction-grade reading (protocol audit), one-shot title skim, custom-template reading, resumable sentence-by-sentence translation, compression/distillation, from-zero concept digs, figure-plus-text bound interpretation, exact-match full-text location from reference strings or vague memory, empirical research-design audit, post-reading follow-up chains.
  [Routing] Survey/journal-manuscript feeding, systematic citation-matched revision, and real reviewer-comment response loops go to aminer-journal-paper-write-review-revise; hands-on code/experiment work goes to aminer-experiment-to-paper; topic finding goes to aminer-topic-advisor-selection; thesis proposal and defense feeding goes to aminer-degree-thesis-proposal-to-defense.
homepage: https://github.com/AMinerOrg/aminer-open-skill/tree/main/skills/aminer-paper-deep-reading
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

# aminer-paper-deep-reading — Read Papers (structure guaranteed by the server-side skeleton; depth drawn out by follow-up hooks)

**Stance**: This skill has the thinnest entry point of the whole set — bare titles, raw reference strings, and two-character concepts recur constantly, and the first message often carries no structure at all. **Structure must be guaranteed by the server-side skeleton; depth is drawn out by follow-up hooks**: never expect the first message to tell you where the depth lies, and never judge the task's magnitude by the first message's length — a two-character noun unrolling into multi-round deep digging is a common shape. Payload first: a pasted PDF / reference string / paper figure / the user's own experiment protocol is what can actually land. Look at what was pasted, not at what was said.

## 0. Essence of the Scenario

1. **First-round output is 100% self-sufficient**: there are users who leave after one round — a bare title comes in, a structured deliverable goes out, done. Clarifying questions get ignored and the user churns; the first answer is everything.
2. **Concrete follow-up hooks pre-embedded at the tail**: another group of users build all their depth through follow-ups; the same bare title can roll into multi-round digging. Hooks must be concrete (the basis for a specific parameter / ablation details / compared against whom / how to read a specific figure), never "anything else you'd like to know". Points 1 and 2 hold simultaneously; missing either yields a crippled answer. Every delivery ends with built-in next steps (directions worth pursuing / things that can be handed off) — a dead end is churn.
3. **Both cadences are accepted**: a minutes-long deadline sprint for a quick skim and a weeks-long sentence-by-sentence marathon are both normal cadences; the delivery contract does not shrink with pace.
4. **The pasted payload is the mode switch**: pasted experiment protocol = protocol-audit mode; pasted column schema = per-column delivery; pasted paper figure = figure-text bound interpretation — triage by what was pasted, not by verbal claims.
5. **Cross-session re-entry is the norm**: the same paper's translation resumes the next day, the same concept is revisited next week, and periodic post-reading wrap-ups ask for landscape recommendations — ledgers inherit incrementally, never rewritten from scratch.

## 1. First-Move Triage Table (triage before acting; similar-looking requests are different task types, and a wrong shape makes the user resend)

| Task type | Recognition signals | Output contract (deliverable shape / fields / how gaps are reported) |
|---|---|---|
| **Structured deep reading (default)** | "deep-read this paper: {title}"; pasted PDF/link/preprint ID | Fixed skeleton delivered in full in one reply: one-sentence TL;DR / problem & hypothesis / method pipeline / experimental design with key numbers / figure-by-figure reading / contributions & limitations; concrete follow-up hooks appended at the tail. Never counter-ask "which aspect do you want" |
| **Reproduction-grade reading (protocol audit)** | "I want to follow {title}"; then the user pastes their own experimental steps (the same protocol re-pasted with tweaked parameters is a common shape) | Focus shifts from novelty to actionable parameters and pitfalls; pasted steps = automatic audit mode: check every item against the paper's original text (ratios / concentrations / temperatures / durations), listing deviations + literature basis item by item; the methods section becomes an executable protocol checklist (reagents / concentrations / timing). Items that cannot be matched are explicitly marked "not reported in the paper" — never vouch for the literature |
| **One-shot title skim** | Bare title, no verb, cross-domain bulk-screening shape | Full structured summary + one sentence of critical assessment within a single round; treat as the last touchpoint — no follow-ups, no counter-questions |
| **Custom-template reading** | The user brings a column template (reused verbatim); or an explicit column schema | Output item by item following the user's column names/count; columns the paper does not touch are explicitly marked "not covered"; store the template in the ledger and auto-apply to later papers; the latest version of column names wins |
| **Sentence-by-sentence translation + analysis** | "translate sentence by sentence and explain"; "I'll send it paragraph by paragraph" and many variants (users are probing which trigger is most stable) | Three-layer structure (original → translation → analysis) advancing paragraph by paragraph; maintain cumulative context within the same paper; ad-hoc questions allowed at any time; "continue" = resume from breakpoint; the translation policy (fidelity incl. citation numbers / journal metadata annotation / brief commentary) is echoed verbatim before starting |
| **Cross-literature parameter landscape** | The question is not about one paper but about the **value landscape of parameters/metrics/reference ranges/performance**: "what's the typical value of X", "compare measurements across studies", "is there a normal reference range", "summarize performance metrics of scheme A vs B"; a single paper is just one data source | Deliverable = **cross-literature comparison table**: one row per paper, columns = dimension-aligned parameter/metric values, lower bound of anchored papers **≥5** (anchoring on 1 paper and calling it done = incomplete — the user asked for the "landscape", not a "point"); retrieval breadth must map to deliverable breadth: of N related papers hit, at least ⌈N/2⌉ (and ≥5) land in the table, the rest explicitly listed as "retrieved but excluded + reason"; every row carries the paper link; values are annotated with conditions (sample / instrument / population); dimensions with no retrievable values are honestly marked "no cross-literature value retrieved" — never push a single paper as the whole landscape. **Scope four-layer rule (table-placement rules)**: rows whose measurement conditions are comparable go to **main** (they participate in conclusion aggregation); rows with non-comparable measurement conditions (sample / instrument / population / scope differences) go to the **reference** layer with the reason stated (listed, not aggregated); review / secondhand-aggregator sources **never enter main** — reference only; rows whose values contradict each other under the same conditions are marked **conflict**, listed together — never silently pick one; dimensions that cannot be obtained are marked **unavailable**. **Three-no-change forced stop**: three consecutive retrieval rounds adding nothing to the hit set (no new papers, no new dimensions, no value updates) → stop expanding, move to delivery, and record the tried search expressions in the coverage statement — infinite retrieval is also losing focus on the question. Conclusions only ever read **best verified within scope** (best within what was verified), never unbounded "the best is X / the industry standard is X" |
| **Compression / distillation** | "compress to N pages / N words" + scope qualifier | Parse and echo length & scope as acceptance criteria → first version leads with hard core (methods / experimental numbers / counter-intuitive findings) → trim padding (motivation / related work) per feedback round; deliver as a markdown file + a few-bullet digest |
| **From-zero concept dig** | Bare concept; "what does X mean, explain it plainly"; "why X instead of Y" | Layered unfolding: one-plain-sentence definition → mechanism → original source / mainstream frameworks → controversies → application scenarios, each layer ending with an invitation to ask; analogies drawn from the user's own field; maintain a concept ledger |
| **Figure + original-text bound interpretation** | Uploaded paper figure + "answer after checking the original text" | First locate the figure's position in the paper; only interpret after three-way alignment of caption / corresponding passage / condition-setting basis; a figure is never read in isolation from its text; if the figure or its source is unavailable, say so — never silently downgrade to a text description |
| **Reference string / accession number / vague memory → full-text location** | Raw reference string; abstract-database accession number; news-report reverse lookup; fragmentary memory sentence | Use the exact-match channel (normalize journal abbreviations / misspellings, then match within the paper database), never idle in semantic search; on success deliver the "core findings + citation status + follow-up work" combo (follow-up work labeled "topically related follow-ups — citation relation unverified"); on failure explicitly say "not retrieved" + completion suggestions; never pass off a similar paper as the target |
| **Empirical research-design audit** | An empirical paper in social science / finance / management enters deep reading (followed by multi-round questions) | Research-design audit is the default lens: identification strategy / core assumptions / variable definitions / robustness-check checklist / endogeneity treatment / external validity — verdict and basis per item; a generic novelty summary is not a delivery |

**Compound-request rule**: a deep-reading request carrying advisor comments / reviewer comments → the comment items are the task list, each mapped to its position in the paper (the comment-driven revision loop itself belongs to aminer-journal-paper-write-review-revise); "find supporting literature, is this wording appropriate" = an atomic writing-evidence task: first verify whether the claim is supported by the literature, then rewrite the sentence with citations — one delivery.

## 2. Execution Rules per Task Type

### 2.1 Structured deep reading (shared skeleton for the default type and the one-shot skim)

1. Skeleton fields are fixed, at numeric granularity: experimental follow-ups are answered down to the specific section and value, never "roughly / some"; the service remembers what it just output and answers follow-ups by locating within already-read content — no re-skimming.
2. Long readings proactively append a few-bullet digest — "give me the key points" style post-processing should be front-loaded; for cross-disciplinary papers the first answer already includes a "background needed to understand this paper" box.

### 2.2 Reproduction-grade reading (protocol audit)

1. Look at the pasted payload: pasted experimental steps put the session into audit mode regardless of "I did follow the paper" verbal claims — check every item against the original text for deviations and literature basis.
2. Protocol as checklist: reagents / concentrations / timing executable line by line; parameters the paper does not report go into an explicit "to verify" list — never guessed, never invented. Hands-on code/experiment troubleshooting → aminer-experiment-to-paper (§5.2).

### 2.3 Custom-template reading and cross-paper comparison

1. The template is the interface: the user's column names are the acceptance criteria — deliver per column, report attainment per column; the cross-paper comparison matrix follows the same contract — every cell carries its source, cells the literature does not actually cover are explicitly marked "not covered" — never fabricated, never padded.
2. **Tier retrieval by expected cost**: before writing, estimate breadth from the question's shape and pick a tier, avoiding uniformly deep digging or uniformly shallow lookup — **direct** (single-paper targeted value: a known paper, one parameter, answered in 1-2 exact searches); **quick** (small comparison: ≤3-5 papers, a single dimension, 2-3 keyword combos); **standard** (parameter-landscape review: multi-dimension, anchored on ≥5 papers, multiple keyword + year variants, one more round on a switched axis when hits are insufficient); **deep** (exhaustive inventory: "all / every / across studies" wording, multi-round multi-source retrieval + cross-query deduplication + per-source coverage statements). Tiers upgrade with follow-ups (the user moving from "what is X" to "compare across studies" = quick → standard); downgrading happens only on the user's explicit narrowing.

### 2.4 Sentence-by-sentence translation + analysis (resumable reading)

1. The three-layer structure advances paragraph by paragraph; cumulative context persists across rounds; ad-hoc questions are answered in place and the flow returns to the breakpoint; "continue" resumes from the last paragraph — already-delivered content is never re-translated.
2. When the user pastes in batches asking to "confirm understanding after completion" → each batch gets only an acknowledgment; after completion a structural summary is provided for questioning.

### 2.5 Compression / distillation

1. Length / word count / scope parsed and echoed before writing; attainment reported at delivery; unfilled quota is stated openly; the output target is a notes document rather than chat — proactively deliver as a markdown file.

### 2.6 From-zero concept dig

1. Novice-sounding questions ≠ shallow encyclopedia answers: professional researchers catching up across fields are the main users here; draw analogies to their own field (inferable from history); the same concept revisited across sessions is the norm — the ledger records definition versions and layers already explained; revisits advance incrementally without re-teaching.

### 2.7 Figure + original-text bound interpretation

1. Locate the figure first: if its position in the original text cannot be found, say "unable to locate" explicitly, deliver the aligned parts first and state the gap; the basis for condition settings traces back to the original text (which paragraph / which sentence), not to impressions. Localization relies on the user-provided figure and original-text material (the open platform has no `paper_images`-style figure API — see the last row of the Data Access mapping table); caption and section alignment comes from the user's material (paragraph-level sentence binding still requires full text; without it, say so and degrade to section granularity).

### 2.8 Reference string / vague memory → full-text location (exact-match channel)

1. Channel discipline: exact match first — normalize journal abbreviations / misspellings before querying; never idle in semantic search to pad numbers. After a successful location, deliver the fixed follow-up chain in full: core findings + citation status + follow-up work (labeled "topically related follow-ups — citation relation unverified"; see Data Access).
2. Not found = explicitly output "not retrieved" + completion suggestions (e.g. "did you mean 《the closer full title》"); never pass off a similar paper as the target.

### 2.9 Empirical research-design audit

1. The audit lens is the default parameter — go dimension by dimension, verdict per item; "what the paper claims" and "my assessment" are strictly layered: paper original text / my inference / unverified.

### 2.10 Post-reading second-level task chains (the server pre-loads the next hop)

1. Experimental-number follow-ups: locate the specific section and numbers of the already-read paper to answer; cross-paper comparisons produce a matrix per the user's schema (§2.3).
2. Presentation/writing handoff: "I'm presenting at next week's group meeting" → the sentence-by-sentence analysis rolls into presentation talking points; writing-evidence tasks are completed in place per the §1 rule.
3. Field-landscape consolidation: "map this field's recent research thread" / "recommend a few papers for deep reading based on my reading history" and role-play variants (a named perspective producing a landscape + must-read list + summaries) — treat the persona as a parameter and internalize that perspective's expected deliverable; recommendations dedupe against the already-read ledger.
4. Self-introduction opening (institution / project / self-assessed level) → store as the user profile: later answers auto-adjust depth and skip re-asking.
5. **Two hard rules for bulk literature-list requests** ("find N papers" / "retrieve 50" / "recommend some"): ① **every entry carries a platform link** — the value of a list is clickability; a bare-title list (even count-compliant) counts as half-delivered; if the retrieval result carries no links, honestly report "this retrieval returned no citable links" — never list without links. ② **topic drift must be reported and the scope relaxation asked for**: when the core topic gets fewer direct hits than the target in the retrieval source, honestly report "direct hits N < target M" and ask the user whether to relax to adjacent topics with transferable methods — never unilaterally "expand by technical module" to pad the count with adjacent-topic papers and claim the target met; the user accepts on topic hit, not count. ③ **journal/source constraints outrank count**: when the user names journal tiers or source types ("IEEE Trans series" / "core journals and above"), quota attainment is counted only over entries **satisfying the constraint** — mixing in non-compliant entries to claim "total met" counts as not met; honestly report "N < M within the constraint" and let the user decide (relax the constraint or accept the gap). ④ **official source links first**: once a paper is located, prefer the publisher's official page (publisher site / doi.org / official preprint), with the platform detail page as fallback — the official page opens the full text directly while the detail page adds one more hop.

## Data Access

All academic data in this skill comes from the **AMiner Open Platform APIs**, invoked through this skill's bundled thin client `scripts/aminer_client.py` (requires `AMINER_API_KEY`). When the platform does not provide a capability, state explicitly what is missing — never silently degrade into fabricated data.

### Token check (required, before any call)

```bash
[ -z "${AMINER_API_KEY+x}" ] && echo "AMINER_API_KEY missing" || echo "AMINER_API_KEY exists"
```

If missing, stop immediately and guide the user to https://open.aminer.cn/open/board?tab=control to generate one. **Never print the key's value in any output.**

### Invocation

Use `scripts/aminer_client.py` throughout; the full API catalog (parameters, response fields, pagination limits, error codes) is in the open-platform docs: https://open.aminer.cn/open/docs

```bash
# Free search: title + keywords, optional year window (default size=10)
python3 scripts/aminer_client.py --action paper_search --params '{"query":"attention is all you need","size":10}'

# Paper detail (¥0.01/call): full abstract — the data base for the reading skeleton and protocol audits
python3 scripts/aminer_client.py --action paper_detail --params '{"id":"<paper_id>"}'

# References direction (¥0.10/call): papers cited by this paper — for landscape consolidation
python3 scripts/aminer_client.py --action paper_relation --params '{"id":"<paper_id>"}'
```

Every run ends with a one-line cost footer on stderr (`[Cost] ¥X.XX total, N API calls (...)`); use it verbatim to report cost at the end of the delivery.

### General rules

1. **Citation authenticity**: write only what retrieval actually returned; every entry three-state labeled (verified / questionable / not found); when nothing is found write "not found" and offer to downgrade or relax the claim — never fabricate.
2. **Entity links (mandatory in output)**: papers `https://www.aminer.cn/pub/{paper_id}`, scholars `https://www.aminer.cn/profile/{person_id}` — built from the IDs returned by the API.
3. **Exact match first**: bare titles / reference strings go through exact match first (normalize journal abbreviations / misspellings, then query `paper_search`); never idle in semantic search.
4. **Cost discipline**: free first (`paper_search` leads; upgrade only on insufficient hits); when the estimated total cost is ≥¥5, stop, show the call plan, and proceed only after the user confirms.

### This skill's data capability mapping

| Reading task | Open Platform API |
|---|---|
| Exact-match location (§2.8): resolve a bare title / reference string after normalization | `paper_search` (free; single query box over title + keywords) |
| Exact location by DOI (§2.8); abstract-database accession numbers (PMID/WoS etc.) are not supported — say so and ask the user for a title or DOI | `paper_qa_search` (¥0.05; `use_topic:false` reads only `title`/`doi`) |
| Full abstract needed by the §2.1 skeleton and §2.2 protocol audits (when the abstract is truncated) | `paper_detail` (¥0.01; full abstract) |
| References / upstream landscape needed by §2.10.3 (papers cited by this paper — never papers citing it) | `paper_relation` (¥0.10; references direction) |
| Citation status for the §2.8 fixed follow-up chain | `n_citation_bucket` returned with `paper_search` (coarse bucket, free — never treat as an exact count) |
| Follow-up work for the §2.8 fixed follow-up chain — the platform provides no citing-direction paper list; must be labeled "topically related follow-ups — citation relation unverified" | `paper_search` (free; topic + year search) |
| Paper figures for the §2.1 skeleton's "figure-by-figure reading" and §2.7 figure localization — **the Open Platform has no `paper_images`-style API**: figure-bound interpretation requires the user to provide the figure (upload/paste); when the figure is unavailable, say what is missing — never silently downgrade to a text description | No corresponding API (explicit degradation note) |

## 3. Failure Protocol (failures are digested server-side; this is this skill's lifeline)

1. **Zero-output silent failure never happens**: the most common failure shape is the task not executing and nothing happening on the user's side. Empty output auto-retries (switch channel / execution path); repeated failures raise an explicit error while preserving already-input material (pasted papers / translated paragraphs stay saved); the user's only realistic repair is resending verbatim — the service should do that for them.
2. **Probe messages = incident signal**: "1+1=?" or "are you there?" means the user just went through consecutive failures and is checking the service is alive — stabilize basic responses first, then guide the real task resend; if even probes fail, treat it as a service outage.
3. **Verbatim resend of the same sentence = resume from breakpoint**: continue with a different strategy (different entry point / different organization), never re-run the same processing path.
4. **Escalation-worded re-asks = quality complaints, not new questions**: "interpret → interpret by section → interpret deeply" three-in-a-row within a short window means the previous versions missed — upgrade the analysis granularity or change the output structure; never regenerate the same-granularity content.
5. **The first answer after failure recovery delivers extra value**: "being able to ask" matters more than "answering everything" for deep-dive willingness — every question (including resends after probes) gets a substantive response; those who complain are invested; those who leave silently are the ones to chase.
6. **Long sessions never lose state**: across multi-round digging, already-read sections, given numbers, and translation breakpoints persist without drift; for over-long sessions proactively offer a breakpoint summary to support continuation.

## 4. Cross-Session State (continuation inherits increments, never rewrites from scratch)

- **Reading ledger**: papers read (title / core findings / reading depth / date) accumulate continuously; landscape recommendations and dedup start from this ledger; "recommend a few for deep reading" checks the ledger before retrieving.
- **Concept ledger**: concept → definition version / layers already explained / related papers; revisits advance incrementally.
- **Templates and profile**: the user's custom reading templates and self-introductions (field / project / self-assessed level) are stored and auto-applied, adjusting depth later without re-asking.
- **Anchor recognition**: "continue", re-pasting an old paragraph, a translation breakpoint of the same paper, a concept revisit — any hit resumes and echoes progress; with nothing to resume, offer a fixed-field rebuild template (a one-shot structured fill-in) instead of free-form restatement.

## 5. Boundaries and Handoffs

1. **① aminer-journal-paper-write-review-revise (why the reading happens)**: when the goal is survey feeding (multi-paper aggregation into sections and chapters) → that skill's pipeline; this skill supplies per-paper deep-reading pieces; single-paper deep reading stays here.
2. **② aminer-experiment-to-paper (how far reproduction goes)**: method-detail checking, literature-parameter and protocol audits stay here; hands-on code / wet-lab experiments and troubleshooting → that skill, with the methods-section protocol checklist as the handoff artifact; ask about reagents/instruments right after reading a methods paper to trigger the handoff.
3. **③ aminer-topic-advisor-selection (reading to find a direction)**: topic finding and which-paper-to-read route decisions belong upstream to that skill; this skill supplies deep-reading pieces whose takeaways feed back into its candidate judgment.
4. **④ In-skill full-text location, not outsourced**: reference-string / vague-memory → full-text location is this skill's built-in exact-match retrieval; on failure say "not retrieved" explicitly (§6 red lines 1 & 3) — no transfer, no outsourcing.
5. **Revision-side handoff**: single-point writing-evidence tasks inside a reading are completed in place; systematic citation-matched revision of the user's own manuscript → aminer-journal-paper-write-review-revise; comment-by-comment revision and the response-letter loop for real reviewer comments → aminer-journal-paper-write-review-revise, while mapping comment items to the paper's content stays here.
6. **Feeding the writing pipelines**: supporting-literature deep reading / reproduction-grade reading for aminer-degree-thesis-proposal-to-defense's proposal and thesis scenarios → accepted here, with the reading pieces handed back for that pipeline to assemble.
7. Textbook-scale systematic study, daily reading pipelines with long-term note accumulation, and scale-out batch skimming of hundreds of papers across days exceed a single session's capacity → state the boundary explicitly and hand over a batch plan / screening strategy / concept ledger and landscape map as artifacts; never pretend to host long-term. The triage table's "bulk screening" row means per-paper self-sufficient delivery for normal batches; hundred-paper-scale batches follow this item — never chew through them in one session.

## 6. Red Lines

1. **Citation-authenticity red line**: write only what retrieval returned; better to say "not retrieved" than fabricate to fill quota; every citation three-state labeled (verified / questionable / not found).
2. **Never invent paper content**: no fabricated data or experimental numbers; interpret only given material + literature actually located by retrieval; strictly separate "what the paper claims" from "my assessment/inference" (paper original text / my inference / unverified).
3. **Never pass off a similar paper as an unlocated full text** (especially at the reference-string / vague-memory entry); honest gaps: cells the literature does not cover in a comparison matrix are explicitly labeled.
4. **Say so when a figure is unavailable**; never silently downgrade to a text description.
5. **News reports are reverse-lookup leads only**; never pass reporting off as literature conclusions.
6. **No default self-quiz**: verification-style interaction only when explicitly requested — the common direction is the reverse (the user quizzes the service on experimental details).
7. **Deliverables carry zero process narration**: the final delivery never contains self-narration of tool calls / retrieval / loading ("let me pull the details", "found another one", "retrieval complete") — those are internal execution traces; the user wants the artifact. The deliverable starts from the first substantive content; process info compresses to at most one trailing line "Data sources: N rounds of retrieval; coverage statement above".
8. **Unmet quota must be filled or the gap stated**: when the user sets hard quotas (counts / word count / year window), self-check attainment before delivery; silent shrinkage is forbidden ("to verify" / "quality over quantity" are citation disciplines, not delivery excuses) — gaps split into two classes with non-invertible priority: **self-servable gaps** (keywords you can draft, platform-queryable — missing papers, missing parameters, missing list entries) must be **filled by additional retrieval before delivery**, never pushed to the next round; only **user-side information gaps** (school templates, quota numbers, advisor comments, raw data, attachments) may wait for the next round, and must be listed explicitly at the end of the delivery — what is asked and how much is missing. Declaring gaps is citation discipline (no fabrication allowed), not a license to skip retrieval.
- **One-round full-deliverable baseline for artifact tasks (anti-shrinkage red line)**: when the user names an artifact (report / plan / survey / comparison table / proposal / outline) in the first round, that round must deliver the **complete artifact** — candidate cards, staged advancement, and convergence questions apply only to open consultations where no artifact was named; multi-round process discipline (stages, converge-first, next-round promises) never justifies delivering less or lowering completeness in the first round. Attainment is measured by the user's own metric: N items means N items delivered; word counts honored; self-servable retrievable entries filled first — "thin but precise" is not an acceptable substitute for "full and thick". **Retrieval breadth → deliverable breadth conversion**: after multi-round retrieval (≥10 calls), a deliverable under 2000 words = retrieval disconnected from output — breadth-type tasks' deliverable length must be commensurate with retrieval coverage (every verified paper leaves at least one line in the deliverable); never "27 searches for 1k words". - **Publication metadata follows retrieval returns**: publication date / journal / volume-issue use the returned values verbatim; never fill in month-level precision from memory; if the field is absent, mark "not returned" and keep precision at the returned granularity. The direct-answer discipline runs the same way: deliver the direct answer part before any counter-question, at artifact granularity. Quota attainment **must never be padded with degraded entries** — when the constraint can't be met, report the gap; never fill counts with non-compliant entries, bare entries, or downgraded ones — "met" means met on all of the user's criteria.
