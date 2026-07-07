"""
Input: __future__, __future__.annotations, polysignal_lab.alpha.fibonacci_core, polysignal_lab.alpha.fibonacci_core.FibonacciAlphaCore, polysignal_lab.alpha.fibonacci_core.ZigZagDetector, polysignal_lab.strategies.config, polysignal_lab.strategies.config.FibonacciBotConfig, polysignal_lab.strategies.fibonacci_bot, polysignal_lab.strategies.fibonacci_bot.FibonacciStrategyBot, alpha_equivalence
Output: test_fibonacci_core_matches_legacy_candidate, test_fibonacci_core_state_roundtrip
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from polysignal_lab.alpha.fibonacci_core import FibonacciAlphaCore, ZigZagDetector
from polysignal_lab.strategies.config import FibonacciBotConfig
from polysignal_lab.strategies.fibonacci_bot import FibonacciStrategyBot
from alpha_equivalence import assert_legacy_core_equivalent
from factories import sample_snapshot


def _fib_config() -> FibonacciBotConfig:
    return FibonacciBotConfig(require_momentum_confirmation=False, zone_width_pct=0.01)


def _fib_snapshot():
    # spot_price 106.18 lands exactly on the 0.382 retracement of swing 100→110.
    return sample_snapshot(up_ask=0.50, down_ask=0.50, spot_price=106.18)


def _seed_zigzag(owner: "FibonacciAlphaCore") -> None:
    detector = ZigZagDetector(threshold_pct=owner.config.zigzag_pct)
    detector._swing_highs.append(110.0)
    detector._swing_lows.append(100.0)
    owner._zigzag["BTCUSDT"] = detector


def test_fibonacci_core_matches_legacy_candidate() -> None:
    config = _fib_config()
    snapshot = _fib_snapshot()

    strategy = FibonacciStrategyBot(config)
    core = FibonacciAlphaCore(config)
    _seed_zigzag(strategy.core)
    _seed_zigzag(core)

    assert_legacy_core_equivalent(strategy, core, snapshot)


def test_fibonacci_core_state_roundtrip() -> None:
    config = _fib_config()
    core = FibonacciAlphaCore(config)

    # Candle history
    candles = core._ensure_candles("BTCUSDT")
    candles.append(100.0)
    candles.append(105.0)
    candles.append(106.18)
    # ZigZag detector with recorded swings + live trend state
    detector = ZigZagDetector(threshold_pct=config.zigzag_pct)
    detector._swing_highs.append(110.0)
    detector._swing_lows.append(100.0)
    detector._prices.extend([99.0, 110.0, 106.18])
    detector._current_trend = "down"
    detector._extreme_price = 106.18
    core._zigzag["BTCUSDT"] = detector
    # Momentum stats
    core._momentum.push("BTCUSDT", 100.0)
    core._momentum.push("BTCUSDT", 105.0)

    payload = core.save_state()

    fresh = FibonacciAlphaCore(config)
    fresh.load_state(payload)

    # Candles round-trip as lists
    assert list(fresh._candles["BTCUSDT"]) == [100.0, 105.0, 106.18]
    # Fresh detector restored
    restored = fresh._zigzag["BTCUSDT"]
    assert list(restored._swing_highs) == [110.0]
    assert list(restored._swing_lows) == [100.0]
    assert list(restored._prices) == [99.0, 110.0, 106.18]
    assert restored._current_trend == "down"
    assert restored._extreme_price == 106.18
    # Momentum history restored
    assert fresh._momentum.stats("BTCUSDT")["count"] == 2