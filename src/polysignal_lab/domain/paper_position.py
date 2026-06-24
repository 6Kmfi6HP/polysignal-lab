from __future__ import annotations

from datetime import datetime

from typing import Any
from pydantic import BaseModel, Field

from polysignal_lab.domain.enums import PositionStatus, Side
from polysignal_lab.utils import new_id, utc_now


class PaperPosition(BaseModel):
    schema_version: int = 1
    paper_position_id: str = Field(default_factory=lambda: new_id("pp"))
    signal_id: str
    paper_order_id: str
    paper_fill_id: str
    strategy: str
    asset: str
    timeframe: str
    market_id: str
    market_slug: str
    token_id: str
    side: Side
    entry_price: float
    shares: float
    stake_usdc: float
    signal_confidence: float | None = None
    signal_metrics: dict[str, Any] = Field(default_factory=dict)
    opened_at: datetime = Field(default_factory=utc_now)
    status: PositionStatus = PositionStatus.OPEN
    closed_at: datetime | None = None
