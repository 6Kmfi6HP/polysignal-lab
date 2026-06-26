from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from polysignal_lab.domain.enums import OrderStatus, Side
from polysignal_lab.utils import new_id, utc_now


class PaperOrder(BaseModel):
    schema_version: int = 1
    paper_order_id: str = Field(default_factory=lambda: new_id("po"))
    signal_id: str
    created_at: datetime = Field(default_factory=utc_now)
    asset: str
    timeframe: str
    strategy: str
    market_id: str
    market_slug: str
    token_id: str
    side: Side
    order_type: str = "SIMULATED_MARKETABLE_LIMIT"
    order_intent: str | None = None
    limit_price: float
    reference_price: float
    stake_usdc: float
    shares: float | None = None
    signal_confidence: float | None = None
    pair_id: str | None = None
    reduce_only: bool = False
    hedge_leg: bool = False
    status: OrderStatus = OrderStatus.PENDING
    reject_reason: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class PaperFill(BaseModel):
    schema_version: int = 1
    paper_fill_id: str = Field(default_factory=lambda: new_id("pf"))
    paper_order_id: str
    signal_id: str
    created_at: datetime = Field(default_factory=utc_now)
    token_id: str
    side: Side
    raw_best_ask: float
    slippage_bps: float
    fill_price: float
    stake_usdc: float
    shares: float
    depth_checked: bool
    available_depth_usdc: float | None = None
    fill_ratio: float = 1.0
    metrics: dict[str, Any] = Field(default_factory=dict)
