from __future__ import annotations

from collections.abc import Iterable, Mapping
import math
from typing import cast

_ORDER_STATUSES = {
    "FILLED": "FILLED",
    "PARTIAL": "PARTIAL",
    "PARTIALLY_FILLED": "PARTIALLY_FILLED",
    "REJECTED": "REJECTED",
    "DENIED": "DENIED",
    "CANCELLED": "CANCELLED",
    "CANCELED": "CANCELED",
    "EXPIRED": "EXPIRED",
    "ACCEPTED": "ACCEPTED",
    "RESTING": "RESTING",
    "SUBMITTED": "SUBMITTED",
}


def normalize_report_order(
    row: Mapping[str, object],
    *,
    market: object | None = None,
) -> dict[str, object]:
    payload, metrics, token_id = _base_payload(row, market)
    _fill_missing(
        payload,
        "report_order_id",
        _text(
            row,
            metrics,
            "report_order_id",
            "client_order_id",
            "order_id",
            "id",
            metric_keys=("report_order_id", "client_order_id", "order_id"),
        ),
    )
    _fill_missing(
        payload,
        "signal_id",
        _text(row, metrics, "signal_id", metric_keys=("signal_id",)),
    )
    _fill_missing(payload, "created_at", _text(row, metrics, "ts", "created_at"))
    _fill_missing(
        payload,
        "order_intent",
        _text(
            row,
            metrics,
            "order_intent",
            metric_keys=("order_intent",),
        ),
    )
    limit_price = _number(
        row,
        metrics,
        "limit_price",
        "price",
        metric_keys=("price", "level_price"),
    )
    shares = _number(
        row,
        metrics,
        "shares",
        "quantity",
        metric_keys=("shares", "quantity", "contracts"),
    )
    if shares in (None, 0.0):
        metric_shares = _number(
            {}, metrics, metric_keys=("contracts", "shares", "quantity")
        )
        if metric_shares not in (None, 0.0):
            shares = metric_shares
    if limit_price in (None, 0.0):
        metric_price = _number(
            {},
            metrics,
            metric_keys=("level_price", "price"),
        )
        if metric_price not in (None, 0.0):
            limit_price = metric_price
    stake = _number(row, metrics, "stake_usdc", metric_keys=("stake_usdc",))
    if stake is None and limit_price is not None and shares is not None:
        stake = limit_price * abs(shares)
    _set_number(payload, "limit_price", limit_price)
    _set_number(
        payload,
        "reference_price",
        _number(
            row,
            metrics,
            "reference_price",
            metric_keys=("reference_price", "level_price", "price"),
        ),
    )
    _set_number(payload, "stake_usdc", stake)
    _set_number(payload, "shares", shares)
    payload["status"] = (
        _ORDER_STATUSES.get(native, "")
        if (
            native := _text(
                row,
                metrics,
                "status",
                "order_status",
                metric_keys=("status", "order_status"),
            ).upper()
        )
        else ""
    )
    _fill_missing(
        payload,
        "reject_reason",
        _text(
            row,
            metrics,
            "reject_reason",
            "reason",
            metric_keys=("reject_reason", "reason"),
        ),
    )
    payload["token_id"] = token_id
    return payload


def normalize_report_fill(
    row: Mapping[str, object],
    *,
    market: object | None = None,
) -> dict[str, object]:
    payload, metrics, _ = _base_payload(row, market)
    fill_id = _text(
        row,
        metrics,
        "report_fill_id",
        "trade_id",
        "fill_id",
        metric_keys=("report_fill_id", "trade_id", "fill_id"),
    )
    _fill_missing(payload, "report_fill_id", fill_id)
    order_id = _text(
        row,
        metrics,
        "report_order_id",
        "client_order_id",
        "order_id",
        "id",
        metric_keys=("report_order_id", "client_order_id", "order_id"),
    )
    _fill_missing(payload, "report_order_id", order_id)
    _fill_missing(
        payload,
        "signal_id",
        _text(row, metrics, "signal_id", metric_keys=("signal_id",)),
    )
    fill_price = _number(
        row,
        metrics,
        "fill_price",
        "price",
        "last_px",
        metric_keys=("fill_price", "price"),
    )
    shares = _number(
        row,
        metrics,
        "shares",
        "quantity",
        "last_qty",
        metric_keys=("shares", "quantity"),
    )
    stake = _number(
        row,
        metrics,
        "stake_usdc",
        "notional",
        metric_keys=("stake_usdc", "notional"),
    )
    if stake is None and fill_price is not None and shares is not None:
        stake = fill_price * abs(shares)
    _set_number(payload, "fill_price", fill_price)
    _set_number(payload, "shares", shares)
    _set_number(payload, "stake_usdc", stake)
    return payload


def normalize_report_position(
    row: Mapping[str, object],
    *,
    market: object | None = None,
) -> dict[str, object]:
    payload, metrics, _ = _base_payload(row, market)
    position_id = _text(
        row,
        metrics,
        "report_position_id",
        "position_id",
    )
    _fill_missing(payload, "report_position_id", position_id)
    _fill_missing(payload, "position_id", position_id)
    _fill_missing(
        payload,
        "signal_id",
        _text(row, metrics, "signal_id", metric_keys=("signal_id",)),
    )
    order_id = _text(
        row,
        metrics,
        "report_order_id",
        "client_order_id",
        "order_id",
        "id",
        metric_keys=("report_order_id", "client_order_id", "order_id"),
    )
    _fill_missing(payload, "report_order_id", order_id)
    fill_id = _text(
        row,
        metrics,
        "report_fill_id",
        "trade_id",
        "fill_id",
        metric_keys=("report_fill_id", "trade_id", "fill_id"),
    )
    _fill_missing(payload, "report_fill_id", fill_id)
    entry_price = _number(
        row,
        metrics,
        "entry_price",
        "avg_entry_price",
        "price",
        "last_px",
        metric_keys=("entry_price", "avg_entry_price", "price"),
    )
    shares = _number(
        row,
        metrics,
        "shares",
        "quantity",
        "signed_qty",
        metric_keys=("shares", "quantity", "signed_qty"),
    )
    stake = _number(row, metrics, "stake_usdc", metric_keys=("stake_usdc",))
    if stake is None and entry_price is not None and shares is not None:
        stake = entry_price * abs(shares)
    _set_number(payload, "entry_price", entry_price)
    _set_number(payload, "shares", shares)
    _set_number(payload, "stake_usdc", stake)
    _fill_missing(
        payload,
        "opened_at",
        _text(row, metrics, "opened_at", "ts", "created_at"),
    )
    status = _text(row, metrics, "status", metric_keys=("status",)).upper()
    is_closed = row.get("is_closed")
    payload["status"] = (
        status
        if status in {"OPEN", "CLOSED"}
        else "CLOSED"
        if is_closed is True
        else "OPEN"
        if is_closed is False
        else ""
    )
    _fill_missing(
        payload,
        "closed_at",
        _text(row, metrics, "closed_at", metric_keys=("closed_at",)),
    )
    payload["is_closed"] = payload["status"] == "CLOSED"
    return payload


def report_token_id(row: Mapping[str, object]) -> str:
    return _report_token_id(row, _metrics(row))


def _base_payload(
    row: Mapping[str, object],
    market: object | None,
) -> tuple[dict[str, object], Mapping[str, object], str]:
    payload = {
        key: _finite_payload_value(value)
        for key, value in row.items()
        if not key.startswith("_")
    }
    metrics = _metrics(row)
    for key in (
        "strategy",
        "asset",
        "timeframe",
        "market_id",
        "market_slug",
        "condition_id",
    ):
        fallback = (
            _attribute_text(market, key)
            if key
            in {
                "asset",
                "timeframe",
                "market_id",
                "market_slug",
                "condition_id",
            }
            else ""
        )
        _fill_missing(
            payload,
            key,
            _text(row, metrics, key, metric_keys=(key,)) or fallback,
        )
    token_id = _report_token_id(row, metrics)
    payload["token_id"] = token_id
    payload["side"] = _side(row, metrics, market, token_id)
    return payload, metrics, token_id


def _finite_payload_value(value: object) -> object:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): _finite_payload_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_finite_payload_value(item) for item in value]
    return value


def _metrics(row: Mapping[str, object]) -> Mapping[str, object]:
    metrics = row.get("metrics")
    return cast(Mapping[str, object], metrics) if isinstance(metrics, Mapping) else {}


def _text(
    row: Mapping[str, object],
    metrics: Mapping[str, object],
    *keys: str,
    metric_keys: tuple[str, ...] = (),
) -> str:
    for source, names in ((row, keys), (metrics, metric_keys)):
        for key in names:
            value = source.get(key)
            if value not in (None, ""):
                return str(value)
    return ""


def _number(
    row: Mapping[str, object],
    metrics: Mapping[str, object],
    *keys: str,
    metric_keys: tuple[str, ...] = (),
) -> float | None:
    for source, names in ((row, keys), (metrics, metric_keys)):
        for key in names:
            value = source.get(key)
            if value in (None, ""):
                continue
            try:
                parsed = float(str(value))
            except (TypeError, ValueError):
                continue
            if math.isfinite(parsed):
                return parsed
    return None


def _report_token_id(
    row: Mapping[str, object],
    metrics: Mapping[str, object],
) -> str:
    value = _text(row, metrics, "instrument_id", "token_id", metric_keys=("token_id",))
    token_id, _, _ = value.partition(".")
    return token_id or value


def _side(
    row: Mapping[str, object],
    metrics: Mapping[str, object],
    market: object | None,
    token_id: str,
) -> str:
    for candidate in (row.get("side"), row.get("order_side"), metrics.get("side")):
        upper = "" if candidate in (None, "") else str(candidate).upper()
        if upper in {"UP", "DOWN"}:
            return upper
    outcome_tokens = getattr(market, "outcome_tokens", ()) if market is not None else ()
    if isinstance(outcome_tokens, Iterable) and not isinstance(
        outcome_tokens, (str, bytes)
    ):
        for token in outcome_tokens:
            if str(getattr(token, "token_id", "")) == token_id:
                return str(getattr(token, "side", ""))
    return ""


def _attribute_text(source: object | None, name: str) -> str:
    value = getattr(source, name, "") if source is not None else ""
    return "" if value is None else str(value)


def _fill_missing(payload: dict[str, object], key: str, value: object) -> None:
    if payload.get(key) in (None, "") and value not in (None, ""):
        payload[key] = value


def _set_number(payload: dict[str, object], key: str, value: float | None) -> None:
    if value is not None and math.isfinite(value):
        payload[key] = value
