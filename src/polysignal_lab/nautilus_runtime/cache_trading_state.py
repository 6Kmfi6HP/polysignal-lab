from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import cast

from polysignal_lab.alpha.types import (
    CachedOrderView,
    CachedPositionView,
    TradingStateView,
)
from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog


def cache_has_active_order_dedupe_key(
    cache: object | None,
    *,
    strategy_id: object | None,
    dedupe_key: str,
) -> bool:
    if cache is None or strategy_id is None:
        return False
    return any(
        _tags(getattr(order, "tags", ())).get("dedupe_key") == dedupe_key
        and (_boolean(order, "is_open") or _boolean(order, "is_inflight"))
        for order in _cache_items(cache, "orders", strategy_id=strategy_id)
    )


def trading_state_from_cache(
    cache: object | None,
    *,
    strategy_id: object | None,
    registry: MarketCatalog,
    condition_id: str | None = None,
) -> TradingStateView:
    if cache is None or strategy_id is None:
        return TradingStateView()
    orders = _cache_items(cache, "orders", strategy_id=strategy_id)
    order_views: list[CachedOrderView] = []
    for order in orders:
        order_view = _order_view(order, registry, condition_id=condition_id)
        if order_view is not None:
            order_views.append(order_view)
    positions = _cache_items(cache, "positions_open", strategy_id=strategy_id)
    position_views: list[CachedPositionView] = []
    for position in positions:
        position_view = _position_view(
            position,
            cache=cache,
            registry=registry,
            orders=orders,
            condition_id=condition_id,
        )
        if position_view is not None:
            position_views.append(position_view)
    return TradingStateView(orders=tuple(order_views), positions=tuple(position_views))


def _cache_items(cache: object, name: str, **kwargs: object) -> tuple[object, ...]:
    query = getattr(cache, name, None)
    if not callable(query):
        return ()
    raw = query(**kwargs)
    if isinstance(raw, Iterable) and not isinstance(raw, (str, bytes, bytearray)):
        return tuple(cast(Iterable[object], raw))
    return ()


def _order_view(
    order: object,
    registry: MarketCatalog,
    *,
    condition_id: str | None,
) -> CachedOrderView | None:
    tags = _tags(getattr(order, "tags", ()))
    instrument_id = _text(getattr(order, "instrument_id", ""))
    identity = _instrument_identity(registry, instrument_id, condition_id=condition_id)
    if identity is None:
        return None
    market_id, condition_id, side = identity
    strategy = tags.get("strategy", "")
    if not strategy:
        return None
    status = _text(getattr(order, "status", ""))
    return CachedOrderView(
        client_order_id=_text(getattr(order, "client_order_id", "")),
        instrument_id=instrument_id,
        strategy=strategy,
        market_id=tags.get("market_id") or market_id,
        condition_id=tags.get("condition_id") or condition_id,
        side=side,
        pair_id=tags.get("pair_id"),
        position_id=tags.get("position_id"),
        status=status,
        price=_number(getattr(order, "price", None)),
        filled_quantity=_number(getattr(order, "filled_qty", None)) or 0.0,
        average_fill_price=_number(getattr(order, "avg_px", None)),
        ts_event=_timestamp(getattr(order, "ts_last", None)),
        hedge_leg=_truthy(tags.get("hedge_leg")),
        reduce_only=_truthy(tags.get("reduce_only")),
        is_open=_boolean(order, "is_open"),
        is_inflight=_boolean(order, "is_inflight"),
        take_profit_price=_number(tags.get("exit_tp_price")),
        stop_loss_price=_number(tags.get("exit_stop_price")),
    )


def _position_view(
    position: object,
    *,
    cache: object,
    registry: MarketCatalog,
    orders: tuple[object, ...],
    condition_id: str | None,
) -> CachedPositionView | None:
    instrument_id = _text(getattr(position, "instrument_id", ""))
    identity = _instrument_identity(registry, instrument_id, condition_id=condition_id)
    if identity is None:
        return None
    market_id, condition_id, side = identity
    position_id = _text(getattr(position, "id", ""))
    linked = _linked_orders(
        cache,
        getattr(position, "id", position_id),
        orders,
        instrument_id,
    )
    tags = next(
        (
            parsed
            for order in reversed(linked)
            if (parsed := _tags(getattr(order, "tags", ())))
            and parsed.get("strategy")
            and not _truthy(parsed.get("reduce_only"))
        ),
        {},
    )
    strategy = tags.get("strategy", "")
    quantity = abs(_number(getattr(position, "signed_qty", None)) or 0.0)
    avg_entry_price = _number(getattr(position, "avg_px_open", None)) or 0.0
    if not position_id or not strategy or quantity <= 0.0 or avg_entry_price <= 0.0:
        return None
    return CachedPositionView(
        position_id=position_id,
        instrument_id=instrument_id,
        strategy=strategy,
        market_id=tags.get("market_id") or market_id,
        condition_id=tags.get("condition_id") or condition_id,
        side=side,
        pair_id=tags.get("pair_id"),
        quantity=quantity,
        avg_entry_price=avg_entry_price,
        opened_at=_timestamp(getattr(position, "ts_opened", None)),
    )


def _linked_orders(
    cache: object,
    position_id: object,
    orders: tuple[object, ...],
    instrument_id: str,
) -> tuple[object, ...]:
    query = getattr(cache, "orders_for_position", None)
    if callable(query) and str(position_id):
        raw = query(position_id)
        if isinstance(raw, Iterable) and not isinstance(raw, (str, bytes, bytearray)):
            linked = tuple(cast(Iterable[object], raw))
            if linked:
                return linked
    return tuple(
        order
        for order in orders
        if _text(getattr(order, "instrument_id", "")) == instrument_id
    )


def _instrument_identity(
    registry: MarketCatalog,
    instrument_id: str,
    *,
    condition_id: str | None,
) -> tuple[str, str, Side] | None:
    condition_ids = (
        (condition_id,)
        if condition_id is not None
        else registry.condition_ids()
    )
    for candidate_condition_id in condition_ids:
        pair = registry.by_condition(candidate_condition_id)
        if pair is None:
            continue
        for token in (pair.up, pair.down):
            if str(registry.instrument_id_for_token(token.token_id)) == instrument_id:
                return pair.market_id, candidate_condition_id, token.side
    return None


def _tags(raw: object) -> dict[str, str]:
    if isinstance(raw, Mapping):
        return {str(key): str(value) for key, value in raw.items()}
    if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes, bytearray)):
        return {}
    parsed: dict[str, str] = {}
    for item in raw:
        key, separator, value = str(item).partition("=")
        if separator and key:
            parsed[key] = value
    return parsed


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    candidate = value
    for name in ("as_double", "as_decimal"):
        converter = getattr(value, name, None)
        if callable(converter):
            candidate = converter()
            break
    try:
        return float(str(candidate))
    except ValueError:
        return None


def _boolean(source: object, name: str) -> bool:
    value = getattr(source, name, False)
    return bool(value() if callable(value) else value)


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    number = _number(value)
    if number is None or number <= 0:
        return None
    return datetime.fromtimestamp(number / 1_000_000_000, tz=UTC)
