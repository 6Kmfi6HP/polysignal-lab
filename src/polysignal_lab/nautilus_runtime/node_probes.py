from __future__ import annotations

import logging
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


def _runtime_startup_marker_path(settings: Settings) -> Path:
    return Path(settings.storage.state_dir) / "runtime_startup.json"


def _log_probe_write_failure(path: Path) -> None:
    logger.warning("Failed to write runtime probe state: %s", path, exc_info=True)


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
) -> None:
    if not _heartbeat_write_due(
        path,
        phase=phase,
        fatal=fatal,
        readiness_key=readiness_key,
        readiness_ok=readiness_ok,
    ):
        return
    try:
        heartbeat = write_runtime_heartbeat(
            path,
            phase=phase,
            fatal=fatal,
            fatal_reason=fatal_reason,
            readiness_key=readiness_key,
            readiness_ok=readiness_ok,
            readiness_detail=readiness_detail,
        )
    except OSError:
        _log_probe_write_failure(path)
        return
    _HEARTBEAT_WRITE_GATES[path] = (
        _monotonic(),
        frozenset(heartbeat.readiness_miss_started_at_by_key),
    )


def _runtime_progress_callback(settings: Settings) -> Callable[[str], None]:
    path = _runtime_heartbeat_path(settings)

    def note_progress(phase: str) -> None:
        _write_runtime_heartbeat_best_effort(path, phase=phase)

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
