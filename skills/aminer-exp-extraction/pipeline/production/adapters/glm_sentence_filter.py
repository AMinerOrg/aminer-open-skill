"""GLM (BigModel) sentence filter — LLM replacement for the SciBERT /filter/batch.

Scores each preprocessed sentence for experiment relevance (0.0-1.0) with a
single glm-5.3 chat call and keeps those >= threshold, mirroring the SciBERT
stage's semantics: original order preserved, capped afterwards. Uses the same
BigModel endpoint / auth / model as the extraction stage, so the whole skill
depends on exactly one model service (open.bigmodel.cn).
"""

from __future__ import annotations

import time
from typing import Any

from pipeline.benchmark.stages.openai_chat_llm_client import OpenAIChatLLMClient
from pipeline.json_repair import parse_json_object

# Frozen semantics, identical to the SciBERT path (WF1_BERT_THRESHOLD).
FILTER_THRESHOLD = 0.6

FILTER_SYSTEM_PROMPT = (
    "You are the sentence-selection stage of a paper experiment-extraction "
    "pipeline. Given a paper title and a numbered list of sentences, score "
    "each sentence for experiment relevance on a 0.0-1.0 scale. Sentences "
    "about the research problem, methods, datasets, evaluation metrics, "
    "experimental setup, quantitative results, conclusions, or limitations "
    "score high. Background, related work, author/affiliation info, "
    "acknowledgements, and references score low. "
    "Work FAST: one short judgement per sentence, no deep analysis, "
    "minimal reasoning. Output JSON only."
)


def build_filter_prompt(paper_title: str, sentences: list[str]) -> str:
    """Build the numbered-sentence scoring prompt for the GLM filter."""
    lines = [f"{i}. {s}" for i, s in enumerate(sentences)]
    return (
        f"Paper title: {paper_title}\n\n"
        "Numbered sentences from this paper (indices start at 0). Score each "
        "one's experiment relevance 0.0-1.0.\n"
        "Return ONE compact JSON object: "
        '{"kept": [[<index>, <score>], ...]} listing ONLY entries with '
        "score >= 0.6, ascending index, no spaces beyond necessities. "
        'If none qualifies: {"kept": []}. No other text, no explanation.\n\n'
        "Sentences:\n" + "\n".join(lines)
    )


def _extract_pairs(raw_kept: Any) -> list[tuple[int, float]]:
    """Normalize GLM's kept entries to (index, score) pairs, leniently."""
    pairs: list[tuple[int, float]] = []
    if not isinstance(raw_kept, list):
        return pairs
    for item in raw_kept:
        if isinstance(item, dict) and "i" in item:
            idx, score = item["i"], item.get("score", 1.0)
        elif isinstance(item, (list, tuple)) and len(item) >= 1:
            idx, score = item[0], item[1] if len(item) > 1 else 1.0
        else:
            continue
        try:
            idx_i, score_f = int(idx), float(score)
        except (TypeError, ValueError):
            continue
        pairs.append((idx_i, score_f))
    return pairs


def filter_sentences_glm(
    sentences: list[str],
    *,
    paper_title: str = "",
    client: OpenAIChatLLMClient | None = None,
    threshold: float = FILTER_THRESHOLD,
    cap: int | None = None,
    num_predict: int = 16384,
) -> dict[str, Any]:
    """Filter sentences through one glm-5.3 chat call (SciBERT replacement).

    Args:
        sentences: Stage-P english_sentences (washed, original order).
        paper_title: Paper title, given to the model as context.
        client: Optional pre-built OpenAIChatLLMClient (else a default one).
        threshold: Keep threshold, frozen at 0.6 (same as SciBERT path).
        cap: Optional max kept count (applied after threshold, keeps order).
        num_predict: max_tokens for the scoring call. BigModel counts
            reasoning_tokens inside this budget and glm-5.3 always thinks
            (thinking.level=low by default), so 16384 leaves ample room for
            reasoning + the scored-index JSON for 60+ sentences.

    Returns:
        {kept: [str], kept_count, total, threshold, scores: {index: score},
         elapsed_sec}. ``kept`` is empty only when GLM explicitly returns an
         empty kept list (legitimate "no experiment sentences" answer).

    Raises:
        RuntimeError: transport/HTTP failure propagates from the client; an
            unparseable scoring response is a hard error (never a silent
            empty result — same contract as the SciBERT gateway).
    """
    start = time.perf_counter()
    if not sentences:
        return {
            "kept": [], "kept_count": 0, "total": 0,
            "threshold": threshold, "scores": {}, "elapsed_sec": 0.0,
        }

    llm = client or OpenAIChatLLMClient()
    result = llm.generate(
        build_filter_prompt(paper_title, sentences),
        temperature=0.05,
        num_predict=num_predict,
        system=FILTER_SYSTEM_PROMPT,
    )
    raw = result["raw_output"]
    parsed, parse_error = parse_json_object(raw)
    if parsed is None:
        raise RuntimeError(
            f"GLM sentence filter: unparseable scoring response "
            f"({parse_error}); head={raw[:200]!r}"
        )

    # Lenient normalization: dedupe by index (keep max score), drop
    # out-of-range indices, apply threshold, restore original order.
    best: dict[int, float] = {}
    for idx, score in _extract_pairs(parsed.get("kept")):
        if 0 <= idx < len(sentences):
            best[idx] = max(score, best.get(idx, -1.0))
    scored = {i: s for i, s in best.items() if s >= threshold}
    kept_indices = sorted(scored)
    if cap is not None:
        kept_indices = kept_indices[:cap]
    kept = [sentences[i] for i in kept_indices]

    return {
        "kept": kept,
        "kept_count": len(kept),
        "total": len(sentences),
        "threshold": threshold,
        "scores": scored,
        "elapsed_sec": round(time.perf_counter() - start, 4),
    }
