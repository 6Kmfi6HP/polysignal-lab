"""
Input: __future__, decimal, logging, typing
Output: normalize_market_data_to_instrument
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

logger = logging.getLogger("polysignal_lab.nautilus.market_data_precision")


def normalize_market_data_to_instrument(data: object, instrument: object) -> object:
    """Return market data whose price/size precision matches ``instrument``.

    Nautilus OrderMatchingEngine rejects QuoteTick / TradeTick / OrderBookDelta
    when the embedded Price.precision differs from instrument.price_precision.
    Polymarket residual market data can carry shorter decimals after tick size
    moves. This rebuilds only mismatched fields via instrument.make_price /
    make_qty.
    """
    if data is None or instrument is None:
        return data

    type_name = type(data).__name__
    if type_name == "QuoteTick":
        return _normalize_quote_tick(data, instrument)
    if type_name == "TradeTick":
        return _normalize_trade_tick(data, instrument)
    if type_name == "OrderBookDelta":
        return _normalize_order_book_delta(data, instrument)
    if type_name == "OrderBookDeltas":
        return _normalize_order_book_deltas(data, instrument)
    return data


def _normalize_quote_tick(tick: object, instrument: object) -> object:
    original_bid_price = getattr(tick, "bid_price")
    original_ask_price = getattr(tick, "ask_price")
    original_bid_size = getattr(tick, "bid_size")
    original_ask_size = getattr(tick, "ask_size")
    bid_price = _normalize_price(original_bid_price, instrument)
    ask_price = _normalize_price(original_ask_price, instrument)
    bid_size = _normalize_qty(original_bid_size, instrument)
    ask_size = _normalize_qty(original_ask_size, instrument)
    if (
        bid_price is original_bid_price
        and ask_price is original_ask_price
        and bid_size is original_bid_size
        and ask_size is original_ask_size
    ):
        return tick

    from nautilus_trader.model.data import QuoteTick

    _log_normalized(
        instrument,
        data_kind="QuoteTick",
        instrument_id=getattr(tick, "instrument_id", None),
        details=(
            f"bid_price precision {getattr(original_bid_price, 'precision', None)} -> "
            f"{getattr(bid_price, 'precision', None)}, "
            f"ask_price precision {getattr(original_ask_price, 'precision', None)} -> "
            f"{getattr(ask_price, 'precision', None)}"
        ),
    )
    return QuoteTick(
        instrument_id=getattr(tick, "instrument_id"),
        bid_price=bid_price,
        ask_price=ask_price,
        bid_size=bid_size,
        ask_size=ask_size,
        ts_event=int(getattr(tick, "ts_event")),
        ts_init=int(getattr(tick, "ts_init")),
    )


def _normalize_trade_tick(tick: object, instrument: object) -> object:
    original_price = getattr(tick, "price")
    original_size = getattr(tick, "size")
    price = _normalize_price(original_price, instrument)
    size = _normalize_qty(original_size, instrument)
    if price is original_price and size is original_size:
        return tick

    from nautilus_trader.model.data import TradeTick

    _log_normalized(
        instrument,
        data_kind="TradeTick",
        instrument_id=getattr(tick, "instrument_id", None),
        details=(
            f"price precision {getattr(original_price, 'precision', None)} -> "
            f"{getattr(price, 'precision', None)}"
        ),
    )
    return TradeTick(
        instrument_id=getattr(tick, "instrument_id"),
        price=price,
        size=size,
        aggressor_side=getattr(tick, "aggressor_side"),
        trade_id=getattr(tick, "trade_id"),
        ts_event=int(getattr(tick, "ts_event")),
        ts_init=int(getattr(tick, "ts_init")),
    )


def _normalize_order_book_delta(delta: object, instrument: object) -> object:
    order = getattr(delta, "order", None)
    if order is None:
        return delta
    original_price = getattr(order, "price", None)
    original_size = getattr(order, "size", None)
    price = _normalize_price(original_price, instrument)
    size = _normalize_qty(original_size, instrument)
    if price is original_price and size is original_size:
        return delta

    from nautilus_trader.model.data import BookOrder, OrderBookDelta

    _log_normalized(
        instrument,
        data_kind="OrderBookDelta",
        instrument_id=getattr(delta, "instrument_id", None),
        details=(
            f"price precision {getattr(original_price, 'precision', None)} -> "
            f"{getattr(price, 'precision', None)}"
        ),
    )
    new_order = BookOrder(
        side=getattr(order, "side"),
        price=price,
        size=size,
        order_id=int(getattr(order, "order_id")),
    )
    return OrderBookDelta(
        instrument_id=getattr(delta, "instrument_id"),
        action=getattr(delta, "action"),
        order=new_order,
        flags=int(getattr(delta, "flags")),
        sequence=int(getattr(delta, "sequence")),
        ts_event=int(getattr(delta, "ts_event")),
        ts_init=int(getattr(delta, "ts_init")),
    )


def _normalize_order_book_deltas(batch: object, instrument: object) -> object:
    deltas = list(getattr(batch, "deltas"))
    changed = False
    normalized: list[Any] = []
    for delta in deltas:
        fixed = _normalize_order_book_delta(delta, instrument)
        if fixed is not delta:
            changed = True
        normalized.append(fixed)
    if not changed:
        return batch

    from nautilus_trader.model.data import OrderBookDeltas

    return OrderBookDeltas(getattr(batch, "instrument_id"), normalized)


def _normalize_price(price: object, instrument: object) -> object:
    if price is None:
        return price
    target = getattr(instrument, "price_precision", None)
    current = getattr(price, "precision", None)
    if not isinstance(target, int) or not isinstance(current, int) or current == target:
        return price
    maker = getattr(instrument, "make_price", None)
    if not callable(maker):
        return price

    # Match native_order / Polymarket adapter: quantize via instrument helpers
    price_text = format(Decimal(str(price)).quantize(Decimal(1).scaleb(-target)), f".{target}f")
    return maker(Decimal(price_text))


def _normalize_qty(size: object, instrument: object) -> object:
    if size is None:
        return size
    target = getattr(instrument, "size_precision", None)
    current = getattr(size, "precision", None)
    if not isinstance(target, int) or not isinstance(current, int) or current == target:
        return size
    maker = getattr(instrument, "make_qty", None)
    if not callable(maker):
        return size
    size_text = format(Decimal(str(size)).quantize(Decimal(1).scaleb(-target)), f".{target}f")
    return maker(Decimal(size_text))


def _log_normalized(
    instrument: object,
    *,
    data_kind: str,
    instrument_id: object,
    details: str,
) -> None:
    instrument_precision = getattr(instrument, "price_precision", None)
    logger.warning(
        "Normalized %s price precision for instrument_id=%s instrument.price_precision=%s (%s)",
        data_kind,
        instrument_id,
        instrument_precision,
        details,
    )
