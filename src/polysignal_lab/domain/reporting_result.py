from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any, TypedDict, assert_never

from polysignal_lab.domain.reporting_models import (
    DailyReport,
    DailyReportRow,
    EquitySource,
    ReportAccountSnapshot,
    ReportAccountSnapshotRow,
    daily_report_row,
    report_date_text,
    report_nested_mapping,
)
from polysignal_lab.domain import missing_values
from polysignal_lab.domain.enums import ExitMode, Side, TradeResultStatus
from polysignal_lab.utils import parse_dt


__all__ = [
    "DailyReport",
    "DailyReportRow",
    "EquitySource",
    "InvalidReportResultRow",
    "ReportResultRow",
    "ReportAccountSnapshot",
    "ReportAccountSnapshotRow",
    "daily_report_row",
    "parse_report_result_row",
    "report_date_text",
    "report_nested_mapping",
    "trade_result_details",
    "trade_result_display",
    "trade_result_identifier",
    "trade_result_number",
    "trade_result_status",
]

_REPORT_RESULT_SOURCE = "report_results"


@dataclass(slots=True)
class InvalidReportResultRow(ValueError):
    field: str
    reason: str

    def __str__(self) -> str:
        return f"invalid report_results.{self.field}: {self.reason}"


class ReportResultRow(TypedDict, total=False):
    schema_version: int
    report_result_id: str
    signal_id: str
    report_position_id: str
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


def trade_result_number(
    row: Mapping[str, Any],
    *keys: str,
    metrics: Mapping[str, Any] | None = None,
    metric_keys: tuple[str, ...] = (),
) -> float | None:
    """Read a trade-result number without collapsing a missing value to zero."""
    return missing_values.number(row, metrics or {}, *keys, metric_keys=metric_keys)


def trade_result_identifier(
    row: Mapping[str, Any],
    *keys: str,
    metrics: Mapping[str, Any] | None = None,
    metric_keys: tuple[str, ...] = (),
) -> str:
    """Read an identifier that must be present, naming the record when it is not."""
    return missing_values.identifier(
        row,
        metrics or {},
        *keys,
        metric_keys=metric_keys,
        source=_result_source(row),
    )


def trade_result_display(
    row: Mapping[str, Any],
    *keys: str,
    metrics: Mapping[str, Any] | None = None,
    metric_keys: tuple[str, ...] = (),
) -> str:
    """Read a display-only text where a missing value legitimately renders empty."""
    return missing_values.display(row, metrics or {}, *keys, metric_keys=metric_keys)


def _result_source(row: Mapping[str, Any]) -> str:
    # Reuse the vocabulary's presence rules so a blank id never names the record.
    try:
        record = missing_values.identifier(row, {}, "report_result_id", "signal_id")
    except missing_values.MissingIdentifierError:
        return _REPORT_RESULT_SOURCE
    return f"{_REPORT_RESULT_SOURCE}:{record}"


def parse_report_result_row(row: Mapping[str, Any]) -> ReportResultRow:
    payload = dict(row)
    for key in (
        "report_result_id",
        "signal_id",
        "report_position_id",
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
        if not trade_result_display(payload, key):
            raise InvalidReportResultRow(key, "missing")

    status = trade_result_status(payload)
    match status:
        case (
            TradeResultStatus.WIN
            | TradeResultStatus.LOSS
            | TradeResultStatus.VOID
            | TradeResultStatus.SPLIT
        ):
            payload["result"] = status.value
        case TradeResultStatus.UNKNOWN:
            raise InvalidReportResultRow("result", "unknown")
        case _:
            assert_never(status)

    raw_side = payload.get("side")
    if raw_side not in (None, ""):
        try:
            payload["side"] = Side(str(raw_side).upper()).value
        except ValueError as exc:
            raise InvalidReportResultRow("side", "unknown") from exc

    raw_exit_mode = payload.get("exit_mode")
    try:
        payload["exit_mode"] = ExitMode(str(raw_exit_mode)).value
    except ValueError as exc:
        raise InvalidReportResultRow("exit_mode", "unknown") from exc

    for key in ("entry_price", "shares", "stake_usdc"):
        payload[key] = _finite_float(
            payload, key, allow_negative=False, allow_zero=False
        )
    for key in ("outcome_value", "settlement_value"):
        payload[key] = _finite_float(
            payload, key, allow_negative=False, allow_zero=True
        )
    for key in ("pnl_usdc", "roi"):
        payload[key] = _finite_float(payload, key, allow_negative=True)

    for key in ("opened_at", "closed_at"):
        value = payload.get(key)
        if value in (None, ""):
            continue
        if not isinstance(value, (str, datetime)):
            raise InvalidReportResultRow(key, "invalid timestamp")
        try:
            parsed_timestamp = parse_dt(value)
        except ValueError as exc:
            raise InvalidReportResultRow(key, "invalid timestamp") from exc
        if parsed_timestamp is None:
            raise InvalidReportResultRow(key, "invalid timestamp")

    details = payload.get("details")
    payload["details"] = dict(details) if isinstance(details, dict) else {}
    return ReportResultRow(**payload)


def _finite_float(
    row: Mapping[str, Any],
    key: str,
    *,
    allow_negative: bool,
    allow_zero: bool = True,
) -> float:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise InvalidReportResultRow(key, "missing")
    try:
        parsed = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise InvalidReportResultRow(key, "not numeric") from exc
    if not math.isfinite(parsed):
        raise InvalidReportResultRow(key, "not finite")
    if parsed < 0.0 and not allow_negative:
        raise InvalidReportResultRow(key, "negative")
    if parsed == 0.0 and not allow_zero:
        raise InvalidReportResultRow(key, "zero")
    return parsed


def trade_result_details(row: Mapping[str, Any]) -> dict[str, Any]:
    details = row.get("details")
    return dict(details) if isinstance(details, dict) else {}
