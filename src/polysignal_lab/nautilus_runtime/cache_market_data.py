"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Iterable, collections.abc.Sequence, datetime, datetime.UTC, datetime.datetime, typing, typing.Callable, typing.cast
Output: NautilusCacheMarketDataProvider
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""




from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Callable, cast

from polysignal_lab.alpha.types import SideBookView, TradeView
from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.strategy.helpers import _maybe_float, _nautilus_instrument_id


class NautilusCacheMarketDataProvider:
    """Read current market data from Nautilus Cache without owning book/trade state."""

    def __init__(self, cache: object, *, catalog: MarketCatalog) -> None:
        self._cache: object = cache
        self._catalog: MarketCatalog = catalog

    def book_for_token(
        self,
        token_id: str,
        *,
        now: datetime | None = None,
    ) -> SideBookView | None:
        instrument_id = self._catalog.instrument_id_for_token(token_id)
        if instrument_id is None:
            return None
        book = self._cache_order_book(_nautilus_instrument_id(instrument_id))
        if book is None:
            return None
        bids = _levels(getattr(book, "bids", ()))
        asks = _levels(getattr(book, "asks", ()))
        best_bid = bids[0][0] if bids else None
        best_ask = asks[0][0] if asks else None
        spread = round(best_ask - best_bid, 10) if best_bid is not None and best_ask is not None else None
        received_at = _datetime_or_none(
            getattr(book, "received_at", getattr(book, "ts_last", None))
        )
        return SideBookView(
            token_id=token_id,
            best_bid=best_bid,
            best_ask=best_ask,
            spread=spread,
            freshness_ms=_freshness_ms(received_at, now) if now is not None else None,
            min_order_size=_maybe_float(getattr(book, "min_order_size", None)),
            tick_size=_maybe_float(getattr(book, "tick_size", None)),
            last_trade_price=_maybe_float(getattr(book, "last_trade_price", None)),
            last_trade_size=_maybe_float(getattr(book, "last_trade_size", None)),
            last_trade_timestamp=_optional_text(getattr(book, "last_trade_timestamp", None)),
            received_at=received_at,
            ask_levels=asks,
        )

    def trades_for_token(self, token_id: str) -> Sequence[TradeView]:
        instrument_id = self._catalog.instrument_id_for_token(token_id)
        if instrument_id is None:
            return ()
        getter = getattr(self._cache, "trade_ticks", None)
        if not callable(getter):
            return ()
        try:
            rows = cast(Callable[[object], object], getter)(_nautilus_instrument_id(instrument_id))
        except LookupError:
            return ()
        if not isinstance(rows, Iterable) or isinstance(rows, (str, bytes)):
            return ()
        return tuple(
            TradeView(
                price=_float_attr(row, "price"),
                size=_float_attr(row, "size"),
                side=_optional_text(getattr(row, "aggressor_side", getattr(row, "side", None))),
                ts=_datetime_or_none(getattr(row, "ts_event", getattr(row, "timestamp", None))),
            )
            for row in rows
        )

    def _cache_order_book(self, instrument_id: object) -> object | None:
        getter = getattr(self._cache, "order_book", None)
        if not callable(getter):
            return None
        try:
            return cast(Callable[[object], object | None], getter)(instrument_id)
        except LookupError:
            return None


def _levels(raw: object) -> tuple[tuple[float, float], ...]:
    if callable(raw):
        raw = raw()
    if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes)):
        return ()
    values: list[tuple[float, float]] = []
    for level in raw:
        price = _maybe_float(getattr(level, "price", None))
        size = _maybe_float(getattr(level, "size", None))
        if price is None or size is None or price <= 0 or size <= 0:
            continue
        values.append((price, size))
    return tuple(values)


def _float_attr(source: object, name: str) -> float:
    value = _maybe_float(getattr(source, name, None))
    return 0.0 if value is None else value


def _datetime_or_none(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    timestamp = _maybe_float(value)
    if timestamp is not None and timestamp > 0:
        return datetime.fromtimestamp(timestamp / 1_000_000_000, UTC)
    return None


def _optional_text(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _freshness_ms(received_at: datetime | None, now: datetime) -> int | None:
    if received_at is None:
        return None
    current = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    dt = received_at if received_at.tzinfo is not None else received_at.replace(tzinfo=UTC)
    return max(0, int((current.astimezone(UTC) - dt.astimezone(UTC)).total_seconds() * 1000))
