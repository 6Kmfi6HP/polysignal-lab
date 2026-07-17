"""
Input: __future__, __future__.annotations, collections.abc, datetime, types, polysignal_lab.alpha.types, polysignal_lab.domain.enums, polysignal_lab.nautilus_bridge.market_catalog
Output: project_order_event, project_fill_event, project_nautilus_order_event, project_nautilus_fill_event, ApprovedSignalMetricsTracker
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import SimpleNamespace
from typing import cast

from polysignal_lab.alpha.types import AlphaFillEvent, AlphaOrderEvent
from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.decision_policy import ApprovedDecision
from polysignal_lab.nautilus_runtime.strategy.helpers import (
    _condition_id_from_catalog_instrument,
    event_datetime,
    _event_side,
    _fallback_fill_price,
    _identifier_text,
    _lookup_id_text,
    _market_id_for_condition,
    _maybe_float,
    _optional_str,
    _tags,
    _token_id_from_catalog_instrument,
    _value,
)


def project_nautilus_order_event(
    event: object, metrics: Mapping[str, object]
) -> SimpleNamespace:
    status = _value(event, "status")
    if status in (None, ""):
        event_name = type(event).__name__
        if event_name.startswith("Order"):
            status = event_name.removeprefix("Order").upper()
    quantity = _value(event, "quantity")
    price = _value(event, "price")
    if _maybe_float(quantity) in (None, 0.0):
        quantity = metrics.get("contracts", metrics.get("quantity", quantity))
    if _maybe_float(price) in (None, 0.0):
        price = metrics.get(
            "level_price",
            metrics.get("up_ask", metrics.get("down_ask", metrics.get("price", price))),
        )
    return SimpleNamespace(
        event_id=_value(event, "id") or _value(event, "event_id"),
        client_order_id=_value(event, "client_order_id"),
        instrument_id=_value(event, "instrument_id"),
        order_side=_value(event, "order_side"),
        order_type=_value(event, "order_type"),
        time_in_force=_value(event, "time_in_force"),
        quantity=quantity,
        price=price,
        status=status,
        tags=_value(event, "tags", ()),
        metrics=dict(metrics),
        ts_event=_value(event, "ts_event", _value(event, "timestamp")),
        event_type_name=type(event).__name__,
    )


def project_nautilus_fill_event(
    event: object, metrics: Mapping[str, object]
) -> SimpleNamespace:
    return SimpleNamespace(
        event_id=_value(event, "id") or _value(event, "event_id"),
        client_order_id=_value(event, "client_order_id"),
        instrument_id=_value(event, "instrument_id"),
        trade_id=_value(event, "trade_id", _value(event, "fill_id")),
        last_qty=_value(
            event, "last_qty", _value(event, "shares", _value(event, "quantity"))
        ),
        last_px=_value(
            event, "last_px", _value(event, "fill_price", _value(event, "price"))
        ),
        liquidity_side=_value(event, "liquidity_side"),
        tags=_value(event, "tags", ()),
        metrics=dict(metrics),
        ts_event=_value(event, "ts_event", _value(event, "timestamp")),
    )


def project_order_event(
    event: object,
    *,
    registry: MarketCatalog | None,
    strategy_name: str,
    metrics_lookup: Callable[[object], Mapping[str, object]],
) -> AlphaOrderEvent:
    tags = _tags(_value(event, "tags"))
    metrics = dict(metrics_lookup(event))
    instrument_id = _identifier_text(_value(event, "instrument_id"))
    condition_id = tags.get("condition_id") or _optional_str(metrics.get("condition_id"))
    if not condition_id and registry is not None and instrument_id is not None:
        condition_id = _condition_id_from_catalog_instrument(
            registry, registry.condition_ids(), instrument_id
        )
    market_id = tags.get("market_id") or _optional_str(metrics.get("market_id"))
    if not market_id and registry is not None and condition_id is not None:
        market_id = _market_id_for_condition(registry, condition_id)
    token_id = tags.get("token_id") or _optional_str(metrics.get("token_id"))
    if (
        not token_id
        and registry is not None
        and condition_id is not None
        and instrument_id is not None
    ):
        token_id = _token_id_from_catalog_instrument(registry, condition_id, instrument_id)
    price = _maybe_float(_value(event, "price"))
    if "level_price" not in metrics and price is not None:
        metrics["level_price"] = price
    if "order_intent" not in metrics and tags.get("order_intent"):
        metrics["order_intent"] = tags["order_intent"]
    if "hedge_leg" not in metrics and tags.get("hedge_leg"):
        metrics["hedge_leg"] = tags["hedge_leg"] == "true"
    if "reduce_only" not in metrics and tags.get("reduce_only"):
        metrics["reduce_only"] = tags["reduce_only"] == "true"
    return AlphaOrderEvent(
        strategy=tags.get("strategy") or str(metrics.get("strategy") or strategy_name),
        market_id=market_id or str(_value(event, "market_id", "")),
        condition_id=condition_id or str(_value(event, "condition_id", "")),
        token_id=token_id or str(_value(event, "token_id", instrument_id or "")),
        side=_event_side(registry, instrument_id, token_id, _value(event, "side")),
        order_id=str(_value(event, "order_id", _value(event, "id", ""))),
        client_order_id=_optional_str(_value(event, "client_order_id")),
        reason=_optional_str(_value(event, "reason")),
        ts_event=event_datetime(_value(event, "ts_event", _value(event, "timestamp"))),
        metrics=metrics,
    )


def project_fill_event(
    event: object,
    *,
    registry: MarketCatalog | None,
    strategy_name: str,
    metrics_lookup: Callable[[object], Mapping[str, object]],
) -> AlphaFillEvent:
    order = project_order_event(
        event,
        registry=registry,
        strategy_name=strategy_name,
        metrics_lookup=metrics_lookup,
    )
    metrics = dict(order.metrics)
    fill_price = _maybe_float(
        _value(event, "fill_price", _value(event, "last_px", _value(event, "price")))
    )
    if fill_price is None or fill_price <= 0.0:
        fill_price = _fallback_fill_price(metrics, _tags(_value(event, "tags")), order.side)
    if fill_price is not None:
        metrics["fill_price"] = fill_price
    shares = (
        _maybe_float(
            _value(event, "shares", _value(event, "last_qty", _value(event, "quantity")))
        )
        or 0.0
    )
    return AlphaFillEvent(
        strategy=order.strategy,
        market_id=order.market_id,
        condition_id=order.condition_id,
        token_id=order.token_id,
        side=order.side,
        order_id=order.order_id,
        client_order_id=order.client_order_id,
        reason=order.reason,
        ts_event=order.ts_event,
        metrics=metrics,
        fill_price=fill_price or 0.0,
        shares=shares,
        liquidity_side=_optional_str(_value(event, "liquidity_side")),
    )


def event_lookup_ids(event: object) -> tuple[str, ...]:
    tags = _tags(_value(event, "tags"))
    values = (
        _value(event, "order_id"),
        _value(event, "client_order_id"),
        _value(event, "id"),
        tags.get("signal_id"),
        tags.get("order_id"),
        tags.get("client_order_id"),
    )
    return tuple(
        text for text in (_lookup_id_text(value) for value in values) if text is not None
    )


class ApprovedSignalMetricsTracker:
    """Track approved-signal metadata keyed by order identifiers."""

    def __init__(self) -> None:
        self._approved_signal_metrics: dict[str, dict[str, object]] = {}

    def metrics_for_event(self, event: object) -> dict[str, object]:
        for key in event_lookup_ids(event):
            metrics = self._approved_signal_metrics.get(key)
            if metrics is not None:
                return dict(metrics)
        return {}

    def remember(self, order: object, approved: ApprovedDecision) -> None:
        signal = approved.signal
        metrics: dict[str, object] = dict(
            cast(Mapping[str, object], getattr(signal, "metrics", {}) or {})
        )
        _ = metrics.setdefault("dedupe_key", signal.dedupe_key)
        _ = metrics.setdefault("reduce_only", bool(getattr(signal, "reduce_only", False)))
        signal_side = cast(object, getattr(signal, "side", None))
        signal_fields: dict[str, object] = {
            "signal_id": getattr(signal, "signal_id", None),
            "strategy": getattr(signal, "strategy", None),
            "asset": getattr(signal, "asset", None),
            "timeframe": getattr(signal, "timeframe", None),
            "market_id": getattr(signal, "market_id", None),
            "market_slug": getattr(signal, "market_slug", None),
            "condition_id": getattr(signal, "condition_id", None),
            "token_id": getattr(signal, "token_id", None),
            "side": getattr(signal_side, "value", signal_side),
        }
        for key, value in signal_fields.items():
            if value not in (None, ""):
                _ = metrics.setdefault(key, value)
        tags = _tags(_value(order, "tags"))
        values = (
            _value(order, "id"),
            _value(order, "client_order_id"),
            getattr(signal, "signal_id", None),
            tags.get("signal_id"),
            tags.get("order_id"),
            tags.get("client_order_id"),
        )
        for value in values:
            text = _lookup_id_text(value)
            if text is not None:
                self._approved_signal_metrics[text] = dict(metrics)

    def forget(self, event: object, order: AlphaOrderEvent) -> None:
        keys = set(event_lookup_ids(event))
        if order.order_id:
            keys.add(order.order_id)
        if order.client_order_id:
            keys.add(order.client_order_id)
        for key in keys:
            self._approved_signal_metrics.pop(key, None)
