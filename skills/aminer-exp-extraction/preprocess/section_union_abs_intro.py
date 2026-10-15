"""Extract and union Abstract + Introduction (section-union-AbsIntro).

Layer 1: match abs/intro title variants (incl. embedded/preamble abstract) and union sections.
Layer 2: strip experiment/ref/tail sections, then density-based reference truncation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from reference_detector import detect_references, level3_density
from preprocess.section_union_common import (
    is_experiment_section,
    is_layer2_drop_section,
    split_sections,
)

STRATEGY_NAME = "section-union-AbsIntro"

INTRO_TITLE_RE = re.compile(
    r"^(?:(?:[IVXLCDM]+|\d+)\.?\s*)?(?:introduction|intro)\b",
    re.IGNORECASE,
)

PREAMBLE_ABSTRACT_START_RE = re.compile(
    r"^abstract\s*[\u2014\u2013\-:—]?\s*",
    re.IGNORECASE,
)

PREAMBLE_BLOCK_BREAK_RE = re.compile(
    r"^(?:index terms|keywords|key words|ccs concepts|acm reference format)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SectionUnionAbsIntroResult:
    text: str
    selected_sections: list[str]
    original_char_count: int
    union_char_count: int
    fallback_layer: str
    fallback_to_full_text: bool
    removed_sections: list[str] = field(default_factory=list)
    reference_cut: dict | None = None
    strategy: str = STRATEGY_NAME


def normalize_section_title(title: str) -> str:
    cleaned = re.sub(r"[^\w\s]", " ", title.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _section_matches_abstract(title: str) -> bool:
    lowered = normalize_section_title(title)
    if not lowered:
        return False
    return lowered == "abstract" or lowered.startswith("abstract ")


def _section_matches_intro(title: str) -> bool:
    lowered = normalize_section_title(title)
    if not lowered:
        return False
    if INTRO_TITLE_RE.match(lowered):
        return True
    return lowered.startswith("introduction ") or lowered.startswith("intro ")


def _looks_like_real_section_title(title: str) -> bool:
    short = title.strip()[:80]
    lowered = normalize_section_title(short)
    if _section_matches_intro(short) or _section_matches_abstract(short):
        return True
    if len(title) <= 80 and is_layer2_drop_section(title):
        return True
    if re.match(r"^(?:[IVXLCDM]+|\d+)\.?\s+[A-Z][A-Za-z\s]{2,60}$", short):
        return True
    return False


def _is_misparsed_intro_header(title: str) -> bool:
    return len(title) >= 150 and not _looks_like_real_section_title(title)


def _should_stop_intro_scan(title: str) -> bool:
    if len(title) > 100:
        return False
    return is_experiment_section(title)


def _select_intro_block(sections: list[tuple[str, str]], preamble: str) -> tuple[str, str] | None:
    best: tuple[int, str, str] | None = None

    def consider(priority: int, label: str, body: str) -> None:
        nonlocal best
        if not body.strip():
            return
        if best is None or priority > best[0]:
            best = (priority, label, body)

    for index, (title, body) in enumerate(sections):
        if title and _section_matches_intro(title):
            consider(3, title, body)
        elif index > 0 and title and _is_misparsed_intro_header(title):
            consider(2, "Introduction (mis-parsed header)", f"{title}\n\n{body}")
        elif title and _should_stop_intro_scan(title):
            break

    preamble_intro = _preamble_after_abstract_block(preamble)
    if preamble_intro:
        consider(2, "Introduction (preamble)", preamble_intro)

    inferred = _first_inferred_intro_body(sections, skip_first_empty=bool(preamble.strip()))
    if inferred:
        consider(1, inferred[0], inferred[1])

    if best is None:
        return None
    return best[1], best[2]


def _extract_preamble_abstract(text: str) -> str | None:
    if not text.strip():
        return None

    lines = text.splitlines()
    collecting = False
    chunks: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if collecting and chunks:
                break
            continue

        if not collecting and PREAMBLE_ABSTRACT_START_RE.match(stripped):
            collecting = True
            remainder = PREAMBLE_ABSTRACT_START_RE.sub("", stripped).strip()
            if remainder:
                chunks.append(remainder)
            continue

        if collecting:
            if PREAMBLE_BLOCK_BREAK_RE.match(stripped):
                break
            if stripped.startswith("#"):
                break
            chunks.append(stripped)

    result = re.sub(r"\s+", " ", " ".join(chunks)).strip()
    return result or None


def _extract_abstract_from_sections(sections: list[tuple[str, str]]) -> tuple[str, str] | None:
    for title, body in sections[:4]:
        abs_text = _extract_preamble_abstract(body)
        if abs_text:
            label = "Abstract (embedded)" if not title else f"Abstract ({title[:40]})"
            return abs_text, label
    return None


def _preamble_after_abstract_block(preamble: str) -> str | None:
    if not preamble.strip():
        return None

    lines = preamble.splitlines()
    start_index: int | None = None
    for index, line in enumerate(lines):
        if PREAMBLE_ABSTRACT_START_RE.match(line.strip()):
            start_index = index
            break
    if start_index is None:
        return None

    body_lines: list[str] = []
    passed_break = False
    for line in lines[start_index + 1 :]:
        stripped = line.strip()
        if not stripped:
            if passed_break and body_lines:
                break
            continue
        if PREAMBLE_BLOCK_BREAK_RE.match(stripped):
            passed_break = True
            body_lines.clear()
            continue
        if stripped.startswith("#"):
            break
        body_lines.append(stripped)

    text = re.sub(r"\s+", " ", " ".join(body_lines)).strip()
    return text if len(text) >= 120 else None


def _first_inferred_intro_body(
    sections: list[tuple[str, str]],
    *,
    skip_first_empty: bool,
) -> tuple[str, str] | None:
    empty_index = 0
    for title, body in sections:
        if title and is_layer2_drop_section(title):
            break
        if title:
            continue
        empty_index += 1
        if skip_first_empty and empty_index == 1:
            continue
        cleaned = re.sub(r"\s+", " ", body).strip()
        if len(cleaned) >= 120:
            return ("Introduction (inferred)", cleaned)
    return None


def _apply_reference_cut(text: str, *, prefer_density: bool) -> tuple[str, dict | None]:
    detection = level3_density(text) if prefer_density else detect_references(text)
    if prefer_density and not detection.found:
        detection = detect_references(text)

    if not detection.found or detection.boundary is None:
        return text, None

    cut_text = text[: detection.boundary].rstrip()
    return cut_text, {
        "method": detection.method,
        "confidence": detection.confidence,
        "reason": detection.reason,
        "boundary": detection.boundary,
        "chars_removed": len(text) - len(cut_text),
    }


def _layer1_abs_intro_union(sections: list[tuple[str, str]], preamble: str) -> tuple[list[str], list[str]]:
    selected: list[str] = []
    selected_titles: list[str] = []

    abstract_text = _extract_preamble_abstract(preamble)
    abstract_label = "Abstract (preamble)"
    if not abstract_text:
        embedded = _extract_abstract_from_sections(sections)
        if embedded:
            abstract_text, abstract_label = embedded

    if abstract_text:
        selected_titles.append(abstract_label)
        selected.append(f"## Abstract\n\n{abstract_text}")

    for title, body in sections:
        if not title or not body:
            continue
        if _section_matches_abstract(title) and not abstract_text:
            selected_titles.append(title)
            selected.append(f"## {title}\n\n{body}")

    intro = _select_intro_block(sections, preamble)
    if intro:
        intro_label, intro_body = intro
        selected_titles.append(intro_label)
        selected.append(f"## Introduction\n\n{intro_body}")

    return selected, selected_titles


def _layer2_strip_experiment_ref(md_text: str) -> tuple[str, list[str], list[str], dict | None]:
    sections = split_sections(md_text)
    kept_blocks: list[str] = []
    kept_titles: list[str] = []
    removed_titles: list[str] = []

    for title, body in sections:
        if title and is_layer2_drop_section(title):
            removed_titles.append(title)
            continue
        if not body.strip():
            continue
        if title:
            kept_titles.append(title)
            kept_blocks.append(f"## {title}\n\n{body}")
        else:
            kept_titles.append("Preamble")
            kept_blocks.append(body)

    text = "\n\n".join(kept_blocks).strip()
    text = re.sub(r"^#{1,3}\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    text, reference_cut = _apply_reference_cut(text, prefer_density=True)
    return text, kept_titles, removed_titles, reference_cut


def union_abs_intro_sections(md_text: str) -> SectionUnionAbsIntroResult:
    """Layer1 abs/intro union; Layer2 experiment/ref strip + density ref cut."""
    original_char_count = len(md_text)
    sections = split_sections(md_text)
    preamble = sections[0][1] if sections and not sections[0][0] else ""

    selected, selected_titles = _layer1_abs_intro_union(sections, preamble)
    if selected:
        union_text = "\n\n".join(selected)
        return SectionUnionAbsIntroResult(
            text=union_text,
            selected_sections=selected_titles,
            original_char_count=original_char_count,
            union_char_count=len(union_text),
            fallback_layer="layer1",
            fallback_to_full_text=False,
        )

    union_text, kept_titles, removed_titles, reference_cut = _layer2_strip_experiment_ref(md_text)
    if not union_text.strip():
        return SectionUnionAbsIntroResult(
            text=md_text,
            selected_sections=[],
            original_char_count=original_char_count,
            union_char_count=len(md_text),
            fallback_layer="layer2_empty",
            fallback_to_full_text=True,
            removed_sections=removed_titles,
            reference_cut=reference_cut,
        )

    return SectionUnionAbsIntroResult(
        text=union_text,
        selected_sections=kept_titles,
        original_char_count=original_char_count,
        union_char_count=len(union_text),
        fallback_layer="layer2",
        fallback_to_full_text=False,
        removed_sections=removed_titles,
        reference_cut=reference_cut,
    )
