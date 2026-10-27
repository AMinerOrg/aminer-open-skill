# Insight Classification Rubric

Method source: *InsightEval: An Automated System for Evaluating Insightfulness in Scientific Papers* (Xia, Yan, Fan, Guo, Zhang, Cheng; SIGIR '26 demo).

Core definition: **insight = relative gain in understanding** — how much more a reader who has already mastered all of the paper's cited references would understand after reading this sentence or section. Scoring is therefore always "opinion sentence vs. its evidence", never "does the sentence sound profound".

> Items marked *(paper)* are stated in the paper. Items marked *(skill)* are operationalizations added so an agent can apply the method consistently (the paper only gives the two ends of each scale and does not publish level thresholds).

---

## 1. Sentence types *(paper §3.1)*

| Type | Paper's definition | Example |
| --- | --- | --- |
| `context` | Background statements without citations or author opinions | "Large language models are widely used for writing." |
| `citation` | Contains references but merely summarizes prior work | "DeepReview [27] proposes a multi-stage framework that emulates expert reviewers." |
| `opinion` | Expresses the author's interpretation, critique or synthesis, often marked by discourse markers (However, We argue that, Crucially…) | "However, existing frameworks [20, 27] primarily assess textual quality, not the understanding a paper adds." |

**Decision order** *(skill)*

1. Does the sentence contain the **author's own** judgment, explanation, comparison, critique, generalization or hypothesis beyond reporting what a source says? Yes → `opinion` (even if it carries citations).
2. Otherwise, does it report / summarize prior work (a citation marker, or a named existing method or paper)? Yes → `citation`.
3. Otherwise → `context`.

**Edge cases** *(skill)*

- The author **describes their own** method, setup or data size ("We use Qwen3-32B as the backbone.") → `context`. An **interpretation** of results ("This suggests that AI favors analytical framing.") → `opinion`.
- Bare numbers ("Human surveys score 3.01 on Depth.") → `context`; "… because X …" explanations → `opinion`.
- A discourse marker that merely contrasts facts ("However, the corpus has 196 papers.") is not an opinion unless it interprets something.
- Research questions and contribution lists ("Our contributions are: …") → `context`.
- Part summary, part commentary → `opinion`.
- Figure / table captions, formulas, reference fragments, affiliations → `context`.
- `rule=` priors are hints only: `strong` is usually right, `weak` is often a false alarm, and a sentence without `rule=opinion` can still be an opinion.

---

## 2. Three-dimension scoring of opinion sentences *(paper §3.3)*

Compare the opinion **only with the evidence provided** and give an integer 1–5 per dimension.

| Dimension | Paper's question | 1 *(paper)* | 5 *(paper)* |
| --- | --- | --- | --- |
| **Depth** | Does the opinion provide deeper understanding than the evidence? | mere paraphrasing | fundamentally new insight |
| **Breadth** | Does the opinion synthesize multiple sources? | relies on a single source | comprehensive integration across references |
| **Height** | Does the opinion operate at a higher level of abstraction? | phenomenon-level description | generalizable principle or hypothesis |

Intermediate anchors *(skill)*:

| Score | Depth | Breadth | Height |
| --- | --- | --- | --- |
| 2 | Adds a label or mild elaboration, no mechanism | Mentions several sources but only lists them in parallel | Groups similar cases into a category |
| 3 | Explains a "why / how" the evidence does not state | Relates 2–3 sources along one shared axis (compare, contrast) | Makes a general statement about a class of methods or problems |
| 4 | Identifies a mechanism, causal structure or limitation with specific grounds, clearly beyond the evidence | Integrates several sources into a pattern none of them states alone | Proposes a principle, trade-off or framework that organizes the class of phenomena |

**Procedure** *(paper: chain-of-thought — compare first, then score)*

1. Summarize in one line what the evidence says (name the `R#`).
2. State what the opinion adds beyond it (mechanism, condition, link, generalization) — or that it adds nothing.
3. Write the rationale (≤ 60 words, naming the `R#` compared against).
4. Then give the three scores.

**Discipline**

- Reward **added content**, not confident tone, polish or jargon. AI-generated surveys in particular can sound analytical without adding anything (paper §4.4).
- Score the dimensions independently: a sentence can be high on Height and low on Depth (a sweeping but empty claim), or high on Depth and low on Breadth (a deep dive into one paper).
- Anything the evidence already states explicitly: Depth ≤ 2.
- Breadth ≥ 3 requires that the sentence really connects content from two or more different sources, not just that several citation numbers are attached.
- Do not drift toward 3 to look reasonable. In the paper (Qwen3-32B, survey papers) the means are roughly Depth 2.9–3.0, Breadth 2.5, Height 2.8–3.0; an overall mean persistently above 4 usually means lenient scoring.

**No or weak evidence** *(skill)*

| Situation | What to do |
| --- | --- |
| `evidence_scope=none` (no citation in the sentence or its paragraph) | Compare with common knowledge of the field and the surrounding context; `confidence=low`; Breadth ≤ 3; never give a 5 |
| Title only ("no abstract/full-text evidence, title only") | `confidence` at most `medium`; say in the rationale that evidence is thin |
| `evidence_scope=paragraph` | The evidence comes from references cited elsewhere in the paragraph: use it to decide whether the sentence merely restates; be cautious with Breadth |
| Excerpt clearly unrelated to the sentence | Treat as no evidence and say "excerpt not relevant" in the rationale |

**confidence**: `high` = the abstract / full-text excerpt directly addresses the opinion; `medium` = indirect or title only; `low` = no evidence or irrelevant excerpt.

### Worked examples

> Illustrative only; the evidence is invented.

1. Opinion: *Transformers are good at modelling long sequences [R1].* Evidence R1: "We propose the Transformer, which models long-range dependencies via self-attention."
   → rationale: "Restates R1; no new mechanism or condition." **D1 B1 H1**, confidence high.
2. Opinion: *Unlike [R2], which relies on labels, [R3] shows the gain comes from the pretraining objective rather than the data size, so scaling alone cannot close the gap.* R2: a supervised method; R3: an ablation showing the pretraining objective contributes most.
   → rationale: "Contrasts R2 with R3 and infers 'scaling alone cannot close the gap' from R3's ablation; R3's abstract does not state that inference." **D3 B3 H3**, confidence medium.
3. Opinion: *These results suggest that robustness failures stem from distribution shift between pretraining and deployment, a pattern shared by R4, R5 and R6 despite their different architectures.* R4–R6: three papers each reporting robustness drops on a different architecture.
   → rationale: "Induces a common cause (distribution shift) across three architectures; each abstract only reports its own phenomenon." **D3 B4 H4**, confidence medium.
4. Opinion: *Existing evaluation methods all ignore the gain in understanding.* (no citation in the sentence or its paragraph)
   → rationale: "No evidence to compare with; a sweeping critique of a whole class of methods with some abstraction, but the synthesized sources cannot be verified." **D2 B2 H3**, confidence low.

---

## 3. Composite score and levels

- **Composite** *(paper, Eq. 1)*: `S = α·Depth + β·Breadth + γ·Height`, equal weights by default. The skill divides by the weight total so the composite stays on 1–5: `S = (α·D + β·B + γ·H) / (α+β+γ)`. Change weights with `--weights`.
- **Insight level** *(skill; the paper's Table 2 reports Low / Medium / High shares but no thresholds)*: `S < 2.5` → low; `2.5 ≤ S < 3.5` → medium; `S ≥ 3.5` → high. Change with `--thresholds`.
- **Dominant dimension** *(skill)*: all three scores ≤ 2 → `none` (no clear gain); tie for the top score → `mixed`; otherwise the top dimension.
- **Paper profile** *(skill)*: range of the three dimension means ≤ 0.3 → `balanced`; otherwise the dimension with the highest mean.

---

## 4. Section types *(paper §4.3 / Table 2)*

Judge a section that contains citations as a whole:

| Type | Meaning | Cues |
| --- | --- | --- |
| `descriptive` | Factual overview: lists or summarizes prior work or the system | mostly "X proposes…, Y implements…"; few author opinions |
| `comparative` | Compares approaches | **comparison is the organizing principle**: similarities, differences, trade-offs along explicit dimensions |
| `analytical` | Offers insight and critical analysis | explains "why", points out limitations, synthesizes patterns, generalizes |

For mixed sections take the main function; choose `comparative` only when comparison really structures the section (it is rare in the paper: 2.6 % of human-written and 1.0 % of AI-generated survey sections).

A section's insight level comes from the mean composite of its scored opinion sentences and the thresholds above; sections without opinion sentences get no level.

---

## 5. Limitations (state them to the user)

- Scores are an LLM's relative judgments; the paper itself only reports significance at the population level (Cohen's d of 0.08–0.22), so **do not treat a single sentence score as a precise measurement**.
- Evidence is mostly abstracts. If a detail is not in the abstract, the opinion may actually come from the cited paper's body, so "gain" can be overestimated; `confidence` exists for this reason.
- The thresholds and intermediate anchors are this skill's choices; a different convention shifts the results as a whole.
- This evaluates the **text relative to its cited references**. It says nothing about whether the experiments are sound or the conclusions are correct.
