"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Mapping, datetime, datetime.datetime, typing, typing.Any, polysignal_lab.domain.enums, polysignal_lab.domain.enums.Side
Output: metrics_from_tags, project_order_metrics, project_fill_metrics, event_lookup_ids, fill_ts_event, fill_side
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.custom_data_state import event_datetime
from polysignal_lab.nautilus_runtime.strategy.helpers import (
    _condition_id_from_catalog_instrument,
    _event_side,
    _identifier_text,
    _lookup_id_text,
    _market_id_for_condition,
    _maybe_float,
    _optional_str,
    _tags,
    _token_id_from_catalog_instrument,
    _value,
)


def metrics_from_tags(event: object) -> dict[str, object]:
    """Recover signal metrics from Cache order tags (sole association path)."""
    tags = _tags(_value(event, "tags"))
    metrics: dict[str, object] = {}
    for key, value in tags.items():
        if value not in (None, ""):
            metrics[key] = value
    if tags.get("reduce_only") is not None:
        metrics["reduce_only"] = str(tags.get("reduce_only")).lower() in {
            "1",
            "true",
            "yes",
        }
    if tags.get("hedge_leg") is not None:
        metrics["hedge_leg"] = str(tags.get("hedge_leg")).lower() in {
            "1",
            "true",
            "yes",
        }
    return metrics


def project_order_metrics(
    event: object,
    *,
    registry: MarketCatalog | None,
    strategy_name: str,
) -> dict[str, object]:
    """Typed Nautilus-event → reporting metrics dict (unique projection path)."""
    tags = _tags(_value(event, "tags"))
    metrics = metrics_from_tags(event)
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
    side = _event_side(registry, instrument_id, token_id, _value(event, "side"))
    metrics.update(
        {
            "strategy": tags.get("strategy")
            or str(metrics.get("strategy") or strategy_name),
            "market_id": market_id or str(_value(event, "market_id", "")),
            "condition_id": condition_id or str(_value(event, "condition_id", "")),
            "token_id": token_id or str(_value(event, "token_id", instrument_id or "")),
            "side": getattr(side, "value", side) if side is not None else metrics.get("side"),
            "order_id": str(_value(event, "order_id", _value(event, "id", ""))),
            "client_order_id": _optional_str(_value(event, "client_order_id")),
            "reason": _optional_str(_value(event, "reason")),
            "ts_event": event_datetime(
                _value(event, "ts_event", _value(event, "timestamp"))
            ),
        }
    )
    return metrics


def project_fill_metrics(
    event: object,
    *,
    registry: MarketCatalog | None,
    strategy_name: str,
) -> dict[str, object]:
    metrics = project_order_metrics(
        event, registry=registry, strategy_name=strategy_name
    )
    fill_price = _maybe_float(
        _value(event, "fill_price", _value(event, "last_px", _value(event, "price")))
    )
    if fill_price is None or fill_price <= 0.0:
        raise ValueError("missing positive fill price; refusing fabricated execution truth")
    metrics["fill_price"] = fill_price
    metrics["shares"] = (
        _maybe_float(
            _value(event, "shares", _value(event, "last_qty", _value(event, "quantity")))
        )
        or 0.0
    )
    metrics["liquidity_side"] = _optional_str(_value(event, "liquidity_side"))
    return metrics


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


def fill_ts_event(metrics: Mapping[str, Any]) -> datetime | None:
    raw = metrics.get("ts_event")
    return raw if isinstance(raw, datetime) else None


def fill_side(metrics: Mapping[str, Any]) -> Side | None:
    raw = metrics.get("side")
    if isinstance(raw, Side):
        return raw
    if raw is None:
        return None
    try:
        return Side(str(raw))
    except ValueError:
        return None
