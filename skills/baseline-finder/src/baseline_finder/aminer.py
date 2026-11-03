"""Standalone AMiner Interface-B manuscript acquisition and normalization."""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit

import httpx

from .errors import BaselineAuditError
from .identity import aminer_headers


AMINER_EXTRACTED_FILES_URL = (
    "https://datacenter.aminer.cn/gateway/open_platform/api/v3/paper/extracted/files"
)
AMINER_PUB_ID = re.compile(r"^[0-9a-f]{24}$", re.IGNORECASE)
MAX_AMINER_INDEX_BYTES = 2 * 1024 * 1024
MAX_AMINER_MARKDOWN_BYTES = 12 * 1024 * 1024
MAX_AMINER_JSON_BYTES = 40 * 1024 * 1024
MAX_REDIRECTS = 3
ProgressCallback = Callable[[str, str, dict[str, Any] | None], None]


def normalize_pub_id(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if not AMINER_PUB_ID.fullmatch(normalized):
        raise BaselineAuditError(
            "AMiner pub_id must be a 24-character hexadecimal identifier."
        )
    return normalized


def _utf8_safe(value: Any) -> str:
    return str(value).encode("utf-8", errors="replace").decode("utf-8")


def _caption_text(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(
            " ".join(str(item).split()) for item in value if str(item).strip()
        ).strip()
    return " ".join(str(value or "").split()).strip()


def _render_content_block(row: dict[str, Any]) -> tuple[str, bool]:
    """Render one MinerU block without inventing unavailable content."""
    block_type = str(row.get("type") or "").lower()
    if block_type == "discarded":
        return "", False
    if block_type == "text":
        text = _utf8_safe(row.get("text") or "").strip()
        if not text:
            return "", False
        try:
            heading_level = int(row.get("text_level"))
        except (TypeError, ValueError):
            heading_level = 0
        if heading_level > 0:
            return f'{"#" * max(1, min(6, heading_level))} {text}', True
        return text, False
    if block_type == "equation":
        return _utf8_safe(row.get("text") or "").strip(), False
    if block_type == "image":
        caption = _caption_text(row.get("image_caption"))
        footnote = _caption_text(row.get("image_footnote"))
        image_path = str(row.get("img_path") or "").strip()
        reference = f"![{caption}]({image_path})" if image_path else ""
        return "\n\n".join(value for value in (reference, caption, footnote) if value), False
    if block_type == "table":
        caption = _caption_text(row.get("table_caption"))
        body = _utf8_safe(row.get("table_body") or "").strip()
        footnote = _caption_text(row.get("table_footnote"))
        image_path = str(row.get("img_path") or "").strip()
        rendered = body or (f"![{caption}]({image_path})" if image_path else "")
        return "\n\n".join(value for value in (caption, rendered, footnote) if value), False
    return _utf8_safe(row.get("text") or "").strip(), False


def semantic_markdown_chunks(
    markdown: str, *, target_chars: int = 4200
) -> tuple[list[str], list[dict[str, Any]]]:
    """Split page-less provider Markdown into bounded evidence units."""
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", markdown) if part.strip()]
    chunks: list[str] = []
    locations: list[dict[str, Any]] = []
    current: list[str] = []
    current_size = 0
    current_section = "Front matter"
    chunk_section = current_section
    section_block = 0
    block_start: int | None = None
    block_end: int | None = None

    def flush() -> None:
        nonlocal current, current_size, block_start, block_end
        if not current:
            return
        chunks.append("\n\n".join(current))
        locations.append(
            {
                "section": chunk_section,
                "paragraph_start": block_start,
                "paragraph_end": block_end,
                "block_start": block_start,
                "block_end": block_end,
                "location_unit": "markdown_block",
                "location_numbering": "section_local",
            }
        )
        current = []
        current_size = 0
        block_start = None
        block_end = None

    for paragraph in paragraphs:
        heading = re.fullmatch(r"#{1,6}\s+(.+?)\s*#*", paragraph)
        if heading:
            flush()
            current_section = " ".join(heading.group(1).split())
            section_block = 0
            chunk_section = current_section
            current = [paragraph]
            current_size = len(paragraph)
            continue
        section_block += 1
        addition = len(paragraph) + (2 if current else 0)
        if current and block_start is not None and current_size + addition > target_chars:
            flush()
            chunk_section = current_section
        if not current:
            chunk_section = current_section
        current.append(paragraph)
        current_size += addition
        block_start = block_start or section_block
        block_end = section_block
    flush()
    if chunks:
        return chunks, locations
    if not markdown:
        return [], []
    return [markdown], [
        {
            "section": "Document",
            "paragraph_start": 1,
            "paragraph_end": 1,
            "block_start": 1,
            "block_end": 1,
            "location_unit": "markdown_block",
            "location_numbering": "section_local",
        }
    ]


def content_list_context(
    content_list: list[dict[str, Any]],
    middle: dict[str, Any] | None = None,
) -> tuple[str, list[str], list[dict[str, Any]], dict[str, int]]:
    """Build Markdown and physical-page evidence units from MinerU blocks."""
    rows = [row for row in content_list if isinstance(row, dict)]
    page_indices: list[int] = []
    for row in rows:
        try:
            page_index = int(row.get("page_idx"))
        except (TypeError, ValueError):
            continue
        if page_index >= 0:
            page_indices.append(page_index)
    middle_pages = middle.get("pdf_info") if isinstance(middle, dict) else []
    middle_pages = middle_pages if isinstance(middle_pages, list) else []
    page_count = max(max(page_indices) + 1 if page_indices else 0, len(middle_pages))
    pages: list[list[str]] = [[] for _ in range(page_count)]
    page_blocks: list[list[dict[str, Any]]] = [[] for _ in range(page_count)]
    document_parts: list[str] = []
    current_section = "Front matter"
    section_block = 0
    document_block = 0
    page_block_counts = [0] * page_count
    type_counts: Counter[str] = Counter()
    current_page_index = -1

    for row in rows:
        block_type = str(row.get("type") or "unknown").lower()
        type_counts[block_type] += 1
        try:
            explicit_page_index = int(row.get("page_idx"))
        except (TypeError, ValueError):
            explicit_page_index = -1
        if 0 <= explicit_page_index < page_count:
            current_page_index = explicit_page_index
        page_index = current_page_index if 0 <= current_page_index < page_count else -1
        row["_resolved_page_idx"] = page_index if page_index >= 0 else None
        row["_page_idx_inherited"] = (
            page_index >= 0 and explicit_page_index != page_index
        )
        rendered, is_heading = _render_content_block(row)
        if not rendered:
            continue
        document_parts.append(rendered)
        if is_heading:
            current_section = re.sub(r"^#{1,6}\s+", "", rendered).strip() or current_section
            section_block = 0
        else:
            section_block += 1
            document_block += 1
        if not (0 <= page_index < page_count):
            continue
        pages[page_index].append(rendered)
        if not is_heading:
            page_block_counts[page_index] += 1
        page_blocks[page_index].append(
            {
                "type": block_type,
                "markdown": rendered,
                "is_heading": is_heading,
                "section": current_section,
                "section_block": None if is_heading else section_block,
                "page_block": None if is_heading else page_block_counts[page_index],
                "document_block": None if is_heading else document_block,
                "bbox": row.get("bbox") if isinstance(row.get("bbox"), list) else [],
                "img_path": str(row.get("img_path") or ""),
                "page_inherited": bool(row["_page_idx_inherited"]),
            }
        )

    rendered_pages: list[str] = []
    source_locations: list[dict[str, Any]] = []
    for page_index in range(page_count):
        blocks = page_blocks[page_index]
        rendered_pages.append("\n\n".join(pages[page_index]))
        sections = list(
            dict.fromkeys(
                str(block.get("section") or "Document")
                for block in blocks
                if not block.get("is_heading")
            )
        )
        middle_page = (
            middle_pages[page_index]
            if page_index < len(middle_pages) and isinstance(middle_pages[page_index], dict)
            else {}
        )
        source_locations.append(
            {
                "physical_page": page_index + 1,
                "page_index": page_index,
                "section": " / ".join(sections[:3]) or "Document",
                "sections": sections,
                "location_unit": "aminer_content_block",
                "location_numbering": "physical_page_and_section_block",
                "page_size": (
                    middle_page.get("page_size")
                    if isinstance(middle_page.get("page_size"), list)
                    else []
                ),
                "blocks": blocks,
            }
        )
    return (
        "\n\n".join(document_parts).strip(),
        rendered_pages,
        source_locations,
        dict(type_counts),
    )


def _first_group(payload: Any) -> dict[str, Any]:
    groups = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(groups, list) and groups and isinstance(groups[0], dict):
        return groups[0]
    return {}


def _trusted_artifact_url(url: str) -> bool:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").rstrip(".").lower()
    return (
        parsed.scheme == "https"
        and not parsed.username
        and not parsed.password
        and (hostname == "aliyuncs.com" or hostname.endswith(".aliyuncs.com"))
    )


def _json_payload(response: httpx.Response, *, byte_limit: int, label: str) -> Any:
    if len(response.content) > byte_limit:
        raise BaselineAuditError(f"AMiner {label} exceeds its configured safety limit.")
    try:
        return json.loads(response.content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BaselineAuditError(f"AMiner {label} is not valid JSON.") from exc


def _trusted_get(client: httpx.Client, url: str, *, byte_limit: int) -> httpx.Response:
    current = url
    for redirect_count in range(MAX_REDIRECTS + 1):
        if not _trusted_artifact_url(current):
            raise BaselineAuditError(
                "AMiner returned an untrusted artifact download URL; download was refused."
            )
        try:
            response = client.get(current, follow_redirects=False)
        except httpx.HTTPError as exc:
            raise BaselineAuditError("AMiner artifact download failed.") from exc
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location")
            if not location or redirect_count == MAX_REDIRECTS:
                raise BaselineAuditError("AMiner artifact redirect could not be followed safely.")
            current = urljoin(current, location)
            continue
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise BaselineAuditError(
                f"AMiner artifact download failed with HTTP {response.status_code}."
            ) from exc
        if len(response.content) > byte_limit:
            raise BaselineAuditError("AMiner artifact exceeds its configured safety limit.")
        return response
    raise BaselineAuditError("AMiner artifact redirect limit exceeded.")


def _private_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    path.chmod(0o600)


def fetch_aminer_source(
    pub_id: str,
    run_dir: Path,
    *,
    api_key: str | None = None,
    proxy: str | None = None,
    progress: ProgressCallback | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Fetch and normalize one AMiner manuscript without repository dependencies."""
    normalized_id = normalize_pub_id(pub_id)
    credential = str(api_key or os.environ.get("AMINER_API_KEY") or "").strip()
    if not credential:
        raise BaselineAuditError(
            "AMINER_API_KEY is unavailable; --pub-id input cannot be fetched."
        )
    run_dir.mkdir(parents=True, exist_ok=True)
    if progress:
        progress(
            "parsing",
            "Requesting structured manuscript files from AMiner Interface B.",
            {"aminer_pub_id": normalized_id},
        )
    owns_client = client is None
    if client is None:
        client = httpx.Client(
            timeout=httpx.Timeout(90.0, connect=10.0),
            proxy=proxy,
            follow_redirects=False,
            trust_env=proxy is not None,
        )
    headers = aminer_headers(credential)
    try:
        try:
            structure_response = client.post(
                AMINER_EXTRACTED_FILES_URL,
                headers=headers,
                json={"pub_id": normalized_id},
            )
            structure_response.raise_for_status()
            filtered_response = client.post(
                AMINER_EXTRACTED_FILES_URL,
                headers=headers,
                json={"pub_id": normalized_id, "file_types": ".md"},
            )
            filtered_response.raise_for_status()
        except httpx.HTTPError as exc:
            raise BaselineAuditError("AMiner Interface B request failed.") from exc
        structure_group = _first_group(
            _json_payload(
                structure_response,
                byte_limit=MAX_AMINER_INDEX_BYTES,
                label="structured-file index",
            )
        )
        filtered_group = _first_group(
            _json_payload(
                filtered_response,
                byte_limit=MAX_AMINER_INDEX_BYTES,
                label="Markdown-file index",
            )
        )
        json_urls = (
            structure_group.get("json")
            if isinstance(structure_group.get("json"), list)
            else []
        )
        markdown_urls = (
            filtered_group.get("md")
            if isinstance(filtered_group.get("md"), list)
            else []
        )

        provider_content_list: list[dict[str, Any]] = []
        middle: dict[str, Any] = {}
        for raw_url in json_urls:
            artifact_url = str(raw_url or "")
            artifact_response = _trusted_get(
                client, artifact_url, byte_limit=MAX_AMINER_JSON_BYTES
            )
            payload = _json_payload(
                artifact_response,
                byte_limit=MAX_AMINER_JSON_BYTES,
                label="structured artifact",
            )
            path = urlsplit(artifact_url).path
            if path.endswith("_content_list.json"):
                raw_rows = (
                    payload
                    if isinstance(payload, list)
                    else payload.get("content_list", []) if isinstance(payload, dict) else []
                )
                provider_content_list = [
                    row for row in raw_rows if isinstance(row, dict)
                ]
            elif path.endswith("_middle.json") and isinstance(payload, dict):
                middle = payload

        provider_markdown = ""
        if markdown_urls:
            markdown_response = _trusted_get(
                client,
                str(markdown_urls[0] or ""),
                byte_limit=MAX_AMINER_MARKDOWN_BYTES,
            )
            provider_markdown = _utf8_safe(
                markdown_response.content.decode("utf-8", errors="replace")
            ).strip()

        type_counts: dict[str, int] = {}
        working_rows: list[dict[str, Any]] = []
        source_provider = "aminer_interface_b_content_list"
        if provider_content_list:
            working_rows = [dict(row) for row in provider_content_list]
            markdown, pages, source_locations, type_counts = content_list_context(
                working_rows, middle
            )
        else:
            markdown, pages, source_locations = "", [], []
        fallback_reason = None
        if not markdown:
            if not provider_markdown:
                raise BaselineAuditError(
                    "AMiner Interface B returned no usable manuscript content for this pub_id."
                )
            markdown = provider_markdown
            pages, source_locations = semantic_markdown_chunks(markdown)
            source_provider = "aminer_interface_b_markdown_fallback"
            fallback_reason = "structured content_list was unavailable or empty"
        elif not any(page.strip() for page in pages):
            pages, source_locations = semantic_markdown_chunks(markdown)
            source_provider = "aminer_interface_b_content_list_semantic_chunks"
            fallback_reason = "structured blocks had no usable physical-page indices"

        markdown_path = run_dir / "source.md"
        markdown_path.write_text(markdown, encoding="utf-8")
        markdown_path.chmod(0o600)
        provider_markdown_file = None
        if provider_markdown and provider_markdown != markdown:
            provider_path = run_dir / "source_provider.md"
            provider_path.write_text(provider_markdown, encoding="utf-8")
            provider_path.chmod(0o600)
            provider_markdown_file = provider_path.name
        if provider_content_list:
            _private_json(run_dir / "source_content_list.json", provider_content_list)
        if source_locations:
            _private_json(run_dir / "source_locations.json", source_locations)
        if middle:
            _private_json(run_dir / "source_middle.json", middle)
        manifest = {
            "input_source": "aminer_interface_b",
            "retrieval_interface": "AMiner interface B extracted files",
            "aminer_pub_id": normalized_id,
            "source_provider": source_provider,
            "markdown_file": markdown_path.name,
            "provider_markdown_file": provider_markdown_file,
            "markdown_bytes": len(markdown.encode("utf-8")),
            "physical_page_count": (
                len(pages) if source_provider == "aminer_interface_b_content_list" else None
            ),
            "logical_text_chunks": (
                None if source_provider == "aminer_interface_b_content_list" else len(pages)
            ),
            "content_list_file": (
                "source_content_list.json" if provider_content_list else None
            ),
            "source_locations_file": (
                "source_locations.json" if source_locations else None
            ),
            "middle_file": "source_middle.json" if middle else None,
            "content_block_count": len(provider_content_list),
            "content_block_type_counts": type_counts,
            "page_coordinate_count": sum(
                isinstance(row.get("_resolved_page_idx"), int)
                and isinstance(row.get("bbox"), list)
                for row in working_rows
            ),
            "explicit_page_coordinate_count": sum(
                isinstance(row.get("page_idx"), int)
                and isinstance(row.get("bbox"), list)
                for row in working_rows
            ),
            "inherited_page_block_count": sum(
                bool(row.get("_page_idx_inherited")) for row in working_rows
            ),
            "structured_fallback_used": fallback_reason is not None,
            "structured_fallback_reason": fallback_reason,
            "location_unit": (
                "aminer_content_block"
                if source_provider == "aminer_interface_b_content_list"
                else "markdown_block"
            ),
            "location_numbering": (
                "physical_page_and_section_block"
                if source_provider == "aminer_interface_b_content_list"
                else "section_local"
            ),
            "asset_policy": (
                "Image binaries are not downloaded because this focused baseline audit "
                "uses textual experiment evidence; table bodies, captions, equations, "
                "image captions, page indices, and bounding boxes are retained."
            ),
        }
        _private_json(run_dir / "source_manifest.json", manifest)
        diagnostics = [
            {
                "parser": source_provider,
                "status": "fallback" if fallback_reason else "completed",
                "message": (
                    f"AMiner produced {len(provider_content_list)} structured blocks "
                    f"across {len(pages)} evidence units."
                    + (f" Fallback: {fallback_reason}." if fallback_reason else "")
                ),
            }
        ]
        if progress:
            progress(
                "parsing",
                "AMiner manuscript context is ready.",
                {
                    "evidence_units": len(pages),
                    "content_blocks": len(provider_content_list),
                    "structured_fallback_used": fallback_reason is not None,
                },
            )
        return {
            "markdown": markdown,
            "pages": pages,
            "local_title": "",
            "source_locations": source_locations,
            "provider": source_provider,
            "grobid_tei_file": None,
            "fallback_used": fallback_reason is not None,
            "diagnostics": diagnostics,
            "manifest": manifest,
        }
    finally:
        if owns_client:
            client.close()
