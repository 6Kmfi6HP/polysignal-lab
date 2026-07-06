"""Runtime health probes extracted from node.py."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from polysignal_lab.config import Settings
from polysignal_lab.observability.runtime_health import (
    write_runtime_heartbeat,
    write_runtime_startup_marker,
)

logger = logging.getLogger("polysignal_lab.nautilus_runtime.node_probes")


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


def _write_runtime_heartbeat_best_effort(
    path: Path,
    *,
    phase: str,
    fatal: bool = False,
    fatal_reason: str | None = None,
) -> None:
    try:
        _ = write_runtime_heartbeat(
            path,
            phase=phase,
            fatal=fatal,
            fatal_reason=fatal_reason,
        )
    except OSError:
        _log_probe_write_failure(path)


def _runtime_progress_callback(settings: Settings) -> Callable[[str], None]:
    path = _runtime_heartbeat_path(settings)

    def note_progress(phase: str) -> None:
        _write_runtime_heartbeat_best_effort(path, phase=phase)

    return note_progress
