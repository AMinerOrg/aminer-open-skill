#!/usr/bin/env python3
"""Fetch one bounded public text source for SOTA research.

This helper is intentionally narrower than curl: it reads one public HTTP(S)
URL, rejects PDFs and oversized responses, writes readable text locally, and
applies per-request safety limits without imposing an aggregate research quota.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import socket
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


DEFAULT_TIMEOUT_SECONDS = 20
HARD_TIMEOUT_SECONDS = 30
DEFAULT_MAX_BYTES = 20 * 1024 * 1024
HARD_MAX_BYTES = 50 * 1024 * 1024
USER_AGENT = "sota-finder-bounded-source-reader/1.0"


class FetchSourceError(RuntimeError):
    """Raised when a source cannot be read within the bounded policy."""


class FetchConfig:
    def __init__(
        self,
        *,
        timeout_seconds: int,
        max_bytes: int,
        output_dir: Path,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.output_dir = output_dir

    @classmethod
    def from_environment(cls, cwd: Path | None = None) -> "FetchConfig":
        root = (cwd or Path.cwd()).resolve()
        return cls(
            timeout_seconds=_bounded_env_int(
                "SOTA_FINDER_FETCH_TIMEOUT_SECONDS",
                DEFAULT_TIMEOUT_SECONDS,
                1,
                HARD_TIMEOUT_SECONDS,
            ),
            max_bytes=_bounded_env_int(
                "SOTA_FINDER_FETCH_MAX_BYTES", DEFAULT_MAX_BYTES, 1024, HARD_MAX_BYTES
            ),
            output_dir=_env_path(
                "SOTA_FINDER_FETCH_OUTPUT_DIR", root / "source-fetches", root
            ),
        )


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise FetchSourceError(f"{name} must be an integer") from exc
    return max(minimum, min(value, maximum))


def _env_path(name: str, default: Path, cwd: Path) -> Path:
    raw = os.environ.get(name)
    if not raw:
        return default
    path = Path(raw).expanduser()
    return path if path.is_absolute() else cwd / path


def _is_public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_public_url(url: str) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise FetchSourceError("source URL must use http or https")
    if not parsed.hostname or parsed.username or parsed.password:
        raise FetchSourceError("source URL must name a public host without credentials")
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(
                parsed.hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        }
    except OSError as exc:
        raise FetchSourceError(f"could not resolve source host: {exc}") from exc
    if not addresses or any(not _is_public_address(address) for address in addresses):
        raise FetchSourceError("source URL must resolve only to public addresses")
    return parsed


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    max_redirections = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ReadableHTMLParser(HTMLParser):
    BLOCK_TAGS = {
        "address", "article", "aside", "blockquote", "br", "caption", "div",
        "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "li",
        "main", "nav", "p", "section", "table", "tbody", "tfoot", "thead", "tr",
    }
    IGNORED_TAGS = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0
        self.cell_index = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self.IGNORED_TAGS:
            self.ignored_depth += 1
            return
        if self.ignored_depth:
            return
        if tag == "tr":
            self.parts.append("\n")
            self.cell_index = 0
        elif tag in {"td", "th"}:
            if self.cell_index:
                self.parts.append("\t")
            self.cell_index += 1
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.IGNORED_TAGS:
            if self.ignored_depth:
                self.ignored_depth -= 1
            return
        if self.ignored_depth:
            return
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.ignored_depth:
            return
        text = " ".join(data.split())
        if text:
            self.parts.append(text)

    def text(self) -> str:
        raw = "".join(self.parts)
        lines: list[str] = []
        for line in raw.splitlines():
            cells = [" ".join(cell.split()) for cell in line.split("\t")]
            cleaned = "\t".join(cell for cell in cells if cell)
            if cleaned and (not lines or cleaned != lines[-1]):
                lines.append(cleaned)
        return "\n".join(lines).strip()


def _content_type(headers: Any) -> str:
    if hasattr(headers, "get_content_type"):
        return str(headers.get_content_type()).lower()
    return str(headers.get("Content-Type", "")).split(";", 1)[0].strip().lower()


def _charset(headers: Any) -> str:
    if hasattr(headers, "get_content_charset"):
        return headers.get_content_charset() or "utf-8"
    return "utf-8"


def _is_text_content(content_type: str, final_url: str) -> bool:
    if content_type.startswith("text/"):
        return True
    if content_type in {
        "application/json",
        "application/xml",
        "application/xhtml+xml",
        "application/csv",
    } or content_type.endswith("+json") or content_type.endswith("+xml"):
        return True
    suffix = Path(urllib.parse.urlparse(final_url).path).suffix.lower()
    return content_type in {"", "application/octet-stream"} and suffix in {
        ".csv", ".htm", ".html", ".json", ".md", ".txt", ".xml",
    }


def _to_readable_text(body: bytes, content_type: str, charset: str) -> str:
    try:
        decoded = body.decode(charset, errors="replace")
    except LookupError:
        decoded = body.decode("utf-8", errors="replace")
    if content_type == "application/json" or content_type.endswith("+json"):
        try:
            return json.dumps(json.loads(decoded), ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            return decoded
    if content_type in {"text/html", "application/xhtml+xml"}:
        parser = ReadableHTMLParser()
        parser.feed(decoded)
        parser.close()
        return parser.text()
    return decoded.strip()


def fetch_source(url: str, config: FetchConfig) -> dict[str, Any]:
    validate_public_url(url)
    parsed = urllib.parse.urlparse(url)
    if parsed.path.lower().endswith(".pdf"):
        raise FetchSourceError("PDF downloads are not supported by the bounded source reader")

    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain,application/json,text/csv,application/xml;q=0.9,*/*;q=0.1"},
    )
    opener = urllib.request.build_opener(SafeRedirectHandler())
    try:
        with opener.open(request, timeout=config.timeout_seconds) as response:
            final_url = response.geturl()
            validate_public_url(final_url)
            content_type = _content_type(response.headers)
            if content_type == "application/pdf":
                raise FetchSourceError(
                    "PDF downloads are not supported by the bounded source reader"
                )
            if not _is_text_content(content_type, final_url):
                raise FetchSourceError(
                    f"unsupported non-text content type: {content_type or 'unknown'}"
                )
            body = response.read(config.max_bytes + 1)
    except FetchSourceError:
        raise
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        raise FetchSourceError(f"source request failed: {exc}") from exc

    if len(body) > config.max_bytes:
        raise FetchSourceError(
            f"source response exceeds the {config.max_bytes}-byte limit"
        )
    readable = _to_readable_text(body, content_type, _charset(response.headers))
    if not readable:
        raise FetchSourceError("source response did not contain readable text")

    config.output_dir.mkdir(parents=True, exist_ok=True)
    output_handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix="source-",
        suffix=".txt",
        dir=config.output_dir,
        delete=False,
    )
    output_path = Path(output_handle.name)
    header = (
        f"Source URL: {url}\n"
        f"Final URL: {final_url}\n"
        f"Content-Type: {content_type or 'unknown'}\n"
        f"Fetched UTC: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n"
        "\n--- Content ---\n"
    )
    with output_handle:
        output_handle.write(header + readable + "\n")
    return {
        "status": "ok",
        "source_url": url,
        "final_url": final_url,
        "content_type": content_type or "unknown",
        "bytes_read": len(body),
        "output_path": str(output_path.resolve()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch one already-discovered public text source within strict limits."
    )
    parser.add_argument("url", help="Official or primary public HTTP(S) URL")
    args = parser.parse_args(argv)
    try:
        result = fetch_source(args.url, FetchConfig.from_environment())
    except FetchSourceError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
