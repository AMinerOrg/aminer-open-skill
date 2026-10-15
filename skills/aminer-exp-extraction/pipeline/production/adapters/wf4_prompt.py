"""wf4 LLM prompt builder — paper-level research_problem* + experiments[0..3].

Mirrors ``build_wf8_dev20_v2_prompt`` style (``/no_think`` header, numbered-
sentences block) with a multi-experiment schema: paper-level problem fields
plus up to 3 per-experiment objects (methods/datasets/metrics/etc.).

wf4 is an experimental, non-canonical workflow. This module is text-only —
parsing/normalization lives in ``wf4_normalize.py``.
"""

from __future__ import annotations


def _render_wf4_prompt_body(sentences_block: str, paper_title: str) -> str:
    """Render the wf4 multi-exp prompt body around a pre-formatted Sentences block.

    Shared by V0 (``build_wf4_prompt``) and the structured adapter so the
    ``/no_think`` header, paper title, schema and rules are byte-identical and
    kept in one place — the ONLY caller-controlled variable is
    ``sentences_block`` (the text emitted under the trailing ``Sentences:``
    header).
    """
    title_line = paper_title or "(unknown)"
    return f"""/no_think
Extract experiment, research, and dataset information from a scientific paper.

Paper title:
{title_line}

Return ONLY valid JSON:
{{
  "research_problem": "",
  "research_problem_description": "",
  "research_problem_aliases": [],
  "domain": "",
  "experiments": [
    {{
      "experiment_name": "",
      "experiment_type": "",
      "key_results": [],
      "methods": [
        {{
          "name": "",
          "description": "",
          "aliases": []
        }}
      ],
      "research_goal": "",
      "experiment_subject": [],
      "metrics": [],
      "datasets": [
        {{
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
        }}
      ]
    }}
  ]
}}

Rules:
- research_problem: ONE short English phrase (≤5 words); paper-level task or problem domain the paper addresses (e.g. "Machine Translation", "Language Understanding", "Object Pose Estimation"); NOT a sentence, NOT a method name, NOT a model name, NOT a dataset name; NOT equal to any methods[].name or the paper's system/method title alone; prefer the task domain; "" if unknown. Do NOT put research_problem inside each experiment object.
- research_problem_description: 2-4 English sentences defining the research problem AS AN ENTITY ("X is a ... that ..."), covering its definition, core challenge, and why it matters. MUST be in English; FORBIDDEN Chinese characters (rewrite any Chinese content in English). Write the problem itself, NOT what this paper does. FORBIDDEN openers (rewrite instead of using these): "The paper addresses ...", "The paper studies ...", "The paper investigates ...", "The paper proposes ...", "The paper introduces ...", "This paper ...", "We ...", "Our ...". A reader who has not read the paper must be able to understand what the problem is. SELF-CHECK before emitting: if the field starts with or contains "The paper" / "This paper" / "We " / "Our " OR contains any Chinese character, REWRITE it as an English entity definition. "" if unknown. Do NOT put research_problem_description inside each experiment object.
- research_problem_aliases: only widely-recognized academic abbreviations or alternative names for the problem (e.g. ["DPO", "Direct Preference Learning"]); [] if none. Do NOT fabricate synonyms or descriptive paraphrases.
- domain: paper-level academic field; exactly ONE of {{computer_science, medicine, biology, chemistry, physics, materials, engineering, economics, education, energy, environment, social_science, other}}; CS/ML/NLP/CV/SE papers → computer_science; pick the dominant field of the paper, not a passing application mention; "" if unknown. Do NOT put domain inside each experiment object.
- experiments: 0 to 3 items. Split into multiple experiments ONLY when the paper clearly contains distinct studies such as: main experiment vs ablation study; offline/automatic evaluation vs human study/user study; completely different methods or experimental settings. Do NOT split when differences are only the same method on multiple datasets (put all in datasets[]) or multiple metrics (put all in metrics[]), or minor hyperparameter sweeps not presented as separate studies. If there is no independent empirical study evidence in the sentences, return []. Never invent experiments not supported by the sentences. Hard cap: at most 3.
- Paper-level methods budget: the total number of method names across ALL experiments must be ≤ 3. Allocation: E=0 → no methods; E=1 → that experiment may have 0–3 methods; E=2 → prefer 1 method each (2+1 allowed); E=3 → at most 1 method per experiment. Prefer author-proposed / paper-core methods that appear in the paper; do NOT spend budget on baselines.
- Experiment-scoped rules below apply INSIDE each experiments[] item:
  - experiment_name: prefer paper title if it names the main method; method-level name, not dataset alone.
  - experiment_type: exactly ONE of {{benchmark, comparison, ablation, simulation, survey, human_study, field_study, lab_experiment, clinical_trial, case_study, empirical_study, data_analysis, other}} for THIS experiment (do not copy one label across distinct studies). Priority: named ablation/component-removal → ablation; public datasets/leaderboards → benchmark; method A vs B without a standard-benchmark framing → comparison; user/human study → human_study; literature review → survey; else the closest remaining label or other; "" if unknown.
  - key_results: 0-5 items; one sentence each; include numbers only if in sentences below; do not fabricate.
  - methods: 0–N objects, each {{"name": "", "description": "", "aliases": []}}. name: short English phrase (≤5 words AND ≤40 characters); ONLY the paper's CORE technical contribution (author-coined or the main proposed method). Prefer author-coined names that appear verbatim in the sentences (e.g. "DeePSiM", "ToolMaker"). Do NOT list baselines, compared methods, training recipes, or generic alignment/optimization algorithms as methods (anti-examples as standalone methods: plain "DPO", "Direct Preference Optimization", "SFT", "LoRA", "Adam") unless that algorithm under an author-coined name IS the paper's core contribution. General paradigms ONLY if the exact phrase appears in the sentences below AND it is the paper's core method. Do NOT invent common paradigms (anti-examples: "contrastive learning", "Autoregressive Blank Infilling") unless they appear verbatim. Do NOT extract consumer chat products (anti-example: "ChatGPT") or bare software/framework product names as methods. NOT datasets, NOT metrics, NOT ablation/evaluation protocol sentences, NOT descriptive sentences. If a name is written as "Full Name (ABBR)", put ABBR in aliases (not as a separate method) and keep a short core name. description: 2-4 English sentences defining the method AS AN ENTITY ("X is a ... that ...") — what the method IS, its core mechanism, the problem it solves, and why it matters; MUST be in English; FORBIDDEN Chinese characters (rewrite any Chinese content in English); SELF-CHECK before emitting: if the field contains any Chinese character, REWRITE it as an English entity definition; NOT what this paper does with it (anti-example: "AlphaFold uses contrastive learning to improve accuracy..."); NOT model names, software, or datasets alone; within the same paper, two methods MUST NOT share identical or near-identical descriptions; "" if unknown. aliases: only widely-recognized academic abbreviations or alternative names used in the paper (e.g. ["DPO"]); [] if none; do NOT fabricate synonyms. [] if no methods known.
  - research_goal: 1-2 sentences; "" if unknown.
  - experiment_subject: 0-3 short English phrases naming the TASK or problem domain studied (e.g. "point cloud completion", "face anti-spoofing", "semi-supervised semantic segmentation"); prefer task phrases that appear in the paper, not generic labels like "deep learning"; not model/baseline names, not dataset names; [] if unknown.
  - metrics: 0-20 metric names stated in the sentences below; names only, not numeric results; not dataset names; [] if unknown.
  - datasets: 0 to N datasets actually used, built, or evaluated in THIS experiment (not merely cited). For each dataset:
    - name: proper dataset/benchmark name only (required); NOT model names (e.g. GPT-3.5), NOT "Table 2", NOT citations ("Liu et al."), NOT methods/concepts; drop if unsure.
    - aliases: other names/abbreviations used in the paper; [] if none.
    - dataset_type: one of {{tabular, image, video, text, audio, graph, point_cloud, 3d_mesh, time_series, multimodal, code, other}}; "" if unknown.
    - description: 2-4 English sentences defining the dataset AS AN ENTITY ("X is a dataset that ...") — what data it contains, its scale, how it is structured, and what research task it serves; MUST be entity-specific and grounded in the sentences (prefer size/domain/split/annotation details when present); MUST be in English; FORBIDDEN Chinese characters (rewrite any Chinese content in English); SELF-CHECK before emitting: if the field contains any Chinese character, REWRITE it as an English entity definition; write the dataset itself, NOT the paper's score on it (anti-example: "A test set of 100 entities for comprehensive evaluation."); within the SAME experiment/paper, each dataset description MUST be distinct — FORBIDDEN copying one generic description across different dataset names (anti-example: BigCodeBench and CodeSearchNet both described as "A benchmark for code generation and summarization..."); "" if unknown.
    - sample_size: integer count of instances/samples/subjects in the dataset resource, or null if unknown; NOT the experiment's evaluated subset.
    - is_public: true if publicly released, false if private/restricted, null if unknown.
    - is_self_collected: true if the authors created it, false if it is a third-party benchmark, null if unknown.
    - urls, github_urls, doi_list, cstr_list: fill ONLY with identifiers that appear verbatim in the sentences below; [] if none; do not fabricate URLs or DOIs.
  - Return [] for datasets if this experiment uses no dataset.
- No markdown fences, no explanation.

Sentences:
{sentences_block}
"""


def build_wf4_prompt(sentences: list[str], paper_title: str) -> str:
    """Build the multi-exp LLM prompt for wf4 (paper RP + experiments[0..3])."""
    numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sentences))
    return _render_wf4_prompt_body(numbered, paper_title)
