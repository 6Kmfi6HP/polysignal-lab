"""
Input: __future__, __future__.annotations, dataclasses, dataclasses.dataclass, dataclasses.field, datetime, datetime.datetime, datetime.timezone, threading, threading.Lock
Output: parse_source_timestamp, MarketRegistry, OrderBookRegistry, SpotRegistry
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from polysignal_lab.data.book_reconciliation import BookEpochState
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market
from polysignal_lab.domain.orderbook import OrderBook
from polysignal_lab.domain.spot import SpotPrice
from polysignal_lab.domain.trade import Trade
from polysignal_lab.observability.metrics import MetricsRegistry


def parse_source_timestamp(ts_val: Any) -> datetime | None:
    if not ts_val:
        return None
    try:
        val = float(ts_val)
        if val > 1e11:
            val = val / 1000.0
        return datetime.fromtimestamp(val, tz=timezone.utc)
    except (ValueError, TypeError, OverflowError):
        try:
            return datetime.fromisoformat(str(ts_val).replace("Z", "+00:00"))
        except ValueError:
            return None

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
    states: dict[str, BookEpochState] = field(default_factory=dict)
    telemetries: dict[str, dict[str, Any]] = field(default_factory=dict)
    trade_events: dict[str, list[Trade]] = field(default_factory=dict)
    metrics: MetricsRegistry = field(default_factory=MetricsRegistry)
    _lock: Lock = field(default_factory=Lock)

    def update(self, book: OrderBook) -> None:
        self.update_from_snapshot(book)

    def get(self, token_id: str) -> OrderBook | None:
        with self._lock:
            return self.books.get(token_id)

    def recent_trades(self, token_id: str) -> list[Trade]:
        with self._lock:
            return list(self.trade_events.get(token_id, ()))

    def get_state(self, token_id: str) -> BookEpochState | None:
        with self._lock:
            return self.states.get(token_id)

    def mark_stale(self, token_id: str, reason: str) -> None:
        with self._lock:
            state = self.states.get(token_id)
            if state is None:
                state = BookEpochState(
                    token_id=token_id,
                    epoch=2,
                    has_snapshot=False,
                    stale_reason=reason,
                    last_hash=None,
                    last_source_timestamp=None,
                    last_received_at=None,
                )
                self.states[token_id] = state
            else:
                state.epoch += 1
                state.has_snapshot = False
                state.stale_reason = reason
                state.last_hash = None

    def is_fill_eligible(self, token_id: str, max_staleness_ms: int, now: datetime) -> bool:
        with self._lock:
            state = self.states.get(token_id)
            if state is None or not state.has_snapshot:
                reason = state.stale_reason if state else "NO_SNAPSHOT"
                self.metrics.inc(f"paper_fill_rejected_{reason}")
                return False

            book = self.books.get(token_id)
            if book is None:
                self.metrics.inc("paper_fill_rejected_MISSING_BOOK")
                return False

            staleness_ms = int((now - book.received_at).total_seconds() * 1000)
            if staleness_ms > max_staleness_ms:
                self.metrics.inc("paper_fill_rejected_STALE_ORDERBOOK")
                return False

            return True

    def _check_sequence_validity(
        self, state: BookEpochState, book: OrderBook
    ) -> bool:
        """Validate the sequence of a book update.

        Returns False (and marks state stale) if the update is chronologically
        before the last known state. Returns True if the update should proceed.
        """
        new_ts = parse_source_timestamp(book.source_timestamp)
        if new_ts and state.last_source_timestamp and new_ts < state.last_source_timestamp:
            state.has_snapshot = False
            state.stale_reason = "BOOK_SEQUENCE_INVALID"
            self.metrics.inc("book_sequence_invalid")
            return False
        state.last_source_timestamp = new_ts or state.last_source_timestamp
        state.last_received_at = book.received_at
        return True

    def update_from_snapshot(self, book: OrderBook) -> None:
        token_id = book.token_id
        with self._lock:
            state = self.states.get(token_id)
            if state is None:
                state = BookEpochState(
                    token_id=token_id,
                    epoch=1,
                    has_snapshot=True,
                    stale_reason=None,
                    last_hash=getattr(book, "hash", None),
                    last_source_timestamp=parse_source_timestamp(book.source_timestamp),
                    last_received_at=book.received_at,
                )
                self.states[token_id] = state
            elif self._check_sequence_validity(state, book):
                state.has_snapshot = True
                state.stale_reason = None
                state.last_hash = getattr(book, "hash", None)
            else:
                return

            self.books[token_id] = book

    def update_from_delta(self, book: OrderBook) -> None:
        token_id = book.token_id
        with self._lock:
            state = self.states.get(token_id)
            if state is None or not state.has_snapshot:
                self.metrics.inc("delta_without_snapshot")
                return

            if not self._check_sequence_validity(state, book):
                return

            self.books[token_id] = book

    def update_telemetry(self, token_id: str, best_bid: float | None, best_ask: float | None) -> None:
        with self._lock:
            telemetry = self.telemetries.setdefault(token_id, {})
            if best_bid is not None:
                telemetry["best_bid"] = best_bid
            if best_ask is not None:
                telemetry["best_ask"] = best_ask

    def update_last_trade(
        self,
        token_id: str,
        price: float,
        size: float | None = None,
        side: str | None = None,
        timestamp: str | None = None,
    ) -> None:
        with self._lock:
            book = self.books.get(token_id)
            if book is not None:
                updated = book.model_copy(deep=True)
                updated.last_trade_price = price
                updated.last_trade_size = size
                updated.last_trade_side = side
                updated.last_trade_timestamp = timestamp
                self.books[token_id] = updated
            if size is not None and size > 0:
                event_time = parse_source_timestamp(timestamp) or datetime.now(timezone.utc)
                self.trade_events.setdefault(token_id, []).append(
                    Trade(price=price, size=size, timestamp=event_time.timestamp())
                )
                self.trade_events[token_id] = self.trade_events[token_id][-512:]

    def telemetry_for(self, token_id: str) -> dict[str, str | int | float | bool | None]:
        with self._lock:
            state = self.states.get(token_id)
            book = self.books.get(token_id)
            telemetry = self.telemetries.get(token_id, {})

            best_bid = telemetry.get("best_bid")
            best_ask = telemetry.get("best_ask")

            if best_bid is None and book is not None:
                best_bid = book.best_bid
            if best_ask is None and book is not None:
                best_ask = book.best_ask

            return {
                "token_id": token_id,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "last_trade_price": book.last_trade_price if book else None,
                "epoch": state.epoch if state else 0,
                "has_snapshot": state.has_snapshot if state else False,
                "stale_reason": state.stale_reason if state else "NO_SNAPSHOT",
            }

    def _book_with_snapshot(self, token_id: str) -> OrderBook | None:
        with self._lock:
            state = self.states.get(token_id)
            if state is None or not state.has_snapshot:
                return None
            return self.books.get(token_id)

    def books_for_market(self, market: Market) -> tuple[OrderBook | None, OrderBook | None]:
        up = (
            self._book_with_snapshot(market.token_for(Side.UP).token_id)
            if any(t.side == Side.UP for t in market.outcome_tokens)
            else None
        )
        down = (
            self._book_with_snapshot(market.token_for(Side.DOWN).token_id)
            if any(t.side == Side.DOWN for t in market.outcome_tokens)
            else None
        )
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
