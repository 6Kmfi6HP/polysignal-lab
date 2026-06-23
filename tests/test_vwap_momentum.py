from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from statistics import mean

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import FreshnessState, MarketSnapshot
from polysignal_lab.strategies.config import VWAPMomentumConfig
from polysignal_lab.strategies.vwap_momentum import VWAPMomentumStrategy
from polysignal_lab.utils import stable_hash, utc_now
from factories import BookFactoryConfig, MarketFactoryConfig, sample_book, sample_market


@dataclass(frozen=True, slots=True)
class VwapScenario:
    side: Side
    prices: tuple[float, ...]
    opposing_ask: float = 0.40
    spread: float = 0.02
    seconds_to_close: int = 120
    elapsed_sec: int = 180
    staleness_ms: int = 0
    # Time gap between each price sample (seconds) — used to seed trade history
    # across different timestamps so the time-band momentum algorithm finds
    # trades at the correct band offset.
    price_interval_sec: float = 5.0


def _snapshot_for(scenario: VwapScenario, price: float, previous_snapshots: list[MarketSnapshot] | None = None) -> MarketSnapshot:
    """Build a snapshot with seeded trade history at staggered timestamps.

    Each call advances `created_at` by `price_interval_sec` so trades
    accumulate at different timestamps.  This mirrors the real system
    where snapshots arrive every few seconds, and lets the time-band
    momentum algorithm find trades at the `now - window_sec ± 1.5s`
    band.
    """
    base_time = utc_now()
    if previous_snapshots:
        # Advance by the interval from the last snapshot
        base_time = previous_snapshots[-1].created_at + timedelta(seconds=scenario.price_interval_sec)

    created_at = base_time
    market = sample_market(
        MarketFactoryConfig(
            asset="BTC",
            timeframe="5m",
            seconds_to_close=scenario.seconds_to_close,
        )
    ).model_copy(
        update={
            "start_ts": created_at - timedelta(seconds=scenario.elapsed_sec),
            "end_ts": created_at + timedelta(seconds=scenario.seconds_to_close),
        }
    )
    received_at = created_at - timedelta(milliseconds=scenario.staleness_ms)
    up_ask = price if scenario.side == Side.UP else scenario.opposing_ask
    down_ask = price if scenario.side == Side.DOWN else scenario.opposing_ask
    up_book = sample_book(
        market.token_for(Side.UP).token_id,
        BookFactoryConfig(ask=up_ask, bid=up_ask - scenario.spread, size=500),
    ).model_copy(update={"received_at": received_at})
    down_book = sample_book(
        market.token_for(Side.DOWN).token_id,
        BookFactoryConfig(ask=down_ask, bid=down_ask - scenario.spread, size=500),
    ).model_copy(update={"received_at": received_at})
    snapshot_id = stable_hash(market.market_id, scenario.side.value, str(price), str(created_at.timestamp()))
    return MarketSnapshot(
        snapshot_id=f"snap_{snapshot_id}",
        created_at=created_at,
        market=market,
        up_book=up_book,
        down_book=down_book,
        freshness=FreshnessState(
            up_book_ms=scenario.staleness_ms,
            down_book_ms=scenario.staleness_ms,
            max_ms=scenario.staleness_ms,
        ),
    )


def _evaluate_sequence(
    strategy: VWAPMomentumStrategy,
    scenario: VwapScenario,
) -> list[SignalCandidate]:
    """Feed a sequence of price snapshots through the strategy.

    Returns the FIRST non-empty signal list, or the last empty list if no signal.
    The time-band momentum algorithm looks for trades at
    `now - momentum_window_sec ± 1.5s`.
    """
    snapshots: list[MarketSnapshot] = []

    for _i, price in enumerate(scenario.prices):
        snap = _snapshot_for(scenario, price, previous_snapshots=snapshots if snapshots else None)
        snapshots.append(snap)
        signals = strategy.evaluate(snap)
        if signals:
            return signals

    return signals  # last evaluate result (empty)


def _config(momentum_window: int = 120) -> VWAPMomentumConfig:
    """Create a PRD-aligned VWAP config with time-band-compatible settings."""
    return VWAPMomentumConfig(
        min_price=0.35,
        max_price=0.85,
        momentum_window_sec=momentum_window,
        min_deviation_pct=0.015,
        max_deviation_pct=0.05,
        min_momentum=0.02,
        min_elapsed_sec=45,
        no_entry_before_end_sec=20,
        max_spread=0.03,
        max_orderbook_staleness_ms=1_000,
    )


def _fast_config() -> VWAPMomentumConfig:
    """Momentum window tuned for rapid tests with short snapshot spacing."""
    return VWAPMomentumConfig(
        min_price=0.35,
        max_price=0.85,
        momentum_window_sec=5,  # band [now-6.5, now-3.5] catches 5s-spaced prev snapshot
        min_deviation_pct=0.0,  # disable deviation filter for basic signal test
        max_deviation_pct=1.0,
        min_momentum=0.001,  # any positive momentum passes
        min_elapsed_sec=0,  # disable elapsed filter
        no_entry_before_end_sec=0,
        max_spread=0.03,
        max_orderbook_staleness_ms=60_000,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_vwap_momentum_emits_buy_up_and_down() -> None:
    """A rising price sequence triggers BUY signals for UP and DOWN sides."""
    config = _fast_config()
    prices = (0.52, 0.54, 0.56, 0.58, 0.60)
    scenario = VwapScenario(
        side=Side.UP, prices=prices,
        price_interval_sec=5.0, seconds_to_close=150, elapsed_sec=150,
    )

    strategy_up = VWAPMomentumStrategy(config)
    up_signals = _evaluate_sequence(strategy_up, scenario)
    assert len(up_signals) == 1
    assert up_signals[0].side == Side.UP
    assert "VWAP_DEVIATION_OK" in up_signals[0].reason_codes
    assert "MOMENTUM_OK" in up_signals[0].reason_codes
    assert "FAVORITE_SELECTED" in up_signals[0].reason_codes
    assert up_signals[0].metrics["favorite_side"] == "UP"

    strategy_down = VWAPMomentumStrategy(config)
    down_signals = _evaluate_sequence(strategy_down, VwapScenario(
        side=Side.DOWN, prices=prices,
        price_interval_sec=5.0, seconds_to_close=150, elapsed_sec=150,
    ))
    assert len(down_signals) == 1
    assert down_signals[0].side == Side.DOWN
    assert down_signals[0].metrics["favorite_side"] == "DOWN"


def test_vwap_momentum_rejects_low_momentum() -> None:
    """Flat price trend — no momentum — should produce no signal."""
    config = _fast_config().model_copy(update={"min_momentum": 0.10})
    strategy = VWAPMomentumStrategy(config)
    # Rising prices at 0.52 -> 0.60 (momentum ~15%, but min_momentum=10%)
    prices = (0.52, 0.54, 0.56, 0.58, 0.60)
    # With momentum_window_sec=1, the band [now-2.5, now-0.5] has a trade
    # at the previous snapshot timestamp. With 5s intervals and rising prices,
    # momentum = (current - prev_price_at_band) / prev_price_at_band should
    # be small since only 1 snapshot is 5s prior, price diff is ~0.02 / 0.54 = ~3.7%.
    # Min_momentum=10% should filter it.
    signals = _evaluate_sequence(strategy, VwapScenario(
        side=Side.UP, prices=prices,
        price_interval_sec=5.0, seconds_to_close=150, elapsed_sec=150,
    ))
    assert signals == []


def test_vwap_momentum_rejects_short_history() -> None:
    """Only 1 snapshot — momentum returns None (no trades in band)."""
    config = _fast_config()
    strategy = VWAPMomentumStrategy(config)
    signals = _evaluate_sequence(strategy, VwapScenario(
        side=Side.UP, prices=(0.70,),
        price_interval_sec=5.0, seconds_to_close=150, elapsed_sec=150,
    ))
    assert signals == []


def test_vwap_momentum_rejects_outside_price_range() -> None:
    """Price above max_price should reject."""
    config = _fast_config()
    strategy = VWAPMomentumStrategy(config)
    # First snapshot at 0.88 (above max_price=0.85) — range check fails
    prices = (0.88,)
    signals = _evaluate_sequence(strategy, VwapScenario(
        side=Side.UP, prices=prices,
        price_interval_sec=5.0, seconds_to_close=150, elapsed_sec=150,
    ))
    assert signals == []


def test_vwap_momentum_one_shot_entry_guard() -> None:
    """After entering a market, second call on same market_id returns None."""
    config = _fast_config()
    strategy = VWAPMomentumStrategy(config)
    prices = (0.52, 0.54, 0.56, 0.58, 0.60)
    scenario = VwapScenario(
        side=Side.UP, prices=prices,
        price_interval_sec=5.0, seconds_to_close=150, elapsed_sec=150,
    )

    # First call — should emit
    signals1 = _evaluate_sequence(strategy, scenario)
    assert len(signals1) == 1

    # Second call on same market_id (same strategy instance) — should be blocked
    signals2 = _evaluate_sequence(strategy, scenario)
    assert signals2 == []


def test_vwap_momentum_rejects_too_early() -> None:
    """Market too early (not enough elapsed time) should reject."""
    config = _fast_config().model_copy(update={"min_elapsed_sec": 180})
    strategy = VWAPMomentumStrategy(config)
    prices = (0.52, 0.54, 0.56, 0.58, 0.60)
    signals = _evaluate_sequence(strategy, VwapScenario(
        side=Side.UP, prices=prices,
        elapsed_sec=10,  # Below min_elapsed_sec=180
        price_interval_sec=5.0, seconds_to_close=150,
    ))
    assert signals == []


def test_vwap_momentum_rejects_too_close_to_end() -> None:
    """Market too close to end should reject."""
    config = _fast_config().model_copy(update={"no_entry_before_end_sec": 30})
    strategy = VWAPMomentumStrategy(config)
    prices = (0.52, 0.54, 0.56, 0.58, 0.60)
    signals = _evaluate_sequence(strategy, VwapScenario(
        side=Side.UP, prices=prices,
        seconds_to_close=10,  # Below no_entry_before_end_sec=30
        price_interval_sec=5.0, elapsed_sec=150,
    ))
    assert signals == []


def test_vwap_momentum_signal_carries_configured_freshness_policy(snapshot) -> None:
    config = VWAPMomentumConfig(
        max_orderbook_staleness_ms=1_000,
        max_spot_staleness_ms=2_000,
        min_deviation_pct=0.0,
        max_deviation_pct=1.0,
        min_momentum=0.0,
        min_elapsed_sec=0,
        no_entry_before_end_sec=0,
        vwap_window_sec=180,
    )
    strategy = VWAPMomentumStrategy(config)
    now = snapshot.created_at.timestamp()
    for side in (Side.UP, Side.DOWN):
        key = strategy._market_key(snapshot.market.market_id, side)
        price = snapshot.ask_for(side)
        assert price is not None
        strategy.trades.push(key, price * 0.95, 1.0, now - config.momentum_window_sec)

    signals = strategy.evaluate(snapshot)

    assert signals
    assert signals[0].freshness_policy is not None
    assert signals[0].freshness_policy.max_orderbook_staleness_ms == 1_000
    assert signals[0].freshness_policy.max_spot_staleness_ms == 2_000
