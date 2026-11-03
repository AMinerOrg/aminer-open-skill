from __future__ import annotations

import multiprocessing
import os
import time
from pathlib import Path

import pytest

from baseline_finder.global_concurrency import (
    DEFAULT_GLOBAL_CONCURRENCY,
    GlobalConcurrencyConfigurationError,
    GlobalConcurrencyTimeout,
    GlobalModelConcurrencyGate,
)


def _hold_slot_until_released(directory: str, ready, release) -> None:
    gate = GlobalModelConcurrencyGate(
        capacity=1,
        directory=directory,
        acquire_timeout_seconds=2,
        poll_seconds=0.01,
    )
    with gate.slot():
        ready.set()
        release.wait(5)


def _acquire_then_crash(directory: str, ready) -> None:
    gate = GlobalModelConcurrencyGate(
        capacity=1,
        directory=directory,
        acquire_timeout_seconds=2,
        poll_seconds=0.01,
    )
    lease = gate.acquire(metadata={"test": "abrupt-exit"})
    ready.set()
    time.sleep(0.05)
    assert lease.slot_index == 0
    os._exit(23)


def test_environment_defaults_to_six_glm_slots(monkeypatch, tmp_path: Path) -> None:
    for name in (
        "BASELINE_GLM_GLOBAL_CONCURRENCY",
        "BASELINE_GLM_GATE_TIMEOUT_SECONDS",
        "BASELINE_GLM_GATE_POLL_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BASELINE_GLM_GATE_DIR", str(tmp_path))

    gate = GlobalModelConcurrencyGate.from_environment(
        profile="glm53",
        model="glm-5.3",
    )

    assert gate.enabled is True
    assert gate.capacity == DEFAULT_GLOBAL_CONCURRENCY == 6
    assert gate.acquire_timeout_seconds == 600


def test_non_glm_profile_uses_noop_gate(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BASELINE_GLM_GATE_DIR", str(tmp_path / "not-created"))
    monkeypatch.setenv("BASELINE_GLM_GLOBAL_CONCURRENCY", "irrelevant-for-gpt")
    gate = GlobalModelConcurrencyGate.from_environment(
        profile="gpt",
        model="gpt-test",
    )

    with gate.slot() as lease:
        assert lease.enabled is False
        assert lease.wait_seconds == 0

    assert not gate.directory.exists()


def test_zero_capacity_disables_gate_without_parsing_other_settings(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BASELINE_GLM_GLOBAL_CONCURRENCY", "0")
    monkeypatch.setenv("BASELINE_GLM_GATE_TIMEOUT_SECONDS", "not-a-number")
    monkeypatch.setenv("BASELINE_GLM_GATE_DIR", str(tmp_path / "not-created"))

    gate = GlobalModelConcurrencyGate.from_environment(
        profile="glm53",
        model="glm-5.3",
    )

    assert gate.enabled is False
    assert gate.capacity == 0
    assert not gate.directory.exists()


def test_two_slots_block_a_third_until_one_is_released(tmp_path: Path) -> None:
    gate = GlobalModelConcurrencyGate(
        capacity=2,
        directory=tmp_path,
        acquire_timeout_seconds=0.05,
        poll_seconds=0.005,
    )
    first = gate.acquire()
    second = gate.acquire()
    assert {first.slot_index, second.slot_index} == {0, 1}
    try:
        with pytest.raises(GlobalConcurrencyTimeout):
            gate.acquire()
        first.release()
        replacement = gate.acquire()
        assert replacement.slot_index == 0
        replacement.release()
    finally:
        first.release()
        second.release()


def test_context_manager_releases_after_exception(tmp_path: Path) -> None:
    gate = GlobalModelConcurrencyGate(
        capacity=1,
        directory=tmp_path,
        acquire_timeout_seconds=0.05,
        poll_seconds=0.005,
    )

    with pytest.raises(RuntimeError, match="boom"):
        with gate.slot():
            raise RuntimeError("boom")

    with gate.slot() as lease:
        assert lease.slot_index == 0


def test_slot_is_shared_between_processes(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    child = context.Process(
        target=_hold_slot_until_released,
        args=(str(tmp_path), ready, release),
    )
    child.start()
    try:
        assert ready.wait(5)
        gate = GlobalModelConcurrencyGate(
            capacity=1,
            directory=tmp_path,
            acquire_timeout_seconds=0.1,
            poll_seconds=0.01,
        )
        with pytest.raises(GlobalConcurrencyTimeout):
            gate.acquire()
    finally:
        release.set()
        child.join(5)
        if child.is_alive():
            child.terminate()
            child.join(5)
    assert child.exitcode == 0


def test_abrupt_process_exit_releases_slot_and_snapshot_cleans_metadata(
    tmp_path: Path,
) -> None:
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    child = context.Process(
        target=_acquire_then_crash,
        args=(str(tmp_path), ready),
    )
    child.start()
    assert ready.wait(5)
    child.join(5)
    if child.is_alive():
        child.terminate()
        child.join(5)
    assert child.exitcode == 23

    gate = GlobalModelConcurrencyGate(
        capacity=1,
        directory=tmp_path,
        acquire_timeout_seconds=0.5,
        poll_seconds=0.01,
    )
    snapshots = gate.inspect_slots()
    assert snapshots[0].occupied is False
    assert snapshots[0].metadata is not None
    assert snapshots[0].metadata["test"] == "abrupt-exit"
    assert snapshots[0].stale_metadata_removed is True

    with gate.slot() as lease:
        assert lease.slot_index == 0


def test_live_slot_has_auditable_metadata(tmp_path: Path) -> None:
    gate = GlobalModelConcurrencyGate(capacity=1, directory=tmp_path)
    with gate.slot(metadata={"request_kind": "selector"}) as lease:
        metadata_path = tmp_path / "slot-000.json"
        metadata = metadata_path.read_text(encoding="utf-8")
        assert lease.owner_id in metadata
        snapshots = gate.inspect_slots()
        assert snapshots[0].occupied is True
        assert snapshots[0].metadata is not None
        assert snapshots[0].metadata["request_kind"] == "selector"

    assert not (tmp_path / "slot-000.json").exists()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("BASELINE_GLM_GLOBAL_CONCURRENCY", "not-an-int"),
        ("BASELINE_GLM_GLOBAL_CONCURRENCY", "-1"),
        ("BASELINE_GLM_GATE_TIMEOUT_SECONDS", "nan"),
        ("BASELINE_GLM_GATE_POLL_SECONDS", "0"),
    ],
)
def test_invalid_environment_fails_clearly(
    monkeypatch,
    tmp_path: Path,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv("BASELINE_GLM_GATE_DIR", str(tmp_path))
    monkeypatch.setenv(name, value)
    with pytest.raises(GlobalConcurrencyConfigurationError):
        GlobalModelConcurrencyGate.from_environment(
            profile="glm53",
            model="glm-5.3",
        )
