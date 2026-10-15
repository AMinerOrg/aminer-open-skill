"""Detect reference-section boundaries in Markdown without modifying text."""

from __future__ import annotations

# 本模块独立，无需外部依赖

import re
from dataclasses import dataclass
from pathlib import Path

MIN_DOC_CHARS = 100
HEADER_MARKDOWN_MIN_RATIO = 0.0
HEADER_STANDALONE_MIN_RATIO = 0.40
PREFIX_MIN_RATIO = 0.50
DENSITY_SCAN_START_RATIO = 0.70

DENSITY_WINDOW_LINES = 20
DENSITY_WINDOW_STEP = 5
DENSITY_SCORE_THRESHOLD = 0.70
DENSITY_CONSECUTIVE_WINDOWS = 3

SECTION_TITLE_PATTERN = r"(?:References|Bibliography|Works Cited)"
HEADER_MARKDOWN_RE = re.compile(
    rf"^#{{1,3}}\s*{SECTION_TITLE_PATTERN}\s*$",
    re.IGNORECASE,
)
HEADER_STANDALONE_RE = re.compile(
    rf"^\s*{SECTION_TITLE_PATTERN}\s*$",
    re.IGNORECASE,
)
EMPTY_HASH_RE = re.compile(r"^#\s*$")
PREFIX_RE = re.compile(r"^\s*references[:\s]+", re.IGNORECASE)

YEAR_RE = re.compile(r"(19|20)\d{2}")
ET_AL_RE = re.compile(r"\bet al\b", re.IGNORECASE)
DOI_RE = re.compile(r"doi\.org|doi:", re.IGNORECASE)
VENUE_RE = re.compile(
    r"Proceedings of|NeurIPS|ICCV|CVPR|arXiv|JMLR|AAAI",
    re.IGNORECASE,
)
AUTHOR_RE = re.compile(r"[A-Z][a-z]+,\s+[A-Z]\.?|[A-Z]\.\s+[A-Z][a-z]+")
CITATION_INDEX_RE = re.compile(r"^\[\d+\]|^\d+\.\s+[A-Z]")

FEATURE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("year", YEAR_RE),
    ("et_al", ET_AL_RE),
    ("doi", DOI_RE),
    ("venue", VENUE_RE),
    ("author", AUTHOR_RE),
)


@dataclass(frozen=True)
class ReferenceDetectionResult:
    found: bool
    boundary: int | None
    confidence: float
    method: str
    reason: str


@dataclass
class ReferenceDetectionStats:
    header_match_count: int = 0
    prefix_match_count: int = 0
    density_match_count: int = 0
    no_cut_count: int = 0
    anomaly_rejected_count: int = 0


def iter_lines_with_offsets(md_text: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    offset = 0
    parts = md_text.split("\n")
    for index, line in enumerate(parts):
        lines.append((offset, line))
        offset += len(line)
        if index < len(parts) - 1:
            offset += 1
    return lines


def line_at_offset(md_text: str, offset: int) -> str | None:
    if offset < 0 or offset >= len(md_text):
        return None
    line_start = md_text.rfind("\n", 0, offset) + 1
    line_end = md_text.find("\n", offset)
    if line_end == -1:
        line_end = len(md_text)
    return md_text[line_start:line_end].strip()


def _no_cut(reason: str) -> ReferenceDetectionResult:
    return ReferenceDetectionResult(
        found=False,
        boundary=None,
        confidence=0.0,
        method="none",
        reason=reason,
    )


def _found_result(
    *,
    boundary: int,
    confidence: float,
    method: str,
    reason: str,
) -> ReferenceDetectionResult:
    return ReferenceDetectionResult(
        found=True,
        boundary=boundary,
        confidence=confidence,
        method=method,
        reason=reason,
    )


def _passes_header_position(boundary: int, text_len: int, *, markdown_heading: bool) -> bool:
    if text_len <= 0:
        return False
    min_ratio = HEADER_MARKDOWN_MIN_RATIO if markdown_heading else HEADER_STANDALONE_MIN_RATIO
    return boundary >= int(text_len * min_ratio)


def _passes_prefix_position(boundary: int, text_len: int) -> bool:
    if text_len <= 0:
        return False
    return boundary >= int(text_len * PREFIX_MIN_RATIO)


def _count_feature_groups(text: str) -> int:
    groups = {
        name
        for name, pattern in FEATURE_PATTERNS
        if pattern.search(text)
    }
    return len(groups)


def level1_header(md_text: str) -> ReferenceDetectionResult:
    text_len = len(md_text)
    lines = iter_lines_with_offsets(md_text)
    candidates: list[tuple[int, str]] = []

    for offset, line in lines:
        if HEADER_MARKDOWN_RE.match(line):
            reason = f"matched heading: {line.strip()}"
            candidates.append((offset, reason, True))
        elif HEADER_STANDALONE_RE.match(line):
            reason = f"matched standalone heading: {line.strip()}"
            candidates.append((offset, reason, False))

    for index, (offset, line) in enumerate(lines):
        if not EMPTY_HASH_RE.match(line):
            continue
        for next_offset, next_line in lines[index + 1 :]:
            if not next_line.strip():
                continue
            if HEADER_STANDALONE_RE.match(next_line):
                reason = f"matched # + heading: {next_line.strip()}"
                candidates.append((next_offset, reason, False))
            break

    valid = [
        (offset, reason)
        for offset, reason, markdown_heading in candidates
        if _passes_header_position(offset, text_len, markdown_heading=markdown_heading)
    ]
    if not valid:
        return _no_cut("header match not found or failed position constraint")

    boundary, reason = min(valid, key=lambda item: item[0])
    return _found_result(
        boundary=boundary,
        confidence=0.99,
        method="header",
        reason=reason,
    )


def level2_prefix(md_text: str) -> ReferenceDetectionResult:
    text_len = len(md_text)
    lines = iter_lines_with_offsets(md_text)
    candidates: list[tuple[int, str, int]] = []

    for index, (offset, line) in enumerate(lines):
        if not PREFIX_RE.match(line):
            continue
        if not _passes_prefix_position(offset, text_len):
            continue
        window_lines = [line]
        for _, next_line in lines[index + 1 : index + 16]:
            window_lines.append(next_line)
        window_text = "\n".join(window_lines)
        hit_count = _count_feature_groups(window_text)
        if hit_count < 2:
            continue
        reason = f"matched references prefix with {hit_count} feature groups"
        candidates.append((offset, reason, hit_count))

    if not candidates:
        return _no_cut("prefix match not found or failed feature validation")

    boundary, reason, _ = min(candidates, key=lambda item: item[0])
    return _found_result(
        boundary=boundary,
        confidence=0.90,
        method="prefix",
        reason=reason,
    )


def _density_window_score(window_lines: list[str]) -> float:
    if not window_lines:
        return 0.0
    window_size = len(window_lines)
    text = "\n".join(window_lines)
    year_density = len(YEAR_RE.findall(text)) / window_size
    author_density = len(AUTHOR_RE.findall(text)) / window_size
    keyword_density = len(ET_AL_RE.findall(text) + DOI_RE.findall(text) + VENUE_RE.findall(text)) / window_size
    index_density = sum(
        1 for line in window_lines if CITATION_INDEX_RE.search(line.strip())
    ) / window_size
    return (
        0.35 * year_density
        + 0.30 * author_density
        + 0.20 * keyword_density
        + 0.15 * index_density
    )


def level3_density(md_text: str) -> ReferenceDetectionResult:
    text_len = len(md_text)
    scan_start = int(text_len * DENSITY_SCAN_START_RATIO)
    all_lines = iter_lines_with_offsets(md_text)
    lines = [(offset, line) for offset, line in all_lines if offset >= scan_start]
    if len(lines) < DENSITY_WINDOW_LINES:
        return _no_cut("insufficient lines in density scan range")

    streak = 0
    streak_scores: list[float] = []
    max_windows = max(0, (len(lines) - DENSITY_WINDOW_LINES) // DENSITY_WINDOW_STEP + 1)
    required_streak = min(DENSITY_CONSECUTIVE_WINDOWS, max_windows)
    if required_streak < 1:
        return _no_cut("insufficient lines in density scan range")

    for start in range(0, len(lines) - DENSITY_WINDOW_LINES + 1, DENSITY_WINDOW_STEP):
        window = [line for _, line in lines[start : start + DENSITY_WINDOW_LINES]]
        score = _density_window_score(window)
        if score > DENSITY_SCORE_THRESHOLD:
            streak += 1
            streak_scores.append(score)
            if streak >= required_streak:
                boundary = lines[start][0]
                mean_score = sum(streak_scores[-required_streak:]) / required_streak
                confidence = min(0.95, 0.75 + mean_score * 0.2)
                return _found_result(
                    boundary=boundary,
                    confidence=confidence,
                    method="density",
                    reason=f"density score {score:.2f} across {required_streak} windows",
                )
        else:
            streak = 0
            streak_scores.clear()

    return _no_cut("density threshold not met in trailing section")


def detect_references(md_text: str) -> ReferenceDetectionResult:
    if len(md_text) < MIN_DOC_CHARS:
        return _no_cut("document too short")

    for level_fn in (level1_header, level2_prefix, level3_density):
        result = level_fn(md_text)
        if result.found:
            return result
    return _no_cut("reference section not detected")


def benchmark_detection(corpus_dir: Path) -> ReferenceDetectionStats:
    """Walk a markdown corpus and aggregate detection outcomes via strip_references."""
    from src.preprocess.strip_references import strip_references

    stats = ReferenceDetectionStats()
    for md_path in sorted(corpus_dir.glob("*.md")):
        result = strip_references(md_path.read_text(encoding="utf-8"))
        if result.anomaly_rejected:
            stats.anomaly_rejected_count += 1
            continue
        if not result.references_found:
            stats.no_cut_count += 1
            continue
        method = result.detection_method or "none"
        if method == "header":
            stats.header_match_count += 1
        elif method == "prefix":
            stats.prefix_match_count += 1
        elif method == "density":
            stats.density_match_count += 1
        else:
            stats.no_cut_count += 1
    return stats
