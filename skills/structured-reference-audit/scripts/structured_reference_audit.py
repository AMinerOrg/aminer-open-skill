"""Build a GROBID-backed reference ledger and resolve entries through AMiner.

This is deliberately separate from AMiner's PDF upload verifier: parsing a PDF
and deciding whether a bibliographic work exists are different operations.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as etree

import requests


AMINER_BASE_URL = "https://datacenter.aminer.cn/gateway/open_platform"
SKILL_NAME = "structured-reference-audit"
SKILL_VERSION = "0.1.0"
DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/:a-z0-9]+", re.IGNORECASE)
ARXIV = re.compile(r"\b(?:arxiv\s*:\s*|arxiv\.org/(?:abs|pdf)/)(\d{4}\.\d{4,5}(?:v\d+)?)", re.IGNORECASE)
URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


def _text(node: etree.Element | None) -> str:
    return " ".join(node.itertext()).strip() if node is not None else ""


def _normal_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, _normal_title(left), _normal_title(right)).ratio()


def detect_skill_runtime() -> str:
    """Identify the host for gateway usage attribution."""
    explicit = (os.environ.get("AMINER_SKILL_RUNTIME") or "").strip().lower().replace("_", "-")
    if explicit:
        return explicit
    if os.environ.get("CLAUDE_CODE") or os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_PROJECT_DIR"):
        return "claude-code"
    if os.environ.get("CURSOR_TRACE_ID") or os.environ.get("CURSOR_AGENT"):
        return "cursor"
    if os.environ.get("CODEX_HOME") or os.environ.get("CODEX_CLI"):
        return "codex"
    if os.environ.get("OPENCLAW") or os.environ.get("OPENCLAW_HOME"):
        return "openclaw"
    return "unknown"


def _skill_md_version(fallback: str) -> str:
    path = Path(__file__).resolve().parents[1] / "SKILL.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return fallback
    if not text.startswith("---"):
        return fallback
    end = text.find("\n---", 3)
    if end < 0:
        return fallback
    for line in text[3:end].splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip() == "version":
            version = value.strip().strip("'\"")
            if version:
                return version
    return fallback


def skill_identity_headers() -> dict[str, str]:
    return {
        "X-Platform": detect_skill_runtime(),
        "X-Skill-Name": SKILL_NAME,
        "X-Skill-Version": _skill_md_version(SKILL_VERSION),
    }


def _pages(node: etree.Element) -> list[int]:
    values: list[int] = []
    for coords in node.attrib.get("coords", "").split(";"):
        page = coords.partition(",")[0]
        if page.isdigit():
            values.append(int(page))
    return values or [1]


def _record(index: int, node: etree.Element) -> dict[str, Any]:
    title_node = node.find(".//{*}analytic/{*}title[@type='main']")
    if title_node is None:
        title_node = node.find(".//{*}analytic/{*}title")
    if title_node is None:
        title_node = node.find(".//{*}monogr/{*}title[@level='m']")
    title = _text(title_node) or None
    raw_node = node.find(".//{*}note[@type='raw_reference']")
    raw = _text(raw_node) or _text(node)
    doi = None
    arxiv_id = None
    urls: list[str] = []
    for identifier in node.findall(".//{*}idno"):
        value = _text(identifier).strip().rstrip(".,;)")
        kind = identifier.attrib.get("type", "").lower()
        if kind == "doi" or DOI.fullmatch(value):
            doi = doi or value
        elif kind in {"arxiv", "arxivid"}:
            arxiv_id = arxiv_id or value.removeprefix("arXiv:").strip()
        elif value.startswith(("http://", "https://")):
            urls.append(value)
    urls.extend(URL.findall(raw))
    urls = list(dict.fromkeys(value.rstrip(".,;)") for value in urls))[:3]
    issues: list[str] = []
    if len(raw) < 25:
        issues.append("record_too_short")
    if not title and not doi and not arxiv_id:
        issues.append("no_title_or_persistent_identifier")
    pages = _pages(node)
    return {
        "id": f"R{index}",
        "raw": raw,
        "candidate_title": title,
        "doi": doi,
        "arxiv_id": arxiv_id,
        "urls": urls,
        "anchor": {"page_start": min(pages), "page_end": max(pages), "quote": raw[:600]},
        "parse_confidence": "high" if title else ("medium" if doi or arxiv_id else "low"),
        "parse_issues": issues,
        "resolution_eligible": bool(title or doi or arxiv_id),
        "parser_reference_id": node.attrib.get("{http://www.w3.org/XML/1998/namespace}id"),
    }


def build_ledger(tei_xml: str) -> dict[str, Any]:
    root = etree.fromstring(tei_xml)
    bibliography = root.find(".//{*}listBibl")
    nodes = bibliography.findall("{*}biblStruct") if bibliography is not None else []
    records = [_record(index, node) for index, node in enumerate(nodes, start=1)]
    eligible = [record for record in records if record["resolution_eligible"]]
    identifiable = sum(bool(record["candidate_title"] or record["doi"] or record["arxiv_id"]) for record in records)
    low_confidence = sum(record["parse_confidence"] == "low" for record in records)
    reasons: list[str] = []
    status = "ready_for_resolution"
    if bibliography is None:
        status = "references_not_found"
        reasons.append("GROBID TEI contains no bibliography list.")
    elif len(eligible) < 3:
        status = "parse_quality_insufficient"
        reasons.append("Fewer than three entries expose a title, DOI, or arXiv identifier.")
    elif low_confidence / max(len(records), 1) > 0.15:
        status = "parse_quality_insufficient"
        reasons.append("More than 15% of parsed entries have no recoverable identity field.")
    return {
        "schema_version": "1.0",
        "status": status,
        "parser": "grobid_tei",
        "records": records,
        "summary": {
            "records_segmented": len(records),
            "records_eligible_for_resolution": len(eligible),
            "records_with_title_or_identifier": identifiable,
            "low_confidence_records": low_confidence,
            "gate_reasons": reasons,
        },
    }


def fetch_tei(pdf: Path, grobid_url: str, timeout: int) -> str:
    response = requests.post(
        f"{grobid_url.rstrip('/')}/api/processFulltextDocument",
        files={"input": (pdf.name, pdf.read_bytes(), "application/pdf")},
        data={"includeRawCitations": "1", "teiCoordinates": "biblStruct"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.text


def _aminer_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        rows = data.get("data") or data.get("items") or data.get("result") or []
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    return []


def _first_author(row: dict[str, Any]) -> str | None:
    authors = row.get("authors")
    if not isinstance(authors, list) or not authors:
        return str(row.get("first_author") or "").strip() or None
    first = authors[0]
    if isinstance(first, dict):
        return str(first.get("name") or first.get("display_name") or "").strip() or None
    return str(first).strip() or None


def resolve_records(ledger: dict[str, Any], token: str, timeout: int) -> None:
    headers = {"Authorization": token, **skill_identity_headers()}
    for record in ledger["records"]:
        if not record["resolution_eligible"]:
            record["status"] = "needs_human_review"
            record["status_reason"] = "The parser did not recover a title or persistent identifier."
            continue
        title = str(record.get("candidate_title") or "").strip()
        if not title:
            record["status"] = "needs_human_review"
            record["status_reason"] = "Identifier-only matching is not implemented by this skill version."
            continue
        try:
            response = requests.get(
                f"{AMINER_BASE_URL}/api/paper/search",
                params={"title": title, "page": 0, "size": 5},
                headers=headers,
                timeout=timeout,
            )
            response.raise_for_status()
            rows = _aminer_rows(response.json())
        except (requests.RequestException, ValueError) as exc:
            record["status"] = "needs_human_review"
            record["status_reason"] = f"AMiner search was unavailable: {type(exc).__name__}."
            continue
        candidates = []
        for row in rows:
            candidate_title = str(row.get("title") or row.get("name") or "").strip()
            if candidate_title:
                candidates.append((round(_similarity(title, candidate_title), 3), row, candidate_title))
        best = max(candidates, key=lambda item: item[0], default=None)
        if not best:
            record["status"] = "not_found_in_aminer"
            record["status_reason"] = "AMiner returned no title candidate for this parsed entry."
            continue
        score, row, candidate_title = best
        record["top_match"] = {
            "id": row.get("id"),
            "title": candidate_title,
            "first_author": _first_author(row),
            "year": row.get("year"),
        }
        record["match_score"] = score
        if score >= 0.90:
            record["status"] = "verified_exists"
            record["status_reason"] = "AMiner returned a high-similarity title match."
        else:
            record["status"] = "needs_human_review"
            record["status_reason"] = "AMiner returned only a partial title match."


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a GROBID-backed reference ledger and resolve entries through AMiner.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--pdf", type=Path, help="PDF to parse through a running GROBID service.")
    source.add_argument("--tei", type=Path, help="Existing GROBID TEI XML to parse.")
    parser.add_argument("--grobid-url", default=os.environ.get("GROBID_URL", "http://127.0.0.1:8070"))
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--skip-resolve", action="store_true", help="Only create the parser ledger; do not call AMiner.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        tei_xml = args.tei.read_text(encoding="utf-8") if args.tei else fetch_tei(args.pdf, args.grobid_url, args.timeout)
        ledger = build_ledger(tei_xml)
    except (OSError, etree.ParseError, requests.RequestException) as exc:
        print(f"ERROR: GROBID parsing failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if not args.skip_resolve and ledger["status"] == "ready_for_resolution":
        token = os.environ.get("AMINER_API_KEY", "").strip()
        if not token:
            print("ERROR: AMINER_API_KEY is required unless --skip-resolve is used.", file=sys.stderr)
            return 2
        resolve_records(ledger, token, args.timeout)
    elif not args.skip_resolve:
        ledger["resolution_status"] = "not_started_due_to_parse_gate"

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "status": ledger["status"], "summary": ledger["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
