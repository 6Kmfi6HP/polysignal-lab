from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class _TradeLike(Protocol):
    price: float
    size: float


@dataclass(frozen=True, slots=True)
class TradeSample:
    price: float
    size: float
    timestamp: float


def samples_from_trade_views(
    trades: Sequence[object],
    *,
    now_ts: float,
) -> tuple[TradeSample, ...]:
    """Normalize Cache-projected trade views into timestamped samples."""
    samples: list[TradeSample] = []
    for raw in trades:
        sample = _sample(raw, now_ts=now_ts)
        if sample is not None:
            samples.append(sample)
    return tuple(samples)


def latest_price(trades: Sequence[TradeSample]) -> float | None:
    if not trades:
        return None
    return trades[-1].price


def trades_in_window(
    trades: Sequence[TradeSample],
    window_sec: float,
    now: float,
) -> tuple[TradeSample, ...]:
    cutoff = now - window_sec
    return tuple(trade for trade in trades if trade.timestamp >= cutoff)


def vwap(
    trades: Sequence[TradeSample],
    window_sec: float,
    now: float,
) -> float | None:
    windowed = trades_in_window(trades, window_sec, now)
    if not windowed:
        return None
    total_vol = sum(trade.size for trade in windowed)
    if total_vol <= 0:
        return None
    return sum(trade.price * trade.size for trade in windowed) / total_vol


def momentum(
    trades: Sequence[TradeSample],
    window_sec: float,
    now: float,
) -> float | None:
    """Price change vs arithmetic mean price ~window_sec seconds ago.

    Uses a time-band approach matching PolyBullLabs:
    takes all trades in [now - window_sec - 1.5, now - window_sec + 1.5]
    (a 3-second band), computes the arithmetic mean of prices in that
    band, and returns the fractional change from that mean to the
    current price.
    """
    if not trades:
        return None

    band_start = now - window_sec - 1.5
    band_end = now - window_sec + 1.5
    band_prices = [
        trade.price for trade in trades if band_start <= trade.timestamp <= band_end
    ]
    if not band_prices:
        return None

    mean_price_ago = sum(band_prices) / len(band_prices)
    if mean_price_ago <= 0:
        return None

    current = latest_price(trades)
    if current is None or current <= 0:
        return None
    return (current - mean_price_ago) / mean_price_ago


def _sample(raw: object, *, now_ts: float) -> TradeSample | None:
    price = getattr(raw, "price", None)
    size = getattr(raw, "size", None)
    if not isinstance(price, (int, float)) or not isinstance(size, (int, float)):
        return None
    if float(price) <= 0 or float(size) <= 0:
        return None

    timestamp = now_ts
    ts = getattr(raw, "ts", None)
    if isinstance(ts, datetime):
        timestamp = ts.timestamp()
    else:
        raw_ts = getattr(raw, "timestamp", None)
        if isinstance(raw_ts, (int, float)) and float(raw_ts) > 0:
            timestamp = float(raw_ts)

    return TradeSample(price=float(price), size=float(size), timestamp=timestamp)
