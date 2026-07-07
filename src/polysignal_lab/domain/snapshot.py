"""
Input: __future__, __future__.annotations, datetime, datetime.datetime, typing, typing.Any, pydantic, pydantic.BaseModel, pydantic.Field, pydantic.computed_field
Output: FreshnessState, MarketSnapshot
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, computed_field

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market
from polysignal_lab.domain.orderbook import OrderBook
from polysignal_lab.domain.spot import SpotPrice
from polysignal_lab.utils import utc_now


class FreshnessState(BaseModel):
    up_book_ms: int | None = None
    down_book_ms: int | None = None
    spot_ms: int | None = None
    max_ms: int | None = None


class MarketSnapshot(BaseModel):
    schema_version: int = 1
    snapshot_id: str
    created_at: datetime = Field(default_factory=utc_now)
    market: Market
    up_book: OrderBook | None = None
    down_book: OrderBook | None = None
    spot: SpotPrice | None = None
    price_to_beat: float | None = None
    freshness: FreshnessState = Field(default_factory=FreshnessState)
    metrics: dict[str, Any] = Field(default_factory=dict)

    @computed_field
    @property
    def seconds_to_close(self) -> int | None:
        if self.market.end_ts is None:
            return None
        return max(0, int((self.market.end_ts - self.created_at).total_seconds()))

    def book_for(self, side: Side) -> OrderBook | None:
        return self.up_book if side == Side.UP else self.down_book

    def ask_for(self, side: Side) -> float | None:
        book = self.book_for(side)
        return book.best_ask if book else None

    def bid_for(self, side: Side) -> float | None:
        book = self.book_for(side)
        return book.best_bid if book else None

    @computed_field
    @property
    def up_ask(self) -> float | None:
        return self.ask_for(Side.UP)

    @computed_field
    @property
    def down_ask(self) -> float | None:
        return self.ask_for(Side.DOWN)

    @computed_field
    @property
    def max_spread(self) -> float | None:
        spreads = [b.spread for b in [self.up_book, self.down_book] if b and b.spread is not None]
        return max(spreads) if spreads else None

    @computed_field
    @property
    def ask_sum(self) -> float | None:
        if self.up_ask is None or self.down_ask is None:
            return None
        return self.up_ask + self.down_ask

    @computed_field
    @property
    def ask_skew(self) -> float | None:
        if self.up_ask is None or self.down_ask is None:
            return None
        return abs(self.up_ask - self.down_ask)

    @computed_field
    @property
    def favorite_side(self) -> Side | None:
        if self.up_ask is None or self.down_ask is None:
            return None
        return Side.UP if self.up_ask >= self.down_ask else Side.DOWN
