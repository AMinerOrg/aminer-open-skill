"""Local evidence anchors and manuscript viability checks."""

from __future__ import annotations

import re
from typing import Any


def sentence_bounded_spans(text: str, *, target_words: int) -> list[str]:
    normalized = text.strip()
    if not normalized:
        return []
    units = [
        unit.strip()
        for unit in re.split(
            r"(?<=[.!?。！？])\s*(?=(?:[A-Z0-9$\[(]|[\u4e00-\u9fff]))|\n+",
            normalized,
        )
        if unit.strip()
    ]
    if not units:
        return [normalized]
    if len(units) == 1 and len(units[0].split()) > target_words:
        words = units[0].split()
        return [
            " ".join(words[start : start + target_words])
            for start in range(0, len(words), target_words)
        ]
    spans: list[str] = []
    current: list[str] = []
    current_words = 0
    for unit in units:
        unit_words = len(unit.split())
        if current and current_words + unit_words > target_words:
            spans.append(" ".join(current))
            current = []
            current_words = 0
        current.append(unit)
        current_words += unit_words
    if current:
        spans.append(" ".join(current))
    return spans


def build_anchor_catalog(
    pages: list[str],
    *,
    source_locations: list[dict[str, Any]] | None = None,
    chunk_words: int = 115,
    max_chunks_per_page: int = 5,
) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    for page_number, page_text in enumerate(pages, start=1):
        source = (
            source_locations[page_number - 1]
            if source_locations and page_number <= len(source_locations)
            else None
        )
        structured_blocks = (
            source.get("blocks")
            if isinstance(source, dict) and isinstance(source.get("blocks"), list)
            else []
        )
        raw_blocks = [
            part.strip() for part in re.split(r"\n\s*\n", page_text) if part.strip()
        ]
        content_blocks = [
            block
            for block in raw_blocks
            if not re.fullmatch(r"#{1,6}\s+(.+?)\s*#*", block)
        ]
        if not content_blocks:
            continue
        chunks: list[tuple[str, dict[str, Any] | None]] = []
        if structured_blocks:
            block_inputs = [
                (str(block.get("markdown") or "").strip(), block)
                for block in structured_blocks
                if isinstance(block, dict)
                and not block.get("is_heading")
                and str(block.get("markdown") or "").strip()
            ]
        else:
            first_block = (
                source.get("block_start", source.get("paragraph_start"))
                if source
                else None
            )
            block_inputs = [
                (
                    block,
                    {"section_block": first_block + offset}
                    if isinstance(first_block, int)
                    else None,
                )
                for offset, block in enumerate(content_blocks)
            ]
        for block, block_metadata in block_inputs:
            for span in sentence_bounded_spans(block, target_words=chunk_words):
                if len(span.split()) >= 6 or len(span) >= 24:
                    chunks.append((span, block_metadata))
        if not source and len(chunks) > max_chunks_per_page:
            indexes = sorted(
                {
                    round(index * (len(chunks) - 1) / (max_chunks_per_page - 1))
                    for index in range(max_chunks_per_page)
                }
            )
            chunks = [chunks[index] for index in indexes]
        for chunk_number, (quote, block_metadata) in enumerate(chunks, start=1):
            anchor_id = f"P{page_number}S{chunk_number}"
            entry: dict[str, Any] = {
                "page": page_number,
                "quote": quote,
                "anchor_version": "sentence_block_v2",
            }
            if source:
                block_metadata = block_metadata or {}
                block_number = block_metadata.get("section_block")
                section = str(
                    block_metadata.get("section")
                    or source.get("section")
                    or "Document"
                )
                structured_location = bool(structured_blocks)
                source_unit = str(
                    source.get("location_unit") or "aminer_content_block"
                )
                location_type = (
                    "grobid_tei_block"
                    if source_unit == "grobid_tei_block"
                    else "aminer_content_list_block"
                )
                entry.update(
                    {
                        "location_type": location_type
                        if structured_location
                        else "markdown_section_paragraph",
                        "section": section,
                        "paragraph_start": block_number,
                        "paragraph_end": block_number,
                        "block_start": block_number,
                        "block_end": block_number,
                        "physical_page": page_number if structured_location else None,
                        "page_index": page_number - 1 if structured_location else None,
                        "page_block": block_metadata.get("page_block"),
                        "document_block": block_metadata.get("document_block"),
                        "source_block_type": block_metadata.get("type"),
                        "bbox": block_metadata.get("bbox") or [],
                        "location_unit": source_unit
                        if structured_location
                        else "markdown_block",
                        "location_numbering": (
                            str(
                                source.get("location_numbering")
                                or "physical_page_and_section_block"
                            )
                            if structured_location
                            else "section_local"
                        ),
                        "location_label": (
                            f"Page {page_number}, {section}, content block {block_number}"
                            if structured_location
                            else f"{section}, content block {block_number}"
                            if block_number
                            else section
                        ),
                    }
                )
            catalog[anchor_id] = entry
    return catalog


EXPERIMENT_SCOPE_PATTERN = re.compile(
    r"\b(?:experiment(?:s|al)?|evaluation|result(?:s)?|baseline(?:s)?|comparison|benchmark|dataset(?:s)?|ablation|table)\b",
    re.IGNORECASE,
)
EXPERIMENT_SECTION_PATTERN = re.compile(
    r"\b(?:experiment(?:s|al)?|evaluation|result(?:s)?|baseline(?:s)?|comparison|ablation|implementation|setup|empirical)\b",
    re.IGNORECASE,
)
NON_EXPERIMENT_SECTION_PATTERN = re.compile(
    r"\b(?:abstract|introduction|background|related\s+work|conclusion|"
    r"preliminar(?:y|ies)|method(?:ology)?|approach)\b",
    re.IGNORECASE,
)
EXPERIMENT_ACTION_PATTERN = re.compile(
    r"\b(?:we\s+(?:evaluate|compare|benchmark)|(?:is|are|was|were)\s+compared|"
    r"outperform(?:s|ed)?|ablation|table\s+\d+|baseline(?:s)?\s+(?:include|are|uses?)|"
    r"recall@\d+|ndcg@\d+|auc|mrr|accuracy|f1(?:-score)?)\b",
    re.IGNORECASE,
)


def experiment_anchor_catalog(
    pages: list[str], source_locations: list[dict[str, Any]] | None = None
) -> dict[str, dict[str, Any]]:
    """Return experiment evidence without importing mentions from Related Work.

    Earlier code selected every block on a page containing one generic word such
    as "evaluation". That made methods cited only in background appear to have
    been experimentally compared. Structured GROBID section labels are now the
    primary boundary; a strong comparison/metric phrase is the fallback.
    """
    catalog = build_anchor_catalog(pages, source_locations=source_locations)
    selected: dict[str, dict[str, Any]] = {}
    for anchor_id, entry in catalog.items():
        quote = str(entry.get("quote") or "")
        section = str(entry.get("section") or "")
        structured = str(entry.get("location_type") or "") == "grobid_tei_block"
        section_is_experiment = bool(EXPERIMENT_SECTION_PATTERN.search(section))
        section_is_background = bool(NON_EXPERIMENT_SECTION_PATTERN.search(section))
        strong_local_signal = bool(EXPERIMENT_ACTION_PATTERN.search(quote)) or (
            not structured and bool(EXPERIMENT_SCOPE_PATTERN.search(quote))
        )
        structured_table = (
            structured
            and str(entry.get("source_block_type") or "") == "table"
            and not section_is_background
        )
        if section_is_experiment or structured_table or (
            not structured and strong_local_signal
        ):
            selected[anchor_id] = entry
    return dict(list(selected.items())[:45])


def anchor_catalog_text(catalog: dict[str, dict[str, Any]]) -> str:
    return "\n\n".join(
        f'[{anchor_id}] {entry.get("location_label") or ("page %s" % entry["page"])}\n{entry["quote"]}'
        for anchor_id, entry in catalog.items()
    )


def assess_input_viability(
    pages: list[str],
    *,
    anchor_count: int,
    minimum_text_characters: int = 800,
    minimum_anchors: int = 4,
) -> dict[str, Any]:
    page_characters = [len(re.sub(r"\s+", "", str(page or ""))) for page in pages]
    nonempty_pages = sum(characters > 0 for characters in page_characters)
    extracted_characters = sum(page_characters)
    if not extracted_characters or not anchor_count:
        status = "parse_unreadable"
        reason = "No usable local body text or source anchors were extracted from the manuscript."
    elif extracted_characters < minimum_text_characters or anchor_count < minimum_anchors:
        status = "evidence_insufficient"
        reason = (
            "The manuscript contains some extractable text, but not enough local evidence "
            "to support a paper-level audit. Use a text-based PDF or OCR export."
        )
    else:
        status = "reviewable"
        reason = "Local text and source anchors meet the minimum evidence threshold."
    return {
        "status": status,
        "reviewable": status == "reviewable",
        "reason": reason,
        "page_count": len(pages),
        "nonempty_page_count": nonempty_pages,
        "extracted_character_count": extracted_characters,
        "source_anchor_count": anchor_count,
        "thresholds": {
            "minimum_extracted_characters": minimum_text_characters,
            "minimum_source_anchors": minimum_anchors,
        },
        "policy": (
            "Paper identity and audit findings originate from locally retained manuscript "
            "evidence. External retrieval is not used when local evidence is insufficient."
        ),
    }
