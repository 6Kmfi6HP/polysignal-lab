"""
Input: __future__, collections.abc, math, typing, polysignal_lab.domain.enums, polysignal_lab.utils
Output: FEE_MODEL_IGNORED_V1, report_result_from_early_exit, fee_fields_v1, exit_mode_from_reason
Pos: Reporting Truth - early reduce-only exit results

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any, TypedDict

from polysignal_lab.domain.enums import ExitMode, Side, TradeResultStatus
from polysignal_lab.utils import new_id, utc_iso

FEE_MODEL_IGNORED_V1 = "ignored_v1"


class FeeFields(TypedDict):
    fee_model: str
    entry_fee: float

_EXIT_REASON_TO_MODE: dict[str, ExitMode] = {
    "TAKE_PROFIT": ExitMode.TAKE_PROFIT,
    "STOP_LOSS": ExitMode.STOP_LOSS,
    "MAX_HOLD_TIME": ExitMode.MAX_HOLD_TIME,
}


def fee_fields_v1(*, entry_fee: float = 0.0) -> FeeFields:
    fee = float(entry_fee)
    if not math.isfinite(fee) or fee < 0.0:
        raise ValueError("entry_fee must be a finite non-negative number")
    return {
        "fee_model": FEE_MODEL_IGNORED_V1,
        "entry_fee": fee,
    }


def exit_mode_from_reason(reason: object) -> ExitMode | None:
    text = str(reason or "").strip().upper()
    return _EXIT_REASON_TO_MODE.get(text)


def report_result_from_early_exit(
    metrics: Mapping[str, object],
    *,
    fill_price: float,
    fill_shares: float,
    strategy_name: str,
    closed_at: str | None = None,
) -> dict[str, Any] | None:
    exit_reason = metrics.get("exit_reason")
    exit_mode = exit_mode_from_reason(exit_reason)
    if exit_mode is None:
        return None

    position_id = str(metrics.get("position_id") or "").strip()
    if not position_id:
        return None

    entry_price = _positive_float(metrics.get("entry_price"))
    if entry_price is None:
        entry_price = _positive_float(metrics.get("avg_entry_price"))
    quantity = _positive_float(metrics.get("position_quantity"))
    if quantity is None:
        quantity = _positive_float(fill_shares)
    exit_px = _positive_float(fill_price)
    if exit_px is None:
        exit_px = _positive_float(metrics.get("exit_price"))
    if entry_price is None or quantity is None or exit_px is None:
        return None

    stake = _positive_float(metrics.get("stake_usdc"))
    if stake is None:
        stake = entry_price * quantity
    if stake <= 0.0:
        return None

    fee = fee_fields_v1()
    entry_fee = float(fee["entry_fee"])
    settlement_value = exit_px * quantity
    pnl = settlement_value - stake - entry_fee
    if pnl > 0.0:
        result_status = TradeResultStatus.WIN
    elif pnl < 0.0:
        result_status = TradeResultStatus.LOSS
    else:
        result_status = TradeResultStatus.VOID

    side_raw = metrics.get("side")
    try:
        side = Side(str(side_raw).upper()).value if side_raw not in (None, "") else ""
    except ValueError:
        side = ""
    if not side:
        return None

    market_id = str(metrics.get("market_id") or "").strip()
    market_slug = str(metrics.get("market_slug") or "").strip()
    asset = str(metrics.get("asset") or "").strip()
    timeframe = str(metrics.get("timeframe") or "").strip()
    if not market_id or not market_slug or not asset or not timeframe:
        return None

    signal_id = str(metrics.get("signal_id") or "").strip()
    if not signal_id:
        signal_id = f"native_exit:{position_id}"

    strategy = str(metrics.get("owning_strategy") or strategy_name or metrics.get("strategy") or "").strip()
    if not strategy or strategy == "native_exit":
        strategy = strategy_name or "native_exit"

    opened_at = str(metrics.get("opened_at") or "").strip()
    closed = closed_at or utc_iso()
    if not opened_at:
        opened_at = closed

    details = {
        "source": "native_exit",
        "exit_reason": str(exit_reason),
        "native_settlement_mode": "report_only",
        "native_position_mutation": "reduce_only_fill",
        **fee,
    }

    return {
        "schema_version": 1,
        "report_result_id": new_id("rr", "exit", position_id),
        "signal_id": signal_id,
        "report_position_id": position_id,
        "strategy": strategy,
        "asset": asset,
        "timeframe": timeframe,
        "market_id": market_id,
        "market_slug": market_slug,
        "side": side,
        "entry_price": entry_price,
        "shares": quantity,
        "stake_usdc": stake,
        "exit_mode": exit_mode.value,
        "outcome_value": exit_px,
        "settlement_value": settlement_value,
        "pnl_usdc": pnl,
        "roi": pnl / stake if stake else 0.0,
        "result": result_status.value,
        "opened_at": opened_at,
        "closed_at": closed,
        "fee_model": fee["fee_model"],
        "entry_fee": entry_fee,
        "details": details,
    }


def _positive_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0.0:
        return None
    return number
