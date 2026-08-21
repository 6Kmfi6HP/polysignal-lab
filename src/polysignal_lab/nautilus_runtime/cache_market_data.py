from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Callable, cast

from polysignal_lab.alpha.types import SideBookView, TradeView
from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.strategy.nautilus_objects import (
    _maybe_float,
    _nautilus_instrument_id,
)


class NautilusCacheMarketDataProvider:
    """Read current market data from Nautilus Cache without owning book/trade state."""

    def __init__(self, cache: object, *, catalog: MarketCatalog) -> None:
        self._cache: object = cache
        self._catalog: MarketCatalog = catalog
        self._book_received_at_by_token: dict[str, datetime] = {}

    def observe_book_received(
        self,
        token_id: str,
        *,
        received_at: datetime,
    ) -> None:
        observed = (
            received_at
            if received_at.tzinfo is not None
            else received_at.replace(tzinfo=UTC)
        ).astimezone(UTC)
        previous = self._book_received_at_by_token.get(token_id)
        if previous is None or observed >= previous:
            self._book_received_at_by_token[token_id] = observed

    def book_for_token(
        self,
        token_id: str,
        *,
        now: datetime | None = None,
    ) -> SideBookView | None:
        instrument_id = self._catalog.instrument_id_for_token(token_id)
        if instrument_id is None:
            return None
        native_id = _nautilus_instrument_id(instrument_id)
        book = self._cache_order_book(native_id)
        if book is None:
            return None
        bids, asks, price_precision, size_precision = self._book_levels(book, native_id)
        best_bid = bids[0][0] if bids else None
        best_ask = asks[0][0] if asks else None
        spread = None
        if best_bid is not None and best_ask is not None:
            spread = _decimal_spread(best_ask, best_bid, price_precision)
        received_at = self._book_received_at_by_token.get(token_id)
        if received_at is None:
            received_at = _datetime_or_none(getattr(book, "received_at", None))
        return SideBookView(
            token_id=token_id,
            best_bid=best_bid,
            best_ask=best_ask,
            spread=spread,
            freshness_ms=_freshness_ms(received_at, now) if now is not None else None,
            min_order_size=_quantized_float(
                _maybe_float(getattr(book, "min_order_size", None)), size_precision
            ),
            tick_size=_maybe_float(getattr(book, "tick_size", None)),
            last_trade_price=_quantized_float(
                _maybe_float(getattr(book, "last_trade_price", None)),
                price_precision,
            ),
            last_trade_size=_quantized_float(
                _maybe_float(getattr(book, "last_trade_size", None)),
                size_precision,
            ),
            last_trade_timestamp=_optional_text(
                getattr(book, "last_trade_timestamp", None)
            ),
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
            rows = cast(Callable[[object], object], getter)(
                _nautilus_instrument_id(instrument_id)
            )
        except LookupError:
            return ()
        if not isinstance(rows, Iterable) or isinstance(rows, (str, bytes)):
            return ()
        precisions = self._instrument_precisions(_nautilus_instrument_id(instrument_id))
        price_precision = precisions[0] if precisions is not None else None
        size_precision = precisions[1] if precisions is not None else None
        return tuple(
            TradeView(
                price=_quantized_attr(row, "price", price_precision),
                size=_quantized_attr(row, "size", size_precision),
                side=_optional_text(
                    getattr(row, "aggressor_side", getattr(row, "side", None))
                ),
                ts=_datetime_or_none(
                    getattr(row, "ts_event", getattr(row, "timestamp", None))
                ),
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

    def _instrument_precisions(self, instrument_id: object) -> tuple[int, int] | None:
        """Resolve the authoritative instrument precision from the Cache.

        Returns (price_precision, size_precision) when the cache exposes the
        instrument; None otherwise (tests/offline consumers keep raw floats).
        """
        getter = getattr(self._cache, "instrument", None)
        if not callable(getter):
            return None
        try:
            instrument = cast(Callable[[object], object | None], getter)(instrument_id)
        except LookupError:
            return None
        if instrument is None:
            return None
        price_precision = getattr(instrument, "price_precision", None)
        size_precision = getattr(instrument, "size_precision", None)
        if not isinstance(price_precision, int) or not isinstance(size_precision, int):
            return None
        return price_precision, size_precision

    def _book_levels(
        self, book: object, instrument_id: object
    ) -> tuple[
        tuple[tuple[float, float], ...],
        tuple[tuple[float, float], ...],
        int | None,
        int | None,
    ]:
        precisions = self._instrument_precisions(instrument_id)
        price_precision = precisions[0] if precisions is not None else None
        size_precision = precisions[1] if precisions is not None else None
        bids = _levels(
            getattr(book, "bids", ()),
            price_precision=price_precision,
            size_precision=size_precision,
        )
        asks = _levels(
            getattr(book, "asks", ()),
            price_precision=price_precision,
            size_precision=size_precision,
        )
        return bids, asks, price_precision, size_precision


def _levels(
    raw: object,
    *,
    price_precision: int | None,
    size_precision: int | None,
) -> tuple[tuple[float, float], ...]:
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
        quantized_price = _quantized_float(price, price_precision)
        quantized_size = _quantized_float(size, size_precision)
        if quantized_price is None or quantized_size is None or quantized_price <= 0:
            continue
        values.append((quantized_price, quantized_size))
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
    dt = (
        received_at
        if received_at.tzinfo is not None
        else received_at.replace(tzinfo=UTC)
    )
    return max(
        0, int((current.astimezone(UTC) - dt.astimezone(UTC)).total_seconds() * 1000)
    )


def _quantized_attr(source: object, name: str, precision: int | None) -> float:
    quantized = _quantized_float(_float_attr(source, name), precision)
    return 0.0 if quantized is None else quantized


def _quantized_float(value: float | None, precision: int | None) -> float | None:
    """Quantize a float onto an exact decimal grid without binary float noise.

    ``precision=None`` (no instrument metadata) passes the value through.
    Conversion goes through Decimal(str(value)): a book price 0.42 at
    precision 3 becomes exactly 0.42, and Decimal difference/spread math never
    produces 0.010000000000000009 artifacts.
    """
    if value is None or precision is None:
        return value
    try:
        decimal = Decimal(str(value))
        quantum = Decimal(1).scaleb(-precision)
        return float(decimal.quantize(quantum))
    except (InvalidOperation, ValueError):
        # Extreme magnitudes beyond the decimal grid keep their raw float.
        return value


def _decimal_spread(
    best_ask: float,
    best_bid: float,
    price_precision: int | None,
) -> float:
    """Exact (Decimal) ask-bid spread, quantized to the price grid."""
    try:
        spread = Decimal(str(best_ask)) - Decimal(str(best_bid))
        if price_precision is not None:
            spread = spread.quantize(Decimal(1).scaleb(-price_precision))
        return float(spread)
    except (InvalidOperation, ValueError):
        return float(best_ask) - float(best_bid)
