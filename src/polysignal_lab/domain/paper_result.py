from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from polysignal_lab.domain.enums import ExitMode, Side, TradeResultStatus
from polysignal_lab.utils import new_id, utc_now


class PaperTradeResult(BaseModel):
    schema_version: int = 1
    paper_trade_id: str = Field(default_factory=lambda: new_id("pt"))
    signal_id: str
    paper_position_id: str
    strategy: str
    asset: str
    timeframe: str
    market_id: str
    market_slug: str
    side: Side
    entry_price: float
    shares: float
    stake_usdc: float
    exit_mode: ExitMode
    outcome_value: float
    settlement_value: float
    pnl_usdc: float
    roi: float
    result: TradeResultStatus
    opened_at: datetime
    closed_at: datetime = Field(default_factory=utc_now)
    details: dict[str, Any] = Field(default_factory=dict)


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
    paper_pnl: float
    paper_roi: float
    total_signals: int
    paper_orders: int
    paper_fills: int
    rejected_paper_orders: int
    stale_paper_fills: int = 0
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
    created_at: datetime = Field(default_factory=utc_now)
