from __future__ import annotations

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


class NautilusBookDataProvider:
    def __init__(self, registry: OrderBookRegistry | None = None) -> None:
        self._registry = registry
        self._books: dict[str, OrderBook] = {}
        self._trades: dict[str, list[TradeView]] = {}
        # Separate cache for last-trade data: token_id → (price, size, side, timestamp_iso)
        # Avoids replacing the OrderBook on every trade tick via model_copy().
        self._last_trades: dict[str, tuple[float | None, float | None, str | None, str | None]] = {}
        if registry is not None:
            self.update_from_registry(registry)

    def update_from_registry(self, registry: OrderBookRegistry) -> None:
        self._registry = registry
        for token_id, book in registry.books.items():
            self.update_book(token_id, book)

    def update_book(self, token_id: str, book: OrderBook) -> None:
        self._books[token_id] = book
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
        self._trades.setdefault(token_id, []).append(
            TradeView(price=price, size=size, side=side, ts=ts),
        )
        self._trades[token_id] = self._trades[token_id][-512:]
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

    def book_for_token(self, token_id: str) -> SideBookView | None:
        book = self._book(token_id)
        if book is None:
            return None
        bid = book.best_bid
        ask = book.best_ask
        spread = round(ask - bid, 10) if bid is not None and ask is not None else None
        last_price, last_size, _last_side, last_ts = self._last_trade_parts(token_id)
        return SideBookView(
            token_id=token_id,
            best_bid=bid,
            best_ask=ask,
            spread=spread,
            freshness_ms=self._freshness_ms(token_id, book),
            min_order_size=getattr(book, "min_order_size", None),
            tick_size=getattr(book, "tick_size", None),
            # Read last-trade data from the separate cache, not from the OrderBook.
            last_trade_price=last_price,
            last_trade_size=last_size,
            last_trade_timestamp=last_ts,
            received_at=book.received_at,
            ask_levels=tuple((float(level.price), float(level.size)) for level in book.asks),
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

    def snapshot_for_token(self, token_id: str) -> BookSnapshot | None:
        book = self._book(token_id)
        if book is None:
            return None
        bid = book.best_bid
        ask = book.best_ask
        spread = ask - bid if bid is not None and ask is not None else None
        return BookSnapshot(
            token_id=token_id,
            bid=bid,
            ask=ask,
            spread=spread,
            freshness_ms=self._freshness_ms(token_id, book),
            received_at=book.received_at,
        )

    def _book(self, token_id: str) -> OrderBook | None:
        if self._registry is not None:
            return self._registry.get(token_id) or self._books.get(token_id)
        return self._books.get(token_id)

    def _freshness_ms(self, token_id: str, book: OrderBook) -> int | None:
        if self._registry is not None:
            state = self._registry.get_state(token_id)
            if state is not None and state.last_received_at is not None:
                return max(0, int((datetime.now(UTC) - state.last_received_at).total_seconds() * 1000))
        if book.received_at is None:
            return None
        return max(0, int((datetime.now(UTC) - book.received_at).total_seconds() * 1000))
