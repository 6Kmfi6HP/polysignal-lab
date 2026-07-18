"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Mapping, typing, typing.Protocol, polysignal_lab.alpha.types, polysignal_lab.alpha.types.AlphaDecision, polysignal_lab.alpha.types.MarketView, polysignal_lab.domain.enums
Output: should_notify_fill, handle_order_lifecycle_event, handle_order_filled, handle_position_event, handle_position_closed, _OrderEventStrategy
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from collections.abc import Iterable, Mapping
import math
from typing import Protocol, cast

from nautilus_trader.core.nautilus_pyo3 import PositionId

from polysignal_lab.alpha.types import AlphaDecision, MarketView
from polysignal_lab.domain.enums import OrderIntent
from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.projections import _tags
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
    cache: object | None
    registry: MarketCatalog | None
    strategy_name: str
    observability: object | None
    _active_condition_ids: set[str]
    _settled_position_keys: set[tuple[str, str]]

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


def _order_from_cache(
    strategy: _OrderEventStrategy,
    event: object,
) -> object | None:
    client_order_id = getattr(event, "client_order_id", None)
    cache = cast(object | None, getattr(strategy, "cache", None))
    if client_order_id is None or cache is None:
        return None
    getter = getattr(cache, "order", None)
    if not callable(getter):
        return None
    try:
        return getter(client_order_id)
    except (LookupError, TypeError, ValueError, AttributeError):
        return None


def _has_usable_tags(source: object) -> bool:
    tags = _tags(getattr(source, "tags", None))
    return bool(tags.get("strategy")) and bool(tags.get("condition_id"))


def _association_order(
    strategy: _OrderEventStrategy,
    event: object,
) -> tuple[object | None, bool]:
    order = _order_from_cache(strategy, event)
    resolved = order is not None and _has_usable_tags(order)
    if not resolved:
        strategy._note_runtime_progress("order_event_unresolved")
    return order, resolved


def handle_order_lifecycle_event(
    strategy: _OrderEventStrategy,
    method_name: str,
    event: object,
    *,
    forget_metrics: bool = False,
) -> None:
    _ = method_name, forget_metrics  # no core on_order_* / metrics tracker
    strategy._note_runtime_progress("order_event")
    order, resolved = _association_order(strategy, event)
    if not resolved:
        return
    try:
        metrics = project_order_metrics(
            event,
            registry=strategy.registry,
            strategy_name=strategy.strategy_name,
            order=order,
        )
    except ValueError:
        strategy._note_runtime_progress("order_event_quarantined")
        return
    strategy._record_nautilus_order(event, metrics)


def handle_order_filled(strategy: _OrderEventStrategy, event: object) -> None:
    strategy._note_runtime_progress("order_event")
    order, resolved = _association_order(strategy, event)
    if not resolved:
        strategy._note_runtime_progress("fill_event_quarantined")
        return
    try:
        metrics = project_fill_metrics(
            event,
            registry=strategy.registry,
            strategy_name=strategy.strategy_name,
            order=order,
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
        _record_completed_early_exit(strategy, metrics)
        return
    # Production cores do not implement on_order_filled; no follow-up decisions.


def _record_completed_early_exit(
    strategy: _OrderEventStrategy,
    metrics: Mapping[str, object],
) -> None:
    position_id = str(metrics.get("position_id") or "")
    if not position_id:
        strategy._note_runtime_progress("early_exit_result_quarantined")
        return
    try:
        cache_position_id = PositionId.from_str(position_id)
    except ValueError:
        strategy._note_runtime_progress("early_exit_result_quarantined")
        return
    settlement_key = (
        strategy.strategy_name,
        position_id,
    )
    if settlement_key in strategy._settled_position_keys:
        strategy._note_runtime_progress("early_exit_result_duplicate")
        return
    position = _cache_position(strategy, cache_position_id)
    if position is None or not bool(getattr(position, "is_closed", False)):
        strategy._note_runtime_progress("early_exit_result_pending")
        return
    exit_orders = _exit_orders_for_position(strategy, cache_position_id)
    if exit_orders is None:
        strategy._note_runtime_progress("early_exit_result_quarantined")
        return
    priced_fills = _priced_exit_fills(exit_orders)
    fill_quantity = sum(quantity for quantity, _ in priced_fills)
    fill_price = _exit_fill_price(priced_fills, position)
    payload = dict(metrics)
    if fill_quantity > 0:
        payload["shares"] = fill_quantity
    if fill_price is not None:
        payload["fill_price"] = fill_price
    if _record_early_exit_result(strategy, payload):
        strategy._settled_position_keys.add(settlement_key)


def _priced_exit_fills(
    exit_orders: Iterable[object],
) -> tuple[tuple[float, float | None], ...]:
    return tuple(
        (quantity, _positive_number(getattr(item, "avg_px", None)))
        for item in exit_orders
        if (quantity := _positive_number(getattr(item, "filled_qty", None))) is not None
    )


def _exit_fill_price(
    priced_fills: tuple[tuple[float, float | None], ...],
    position: object,
) -> float | None:
    if priced_fills and all(price is not None for _, price in priced_fills):
        quantity = sum(fill_quantity for fill_quantity, _ in priced_fills)
        notional = sum(
            fill_quantity * price
            for fill_quantity, price in priced_fills
            if price is not None
        )
        return notional / quantity
    return _positive_number(getattr(position, "avg_px_close", None))


def _positive_number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    candidate = value
    for name in ("as_double", "as_decimal"):
        converter = getattr(value, name, None)
        if callable(converter):
            candidate = converter()
            break
    try:
        number = float(str(candidate))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _record_early_exit_result(
    strategy: _OrderEventStrategy,
    metrics: Mapping[str, object],
) -> bool:
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
        strategy._note_runtime_progress("early_exit_result_quarantined")
        return False
    observability = strategy.observability
    if observability is None:
        return False
    recorder = getattr(observability, "record_event", None)
    if not callable(recorder):
        return False
    try:
        created = recorder("settlements", result)
        if created is False:
            strategy._note_runtime_progress("early_exit_result_duplicate")
            return True
        strategy._note_runtime_progress("early_exit_result")
    except Exception:
        strategy._note_runtime_progress("early_exit_result_failed")
        return False
    notify = getattr(observability, "notify_report_result", None)
    if callable(notify):
        try:
            notify(result)
        except Exception:
            strategy._note_runtime_progress("early_exit_result_publish_failed")
    return True


def _exit_orders_for_position(
    strategy: _OrderEventStrategy,
    position_id: object,
) -> tuple[object, ...] | None:
    cache = getattr(strategy, "cache", None)
    getter = getattr(cache, "orders_for_position", None)
    if not callable(getter):
        return None
    try:
        orders = getter(position_id)
    except (LookupError, TypeError, ValueError, AttributeError):
        return None
    if not isinstance(orders, Iterable):
        return None
    return tuple(
        order
        for order in orders
        if str(_tags(getattr(order, "tags", None)).get("reduce_only", "")).lower()
        in {"1", "true", "yes"}
    )


def _cache_position(
    strategy: _OrderEventStrategy,
    position_id: object,
) -> object | None:
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
    return _cache_position(strategy, position_id)


def handle_position_event(strategy: _OrderEventStrategy, event: object) -> None:
    position = _position_from_event(strategy, event)
    if position is None:
        strategy._note_runtime_progress("position_event_unresolved")
        return
    strategy._record_nautilus_position(position)


def handle_position_closed(strategy: _OrderEventStrategy, event: object) -> None:
    handle_position_event(strategy, event)
