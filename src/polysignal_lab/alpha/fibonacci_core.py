"""
Input: __future__, __future__.annotations, collections, collections.defaultdict, collections.deque, typing, typing.Any, typing.Mapping, polysignal_lab.alpha.state, polysignal_lab.alpha.state.json_safe_state
Output: _RollingPriceStats, ZigZagDetector, FibonacciCalculator, FibonacciAlphaCore
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""








from __future__ import annotations

from collections import deque
from typing import Any, Mapping, Sequence, TypedDict

from polysignal_lab.alpha.helpers import (
    OrderDecisionSpec,
    build_order_decision,
    enabled_for_view,
)
from polysignal_lab.alpha.state import json_safe_state
from polysignal_lab.alpha.stats import _RollingPriceStats
from polysignal_lab.alpha.types import AlphaDecision, MarketView, OrderIntentSpec
from polysignal_lab.domain.enums import OrderIntent, Side


class _FibState(TypedDict):
    spot_price: float
    symbol: str


class _FibSetup(TypedDict):
    swing_high: float
    swing_low: float
    fib_levels: dict[float, float]


class ZigZagDetector:
    """Percentage-threshold ZigZag swing-high/low detector (pure)."""

    def __init__(self, threshold_pct: float) -> None:
        self.threshold_pct = threshold_pct
        self._prices: deque[float] = deque(maxlen=200)
        self._swing_highs: deque[float] = deque(maxlen=10)
        self._swing_lows: deque[float] = deque(maxlen=10)
        self._current_trend: str | None = None
        self._extreme_price: float | None = None

    def push(self, price: float) -> None:
        self._prices.append(price)
        n = len(self._prices)
        if n < 2:
            return
        if n == 2:
            self._current_trend = "up" if price > self._prices[0] else "down"
            self._extreme_price = price
            return
        prev = self._prices[-2]
        if price > prev:
            new_direction = "up"
        elif price < prev:
            new_direction = "down"
        else:
            return
        extreme_price = self._extreme_price
        if extreme_price is None:
            self._extreme_price = price
            return
        if new_direction == self._current_trend:
            if (new_direction == "up" and price > extreme_price) or (
                new_direction == "down" and price < extreme_price
            ):
                self._extreme_price = price
        else:
            if self._extreme_price is not None and self._extreme_price > 0:
                change_pct = abs(price - self._extreme_price) / self._extreme_price
                if change_pct >= self.threshold_pct:
                    if self._current_trend == "up":
                        self._swing_highs.append(self._extreme_price)
                    else:
                        self._swing_lows.append(self._extreme_price)
                    self._current_trend = new_direction
                    self._extreme_price = price

    def _finalize_last_extreme(self) -> None:
        if self._current_trend is None or self._extreme_price is None:
            return
        if self._current_trend == "up":
            if not self._swing_highs or self._extreme_price != self._swing_highs[-1]:
                self._swing_highs.append(self._extreme_price)
        else:
            if not self._swing_lows or self._extreme_price != self._swing_lows[-1]:
                self._swing_lows.append(self._extreme_price)

    @property
    def high(self) -> float | None:
        return self._swing_highs[-1] if self._swing_highs else None

    @property
    def low(self) -> float | None:
        return self._swing_lows[-1] if self._swing_lows else None

    def has_swing(self) -> bool:
        return bool(self._swing_highs) and bool(self._swing_lows)

    def current_swing_high(self) -> float | None:
        return self._swing_highs[-1] if self._swing_highs else None

    def current_swing_low(self) -> float | None:
        return self._swing_lows[-1] if self._swing_lows else None


class FibonacciCalculator:
    """Fibonacci retracement/extension level calculator (pure)."""

    def __init__(self, ratios: tuple[float, ...]) -> None:
        self.ratios = ratios

    def retracement_levels(
        self, swing_high: float, swing_low: float
    ) -> dict[float, float]:
        diff = swing_high - swing_low
        if diff <= 0:
            return {}
        return {ratio: swing_high - ratio * diff for ratio in self.ratios}

    @staticmethod
    def is_in_zone(
        current_price: float, fib_level_price: float, zone_width_pct: float
    ) -> bool:
        zone = fib_level_price * zone_width_pct
        if zone <= 0:
            return current_price == fib_level_price
        return abs(current_price - fib_level_price) <= zone


class FibonacciAlphaCore:
    name = "fibonacci_bot"

    def __init__(self, config) -> None:
        self.config = config
        self._candles: dict[str, deque[float]] = {}
        self._zigzag: dict[str, ZigZagDetector] = {}
        self._fib_calc = FibonacciCalculator(config.ratios)
        self._momentum = _RollingPriceStats(window_size=config.momentum_window)

    def _ensure_candles(self, symbol: str) -> deque[float]:
        if symbol not in self._candles:
            self._candles[symbol] = deque(maxlen=100)
        return self._candles[symbol]

    def _ensure_zigzag(self, symbol: str) -> ZigZagDetector:
        if symbol not in self._zigzag:
            self._zigzag[symbol] = ZigZagDetector(threshold_pct=self.config.zigzag_pct)
        return self._zigzag[symbol]

    def _check_momentum(self, symbol: str, current_price: float) -> bool:
        if not self.config.require_momentum_confirmation:
            return True
        stats = self._momentum.stats(symbol)
        z = stats.get("z_score")
        if z is None or stats.get("count", 0) < self.config.momentum_window:
            return False
        return abs(z) >= self.config.min_momentum_zscore

    def _determine_side(
        self, spot_price: float, fib_level_price: float
    ) -> Side | None:
        if spot_price <= fib_level_price:
            return Side.UP
        return Side.DOWN

    # -- guard helpers -------------------------------------------------------

    def _validate_inputs(self, view: MarketView) -> bool:
        return enabled_for_view(self.config, view)

    def _update_state(self, view: MarketView) -> _FibState | None:
        if view.spot is None or view.spot.price <= 0:
            return None
        spot_price = view.spot.price
        symbol = view.spot.symbol
        candles = self._ensure_candles(symbol)
        candles.append(spot_price)
        self._momentum.push(symbol, spot_price)
        return {"spot_price": spot_price, "symbol": symbol}

    def _compute_fib_setup(self, symbol: str, spot_price: float) -> _FibSetup | None:
        zigzag = self._ensure_zigzag(symbol)
        zigzag.push(spot_price)
        zigzag._finalize_last_extreme()
        if not zigzag.has_swing():
            return None
        swing_high = zigzag.current_swing_high()
        swing_low = zigzag.current_swing_low()
        if swing_high is None or swing_low is None or swing_high <= swing_low:
            return None
        fib_levels = self._fib_calc.retracement_levels(swing_high, swing_low)
        if not fib_levels:
            return None
        return {"swing_high": swing_high, "swing_low": swing_low, "fib_levels": fib_levels}

    # -- decision helpers ----------------------------------------------------

    def _build_fib_decisions(
        self, view: MarketView, state: _FibState, setup: _FibSetup
    ) -> list[AlphaDecision]:
        spot_price = state["spot_price"]
        symbol = state["symbol"]
        swing_high = setup["swing_high"]
        swing_low = setup["swing_low"]
        fib_levels = setup["fib_levels"]
        cfg = self.config
        decisions: list[AlphaDecision] = []
        for idx, (ratio, fib_price) in enumerate(fib_levels.items()):
            if not FibonacciCalculator.is_in_zone(
                spot_price, fib_price, cfg.zone_width_pct
            ):
                continue
            side = self._determine_side(spot_price, fib_price)
            if side is None:
                continue
            book = view.book_for(side)
            if book.best_ask is None:
                continue
            token_ask = book.best_ask
            if token_ask > cfg.max_token_price:
                continue

            weight_idx = min(idx, len(cfg.fib_size_weights) - 1)
            weight = cfg.fib_size_weights[weight_idx]
            confidence = max(
                0.45, min(0.85, 0.70 + (0.236 - ratio) / 0.236 * 0.15)
            )

            mom_stats = self._momentum.stats(symbol)
            metrics: dict[str, Any] = {
                "spot_price": spot_price,
                "swing_high": swing_high,
                "swing_low": swing_low,
                "fib_ratio": ratio,
                "fib_price": round(fib_price, 8),
                "zone_width_pct": cfg.zone_width_pct,
                "token_ask": token_ask,
                "weight": weight,
                "momentum_confirmed": cfg.require_momentum_confirmation,
                "momentum_z": mom_stats.get("z_score"),
                "momentum_vwap": mom_stats.get("vwap"),
                "created_at_for_test": view.created_at,
            }

            decision = build_order_decision(
                self.name,
                view,
                side,
                OrderDecisionSpec(
                    confidence=confidence,
                    max_entry_price=min(token_ask + cfg.offset_from_fib, cfg.max_token_price),
                    reason_codes=(
                        "FIBONACCI_ZONE",
                        f"RATIO_{ratio:.3f}",
                        f"SIDE_{side.value}",
                        f"WEIGHT_{weight}",
                    ),
                    metrics=metrics,
                    order_intent=OrderIntentSpec(
                        intent=OrderIntent.PASSIVE_GTD, expiry_seconds=300
                    ),
                ),
            )
            if decision is not None:
                decisions.append(decision)

        return decisions

    # -- entry point ---------------------------------------------------------

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        if not self._validate_inputs(view):
            return []
        state = self._update_state(view)
        if state is None or not self._check_momentum(state["symbol"], state["spot_price"]):
            return []
        setup = self._compute_fib_setup(state["symbol"], state["spot_price"])
        if setup is None:
            return []
        return self._build_fib_decisions(view, state, setup)

    # --- StatefulAlphaCore -------------------------------------------------

    def save_state(self) -> Mapping[str, object]:
        return json_safe_state(
            {
                "candles": {k: list(v) for k, v in self._candles.items()},
                "zigzag": {
                    k: {
                        "threshold_pct": d.threshold_pct,
                        "prices": list(d._prices),
                        "swing_highs": list(d._swing_highs),
                        "swing_lows": list(d._swing_lows),
                        "current_trend": d._current_trend,
                        "extreme_price": d._extreme_price,
                    }
                    for k, d in self._zigzag.items()
                },
                "momentum": {k: list(v) for k, v in self._momentum.values.items()},
            }
        )

    def load_state(self, payload: Mapping[str, object]) -> None:
        candles_raw = payload.get("candles", {}) or {}
        if not isinstance(candles_raw, Mapping):
            candles_raw = {}
        self._candles = {
            str(k): deque(
                (float(str(item)) for item in v),
                maxlen=100,
            )
            for k, v in candles_raw.items()
            if isinstance(v, Sequence) and not isinstance(v, str)
        }

        zigzag_raw = payload.get("zigzag", {}) or {}
        if not isinstance(zigzag_raw, Mapping):
            zigzag_raw = {}
        self._zigzag = {}
        for k, d in zigzag_raw.items():
            if not isinstance(d, Mapping):
                continue
            det = ZigZagDetector(threshold_pct=float(str(d["threshold_pct"])))
            prices = d.get("prices", ())
            swing_highs = d.get("swing_highs", ())
            swing_lows = d.get("swing_lows", ())
            if isinstance(prices, Sequence) and not isinstance(prices, str):
                det._prices.extend(float(str(item)) for item in prices)
            if isinstance(swing_highs, Sequence) and not isinstance(swing_highs, str):
                det._swing_highs.extend(float(str(item)) for item in swing_highs)
            if isinstance(swing_lows, Sequence) and not isinstance(swing_lows, str):
                det._swing_lows.extend(float(str(item)) for item in swing_lows)
            current_trend = d.get("current_trend")
            det._current_trend = current_trend if isinstance(current_trend, str) else None
            extreme_price = d.get("extreme_price")
            det._extreme_price = (
                float(str(extreme_price)) if extreme_price is not None else None
            )
            self._zigzag[str(k)] = det

        momentum_raw = payload.get("momentum", {}) or {}
        if not isinstance(momentum_raw, Mapping):
            momentum_raw = {}
        new_momentum = _RollingPriceStats(window_size=self.config.momentum_window)
        for k, entries in momentum_raw.items():
            if not isinstance(entries, Sequence):
                continue
            new_momentum.values[str(k)] = deque(
                (
                    (float(str(entry[0])), float(str(entry[1])))
                    for entry in entries
                    if isinstance(entry, Sequence) and len(entry) == 2
                ),
                maxlen=self.config.momentum_window,
            )
        self._momentum = new_momentum
