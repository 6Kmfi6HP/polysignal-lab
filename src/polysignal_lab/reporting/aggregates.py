from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any, assert_never

from polysignal_lab.domain.enums import TradeResultStatus
from polysignal_lab.domain.reporting_result import (
    trade_result_details,
    trade_result_display,
    trade_result_number,
    trade_result_status,
)
from polysignal_lab.domain.missing_values import (
    COLLAPSE_COMPONENT,
    missing_value_counter,
)

CalibrationValue = str | int | float
CalibrationBreakdown = dict[str, dict[str, CalibrationValue]]


def _count_collapse(key: str) -> None:
    """Record a single missing-value collapse for ``key`` when a counter is bound."""
    counter = missing_value_counter()
    if counter is not None:
        counter.inc_metric(COLLAPSE_COMPONENT, f"collapsed_{key}")


def calibration_breakdown(closed_rows: list[Any]) -> CalibrationBreakdown:
    """Build calibration buckets from pre-resolved closed rows.

    ``closed_rows`` items expose ``record`` (the raw result mapping), ``roi``
    (pre-resolved, already counted for collapse by the caller), and read
    ``entry_price`` here — the latter is calibration-only so it is counted
    exactly once at this point.
    """
    rows: CalibrationBreakdown = {}
    entry_price_sum: dict[str, float] = {}
    return_sum: dict[str, float] = {}
    entry_price_count: dict[str, int] = {}
    return_count: dict[str, int] = {}
    for closed_row in closed_rows:
        result = closed_row.record
        details = trade_result_details(result)
        bucket = confidence_bucket(details.get("confidence"))
        strategy = trade_result_display(result, "strategy")
        asset = trade_result_display(result, "asset")
        timeframe = trade_result_display(result, "timeframe")
        key = f"{strategy}|{asset}|{timeframe}|{bucket}"
        row = rows.setdefault(
            key,
            {
                "strategy": strategy,
                "asset": asset,
                "timeframe": timeframe,
                "confidence_bucket": bucket,
                "sample_size": 0,
                "wins": 0,
                "losses": 0,
                "entry_price_count": 0,
                "return_count": 0,
                "average_entry_price": 0.0,
                "average_return": 0.0,
                "calibration_status": "insufficient_data",
            },
        )
        sample_size = row["sample_size"]
        row["sample_size"] = (sample_size if isinstance(sample_size, int) else 0) + 1
        status = trade_result_status(result)
        wins = row["wins"]
        row["wins"] = (wins if isinstance(wins, int) else 0) + (
            1 if status == TradeResultStatus.WIN else 0
        )
        losses = row["losses"]
        row["losses"] = (losses if isinstance(losses, int) else 0) + (
            1 if status == TradeResultStatus.LOSS else 0
        )
        entry_price = trade_result_number(result, "entry_price")
        if entry_price is None:
            _count_collapse("entry_price")
        else:
            entry_price_sum[key] = entry_price_sum.get(key, 0.0) + entry_price
            entry_price_count[key] = entry_price_count.get(key, 0) + 1
            row["entry_price_count"] = entry_price_count[key]
        roi = closed_row.roi
        if roi is not None:
            return_sum[key] = return_sum.get(key, 0.0) + roi
            return_count[key] = return_count.get(key, 0) + 1
            row["return_count"] = return_count[key]
    for key, row in rows.items():
        row["average_entry_price"] = (
            entry_price_sum[key] / entry_price_count[key]
            if entry_price_count.get(key, 0)
            else 0.0
        )
        row["average_return"] = (
            return_sum[key] / return_count[key] if return_count.get(key, 0) else 0.0
        )
        row["calibration_status"] = (
            "calibrated"
            if isinstance(row["sample_size"], int) and row["sample_size"] >= 30
            else "insufficient_data"
        )
    return rows


def optional_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def confidence_bucket(confidence: Any) -> str:
    if isinstance(confidence, bool):
        return "low"
    try:
        value = float(confidence or 0.0)
    except (OverflowError, TypeError, ValueError):
        return "low"
    if not math.isfinite(value):
        return "low"
    if value >= 0.75:
        return "high"
    if value >= 0.55:
        return "medium"
    return "low"


def is_closed_result(result: Mapping[str, Any]) -> bool:
    match trade_result_status(result):
        case (
            TradeResultStatus.WIN
            | TradeResultStatus.LOSS
            | TradeResultStatus.VOID
            | TradeResultStatus.SPLIT
        ):
            return True
        case TradeResultStatus.UNKNOWN:
            return False
        case unreachable:
            assert_never(unreachable)
