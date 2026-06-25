from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol, Sequence

from polysignal_lab.domain.enums import OrderIntent, Side


@dataclass(frozen=True, slots=True)
class SideBookView:
    token_id: str
    best_bid: float | None
    best_ask: float | None
    spread: float | None
    freshness_ms: int | None
    min_order_size: float | None = None
    tick_size: float | None = None


@dataclass(frozen=True, slots=True)
class SpotView:
    asset: str
    symbol: str
    price: float
    source: str
    freshness_ms: int | None


@dataclass(frozen=True, slots=True)
class TradeView:
    price: float
    size: float
    side: str | None
    ts: datetime | None


@dataclass(frozen=True, slots=True)
class FreshnessView:
    up_book_ms: int | None
    down_book_ms: int | None
    spot_ms: int | None
    max_ms: int | None


@dataclass(frozen=True, slots=True)
class MarketView:
    view_id: str
    market_id: str
    market_slug: str
    condition_id: str
    asset: str
    timeframe: str
    start_ts: datetime | None
    end_ts: datetime | None
    created_at: datetime
    seconds_to_close: int | None
    up: SideBookView
    down: SideBookView
    spot: SpotView | None
    price_to_beat: float | None
    up_trades: Sequence[TradeView]
    down_trades: Sequence[TradeView]
    metrics: Mapping[str, Any]
    freshness: FreshnessView

    def book_for(self, side: Side) -> SideBookView:
        return self.up if side == Side.UP else self.down

    def ask_for(self, side: Side) -> float | None:
        return self.book_for(side).best_ask


@dataclass(frozen=True, slots=True)
class OrderIntentSpec:
    intent: OrderIntent
    expiry_seconds: int | None = None
    pair_id: str | None = None


@dataclass(frozen=True, slots=True)
class AlphaDecision:
    strategy: str
    asset: str
    timeframe: str
    market_id: str
    market_slug: str
    condition_id: str
    token_id: str
    side: Side
    confidence: float
    entry_reference_price: float
    max_entry_price: float
    seconds_to_close: int | None
    data_freshness_ms: int | None
    reason_codes: tuple[str, ...]
    metrics: Mapping[str, Any]
    order_intent: OrderIntentSpec | None = None
    hedge_leg: bool = False


class AlphaCore(Protocol):
    def evaluate(self, view: MarketView) -> list[AlphaDecision]: ...
