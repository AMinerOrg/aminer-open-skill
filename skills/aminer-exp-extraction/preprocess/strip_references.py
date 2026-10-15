"""Strip References / Bibliography sections from Markdown text."""

from __future__ import annotations

from dataclasses import dataclass

# 从根目录导入
from reference_detector import (
    MIN_DOC_CHARS,
    detect_references,
    line_at_offset,
)

MAX_REMOVAL_RATIO = 0.70


@dataclass(frozen=True)
class StripReferencesResult:
    text: str
    references_found: bool
    original_char_count: int
    stripped_char_count: int
    matched_heading: str | None = None
    detection_method: str | None = None
    confidence: float | None = None
    reason: str | None = None
    anomaly_rejected: bool = False
    removal_ratio: float | None = None


def _base_fields(
    *,
    text: str,
    original_char_count: int,
    references_found: bool,
    matched_heading: str | None = None,
    detection_method: str | None = None,
    confidence: float | None = None,
    reason: str | None = None,
    anomaly_rejected: bool = False,
    removal_ratio: float | None = None,
) -> StripReferencesResult:
    stripped_char_count = len(text)
    return StripReferencesResult(
        text=text,
        references_found=references_found,
        original_char_count=original_char_count,
        stripped_char_count=stripped_char_count,
        matched_heading=matched_heading,
        detection_method=detection_method,
        confidence=confidence,
        reason=reason,
        anomaly_rejected=anomaly_rejected,
        removal_ratio=removal_ratio,
    )


def strip_references(md_text: str) -> StripReferencesResult:
    """Detect a reference boundary and truncate, with safe anomaly fallback."""
    original = md_text
    original_len = len(original)

    if original_len < MIN_DOC_CHARS:
        return _base_fields(
            text=original,
            original_char_count=original_len,
            references_found=False,
            detection_method="none",
            reason="document too short",
            removal_ratio=0.0,
        )

    detection = detect_references(original)
    if not detection.found or detection.boundary is None:
        return _base_fields(
            text=original,
            original_char_count=original_len,
            references_found=False,
            detection_method=detection.method,
            confidence=detection.confidence,
            reason=detection.reason,
            removal_ratio=0.0,
        )

    stripped = original[: detection.boundary].rstrip()
    removal_ratio = 1.0 - (len(stripped) / original_len)
    matched_heading = line_at_offset(original, detection.boundary)

    if removal_ratio >= MAX_REMOVAL_RATIO:
        return _base_fields(
            text=original,
            original_char_count=original_len,
            references_found=False,
            matched_heading=matched_heading,
            detection_method="anomaly_rejected",
            confidence=detection.confidence,
            reason=(
                f"removal_ratio={removal_ratio:.2f} exceeds threshold {MAX_REMOVAL_RATIO}"
            ),
            anomaly_rejected=True,
            removal_ratio=removal_ratio,
        )

    return _base_fields(
        text=stripped,
        original_char_count=original_len,
        references_found=True,
        matched_heading=matched_heading,
        detection_method=detection.method,
        confidence=detection.confidence,
        reason=detection.reason,
        removal_ratio=removal_ratio,
    )
