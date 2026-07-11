"""
Input: collections, polysignal_lab.domain.trade
Output: TradeHistory
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from collections import defaultdict

from polysignal_lab.domain.trade import Trade


class TradeHistory:
    """Time-windowed trade history per (market_id, side) key.

    Mirrors PolyBullLabs' deque of Trade objects used for VWAP,
    deviation, and momentum calculations.
    """

    def __init__(self) -> None:
        # key -> list[Trade] sorted oldest-first
        self._trades: dict[str, list[Trade]] = defaultdict(list)

    def push(self, key: str, price: float, size: float, timestamp: float) -> None:
        self._trades[key].append(Trade(price=price, size=size, timestamp=timestamp))

    def remove(self, key: str, price: float, size: float, timestamp: float) -> None:
        trades = self._trades.get(key)
        if not trades:
            return
        for idx in range(len(trades) - 1, -1, -1):
            trade = trades[idx]
            if (
                trade.price == price
                and trade.size == size
                and trade.timestamp == timestamp
            ):
                del trades[idx]
                if not trades:
                    self._trades.pop(key, None)
                return

    def _prune(self, key: str, window_sec: float, now: float) -> None:
        """Trim trades older than ``window_sec`` from storage.

        Momentum needs the band around ``now - window_sec`` while VWAP needs the
        recent window itself. We keep only data that could still affect either
        calculation, plus the newest trade so ``latest_price`` remains available.
        """
        trades = self._trades.get(key)
        if not trades:
            return
        cutoff = now - window_sec
        idx = 0
        while idx < len(trades) - 1 and trades[idx].timestamp < cutoff:
            idx += 1
        if idx > 0:
            self._trades[key] = trades[idx:]

    def trades_in_window(self, key: str, window_sec: float, now: float) -> list[Trade]:
        """Return trades within the window WITHOUT modifying storage."""
        trades = self._trades.get(key)
        if not trades:
            return []
        cutoff = now - window_sec
        return [trade for trade in trades if trade.timestamp >= cutoff]

    def vwap(self, key: str, window_sec: float, now: float) -> float | None:
        trades = self.trades_in_window(key, window_sec, now)
        if not trades:
            return None
        total_vol = sum(trade.size for trade in trades)
        if total_vol <= 0:
            return None
        return sum(trade.price * trade.size for trade in trades) / total_vol

    def momentum(self, key: str, window_sec: float, now: float) -> float | None:
        """Return price change versus the mean price near the prior window."""
        trades = self._trades.get(key)
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

        current_price = self.latest_price(key)
        if current_price is None or current_price <= 0:
            return None
        return (current_price - mean_price_ago) / mean_price_ago

    def latest_price(self, key: str) -> float | None:
        trades = self._trades.get(key)
        if not trades:
            return None
        return trades[-1].price

    def prune(self, key: str, window_sec: float, now: float) -> None:
        """Trim stored trades older than ``window_sec``."""
        self._prune(key, window_sec, now)

    def trades_for_key(self, key: str) -> tuple[Trade, ...]:
        """Return an immutable snapshot of trades for ``key``."""
        return tuple(self._trades.get(key, ()))

    def all_trades(self) -> dict[str, tuple[Trade, ...]]:
        """Return immutable per-key snapshots of all stored trades."""
        return {key: tuple(trades) for key, trades in self._trades.items()}

    def clear_key(self, key: str) -> None:
        self._trades.pop(key, None)
