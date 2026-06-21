from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market
from polysignal_lab.domain.orderbook import OrderBook
from polysignal_lab.domain.spot import SpotPrice


@dataclass
class MarketRegistry:
    markets: dict[str, Market] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def upsert_many(self, markets: list[Market]) -> None:
        with self._lock:
            for market in markets:
                self.markets[market.market_id] = market

    def active(self) -> list[Market]:
        with self._lock:
            return [m for m in self.markets.values() if m.is_active]

    def get(self, market_id: str) -> Market | None:
        with self._lock:
            return self.markets.get(market_id)


@dataclass
class OrderBookRegistry:
    books: dict[str, OrderBook] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def update(self, book: OrderBook) -> None:
        with self._lock:
            self.books[book.token_id] = book

    def get(self, token_id: str) -> OrderBook | None:
        with self._lock:
            return self.books.get(token_id)

    def books_for_market(self, market: Market) -> tuple[OrderBook | None, OrderBook | None]:
        up = self.get(market.token_for(Side.UP).token_id) if any(t.side == Side.UP for t in market.outcome_tokens) else None
        down = self.get(market.token_for(Side.DOWN).token_id) if any(t.side == Side.DOWN for t in market.outcome_tokens) else None
        return up, down


@dataclass
class SpotRegistry:
    spots: dict[str, SpotPrice] = field(default_factory=dict)
    history: dict[str, list[SpotPrice]] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def update(self, spot: SpotPrice) -> None:
        asset = spot.asset.upper()
        with self._lock:
            self.spots[asset] = spot
            self.history.setdefault(asset, []).append(spot)
            self.history[asset] = self.history[asset][-512:]

    def get(self, asset: str) -> SpotPrice | None:
        with self._lock:
            return self.spots.get(asset.upper())

    def movement_pct(self, asset: str, lookback: int = 5) -> float | None:
        with self._lock:
            hist = self.history.get(asset.upper(), [])
            if len(hist) <= lookback:
                return None
            old = hist[-lookback - 1].price
            new = hist[-1].price
            return (new - old) / old if old else None
