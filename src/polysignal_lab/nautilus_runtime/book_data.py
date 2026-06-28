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
        if registry is not None:
            self.update_from_registry(registry)

    def update_from_registry(self, registry: OrderBookRegistry) -> None:
        self._registry = registry
        for token_id, book in registry.books.items():
            self.update_book(token_id, book)

    def update_book(self, token_id: str, book: OrderBook) -> None:
        self._books[token_id] = book

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
        book = self._book(token_id)
        if book is not None:
            updated = book.model_copy(deep=True)
            updated.last_trade_price = price
            updated.last_trade_size = size
            updated.last_trade_side = side
            updated.last_trade_timestamp = ts.isoformat() if ts is not None else None
            self._books[token_id] = updated

    def book_for_token(self, token_id: str) -> SideBookView | None:
        book = self._book(token_id)
        if book is None:
            return None
        bid = book.best_bid
        ask = book.best_ask
        spread = round(ask - bid, 10) if bid is not None and ask is not None else None
        return SideBookView(
            token_id=token_id,
            best_bid=bid,
            best_ask=ask,
            spread=spread,
            freshness_ms=self._freshness_ms(token_id, book),
            min_order_size=getattr(book, "min_order_size", None),
            tick_size=getattr(book, "tick_size", None),
            last_trade_price=book.last_trade_price,
            last_trade_size=book.last_trade_size,
            last_trade_timestamp=book.last_trade_timestamp,
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
