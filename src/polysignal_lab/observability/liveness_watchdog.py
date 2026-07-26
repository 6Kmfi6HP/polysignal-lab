from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from polysignal_lab.config import Settings
from polysignal_lab.observability.liveness_alert import (
    AlertState,
    evaluate_liveness_alert,
)
from polysignal_lab.observability.runtime_health import (
    _utc_now,
    evaluate_liveness,
    read_runtime_startup_started_at,
)

logger = logging.getLogger("polysignal_lab.observability.liveness_watchdog")


class LivenessWatchdog:
    """Polls the heartbeat the Docker healthcheck reads, and notifies on failure.

    Runs on its own thread rather than the Nautilus event loop: the failure it
    exists to report is the runtime being wedged, so it must not share a
    scheduler with the thing it watches.
    """

    def __init__(
        self,
        settings: Settings,
        send: Callable[[str], None],
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings: Settings = settings
        self._send: Callable[[str], None] = send
        self._now: Callable[[], datetime] | None = now
        self._state: AlertState = AlertState()
        self._stop: threading.Event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def state(self) -> AlertState:
        return self._state

    def _heartbeat_path(self) -> Path:
        return Path(self._settings.storage.state_dir) / "runtime_heartbeat.json"

    def _startup_started_at(self) -> datetime | None:
        marker = Path(self._settings.storage.state_dir) / "runtime_startup.json"
        try:
            return read_runtime_startup_started_at(marker)
        except (OSError, ValueError, KeyError):
            return None

    def poll_once(self) -> str | None:
        """Evaluate liveness once and send an alert if the gate says so."""
        health = self._settings.health
        now = self._now() if self._now is not None else None
        liveness = evaluate_liveness(
            self._heartbeat_path(),
            max_age_sec=health.liveness.heartbeat_max_age_sec,
            startup_started_at=self._startup_started_at(),
            startup_grace_sec=health.startup_grace_sec,
            max_readiness_miss_sec=health.liveness.max_readiness_miss_sec,
            now=now,
        )
        previous = self._state
        decision = evaluate_liveness_alert(
            liveness,
            previous=previous,
            min_unhealthy_sec=health.alert.min_unhealthy_sec,
            min_consecutive_failures=health.alert.min_consecutive_failures,
            now=now or _utc_now(),
        )
        if decision.message is None:
            self._state = decision.state
            return None
        try:
            self._send(decision.message)
        except Exception:
            # Keep the previous `notified` flag so the next poll retries this
            # message. Advancing it here would burn the only page for the
            # episode and leave the operator with just a recovery notice.
            logger.exception("Failed to send runtime health alert")
            self._state = replace(decision.state, notified=previous.notified)
            return None
        self._state = decision.state
        return decision.message

    def _run(self) -> None:
        interval = max(1, int(self._settings.health.alert.poll_interval_sec))
        while not self._stop.wait(interval):
            try:
                _ = self.poll_once()
            except Exception:
                logger.exception("Liveness watchdog poll failed")

    def start(self) -> None:
        if not self._settings.health.alert.enabled:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="polysignal-liveness-watchdog",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is None:
            return
        thread.join(timeout=5.0)
        if thread.is_alive():
            # Join timed out — most likely blocked on a slow alert send.
            # Keep the handle so a later start() cannot clear the stop flag
            # and race a second thread against this one's state.
            logger.warning("Liveness watchdog did not stop within 5s")
            return
        self._thread = None
