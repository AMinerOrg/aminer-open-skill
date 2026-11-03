"""Cross-process concurrency gate for GLM provider requests.

The gate uses a small pool of ordinary files as auditable slots.  Holding a
slot means holding an operating-system lock on one byte of the corresponding
``.lock`` file.  File locks are released by the operating system when a
process exits, so a crashed worker cannot permanently consume capacity.

The default directory is local to the current operating-system user.  A
deployment spanning containers or hosts must point ``BASELINE_GLM_GATE_DIR``
at one shared filesystem directory and use the same configured capacity in
every worker.
"""

from __future__ import annotations

import errno
import getpass
import json
import math
import os
import re
import socket
import tempfile
import threading
import time
import uuid
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Mapping

from .errors import BaselineAuditError


GLM_PROFILES = frozenset({"glm", "glm53", "glm53flash"})
DEFAULT_GLOBAL_CONCURRENCY = 6
DEFAULT_ACQUIRE_TIMEOUT_SECONDS = 600.0
DEFAULT_POLL_SECONDS = 0.05


class GlobalConcurrencyConfigurationError(BaselineAuditError):
    """The cross-process concurrency gate has invalid configuration."""


class GlobalConcurrencyTimeout(BaselineAuditError):
    """No provider slot became available before the configured deadline."""


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _default_gate_directory() -> Path:
    if hasattr(os, "getuid"):
        identity = str(os.getuid())
    else:
        identity = re.sub(r"[^A-Za-z0-9_.-]+", "-", getpass.getuser()).strip("-")
        identity = identity or "user"
    return Path(tempfile.gettempdir()) / f"baseline-audit-glm-gate-{identity}"


def _integer_environment(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise GlobalConcurrencyConfigurationError(
            f"{name} must be an integer; got {raw!r}."
        ) from exc
    if value < 0:
        raise GlobalConcurrencyConfigurationError(
            f"{name} must be zero or greater; got {value}."
        )
    return value


def _float_environment(name: str, default: float, *, allow_zero: bool) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw.strip())
    except ValueError as exc:
        raise GlobalConcurrencyConfigurationError(
            f"{name} must be a number; got {raw!r}."
        ) from exc
    minimum_ok = value >= 0 if allow_zero else value > 0
    if not math.isfinite(value) or not minimum_ok:
        relation = "zero or greater" if allow_zero else "greater than zero"
        raise GlobalConcurrencyConfigurationError(
            f"{name} must be finite and {relation}; got {raw!r}."
        )
    return value


def _try_lock(handle: BinaryIO) -> bool:
    """Try to lock byte zero without blocking on Unix or Windows."""
    handle.seek(0)
    if os.name == "nt":  # pragma: no cover - exercised on Windows CI/deployments
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                return False
            raise

    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError as exc:
        if exc.errno in {errno.EACCES, errno.EAGAIN}:
            return False
        raise


def _unlock(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":  # pragma: no cover - exercised on Windows CI/deployments
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic_json(path: Path, payload: Mapping[str, Any], owner_id: str) -> None:
    temporary = path.with_name(f".{path.name}.{owner_id}.tmp")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = None
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
        os.replace(temporary, path)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


@dataclass(frozen=True)
class GateSlotSnapshot:
    """Best-effort auditable state for one configured slot."""

    slot_index: int
    occupied: bool
    metadata: dict[str, Any] | None
    stale_metadata_removed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "slot_index": self.slot_index,
            "occupied": self.occupied,
            "metadata": self.metadata,
            "stale_metadata_removed": self.stale_metadata_removed,
        }


class GlobalConcurrencyLease(AbstractContextManager["GlobalConcurrencyLease"]):
    """One acquired slot; release is idempotent and exception-safe."""

    def __init__(
        self,
        *,
        gate: "GlobalModelConcurrencyGate",
        slot_index: int | None,
        owner_id: str,
        wait_seconds: float,
        handle: BinaryIO | None,
        metadata_path: Path | None,
    ) -> None:
        self.gate = gate
        self.slot_index = slot_index
        self.owner_id = owner_id
        self.wait_seconds = wait_seconds
        self._handle = handle
        self._metadata_path = metadata_path
        self._release_mutex = threading.Lock()
        self._released = False

    @property
    def enabled(self) -> bool:
        return self.slot_index is not None

    @property
    def released(self) -> bool:
        return self._released

    def release(self) -> None:
        with self._release_mutex:
            if self._released:
                return
            self._released = True
            handle = self._handle
            self._handle = None
            if handle is None:
                return
            try:
                if self._metadata_path is not None:
                    metadata = _read_json(self._metadata_path)
                    if metadata and metadata.get("owner_id") == self.owner_id:
                        try:
                            self._metadata_path.unlink()
                        except FileNotFoundError:
                            pass
            finally:
                try:
                    _unlock(handle)
                finally:
                    handle.close()

    def __enter__(self) -> "GlobalConcurrencyLease":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.release()


class GlobalModelConcurrencyGate:
    """A cross-process, thread-safe pool of provider request slots."""

    def __init__(
        self,
        *,
        capacity: int = DEFAULT_GLOBAL_CONCURRENCY,
        directory: Path | str | None = None,
        acquire_timeout_seconds: float = DEFAULT_ACQUIRE_TIMEOUT_SECONDS,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        profile: str = "glm53",
        model: str = "",
        enabled: bool = True,
    ) -> None:
        if capacity < 0:
            raise GlobalConcurrencyConfigurationError(
                f"Gate capacity must be zero or greater; got {capacity}."
            )
        if not math.isfinite(acquire_timeout_seconds) or acquire_timeout_seconds < 0:
            raise GlobalConcurrencyConfigurationError(
                "Gate acquire timeout must be finite and zero or greater."
            )
        if not math.isfinite(poll_seconds) or poll_seconds <= 0:
            raise GlobalConcurrencyConfigurationError(
                "Gate poll interval must be finite and greater than zero."
            )
        self.capacity = capacity if enabled else 0
        self.directory = Path(directory or _default_gate_directory()).expanduser()
        self.acquire_timeout_seconds = acquire_timeout_seconds
        self.poll_seconds = poll_seconds
        self.profile = profile
        self.model = model
        self.enabled = self.capacity > 0
        self._host = socket.gethostname()
        if self.enabled:
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            if not self.directory.is_dir():
                raise GlobalConcurrencyConfigurationError(
                    f"GLM gate path is not a directory: {self.directory}"
                )

    @classmethod
    def from_environment(
        cls,
        *,
        profile: str,
        model: str,
    ) -> "GlobalModelConcurrencyGate":
        """Build the GLM-only gate from public runtime environment settings."""
        normalized_profile = profile.strip().lower()
        is_glm = normalized_profile in GLM_PROFILES
        if not is_glm:
            return cls(
                capacity=0,
                profile=normalized_profile,
                model=model,
                enabled=False,
            )
        capacity = _integer_environment(
            "BASELINE_GLM_GLOBAL_CONCURRENCY",
            DEFAULT_GLOBAL_CONCURRENCY,
        )
        if capacity == 0:
            return cls(
                capacity=0,
                profile=normalized_profile,
                model=model,
                enabled=False,
            )
        timeout = _float_environment(
            "BASELINE_GLM_GATE_TIMEOUT_SECONDS",
            DEFAULT_ACQUIRE_TIMEOUT_SECONDS,
            allow_zero=True,
        )
        poll = _float_environment(
            "BASELINE_GLM_GATE_POLL_SECONDS",
            DEFAULT_POLL_SECONDS,
            allow_zero=False,
        )
        configured_directory = os.environ.get("BASELINE_GLM_GATE_DIR")
        return cls(
            capacity=capacity,
            directory=(
                Path(configured_directory.strip())
                if configured_directory and configured_directory.strip()
                else None
            ),
            acquire_timeout_seconds=timeout,
            poll_seconds=poll,
            profile=normalized_profile,
            model=model,
            enabled=True,
        )

    def _lock_path(self, slot_index: int) -> Path:
        return self.directory / f"slot-{slot_index:03d}.lock"

    def _metadata_path(self, slot_index: int) -> Path:
        return self.directory / f"slot-{slot_index:03d}.json"

    def _open_lock_file(self, slot_index: int) -> BinaryIO:
        path = self._lock_path(slot_index)
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if os.fstat(descriptor).st_size < 1:
                os.write(descriptor, b"\0")
            return os.fdopen(descriptor, "r+b", buffering=0)
        except BaseException:
            os.close(descriptor)
            raise

    def _try_acquire_slot(
        self,
        slot_index: int,
        *,
        owner_id: str,
        wait_seconds: float,
        extra_metadata: Mapping[str, Any] | None,
    ) -> GlobalConcurrencyLease | None:
        handle = self._open_lock_file(slot_index)
        locked = False
        try:
            locked = _try_lock(handle)
            if not locked:
                handle.close()
                return None
            metadata_path = self._metadata_path(slot_index)
            metadata: dict[str, Any] = dict(extra_metadata or {})
            metadata.update(
                {
                    "schema": "baseline-audit-glm-gate/v1",
                    "slot_index": slot_index,
                    "owner_id": owner_id,
                    "pid": os.getpid(),
                    "thread_id": threading.get_ident(),
                    "host": self._host,
                    "profile": self.profile,
                    "model": self.model,
                    "acquired_at_utc": _utc_now_text(),
                    "wait_seconds": round(wait_seconds, 6),
                }
            )
            _atomic_json(metadata_path, metadata, owner_id)
            return GlobalConcurrencyLease(
                gate=self,
                slot_index=slot_index,
                owner_id=owner_id,
                wait_seconds=wait_seconds,
                handle=handle,
                metadata_path=metadata_path,
            )
        except BaseException:
            try:
                if locked:
                    _unlock(handle)
            finally:
                handle.close()
            raise

    def acquire(
        self,
        *,
        timeout_seconds: float | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> GlobalConcurrencyLease:
        """Acquire one global provider slot, waiting up to the configured limit."""
        started = time.monotonic()
        owner_id = uuid.uuid4().hex
        if not self.enabled:
            return GlobalConcurrencyLease(
                gate=self,
                slot_index=None,
                owner_id=owner_id,
                wait_seconds=0.0,
                handle=None,
                metadata_path=None,
            )
        timeout = (
            self.acquire_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        if not math.isfinite(timeout) or timeout < 0:
            raise GlobalConcurrencyConfigurationError(
                "Gate acquire timeout must be finite and zero or greater."
            )
        deadline = started + timeout
        while True:
            for slot_index in range(self.capacity):
                waited = max(0.0, time.monotonic() - started)
                lease = self._try_acquire_slot(
                    slot_index,
                    owner_id=owner_id,
                    wait_seconds=waited,
                    extra_metadata=metadata,
                )
                if lease is not None:
                    return lease
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GlobalConcurrencyTimeout(
                    "Timed out waiting for a global GLM request slot "
                    f"after {max(0.0, time.monotonic() - started):.3f}s "
                    f"(capacity={self.capacity}, directory={self.directory})."
                )
            time.sleep(min(self.poll_seconds, remaining))

    def slot(
        self,
        *,
        timeout_seconds: float | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> GlobalConcurrencyLease:
        """Return an acquired context-managed slot."""
        return self.acquire(timeout_seconds=timeout_seconds, metadata=metadata)

    def inspect_slots(self, *, clean_stale_metadata: bool = True) -> list[GateSlotSnapshot]:
        """Report live lock state and optionally remove crash-left metadata.

        A metadata file is stale only when this method successfully locks the
        corresponding slot.  This avoids PID probing and is safe across normal
        exits, exceptions, and abrupt process termination.
        """
        if not self.enabled:
            return []
        snapshots: list[GateSlotSnapshot] = []
        for slot_index in range(self.capacity):
            handle = self._open_lock_file(slot_index)
            metadata_path = self._metadata_path(slot_index)
            locked = False
            try:
                locked = _try_lock(handle)
                metadata = _read_json(metadata_path)
                removed = False
                if locked and metadata is not None and clean_stale_metadata:
                    try:
                        metadata_path.unlink()
                        removed = True
                    except FileNotFoundError:
                        pass
                snapshots.append(
                    GateSlotSnapshot(
                        slot_index=slot_index,
                        occupied=not locked,
                        metadata=metadata,
                        stale_metadata_removed=removed,
                    )
                )
            finally:
                if locked:
                    _unlock(handle)
                handle.close()
        return snapshots
