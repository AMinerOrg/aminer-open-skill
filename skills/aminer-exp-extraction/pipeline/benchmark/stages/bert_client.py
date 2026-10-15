"""Sentence utilities + (removed) SciBERT client shim for benchmark workflows.

The SciBERT ``/filter/batch`` network client is gone: this skill's only model
service is the public BigModel API (GLM sentence filter + extraction). The pure
helpers ``split_sentences`` / ``filter_english_only`` remain — the vendored
workflow modules use them for text slicing. ``SerialBertClient`` is kept as an
explicit-error shim so any stale call site fails loudly instead of silently
reaching for a removed internal service.
"""

from __future__ import annotations

import re
from typing import Any

from pipeline.benchmark.config import BERT_TIMEOUT


def split_sentences(text: str) -> list[str]:
    """Split text into sentences (simple implementation for benchmark)."""
    text = re.sub(r"\s+", " ", text)
    parts = re.split(r"(?<=[.!?])\s+", text)
    result: list[str] = []
    for part in parts:
        sentence = part.strip()
        if len(sentence) > 15:
            result.append(sentence)
    return result


def filter_english_only(sentences: list[str]) -> list[str]:
    """Filter to keep only English sentences."""
    english: list[str] = []
    for sentence in sentences:
        first_alpha = next((ch for ch in sentence if ch.isalpha()), "")
        if first_alpha and first_alpha.isascii():
            english.append(sentence)
    return english


class SerialBertClient:
    """Removed SciBERT client shim — always raises.

    The sentence-filter stage now runs on the public BigModel service
    (``pipeline.production.adapters.glm_sentence_filter``). This shim exists
    only so legacy vendored call sites fail with a clear message.
    """

    def __init__(self, url: str = "", timeout: int = BERT_TIMEOUT) -> None:
        self.url = url
        self.timeout = timeout

    def filter_sentences_serial(
        self,
        sentences: list[str],
        threshold: float = 0.6,
    ) -> dict[str, Any]:
        """Always raises — the SciBERT /filter/batch path was removed."""
        raise RuntimeError(
            "SciBERT /filter/batch path removed — this skill uses the GLM "
            "sentence filter only (public BigModel service, no internal services)"
        )


class BatchBertClient:
    """Future: POST /filter/batch. Not implemented in v0.1.0."""

    def filter_papers(self, papers: list[dict]) -> dict:
        """Phase 2: bert batch mode."""
        raise NotImplementedError("Phase 2: bert batch mode not implemented in v0.1.0")
