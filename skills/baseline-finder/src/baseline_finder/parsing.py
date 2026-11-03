"""PDF parsing with structured GROBID output and a visible pypdf fallback."""

from __future__ import annotations

import re
import xml.etree.ElementTree as etree
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

import httpx
from pypdf import PdfReader


@dataclass
class MarkdownParseResult:
    markdown: str
    pages: list[str]
    content_list: list[dict[str, Any]] | None = None
    provider: str = "local_pypdf"
    source_locations: list[dict[str, Any]] | None = None
    bibliography_entries: list[dict[str, Any]] | None = None
    citation_contexts: list[dict[str, Any]] | None = None


TEI_NAMESPACE = "http://www.tei-c.org/ns/1.0"
TEI = f"{{{TEI_NAMESPACE}}}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _tei_text(node: etree.Element | None) -> str:
    if node is None:
        return ""
    return " ".join("".join(node.itertext()).split())


def _coordinate_pages(node: etree.Element) -> list[int]:
    pages: list[int] = []
    for candidate in node.iter():
        coords = str(candidate.get("coords") or "")
        for box in coords.split(";"):
            token = box.split(",", 1)[0].strip()
            if not token:
                continue
            try:
                page = int(float(token))
            except ValueError:
                continue
            if page > 0 and page not in pages:
                pages.append(page)
    return pages


def _normalized_alignment_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _align_text_to_page(text: str, physical_pages: list[str], default_page: int) -> int:
    needle = _normalized_alignment_text(text)
    if len(needle) >= 32:
        probes = (needle[:160], needle[-160:])
        normalized_pages = [_normalized_alignment_text(page) for page in physical_pages]
        for probe in probes:
            if len(probe) < 32:
                continue
            for index, page in enumerate(normalized_pages, start=1):
                if probe in page:
                    return index
    return max(1, min(default_page, len(physical_pages) or 1))


def _bibliography_title(node: etree.Element) -> str:
    """Return the publication title rather than the containing venue title."""
    paths = (
        f"./{TEI}analytic/{TEI}title[@type='main']",
        f"./{TEI}analytic/{TEI}title[@level='a']",
        f"./{TEI}monogr/{TEI}title[@type='main']",
        f"./{TEI}monogr/{TEI}title[@level='m']",
        f".//{TEI}title[@type='main']",
        f".//{TEI}title",
    )
    for path in paths:
        title = _tei_text(node.find(path)).strip(" .")
        if title:
            return title
    return ""


def _bibliography_authors(node: etree.Element) -> list[str]:
    authors = node.findall(f"./{TEI}analytic/{TEI}author")
    if not authors:
        authors = node.findall(f"./{TEI}monogr/{TEI}author")
    rendered: list[str] = []
    seen: set[str] = set()
    for author in authors:
        person = author.find(f".//{TEI}persName")
        if person is not None:
            name_parts = [
                _tei_text(child)
                for child in list(person)
                if _tei_text(child)
            ]
            name = " ".join(name_parts) or _tei_text(person)
        else:
            name = _tei_text(author)
        key = name.casefold()
        if name and key not in seen:
            rendered.append(name)
            seen.add(key)
    return rendered


def _bibliography_year(node: etree.Element) -> int | None:
    for date_node in node.findall(f".//{TEI}date"):
        value = str(date_node.get("when") or _tei_text(date_node) or "")
        match = re.search(r"\b(?:19|20)\d{2}\b", value)
        if match:
            return int(match.group(0))
    return None


def _bibliography_identifiers(node: etree.Element) -> list[dict[str, str]]:
    identifiers: list[dict[str, str]] = []
    for identifier in node.findall(f".//{TEI}idno"):
        value = _tei_text(identifier)
        if value:
            identifiers.append(
                {
                    "type": str(identifier.get("type") or "").strip(),
                    "value": value,
                }
            )
    return identifiers


def extract_grobid_bibliography(root: etree.Element) -> list[dict[str, Any]]:
    """Extract ``back/listBibl`` records without reconstructing paper titles."""
    entries: list[dict[str, Any]] = []
    nodes = root.findall(
        f".//{TEI}text/{TEI}back//{TEI}listBibl/{TEI}biblStruct"
    )
    for index, node in enumerate(nodes, start=1):
        tei_id = str(node.get(XML_ID) or node.get("id") or "").strip()
        title = _bibliography_title(node)
        raw_reference = _tei_text(
            node.find(f"./{TEI}note[@type='raw_reference']")
        )
        complete_entry = raw_reference or _tei_text(node)
        if not title and not complete_entry:
            continue
        entries.append(
            {
                "tei_id": tei_id,
                "ordinal": index,
                "title": title,
                "authors": _bibliography_authors(node),
                "year": _bibliography_year(node),
                "entry": complete_entry,
                "raw_reference": raw_reference,
                "identifiers": _bibliography_identifiers(node),
                "coords": str(node.get("coords") or ""),
            }
        )
    return entries


def extract_grobid_inline_citations(
    root: etree.Element,
    body: etree.Element,
) -> list[dict[str, Any]]:
    """Preserve each inline bibliographic ref's target, label, and full context."""
    parents = {
        child: parent
        for parent in root.iter()
        for child in list(parent)
    }
    contexts: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for ref in body.iter(f"{TEI}ref"):
        if str(ref.get("type") or "").strip().lower() != "bibr":
            continue
        raw_target = " ".join(str(ref.get("target") or "").split())
        target_ids = [
            token.lstrip("#")
            for token in re.split(r"[\s,;]+", raw_target)
            if token.strip().lstrip("#")
        ]
        label = _tei_text(ref)
        container = ref
        while container in parents:
            container = parents[container]
            if container.tag.rsplit("}", 1)[-1] in {"s", "p"}:
                break
        context = _tei_text(container)
        section = "Document"
        ancestor = container
        while ancestor in parents:
            ancestor = parents[ancestor]
            if ancestor.tag.rsplit("}", 1)[-1] == "div":
                section = _tei_text(ancestor.find(f"./{TEI}head")) or section
                break
        pages = _coordinate_pages(ref)
        key = (raw_target, label, context)
        if key in seen:
            continue
        seen.add(key)
        contexts.append(
            {
                "target": raw_target,
                "target_ids": target_ids,
                "label": label,
                "context": context,
                "section": section,
                "page": pages[0] if pages else None,
                "coords": str(ref.get("coords") or ""),
            }
        )
    return contexts


def parse_grobid_fulltext(
    tei_xml: str,
    *,
    physical_pages: list[str],
) -> MarkdownParseResult:
    """Build physical-page and section-aware text from GROBID TEI."""
    root = etree.fromstring(tei_xml)
    body = root.find(f".//{TEI}text/{TEI}body")
    if body is None:
        raise ValueError("GROBID TEI does not contain a document body.")

    bibliography_entries = extract_grobid_bibliography(root)
    citation_contexts = extract_grobid_inline_citations(root, body)
    contexts_by_target: dict[str, list[dict[str, Any]]] = {}
    for context in citation_contexts:
        for target_id in context.get("target_ids") or []:
            contexts_by_target.setdefault(str(target_id), []).append(dict(context))
    for entry in bibliography_entries:
        entry["citation_contexts"] = contexts_by_target.get(
            str(entry.get("tei_id") or ""), []
        )

    coordinate_pages = _coordinate_pages(body)
    page_count = max([len(physical_pages), *coordinate_pages, 1])
    page_parts: list[list[str]] = [[] for _ in range(page_count)]
    page_blocks: list[list[dict[str, Any]]] = [[] for _ in range(page_count)]
    content_list: list[dict[str, Any]] = []
    page_sections: list[set[str]] = [set() for _ in range(page_count)]
    section_counts: dict[str, int] = {}
    document_block = 0
    last_page = 1

    def add_block(
        text: str,
        *,
        page: int,
        section: str,
        block_type: str,
        coords: str = "",
    ) -> None:
        nonlocal document_block, last_page
        rendered = " ".join(str(text or "").split())
        if not rendered:
            return
        page = max(1, min(page, page_count))
        page_index = page - 1
        section = section.strip() or "Document"
        if section not in page_sections[page_index]:
            page_sections[page_index].add(section)
            page_parts[page_index].append(f"## {section}")
            page_blocks[page_index].append(
                {
                    "type": "heading",
                    "markdown": f"## {section}",
                    "is_heading": True,
                    "section": section,
                    "section_block": None,
                    "page_block": None,
                    "document_block": None,
                    "coords": "",
                    "bbox": [],
                }
            )
        section_counts[section] = section_counts.get(section, 0) + 1
        document_block += 1
        page_block = sum(
            not item.get("is_heading") for item in page_blocks[page_index]
        ) + 1
        metadata = {
            "type": block_type,
            "markdown": rendered,
            "is_heading": False,
            "section": section,
            "section_block": section_counts[section],
            "page_block": page_block,
            "document_block": document_block,
            "coords": coords,
            "bbox": [],
        }
        page_parts[page_index].append(rendered)
        page_blocks[page_index].append(metadata)
        content_list.append(
            {
                "page_idx": page_index,
                "type": block_type,
                "text": rendered,
                "section": section,
                "coords": coords,
            }
        )
        last_page = page

    title = _tei_text(root.find(f".//{TEI}teiHeader//{TEI}titleStmt/{TEI}title"))
    if title:
        page_parts[0].append(title)
        page_blocks[0].append(
            {
                "type": "title",
                "markdown": title,
                "is_heading": True,
                "section": "Front matter",
                "section_block": None,
                "page_block": None,
                "document_block": None,
                "coords": "",
                "bbox": [],
            }
        )
    abstract = _tei_text(root.find(f".//{TEI}teiHeader//{TEI}abstract"))
    if abstract:
        add_block(abstract, page=1, section="Abstract", block_type="abstract")

    def paragraph_blocks(node: etree.Element, section: str) -> None:
        nonlocal last_page
        sentences = node.findall(f".//{TEI}s")
        if not sentences:
            text = _tei_text(node)
            pages = _coordinate_pages(node)
            page = pages[0] if pages else _align_text_to_page(
                text, physical_pages, last_page
            )
            add_block(
                text,
                page=page,
                section=section,
                block_type="text",
                coords=str(node.get("coords") or ""),
            )
            return
        groups: list[tuple[int, list[str], list[str]]] = []
        for sentence in sentences:
            text = _tei_text(sentence)
            if not text:
                continue
            pages = _coordinate_pages(sentence)
            page = pages[0] if pages else _align_text_to_page(
                text, physical_pages, last_page
            )
            coords = str(sentence.get("coords") or "")
            if groups and groups[-1][0] == page:
                groups[-1][1].append(text)
                if coords:
                    groups[-1][2].append(coords)
            else:
                groups.append((page, [text], [coords] if coords else []))
        for page, texts, coords in groups:
            add_block(
                " ".join(texts),
                page=page,
                section=section,
                block_type="text",
                coords=";".join(coords),
            )

    def walk_div(node: etree.Element, inherited_section: str) -> None:
        head = node.find(f"./{TEI}head")
        section = _tei_text(head) or inherited_section or "Document"
        for child in list(node):
            local = child.tag.rsplit("}", 1)[-1]
            if local == "head":
                continue
            if local == "div":
                walk_div(child, section)
            elif local == "p":
                paragraph_blocks(child, section)
            elif local in {"formula", "figure", "table"}:
                text = _tei_text(child)
                pages = _coordinate_pages(child)
                page = pages[0] if pages else _align_text_to_page(
                    text, physical_pages, last_page
                )
                block_type = "table" if child.get("type") == "table" else local
                add_block(
                    text,
                    page=page,
                    section=section,
                    block_type=block_type,
                    coords=str(child.get("coords") or ""),
                )
            elif local == "list":
                for item in child.findall(f"./{TEI}item"):
                    text = _tei_text(item)
                    pages = _coordinate_pages(item)
                    page = pages[0] if pages else _align_text_to_page(
                        text, physical_pages, last_page
                    )
                    add_block(
                        text,
                        page=page,
                        section=section,
                        block_type="list_item",
                        coords=str(item.get("coords") or ""),
                    )

    for child in list(body):
        local = child.tag.rsplit("}", 1)[-1]
        if local == "div":
            walk_div(child, "Document")
        elif local in {"formula", "figure", "table"}:
            text = _tei_text(child)
            pages = _coordinate_pages(child)
            page = pages[0] if pages else _align_text_to_page(
                text, physical_pages, last_page
            )
            block_type = "table" if child.get("type") == "table" else local
            section = (
                "Tables"
                if block_type == "table"
                else "Figures" if block_type == "figure" else "Document"
            )
            add_block(
                text,
                page=page,
                section=section,
                block_type=block_type,
                coords=str(child.get("coords") or ""),
            )

    if document_block == 0:
        raise ValueError("GROBID TEI body did not contain reviewable text blocks.")
    rendered_pages = ["\n\n".join(parts).strip() for parts in page_parts]
    source_locations: list[dict[str, Any]] = []
    for page_index, blocks in enumerate(page_blocks):
        sections = list(
            dict.fromkeys(
                str(block.get("section") or "Document")
                for block in blocks
                if not block.get("is_heading")
            )
        )
        source_locations.append(
            {
                "physical_page": page_index + 1,
                "page_index": page_index,
                "section": " / ".join(sections[:3]) or "Document",
                "sections": sections,
                "location_unit": "grobid_tei_block",
                "location_numbering": "physical_page_and_section_block",
                "blocks": blocks,
            }
        )
    markdown = "\n\n".join(
        f"## Page {index}\n\n{page}"
        for index, page in enumerate(rendered_pages, start=1)
        if page
    ).strip()
    return MarkdownParseResult(
        markdown=markdown,
        pages=rendered_pages,
        content_list=content_list,
        provider="local_grobid_tei_hybrid",
        source_locations=source_locations,
        bibliography_entries=bibliography_entries,
        citation_contexts=citation_contexts,
    )


def parse_pdf_locally(pdf_bytes: bytes) -> MarkdownParseResult:
    reader = PdfReader(BytesIO(pdf_bytes))
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    markdown = "\n".join(
        f"## Page {index}\n\n{page}\n"
        for index, page in enumerate(pages, start=1)
    ).strip()
    content_list = [
        {"page_idx": page_idx, "type": "text", "text": line.strip()}
        for page_idx, page in enumerate(pages)
        for line in page.splitlines()
        if line.strip()
    ]
    return MarkdownParseResult(
        markdown=markdown,
        pages=pages,
        content_list=content_list,
    )


def grobid_document_title(tei_xml: str) -> str:
    try:
        root = etree.fromstring(tei_xml)
    except etree.ParseError:
        return ""
    title = root.find(".//{*}teiHeader/{*}fileDesc/{*}titleStmt/{*}title")
    if title is None:
        return ""
    return re.sub(r"\s+", " ", "".join(title.itertext())).strip(" .")


def grobid_document_authors(tei_xml: str) -> list[str]:
    """Return header authors only; never guess authors from body text."""
    try:
        root = etree.fromstring(tei_xml)
    except etree.ParseError:
        return []
    authors: list[str] = []
    seen: set[str] = set()
    nodes = root.findall(".//{*}teiHeader//{*}analytic/{*}author")
    if not nodes:
        nodes = root.findall(".//{*}teiHeader//{*}titleStmt/{*}author")
    for node in nodes:
        person = node.find(".//{*}persName")
        name = _tei_text(person if person is not None else node)
        key = name.casefold()
        if name and key not in seen:
            authors.append(name)
            seen.add(key)
    return authors


def grobid_document_year(tei_xml: str) -> int | None:
    """Return an explicit bibliographic year; do not infer one from body text."""
    try:
        root = etree.fromstring(tei_xml)
    except etree.ParseError:
        return None
    for node in root.findall(".//{*}teiHeader//{*}date"):
        value = str(node.get("when") or _tei_text(node) or "")
        match = re.search(r"\b(19|20)\d{2}\b", value)
        if match:
            return int(match.group(0))
    return None


def request_grobid_fulltext(pdf_path: Path, grobid_url: str) -> str:
    with httpx.Client(
        timeout=httpx.Timeout(120.0, connect=5.0), trust_env=False
    ) as client:
        response = client.post(
            f"{grobid_url.rstrip('/')}/api/processFulltextDocument",
            files={"input": (pdf_path.name, pdf_path.read_bytes(), "application/pdf")},
            data={
                "includeRawCitations": "1",
                "segmentSentences": "1",
                "teiCoordinates": ["s", "ref", "biblStruct", "formula", "figure"],
            },
        )
        response.raise_for_status()
    if not response.text.strip() or "[BAD_INPUT_DATA]" in response.text:
        raise ValueError("GROBID returned no usable TEI document.")
    return response.text


def prepare_pdf_source(
    pdf_path: Path,
    run_dir: Path,
    *,
    grobid_url: str,
    allow_pypdf_fallback: bool = False,
    progress: Callable[[str, str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    """Parse a PDF with GROBID, optionally allowing a visible pypdf downgrade."""
    run_dir.mkdir(parents=True, exist_ok=True)
    diagnostics: list[dict[str, Any]] = []
    local: MarkdownParseResult | None = None
    try:
        local = parse_pdf_locally(pdf_path.read_bytes())
    except Exception as exc:
        diagnostics.append(
            {
                "parser": "local_pypdf",
                "status": "unavailable",
                "message": (
                    "pypdf page extraction was unavailable "
                    f"({type(exc).__name__}); GROBID will parse independently."
                ),
            }
        )
    tei_xml = ""
    try:
        if progress:
            progress("parsing", "Parsing manuscript structure with GROBID.", None)
        tei_xml = request_grobid_fulltext(pdf_path, grobid_url)
        tei_path = run_dir / "grobid_fulltext.tei.xml"
        tei_path.write_text(tei_xml, encoding="utf-8")
        tei_path.chmod(0o600)
        parsed = parse_grobid_fulltext(
            tei_xml,
            physical_pages=local.pages if local is not None else [],
        )
        diagnostics.append(
            {
                "parser": "local_grobid_tei_hybrid",
                "status": "completed",
                "message": (
                    f"GROBID produced {len(parsed.content_list or [])} structured body "
                    f"blocks across {len(parsed.pages)} physical pages, "
                    f"{len(parsed.bibliography_entries or [])} structured references, "
                    f"and {len(parsed.citation_contexts or [])} inline citation contexts."
                ),
            }
        )
        return {
            "markdown": parsed.markdown,
            "pages": parsed.pages,
            "local_title": grobid_document_title(tei_xml),
            "local_authors": grobid_document_authors(tei_xml),
            "local_publication_year": grobid_document_year(tei_xml),
            "source_locations": parsed.source_locations or [],
            "bibliography_entries": parsed.bibliography_entries or [],
            "citation_contexts": parsed.citation_contexts or [],
            "provider": parsed.provider,
            "grobid_tei_file": tei_path.name,
            "diagnostics": diagnostics,
            "fallback_used": False,
        }
    except (httpx.HTTPError, etree.ParseError, OSError, ValueError) as exc:
        if local is None:
            raise ValueError(
                "Neither GROBID nor pypdf could produce reviewable manuscript text."
            ) from exc
        if not allow_pypdf_fallback:
            raise ValueError(
                "GROBID could not produce the required structured manuscript input. "
                "Restore GROBID or rerun with --allow-pypdf-fallback to accept a "
                "lower-quality, explicitly reported pypdf parse."
            ) from exc
        diagnostics.append(
            {
                "parser": "local_grobid_tei_hybrid",
                "status": "fallback",
                "message": (
                    f"GROBID body parsing was unavailable ({type(exc).__name__}); "
                    "used local pypdf text."
                ),
            }
        )
        if progress:
            progress(
                "parsing",
                (
                    "GROBID was unavailable; using the explicitly allowed "
                    "lower-quality pypdf fallback."
                ),
                {"parser": "local_pypdf", "fallback_used": True},
            )
        return {
            "markdown": local.markdown,
            "pages": local.pages,
            "local_title": "",
            "local_authors": [],
            "local_publication_year": None,
            "source_locations": [],
            "bibliography_entries": [],
            "citation_contexts": [],
            "provider": local.provider,
            "grobid_tei_file": None,
            "diagnostics": diagnostics,
            "fallback_used": True,
        }


def extract_local_title(pages: list[str]) -> str:
    if not pages:
        return ""
    lines = [line.strip() for line in str(pages[0] or "").splitlines() if line.strip()]
    title_lines: list[str] = []
    for line in lines[:16]:
        lowered = line.lower()
        if lowered.startswith(
            ("under review", "submitted to", "published as a conference paper", "arxiv:", "arxiv ")
        ):
            continue
        if lowered.startswith(("abstract", "keywords", "introduction")):
            break
        if title_lines and ("@" in line or any(mark in line for mark in ("*", "∗", "⋆", "†"))):
            break
        if title_lines and re.search(
            r"\b(university|institute|laboratory|school|company)\b", lowered
        ):
            break
        if len(re.findall(r"[A-Za-z0-9]+", line)) < 2:
            continue
        title_lines.append(line)
        if len(title_lines) == 3:
            break
    title = re.sub(r"\s+", " ", " ".join(title_lines)).strip(" .")
    return title if 6 <= len(title) <= 260 else ""
