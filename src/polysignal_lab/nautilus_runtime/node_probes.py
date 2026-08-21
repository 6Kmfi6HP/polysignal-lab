from __future__ import annotations

import logging
import os
from pathlib import Path
import time
from typing import Callable

from polysignal_lab.config import Settings
from polysignal_lab.observability.runtime_health import (
    write_runtime_heartbeat,
    write_runtime_startup_marker,
)

logger = logging.getLogger("polysignal_lab.nautilus_runtime.node_probes")

_monotonic = time.monotonic

# Heartbeat writes happen on the strategy's market-data hot path; unthrottled
# they dominate the event loop (issue #21: feed backlog -> permanent
# readiness_miss). Liveness only needs updated_at fresh within 120s and the
# keyed miss set accurate on transitions, so identical states are written at
# most once per interval while state transitions always hit disk.
_HEARTBEAT_WRITE_INTERVAL_SEC = 1.0

# Per heartbeat-path throttle state: last write time + keys currently missing.
_HEARTBEAT_WRITE_GATES: dict[Path, tuple[float, frozenset[str]]] = {}


def _reset_heartbeat_write_gates() -> None:
    _HEARTBEAT_WRITE_GATES.clear()


def _runtime_heartbeat_path(settings: Settings) -> Path:
    return Path(settings.storage.state_dir) / "runtime_heartbeat.json"


def _current_process_boot_id() -> str | None:
    """Boot/generation id assigned by the entrypoint supervisor for THIS app
    spawn (immune to PID reuse across container restarts). None when running
    outside the supervised entrypoint (tests, local runs); the field is then
    written as null and the bash supervisor treats it as foreign."""
    return os.environ.get("POLYSIGNAL_HEARTBEAT_BOOT_ID") or None


def _runtime_startup_marker_path(settings: Settings) -> Path:
    return Path(settings.storage.state_dir) / "runtime_startup.json"


def _log_probe_write_failure(path: Path) -> None:
    logger.warning("Failed to write runtime probe state: %s", path, exc_info=True)


def _log_readiness_transitions(
    previous: frozenset[str] | None,
    current: frozenset[str],
    detail_by_key: dict[str, dict[str, object]],
    *,
    transition_key: str | None = None,
    transition_detail: dict[str, object] | None = None,
) -> None:
    """Put readiness transitions on the log stream, not just in the heartbeat file.

    The heartbeat JSON is the liveness probe's truth source, but it is invisible
    to `docker logs`: a container could sit unhealthy on `readiness_miss` for
    hours without emitting a single ERROR. Only transitions are logged — this
    runs on the market-data hot path.
    """
    known: frozenset[str] = frozenset() if previous is None else previous
    for condition_id in sorted(current - known):
        logger.error(
            "Runtime readiness miss started: condition_id=%s",
            condition_id,
            extra={"readiness_detail": detail_by_key.get(condition_id, {})},
        )
    for condition_id in sorted(known - current):
        detail = (
            transition_detail
            if condition_id == transition_key and transition_detail is not None
            else detail_by_key.get(condition_id, {})
        )
        logger.info(
            "Runtime readiness recovered: condition_id=%s",
            condition_id,
            extra={"readiness_detail": detail},
        )


def _write_runtime_startup_marker_best_effort(path: Path) -> None:
    try:
        _ = write_runtime_startup_marker(path)
    except OSError:
        _log_probe_write_failure(path)


def _heartbeat_write_due(
    path: Path,
    *,
    phase: str,
    fatal: bool,
    readiness_key: str | None,
    readiness_ok: bool | None,
) -> bool:
    if fatal or phase in {"start", "starting"}:
        return True
    gate = _HEARTBEAT_WRITE_GATES.get(path)
    if gate is None:
        return True
    last_write_at, miss_keys = gate
    if readiness_key is not None:
        if readiness_ok is True and readiness_key in miss_keys:
            return True
        if readiness_ok is False and readiness_key not in miss_keys:
            return True
    return _monotonic() - last_write_at >= _HEARTBEAT_WRITE_INTERVAL_SEC


def _write_runtime_heartbeat_best_effort(
    path: Path,
    *,
    phase: str,
    fatal: bool = False,
    fatal_reason: str | None = None,
    readiness_key: str | None = None,
    readiness_ok: bool | None = None,
    readiness_detail: dict[str, object] | None = None,
    active_readiness_keys: frozenset[str] | None = None,
) -> None:
    if not _heartbeat_write_due(
        path,
        phase=phase,
        fatal=fatal,
        readiness_key=readiness_key,
        readiness_ok=readiness_ok,
    ):
        return
    previous_gate = _HEARTBEAT_WRITE_GATES.get(path)
    try:
        heartbeat = write_runtime_heartbeat(
            path,
            phase=phase,
            fatal=fatal,
            fatal_reason=fatal_reason,
            readiness_key=readiness_key,
            readiness_ok=readiness_ok,
            readiness_detail=readiness_detail,
            active_readiness_keys=active_readiness_keys,
            pid=os.getpid(),
            boot_id=_current_process_boot_id(),
        )
    except OSError:
        _log_probe_write_failure(path)
        return
    miss_keys = frozenset(heartbeat.readiness_miss_started_at_by_key)
    _log_readiness_transitions(
        None if previous_gate is None else previous_gate[1],
        miss_keys,
        heartbeat.readiness_detail_by_key,
        transition_key=readiness_key,
        transition_detail=readiness_detail,
    )
    _HEARTBEAT_WRITE_GATES[path] = (_monotonic(), miss_keys)


def _runtime_progress_callback(settings: Settings) -> Callable[..., None]:
    path = _runtime_heartbeat_path(settings)

    def note_progress(
        phase: str,
        active_readiness_keys: frozenset[str] | None = None,
    ) -> None:
        _write_runtime_heartbeat_best_effort(
            path,
            phase=phase,
            active_readiness_keys=active_readiness_keys,
        )

    return note_progress


def _runtime_readiness_callback(
    settings: Settings,
) -> Callable[[str, bool, dict[str, object]], None]:
    path = _runtime_heartbeat_path(settings)

    def note_readiness(
        condition_id: str,
        ready: bool,
        detail: dict[str, object],
    ) -> None:
        _write_runtime_heartbeat_best_effort(
            path,
            phase="readiness_ok" if ready else "readiness_miss",
            readiness_key=condition_id,
            readiness_ok=ready,
            readiness_detail=detail,
        )

    return note_readiness
