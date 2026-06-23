from __future__ import annotations

from datetime import timedelta

from polysignal_lab.config import Settings
from polysignal_lab.data.market_snapshot import MarketSnapshotBuilder
from polysignal_lab.data.price_to_beat_provider import PriceToBeatProvider
from polysignal_lab.data.state import OrderBookRegistry, SpotRegistry
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.snapshot import FreshnessState, MarketSnapshot
from polysignal_lab.strategies.binary_momentum import BinaryMomentumConfig, BinaryMomentumStrategy
from polysignal_lab.strategies.cross_market_bot import CrossMarketBotConfig, CrossMarketBotStrategy, RelationType
from polysignal_lab.strategies.dump_hedge import DumpHedgeConfig, DumpHedgeStrategy
from polysignal_lab.strategies.fibonacci_bot import FibonacciBotConfig, FibonacciStrategyBot, ZigZagDetector
from polysignal_lab.strategies.late_consensus import LateConsensusStrategy
from polysignal_lab.strategies.low_side_dual_reversion import LowSideDualReversionConfig, LowSideDualReversionStrategy
from polysignal_lab.strategies.mid_price_sizing import MidPriceSizingConfig, MidPriceSizingStrategy
from polysignal_lab.strategies.ninety_nine_cent_sniper import NinetyNineCentSniperStrategy
from polysignal_lab.strategies.one_cent_buy import OneCentBuyStrategy
from polysignal_lab.strategies.pre_order_market import PreOrderMarketConfig, PreOrderMarketStrategy
from polysignal_lab.strategies.ptb_diff import PTBDiffStrategy
from polysignal_lab.strategies.vwap_momentum import VWAPMomentumStrategy
from polysignal_lab.utils import utc_now
from factories import BookFactoryConfig, MarketFactoryConfig, SpotFactoryConfig, sample_book, sample_market, sample_spot


async def test_ptb_diff_generates_buy_up(snapshot, settings):
    strategy = PTBDiffStrategy(settings.strategies.ptb_diff)
    signals = strategy.evaluate(snapshot)
    assert signals
    assert signals[0].side == Side.UP
    assert "PTB_DIFF_THRESHOLD_OK" in signals[0].reason_codes
    # Default triggers now use refs-style range check (min_token_price=0.80)
    assert "PTB_PROB_RANGE_OK" in signals[0].reason_codes


async def test_ptb_diff_requires_verified_ptb(snapshot, settings):
    strategy = PTBDiffStrategy(settings.strategies.ptb_diff)
    bad = snapshot.model_copy(update={"price_to_beat": 100000.0, "metrics": {"price_to_beat_verified": False}})
    assert strategy.evaluate(bad) == []


async def test_late_consensus_generates_favorite_side(snapshot, settings):
    strategy = LateConsensusStrategy(settings.strategies.late_consensus)
    signals = strategy.evaluate(snapshot)
    assert signals
    assert signals[0].side == Side.UP
    assert signals[0].strategy == "late_consensus"


async def test_late_consensus_flip_guard_blocks_recent_flip(market, spots, settings):
    books = OrderBookRegistry()
    builder = MarketSnapshotBuilder(books, spots, PriceToBeatProvider())
    strategy = LateConsensusStrategy(settings.strategies.late_consensus)
    books.update(sample_book(market.token_for(Side.UP).token_id, BookFactoryConfig(ask=0.82, bid=0.79, size=500)))
    books.update(sample_book(market.token_for(Side.DOWN).token_id, BookFactoryConfig(ask=0.18, bid=0.15, size=500)))
    snap1 = await builder.build(market)
    first_signals = strategy.evaluate(snap1)
    assert first_signals
    strategy.notify_signal_accepted(first_signals[0])
    books.update(sample_book(market.token_for(Side.UP).token_id, BookFactoryConfig(ask=0.18, bid=0.15, size=500)))
    books.update(sample_book(market.token_for(Side.DOWN).token_id, BookFactoryConfig(ask=0.82, bid=0.79, size=500)))
    snap2 = await builder.build(market)
    assert strategy.evaluate(snap2) == []


async def test_vwap_momentum_generates_after_window(market, spots, settings):
    books = OrderBookRegistry()
    builder = MarketSnapshotBuilder(books, spots, PriceToBeatProvider())
    strategy = VWAPMomentumStrategy(settings.strategies.vwap_momentum)
    # Time-band momentum at 120s default window needs trades spread over >120s.
    # In this test we create snapshots rapidly, so use a short momentum window
    # that can find trades from the immediately preceding snapshots.
    strategy.config.momentum_window_sec = 1
    strategy.config.min_momentum = 0.001
    down = sample_book(market.token_for(Side.DOWN).token_id, BookFactoryConfig(ask=0.18, bid=0.15, size=500))
    emitted = []
    for ask in [0.52, 0.54, 0.56, 0.59, 0.63]:
        books.update(sample_book(market.token_for(Side.UP).token_id, BookFactoryConfig(ask=ask, bid=ask - 0.03, size=500)))
        books.update(down)
        snap = await builder.build(market)
        signals = strategy.evaluate(snap)
        emitted.extend(signals)
    assert emitted
    assert emitted[0].side == Side.UP
    assert "VWAP_DEVIATION_OK" in emitted[0].reason_codes


def _strategy_snapshot(
    *,
    up_ask: float = 0.50,
    up_bid: float | None = None,
    down_ask: float = 0.50,
    down_bid: float | None = None,
    size: float = 500.0,
    seconds_to_close: int = 120,
    start_offset_seconds: int = -180,
    spot_price: float = 100_120.0,
    metrics: dict | None = None,
    now=None,
) -> MarketSnapshot:
    created_at = now or utc_now()
    market = sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m", seconds_to_close=seconds_to_close, price_to_beat=100_000.0))
    market = market.model_copy(
        update={
            "start_ts": created_at + timedelta(seconds=start_offset_seconds),
            "end_ts": created_at + timedelta(seconds=seconds_to_close),
        }
    )
    return MarketSnapshot(
        snapshot_id=f"strategy-{market.market_id}-{created_at.timestamp()}",
        created_at=created_at,
        market=market,
        up_book=sample_book(market.token_for(Side.UP).token_id, BookFactoryConfig(ask=up_ask, bid=up_bid, size=size)),
        down_book=sample_book(market.token_for(Side.DOWN).token_id, BookFactoryConfig(ask=down_ask, bid=down_bid, size=size)),
        spot=sample_spot(SpotFactoryConfig(asset="BTC", price=spot_price)),
        price_to_beat=market.price_to_beat,
        freshness=FreshnessState(up_book_ms=1, down_book_ms=1, spot_ms=1, max_ms=1),
        metrics=metrics or {},
    )


def test_one_cent_buy_emits_passive_gtd_intent():
    strategy = OneCentBuyStrategy()
    snapshot = _strategy_snapshot(up_ask=0.50, down_ask=0.50)

    signals = strategy.evaluate(snapshot)

    assert signals
    assert {signal.order_intent for signal in signals} == {OrderIntent.PASSIVE_GTD}
    assert {signal.expiry_seconds for signal in signals} == {
        int(snapshot.seconds_to_close - strategy.config.cancel_before_close_seconds)
    }


def test_ninety_nine_cent_sniper_emits_fok_intent_and_reason_code():
    strategy = NinetyNineCentSniperStrategy()
    snapshot = _strategy_snapshot(
        up_ask=0.98,
        up_bid=0.97,
        down_ask=0.02,
        down_bid=0.01,
        seconds_to_close=60,
        metrics={"external_probability": 0.996},
    )

    signals = strategy.evaluate(snapshot)

    assert signals
    assert signals[0].order_intent == OrderIntent.TAKER_FOK
    assert "FOK_EXECUTION" in signals[0].reason_codes


def test_binary_momentum_emits_fak_intent():
    strategy = BinaryMomentumStrategy(
        BinaryMomentumConfig(
            macd_fast=2,
            macd_slow=3,
            macd_signal=2,
            rsi_period=2,
            rsi_upper=100,
            vwap_deviation=0.0,
        )
    )
    snapshot = _strategy_snapshot(up_ask=0.50, up_bid=0.48, down_ask=0.45, down_bid=0.43, spot_price=105.0)
    strategy._spot_prices.extend([100.0, 101.0, 102.0, 103.0])
    strategy._vwap_stats.push(f"{snapshot.market.market_id}:{Side.UP.value}", 0.40)

    signals = strategy.evaluate(snapshot)

    assert signals
    assert signals[0].order_intent == OrderIntent.TAKER_FAK


def test_fibonacci_bot_emits_passive_gtd_intent():
    strategy = FibonacciStrategyBot(FibonacciBotConfig(require_momentum_confirmation=False, zone_width_pct=0.01))
    detector = ZigZagDetector(threshold_pct=strategy.config.zigzag_pct)
    detector._swing_highs.append(110.0)
    detector._swing_lows.append(100.0)
    strategy._zigzag["BTCUSDT"] = detector
    snapshot = _strategy_snapshot(up_ask=0.50, up_bid=0.48, down_ask=0.50, down_bid=0.48, spot_price=106.18)

    signals = strategy.evaluate(snapshot)

    assert signals
    assert {signal.order_intent for signal in signals} == {OrderIntent.PASSIVE_GTD}
    assert {signal.expiry_seconds for signal in signals} == {300}


def test_dump_hedge_emits_leg_and_hedge_intents():
    strategy = DumpHedgeStrategy(DumpHedgeConfig())
    strategy.evaluate(_strategy_snapshot(up_ask=0.60, up_bid=0.58, down_ask=0.50, down_bid=0.48, start_offset_seconds=-60))
    snapshot = _strategy_snapshot(up_ask=0.40, up_bid=0.38, down_ask=0.50, down_bid=0.48, start_offset_seconds=-60)

    leg_signals = strategy.evaluate(snapshot)

    assert leg_signals
    assert leg_signals[0].order_intent == OrderIntent.TAKER_FAK
    assert leg_signals[0].pair_id == f"{snapshot.market.market_id}:dump"
    assert leg_signals[0].hedge_leg is False

    hedge_strategy = DumpHedgeStrategy(DumpHedgeConfig())
    hedge_strategy.notify_fill(snapshot.market.market_id, Side.UP, 0.40, 10.0)
    hedge_signals = hedge_strategy.evaluate(snapshot)

    assert hedge_signals
    assert hedge_signals[0].order_intent == OrderIntent.TAKER_FOK
    assert hedge_signals[0].pair_id == f"{snapshot.market.market_id}:dump"
    assert hedge_signals[0].hedge_leg is True

    stop_strategy = DumpHedgeStrategy(DumpHedgeConfig(pair_cost_cap=0.10, stop_loss_max_wait_seconds=0.0))
    stop_strategy.notify_fill(snapshot.market.market_id, Side.UP, 0.40, 10.0)
    stop_signals = stop_strategy.evaluate(snapshot)

    assert stop_signals
    assert stop_signals[0].order_intent == OrderIntent.TAKER_FOK
    assert stop_signals[0].hedge_leg is True


def test_low_side_dual_reversion_emits_initial_and_hedge_intents():
    strategy = LowSideDualReversionStrategy(LowSideDualReversionConfig())
    snapshot = _strategy_snapshot(up_ask=0.50, up_bid=0.48, down_ask=0.50, down_bid=0.48)

    initial_signals = strategy.evaluate(snapshot)

    assert initial_signals
    assert {signal.order_intent for signal in initial_signals} == {OrderIntent.PASSIVE_GTD}
    assert {signal.pair_id for signal in initial_signals} == {f"{snapshot.market.market_id}:dual"}
    assert {signal.expiry_seconds for signal in initial_signals} == {min(snapshot.seconds_to_close - 60, 300)}
    near_close_snapshot = _strategy_snapshot(
        up_ask=0.50,
        up_bid=0.48,
        down_ask=0.50,
        down_bid=0.48,
        seconds_to_close=50,
    )
    assert LowSideDualReversionStrategy(LowSideDualReversionConfig()).evaluate(near_close_snapshot) == []

    hedge_strategy = LowSideDualReversionStrategy(LowSideDualReversionConfig())
    hedge_strategy.notify_fill(snapshot.market.market_id, Side.UP, 0.35, 5.0)
    hedge_signals = hedge_strategy.evaluate(snapshot)

    assert hedge_signals
    assert hedge_signals[0].order_intent == OrderIntent.TAKER_FAK
    assert hedge_signals[0].pair_id == f"{snapshot.market.market_id}:dual"
    assert hedge_signals[0].hedge_leg is True

    stop_strategy = LowSideDualReversionStrategy(LowSideDualReversionConfig(pair_cost_cap=0.10, max_unhedged_seconds=0.0))
    stop_strategy.notify_fill(snapshot.market.market_id, Side.UP, 0.35, 5.0)
    stop_signals = stop_strategy.evaluate(snapshot)

    assert stop_signals
    assert stop_signals[0].order_intent == OrderIntent.TAKER_FAK
    assert stop_signals[0].hedge_leg is True


def test_pre_order_market_emits_initial_and_reconcile_intents():
    fixed_now = utc_now()
    strategy = PreOrderMarketStrategy(PreOrderMarketConfig())
    strategy._utc_now = lambda: fixed_now
    snapshot = _strategy_snapshot(
        up_ask=0.50,
        up_bid=0.48,
        down_ask=0.50,
        down_bid=0.48,
        seconds_to_close=300,
        start_offset_seconds=120,
        now=fixed_now,
    )

    initial_signals = strategy.evaluate(snapshot)

    assert initial_signals
    assert {signal.order_intent for signal in initial_signals} == {OrderIntent.PASSIVE_GTD}
    assert {signal.pair_id for signal in initial_signals} == {f"{snapshot.market.market_id}:pre"}
    assert {signal.expiry_seconds for signal in initial_signals} == {150}

    reconcile_strategy = PreOrderMarketStrategy(PreOrderMarketConfig())
    reconcile_strategy.notify_fill(snapshot.market.market_id, Side.UP, 0.45, 5.0)
    reconcile_signals = reconcile_strategy.evaluate(snapshot)

    assert reconcile_signals
    assert reconcile_signals[0].order_intent == OrderIntent.TAKER_FAK
    assert reconcile_signals[0].pair_id == f"{snapshot.market.market_id}:pre"
    assert reconcile_signals[0].hedge_leg is True

    same_side_strategy = PreOrderMarketStrategy(PreOrderMarketConfig())
    same_side_strategy.notify_fill(snapshot.market.market_id, Side.UP, 0.45, 5.0)
    same_side_strategy.notify_fill(snapshot.market.market_id, Side.UP, 0.40, 5.0)
    assert same_side_strategy._positions[snapshot.market.market_id]["hedged"] is False


def test_mid_price_sizing_emits_fak_intent_and_tracks_fills():
    strategy = MidPriceSizingStrategy(MidPriceSizingConfig())
    snapshot = _strategy_snapshot(up_ask=0.46, up_bid=0.43, down_ask=0.44, down_bid=0.41)

    signals = strategy.evaluate(snapshot)

    assert signals
    assert {signal.order_intent for signal in signals} == {OrderIntent.TAKER_FAK}

    strategy.notify_fill(snapshot.market.market_id, Side.UP, 0.46, 5.0)
    key = strategy._pos_key(snapshot.market.market_id, Side.UP)
    assert strategy._layer_count[key] == 1
    assert strategy._entry_prices[key] == [0.46]


def test_cross_market_bot_emits_fok_intent_and_tracks_leg_failure():
    strategy = CrossMarketBotStrategy(CrossMarketBotConfig())
    snapshot = _strategy_snapshot(up_ask=0.40, up_bid=0.38, down_ask=0.60, down_bid=0.58)
    relation_id = "basket-1"
    strategy.register_relation(
        relation_id,
        RelationType.EXHAUSTIVE_MUTUALLY_EXCLUSIVE,
        [snapshot.market.condition_id, "condition-other"],
        [Side.UP, Side.UP],
    )

    signals = strategy.evaluate(snapshot)

    assert signals
    assert signals[0].order_intent == OrderIntent.TAKER_FOK
    assert signals[0].pair_id == relation_id

    strategy.notify_fill(snapshot.market.market_id, Side.UP, 0.40, 5.0)
    assert strategy._active_baskets[relation_id]["fills"][snapshot.market.market_id]["side"] == Side.UP
    strategy.notify_leg_failure(relation_id, snapshot.market.market_id, Side.UP)
    assert strategy._active_baskets[relation_id]["failed"] is True
