from __future__ import annotations

from typing import Any


def project_order_event(event: Any) -> dict[str, object]:
    tags = _tags(getattr(event, "tags", None))
    return {
        "client_order_id": str(getattr(event, "client_order_id", "")),
        "instrument_id": str(getattr(event, "instrument_id", "")),
        "side": str(getattr(event, "order_side", "")),
        "order_type": str(getattr(event, "order_type", "")),
        "time_in_force": str(getattr(event, "time_in_force", "")),
        "quantity": float(getattr(event, "quantity", 0.0) or 0.0),
        "price": float(getattr(event, "price", 0.0) or 0.0),
        "strategy": tags.get("strategy", ""),
        "condition_id": tags.get("condition_id", ""),
    }


def project_fill_event(event: Any) -> dict[str, object]:
    quantity = float(getattr(event, "last_qty", 0.0) or 0.0)
    price = float(getattr(event, "last_px", 0.0) or 0.0)
    return {
        "client_order_id": str(getattr(event, "client_order_id", "")),
        "instrument_id": str(getattr(event, "instrument_id", "")),
        "trade_id": str(getattr(event, "trade_id", "")),
        "quantity": quantity,
        "price": price,
        "notional": quantity * price,
        "liquidity_side": str(getattr(event, "liquidity_side", "")),
    }


def project_position(position: Any) -> dict[str, object]:
    return {
        "position_id": str(getattr(position, "id", "")),
        "instrument_id": str(getattr(position, "instrument_id", "")),
        "quantity": float(getattr(position, "signed_qty", 0.0) or 0.0),
        "avg_entry_price": float(getattr(position, "avg_px_open", 0.0) or 0.0),
        "realized_pnl": float(getattr(position, "realized_pnl", 0.0) or 0.0),
        "is_closed": bool(getattr(position, "is_closed", False)),
    }


def _tags(raw: object) -> dict[str, str]:
    if isinstance(raw, dict):
        return {str(key): str(value) for key, value in raw.items()}
    parsed: dict[str, str] = {}
    for item in raw or ():
        text = str(item)
        if "=" not in text:
            continue
        key, value = text.split("=", 1)
        parsed[key] = value
    return parsed
