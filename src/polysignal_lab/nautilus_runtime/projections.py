from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from inspect import Parameter, signature
import math
from typing import SupportsFloat, cast

from polysignal_lab.domain import missing_values


def project_order_event(
    event: object,
    *,
    metrics: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Project a Nautilus order lifecycle event into a reporting row.

    Order events carry no `tags`, `price`, or `quantity` — those belong to the
    `Order` and reach us already resolved in `metrics` (see
    `strategy/event_projection.py:project_order_metrics`). Only read event-owned
    facts from `event`.
    """
    merged_metrics = _metrics(event)
    if metrics is not None:
        merged_metrics.update(dict(metrics))
    client_order_id = _text_attr(event, "client_order_id")
    return {
        "event_id": _text_attr(event, "event_id") or _text_attr(event, "id"),
        "report_order_id": client_order_id,
        "client_order_id": client_order_id,
        "instrument_id": _text_attr(event, "instrument_id"),
        "side": _text_attr(event, "order_side") or _text_attr(event, "side"),
        "order_type": _text_attr(event, "order_type"),
        "time_in_force": _text_attr(event, "time_in_force"),
        "order_intent": _metric_text(merged_metrics, "order_intent") or "default",
        # Only `OrderUpdated` carries its own economics, and there they are the
        # authoritative new values; every other event falls back to metrics.
        "quantity": _float_attr(event, "quantity")
        or _metric_float(merged_metrics, "contracts", "shares", "quantity"),
        "price": _float_attr(event, "price")
        or _metric_float(merged_metrics, "level_price", "price"),
        "status": _order_status(event),
        "reject_reason": _text_attr(event, "reason"),
        "strategy": _metric_text(merged_metrics, "strategy"),
        "condition_id": _metric_text(merged_metrics, "condition_id"),
        "market_id": _metric_text(merged_metrics, "market_id"),
        "signal_id": _metric_text(merged_metrics, "signal_id"),
        "metrics": merged_metrics,
        "ts": _timestamp_text(event, "ts_event", "timestamp"),
    }


def project_fill_event(
    event: object,
    *,
    metrics: Mapping[str, object] | None = None,
) -> dict[str, object]:
    merged_metrics = _metrics(event)
    if metrics is not None:
        merged_metrics.update(dict(metrics))
    tags = _tags(getattr(event, "tags", None))
    signal_id = tags.get("signal_id") or missing_values.identifier(
        merged_metrics, {}, "signal_id", source="project_fill_event"
    )
    quantity = _float_attr(event, "last_qty")
    if quantity == 0.0:
        quantity = _float_attr(event, "shares") or _float_attr(event, "quantity")
    price = _float_attr(event, "last_px")
    if price == 0.0:
        price = _float_attr(event, "fill_price") or _float_attr(event, "price")
    if price <= 0.0:
        raise ValueError(
            "missing positive fill price; refusing fabricated execution truth"
        )
    trade_id = _text_attr(event, "trade_id") or _text_attr(event, "fill_id")
    client_order_id = _text_attr(event, "client_order_id")
    leaves_qty = _optional_float_attr(event, "leaves_qty")
    filled_qty = _optional_float_attr(event, "filled_qty")
    order_qty = _optional_float_attr(event, "order_quantity")
    order_status = _text_attr(event, "order_status") or _text_attr(event, "status")
    return {
        "event_id": _text_attr(event, "event_id") or _text_attr(event, "id"),
        "report_fill_id": trade_id,
        "report_order_id": client_order_id,
        "client_order_id": client_order_id,
        "instrument_id": _text_attr(event, "instrument_id"),
        "trade_id": trade_id,
        "quantity": quantity,
        "price": price,
        "notional": quantity * price,
        "liquidity_side": _text_attr(event, "liquidity_side"),
        "leaves_qty": leaves_qty,
        "filled_qty": filled_qty,
        "order_quantity": order_qty,
        "order_status": order_status,
        "signal_id": signal_id,
        "metrics": merged_metrics,
        "ts": _timestamp_text(event, "ts_event", "timestamp"),
    }


def project_position(position: object) -> dict[str, object]:
    position_id = _text_attr(position, "id")
    is_closed = bool(getattr(position, "is_closed", False))
    quantity = _optional_float_attr(position, "signed_qty")
    avg_entry_price = _optional_float_attr(position, "avg_px_open")
    stake_usdc = (
        abs(quantity) * avg_entry_price
        if quantity is not None and avg_entry_price is not None
        else None
    )
    opened_at = _timestamp_text(position, "ts_opened", "opened_at")
    closed_at = _timestamp_text(position, "ts_closed", "closed_at")
    event_at = _timestamp_text(position, "ts_event")
    timestamp = (
        closed_at or event_at or opened_at
        if is_closed
        else opened_at or event_at or closed_at
    )
    return {
        "report_position_id": position_id,
        "position_id": position_id,
        "instrument_id": _text_attr(position, "instrument_id"),
        "quantity": quantity,
        "avg_entry_price": avg_entry_price,
        "stake_usdc": stake_usdc,
        "realized_pnl": _float_attr(position, "realized_pnl"),
        "status": "CLOSED" if is_closed else "OPEN",
        "is_closed": is_closed,
        "opened_at": opened_at,
        "closed_at": closed_at,
        "ts": timestamp,
    }


def project_account(account: object) -> dict[str, object]:
    balances_raw = getattr(account, "balances", ())
    if callable(balances_raw):
        balances_raw = balances_raw()
    if isinstance(balances_raw, Mapping):
        balances_raw = balances_raw.values()
    balances: list[dict[str, object]] = []
    if isinstance(balances_raw, Iterable) and not isinstance(
        balances_raw, (str, bytes)
    ):
        for balance in cast(Iterable[object], balances_raw):
            balances.append(
                {
                    "currency": _text_attr(balance, "currency"),
                    "total": _float_attr(balance, "total"),
                }
            )
    return {
        "account_id": _text_attr(account, "id"),
        "balances": balances,
    }


def project_portfolio_snapshot(
    portfolio: object,
    *,
    account: object | None = None,
    currency: str | None = None,
) -> dict[str, object]:
    equity_value = _portfolio_equity(portfolio, account, currency=currency)
    return {
        "portfolio_id": _text_attr(portfolio, "id"),
        "equity": equity_value,
    }


def _portfolio_equity(
    portfolio: object,
    account: object | None,
    *,
    currency: str | None = None,
) -> float | None:
    """Read equity from either portfolio shape.

    Nautilus `Portfolio.equity(venue=None, account_id=None) -> dict` must be
    scoped by account, so without one we report nothing rather than guess a
    venue-wide total. Project-side portfolio wrappers expose a no-arg `equity()`
    that needs no scoping. The signature tells the two apart.
    """
    equity = getattr(portfolio, "equity", None)
    if callable(equity):
        account_id = getattr(account, "id", None)
        if account_id is not None:
            try:
                return _equity_float(equity(account_id=account_id), currency)
            except TypeError:
                try:
                    parameters = signature(equity).parameters.values()
                except (TypeError, ValueError):
                    raise
                if any(
                    parameter.kind == Parameter.VAR_KEYWORD
                    or parameter.name == "account_id"
                    for parameter in parameters
                ):
                    raise
        else:
            try:
                parameters = signature(equity).parameters.values()
            except (TypeError, ValueError):
                parameters = ()
            if any(
                parameter.kind == Parameter.VAR_KEYWORD
                or parameter.name in {"venue", "account_id"}
                for parameter in parameters
            ):
                return None
        return _equity_float(equity(), currency)
    return _equity_float(equity, currency)


def _equity_float(value: object, currency: str | None) -> float | None:
    if currency is None or not isinstance(value, Mapping):
        return _to_float_or_none(value)
    for key, amount in value.items():
        if str(key) == currency:
            return _to_float_or_none(amount)
    return None


def _to_float(value: object) -> float:
    if isinstance(value, Mapping):
        return sum(
            _to_float(item) for item in cast(Mapping[object, object], value).values()
        )

    for name in ("as_double", "as_decimal"):
        numeric = getattr(value, name, None)
        if callable(numeric):
            try:
                return _to_float(numeric())
            except (TypeError, ValueError):
                pass

    coerced = (
        value
        if isinstance(value, (int, float, str, bytes, bytearray))
        else cast(SupportsFloat, value)
    )
    try:
        return float(coerced)
    except (TypeError, ValueError):
        try:
            return float(str(value))
        except (TypeError, ValueError):
            return 0.0


def _float_attr(source: object, name: str) -> float:
    value = getattr(source, name, 0.0)
    if callable(value):
        value = value()
    return _to_float(value)


def _optional_float_attr(source: object, name: str) -> float | None:
    value = getattr(source, name, None)
    if callable(value):
        value = value()
    return _to_float_or_none(value)


def _to_float_or_none(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        parsed_values = [
            parsed
            for item in cast(Mapping[object, object], value).values()
            if (parsed := _to_float_or_none(item)) is not None
        ]
        return sum(parsed_values) if parsed_values else None
    for name in ("as_double", "as_decimal"):
        numeric = getattr(value, name, None)
        if callable(numeric):
            try:
                return _to_float_or_none(numeric())
            except (TypeError, ValueError):
                pass
    try:
        parsed = float(
            value
            if isinstance(value, (int, float, str, bytes, bytearray))
            else cast(SupportsFloat, value)
        )
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        try:
            parsed = float(str(value))
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None


def _text_attr(source: object, name: str) -> str:
    value = getattr(source, name, "")
    return "" if value is None else str(value)


def _metrics(source: object) -> dict[str, object]:
    raw = getattr(source, "metrics", None)
    if isinstance(raw, Mapping):
        return dict(cast(Mapping[str, object], raw))
    return {}


def _metric_text(metrics: Mapping[str, object], key: str) -> str:
    value = metrics.get(key)
    return "" if value is None else str(value)


def _metric_float(metrics: Mapping[str, object], *keys: str) -> float:
    """First non-zero metric value; 0.0 means the economics never arrived."""
    for key in keys:
        parsed = _to_float_or_none(metrics.get(key))
        if parsed:
            return parsed
    return 0.0


def _order_status(event: object) -> str:
    """Order events name their own status: `OrderSubmitted` → `SUBMITTED`.

    Neither the pyo3 nor the Cython event classes expose a `status` attribute.
    """
    event_name = type(event).__name__
    if event_name.startswith("Order"):
        return event_name.removeprefix("Order").upper()
    return ""


def _timestamp_text(source: object, *names: str) -> str:
    for name in names:
        value = getattr(source, name, None)
        if isinstance(value, datetime):
            return (
                value.astimezone(UTC)
                .isoformat(timespec="microseconds")
                .replace("+00:00", "Z")
            )
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return (
                datetime.fromtimestamp(float(value) / 1_000_000_000, tz=UTC)
                .isoformat(timespec="microseconds")
                .replace("+00:00", "Z")
            )
        if isinstance(value, str) and value:
            return value
    return ""


def _tags(raw: object) -> dict[str, str]:
    if isinstance(raw, Mapping):
        return {
            str(key): str(value)
            for key, value in cast(Mapping[object, object], raw).items()
        }
    if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes)):
        return {}
    parsed: dict[str, str] = {}
    for item in raw:
        text = str(item)
        if "=" not in text:
            continue
        key, value = text.split("=", 1)
        parsed[key] = value
    return parsed
