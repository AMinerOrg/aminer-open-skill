from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from baseline_audit.config import JsonModelClient, ModelRuntime


def _runtime() -> ModelRuntime:
    return ModelRuntime(
        profile="deepseek",
        label="test",
        model="test-model",
        api_key="test-key",
        base_url="https://example.invalid/v1",
    )


def test_parallel_requests_preserve_usage_and_distinguish_sum_from_wall() -> None:
    worker_count = 6
    barrier = threading.Barrier(worker_count)

    class FakeCompletions:
        def create(self, **_request):
            barrier.wait(timeout=2)
            time.sleep(0.04)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"status": "ok"}')
                    )
                ],
                usage=SimpleNamespace(
                    prompt_tokens=10,
                    completion_tokens=2,
                    total_tokens=12,
                ),
            )

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

        def close(self) -> None:
            pass

    with (
        patch("baseline_audit.config.configured_proxy", return_value=None),
        patch("baseline_audit.config.OpenAI", FakeOpenAI),
    ):
        with JsonModelClient(_runtime()) as client:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                results = list(
                    executor.map(
                        lambda index: client.json(
                            "system",
                            f"user-{index}",
                            max_tokens=100,
                        ),
                        range(worker_count),
                    )
                )
            usage = client.model_usage_snapshot()

    assert results == [{"status": "ok"}] * worker_count
    assert usage["logical_json_call_count"] == worker_count
    assert usage["request_count"] == worker_count
    assert usage["response_count"] == worker_count
    assert usage["usage_reported_request_count"] == worker_count
    assert usage["prompt_tokens"] == worker_count * 10
    assert usage["completion_tokens"] == worker_count * 2
    assert usage["total_tokens"] == worker_count * 12
    assert usage["active_request_count"] == 0
    assert usage["max_concurrent_requests"] == worker_count
    assert usage["request_seconds_sum"] >= 0.04 * worker_count
    assert usage["request_wall_seconds"] == usage["request_seconds_sum"]
    assert usage["request_active_wall_seconds"] >= 0.04
    assert usage["request_active_wall_seconds"] < usage["request_seconds_sum"] / 2


def test_snapshot_includes_requests_that_are_still_in_flight() -> None:
    worker_count = 2
    both_started = threading.Barrier(worker_count + 1)
    release = threading.Event()

    class FakeCompletions:
        def create(self, **_request):
            both_started.wait(timeout=2)
            assert release.wait(timeout=2)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"status": "ok"}')
                    )
                ],
                usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            )

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

        def close(self) -> None:
            pass

    with (
        patch("baseline_audit.config.configured_proxy", return_value=None),
        patch("baseline_audit.config.OpenAI", FakeOpenAI),
    ):
        with JsonModelClient(_runtime()) as client:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = [
                    executor.submit(client.json, "system", "user", max_tokens=100)
                    for _ in range(worker_count)
                ]
                both_started.wait(timeout=2)
                time.sleep(0.01)
                in_flight = client.model_usage_snapshot()
                release.set()
                assert [future.result(timeout=2) for future in futures] == [
                    {"status": "ok"},
                    {"status": "ok"},
                ]
            finished = client.model_usage_snapshot()

    assert in_flight["active_request_count"] == worker_count
    assert in_flight["max_concurrent_requests"] == worker_count
    assert in_flight["request_seconds_sum"] == in_flight["request_wall_seconds"]
    assert in_flight["request_seconds_sum"] > in_flight["request_active_wall_seconds"]
    assert finished["active_request_count"] == 0
    assert finished["request_count"] == worker_count
    assert finished["prompt_tokens"] == worker_count
    assert finished["completion_tokens"] == worker_count


def test_glm_global_gate_serializes_two_shared_client_requests(tmp_path) -> None:
    state_lock = threading.Lock()

    class FakeCompletions:
        def __init__(self) -> None:
            self.active = 0
            self.max_active = 0

        def create(self, **_request):
            with state_lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            try:
                time.sleep(0.05)
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content='{"status": "ok"}')
                        )
                    ],
                    usage={
                        "prompt_tokens": 3,
                        "completion_tokens": 1,
                        "total_tokens": 4,
                    },
                )
            finally:
                with state_lock:
                    self.active -= 1

    completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=completions)

        def close(self) -> None:
            pass

    runtime = ModelRuntime(
        profile="glm53",
        label="test",
        model="glm-test-model",
        api_key="test-key",
        base_url="https://example.invalid/v1",
        thinking_effort="low",
    )
    with (
        patch.dict(
            os.environ,
            {
                "BASELINE_GLM_GLOBAL_CONCURRENCY": "1",
                "BASELINE_GLM_GATE_DIR": str(tmp_path / "gate"),
                "BASELINE_GLM_GATE_TIMEOUT_SECONDS": "2",
                "BASELINE_GLM_GATE_POLL_SECONDS": "0.005",
            },
            clear=False,
        ),
        patch("baseline_audit.config.configured_proxy", return_value=None),
        patch("baseline_audit.config.OpenAI", FakeOpenAI),
    ):
        with JsonModelClient(runtime) as client:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(client.json, "system", "user", max_tokens=100)
                    for _ in range(2)
                ]
                assert [future.result(timeout=2) for future in futures] == [
                    {"status": "ok"},
                    {"status": "ok"},
                ]
            usage = client.model_usage_snapshot()

    assert completions.max_active == 1
    assert usage["max_concurrent_requests"] == 1
    assert usage["global_gate_enabled"] is True
    assert usage["global_gate_capacity"] == 1
    assert usage["global_gate_acquisition_count"] == 2
    assert usage["global_gate_waited_acquisition_count"] == 1
    assert usage["global_gate_wait_seconds_sum"] >= 0.04
    assert usage["global_gate_wait_seconds"] == usage[
        "global_gate_wait_seconds_sum"
    ]
    assert usage["request_count"] == 2
    assert usage["prompt_tokens"] == 6
    assert usage["completion_tokens"] == 2
    assert usage["total_tokens"] == 8


def test_parallel_request_failure_does_not_leave_active_timing_open() -> None:
    class FakeCompletions:
        def create(self, **_request):
            raise RuntimeError("provider failed")

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

        def close(self) -> None:
            pass

    with (
        patch("baseline_audit.config.configured_proxy", return_value=None),
        patch("baseline_audit.config.OpenAI", FakeOpenAI),
    ):
        with JsonModelClient(_runtime()) as client:
            with pytest.raises(RuntimeError, match="provider failed"):
                client.json("system", "user", max_tokens=100)
            usage = client.model_usage_snapshot()

    assert usage["request_count"] == 1
    assert usage["failed_request_count"] == 1
    assert usage["active_request_count"] == 0
    assert usage["request_seconds_sum"] >= 0
    assert usage["request_wall_seconds"] >= 0
    assert usage["request_active_wall_seconds"] >= 0
