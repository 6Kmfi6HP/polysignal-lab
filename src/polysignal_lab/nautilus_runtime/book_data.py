from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from polysignal_lab.alpha.types import SideBookView, TradeView
from polysignal_lab.data.state import OrderBookRegistry
from polysignal_lab.domain.orderbook import OrderBook


@dataclass(frozen=True, slots=True)
class BookSnapshot:
    token_id: str
    bid: float | None
    ask: float | None
    spread: float | None
    freshness_ms: int | None
    received_at: datetime | None


_TRADES_DEQUE_MAXLEN = 512


class NautilusBookDataProvider:
    def __init__(self, registry: OrderBookRegistry | None = None) -> None:
        self._registry = registry
        self._books: dict[str, OrderBook] = {}
        self._trades: dict[str, deque[TradeView]] = {}
        # Separate cache for last-trade data: token_id → (price, size, side, timestamp_iso)
        # Avoids replacing the OrderBook on every trade tick via model_copy().
        self._last_trades: dict[str, tuple[float | None, float | None, str | None, str | None]] = {}
        # Cached derived fields so book_for_token avoids O(N) computed_field
        # traversal and tuple re-allocation on every evaluate_condition().
        self._cached_best_bid: dict[str, float | None] = {}
        self._cached_best_ask: dict[str, float | None] = {}
        self._cached_ask_levels: dict[str, tuple[tuple[float, float], ...]] = {}
        if registry is not None:
            self.update_from_registry(registry)

    def update_from_registry(self, registry: OrderBookRegistry) -> None:
        self._registry = registry
        for token_id, book in registry.books.items():
            self.update_book(token_id, book)

    def update_book(self, token_id: str, book: OrderBook) -> None:
        self._books[token_id] = book
        # Pre-compute derived fields once so book_for_token avoids O(N)
        # computed_field traversal and tuple re-allocation on every call.
        self._cached_best_bid[token_id] = max(
            (level.price for level in book.bids), default=None
        )
        self._cached_best_ask[token_id] = min(
            (level.price for level in book.asks), default=None
        )
        self._cached_ask_levels[token_id] = tuple(
            (float(level.price), float(level.size)) for level in book.asks
        )
        # Seed the last-trade cache from the book's own fields so they are
        # available even when update_trade is never called (e.g. on_order_book
        # snapshots from the Nautilus adapter already carry last-trade data).
        if token_id not in self._last_trades and any(
            (book.last_trade_price, book.last_trade_size, book.last_trade_timestamp)
        ):
            self._last_trades[token_id] = (
                book.last_trade_price,
                book.last_trade_size,
                book.last_trade_side,
                book.last_trade_timestamp,
            )

    def update_trade(
        self,
        token_id: str,
        *,
        price: float,
        size: float,
        side: str | None,
        ts: datetime | None,
    ) -> None:
        trades = self._trades.get(token_id)
        if trades is None:
            trades = deque[TradeView](maxlen=_TRADES_DEQUE_MAXLEN)
            self._trades[token_id] = trades
        trades.append(
            TradeView(price=price, size=size, side=side, ts=ts),
        )
        # Store last-trade fields in a separate lightweight cache instead of
        # copying the entire OrderBook. This eliminates OrderBook.model_copy()
        # allocation on every trade tick.
        self._last_trades[token_id] = (
            price,
            size,
            side,
            ts.isoformat() if ts is not None else None,
        )

    def _last_trade_parts(self, token_id: str) -> tuple[float | None, float | None, str | None, str | None]:
        return self._last_trades.get(token_id, (None, None, None, None))

    def book_for_token(self, token_id: str, *, now: datetime | None = None) -> SideBookView | None:
        book = self._book(token_id)
        if book is None:
            return None
        bid = self._cached_best_bid.get(token_id)
        ask = self._cached_best_ask.get(token_id)
        spread = round(ask - bid, 10) if bid is not None and ask is not None else None
        last_price, last_size, _last_side, last_ts = self._last_trade_parts(token_id)
        return SideBookView(
            token_id=token_id,
            best_bid=bid,
            best_ask=ask,
            spread=spread,
            freshness_ms=self._freshness_ms(token_id, book, now=now),
            min_order_size=getattr(book, "min_order_size", None),
            tick_size=getattr(book, "tick_size", None),
            # Read last-trade data from the separate cache, not from the OrderBook.
            last_trade_price=last_price,
            last_trade_size=last_size,
            last_trade_timestamp=last_ts,
            received_at=book.received_at,
            ask_levels=self._cached_ask_levels.get(token_id, ()),
        )

    def trades_for_token(self, token_id: str) -> Sequence[TradeView]:
        if self._registry is not None:
            return tuple(
                TradeView(
                    price=trade.price,
                    size=trade.size,
                    side=getattr(trade, "side", None),
                    ts=getattr(trade, "datetime", None),
                )
                for trade in self._registry.recent_trades(token_id)
            )
        return tuple(self._trades.get(token_id, ()))

    def snapshot_for_token(self, token_id: str, *, now: datetime | None = None) -> BookSnapshot | None:
        book = self._book(token_id)
        if book is None:
            return None
        bid = self._cached_best_bid.get(token_id)
        ask = self._cached_best_ask.get(token_id)
        spread = ask - bid if bid is not None and ask is not None else None
        return BookSnapshot(
            token_id=token_id,
            bid=bid,
            ask=ask,
            spread=spread,
            freshness_ms=self._freshness_ms(token_id, book, now=now),
            received_at=book.received_at,
        )

    def _book(self, token_id: str) -> OrderBook | None:
        if self._registry is not None:
            return self._registry.get(token_id) or self._books.get(token_id)
        return self._books.get(token_id)

    def _freshness_ms(self, token_id: str, book: OrderBook, *, now: datetime | None = None) -> int | None:
        now = now or datetime.now(UTC)
        if self._registry is not None:
            state = self._registry.get_state(token_id)
            if state is not None and state.last_received_at is not None:
                return max(0, int((now - state.last_received_at).total_seconds() * 1000))
        if book.received_at is None:
            return None
        return max(0, int((now - book.received_at).total_seconds() * 1000))
