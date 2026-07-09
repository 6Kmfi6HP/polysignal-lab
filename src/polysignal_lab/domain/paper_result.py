"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Mapping, dataclasses, dataclasses.dataclass, datetime, datetime.datetime, math, typing, typing.Any, polysignal_lab.domain.paper_report
Output: InvalidPaperTradeResultRow, PaperTradeResultRow, parse_paper_trade_result_row, trade_result_status, PaperWalletSnapshot, DailyReport
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any, TypedDict, assert_never

from polysignal_lab.domain.paper_report import (
    DailyReport,
    DailyReportRow,
    PaperWalletSnapshot,
    PaperWalletSnapshotRow,
    daily_report_row,
    report_date_text,
    report_float,
    report_nested_mapping,
    report_text,
    wallet_float,
)
from polysignal_lab.domain.enums import ExitMode, Side, TradeResultStatus
from polysignal_lab.utils import parse_dt


__all__ = [
    "DailyReport",
    "DailyReportRow",
    "InvalidPaperTradeResultRow",
    "PaperTradeResultRow",
    "PaperWalletSnapshot",
    "PaperWalletSnapshotRow",
    "daily_report_row",
    "parse_paper_trade_result_row",
    "report_date_text",
    "report_float",
    "report_nested_mapping",
    "report_text",
    "trade_result_details",
    "trade_result_float",
    "trade_result_status",
    "trade_result_text",
    "wallet_float",
]


@dataclass(slots=True)  # noqa: MUTABLE_OK
class InvalidPaperTradeResultRow(ValueError):
    field: str
    reason: str

    def __str__(self) -> str:
        return f"invalid paper_trade_results.{self.field}: {self.reason}"


class PaperTradeResultRow(TypedDict, total=False):
    schema_version: int
    paper_trade_id: str
    signal_id: str
    paper_position_id: str
    strategy: str
    asset: str
    timeframe: str
    market_id: str
    market_slug: str
    side: str
    entry_price: float
    shares: float
    stake_usdc: float
    exit_mode: str
    outcome_value: float
    settlement_value: float
    pnl_usdc: float
    roi: float
    result: str
    opened_at: str
    closed_at: str
    details: dict[str, Any]


def trade_result_status(row: Mapping[str, Any]) -> TradeResultStatus:
    raw = row.get("result")
    if isinstance(raw, TradeResultStatus):
        return raw
    try:
        return TradeResultStatus(str(raw))
    except ValueError:
        return TradeResultStatus.UNKNOWN


def trade_result_text(row: Mapping[str, Any], key: str, default: str = "") -> str:
    value = row.get(key)
    if value is None:
        return default
    if isinstance(value, Side):
        return value.value
    return str(value)


def trade_result_float(row: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    value = row.get(key)
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float, str)):
        try:
            parsed = float(value)
        except (OverflowError, TypeError, ValueError):
            return default
        return parsed if math.isfinite(parsed) else default
    return default


def parse_paper_trade_result_row(row: Mapping[str, Any]) -> PaperTradeResultRow:
    payload = dict(row)
    for key in (
        "paper_trade_id",
        "signal_id",
        "paper_position_id",
        "strategy",
        "asset",
        "timeframe",
        "market_id",
        "market_slug",
        "side",
        "exit_mode",
        "result",
        "opened_at",
        "closed_at",
    ):
        if not trade_result_text(payload, key):
            raise InvalidPaperTradeResultRow(key, "missing")

    status = trade_result_status(payload)
    match status:
        case TradeResultStatus.WIN | TradeResultStatus.LOSS | TradeResultStatus.VOID | TradeResultStatus.SPLIT:
            payload["result"] = status.value
        case TradeResultStatus.UNKNOWN:
            raise InvalidPaperTradeResultRow("result", "unknown")
        case _:
            assert_never(status)

    raw_side = payload.get("side")
    if raw_side not in (None, ""):
        try:
            payload["side"] = Side(str(raw_side).upper()).value
        except ValueError as exc:
            raise InvalidPaperTradeResultRow("side", "unknown") from exc

    raw_exit_mode = payload.get("exit_mode")
    try:
        payload["exit_mode"] = ExitMode(str(raw_exit_mode)).value
    except ValueError as exc:
        raise InvalidPaperTradeResultRow("exit_mode", "unknown") from exc

    for key in ("entry_price", "shares", "stake_usdc"):
        payload[key] = _finite_float(payload, key, allow_negative=False, allow_zero=False)
    for key in ("outcome_value", "settlement_value"):
        payload[key] = _finite_float(payload, key, allow_negative=False, allow_zero=True)
    for key in ("pnl_usdc", "roi"):
        payload[key] = _finite_float(payload, key, allow_negative=True)

    for key in ("opened_at", "closed_at"):
        value = payload.get(key)
        if value in (None, ""):
            continue
        if not isinstance(value, (str, datetime)):
            raise InvalidPaperTradeResultRow(key, "invalid timestamp")
        try:
            parsed_timestamp = parse_dt(value)
        except ValueError as exc:
            raise InvalidPaperTradeResultRow(key, "invalid timestamp") from exc
        if parsed_timestamp is None:
            raise InvalidPaperTradeResultRow(key, "invalid timestamp")

    details = payload.get("details")
    payload["details"] = dict(details) if isinstance(details, dict) else {}
    return PaperTradeResultRow(**payload)


def _finite_float(
    row: Mapping[str, Any],
    key: str,
    *,
    allow_negative: bool,
    allow_zero: bool = True,
) -> float:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise InvalidPaperTradeResultRow(key, "missing")
    try:
        parsed = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise InvalidPaperTradeResultRow(key, "not numeric") from exc
    if not math.isfinite(parsed):
        raise InvalidPaperTradeResultRow(key, "not finite")
    if parsed < 0.0 and not allow_negative:
        raise InvalidPaperTradeResultRow(key, "negative")
    if parsed == 0.0 and not allow_zero:
        raise InvalidPaperTradeResultRow(key, "zero")
    return parsed


def trade_result_details(row: Mapping[str, Any]) -> dict[str, Any]:
    details = row.get("details")
    return dict(details) if isinstance(details, dict) else {}
