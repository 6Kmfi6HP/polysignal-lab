"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Mapping, typing, typing.Protocol, polysignal_lab.alpha.types, polysignal_lab.alpha.types.AlphaDecision, polysignal_lab.alpha.types.MarketView, polysignal_lab.domain.enums
Output: should_notify_fill, handle_order_lifecycle_event, handle_order_filled, handle_position_event, handle_position_closed, _OrderEventStrategy
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from polysignal_lab.alpha.types import AlphaDecision, MarketView
from polysignal_lab.domain.enums import OrderIntent
from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.strategy.event_projection import (
    fill_side,
    fill_ts_event,
    project_fill_metrics,
    project_order_metrics,
)
from polysignal_lab.reporting.exit_result import report_result_from_early_exit
from polysignal_lab.utils import utc_iso


class _OrderEventStrategy(Protocol):
    core: object
    registry: MarketCatalog | None
    strategy_name: str
    observability: object | None
    _active_condition_ids: set[str]

    def _note_runtime_progress(self, phase: str) -> None: ...
    def _record_nautilus_order(
        self, event: object, metrics: Mapping[str, object]
    ) -> None: ...
    def _record_nautilus_fill(
        self, event: object, metrics: Mapping[str, object]
    ) -> None: ...
    def _record_nautilus_position(self, position: object) -> None: ...
    def _require_assembler(self) -> object: ...
    def _handle_decision(self, decision: AlphaDecision, view: MarketView) -> None: ...


def should_notify_fill(strategy: _OrderEventStrategy, metrics: Mapping[str, object]) -> bool:
    if str(metrics.get("strategy") or strategy.strategy_name) != "vwap_momentum":
        return True
    intent = metrics.get("order_intent")
    if isinstance(intent, OrderIntent):
        intent = intent.value
    return not (
        bool(metrics.get("hedge_leg"))
        or intent == OrderIntent.PASSIVE_GTD.value
    )


def handle_order_lifecycle_event(
    strategy: _OrderEventStrategy,
    method_name: str,
    event: object,
    *,
    forget_metrics: bool = False,
) -> None:
    _ = method_name, forget_metrics  # no core on_order_* / metrics tracker
    strategy._note_runtime_progress("order_event")
    try:
        metrics = project_order_metrics(
            event,
            registry=strategy.registry,
            strategy_name=strategy.strategy_name,
        )
    except ValueError:
        strategy._note_runtime_progress("order_event_quarantined")
        return
    strategy._record_nautilus_order(event, metrics)


def handle_order_filled(strategy: _OrderEventStrategy, event: object) -> None:
    strategy._note_runtime_progress("order_event")
    try:
        metrics = project_fill_metrics(
            event,
            registry=strategy.registry,
            strategy_name=strategy.strategy_name,
        )
    except ValueError:
        strategy._note_runtime_progress("fill_event_quarantined")
        return
    if should_notify_fill(strategy, metrics):
        notify = getattr(strategy.core, "on_notify_fill", None)
        if callable(notify):
            side = fill_side(metrics)
            shares = float(metrics.get("shares") or 0.0)
            _ = notify(str(metrics.get("market_id") or ""), side, shares)
    strategy._record_nautilus_fill(event, metrics)
    if bool(metrics.get("reduce_only")):
        _record_early_exit_result(strategy, metrics)
        return
    # Production cores do not implement on_order_filled; no follow-up decisions.


def _record_early_exit_result(
    strategy: _OrderEventStrategy,
    metrics: Mapping[str, object],
) -> None:
    """Persist Reporting Truth for NativeExitPolicy reduce-only closes."""
    payload = dict(metrics)
    side = fill_side(payload)
    if "side" not in payload and side is not None:
        payload["side"] = side.value
    for key in ("market_id", "condition_id", "token_id", "strategy"):
        if payload.get(key) in (None, ""):
            continue
    payload.setdefault("owning_strategy", strategy.strategy_name)
    ts = fill_ts_event(payload)
    closed_at = None
    if ts is not None:
        try:
            closed_at = ts.isoformat()
        except AttributeError:
            closed_at = None
    result = report_result_from_early_exit(
        payload,
        fill_price=float(payload.get("fill_price") or 0.0),
        fill_shares=float(payload.get("shares") or 0.0),
        strategy_name=strategy.strategy_name,
        closed_at=closed_at or utc_iso(),
    )
    if result is None:
        return
    observability = strategy.observability
    if observability is None:
        return
    recorder = getattr(observability, "record_event", None)
    if not callable(recorder):
        return
    try:
        recorder("settlements", result)
        strategy._note_runtime_progress("early_exit_result")
    except Exception:
        strategy._note_runtime_progress("early_exit_result_failed")
        return
    notify = getattr(observability, "notify_report_result", None)
    if callable(notify):
        try:
            notify(result)
        except Exception:
            strategy._note_runtime_progress("early_exit_result_publish_failed")


def _position_from_event(strategy: _OrderEventStrategy, event: object) -> object | None:
    """Resolve Cache Position via event.position_id — never treat PositionEvent as Position."""
    position_id = getattr(event, "position_id", None)
    if position_id is None:
        if (
            getattr(event, "instrument_id", None) is not None
            or getattr(event, "is_closed", None) is not None
            or getattr(event, "signed_qty", None) is not None
        ):
            return event
        return None
    cache = getattr(strategy, "cache", None)
    if cache is None:
        return None
    getter = getattr(cache, "position", None)
    if not callable(getter):
        return None
    try:
        return getter(position_id)
    except (LookupError, TypeError, ValueError, AttributeError):
        return None


def handle_position_event(strategy: _OrderEventStrategy, event: object) -> None:
    position = _position_from_event(strategy, event)
    if position is None:
        strategy._note_runtime_progress("position_event_unresolved")
        return
    strategy._record_nautilus_position(position)


def handle_position_closed(strategy: _OrderEventStrategy, event: object) -> None:
    handle_position_event(strategy, event)
