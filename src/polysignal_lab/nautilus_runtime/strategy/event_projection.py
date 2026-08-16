from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import math
from typing import Any

from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.custom_data_state import event_datetime
from polysignal_lab.nautilus_runtime.projections import _tags
from polysignal_lab.nautilus_runtime.strategy.catalog_lookups import (
    _condition_id_from_catalog_instrument,
    _event_side,
    _market_id_for_condition,
    _token_id_from_catalog_instrument,
)
from polysignal_lab.nautilus_runtime.strategy.nautilus_objects import (
    _identifier_text,
    _lookup_id_text,
    _maybe_float,
    _optional_str,
    _value,
)


def _merged_tags(event: object, order: object | None) -> dict[str, str]:
    cached = _tags(_value(order, "tags")) if order is not None else {}
    event_tags = _tags(_value(event, "tags"))
    return {
        **cached,
        **{key: value for key, value in event_tags.items() if value not in (None, "")},
    }


def metrics_from_tags(
    event: object,
    *,
    order: object | None = None,
) -> dict[str, object]:
    """Recover signal metrics from the Cache-owned Order tags."""
    tags = _merged_tags(event, order)
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


def _association_ids(
    event: object,
    registry: MarketCatalog | None,
    tags: Mapping[str, object],
    metrics: Mapping[str, object],
) -> tuple[str | None, str | None, str | None, str | None]:
    instrument_id = _identifier_text(_value(event, "instrument_id"))
    condition_id = _optional_str(
        tags.get("condition_id") or metrics.get("condition_id")
    )
    if not condition_id and registry is not None and instrument_id is not None:
        condition_id = _condition_id_from_catalog_instrument(
            registry, registry.condition_ids(), instrument_id
        )
    market_id = _optional_str(tags.get("market_id") or metrics.get("market_id"))
    if not market_id and registry is not None and condition_id is not None:
        market_id = _market_id_for_condition(registry, condition_id)
    token_id = _optional_str(tags.get("token_id") or metrics.get("token_id"))
    if not token_id and registry is not None and condition_id and instrument_id:
        token_id = _token_id_from_catalog_instrument(
            registry, condition_id, instrument_id
        )
    return instrument_id, condition_id, market_id, token_id


def project_order_metrics(
    event: object,
    *,
    registry: MarketCatalog | None,
    strategy_name: str,
    order: object | None = None,
) -> dict[str, object]:
    """Typed Nautilus-event → reporting metrics dict (unique projection path)."""
    tags = _merged_tags(event, order)
    metrics = metrics_from_tags(event, order=order)
    instrument_id, condition_id, market_id, token_id = _association_ids(
        event, registry, tags, metrics
    )
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
            "side": getattr(side, "value", side)
            if side is not None
            else metrics.get("side"),
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
    order: object | None = None,
) -> dict[str, object]:
    metrics = project_order_metrics(
        event,
        registry=registry,
        strategy_name=strategy_name,
        order=order,
    )
    fill_price = _maybe_float(
        _value(event, "fill_price", _value(event, "last_px", _value(event, "price")))
    )
    if fill_price is None or not math.isfinite(fill_price) or fill_price <= 0.0:
        raise ValueError(
            "missing positive fill_price; refusing fabricated execution truth"
        )
    metrics["fill_price"] = fill_price
    fill_shares = _maybe_float(
        _value(event, "shares", _value(event, "last_qty", _value(event, "quantity")))
    )
    if fill_shares is None or not math.isfinite(fill_shares) or fill_shares <= 0.0:
        raise ValueError(
            "missing positive fill_shares; refusing fabricated execution truth"
        )
    metrics["shares"] = fill_shares
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
        text
        for text in (_lookup_id_text(value) for value in values)
        if text is not None
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
