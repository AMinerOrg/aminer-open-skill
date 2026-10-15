"""Dataset-section fallback — shared preprocess capability.

Problem
-------
``union_experiment_sections`` / ``wf4_union_experiment_sections`` select sections
by **title-keyword match** (experiment / evaluation / result / setup / dataset /
data / ...). Sections whose titles do NOT contain any keyword are excluded
entirely from the candidate pool — and since section-union is a **hard
pre-filter** (merged_text -> split -> BERT -> LLM), anything in those sections
is invisible to BERT and the LLM.

On the AI2000 corpus this produces a recall gap: papers that describe their
datasets under non-standard section titles (security/method papers using
"Threat Model", "White-Box Access", "Tasks and Models", ...) come back with
``datasets: []`` even though the paper names real datasets. dev500 measured
~22.8% zero-datasets; dev10 handoff (standard structure) had none.

Fix
---
This module adds a **third** text block to the union: when the primary union
captured no dataset-bearing section AND the primary body itself lacks dataset
signal, scan the *non-primary, non-skip* sections at **paragraph** level and
append the top-K highest-signal paragraphs (dataset names / "we use" / benchmark
/ corpus / training-set phrasing) so BERT and the LLM get a chance to see them.

Design rules (see ``pipeline/docs/STRATEGY_SECTION_UNION_DATASET_FALLBACK.md``):

- **Incremental, not replacement** — primary experiment union + absintro union
  are untouched; fallback is appended as a third marker block.
- **Conditional** — triggers only when primary clearly lacks dataset coverage.
- **Body-level recall** — paragraph scoring, NOT a blind keyword-list expansion
  of section titles.
- **Budgeted** — MAX_PARAGRAPHS / MAX_CHARS cap so the BERT/LLM 40-sentence
  budget is not crowded out.
- **Observable** — every call returns trigger reason / source sections /
  paragraph count / char count for monitor provenance.

The fallback text flows through the normal ``merge_union_text`` -> split ->
BERT top-40 path; it competes for the sentence budget (BERT is expected to keep
experiment-relevant dataset-usage sentences). It does NOT bypass BERT.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Sequence

from preprocess.section_union_common import split_sections

# Default section-title keywords to EXCLUDE from the fallback scan. Composed to
# match the union strategies' skip sets (intro / related work / refs / ack /
# abstract / appendix / conclusion / supplementary). Defined here (not imported
# from pipeline.production.adapters.wf4_union) so the preprocess layer does not
# depend on the production layer.
DEFAULT_SKIP_SECTION_KEYWORDS: tuple[str, ...] = (
    "introduction",
    "related work",
    "conclusion",
    "acknowledg",
    "reference",
    "bibliography",
    "abstract",
    "appendix",
    "supplementary",
)

_DEFAULT_SKIP_KEYWORDS = DEFAULT_SKIP_SECTION_KEYWORDS  # backwards-compat alias

# --------------------------------------------------------------------------- #
# Signal patterns                                                             #
# --------------------------------------------------------------------------- #

# Strong signals — each match contributes +2 to a paragraph's score.
# Case-insensitive. These indicate a paragraph is describing dataset *usage*
# (not merely citing a dataset name in passing, e.g. in Related Work).
_STRONG_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bdatasets?\b", re.IGNORECASE),
    re.compile(r"\bbenchmark\b", re.IGNORECASE),
    re.compile(r"\bcorpus\b", re.IGNORECASE),
    re.compile(r"\bevaluated on\b", re.IGNORECASE),
    re.compile(r"\bwe (use|used|employ|utilize|adopt|train on|evaluate on)\b", re.IGNORECASE),
    re.compile(r"\btest (set|data|corpus)\b", re.IGNORECASE),
    # Lightweight dataset-name heuristic: CamelCase token (>=1 internal uppercase)
    # containing a digit — VGGFace2, ImageNet1k, CIFAR10, ResNet50, MobileNetV2.
    # The internal-uppercase requirement rejects author names with superscript
    # affiliation digits ("Evans2", "Tian1", "Suri2") which otherwise flood the
    # gate. Single-word+digit tokens without CamelCase are caught by context
    # words ("dataset"/"benchmark") instead.
    re.compile(r"\b[A-Z][a-zA-Z0-9]*[A-Z][a-zA-Z0-9]*\d[a-zA-Z0-9]*\b"),
)

# Weak signals — +1 each, capped at +1 per paragraph so weak-only paragraphs
# stay below the threshold. NOTE: "training set/data" is deliberately weak — it
# appears in generic method/threat-model prose and would otherwise flood the
# fallback with non-dataset paragraphs (paper-2 "Threat Model" regression).
_WEAK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bmodels?\b", re.IGNORECASE),
    re.compile(r"\btasks?\b", re.IGNORECASE),
    re.compile(r"\btraining (set|data)\b", re.IGNORECASE),
)

# Table-row signal: a paragraph that looks like a markdown table row mentioning
# dataset/benchmark — tables often enumerate datasets used.
_TABLE_DATASET_RE = re.compile(r"\|.*\b(datasets?|benchmark|corpus)\b.*\|", re.IGNORECASE)

# Eligibility gate: a paragraph is scanned/scored ONLY if it contains a dataset
# word OR a dataset-name-like token. This excludes generic "training set"
# method prose that lacks any dataset reference (paper-2 Threat Model noise).
_GATE_DATASET_WORD_RE = re.compile(r"\b(datasets?|benchmark|corpus)\b", re.IGNORECASE)
_GATE_DATASET_NAME_RE = re.compile(r"\b[A-Z][a-zA-Z0-9]*[A-Z][a-zA-Z0-9]*\d[a-zA-Z0-9]*\b")

# Title match for "this section is a dataset section" (trigger guard).
_DATASET_TITLE_RE = re.compile(r"dataset|data", re.IGNORECASE)


@dataclass(frozen=True)
class DatasetFallbackConfig:
    """Tunable knobs for ``apply_dataset_section_fallback``."""

    # Paragraph is kept if its dataset_signal_score >= this threshold.
    paragraph_threshold: int = 3
    # Max paragraphs appended (top-K by score).
    max_paragraphs: int = 4
    # Max chars per appended paragraph (long setup paragraphs are truncated at a
    # sentence boundary so one paragraph cannot eat the whole budget). 1500
    # keeps multi-dataset setup paragraphs intact (e.g. a paragraph naming both
    # VGGFace2 and ImageNet, ~1200 chars).
    max_paragraph_chars: int = 1500
    # Max total chars appended (budget guard for the BERT/LLM 40-sentence cap).
    max_chars: int = 4000
    # Trigger guard: if the primary union body already has >= this many strong
    # dataset signals, fallback is skipped (primary already covers datasets).
    # 0 disables the guard (trigger purely on title + scan). Default 2 so a
    # single passing "dataset" mention in primary does NOT suppress fallback
    # (paper-2-style: primary mentions "dataset" once but misses VGGFace2).
    min_primary_body_signal: int = 2


@dataclass(frozen=True)
class DatasetFallbackResult:
    """Outcome of ``apply_dataset_section_fallback``."""

    text: str  # appended-block body ("" if not triggered)
    triggered: bool
    trigger_reason: str  # "no_dataset_title_in_primary" | "skipped:..." | "disabled"
    source_section_titles: list[str] = field(default_factory=list)
    source_paragraph_count: int = 0
    char_count: int = 0
    skipped_reason: str | None = None  # set when triggered is False

    @classmethod
    def empty(cls, reason: str = "disabled") -> "DatasetFallbackResult":
        return cls(
            text="",
            triggered=False,
            trigger_reason=reason,
            source_section_titles=[],
            source_paragraph_count=0,
            char_count=0,
            skipped_reason=reason,
        )


# --------------------------------------------------------------------------- #
# Scoring                                                                      #
# --------------------------------------------------------------------------- #


def _paragraph_eligible(text: str) -> bool:
    """Gate: paragraph must reference a dataset word or a dataset-name token."""
    return bool(_GATE_DATASET_WORD_RE.search(text) or _GATE_DATASET_NAME_RE.search(text))


def _paragraph_score(text: str) -> tuple[int, int]:
    """Return (score, strong_hit_count) for one paragraph.

    Returns (0, 0) if the paragraph fails the eligibility gate (no dataset word
    and no dataset-name token) — this excludes generic method/threat-model
    prose that mentions "training set" without naming any dataset.
    """
    if not _paragraph_eligible(text):
        return 0, 0
    strong = 0
    for pat in _STRONG_PATTERNS:
        strong += len(pat.findall(text))
    if _TABLE_DATASET_RE.search(text):
        strong += 1  # table-row dataset mention counts as strong
    weak = 0
    for pat in _WEAK_PATTERNS:
        if pat.search(text):
            weak += 1
            break  # cap weak contribution at +1
    return strong * 2 + weak, strong


def _truncate_paragraph(text: str, max_chars: int) -> str:
    """Truncate to <= max_chars at a sentence boundary (". " near the limit)."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    # back up to the last sentence end for a clean break
    last_stop = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if last_stop > max_chars // 2:
        return cut[: last_stop + 1]
    return cut.rstrip() + "…"


def _count_primary_body_signal(primary_union_text: str) -> int:
    """Count strong dataset signals across the whole primary union body."""
    if not primary_union_text:
        return 0
    total = 0
    for pat in _STRONG_PATTERNS:
        total += len(pat.findall(primary_union_text))
    if _TABLE_DATASET_RE.search(primary_union_text):
        total += 1
    return total


def _split_paragraphs(body: str) -> list[str]:
    """Split a section body into non-empty paragraphs (blank-line separated)."""
    parts = re.split(r"\n\s*\n", body)
    return [p.strip() for p in parts if p.strip()]


def _title_in_keywords(title: str, keywords: Sequence[str]) -> bool:
    lowered = title.lower().strip()
    return any(kw in lowered for kw in keywords)


# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #


def apply_dataset_section_fallback(
    md_text: str,
    *,
    primary_selected_titles: list[str],
    primary_union_text: str,
    primary_fallback_to_full_text: bool,
    section_matcher: Callable[[str], bool] | None = None,
    skip_keywords: Sequence[str] = _DEFAULT_SKIP_KEYWORDS,
    config: DatasetFallbackConfig | None = None,
) -> DatasetFallbackResult:
    """Append a dataset-bearing paragraph block from non-primary sections.

    Args:
        md_text: full preprocessed markdown (post ``run_preprocess_steps``).
        primary_selected_titles: titles the primary union already captured.
        primary_union_text: the primary union body (for body-signal guard).
        primary_fallback_to_full_text: True if primary fell back to full text
            (in which case fallback is redundant -> skipped).
        section_matcher: the primary union's title matcher (reserved for
            future use / provenance; not used for filtering).
        skip_keywords: section-title keywords to exclude from the scan
            (intro / related work / references / acknowledg / abstract /
            appendix / conclusion).
        config: tunable thresholds.

    Returns:
        ``DatasetFallbackResult``. ``triggered`` is True only when the trigger
        conditions hold AND the scan found >= 1 above-threshold paragraph.
    """
    cfg = config or DatasetFallbackConfig()

    # --- trigger guard 1: primary already used full text -> redundant --------
    if primary_fallback_to_full_text:
        return DatasetFallbackResult(
            text="",
            triggered=False,
            trigger_reason="skipped:primary_full_text_fallback",
            skipped_reason="primary_full_text_fallback",
        )

    # --- trigger guard 2: primary captured a dataset/data-titled section -----
    if any(_DATASET_TITLE_RE.search(t) for t in primary_selected_titles):
        return DatasetFallbackResult(
            text="",
            triggered=False,
            trigger_reason="skipped:primary_has_dataset_title",
            skipped_reason="primary_has_dataset_title",
        )

    # --- trigger guard 3 (optional): primary body already has enough signal --
    if cfg.min_primary_body_signal > 0:
        body_signal = _count_primary_body_signal(primary_union_text)
        if body_signal >= cfg.min_primary_body_signal:
            return DatasetFallbackResult(
                text="",
                triggered=False,
                trigger_reason="skipped:primary_has_body_signal",
                skipped_reason=f"primary_has_body_signal({body_signal})",
            )

    # --- scan non-primary, non-skip sections at paragraph level --------------
    primary_titles_lower = {t.lower().strip() for t in primary_selected_titles}
    sections = split_sections(md_text)

    # candidate paragraphs: (score, doc_position, section_title, paragraph_text)
    candidates: list[tuple[int, int, str, str]] = []
    doc_pos = 0
    for title, body in sections:
        if not title:
            continue
        t_lower = title.lower().strip()
        if t_lower in primary_titles_lower:
            continue  # already in primary union
        if _title_in_keywords(title, skip_keywords):
            continue  # intro / related work / references / appendix / ...
        for para in _split_paragraphs(body):
            score, _strong = _paragraph_score(para)
            if score >= cfg.paragraph_threshold:
                candidates.append((score, doc_pos, title, para))
            doc_pos += 1

    if not candidates:
        return DatasetFallbackResult(
            text="",
            triggered=False,
            trigger_reason="skipped:no_dataset_signal_in_scan",
            skipped_reason="no_dataset_signal_in_scan",
        )

    # --- budget: top-K by score, then re-sort by doc position for output -----
    candidates.sort(key=lambda c: (-c[0], c[1]))
    chosen: list[tuple[int, str, str]] = []  # (doc_pos, title, para)
    total_chars = 0
    used_titles: list[str] = []
    seen_para: set[int] = set()
    for score, pos, title, para in candidates:
        if len(chosen) >= cfg.max_paragraphs:
            break
        if pos in seen_para:
            continue
        para = _truncate_paragraph(para, cfg.max_paragraph_chars)
        block = f"## {title} (fallback)\n\n{para}"
        if total_chars + len(block) > cfg.max_chars and chosen:
            break  # budget exhausted
        chosen.append((pos, title, para))
        seen_para.add(pos)
        total_chars += len(block)
        if title not in used_titles:
            used_titles.append(title)

    if not chosen:
        return DatasetFallbackResult(
            text="",
            triggered=False,
            trigger_reason="skipped:budget_exhausted_empty",
            skipped_reason="budget_exhausted_empty",
        )

    chosen.sort(key=lambda c: c[0])  # restore document order
    text = "\n\n".join(f"## {title} (fallback)\n\n{para}" for _pos, title, para in chosen)

    return DatasetFallbackResult(
        text=text,
        triggered=True,
        trigger_reason="no_dataset_title_in_primary",
        source_section_titles=used_titles,
        source_paragraph_count=len(chosen),
        char_count=len(text),
        skipped_reason=None,
    )
