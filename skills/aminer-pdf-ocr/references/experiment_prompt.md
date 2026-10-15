# Experiment Extraction Prompt

After OCR succeeds, the agent MUST extract structured experiment information from `result.md` using this prompt. Fill `{PAPER_TITLE}` (first Markdown heading, else the input stem) and `{PAPER_MARKDOWN}` (full `result.md`). Write one JSON object to `<output-dir>/experiments.json`, then paste that same object in the chat reply.

Do not invent facts. If a field is unknown, use `""` / `[]` / `null`. Do not emit any `justification` field.

```text
You extract structured experiment information from ONE scientific paper given as full Markdown.

Paper title:
{PAPER_TITLE}

Return ONLY one valid JSON object. No markdown fences. No commentary.
If a field is unknown, use "" / [] / null as appropriate. Do NOT invent facts not supported by the Markdown.
Do NOT include justification fields.

JSON schema:
{
  "research_problem": "",
  "research_problem_description": "",
  "research_problem_aliases": [],
  "domain": "",
  "experiments": [
    {
      "experiment_name": "",
      "experiment_type": "",
      "research_goal": "",
      "experiment_subject": [],
      "methods": [
        {
          "name": "",
          "description": "",
          "aliases": []
        }
      ],
      "datasets": [
        {
          "name": "",
          "aliases": [],
          "dataset_type": "",
          "description": "",
          "sample_size": null,
          "is_public": null,
          "is_self_collected": null,
          "urls": [],
          "github_urls": [],
          "doi_list": [],
          "cstr_list": []
        }
      ],
      "metrics": [],
      "key_results": [],
      "sample_size": null,
      "conclusion": "",
      "limitations": "",
      "evidence": []
    }
  ]
}

========== GLOBAL RULES ==========
1) Grounding: Every claim must be supported by the Markdown below. Prefer Abstract / Introduction / Method / Experiments / Results / Conclusion. Ignore References bibliography entries as experiment evidence.
2) Output language: English for all string fields (research_problem, descriptions, names, research_goal, experiment_subject, metrics, key_results, conclusion, limitations, domain, experiment_type, evidence).
3) Paper-level vs experiment-level:
   - research_problem* and domain are PAPER-level (outside experiments[]).
   - Do NOT duplicate research_problem* inside each experiment.

========== PAPER-LEVEL FIELDS ==========
- research_problem: ONE short English phrase (≤5 words). Task/problem domain (e.g. "Machine Translation", "Point Cloud Completion"). NOT a sentence, NOT method/model/dataset name, NOT equal to any methods[].name or the paper system title alone. "" if unknown.
- research_problem_description: 2–4 English sentences defining the PROBLEM AS AN ENTITY ("X is a ... that ..."): definition, core challenge, why it matters. Write the problem itself, NOT what this paper does. FORBIDDEN openers/patterns: "The paper ...", "This paper ...", "We ...", "Our ...", and any Chinese characters. "" if unknown.
- research_problem_aliases: only widely-recognized abbreviations/alt names (e.g. ["DPO"]); [] if none; do NOT fabricate synonyms.
- domain: exactly ONE of:
  ["computer_science", "engineering", "environment", "materials", "medicine", "biology", "physics", "chemistry", "mathematics", "other"]
  Prefer "computer_science" for typical AI/ML/systems papers. Use "other" only if none fit. "" if truly unknown.

========== EXPERIMENTS ==========
- experiments: 0–5 items. Prefer fewer.
  Split into multiple experiments ONLY when the paper clearly presents distinct studies, e.g.:
  main experiment vs ablation; automatic evaluation vs human/user study; substantially different methods/settings.
  Do NOT split only because there are multiple datasets or metrics (put them in datasets[] / metrics[]).
  If there is no empirical study, return [].
  Never invent experiments.

Paper-level methods budget (across ALL experiments):
- Total count of methods[].name ≤ 3.
- E=0 → no methods; E=1 → 0–3 methods; E=2 → prefer 1 each (2+1 OK); E=3+ → at most 1 method per experiment.
- Prefer author-proposed / paper-core methods. Do NOT spend budget on baselines.

Per experiment:
- experiment_name: prefer paper title if it names the main method/system; method-level name, not dataset alone.
- experiment_type: exactly ONE of:
  ["ablation", "benchmark", "case_study", "comparison", "data_analysis", "empirical_study", "field_study", "human_study", "lab_experiment", "simulation", "survey", "other"]
  Pick the best fit for THIS experiment block. "" if unknown.
- research_goal: 1–2 English sentences; "" if unknown.
- experiment_subject: 0–3 short English task phrases appearing in the paper (e.g. "face anti-spoofing"); not model/dataset names; [] if unknown.
- metrics: 0–20 metric NAMES only (no numeric scores here); not dataset names; [] if unknown.
- key_results: 0–8 items; one English sentence each; include numbers ONLY if present in the Markdown; do not fabricate.
- sample_size: top-level experiment sample size (integer) if the paper reports an overall subject/sample count for this study AND it is NOT already captured as datasets[].sample_size; else null. Do NOT invent. Do NOT copy max(datasets[].sample_size).
- conclusion: 1–5 English sentences summarizing the paper's conclusion for this study (entity-grounded; no Chinese). "" if unknown.
- limitations: 1–5 English sentences on limitations stated or clearly implied in the paper. "" if unknown.
- evidence: 0–8 short English sentences that are concise paraphrases of key supporting statements from Experiments/Results. [] if unknown.

methods[] each object:
- name: short English phrase (≤5 words AND ≤40 chars). ONLY the paper's CORE contribution method. Prefer author-coined names that appear in the Markdown. Do NOT list baselines / compared methods / training recipes / generic optimizers as methods (anti-examples as standalone methods: plain "DPO", "SFT", "LoRA", "Adam") unless that IS the paper's named core contribution. Do NOT invent paradigms not in the text (anti-examples: "contrastive learning" unless verbatim). No consumer chat products ("ChatGPT"). No datasets/metrics.
- description: 2–4 English sentences defining the method AS AN ENTITY ("X is a ... that ..."): what it is, core mechanism, problem it solves. NOT "The paper uses X to ...". No Chinese. Distinct across methods.
- aliases: recognized abbreviations only; [] if none.

datasets[] (only datasets actually used/built/evaluated in THIS experiment; not merely cited):
- name: proper dataset/benchmark name only (required). Drop if unsure. FORBIDDEN: model names (GPT-3.5), "Table 2"/"Figure 3"/"Algorithm 1"/"Section 4.2", "et al." citations, method/concept names.
- aliases: other names/abbreviations in the paper; [] if none.
- dataset_type: one of {tabular, image, video, text, audio, graph, point_cloud, 3d_mesh, time_series, multimodal, code, other}; "" if unknown.
- description: 2–4 English sentences defining the dataset AS AN ENTITY ("X is a dataset that ..."): content, scale, structure, task. NOT the paper's score on it. No Chinese. Distinct per dataset.
- sample_size: integer size of the dataset resource, or null; NOT the evaluated subset size unless that is all that exists.
- is_public / is_self_collected: true/false/null.
- urls / github_urls / doi_list / cstr_list: ONLY identifiers that appear verbatim in the Markdown; [] if none; never fabricate.

========== SELF-CHECK BEFORE EMIT ==========
- Valid JSON only.
- No justification keys anywhere.
- methods name budget ≤ 3 across the paper.
- No Chinese in description/conclusion/limitations/research_problem_description.
- No paper-structure dataset names (Table/Figure/...).
- domain / experiment_type are from the allowed enums (or "").

========== PAPER MARKDOWN (FULL TEXT) ==========
{PAPER_MARKDOWN}
```
