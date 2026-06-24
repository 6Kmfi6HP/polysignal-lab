from __future__ import annotations

from datetime import timedelta

from polysignal_lab.config import (
    FillModelConfig,
    PaperTradingConfig,
    PolymarketDataConfig,
    load_settings,
)
from polysignal_lab.data.price_to_beat_provider import PriceToBeatProvider
from polysignal_lab.data.polymarket_clob_ws import PolymarketMarketWebSocket
from polysignal_lab.data.market_snapshot import MarketSnapshotBuilder
from polysignal_lab.data.state import OrderBookRegistry, SpotRegistry
from polysignal_lab.domain.enums import ExitMode, OrderIntent, OrderStatus, Side
from polysignal_lab.domain.paper_order import PaperFill, PaperOrder
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.paper.exit_engine import PaperExitEngine
from polysignal_lab.signal_layer.deduper import SignalDeduper
from polysignal_lab.paper.simulator import PaperSimulator
from polysignal_lab.paper.wallet import PaperWallet
from polysignal_lab.strategies.config import LateConsensusConfig, PTBDiffConfig, VWAPMomentumConfig
from polysignal_lab.strategies.late_consensus import LateConsensusStrategy
from polysignal_lab.strategies.ptb_diff import PTBDiffStrategy
from polysignal_lab.strategies.vwap_momentum import VWAPMomentumStrategy
from polysignal_lab.utils import utc_now
from factories import BookFactoryConfig, MarketFactoryConfig, sample_book, sample_market, sample_spot


def _snapshot(*, seconds_to_close: int, up_ask: float, down_ask: float, up_last: float | None = None, down_last: float | None = None, spot_price: float = 100_120.0, ptb: float = 100_000.0) -> MarketSnapshot:
    market = sample_market(MarketFactoryConfig(seconds_to_close=seconds_to_close, price_to_beat=ptb))
    up_token = market.token_for(Side.UP).token_id
    down_token = market.token_for(Side.DOWN).token_id
    up_book = sample_book(up_token, BookFactoryConfig(ask=up_ask, bid=max(0.01, up_ask - 0.01)))
    down_book = sample_book(down_token, BookFactoryConfig(ask=down_ask, bid=max(0.01, down_ask - 0.01)))
    if up_last is not None:
        up_book = up_book.model_copy(update={"last_trade_price": up_last})
    if down_last is not None:
        down_book = down_book.model_copy(update={"last_trade_price": down_last})
    return MarketSnapshot(
        snapshot_id="reference-parity",
        market=market,
        up_book=up_book,
        down_book=down_book,
        spot=sample_spot().model_copy(update={"price": spot_price}),
        price_to_beat=ptb,
        metrics={"price_to_beat_verified": True},
    )


def test_vwap_momentum_prefers_reference_last_trade_price_over_best_ask() -> None:
    config = VWAPMomentumConfig(
        assets=["BTC"],
        timeframes=["5m"],
        min_price=0.50,
        max_price=0.95,
        vwap_window_sec=120,
        momentum_window_sec=60,
        min_deviation_pct=-1.0,
        max_deviation_pct=1.0,
        min_momentum=0.01,
        min_elapsed_sec=0,
        no_entry_before_end_sec=0,
    )
    strategy = VWAPMomentumStrategy(config)
    snapshot = _snapshot(
        seconds_to_close=120,
        up_ask=0.82,
        down_ask=0.88,
        up_last=0.80,
        down_last=0.78,
    )
    now = snapshot.created_at.timestamp()
    market_id = snapshot.market.market_id
    strategy.trades.push(f"{market_id}:UP", 0.70, 4.0, now - 60.0)
    strategy.trades.push(f"{market_id}:DOWN", 0.70, 4.0, now - 60.0)

    signals = strategy.evaluate(snapshot)

    assert [signal.side for signal in signals] == [Side.UP]
    assert signals[0].metrics["fav_price"] == 0.80


def test_late_consensus_paper_uses_reference_contract_sizing() -> None:
    strategy = LateConsensusStrategy(LateConsensusConfig(entry_frequency_sec=0))
    snapshot = _snapshot(seconds_to_close=100, up_ask=0.82, down_ask=0.18)
    signal = strategy.evaluate(snapshot)[0]
    assert signal.metrics["contracts"] == 8

    paper_config = PaperTradingConfig(
        fixed_stake_usdc=10.0,
        fill_model=FillModelConfig(slippage_bps=0.0, require_depth_check=False),
    )
    wallet = PaperWallet(starting_balance=1000.0)
    simulator = PaperSimulator(paper_config, PolymarketDataConfig(max_book_staleness_ms=60_000), wallet)

    result = simulator.process_signal(signal, snapshot.book_for(signal.side))

    assert result.position is not None
    assert result.position.shares == 8
    assert result.position.stake_usdc == 8 * 0.82


def test_late_contract_sizing_revalidates_depth_with_contract_stake() -> None:
    strategy = LateConsensusStrategy(LateConsensusConfig(entry_frequency_sec=0))
    snapshot = _snapshot(seconds_to_close=100, up_ask=0.82, down_ask=0.18)
    signal = strategy.evaluate(snapshot)[0]
    shallow_but_sufficient_book = sample_book(
        signal.token_id,
        BookFactoryConfig(ask=0.82, bid=0.81, size=8.6),
    )
    shallow_but_sufficient_book = shallow_but_sufficient_book.model_copy(
        update={"asks": [shallow_but_sufficient_book.asks[0]]}
    )
    paper_config = PaperTradingConfig(
        fixed_stake_usdc=10.0,
        fill_model=FillModelConfig(slippage_bps=0.0, require_depth_check=True),
    )
    simulator = PaperSimulator(
        paper_config,
        PolymarketDataConfig(max_book_staleness_ms=60_000),
        PaperWallet(starting_balance=1000.0),
    )

    result = simulator.process_signal(signal, shallow_but_sufficient_book)

    assert result.position is not None
    assert result.position.shares == 8



def test_late_contract_sizing_preserves_contract_count_with_slippage() -> None:
    strategy = LateConsensusStrategy(LateConsensusConfig(entry_frequency_sec=0))
    snapshot = _snapshot(seconds_to_close=100, up_ask=0.82, down_ask=0.18)
    signal = strategy.evaluate(snapshot)[0]
    simulator = PaperSimulator(
        PaperTradingConfig(
            fixed_stake_usdc=10.0,
            fill_model=FillModelConfig(slippage_bps=25.0, require_depth_check=False),
        ),
        PolymarketDataConfig(max_book_staleness_ms=60_000),
        PaperWallet(starting_balance=1000.0),
    )

    result = simulator.process_signal(signal, snapshot.book_for(signal.side))

    assert result.position is not None
    assert result.position.shares == 8
    assert result.position.stake_usdc == result.position.entry_price * 8

def test_runtime_ptb_config_matches_reference_c1_rule() -> None:
    settings = load_settings("config/signal_bot.yaml")
    strategy = PTBDiffStrategy(settings.strategies.ptb_diff)
    snapshot = _snapshot(seconds_to_close=100, up_ask=0.85, down_ask=0.15, spot_price=100_040.0, ptb=100_000.0)
    assert snapshot.spot is not None
    snapshot.spot = snapshot.spot.model_copy(update={"source": "polymarket_rtds"})
    snapshot.metrics["spot_source"] = "polymarket_rtds"

    signals = strategy.evaluate(snapshot)

    assert [signal.side for signal in signals] == [Side.UP]
    assert signals[0].metrics["trigger"] == "r1_up"


def test_ptb_crypto_price_variant_matches_reference_for_5m() -> None:
    assert PriceToBeatProvider()._variant_for("5m") == "fifteen"


def test_paper_exit_engine_uses_ptb_reference_probability_targets() -> None:
    wallet = PaperWallet(starting_balance=1000.0)
    position = PaperPosition(
        signal_id="sig-ptb",
        paper_order_id="order-ptb",
        paper_fill_id="fill-ptb",
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="btc-5m-test",
        market_slug="btc-updown-5m-test",
        token_id="btc-5m-test-UP",
        side=Side.UP,
        entry_price=0.80,
        shares=10.0,
        stake_usdc=8.0,
        opened_at=utc_now() - timedelta(seconds=30),
        signal_metrics={"tp_sl_stop_prob": 0.68, "tp_sl_tp_prob": 0.88},
    )
    wallet.apply_fill(position)
    engine = PaperExitEngine(PaperTradingConfig().exit_model, wallet)

    result = engine.evaluate(position, sample_book(position.token_id, BookFactoryConfig(ask=0.90, bid=0.88)))

    assert result is not None
    assert result.exit_mode == ExitMode.TAKE_PROFIT
    assert result.details["exit_threshold_source"] == "signal_metrics"


def test_signal_specific_exit_metrics_bypass_global_take_profit() -> None:
    wallet = PaperWallet(starting_balance=1000.0)
    position = PaperPosition(
        signal_id="sig-late",
        paper_order_id="order-late",
        paper_fill_id="fill-late",
        strategy="late_consensus",
        asset="BTC",
        timeframe="5m",
        market_id="btc-5m-test",
        market_slug="btc-updown-5m-test",
        token_id="btc-5m-test-UP",
        side=Side.UP,
        entry_price=0.82,
        shares=8.0,
        stake_usdc=6.56,
        opened_at=utc_now() - timedelta(seconds=30),
        signal_metrics={"flip_stop_enabled": True, "flip_stop_price": 0.48},
    )
    wallet.apply_fill(position)
    engine = PaperExitEngine(PaperTradingConfig().exit_model, wallet)

    result = engine.evaluate(position, sample_book(position.token_id, BookFactoryConfig(ask=0.92, bid=0.91)))

    assert result is None


def test_clob_last_trade_size_reaches_vwap_weighted_history() -> None:
    registry = OrderBookRegistry()
    ws = PolymarketMarketWebSocket(PolymarketDataConfig(), registry)
    ws.handle_message(
        {
            "event_type": "book",
            "market": "m",
            "asset_id": "token-up",
            "bids": [{"price": "0.70", "size": "100"}],
            "asks": [{"price": "0.72", "size": "100"}],
        }
    )

    ws.handle_message(
        {
            "event_type": "last_trade_price",
            "asset_id": "token-up",
            "price": "0.80",
            "size": "25",
            "side": "BUY",
        }
    )

    book = registry.get("token-up")
    assert book is not None
    assert book.last_trade_price == 0.80
    assert book.last_trade_size == 25.0


def test_passive_gtd_buy_fills_when_best_ask_reaches_limit() -> None:
    signal = SignalCandidate.build(
        strategy="vwap_momentum",
        asset="BTC",
        timeframe="5m",
        market_id="m",
        market_slug="btc-updown-5m-test",
        condition_id="c",
        token_id="token-down",
        side=Side.DOWN,
        confidence=0.7,
        entry_reference_price=0.02,
        max_entry_price=0.02,
        seconds_to_close=100,
        data_freshness_ms=0,
        reason_codes=["VWAP_GTD_HEDGE"],
        metrics={"contracts": 10},
        order_intent=OrderIntent.PASSIVE_GTD,
        expiry_seconds=3600,
        pair_id="m:vwap",
        hedge_leg=True,
    )
    wallet = PaperWallet(starting_balance=1000.0)
    simulator = PaperSimulator(
        PaperTradingConfig(),
        PolymarketDataConfig(max_book_staleness_ms=60_000),
        wallet,
    )
    resting = simulator.process_signal(signal, sample_book("token-down", BookFactoryConfig(ask=0.20, bid=0.18)))
    assert resting.order.status == OrderStatus.RESTING

    result = simulator.passive.tick(
        {"token-down": sample_book("token-down", BookFactoryConfig(ask=0.02, bid=0.01, size=20))},
        wallet,
    )[0]

    assert result.status == OrderStatus.FILLED
    assert result.positions[0].shares == 10
    assert result.positions[0].stake_usdc == 0.20


def test_vwap_fill_schedules_opposite_token_gtd_hedge() -> None:
    strategy = VWAPMomentumStrategy(
        VWAPMomentumConfig(
            assets=["BTC"],
            timeframes=["5m"],
            hedge_enabled=True,
            hedge_price=0.02,
            hedge_expiry_seconds=3600,
        )
    )
    snapshot = _snapshot(seconds_to_close=100, up_ask=0.80, down_ask=0.20)

    strategy.notify_fill(snapshot.market.market_id, Side.UP, fill_price=0.80, shares=10)
    signals = strategy.evaluate(snapshot)

    assert len(signals) == 1
    hedge = signals[0]
    assert hedge.side == Side.DOWN
    assert hedge.order_intent == OrderIntent.PASSIVE_GTD
    assert hedge.hedge_leg is True
    assert hedge.max_entry_price == 0.02
    assert hedge.entry_reference_price == 0.02
    assert hedge.metrics["contracts"] == 10


def test_vwap_filled_gtd_hedge_does_not_schedule_reverse_hedge() -> None:
    strategy = VWAPMomentumStrategy(
        VWAPMomentumConfig(
            assets=["BTC"],
            timeframes=["5m"],
            hedge_enabled=True,
            hedge_price=0.02,
            hedge_expiry_seconds=3600,
        )
    )
    snapshot = _snapshot(seconds_to_close=100, up_ask=0.80, down_ask=0.20)
    strategy.notify_fill(snapshot.market.market_id, Side.UP, fill_price=0.80, shares=10)
    hedge = strategy.evaluate(snapshot)[0]
    order = PaperOrder(
        signal_id=hedge.signal_id,
        asset=hedge.asset,
        timeframe=hedge.timeframe,
        strategy=hedge.strategy,
        market_id=hedge.market_id,
        market_slug=hedge.market_slug,
        token_id=hedge.token_id,
        side=hedge.side,
        order_intent=hedge.order_intent.value if hedge.order_intent else None,
        limit_price=hedge.max_entry_price,
        reference_price=hedge.entry_reference_price,
        stake_usdc=0.20,
        metrics={"signal_metrics": hedge.metrics},
    )
    fill = PaperFill(
        paper_order_id=order.paper_order_id,
        signal_id=order.signal_id,
        token_id=order.token_id,
        side=order.side,
        raw_best_ask=0.02,
        slippage_bps=0.0,
        fill_price=0.02,
        stake_usdc=0.20,
        shares=10.0,
        depth_checked=False,
    )

    strategy.notify_fill(order.market_id, order.side, fill.fill_price, fill.shares)
    assert strategy.follow_up_signals(order, fill) == []
    assert strategy._pending_hedges == {}


def test_late_repeat_after_entry_frequency_uses_new_dedupe_key() -> None:
    strategy = LateConsensusStrategy(LateConsensusConfig(entry_frequency_sec=7))
    snapshot = _snapshot(seconds_to_close=100, up_ask=0.82, down_ask=0.18)
    deduper = SignalDeduper(ttl_sec=300)
    first = strategy.evaluate(snapshot)[0]
    assert deduper.is_duplicate(first) is False
    strategy.notify_signal_accepted(first)
    strategy._last_entry_at[first.market_id] = utc_now() - timedelta(seconds=8)

    second = strategy.evaluate(snapshot)[0]

    assert second.dedupe_key != first.dedupe_key
    assert deduper.is_duplicate(second) is False


def test_ptb_diff_requires_chainlink_rtds_spot_source() -> None:
    strategy = PTBDiffStrategy(PTBDiffConfig())
    snapshot = _snapshot(seconds_to_close=100, up_ask=0.85, down_ask=0.15, spot_price=100_040.0)
    assert snapshot.spot is not None

    assert strategy.evaluate(snapshot) == []


def test_ptb_diff_persists_chainlink_and_ptb_source_metrics() -> None:
    strategy = PTBDiffStrategy(PTBDiffConfig())
    snapshot = _snapshot(seconds_to_close=100, up_ask=0.85, down_ask=0.15, spot_price=100_040.0)
    assert snapshot.spot is not None
    snapshot.spot = snapshot.spot.model_copy(update={"source": "polymarket_rtds"})
    snapshot.metrics.update(
        {
            "price_to_beat_source": "crypto_price_api",
            "price_to_beat_verified": True,
            "spot_source": "polymarket_rtds",
        }
    )

    signal = strategy.evaluate(snapshot)[0]

    assert signal.metrics["spot_source"] == "polymarket_rtds"
    assert signal.metrics["price_to_beat_source"] == "crypto_price_api"


def test_rtds_chainlink_message_updates_spot_registry() -> None:
    from polysignal_lab.data.polymarket_rtds_ws import PolymarketRtdsPriceFeed

    registry = SpotRegistry()
    feed = PolymarketRtdsPriceFeed(registry)
    feed.handle_message(
        {
            "topic": "crypto_prices",
            "payload": {
                "symbol": "btc/usd",
                "data": [{"value": 100_123.45}],
            },
        }
    )

    spot = registry.get("BTC")
    assert spot is not None
    assert spot.price == 100_123.45
    assert spot.source == "polymarket_rtds"


def test_rtds_subscription_uses_unfiltered_chainlink_updates() -> None:
    from polysignal_lab.data.polymarket_rtds_ws import PolymarketRtdsPriceFeed

    feed = PolymarketRtdsPriceFeed(SpotRegistry(), PolymarketDataConfig(rtds_assets=("BTC", "ETH")))

    assert feed._subscribe_message() == {
        "action": "subscribe",
        "subscriptions": [
            {
                "topic": "crypto_prices_chainlink",
                "type": "*",
                "filters": "",
            }
        ],
    }

    feed.handle_message(
        {
            "topic": "crypto_prices_chainlink",
            "type": "update",
            "payload": {
                "symbol": "btc/usd",
                "value": 100_456.78,
                "timestamp": 1_782_309_401_000,
            },
        }
    )

    assert feed.registry.get("BTC") is not None


async def test_vwap_strategy_ingests_all_recent_trade_events_from_snapshot_builder() -> None:
    market = sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m", seconds_to_close=120))
    up_token = market.token_for(Side.UP).token_id
    down_token = market.token_for(Side.DOWN).token_id
    books = OrderBookRegistry()
    books.update(sample_book(up_token, BookFactoryConfig(ask=0.90, bid=0.89, size=500.0)))
    books.update(sample_book(down_token, BookFactoryConfig(ask=0.40, bid=0.39, size=500.0)))
    spots = SpotRegistry()
    spots.update(sample_spot().model_copy(update={"source": "polymarket_rtds"}))
    event_ts = str(int(utc_now().timestamp()))
    ws = PolymarketMarketWebSocket(PolymarketDataConfig(), books)
    ws.handle_message(
        {"event_type": "last_trade_price", "asset_id": up_token, "price": "0.80", "size": "2", "timestamp": event_ts}
    )
    ws.handle_message(
        {"event_type": "last_trade_price", "asset_id": up_token, "price": "0.90", "size": "8", "timestamp": event_ts}
    )
    builder = MarketSnapshotBuilder(books, spots, PriceToBeatProvider())
    snapshot = await builder.build(market)
    strategy = VWAPMomentumStrategy(
        VWAPMomentumConfig(
            assets=["BTC"],
            timeframes=["5m"],
            min_price=0.50,
            max_price=0.95,
            vwap_window_sec=120,
            momentum_window_sec=60,
            min_deviation_pct=-1.0,
            max_deviation_pct=1.0,
            min_momentum=0.01,
            min_elapsed_sec=0,
            no_entry_before_end_sec=0,
        )
    )
    now_ts = snapshot.created_at.timestamp()
    strategy.trades.push(f"{market.market_id}:UP", 0.70, 4.0, now_ts - 60.0)
    strategy.trades.push(f"{market.market_id}:DOWN", 0.50, 4.0, now_ts - 60.0)

    signal = strategy.evaluate(snapshot)[0]

    assert signal.side == Side.UP
    assert signal.metrics["fav_price"] == 0.90
    assert round(signal.metrics["vwap"], 6) == round((0.70 * 4.0 + 0.80 * 2.0 + 0.90 * 8.0) / 14.0, 6)
