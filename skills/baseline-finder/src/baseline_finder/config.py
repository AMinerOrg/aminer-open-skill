"""Explicit model/runtime configuration for the standalone audit."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from openai import OpenAI

from .errors import BaselineAuditError
from .global_concurrency import GlobalModelConcurrencyGate


MODEL_PROFILES = ("deepseek", "glm", "glm53", "glm53flash", "gpt")


def _env(*names: str, default: str | None = None) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value is not None and value.strip():
            return value.strip()
    return default


def load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE assignments without evaluating shell syntax."""
    normalized = path.expanduser().resolve()
    if not normalized.is_file():
        raise BaselineAuditError(f"Environment file not found: {normalized}")
    for line_number, raw_line in enumerate(
        normalized.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise BaselineAuditError(
                f"Invalid environment assignment at {normalized}:{line_number}"
            )
        name, value = line.split("=", 1)
        name = name.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise BaselineAuditError(
                f"Invalid environment name at {normalized}:{line_number}"
            )
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(name, value)


@dataclass(frozen=True)
class ModelRuntime:
    profile: str
    label: str
    model: str
    api_key: str
    base_url: str
    thinking_effort: str | None = None


def resolve_model_runtime(profile: str) -> ModelRuntime:
    """Resolve one supported OpenAI-compatible profile from environment values."""
    selected = profile.strip().lower()
    if selected == "deepseek":
        runtime = ModelRuntime(
            profile="deepseek",
            label="DeepSeek Chat",
            model=_env("DEEPSEEK_MODEL", default="deepseek-chat") or "deepseek-chat",
            api_key=_env("DEEPSEEK_API_KEY") or "",
            base_url=_env(
                "DEEPSEEK_BASE_URL",
                default="https://api.deepseek.com",
            ) or "",
        )
    elif selected == "glm":
        runtime = ModelRuntime(
            profile="glm",
            label="GLM 5.2",
            model=_env("GLM_MODEL", default="glm-5.2") or "glm-5.2",
            api_key=_env("GLM_API_KEY") or "",
            base_url=_env(
                "GLM_BASE_URL",
                default="https://open.bigmodel.cn/api/paas/v4",
            ) or "",
        )
    elif selected in {"glm53", "glm53flash"}:
        effort = (_env("GLM53_THINKING_EFFORT", default="low") or "low").lower()
        if effort not in {"low", "high", "max"}:
            raise BaselineAuditError(
                "GLM53_THINKING_EFFORT must be low, high, or max."
            )
        is_flash = selected == "glm53flash"
        runtime = ModelRuntime(
            profile=selected,
            label=(
                f"GLM 5.3 Flash ({effort} reasoning)"
                if is_flash else f"GLM 5.3 ({effort} reasoning)"
            ),
            model=_env(
                "GLM53_FLASH_MODEL" if is_flash else "GLM53_MODEL",
                default="glm-5.3-flash" if is_flash else "glm-5.3",
            ) or ("glm-5.3-flash" if is_flash else "glm-5.3"),
            api_key=_env("GLM_API_KEY") or "",
            base_url=_env(
                "GLM_BASE_URL",
                default="https://open.bigmodel.cn/api/paas/v4",
            ) or "",
            thinking_effort=effort,
        )
    elif selected == "gpt":
        runtime = ModelRuntime(
            profile="gpt",
            label="GPT",
            model=_env("GPT_MODEL", default="gpt-5.6-sol") or "gpt-5.6-sol",
            api_key=_env("GPT_API_KEY") or "",
            base_url=_env("GPT_BASE_URL") or "",
        )
    else:
        raise BaselineAuditError(f"Unknown model profile: {profile}")
    if not runtime.api_key or not runtime.base_url:
        raise BaselineAuditError(
            f"Model profile {runtime.profile} is not configured with an API key and base URL."
        )
    return runtime


def configured_proxy() -> str | None:
    return _env("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")


def close_json_containers(text: str) -> str:
    closing = {"{": "}", "[": "]"}
    result: list[str] = []
    stack: list[str] = []
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            result.append(char)
        elif char in closing:
            stack.append(char)
            result.append(char)
        elif char in "}]":
            while stack and closing[stack[-1]] != char:
                result.append(closing[stack.pop()])
            if stack:
                stack.pop()
            result.append(char)
        else:
            result.append(char)
    if not in_string:
        while stack:
            result.append(closing[stack.pop()])
    return "".join(result)


def json_from_text(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.S)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    candidates = [cleaned]
    if start >= 0:
        candidates.append(cleaned[start : end + 1] if end > start else cleaned[start:])
    last_error: json.JSONDecodeError | None = None
    for candidate in dict.fromkeys(candidates):
        for value in (candidate, close_json_containers(candidate)):
            try:
                payload = json.loads(value)
                if isinstance(payload, dict):
                    return payload
            except json.JSONDecodeError as exc:
                last_error = exc
    if start < 0:
        raise ValueError("The model did not return a JSON object.")
    raise last_error or ValueError("The model did not return a JSON object.")


class JsonModelClient:
    """Small explicit structured-output client; no process-global profile state."""

    def __init__(self, runtime: ModelRuntime):
        self.runtime = runtime
        # One client is intentionally shared by selector workers.  Protect only
        # the mutable telemetry below; the network request must remain outside
        # this lock or selector batches would still execute serially.
        self._telemetry_lock = threading.Lock()
        self._logical_json_call_count = 0
        self._request_count = 0
        self._response_count = 0
        self._failed_request_count = 0
        self._json_retry_count = 0
        self._json_parse_error_count = 0
        self._usage_reported_request_count = 0
        self._usage_missing_request_count = 0
        self._usage_incomplete_request_count = 0
        self._derived_total_tokens_request_count = 0
        self._prompt_tokens_reported_response_count = 0
        self._completion_tokens_reported_response_count = 0
        self._reasoning_tokens_reported_response_count = 0
        self._total_tokens_reported_response_count = 0
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._reasoning_tokens = 0
        self._total_tokens = 0
        self._request_seconds_sum = 0.0
        self._request_active_wall_seconds = 0.0
        self._active_request_started: dict[int, float] = {}
        self._active_wall_interval_started: float | None = None
        self._max_concurrent_requests = 0
        self._global_gate_wait_seconds_sum = 0.0
        self._global_gate_acquisition_count = 0
        self._global_gate_waited_acquisition_count = 0
        self._global_model_gate = GlobalModelConcurrencyGate.from_environment(
            profile=runtime.profile,
            model=runtime.model,
        )
        proxy = configured_proxy()
        self._http_client = httpx.Client(proxy=proxy) if proxy else None
        self._client = OpenAI(
            api_key=runtime.api_key,
            base_url=runtime.base_url,
            timeout=max(30, int(_env("OPENAI_TIMEOUT_SECONDS", default="300") or "300")),
            max_retries=max(0, int(_env("OPENAI_MAX_RETRIES", default="0") or "0")),
            http_client=self._http_client,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "JsonModelClient":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    @staticmethod
    def _usage_field(container: Any, name: str) -> Any:
        if container is None:
            return None
        try:
            if isinstance(container, Mapping):
                return container.get(name)
            return getattr(container, name, None)
        except Exception:
            return None

    @classmethod
    def _token_count(cls, container: Any, *names: str) -> int | None:
        for name in names:
            value = cls._usage_field(container, name)
            if value is None:
                continue
            try:
                normalized = int(value)
            except (TypeError, ValueError, OverflowError):
                continue
            if normalized >= 0:
                return normalized
        return None

    @classmethod
    def _reasoning_token_count(cls, usage: Any) -> int | None:
        direct = cls._token_count(
            usage,
            "reasoning_tokens",
            "reasoning_token_count",
        )
        if direct is not None:
            return direct
        for details_name in (
            "completion_tokens_details",
            "output_tokens_details",
            "completion_details",
            "output_details",
        ):
            details = cls._usage_field(usage, details_name)
            nested = cls._token_count(
                details,
                "reasoning_tokens",
                "reasoning_token_count",
            )
            if nested is not None:
                return nested
        return None

    def _record_usage_unlocked(self, response: Any) -> None:
        """Accumulate one response while ``_telemetry_lock`` is held."""
        usage = self._usage_field(response, "usage")
        if usage is None:
            self._usage_missing_request_count += 1
            return
        self._usage_reported_request_count += 1
        prompt_tokens = self._token_count(usage, "prompt_tokens", "input_tokens")
        completion_tokens = self._token_count(
            usage,
            "completion_tokens",
            "output_tokens",
        )
        reasoning_tokens = self._reasoning_token_count(usage)
        total_tokens = self._token_count(usage, "total_tokens")
        if (
            total_tokens is None
            and prompt_tokens is not None
            and completion_tokens is not None
        ):
            total_tokens = prompt_tokens + completion_tokens
            self._derived_total_tokens_request_count += 1
        if prompt_tokens is None or completion_tokens is None or total_tokens is None:
            self._usage_incomplete_request_count += 1
        if prompt_tokens is not None:
            self._prompt_tokens_reported_response_count += 1
            self._prompt_tokens += prompt_tokens
        if completion_tokens is not None:
            self._completion_tokens_reported_response_count += 1
            self._completion_tokens += completion_tokens
        if reasoning_tokens is not None:
            self._reasoning_tokens_reported_response_count += 1
            self._reasoning_tokens += reasoning_tokens
        if total_tokens is not None:
            self._total_tokens_reported_response_count += 1
            self._total_tokens += total_tokens

    def _start_request(self) -> tuple[int, float]:
        """Register one in-flight provider request and return its identity."""
        started = time.monotonic()
        with self._telemetry_lock:
            self._request_count += 1
            request_id = self._request_count
            if not self._active_request_started:
                self._active_wall_interval_started = started
            self._active_request_started[request_id] = started
            self._max_concurrent_requests = max(
                self._max_concurrent_requests,
                len(self._active_request_started),
            )
        return request_id, started

    def _finish_request(self, request_id: int, started: float) -> None:
        """Close one request and update additive and overlap-aware timings."""
        finished = time.monotonic()
        with self._telemetry_lock:
            actual_started = self._active_request_started.pop(request_id, started)
            self._request_seconds_sum += max(0.0, finished - actual_started)
            if not self._active_request_started:
                interval_started = self._active_wall_interval_started
                if interval_started is not None:
                    self._request_active_wall_seconds += max(
                        0.0,
                        finished - interval_started,
                    )
                self._active_wall_interval_started = None

    def model_usage_snapshot(self) -> dict[str, Any]:
        """Return cumulative provider usage for every SDK request made so far."""
        now = time.monotonic()
        with self._telemetry_lock:
            if self._usage_reported_request_count == 0:
                usage_status = "unavailable"
            elif (
                self._failed_request_count
                or self._usage_missing_request_count
                or self._usage_incomplete_request_count
            ):
                usage_status = "partial"
            else:
                usage_status = "complete"
            request_seconds_sum = self._request_seconds_sum + sum(
                max(0.0, now - started)
                for started in self._active_request_started.values()
            )
            request_active_wall_seconds = self._request_active_wall_seconds
            if (
                self._active_request_started
                and self._active_wall_interval_started is not None
            ):
                request_active_wall_seconds += max(
                    0.0,
                    now - self._active_wall_interval_started,
                )
            return {
                "telemetry_available": True,
                "usage_status": usage_status,
                "logical_json_call_count": self._logical_json_call_count,
                "request_attempt_count": self._request_count,
                "request_count": self._request_count,
                "response_count": self._response_count,
                "failed_request_count": self._failed_request_count,
                "error_count": (
                    self._failed_request_count + self._json_parse_error_count
                ),
                "json_retry_count": self._json_retry_count,
                "json_parse_error_count": self._json_parse_error_count,
                "responses_with_usage_count": self._usage_reported_request_count,
                "responses_without_usage_count": self._usage_missing_request_count,
                "usage_reported_request_count": self._usage_reported_request_count,
                "usage_missing_request_count": self._usage_missing_request_count,
                "usage_incomplete_request_count": (
                    self._usage_incomplete_request_count
                ),
                "derived_total_tokens_request_count": (
                    self._derived_total_tokens_request_count
                ),
                "prompt_tokens": (
                    self._prompt_tokens
                    if self._prompt_tokens_reported_response_count
                    else None
                ),
                "completion_tokens": (
                    self._completion_tokens
                    if self._completion_tokens_reported_response_count
                    else None
                ),
                "reasoning_tokens": (
                    self._reasoning_tokens
                    if self._reasoning_tokens_reported_response_count
                    else None
                ),
                "total_tokens": (
                    self._total_tokens
                    if self._total_tokens_reported_response_count
                    else None
                ),
                "reasoning_tokens_reported_response_count": (
                    self._reasoning_tokens_reported_response_count
                ),
                # Additive provider occupancy: overlapping requests are all
                # counted. Keep request_wall_seconds as the compatibility name
                # used by telemetry-only v0.4.9 reports.
                "request_seconds_sum": round(request_seconds_sum, 6),
                "request_wall_seconds": round(request_seconds_sum, 6),
                # Union of intervals with >=1 provider request in flight. This
                # is the model-wait contribution to parallel wall time.
                "request_active_wall_seconds": round(
                    request_active_wall_seconds,
                    6,
                ),
                "active_request_count": len(self._active_request_started),
                "max_concurrent_requests": self._max_concurrent_requests,
                "global_gate_enabled": self._global_model_gate.enabled,
                "global_gate_capacity": self._global_model_gate.capacity,
                "global_gate_acquisition_count": (
                    self._global_gate_acquisition_count
                ),
                "global_gate_waited_acquisition_count": (
                    self._global_gate_waited_acquisition_count
                ),
                "global_gate_wait_seconds_sum": round(
                    self._global_gate_wait_seconds_sum,
                    6,
                ),
                # Temporary compatibility alias for early v0.5.0 harnesses.
                "global_gate_wait_seconds": round(
                    self._global_gate_wait_seconds_sum,
                    6,
                ),
            }

    def json(self, system: str, user: str, *, max_tokens: int) -> dict[str, Any]:
        with self._telemetry_lock:
            self._logical_json_call_count += 1
        last_error: ValueError | None = None
        for attempt in range(2):
            retry = ""
            if attempt:
                with self._telemetry_lock:
                    self._json_retry_count += 1
                retry = (
                    "\n\nYour previous response was not valid JSON. Return one complete JSON object only, "
                    "with no Markdown fence, commentary, or trailing text. Keep every string concise. "
                    "Do not omit required keys or close the response early."
                )
            request_tokens = max_tokens
            if self.runtime.profile == "gpt" or self.runtime.thinking_effort:
                request_tokens = min(max_tokens * 2, 12000)
            request: dict[str, Any] = {
                "model": self.runtime.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user + retry},
                ],
            }
            if self.runtime.profile != "gpt":
                request["temperature"] = 0.15
            if self.runtime.profile == "gpt":
                request["max_completion_tokens"] = request_tokens
                request["response_format"] = {"type": "json_object"}
            else:
                request["max_tokens"] = request_tokens
                if self.runtime.profile in {"glm", "glm53", "glm53flash"}:
                    request["response_format"] = {"type": "json_object"}
            if self.runtime.profile == "glm":
                request["extra_body"] = {"thinking": {"type": "disabled"}}
            elif self.runtime.profile == "glm53flash":
                request["extra_body"] = {
                    "thinking": {"type": "enabled"},
                    "reasoning_effort": self.runtime.thinking_effort or "low",
                }
            elif self.runtime.profile == "glm53" and self.runtime.thinking_effort:
                request["reasoning_effort"] = self.runtime.thinking_effort
            with self._global_model_gate.slot() as lease:
                if lease.enabled:
                    with self._telemetry_lock:
                        self._global_gate_acquisition_count += 1
                        self._global_gate_wait_seconds_sum += max(
                            0.0,
                            lease.wait_seconds,
                        )
                        if (
                            lease.wait_seconds
                            >= self._global_model_gate.poll_seconds
                        ):
                            self._global_gate_waited_acquisition_count += 1
                request_id, request_started = self._start_request()
                try:
                    response = self._client.chat.completions.create(**request)
                except Exception:
                    with self._telemetry_lock:
                        self._failed_request_count += 1
                    raise
                finally:
                    self._finish_request(request_id, request_started)
            with self._telemetry_lock:
                self._response_count += 1
                self._record_usage_unlocked(response)
            response_text = response.choices[0].message.content or ""
            try:
                return json_from_text(response_text)
            except ValueError as exc:
                with self._telemetry_lock:
                    self._json_parse_error_count += 1
                last_error = ValueError(
                    "Invalid structured model output "
                    f"(model={self.runtime.model}, chars={len(response_text)}): {exc}"
                )
        raise last_error or ValueError("The model did not return valid JSON.")
