"""
Input: __future__, __future__.annotations, datetime, datetime.datetime, pydantic, pydantic.BaseModel, pydantic.Field, pydantic.computed_field
Output: BookLevel, OrderBook
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, computed_field

from polysignal_lab.utils import utc_now


class BookLevel(BaseModel):
    price: float
    size: float


class OrderBook(BaseModel):
    schema_version: int = 1
    market_id: str | None = None
    token_id: str
    bids: list[BookLevel] = Field(default_factory=list)
    asks: list[BookLevel] = Field(default_factory=list)
    last_trade_price: float | None = None
    last_trade_size: float | None = None
    last_trade_side: str | None = None
    last_trade_timestamp: str | None = None
    min_order_size: float | None = None
    tick_size: float | None = None
    source_timestamp: str | None = None
    hash: str | None = None
    received_at: datetime = Field(default_factory=utc_now)

    @computed_field
    @property
    def best_bid(self) -> float | None:
        return max((level.price for level in self.bids), default=None)

    @computed_field
    @property
    def best_ask(self) -> float | None:
        return min((level.price for level in self.asks), default=None)

    @computed_field
    @property
    def spread(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return round(max(0.0, self.best_ask - self.best_bid), 10)

    @computed_field
    @property
    def mid(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return self.last_trade_price
        return (self.best_bid + self.best_ask) / 2.0

    def freshness_ms(self, now: datetime | None = None) -> int:
        current = now or utc_now()
        return max(0, int((current - self.received_at).total_seconds() * 1000))

    def is_fresh(self, max_staleness_ms: int, now: datetime | None = None) -> bool:
        return self.freshness_ms(now) <= max_staleness_ms

    def depth_until(self, max_price: float) -> float:
        total_usdc = 0.0
        for level in sorted(self.asks, key=lambda x: x.price):
            if level.price <= max_price:
                total_usdc += level.price * level.size
        return total_usdc
