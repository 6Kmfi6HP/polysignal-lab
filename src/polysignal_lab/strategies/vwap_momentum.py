from __future__ import annotations

from collections import defaultdict

from polysignal_lab.config import VWAPMomentumConfig
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.trade import Trade
from polysignal_lab.strategies.base import BaseStrategy


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

    def _prune(self, key: str, window_sec: float, now: float) -> None:
        trades = self._trades.get(key)
        if not trades:
            return
        cutoff = now - window_sec
        # Remove expired trades while keeping at least 1 for momentum reference
        idx = 0
        while idx < len(trades) - 1 and trades[idx].timestamp < cutoff:
            idx += 1
        if idx > 0:
            self._trades[key] = trades[idx:]

    def trades_in_window(self, key: str, window_sec: float, now: float) -> list[Trade]:
        self._prune(key, window_sec, now)
        return list(self._trades.get(key, []))

    def vwap(self, key: str, window_sec: float, now: float) -> float | None:
        trades = self.trades_in_window(key, window_sec, now)
        if not trades:
            return None
        total_vol = sum(t.size for t in trades)
        if total_vol <= 0:
            return None
        return sum(t.price * t.size for t in trades) / total_vol

    def momentum_pct(self, key: str, window_sec: float, now: float) -> float | None:
        """Return the percentage price change over the window.

        Formula: ((P_latest - P_earliest) / P_earliest) * 100

        Returns None if we don't have enough data.
        """
        trades = self.trades_in_window(key, window_sec, now)
        if len(trades) < 2:
            return None
        p0 = trades[0].price
        p1 = trades[-1].price
        if p0 <= 0:
            return None
        return ((p1 - p0) / p0) * 100.0

    def latest_price(self, key: str) -> float | None:
        trades = self._trades.get(key)
        if not trades:
            return None
        return trades[-1].price

    def clear_key(self, key: str) -> None:
        self._trades.pop(key, None)


class VWAPMomentumStrategy(BaseStrategy):
    """PolyBullLabs VWAP / Deviation / Momentum signal strategy.

    Evaluates market snapshots using the same logic as PolyBullLabs'
    VWAP momentum bot:
      - VWAP computed over `vwap_window_sec` of trades
      - Deviation = ((price - VWAP) / VWAP) * 100 (percentage)
      - Momentum = % price change over `momentum_window_sec`
      - Favorite side = the token with the higher last-trade price
      - Entry window: [min_elapsed_sec, duration - no_entry_before_end_sec]
      - Per-market one-shot entry (can_enter flag)
    """

    name = "vwap_momentum"

    def __init__(self, config: VWAPMomentumConfig):
        self.config = config
        self.trades = TradeHistory()
        # Per-market one-shot entry guard: market_id -> bool
        self._can_enter: dict[str, bool] = defaultdict(lambda: True)

    def reset_entry_guard(self, market_id: str) -> None:
        """Re-allow entry for a market (used by tests or manual reset)."""
        self._can_enter[market_id] = True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _market_key(self, market_id: str, side: Side) -> str:
        return f"{market_id}:{side.value}"

    # ------------------------------------------------------------------
    # Evaluate
    # ------------------------------------------------------------------

    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        if not self.config.enabled:
            return []
        asset_upper = snapshot.market.asset.upper()
        if asset_upper not in [a.upper() for a in self.config.assets]:
            return []
        if snapshot.market.timeframe not in self.config.timeframes:
            return []

        seconds_to_close = snapshot.seconds_to_close
        if seconds_to_close is None:
            return []

        # ------------------------------------------------------------------
        # PolyBullLabs 原版逻辑: elapsed_sec = duration_sec - time_left
        # 即自市场开始以来的秒数 = (end_ts - start_ts) - (end_ts - now)
        #                         = now - start_ts
        # 如果 start_ts 不可用, 用 seconds_to_close 推算
        # ------------------------------------------------------------------
        dt_duration = None
        if snapshot.market.start_ts and snapshot.market.end_ts:
            dt_duration = (snapshot.market.end_ts - snapshot.market.start_ts).total_seconds()
        elif snapshot.market.end_ts:
            # 5m = 300s, 15m = 900s — 从 slug 推断
            if snapshot.market.timeframe == "5m":
                dt_duration = 300.0
            elif snapshot.market.timeframe == "15m":
                dt_duration = 900.0

        elapsed_sec: float | None = None
        if dt_duration is not None and dt_duration > 0:
            elapsed_sec = dt_duration - seconds_to_close

        # ------------------------------------------------------------------
        # Feed prices from this snapshot (使用 ask 价格而非 ltp)
        # 原版用 WS trade stream 的 last_price, 我们 REST 环境改用 ask
        # ------------------------------------------------------------------
        now_ts = snapshot.created_at.timestamp()
        for side in [Side.UP, Side.DOWN]:
            book = snapshot.book_for(side)
            if book is None:
                continue
            # 用 best_ask 作为 "当前价格" (PolyBullLabs VWAP 用 last_trade_price,
            # 但 REST 模式下 best_ask 是更可靠的实时价格源)
            price = book.best_ask if book.best_ask is not None else book.last_trade_price
            if price is not None and price > 0:
                key = self._market_key(snapshot.market.market_id, side)
                self.trades.push(key, price, 1.0, now_ts)

        # ------------------------------------------------------------------
        # Determine favorite side (higher current price)
        # ------------------------------------------------------------------
        up_key = self._market_key(snapshot.market.market_id, Side.UP)
        down_key = self._market_key(snapshot.market.market_id, Side.DOWN)

        up_price = self.trades.latest_price(up_key)
        down_price = self.trades.latest_price(down_key)
        if up_price is None or down_price is None:
            return []

        fav_side = Side.UP if up_price >= down_price else Side.DOWN
        fav_price = up_price if fav_side == Side.UP else down_price
        fav_key = self._market_key(snapshot.market.market_id, fav_side)

        # ------------------------------------------------------------------
        # Condition 1: Price in range
        # ------------------------------------------------------------------
        if not (self.config.min_price <= fav_price <= self.config.max_price):
            return []

        # ------------------------------------------------------------------
        # Condition 2: Enough time elapsed (原版: elapsed_sec >= min_elapsed)
        # ------------------------------------------------------------------
        if elapsed_sec is not None and elapsed_sec < self.config.min_elapsed_sec:
            return []

        # ------------------------------------------------------------------
        # Condition 3: Not too close to end
        # ------------------------------------------------------------------
        if seconds_to_close <= self.config.no_entry_before_end_sec:
            return []

        # ------------------------------------------------------------------
        # VWAP & Deviation (percentage)
        # ------------------------------------------------------------------
        vwap = self.trades.vwap(fav_key, self.config.vwap_window_sec, now_ts)
        if vwap is None or vwap <= 0:
            return []

        deviation_pct = ((fav_price - vwap) / vwap) * 100.0

        # Condition 4: Deviation in range
        if not (self.config.min_deviation_pct < deviation_pct < self.config.max_deviation_pct):
            return []

        # ------------------------------------------------------------------
        # Momentum (%) — 原版用 WS trade stream 的价格变化
        # 我们改用 ask 价格序列的动量
        # ------------------------------------------------------------------
        momentum = self.trades.momentum_pct(
            fav_key, self.config.momentum_window_sec, now_ts
        )
        if momentum is None:
            return []

        # Condition 5: Positive momentum above noise threshold
        if momentum <= self.config.min_momentum_pct:
            return []

        # ------------------------------------------------------------------
        # One-shot entry guard (per-market)
        # ------------------------------------------------------------------
        if not self._can_enter[snapshot.market.market_id]:
            return []

        # Mark this market as entered (one-shot)
        self._can_enter[snapshot.market.market_id] = False

        # ------------------------------------------------------------------
        # Build signal
        # ------------------------------------------------------------------
        confidence = self._compute_confidence(deviation_pct, momentum)

        signal = self._candidate(
            snapshot,
            fav_side,
            confidence,
            max_entry_price=min(self.config.max_price, fav_price + 0.05),
            reason_codes=[
                "VWAP_DEVIATION_OK",
                "MOMENTUM_OK",
                "FAVORITE_SELECTED",
                "ENTRY_WINDOW_OK",
            ],
            metrics={
                "vwap": vwap,
                "deviation_pct": deviation_pct,
                "momentum_pct": momentum,
                "favorite_side": fav_side.value,
                "fav_price": fav_price,
                "elapsed_sec": elapsed_sec,
                "seconds_to_close": seconds_to_close,
                "up_last_price": up_price,
                "down_last_price": down_price,
            },
        )
        return [signal] if signal else []

    # ------------------------------------------------------------------
    # Confidence calculation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_confidence(deviation_pct: float, momentum_pct: float) -> float:
        """Map deviation + momentum to a confidence score in [0, 1].

        Matches PolyBullLabs heuristic: stronger deviation and momentum
        produce higher confidence, capped at 0.95.
        """
        # Base confidence
        base = 0.50
        # Deviation contribution: each 1% deviation beyond minimum adds ~2%
        dev_contrib = max(0.0, min(0.25, abs(deviation_pct) * 0.02))
        # Momentum contribution: each 5% momentum adds ~3%
        mom_contrib = max(0.0, min(0.20, momentum_pct * 0.006))
        return min(0.95, base + dev_contrib + mom_contrib)
