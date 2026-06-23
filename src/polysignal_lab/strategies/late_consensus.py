from __future__ import annotations

from datetime import datetime

from polysignal_lab.config import LateConsensusConfig
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.freshness import FreshnessPolicy
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.strategies.base import BaseStrategy
from polysignal_lab.utils import utc_now


class LateConsensusStrategy(BaseStrategy):
    """Meridian Late Entry V3 strategy — exact 8-step entry flow.

    Implements the PolyBullLabs Meridian Late Entry V3 strategy:
      1. Time window (0 < seconds_till_end <= 240)
      2. Entry frequency (>= 7 seconds since last entry in this market)
      3. Spread check (ask_sum <= 1.05)
      4. Confidence check (|up_ask - down_ask| >= 0.30)
      5. Identify favorite side
      6. Price ceiling (favorite_price <= max_entry_price)
      7. (Delegated) Investment cap per-market ($300)
      8. Dynamic position sizing (8/10/12 contracts)

    Exit logic embedded via SignalCandidate metrics:
      - flip_stop: exit if price <= 0.48
      - per-coin stop_loss: fixed $ amount
    """

    name = "late_consensus"

    def __init__(self, config: LateConsensusConfig):
        self.config = config
        # Track last favorite per market for flip guard (Step 5 + side change detection)
        self._last_favorite: dict[str, tuple[Side, datetime]] = {}
        # Track last entry timestamp per market for frequency gating (Step 2)
        self._last_entry_at: dict[str, datetime] = {}

    @property
    def freshness_policy(self) -> FreshnessPolicy:
        return FreshnessPolicy(
            max_orderbook_staleness_ms=self.config.max_orderbook_staleness_ms,
            max_spot_staleness_ms=self.config.max_spot_staleness_ms,
        )

    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        # --- Pre-checks: enabled, asset, timeframe ---
        if not self.config.enabled:
            return []
        if snapshot.market.asset.upper() not in [a.upper() for a in self.config.assets]:
            return []
        if snapshot.market.timeframe not in self.config.timeframes:
            return []
        if snapshot.up_ask is None or snapshot.down_ask is None:
            return []

        market_id = snapshot.market.market_id
        seconds = snapshot.seconds_to_close
        up_ask = snapshot.up_ask
        down_ask = snapshot.down_ask

        # ===============================================================
        # Step 1: Time window check — market-interval-aware scaling
        #   15m → 240s, 5m → min(120, interval-10) = 120s
        # ===============================================================
        if seconds is None or seconds <= 0:
            return []
        market_interval_sec = self._derive_market_interval(snapshot)
        if market_interval_sec >= 900:
            effective_entry_window = self.config.entry_window_sec
        else:
            effective_entry_window = min(120, market_interval_sec - 10)
        if seconds > effective_entry_window:
            return []

        # ===============================================================
        # Step 2: Entry frequency check — at most once per 7 seconds per market
        # ===============================================================
        now = utc_now()
        last_entry = self._last_entry_at.get(market_id)
        if last_entry is not None:
            elapsed = (now - last_entry).total_seconds()
            if elapsed < self.config.entry_frequency_sec:
                return []

        # ===============================================================
        # Step 3: Spread = ask_sum (up_ask + down_ask) <= 1.05, > 0
        # ===============================================================
        ask_sum = up_ask + down_ask
        if ask_sum <= 0 or ask_sum > self.config.max_ask_sum:
            return []

        # ===============================================================
        # Step 4: Confidence = |up_ask - down_ask| >= 0.30
        # ===============================================================
        confidence_value = abs(up_ask - down_ask)
        if confidence_value < self.config.min_confidence_abs:
            return []

        # ===============================================================
        # Step 5: Identify favorite side
        #   up_ask > down_ask → favorite = UP, price = up_ask
        #   down_ask > up_ask → favorite = DOWN, price = down_ask
        # ===============================================================
        if up_ask > down_ask:
            favorite_side = Side.UP
            favorite_price = up_ask
        elif down_ask > up_ask:
            favorite_side = Side.DOWN
            favorite_price = down_ask
        else:
            return []  # tie — no clear favorite

        # --- Side change guard: block rapid direction flips (not flip-stop) ---
        if self._side_change_blocked(snapshot, favorite_side):
            return []

        # ===============================================================
        # Step 6: Price ceiling — favorite_price <= max_entry_price
        # ===============================================================
        if favorite_price > self.config.max_entry_price:
            return []

        # ===============================================================
        # Step 7: Investment cap per-market (delegated to paper wallet layer)
        #   We embed max_investment_per_market in signal metrics so the
        #   paper wallet / signal handling layer can enforce it.
        # ===============================================================

        # ===============================================================
        # Step 8: Dynamic position sizing — market-interval-aware
        #   Scaling factor = market_interval_sec / 900
        #   15m (900s): >180s → 8, >120s → 10, ≤120s → 12
        #    5m (300s):  >60s → 8,  >40s → 10,  ≤40s → 12
        # ===============================================================
        scale = market_interval_sec / 900.0
        high_threshold = int(180 * scale)
        mid_threshold = int(120 * scale)
        contracts = self._dynamic_position_size(seconds, high_threshold, mid_threshold)

        # --- Record this entry for frequency gating ---
        self._last_entry_at[market_id] = now

        # --- Build SignalCandidate with exit logic metadata ---
        reason_codes = [
            "LATE_V3_WINDOW_OK",
            "LATE_V3_FREQ_OK",
            "LATE_V3_ASK_SUM_OK",
            "LATE_V3_CONFIDENCE_OK",
            "LATE_V3_PRICE_OK",
            "LATE_CONSENSUS_SIDE_CHANGE_OK",
        ]

        # Standard confidence is the raw |up-down| confidence clamped 0..1
        signal_confidence = max(0.0, min(1.0, confidence_value))

        # Compute a synthetic "price" for confidence (matching original pattern)
        effective_confidence = min(0.95, confidence_value + 0.35)

        metrics = {
            # Entry decision details
            "confidence_raw": confidence_value,
            "confidence_abs": confidence_value,
            "ask_sum": round(ask_sum, 4),
            "up_ask": up_ask,
            "down_ask": down_ask,
            "favorite_side": favorite_side.value,
            "favorite_price": favorite_price,
            "seconds_to_close": seconds,
            "contracts": contracts,
            # Per-market investment cap for paper wallet enforcement
            "max_investment_per_market": self.config.max_investment_per_market,
            # Exit logic: flip-stop
            "flip_stop_enabled": self.config.flip_stop_enabled,
            "flip_stop_price": self.config.flip_stop_price,
            # Exit logic: per-coin stop-loss
            "stop_loss_enabled": True,
            "stop_loss_config": self.config.stop_loss_per_coin,
        }

        signal = self._candidate(
            snapshot,
            favorite_side,
            effective_confidence,
            max_entry_price=self.config.max_entry_price,
            reason_codes=reason_codes,
            metrics=metrics,
        )

        return [signal] if signal else []

    def _dynamic_position_size(self, seconds_remaining: int, high_threshold: int = 180, mid_threshold: int = 120) -> int:
        """Step 8: Dynamic position sizing based on time remaining.

        Thresholds are market-interval-aware (scaled by interval/900).
        15m (900s): high=180, mid=120; 5m (300s): high=60, mid=40.
        """
        if seconds_remaining > high_threshold:
            return self.config.sizing_above_180
        elif seconds_remaining > mid_threshold:
            return self.config.sizing_above_120
        else:
            return self.config.sizing_below_120

    @staticmethod
    def _derive_market_interval(snapshot: MarketSnapshot) -> int:
        """Derive market interval in seconds from snapshot timeframe.

        15m markets → 900s, 5m markets → 300s.
        """
        if snapshot.market.timeframe == "15m":
            return 900
        if snapshot.market.timeframe == "5m":
            return 300
        return 900

    def _side_change_blocked(self, snapshot: MarketSnapshot, side: Side) -> bool:
        """Side change guard: prevent rapid direction flips within the guard window.

        If the last recorded favorite for this market was the opposite side
        within the last `flip_guard_window_sec` seconds, block the entry.
        This is a strict side-change guard (not flip-stop).

        Only updates the tracked favorite when the entry is NOT blocked,
        so a blocked flip does not poison the state for the next call.
        """
        if not self.config.flip_guard_enabled:
            return False
        now = utc_now()
        previous = self._last_favorite.get(snapshot.market.market_id)
        if previous:
            prev_side, prev_time = previous
            if prev_side != side and (now - prev_time).total_seconds() <= self.config.flip_guard_window_sec:
                return True
        self._last_favorite[snapshot.market.market_id] = (side, now)
        return False
