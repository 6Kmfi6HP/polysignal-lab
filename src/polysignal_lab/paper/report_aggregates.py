from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any, assert_never

from polysignal_lab.domain.enums import TradeResultStatus
from polysignal_lab.domain.paper_result import (
    trade_result_details,
    trade_result_float,
    trade_result_status,
    trade_result_text,
)

CalibrationValue = str | int | float
CalibrationBreakdown = dict[str, dict[str, CalibrationValue]]


def calibration_breakdown(results: list[Mapping[str, Any]]) -> CalibrationBreakdown:
    rows: CalibrationBreakdown = {}
    entry_price_sum: dict[str, float] = {}
    return_sum: dict[str, float] = {}
    for result in results:
        details = trade_result_details(result)
        bucket = confidence_bucket(details.get("confidence"))
        strategy = trade_result_text(result, "strategy")
        asset = trade_result_text(result, "asset")
        timeframe = trade_result_text(result, "timeframe")
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
        entry_price_sum[key] = entry_price_sum.get(key, 0.0) + trade_result_float(
            result, "entry_price"
        )
        return_sum[key] = return_sum.get(key, 0.0) + trade_result_float(result, "roi")
    for key, row in rows.items():
        raw_sample_size = row["sample_size"]
        sample_size = raw_sample_size if isinstance(raw_sample_size, int) else 0
        row["average_entry_price"] = entry_price_sum[key] / sample_size
        row["average_return"] = return_sum[key] / sample_size
        row["calibration_status"] = (
            "calibrated" if sample_size >= 30 else "insufficient_data"
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
