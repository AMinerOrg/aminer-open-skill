"""Local validation for PDFs accepted by the PDF OCR open API."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MAX_BYTES = 10 * 1024 * 1024
MIN_PAGES = 1
MAX_PAGES = 30


class PdfValidationError(ValueError):
    pass


@dataclass(frozen=True)
class PdfInfo:
    path: Path
    size_bytes: int
    pages: int
    encrypted: bool


def validate_pdf(path: Path) -> PdfInfo:
    path = Path(path)
    if not path.is_file():
        raise PdfValidationError(f"PDF file not found: {path}")
    size = path.stat().st_size
    if size == 0:
        raise PdfValidationError("PDF file is empty")
    with path.open("rb") as fp:
        if fp.read(5) != b"%PDF-":
            raise PdfValidationError("file does not start with the %PDF- signature")
    if size > MAX_BYTES:
        raise PdfValidationError(f"PDF is too large: {size} bytes (limit {MAX_BYTES})")
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path), strict=False)
        encrypted = bool(reader.is_encrypted)
        if encrypted:
            raise PdfValidationError("encrypted PDFs are not supported")
        pages = len(reader.pages)
    except PdfValidationError:
        raise
    except Exception as exc:
        raise PdfValidationError(f"PDF cannot be parsed: {exc}") from exc
    if not MIN_PAGES <= pages <= MAX_PAGES:
        raise PdfValidationError(f"PDF must contain 1-30 pages; found {pages}")
    return PdfInfo(path, size, pages, encrypted)
