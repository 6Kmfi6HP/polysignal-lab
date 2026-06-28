from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import cast


def project_order_event(event: object) -> dict[str, object]:
    tags = _tags(getattr(event, "tags", None))
    metrics = _metrics(event)
    order_intent = tags.get("order_intent", str(metrics.get("paper_order_intent") or ""))
    if order_intent and "paper_order_intent" not in metrics:
        metrics["paper_order_intent"] = order_intent
    client_order_id = _text_attr(event, "client_order_id")
    return {
        "paper_order_id": client_order_id,
        "client_order_id": client_order_id,
        "instrument_id": _text_attr(event, "instrument_id"),
        "side": _text_attr(event, "order_side"),
        "order_type": _text_attr(event, "order_type"),
        "time_in_force": _text_attr(event, "time_in_force"),
        "order_intent": order_intent or "default",
        "quantity": _float_attr(event, "quantity"),
        "price": _float_attr(event, "price"),
        "status": _order_status(event),
        "reject_reason": _text_attr(event, "reason"),
        "strategy": tags.get("strategy", ""),
        "condition_id": tags.get("condition_id", ""),
        "market_id": tags.get("market_id", ""),
        "metrics": metrics,
        "ts": _timestamp_text(event, "ts_event", "timestamp"),
    }


def project_fill_event(event: object) -> dict[str, object]:
    quantity = _float_attr(event, "last_qty")
    price = _float_attr(event, "last_px")
    trade_id = _text_attr(event, "trade_id") or _text_attr(event, "fill_id")
    client_order_id = _text_attr(event, "client_order_id")
    return {
        "paper_fill_id": trade_id,
        "paper_order_id": client_order_id,
        "client_order_id": client_order_id,
        "instrument_id": _text_attr(event, "instrument_id"),
        "trade_id": trade_id,
        "quantity": quantity,
        "price": price,
        "notional": quantity * price,
        "liquidity_side": _text_attr(event, "liquidity_side"),
        "metrics": _metrics(event),
        "ts": _timestamp_text(event, "ts_event", "timestamp"),
    }


def project_position(position: object) -> dict[str, object]:
    position_id = _text_attr(position, "id")
    is_closed = bool(getattr(position, "is_closed", False))
    return {
        "paper_position_id": position_id,
        "position_id": position_id,
        "instrument_id": _text_attr(position, "instrument_id"),
        "quantity": _float_attr(position, "signed_qty"),
        "avg_entry_price": _float_attr(position, "avg_px_open"),
        "realized_pnl": _float_attr(position, "realized_pnl"),
        "status": "CLOSED" if is_closed else "OPEN",
        "is_closed": is_closed,
        "ts": _timestamp_text(position, "ts_event", "opened_at", "closed_at"),
    }


def project_account(account: object) -> dict[str, object]:
    balances_raw = getattr(account, "balances", ())
    if callable(balances_raw):
        balances_raw = balances_raw()
    balances: list[dict[str, object]] = []
    if isinstance(balances_raw, Iterable) and not isinstance(balances_raw, (str, bytes)):
        for balance in balances_raw:
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


def project_portfolio_snapshot(portfolio: object) -> dict[str, object]:
    return {
        "portfolio_id": _text_attr(portfolio, "id"),
        "equity": _float_attr(portfolio, "equity"),
    }


def _float_attr(source: object, name: str) -> float:
    value = getattr(source, name, 0.0)
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _text_attr(source: object, name: str) -> str:
    value = getattr(source, name, "")
    return "" if value is None else str(value)


def _metrics(source: object) -> dict[str, object]:
    raw = getattr(source, "metrics", None)
    if isinstance(raw, Mapping):
        return dict(cast(Mapping[str, object], raw))
    return {}


def _order_status(event: object) -> str:
    status = getattr(event, "status", None)
    if status is not None:
        name = getattr(status, "name", None)
        value = name if name not in (None, "") else status
        return str(value)
    event_name = type(event).__name__
    if event_name.startswith("Order"):
        return event_name.removeprefix("Order").upper()
    return ""


def _timestamp_text(source: object, *names: str) -> str:
    for name in names:
        value = getattr(source, name, None)
        if isinstance(value, datetime):
            return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return datetime.fromtimestamp(float(value) / 1_000_000_000, tz=UTC).isoformat(
                timespec="microseconds"
            ).replace("+00:00", "Z")
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
