from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
import math
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field

from polysignal_lab.utils import new_id, utc_now


EquitySource = Literal[
    "portfolio",
    "account_balance",
    "starting_balance",
    "report_results",
]


class ReportAccountSnapshotRow(TypedDict, total=False):
    schema_version: int
    account_id: str
    currency: str
    starting_balance: float
    cash_balance: float
    realized_pnl: float
    unrealized_pnl: float
    equity: float
    open_position_count: int
    created_at: str


class DailyReportRow(TypedDict, total=False):
    schema_version: int
    report_id: str
    report_date: str
    revision: int
    starting_equity: float
    ending_equity: float
    equity_currency: str
    equity_source: EquitySource | None
    net_pnl: float
    return_rate: float
    total_signals: int
    order_count: int
    fill_count: int
    rejected_order_count: int
    stale_fill_count: int
    order_attempts_by_intent: dict[str, int]
    fills_by_intent: dict[str, int]
    partial_fills_by_intent: dict[str, int]
    rejects_by_reason: dict[str, int]
    rejects_by_original_reason: dict[str, int]
    average_execution_staleness_ms: float | None
    average_executable_depth_usdc: float | None
    execution_assumptions: dict[str, Any]
    telemetry_status: str
    telemetry_incomplete_reasons: list[str]
    open_positions: int
    closed_positions: int
    win_count: int
    loss_count: int
    void_count: int
    win_rate: float
    total_pnl_usdc: float
    average_roi: float
    max_drawdown: float
    profit_factor: float | None
    strategy_breakdown: dict[str, dict[str, Any]]
    asset_breakdown: dict[str, dict[str, Any]]
    timeframe_breakdown: dict[str, dict[str, Any]]
    calibration_breakdown: dict[str, dict[str, Any]]
    created_at: str


def _row_value(row: Mapping[str, Any] | Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


def account_float(
    row: Mapping[str, Any] | Any, key: str, default: float = 0.0
) -> float:
    value = _row_value(row, key, default)
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float, str)):
        try:
            parsed = float(value)
        except (OverflowError, TypeError, ValueError):
            return default
        return parsed if math.isfinite(parsed) else default
    return default


def report_float(row: Mapping[str, Any] | Any, key: str, default: float = 0.0) -> float:
    return account_float(row, key, default)


def report_text(row: Mapping[str, Any] | Any, key: str, default: str = "") -> str:
    value = _row_value(row, key, default)
    if value is None:
        return default
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def report_date_text(row: Mapping[str, Any] | Any) -> str:
    value = _row_value(row, "report_date", "")
    if isinstance(value, date):
        return value.isoformat()
    return str(value) if value is not None else ""


def report_nested_mapping(
    row: Mapping[str, Any] | Any,
    key: str,
) -> dict[str, Any]:
    value = _row_value(row, key, {})
    return dict(value) if isinstance(value, dict) else {}


def daily_report_row(report: DailyReport) -> DailyReportRow:
    return DailyReportRow(**report.model_dump(mode="json"))


class ReportAccountSnapshot(BaseModel):
    schema_version: int = 1
    account_id: str = "default"
    currency: str = "USDC"
    starting_balance: float
    cash_balance: float
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    equity: float
    open_position_count: int
    created_at: datetime = Field(default_factory=utc_now)


class DailyReport(BaseModel):
    schema_version: int = 1
    report_id: str = Field(default_factory=lambda: new_id("dr"))
    report_date: date
    revision: int = Field(default=1, ge=1)
    starting_equity: float
    ending_equity: float
    equity_currency: str = "USDC"
    equity_source: EquitySource | None = None
    net_pnl: float
    return_rate: float
    total_signals: int
    order_count: int
    fill_count: int
    rejected_order_count: int
    stale_fill_count: int = 0
    order_attempts_by_intent: dict[str, int] = Field(default_factory=dict)
    fills_by_intent: dict[str, int] = Field(default_factory=dict)
    partial_fills_by_intent: dict[str, int] = Field(default_factory=dict)
    rejects_by_reason: dict[str, int] = Field(default_factory=dict)
    rejects_by_original_reason: dict[str, int] = Field(default_factory=dict)
    average_execution_staleness_ms: float | None = None
    average_executable_depth_usdc: float | None = None
    execution_assumptions: dict[str, Any] = Field(default_factory=dict)
    telemetry_status: Literal["complete", "incomplete"] = "complete"
    telemetry_incomplete_reasons: list[str] = Field(default_factory=list)
    open_positions: int
    closed_positions: int
    win_count: int
    loss_count: int
    void_count: int
    win_rate: float
    total_pnl_usdc: float
    average_roi: float
    max_drawdown: float
    profit_factor: float | None
    strategy_breakdown: dict[str, Any] = Field(default_factory=dict)
    asset_breakdown: dict[str, Any] = Field(default_factory=dict)
    timeframe_breakdown: dict[str, Any] = Field(default_factory=dict)
    calibration_breakdown: dict[str, dict[str, Any]] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
