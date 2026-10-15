"""Upload a PDF to the pdf-citation-verifier service and poll for the result.

This is a thin HTTP client around the AMiner pdf-citation-verifier API:
    POST /api/v3/paper/citation/verify/upload
    GET  /api/v3/paper/citation/result?job_id=<job_id>

Both endpoints return the AMiner gateway envelope:
    {"code": 200, "success": true, "msg": "", "data": <obj or list>, "log_id": "..."}

`upload`  -> data is an object: {"job_id": "verify_..."}
`result`  -> data is a list with one element: [{"is_finish": bool, ...}]

It reads the auth token from `AMINER_API_KEY` and the (optional) base URL
override from `PDF_CITATION_VERIFIER_BASE_URL`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests

DEFAULT_BASE_URL = "https://datacenter.aminer.cn/gateway/open_platform"
SKILL_NAME = "pdf-citation-verifier"
SKILL_VERSION = "1.0.0"
UPLOAD_PATH = "/api/v3/paper/citation/verify/upload"
RESULT_PATH = "/api/v3/paper/citation/result"
JOB_ID_PATTERN = re.compile(r"^verify_\d{8}T\d{6}Z_[0-9a-f]{8}$")


def _resolve_base_url() -> str:
    return os.environ.get("PDF_CITATION_VERIFIER_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def detect_skill_runtime() -> str:
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
        key, sep, value = line.partition(":")
        if sep and key.strip() == "version":
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


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": api_key, **skill_identity_headers()}


def _unwrap_gateway(body: dict[str, Any], *, context: str) -> Any:
    """Validate the gateway envelope and return its `data` payload."""
    if not isinstance(body, dict):
        raise SystemExit(f"ERROR: {context} returned non-object body: {body!r}")
    code = body.get("code")
    success = body.get("success")
    if code != 200 or success is not True:
        msg = body.get("msg") or body.get("message") or ""
        raise SystemExit(f"ERROR: {context} returned code={code} success={success} msg={msg!r}")
    if "data" not in body:
        raise SystemExit(f"ERROR: {context} response missing 'data' field: {body!r}")
    return body["data"]


def upload_pdf(
    pdf_path: Path,
    *,
    api_key: str,
    base_url: str,
    max_refs: int,
    strict: bool,
    request_timeout: int,
) -> str:
    url = f"{base_url}{UPLOAD_PATH}"
    with pdf_path.open("rb") as fp:
        files = {"file": (pdf_path.name, fp, "application/pdf")}
        data = {"max_refs": str(max_refs), "strict": "true" if strict else "false"}
        resp = requests.post(
            url,
            headers=_auth_headers(api_key),
            files=files,
            data=data,
            timeout=request_timeout,
        )

    if resp.status_code == 401:
        raise SystemExit("ERROR: 401 unauthorized — check AMINER_API_KEY.")
    if resp.status_code == 413:
        raise SystemExit("ERROR: 413 PDF too large (server cap, default 50 MB).")
    if resp.status_code == 429:
        raise SystemExit("ERROR: 429 too many active jobs for this user (server cap).")
    if resp.status_code >= 400:
        raise SystemExit(f"ERROR: upload failed with HTTP {resp.status_code}: {resp.text[:300]}")

    payload = _unwrap_gateway(resp.json(), context="upload")
    if not isinstance(payload, dict):
        raise SystemExit(f"ERROR: upload data is not an object: {payload!r}")

    job_id = payload.get("job_id")
    if not isinstance(job_id, str) or not JOB_ID_PATTERN.match(job_id):
        raise SystemExit(f"ERROR: server returned an invalid job_id: {job_id!r}")
    return job_id


def fetch_result(
    job_id: str,
    *,
    api_key: str,
    base_url: str,
    request_timeout: int,
) -> dict[str, Any]:
    url = f"{base_url}{RESULT_PATH}"
    resp = requests.get(
        url,
        headers=_auth_headers(api_key),
        params={"job_id": job_id},
        timeout=request_timeout,
    )
    if resp.status_code == 429:
        raise SystemExit(
            "ERROR: 429 too many active jobs for this user (server cap). "
            "Wait for prior jobs to finish before polling again."
        )
    if resp.status_code >= 400:
        raise SystemExit(
            f"ERROR: polling failed with HTTP {resp.status_code}: {resp.text[:300]}"
        )

    payload = _unwrap_gateway(resp.json(), context="result")
    if isinstance(payload, list):
        if not payload:
            raise SystemExit(f"ERROR: result data list is empty for job {job_id}")
        record = payload[0]
    elif isinstance(payload, dict):
        record = payload
    else:
        raise SystemExit(f"ERROR: result data has unexpected type: {payload!r}")

    if not isinstance(record, dict):
        raise SystemExit(f"ERROR: result record is not an object: {record!r}")
    return record


def poll_result(
    job_id: str,
    *,
    api_key: str,
    base_url: str,
    poll_interval: float,
    overall_timeout: int,
    request_timeout: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + overall_timeout
    last_status: str | None = None
    while True:
        record = fetch_result(
            job_id,
            api_key=api_key,
            base_url=base_url,
            request_timeout=request_timeout,
        )
        if record.get("is_finish") is True:
            return record

        status = str(record.get("status", "running"))
        if status != last_status:
            print(f"[poll] {job_id}: {status}", file=sys.stderr)
            last_status = status

        if time.monotonic() >= deadline:
            raise SystemExit(
                f"ERROR: timed out after {overall_timeout}s waiting for job {job_id}. "
                f"Last status: {status}. You can keep polling manually with --no-wait + --job-id."
            )
        time.sleep(poll_interval)


def _enrich_with_details(payload: dict[str, Any], *, request_timeout: int) -> None:
    """If urls.result is present, GET the detailed JSON and inline it under payload['details'].

    OSS URLs expire in ~5 minutes, so we fetch immediately. Failure is logged
    but never fatal — the caller still has the summary in `payload`.
    """
    result_url = (payload.get("urls") or {}).get("result")
    if not result_url:
        return
    try:
        resp = requests.get(result_url, timeout=request_timeout)
        resp.raise_for_status()
        payload["details"] = resp.json()
        print(f"[details] inlined {len(resp.content)} bytes from urls.result", file=sys.stderr)
    except Exception as exc:
        payload["details_fetch_error"] = f"{type(exc).__name__}: {exc}"
        print(f"[details] WARN: could not fetch urls.result: {exc}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Submit a PDF to pdf-citation-verifier and print the verification result."
    )
    parser.add_argument(
        "--pdf",
        help="Path to the PDF to verify. Required unless --job-id is given.",
    )
    parser.add_argument(
        "--job-id",
        help="Skip upload and only fetch the result for an existing job_id.",
    )
    parser.add_argument(
        "--max-refs",
        type=int,
        default=50,
        help="Max references to verify (1-100, default 50).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Enable stricter FAKE judgement on partial matches.",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Submit the job and print job_id without polling.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Overall polling timeout in seconds (default 600).",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=5.0,
        help="Polling interval in seconds (default 5).",
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=120,
        help="Per-HTTP-request timeout in seconds (default 120).",
    )
    parser.add_argument(
        "--output",
        help="Optional path to write the final JSON response.",
    )
    args = parser.parse_args()

    api_key = os.environ.get("AMINER_API_KEY")
    if not api_key:
        print(
            "ERROR: AMINER_API_KEY is not set. Get a token from https://open.aminer.cn and "
            "export it before running this skill.",
            file=sys.stderr,
        )
        return 2

    if not (1 <= args.max_refs <= 100):
        print("ERROR: --max-refs must be between 1 and 100.", file=sys.stderr)
        return 2

    if not args.pdf and not args.job_id:
        print("ERROR: provide either --pdf (to upload) or --job-id (to fetch).", file=sys.stderr)
        return 2

    base_url = _resolve_base_url()

    if args.job_id:
        if not JOB_ID_PATTERN.match(args.job_id):
            print(f"ERROR: --job-id format is invalid: {args.job_id!r}", file=sys.stderr)
            return 2
        job_id = args.job_id
        print(f"[fetch] using existing job_id={job_id}", file=sys.stderr)
    else:
        pdf_path = Path(args.pdf).expanduser()
        if not pdf_path.is_file():
            print(f"ERROR: PDF not found: {pdf_path}", file=sys.stderr)
            return 2
        if pdf_path.suffix.lower() != ".pdf":
            print(f"ERROR: input must be a .pdf file: {pdf_path}", file=sys.stderr)
            return 2

        job_id = upload_pdf(
            pdf_path,
            api_key=api_key,
            base_url=base_url,
            max_refs=args.max_refs,
            strict=args.strict,
            request_timeout=args.request_timeout,
        )
        print(f"[upload] accepted job_id={job_id}", file=sys.stderr)

    if args.no_wait:
        if args.job_id:
            # --job-id + --no-wait: single status check, return immediately regardless of is_finish
            payload = fetch_result(
                job_id,
                api_key=api_key,
                base_url=base_url,
                request_timeout=args.request_timeout,
            )
            payload.setdefault("job_id", job_id)
        else:
            # --pdf + --no-wait: just uploaded, return job_id without polling
            payload: dict[str, Any] = {"job_id": job_id, "is_finish": False, "status": "submitted"}
    else:
        payload = poll_result(
            job_id,
            api_key=api_key,
            base_url=base_url,
            poll_interval=args.poll_interval,
            overall_timeout=args.timeout,
            request_timeout=args.request_timeout,
        )
        payload.setdefault("job_id", job_id)

    if payload.get("is_finish") is True:
        _enrich_with_details(payload, request_timeout=args.request_timeout)

    if args.output:
        out_path = Path(args.output).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[output] wrote {out_path}", file=sys.stderr)

    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
