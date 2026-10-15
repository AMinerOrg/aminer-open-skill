"""wf4 per-model prompt adapter.

Investigation (``WF4_MODEL_INVESTIGATION_REPORT.md``) showed the production
``build_wf4_prompt`` fails small non-LLM models because it ENDS with a numbered
sentence block (``Sentences:\\n1. .. N.``), triggering continuation numbering.
The proven fix is to (a) move sentences BEFORE the JSON instruction and (b)
terminate the prompt with ``Return ONLY valid JSON starting with:\\n{`` so the
model's first generated token is ``{``.

This module dispatches on an ``adapter`` name. ``None`` (or ``"v0"``) returns
the unmodified ``build_wf4_prompt`` (backward-equivalent). ``"v3"`` returns the
JSON-terminated variant validated in the diagnostic (parse_ok for baseline
2/2). The schema and rules are kept identical to V0 so the only variable is
prompt structure.

This module is text-only and does NOT modify ``build_wf4_prompt``.
"""

from __future__ import annotations

from pipeline.production.adapters.wf4_prompt import (
    _render_wf4_prompt_body,
    build_wf4_prompt,
)

# Keep byte-synced with wf4_prompt._render_wf4_prompt_body schema + rules.
_SCHEMA = """{
  "research_problem": "",
  "research_problem_description": "",
  "research_problem_aliases": [],
  "domain": "",
  "experiments": [
    {
      "experiment_name": "",
      "experiment_type": "",
      "key_results": [],
      "methods": [
        {
          "name": "",
          "description": "",
          "aliases": []
        }
      ],
      "research_goal": "",
      "experiment_subject": [],
      "metrics": [],
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
      ]
    }
  ]
}"""

_RULES = """Rules:
- research_problem: ONE short English phrase (≤5 words); paper-level task or problem domain the paper addresses (e.g. "Machine Translation", "Language Understanding", "Object Pose Estimation"); NOT a sentence, NOT a method name, NOT a model name, NOT a dataset name; NOT equal to any methods[].name or the paper's system/method title alone; prefer the task domain; "" if unknown. Do NOT put research_problem inside each experiment object.
- research_problem_description: 2-4 English sentences defining the research problem AS AN ENTITY ("X is a ... that ..."), covering its definition, core challenge, and why it matters. MUST be in English; FORBIDDEN Chinese characters (rewrite any Chinese content in English). Write the problem itself, NOT what this paper does. FORBIDDEN openers (rewrite instead of using these): "The paper addresses ...", "The paper studies ...", "The paper investigates ...", "The paper proposes ...", "The paper introduces ...", "This paper ...", "We ...", "Our ...". A reader who has not read the paper must be able to understand what the problem is. SELF-CHECK before emitting: if the field starts with or contains "The paper" / "This paper" / "We " / "Our " OR contains any Chinese character, REWRITE it as an English entity definition. "" if unknown. Do NOT put research_problem_description inside each experiment object.
- research_problem_aliases: only widely-recognized academic abbreviations or alternative names for the problem (e.g. ["DPO", "Direct Preference Learning"]); [] if none. Do NOT fabricate synonyms or descriptive paraphrases.
- domain: paper-level academic field; exactly ONE of {computer_science, medicine, biology, chemistry, physics, materials, engineering, economics, education, energy, environment, social_science, other}; CS/ML/NLP/CV/SE papers → computer_science; pick the dominant field of the paper, not a passing application mention; "" if unknown. Do NOT put domain inside each experiment object.
- experiments: 0 to 3 items. Split into multiple experiments ONLY when the paper clearly contains distinct studies such as: main experiment vs ablation study; offline/automatic evaluation vs human study/user study; completely different methods or experimental settings. Do NOT split when differences are only the same method on multiple datasets (put all in datasets[]) or multiple metrics (put all in metrics[]), or minor hyperparameter sweeps not presented as separate studies. If there is no independent empirical study evidence in the sentences, return []. Never invent experiments not supported by the sentences. Hard cap: at most 3.
- Paper-level methods budget: the total number of method names across ALL experiments must be ≤ 3. Allocation: E=0 → no methods; E=1 → that experiment may have 0–3 methods; E=2 → prefer 1 method each (2+1 allowed); E=3 → at most 1 method per experiment. Prefer author-proposed / paper-core methods that appear in the paper; do NOT spend budget on baselines.
- Experiment-scoped rules below apply INSIDE each experiments[] item:
  - experiment_name: prefer paper title if it names the main method; method-level name, not dataset alone.
  - experiment_type: exactly ONE of {benchmark, comparison, ablation, simulation, survey, human_study, field_study, lab_experiment, clinical_trial, case_study, empirical_study, data_analysis, other} for THIS experiment (do not copy one label across distinct studies). Priority: named ablation/component-removal → ablation; public datasets/leaderboards → benchmark; method A vs B without a standard-benchmark framing → comparison; user/human study → human_study; literature review → survey; else the closest remaining label or other; "" if unknown.
  - key_results: 0-5 items; one sentence each; include numbers only if in the sentences provided; do not fabricate.
  - methods: 0–N objects, each {"name": "", "description": "", "aliases": []}. name: short English phrase (≤5 words AND ≤40 characters); ONLY the paper's CORE technical contribution (author-coined or the main proposed method). Prefer author-coined names that appear verbatim in the sentences provided (e.g. "DeePSiM", "ToolMaker"). Do NOT list baselines, compared methods, training recipes, or generic alignment/optimization algorithms as methods (anti-examples as standalone methods: plain "DPO", "Direct Preference Optimization", "SFT", "LoRA", "Adam") unless that algorithm under an author-coined name IS the paper's core contribution. General paradigms ONLY if the exact phrase appears in the sentences provided AND it is the paper's core method. Do NOT invent common paradigms (anti-examples: "contrastive learning", "Autoregressive Blank Infilling") unless they appear verbatim. Do NOT extract consumer chat products (anti-example: "ChatGPT") or bare software/framework product names as methods. NOT datasets, NOT metrics, NOT ablation/evaluation protocol sentences, NOT descriptive sentences. If a name is written as "Full Name (ABBR)", put ABBR in aliases (not as a separate method) and keep a short core name. description: 2-4 English sentences defining the method AS AN ENTITY ("X is a ... that ...") — what the method IS, its core mechanism, the problem it solves, and why it matters; MUST be in English; FORBIDDEN Chinese characters (rewrite any Chinese content in English); SELF-CHECK before emitting: if the field contains any Chinese character, REWRITE it as an English entity definition; NOT what this paper does with it (anti-example: "AlphaFold uses contrastive learning to improve accuracy..."); NOT model names, software, or datasets alone; within the same paper, two methods MUST NOT share identical or near-identical descriptions; "" if unknown. aliases: only widely-recognized academic abbreviations or alternative names used in the paper (e.g. ["DPO"]); [] if none; do NOT fabricate synonyms. [] if no methods known.
  - research_goal: 1-2 sentences; "" if unknown.
  - experiment_subject: 0-3 short English phrases naming the TASK or problem domain studied (e.g. "point cloud completion", "face anti-spoofing", "semi-supervised semantic segmentation"); prefer task phrases that appear in the paper, not generic labels like "deep learning"; not model/baseline names, not dataset names; [] if unknown.
  - metrics: 0-20 metric names stated in the sentences provided; names only, not numeric results; not dataset names; [] if unknown.
  - datasets: 0 to N datasets actually used, built, or evaluated in THIS experiment (not merely cited). For each dataset:
    - name: proper dataset/benchmark name only (required); NOT model names (e.g. GPT-3.5), NOT "Table 2", NOT citations ("Liu et al."), NOT methods/concepts; drop if unsure.
    - aliases: other names/abbreviations used in the paper; [] if none.
    - dataset_type: one of {tabular, image, video, text, audio, graph, point_cloud, 3d_mesh, time_series, multimodal, code, other}; "" if unknown.
    - description: 2-4 English sentences defining the dataset AS AN ENTITY ("X is a dataset that ...") — what data it contains, its scale, how it is structured, and what research task it serves; MUST be entity-specific and grounded in the sentences (prefer size/domain/split/annotation details when present); MUST be in English; FORBIDDEN Chinese characters (rewrite any Chinese content in English); SELF-CHECK before emitting: if the field contains any Chinese character, REWRITE it as an English entity definition; write the dataset itself, NOT the paper's score on it (anti-example: "A test set of 100 entities for comprehensive evaluation."); within the SAME experiment/paper, each dataset description MUST be distinct — FORBIDDEN copying one generic description across different dataset names (anti-example: BigCodeBench and CodeSearchNet both described as "A benchmark for code generation and summarization..."); "" if unknown.
    - sample_size: integer count of instances/samples/subjects in the dataset resource, or null if unknown; NOT the experiment's evaluated subset.
    - is_public: true if publicly released, false if private/restricted, null if unknown.
    - is_self_collected: true if the authors created it, false if it is a third-party benchmark, null if unknown.
    - urls, github_urls, doi_list, cstr_list: fill ONLY with identifiers that appear verbatim in the sentences provided; [] if none; do not fabricate URLs or DOIs.
  - Return [] for datasets if this experiment uses no dataset.
- No markdown fences, no explanation."""


def _v3_json_terminated(sentences: list[str], paper_title: str) -> str:
    """V3: sentences (bullets, no index) BEFORE JSON; prompt ENDS with '{'.

    Defeats the numbered-continuation trap (no trailing numbered block) and forces
    the first generated token to be '{'. /no_think kept for LLM-family models
    (harmless for Llama). Schema + rules identical to V0.
    """
    bulleted = "\n".join(f"- {s}" for s in sentences)
    title_line = paper_title or "(unknown)"
    return f"""/no_think
Extract experiment, research, and dataset information from a scientific paper.

Paper title:
{title_line}

Sentences:
{bulleted}

{_RULES}

Return ONLY valid JSON:
{_SCHEMA}

Return ONLY valid JSON starting with:
{{"""


def _structured(sentences: list[str], paper_title: str) -> str:
    """Structured (nobert) variant: block markers + bare sentence lines.

    ``sentences`` here is the nobert-structured ``llm_input``: a flat list whose
    elements are either a block-marker sentinel line (``=== EXPERIMENT ===`` /
    ``=== ABSINTRO ===`` / ``=== DATASET_FALLBACK ===``) or a washed bare
    sentence. Every element is emitted verbatim as its own line under the
    ``Sentences:`` header — markers as unnumbered section headers, sentences as
    bare lines (no ``N.`` index, no ``-`` bullet). Markers are never numbered
    and never count toward any sentence cap.

    Schema + rules + headers are byte-identical to V0 (shared
    ``_render_wf4_prompt_body``); the ONLY difference from V0 is the Sentences
    block layout (numbered list -> marker + bare lines). V0 order is preserved
    (schema/rules first, Sentences last) so the rules' "in the sentences below"
    wording stays accurate.
    """
    block = "\n".join(s for s in sentences if s)
    return _render_wf4_prompt_body(block, paper_title)


def build_wf4_prompt_for_adapter(
    sentences: list[str], paper_title: str, adapter: str | None
) -> str:
    """Dispatch to the per-model prompt variant.

    Args:
        sentences: BERT-filtered llm_input sentences (for ``"structured"``,
            the nobert marker+sentence line list).
        paper_title: Paper title.
        adapter: ``None``/``"v0"`` -> current production prompt (backward
            equivalent); ``"v3"`` -> JSON-terminated variant; ``"structured"``
            -> nobert block-marker + bare-line variant (schema/rules byte-
            identical to V0).

    Returns:
        The assembled prompt string.
    """
    if adapter in (None, "v0", ""):
        return build_wf4_prompt(sentences, paper_title)
    if adapter == "v3":
        return _v3_json_terminated(sentences, paper_title)
    if adapter == "structured":
        return _structured(sentences, paper_title)
    raise ValueError(f"unknown wf4 prompt adapter: {adapter!r}")
