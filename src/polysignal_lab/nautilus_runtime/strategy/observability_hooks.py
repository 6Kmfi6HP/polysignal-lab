from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from typing import Protocol

from polysignal_lab.alpha.types import AlphaDecision
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_runtime.decision_policy import RejectedDecision
from polysignal_lab.nautilus_runtime.strategy.protocols import _Observability


class _ObservabilityStrategy(Protocol):
    observability: _Observability | None
    fixed_stake_usdc: float

    def _note_runtime_progress(self, phase: str) -> None: ...


def record_observability(
    strategy: _ObservabilityStrategy,
    action: Callable[[_Observability], None],
) -> None:
    observability = strategy.observability
    if observability is None:
        return
    try:
        action(observability)
    except (OSError, sqlite3.Error):
        strategy._note_runtime_progress("telemetry_side_effect_failed")


def record_signal(strategy: _ObservabilityStrategy, signal: SignalCandidate) -> None:
    recorder = (
        None
        if strategy.observability is None
        else getattr(strategy.observability, "record_signal", None)
    )
    if callable(recorder):
        _ = recorder(signal)


def notify_accepted_signal(
    strategy: _ObservabilityStrategy, signal: SignalCandidate
) -> None:
    notifier = (
        None
        if strategy.observability is None
        else getattr(strategy.observability, "notify_accepted_signal", None)
    )
    if callable(notifier):
        _ = notifier(signal, strategy.fixed_stake_usdc)


def record_decision(
    strategy: _ObservabilityStrategy,
    decision: AlphaDecision,
    *,
    accepted: bool,
) -> None:
    record_observability(
        strategy,
        lambda obs: obs.record_decision(decision, accepted),
    )


def record_rejected(
    strategy: _ObservabilityStrategy,
    rejected: RejectedDecision,
) -> None:
    record_observability(
        strategy,
        lambda obs: obs.record_rejected_decision(rejected),
    )


def record_nautilus_order(
    strategy: _ObservabilityStrategy,
    event: object,
    metrics: Mapping[str, object],
) -> None:
    record_observability(
        strategy,
        lambda obs: obs.record_nautilus_order_event(event, metrics),
    )


def record_nautilus_fill(
    strategy: _ObservabilityStrategy,
    event: object,
    metrics: Mapping[str, object],
) -> None:
    record_observability(
        strategy,
        lambda obs: obs.record_nautilus_fill_event(event, metrics),
    )


def record_nautilus_position(
    strategy: _ObservabilityStrategy, position: object
) -> None:
    record_observability(
        strategy,
        lambda obs: obs.record_nautilus_position(position),
    )
