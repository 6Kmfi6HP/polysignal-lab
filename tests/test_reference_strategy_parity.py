from __future__ import annotations

from datetime import timedelta

from polysignal_lab.config import (
    FillModelConfig,
    PaperTradingConfig,
    PolymarketDataConfig,
    load_settings,
)
from polysignal_lab.data.price_to_beat_provider import PriceToBeatProvider
from polysignal_lab.domain.enums import ExitMode, Side
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.paper.exit_engine import PaperExitEngine
from polysignal_lab.paper.simulator import PaperSimulator
from polysignal_lab.paper.wallet import PaperWallet
from polysignal_lab.strategies.config import LateConsensusConfig, VWAPMomentumConfig
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
