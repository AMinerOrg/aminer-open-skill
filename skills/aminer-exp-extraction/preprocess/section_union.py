"""Extract and union experiment-related markdown sections."""

from __future__ import annotations

import re
from dataclasses import dataclass

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

SKIP_SECTION_KEYWORDS = (
    "introduction",
    "related work",
    "conclusion",
    "acknowledg",
    "reference",
    "bibliography",
    "appendix",
    "abstract",
)


@dataclass(frozen=True)
class SectionUnionResult:
    text: str
    selected_sections: list[str]
    original_char_count: int
    union_char_count: int
    fallback_to_full_text: bool


def _section_matches(title: str) -> bool:
    lowered = title.lower().strip()
    if any(keyword in lowered for keyword in SKIP_SECTION_KEYWORDS):
        return False
    return any(keyword in lowered for keyword in EXPERIMENT_SECTION_KEYWORDS)


def _split_sections(md_text: str) -> list[tuple[str, str]]:
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


def union_experiment_sections(md_text: str) -> SectionUnionResult:
    """Keep experiment-related sections and union them for downstream filtering."""
    original_char_count = len(md_text)
    sections = _split_sections(md_text)

    selected: list[str] = []
    selected_titles: list[str] = []

    for title, body in sections:
        if not title:
            continue
        if _section_matches(title) and body:
            selected_titles.append(title)
            selected.append(f"## {title}\n\n{body}")

    if not selected:
        return SectionUnionResult(
            text=md_text,
            selected_sections=[],
            original_char_count=original_char_count,
            union_char_count=len(md_text),
            fallback_to_full_text=True,
        )

    union_text = "\n\n".join(selected)
    return SectionUnionResult(
        text=union_text,
        selected_sections=selected_titles,
        original_char_count=original_char_count,
        union_char_count=len(union_text),
        fallback_to_full_text=False,
    )
