"""Data-driven recovery regression tests.

nautilus 1.231 timer callbacks do not fire under ``LiveNode.run()`` (verified
live: the strategy evaluation heartbeat stays silent for whole runs), so the
10s recovery/reconcile heartbeat never executes and DOWN-side book stalls are
never repaired. ``maybe_run_data_driven_recovery`` drives the same logic from
data callbacks (which do fire under ``run()``), throttled to the heartbeat
interval. These tests pin that throttle and the integration point.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

import pytest

from polysignal_lab.nautilus_runtime.strategy import lifecycle as life
from polysignal_lab.nautilus_runtime.strategy.constants import (
    EVALUATION_HEARTBEAT_INTERVAL,
)


class _FakeClock:
    """Wall clock whose time the test controls."""

    def __init__(self, start_ns: int = 1_700_000_000_000_000_000) -> None:
        self._ns = start_ns

    def timestamp_ns(self) -> int:
        return self._ns

    def advance_sec(self, seconds: float) -> None:
        self._ns += int(seconds * 1_000_000_000)


class _DataDrivenStrategy:
    """Minimal duck-typed strategy for the throttle integration point."""

    def __init__(self) -> None:
        self.clock = _FakeClock()
        self._last_data_driven_recovery_at: datetime | None = None
        self._active_condition_ids: set[str] = set()
        self._data_driven_recovery_disabled: bool = False
        self._subscriptions_started: bool = True


def _now(strategy: _DataDrivenStrategy) -> datetime:
    return life.framework_now(cast(Any, strategy))


def test_data_driven_recovery_fires_on_first_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(life, "on_evaluation_heartbeat", lambda s, e: calls.append(s))
    strategy = _DataDrivenStrategy()

    life.maybe_run_data_driven_recovery(cast(Any, strategy), now=_now(strategy))

    assert len(calls) == 1
    assert strategy._last_data_driven_recovery_at is not None


def test_data_driven_recovery_throttles_within_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(life, "on_evaluation_heartbeat", lambda s, e: calls.append(s))
    strategy = _DataDrivenStrategy()

    life.maybe_run_data_driven_recovery(cast(Any, strategy), now=_now(strategy))
    life.maybe_run_data_driven_recovery(cast(Any, strategy), now=_now(strategy))
    # Just inside the interval.
    strategy.clock.advance_sec(EVALUATION_HEARTBEAT_INTERVAL.total_seconds() - 1)
    life.maybe_run_data_driven_recovery(cast(Any, strategy), now=_now(strategy))

    assert len(calls) == 1


def test_data_driven_recovery_refires_after_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(life, "on_evaluation_heartbeat", lambda s, e: calls.append(s))
    strategy = _DataDrivenStrategy()

    life.maybe_run_data_driven_recovery(cast(Any, strategy), now=_now(strategy))
    strategy.clock.advance_sec(EVALUATION_HEARTBEAT_INTERVAL.total_seconds() + 0.1)
    life.maybe_run_data_driven_recovery(cast(Any, strategy), now=_now(strategy))

    assert len(calls) == 2


def test_data_driven_recovery_respects_disabled_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(life, "on_evaluation_heartbeat", lambda s, e: calls.append(s))
    strategy = _DataDrivenStrategy()
    strategy._data_driven_recovery_disabled = True

    life.maybe_run_data_driven_recovery(cast(Any, strategy), now=_now(strategy))

    assert len(calls) == 0


def test_data_driven_recovery_uses_injected_now(monkeypatch: pytest.MonkeyPatch) -> None:
    """The optional ``now`` short-circuits the clock, so two calls with the same
    timestamp never double-fire even if the clock is identical."""
    calls: list[object] = []
    monkeypatch.setattr(life, "on_evaluation_heartbeat", lambda s, e: calls.append(s))
    strategy = _DataDrivenStrategy()

    life.maybe_run_data_driven_recovery(cast(Any, strategy), now=_now(strategy))
    life.maybe_run_data_driven_recovery(cast(Any, strategy), now=_now(strategy))

    assert len(calls) == 1
