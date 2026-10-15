"""Shared section-matching helpers for union strategies."""

from __future__ import annotations

import re

SECTION_HEADER_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.MULTILINE)

EXPERIMENT_SECTION_KEYWORDS = (
    "experiment",
    "implementation",
    "evaluation",
    "result",
    "benchmark",
    "ablation",
    "dataset",
    "setup",
    "training",
    "comparison",
    "performance",
    "metric",
)

REF_SECTION_KEYWORDS = (
    "reference",
    "bibliography",
    "works cited",
    "acknowledg",
)

TAIL_SKIP_KEYWORDS = (
    "conclusion",
    "appendix",
    "supplementary",
)


def split_sections(md_text: str) -> list[tuple[str, str]]:
    """Return (title, body) pairs. Preamble uses empty title."""
    matches = list(SECTION_HEADER_RE.finditer(md_text))
    if not matches:
        return [("", md_text.strip())]

    sections: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        sections.append(("", md_text[: matches[0].start()].strip()))

    for index, match in enumerate(matches):
        title = match.group(2).strip()
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(md_text)
        body = md_text[body_start:body_end].strip()
        sections.append((title, body))

    return sections


def normalize_section_title(title: str) -> str:
    cleaned = re.sub(r"[^\w\s]", " ", title.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def is_experiment_section(title: str) -> bool:
    lowered = normalize_section_title(title)
    if not lowered:
        return False
    return any(keyword in lowered for keyword in EXPERIMENT_SECTION_KEYWORDS)


def is_ref_section(title: str) -> bool:
    lowered = normalize_section_title(title)
    if not lowered:
        return False
    return any(keyword in lowered for keyword in REF_SECTION_KEYWORDS)


def is_tail_skip_section(title: str) -> bool:
    lowered = normalize_section_title(title)
    if not lowered:
        return False
    return any(keyword in lowered for keyword in TAIL_SKIP_KEYWORDS)


def is_layer2_drop_section(title: str) -> bool:
    return is_experiment_section(title) or is_ref_section(title) or is_tail_skip_section(title)
