"""
Input: __future__, logging, datetime, concurrent.futures, nautilus_trader.core.nautilus_pyo3
Output: ReportingHousekeepingActor, REPORT_TIMER_NAME
Pos: Read-only reporting/settlement lifecycle on Nautilus clock

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import date, timedelta
from typing import cast

from nautilus_trader.core.nautilus_pyo3 import DataActor

logger = logging.getLogger("polysignal_lab.nautilus.reporting")

_REPORTING_ACTOR_ID = "PolySignal-Reporting"
REPORT_TIMER_NAME = "reporting_housekeeping"


class _ReportingHousekeepingWorker:
    """Blocking IO boundary for settlement/report projections (no trading state)."""

    def __init__(self, services: object) -> None:
        self._services = services
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="polysignal-reporting",
        )
        self._future: Future[date | None] | None = None
        self._closed = False

    def request(self, last_report_date: date | None) -> bool:
        if self._closed or self._future is not None:
            return False
        self._future = self._executor.submit(self._run, last_report_date)
        return True

    def take_result(self) -> date | None | object:
        future = self._future
        if future is None or not future.done():
            return _PENDING
        self._future = None
        return future.result()

    def close(self) -> None:
        self._closed = True
        future = self._future
        self._future = None
        if future is not None:
            _ = future.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run(self, last_report_date: date | None) -> date | None:
        from polysignal_lab.nautilus_runtime.signal_sidecar import (
            _run_nautilus_housekeeping_once,
        )

        return asyncio.run(_run_nautilus_housekeeping_once(self._services, last_report_date))


_PENDING = object()


class ReportingHousekeepingActor(DataActor):
    """Nautilus-clock-driven reporting/settlement; never owns trading state."""

    def __new__(cls, *args: object, **kwargs: object):
        return super().__new__(cls)

    def __init__(
        self,
        config: object | None = None,
        *,
        services: object | None = None,
        interval_sec: float | None = None,
    ) -> None:
        from nautilus_trader.core.nautilus_pyo3 import ActorId, DataActorConfig

        if config is None:
            config = DataActorConfig(actor_id=ActorId(_REPORTING_ACTOR_ID))
        if services is None:
            raise RuntimeError("ReportingHousekeepingActor requires read-only services")
        DataActor.__init__(self, config)
        self._services = services
        settings = getattr(services, "settings", None)
        markets = getattr(settings, "markets", None) if settings is not None else None
        default_interval = float(getattr(markets, "refresh_interval_sec", 60) or 60)
        self._interval_sec = max(float(interval_sec or default_interval), 1.0)
        self._worker = _ReportingHousekeepingWorker(services)
        self._last_report_date: date | None = None

    def on_start(self) -> None:
        clock = getattr(self, "clock", None)
        set_timer = getattr(clock, "set_timer", None)
        if not callable(set_timer):
            raise RuntimeError("Nautilus actor clock is required for reporting housekeeping")
        _ = set_timer(
            REPORT_TIMER_NAME,
            timedelta(seconds=self._interval_sec),
            callback=self._on_report_timer,
        )
        # Kick once immediately so late node start still runs projections.
        _ = self._worker.request(self._last_report_date)

    def on_stop(self) -> None:
        try:
            clock = getattr(self, "clock", None)
            cancel_timer = getattr(clock, "cancel_timer", None)
            if callable(cancel_timer):
                _ = cancel_timer(REPORT_TIMER_NAME)
        finally:
            self._worker.close()

    def _on_report_timer(self, _event: object = None) -> None:
        result = self._worker.take_result()
        if result is not _PENDING:
            self._last_report_date = cast(date | None, result)
        if not self._worker.request(self._last_report_date):
            return
