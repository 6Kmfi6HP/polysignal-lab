"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Mapping, datetime, datetime.date, datetime.datetime, typing, typing.Any, pydantic, pydantic.BaseModel, pydantic.Field, polysignal_lab.utils
Output: PaperWalletSnapshotRow, DailyReportRow, daily_report_row, wallet_float, report_float, report_text, report_date_text, report_nested_mapping, PaperWalletSnapshot, DailyReport
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
import math
from typing import Any, TypedDict

from pydantic import BaseModel, Field

from polysignal_lab.utils import new_id, utc_now


class PaperWalletSnapshotRow(TypedDict, total=False):
    schema_version: int
    wallet_id: str
    currency: str
    starting_balance: float
    cash_balance: float
    reserved_balance: float
    realized_pnl: float
    unrealized_pnl: float
    equity: float
    open_position_count: int
    created_at: str


class DailyReportRow(TypedDict, total=False):
    schema_version: int
    report_id: str
    report_date: str
    starting_equity: float
    ending_equity: float
    equity_currency: str
    paper_pnl: float
    paper_roi: float
    total_signals: int
    paper_orders: int
    paper_fills: int
    rejected_paper_orders: int
    stale_paper_fills: int
    paper_attempts_by_intent: dict[str, int]
    paper_fills_by_intent: dict[str, int]
    paper_partial_fills_by_intent: dict[str, int]
    paper_rejects_by_reason: dict[str, int]
    paper_rejects_by_original_reason: dict[str, int]
    average_execution_staleness_ms: float | None
    average_executable_depth_usdc: float | None
    paper_execution_assumptions: dict[str, Any]
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


def wallet_float(row: Mapping[str, Any] | Any, key: str, default: float = 0.0) -> float:
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
    return wallet_float(row, key, default)


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


class PaperWalletSnapshot(BaseModel):
    schema_version: int = 1
    wallet_id: str = "default"
    currency: str = "USDC"
    starting_balance: float
    cash_balance: float
    reserved_balance: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    equity: float
    open_position_count: int
    created_at: datetime = Field(default_factory=utc_now)


class DailyReport(BaseModel):
    schema_version: int = 1
    report_id: str = Field(default_factory=lambda: new_id("dr"))
    report_date: date
    starting_equity: float
    ending_equity: float
    equity_currency: str = "USDC"
    paper_pnl: float
    paper_roi: float
    total_signals: int
    paper_orders: int
    paper_fills: int
    rejected_paper_orders: int
    stale_paper_fills: int = 0
    paper_attempts_by_intent: dict[str, int] = Field(default_factory=dict)
    paper_fills_by_intent: dict[str, int] = Field(default_factory=dict)
    paper_partial_fills_by_intent: dict[str, int] = Field(default_factory=dict)
    paper_rejects_by_reason: dict[str, int] = Field(default_factory=dict)
    paper_rejects_by_original_reason: dict[str, int] = Field(default_factory=dict)
    average_execution_staleness_ms: float | None = None
    average_executable_depth_usdc: float | None = None
    paper_execution_assumptions: dict[str, Any] = Field(default_factory=dict)
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
