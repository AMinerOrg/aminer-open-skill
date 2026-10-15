"""Client for the AMiner PDF OCR asynchronous open-platform API."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urljoin

import requests

DEFAULT_BASE_URL = "https://datacenter.aminer.cn/gateway/open_platform/api/v3"
SKILL_NAME = "aminer-pdf-ocr"
SKILL_VERSION = "3.0.1"
UPLOAD_PATH = "/paper/pdfocr/upload"
RESULT_PATH = "/paper/pdfocr/result"
TERMINAL_FAILURES = {"failed", "timeout", "queue_timeout", "expired"}
ACTIVE_STATUSES = {"preparing", "queued", "running"}


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


class PdfOcrApiError(RuntimeError):
    def __init__(self, message: str, *, http_status: int | None = None,
                 code: int | None = None, log_id: str | None = None):
        super().__init__(message)
        self.http_status = http_status
        self.code = code
        self.log_id = log_id


class PdfOcrQueueFullError(PdfOcrApiError):
    def __init__(self, retry_after_seconds: int, **kwargs: Any):
        super().__init__("PDF OCR queue is full", **kwargs)
        self.retry_after_seconds = max(1, int(retry_after_seconds))


class PdfOcrJobFailedError(PdfOcrApiError):
    def __init__(self, job_id: str, status: str, error_code: str | None,
                 error_message: str | None, **kwargs: Any):
        detail = error_message or error_code or "unknown error"
        super().__init__(f"PDF OCR job {job_id} ended with {status}: {detail}", **kwargs)
        self.job_id = job_id
        self.status = status
        self.error_code = error_code
        self.error_message = error_message


@dataclass(frozen=True)
class UploadResult:
    job_id: str
    status: str
    reused: bool
    code: int
    log_id: str | None


@dataclass(frozen=True)
class JobResult:
    job_id: str
    status: str
    is_finish: bool
    download_url: str | None
    url_expire_seconds: int | None
    error_code: str | None
    error_message: str | None
    code: int
    log_id: str | None


class PdfOcrClient:
    def __init__(self, token: str, *, base_url: str = DEFAULT_BASE_URL,
                 session: requests.Session | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        if not token.strip():
            raise ValueError("AMINER_API_KEY must not be empty")
        self.token = token.strip()
        self.base_url = base_url.rstrip("/") + "/"
        self.session = session or requests.Session()
        self.sleep = sleep
        self.clock = clock

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": self.token, **skill_identity_headers()}

    def _json(self, response: requests.Response) -> Mapping[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise PdfOcrApiError("PDF OCR returned invalid JSON", http_status=response.status_code) from exc
        if not isinstance(body, Mapping):
            raise PdfOcrApiError("PDF OCR returned a non-object response", http_status=response.status_code)
        return body

    def _check_gateway(self, response: requests.Response, body: Mapping[str, Any]) -> None:
        msg = body.get("msg")
        log_id = body.get("log_id")
        if msg == "该接口已停用":
            raise PdfOcrApiError("PDF OCR interface is disabled", http_status=response.status_code,
                                 code=body.get("code"), log_id=log_id)
        if response.status_code == 500:
            raise PdfOcrApiError("PDF OCR gateway returned a generic upstream error",
                                 http_status=500, code=body.get("code"), log_id=log_id)
        if response.status_code == 504:
            raise PdfOcrApiError("PDF OCR gateway timed out", http_status=504,
                                 code=body.get("code"), log_id=log_id)
        if response.status_code >= 400:
            raise PdfOcrApiError(f"PDF OCR HTTP error {response.status_code}",
                                 http_status=response.status_code, code=body.get("code"), log_id=log_id)

    def _request(self, method: str, path: str, *, timeout: float, **kwargs: Any) -> tuple[requests.Response, Mapping[str, Any]]:
        try:
            response = self.session.request(method, urljoin(self.base_url, path.lstrip("/")),
                                            headers=self._headers, timeout=timeout, **kwargs)
        except requests.RequestException as exc:
            raise PdfOcrApiError(f"PDF OCR request failed: {exc}") from exc
        body = self._json(response)
        self._check_gateway(response, body)
        return response, body

    @staticmethod
    def _data(body: Mapping[str, Any]) -> Mapping[str, Any]:
        data = body.get("data")
        if not isinstance(data, Mapping):
            raise PdfOcrApiError("PDF OCR response is missing data", code=body.get("code"), log_id=body.get("log_id"))
        return data

    def upload(self, file_path: Any, *, timeout: float = 60) -> UploadResult:
        with open(file_path, "rb") as fp:
            response, body = self._request(
                "POST", UPLOAD_PATH, timeout=timeout,
                files={"file": (getattr(file_path, "name", "document.pdf"), fp, "application/pdf")},
            )
        data = self._data(body)
        if data.get("queue_full") is True:
            raise PdfOcrQueueFullError(data.get("retry_after_seconds", 30),
                                       http_status=response.status_code, code=body.get("code"), log_id=body.get("log_id"))
        job_id = data.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            raise PdfOcrApiError("PDF OCR upload response has no job_id", http_status=response.status_code,
                                 code=body.get("code"), log_id=body.get("log_id"))
        return UploadResult(job_id, str(data.get("status", "queued")), bool(data.get("reused")),
                            int(body.get("code", 0)), body.get("log_id"))

    def result(self, job_id: str, *, timeout: float = 30) -> JobResult:
        response, body = self._request("GET", RESULT_PATH, timeout=timeout,
                                        params={"job_id": job_id})
        data = self._data(body)
        status = str(data.get("status", "unknown"))
        return JobResult(job_id=str(data.get("job_id", job_id)), status=status,
                         is_finish=bool(data.get("is_finish", status not in ACTIVE_STATUSES)),
                         download_url=data.get("download_url"),
                         url_expire_seconds=data.get("url_expire_seconds"),
                         error_code=data.get("error_code"), error_message=data.get("error_message"),
                         code=int(body.get("code", 0)), log_id=body.get("log_id"))

    def upload_with_retry(self, file_path: Any, *, timeout: float = 60,
                          max_attempts: int = 5) -> UploadResult:
        for attempt in range(max_attempts):
            try:
                return self.upload(file_path, timeout=timeout)
            except PdfOcrQueueFullError as exc:
                if attempt + 1 >= max_attempts:
                    raise
                self.sleep(exc.retry_after_seconds)
        raise AssertionError("unreachable")

    def wait_for_result(self, job_id: str, *, request_timeout: float = 30,
                        poll_timeout: float = 720, initial_delay: float = 0,
                        on_status: Callable[[JobResult], None] | None = None) -> JobResult:
        started = self.clock()
        if initial_delay:
            self.sleep(initial_delay)
        while True:
            result = self.result(job_id, timeout=request_timeout)
            if on_status:
                on_status(result)
            if result.status == "success" and result.is_finish and result.download_url:
                return result
            if result.status in TERMINAL_FAILURES:
                raise PdfOcrJobFailedError(result.job_id, result.status, result.error_code,
                                           result.error_message, code=result.code, log_id=result.log_id)
            if result.status == "unknown":
                raise PdfOcrApiError("PDF OCR job is unknown for this token", code=result.code, log_id=result.log_id)
            if self.clock() - started >= poll_timeout:
                raise PdfOcrApiError(f"PDF OCR polling exceeded {poll_timeout:g} seconds", log_id=result.log_id)
            elapsed = self.clock() - started
            self.sleep(2 if elapsed < 30 else 5)

    def download(self, url: str, target: Any, *, timeout: float = 120) -> None:
        try:
            from .url_guard import UrlGuardError, fetch_public_url
        except ImportError:
            from url_guard import UrlGuardError, fetch_public_url
        try:
            content = fetch_public_url(url, timeout=timeout, max_bytes=200 * 1024 * 1024)
        except (UrlGuardError, requests.RequestException) as exc:
            raise PdfOcrApiError(f"PDF OCR result download failed: {exc}") from exc
        with open(target, "wb") as fp:
            fp.write(content)
