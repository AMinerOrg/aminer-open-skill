"""CLI orchestration for the AMiner PDF OCR open-platform API."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

try:
    from .artifacts import extract_result, write_metadata
    from .pdfocr_client import PdfOcrApiError, PdfOcrClient
    from .pdf_validation import MAX_BYTES, validate_pdf
    from .url_guard import UrlGuardError, fetch_public_url
except ImportError:
    from artifacts import extract_result, write_metadata
    from pdfocr_client import PdfOcrApiError, PdfOcrClient
    from pdf_validation import MAX_BYTES, validate_pdf
    from url_guard import UrlGuardError, fetch_public_url

DEFAULT_BASE_URL = "https://datacenter.aminer.cn/gateway/open_platform/api/v3"
CONSOLE_URL = "https://open.aminer.cn/open/board?tab=control"
URL_PREFIXES = ("http://", "https://")


def safe_stem(name: str) -> str:
    base = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].split("?", 1)[0]
    stem = Path(base).stem or "input"
    return "".join(ch if ch.isascii() and (ch.isalnum() or ch in "._-") else "_" for ch in stem).strip("._") or "input"


def _download_input(url: str, timeout: float) -> Path:
    try:
        content = fetch_public_url(url, timeout=timeout, max_bytes=MAX_BYTES)
    except (UrlGuardError, requests.RequestException) as exc:
        raise SystemExit(f"ERROR: failed to download input URL: {exc}") from exc
    name = Path(urlparse(url).path).name or "download.pdf"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    fd, raw = tempfile.mkstemp(prefix="pdfocr_", suffix=".pdf")
    os.close(fd)
    path = Path(raw).with_name(name)
    Path(raw).replace(path)
    path.write_bytes(content)
    return path


def resolve_token() -> str:
    token = (os.environ.get("AMINER_API_KEY") or os.environ.get("OPEN_PLATFORM_TOKEN") or "").strip()
    if not token:
        raise SystemExit(
            "ERROR: AMINER_API_KEY is not set. Get a token from "
            f"{CONSOLE_URL} and export AMINER_API_KEY=<token>."
        )
    return token


def run_ocr(args: argparse.Namespace) -> int:
    token = resolve_token()
    temp_path: Path | None = None
    source = args.input
    try:
        if source.lower().startswith(URL_PREFIXES):
            temp_path = _download_input(source, min(args.request_timeout, 120))
            input_path = temp_path
        else:
            input_path = Path(source).expanduser()
        info = validate_pdf(input_path)
        output_dir = Path(args.output_dir).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        client = PdfOcrClient(token, base_url=os.environ.get("PDFOCR_OPEN_API_BASE_URL", DEFAULT_BASE_URL))
        started = time.monotonic()
        upload = client.upload_with_retry(input_path, timeout=args.request_timeout,
                                          max_attempts=args.max_upload_attempts)
        result = client.wait_for_result(upload.job_id, request_timeout=args.request_timeout,
                                        poll_timeout=args.poll_timeout,
                                        on_status=lambda item: print(f"[pdfocr] status={item.status}", file=sys.stderr))
        zip_path = output_dir / "pdfocr_result.zip"
        client.download(result.download_url or "", zip_path, timeout=args.request_timeout)
        artifacts = extract_result(zip_path, output_dir, save_images=not args.no_save_images)
        write_metadata(output_dir / "response.json", upload=upload, result=result, artifacts=artifacts)
        summary = {"engine": "pdfocr-open-api", "status": "ok", "elapsed_seconds": round(time.monotonic() - started, 2),
                   "job_id": upload.job_id, "pages": info.pages, "output_dir": str(output_dir), "artifacts": artifacts}
        if args.output:
            Path(args.output).expanduser().write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        json.dump(summary, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    except (PdfOcrApiError, ValueError, OSError) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Parse a PDF through the AMiner PDF OCR open API.")
    parser.add_argument("--input", required=True, help="Local PDF path or http(s) PDF URL.")
    parser.add_argument("--output-dir", default=None, help="Output directory for Markdown, ZIP, images and metadata.")
    parser.add_argument("--request-timeout", type=float, default=60, help="Timeout for each HTTP request in seconds.")
    parser.add_argument("--poll-timeout", type=float, default=720, help="Maximum polling budget in seconds.")
    parser.add_argument("--max-upload-attempts", type=int, default=5, help="Maximum upload attempts when the queue is full.")
    parser.add_argument("--no-save-images", action="store_true", help="Do not extract images from the result ZIP.")
    parser.add_argument("--output", help="Optional path for the summary JSON.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.output_dir is None:
        args.output_dir = str(Path("outputs/aminer-pdf-ocr") / safe_stem(args.input))
    return run_ocr(args)


if __name__ == "__main__":
    sys.exit(main())
