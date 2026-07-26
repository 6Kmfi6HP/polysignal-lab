from __future__ import annotations

import math
from datetime import datetime
from typing import Any, cast

from polysignal_lab.domain.enums import ExitMode, Side, TradeResultStatus
from polysignal_lab.domain.market import Market
from polysignal_lab.reporting.exit_result import fee_fields_v1
from polysignal_lab.utils import new_id, parse_dt, utc_now


def _projection_float(source: dict[str, object], key: str) -> float | None:
    value = source.get(key)
    if not isinstance(value, (int, float, str)):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def report_result_from_projection(
    projection: dict[str, object],
    *,
    market: Market,
    outcome_value: float,
    details: dict[str, object],
) -> dict[str, Any] | None:
    quantity = _projection_float(projection, "shares") or _projection_float(
        projection, "quantity"
    )
    entry_price = _projection_float(projection, "entry_price") or _projection_float(
        projection, "avg_entry_price"
    )
    stake = _projection_float(projection, "stake_usdc")
    if quantity is None or entry_price is None or stake is None:
        return None
    try:
        outcome = float(outcome_value)
    except (TypeError, ValueError):
        return None
    if quantity <= 0 or entry_price <= 0 or stake <= 0 or not math.isfinite(outcome):
        return None
    fee = fee_fields_v1()
    entry_fee = float(fee["entry_fee"])
    settlement_value = quantity * outcome
    pnl = settlement_value - stake - entry_fee
    token_id = str(projection.get("token_id") or projection.get("instrument_id") or "")
    side = _projection_side(projection, market, token_id)
    if side is None:
        return None
    result_status = (
        TradeResultStatus.WIN
        if outcome_value == 1.0
        else TradeResultStatus.LOSS
        if outcome_value == 0.0
        else TradeResultStatus.VOID
        if 0.0 < outcome_value < 1.0
        else TradeResultStatus.WIN
        if pnl > 0
        else TradeResultStatus.LOSS
    )
    opened_at = None
    for key in ("opened_at", "ts", "created_at"):
        if projection.get(key):
            try:
                opened_at = parse_dt(cast(str | datetime | None, projection[key]))
            except ValueError:
                return None
            break
    if opened_at is None:
        return None
    result_details = dict(details)
    result_details.setdefault("fee_model", fee["fee_model"])
    result_details.setdefault("entry_fee", entry_fee)
    position_id = str(
        projection.get("report_position_id") or projection.get("position_id") or ""
    )
    trade_id = new_id("rr")
    return {
        "schema_version": 1,
        "report_result_id": trade_id,
        "signal_id": str(projection.get("signal_id") or ""),
        "report_position_id": position_id,
        "strategy": str(projection.get("strategy") or market.asset),
        "asset": str(projection.get("asset") or market.asset),
        "timeframe": str(projection.get("timeframe") or market.timeframe),
        "market_id": market.market_id,
        "market_slug": market.market_slug,
        "side": side.value,
        "entry_price": entry_price,
        "shares": quantity,
        "stake_usdc": stake,
        "exit_mode": ExitMode.RESOLUTION.value,
        "outcome_value": outcome,
        "settlement_value": settlement_value,
        "pnl_usdc": pnl,
        "roi": pnl / stake,
        "result": result_status.value,
        "opened_at": opened_at.isoformat(),
        "closed_at": utc_now().isoformat(),
        "fee_model": fee["fee_model"],
        "entry_fee": entry_fee,
        "details": result_details,
    }


def _projection_side(
    projection: dict[str, object], market: Market, token_id: str
) -> Side | None:
    raw_side = projection.get("side")
    if raw_side is not None:
        try:
            return Side(str(raw_side).upper())
        except ValueError:
            pass
    for token in market.outcome_tokens:
        if token.token_id == token_id:
            return token.side
    return None
