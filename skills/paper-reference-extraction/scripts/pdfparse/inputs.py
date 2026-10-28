"""Turn a paper file into a ParsedDocument: PDF / Word (.docx) / plain text / Markdown."""

from __future__ import annotations

import re
import zipfile
from html import unescape
from pathlib import Path

from .models import ParsedDocument
from .parser import parse_pdf, parse_text

SUPPORTED = (".pdf", ".docx", ".txt", ".md")


def parse_input(path: Path, title: str = "") -> ParsedDocument:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        doc = parse_pdf(path)
    elif suffix == ".docx":
        doc = parse_text(docx_to_text(path), title=title)
        doc.source = "docx"
    else:
        doc = parse_text(path.read_text(encoding="utf-8", errors="replace"), title=title)
    if title and (doc.source != "pdf" or not doc.title):
        doc.title = title
    return doc


def docx_to_text(path: Path) -> str:
    """No python-docx needed: read document.xml directly; superscript numbers (a common Word citation format) become [n]."""
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    paras = []
    for p in re.findall(r"<w:p[ >].*?</w:p>", xml, flags=re.S):
        parts = []
        for run in re.findall(r"<w:r[ >].*?</w:r>", p, flags=re.S):
            text = "".join(unescape(t) for t in re.findall(r"<w:t(?: [^>]*)?>(.*?)</w:t>", run, flags=re.S))
            if not text:
                continue
            if 'w:val="superscript"' in run and re.fullmatch(r"\s*\[?\d{1,3}(?:[,，\-–]\d{1,3})*\]?\s*", text):
                text = "[" + text.strip().strip("[]") + "]"
            parts.append(text)
        line = "".join(parts).strip()
        if line:
            paras.append(line)
    return "\n\n".join(paras)
