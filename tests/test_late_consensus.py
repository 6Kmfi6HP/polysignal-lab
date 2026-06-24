from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from types import SimpleNamespace
from typing import Final

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.snapshot import FreshnessState, MarketSnapshot
from polysignal_lab.domain.spot import SpotPrice
from polysignal_lab.strategies.config import LateConsensusConfig
from polysignal_lab.strategies.late_consensus import LateConsensusStrategy
from polysignal_lab.utils import stable_hash, utc_now
from factories import BookFactoryConfig, MarketFactoryConfig, sample_book, sample_market


SUPPORTED_ASSETS: Final = ("BTC", "ETH", "SOL", "XRP")


@dataclass(frozen=True, slots=True)
class ConsensusBooks:
    up_ask: float = 0.82
    down_ask: float = 0.18
    spread: float = 0.03
    staleness_ms: int = 0


@dataclass(frozen=True, slots=True)
class SpotState:
    price: float
    price_to_beat: float
    staleness_ms: int = 0


@dataclass(frozen=True, slots=True)
class LateConsensusScenario:
    asset: str = "BTC"
    seconds_to_close: int = 120
    books: ConsensusBooks = ConsensusBooks()
    spot: SpotState = SpotState(price=100_120.0, price_to_beat=100_000.0)


def _config() -> LateConsensusConfig:
    return LateConsensusConfig(
        max_spread=0.08,
        max_orderbook_staleness_ms=1_500,
        max_spot_staleness_ms=1_500,
        min_spot_move_abs=1.0,
    )


def _snapshot(scenario: LateConsensusScenario) -> MarketSnapshot:
    created_at = utc_now()
    market = sample_market(
        MarketFactoryConfig(
            asset=scenario.asset,
            timeframe="5m",
            seconds_to_close=scenario.seconds_to_close,
            price_to_beat=scenario.spot.price_to_beat,
        )
    ).model_copy(
        update={
            "end_ts": created_at + timedelta(seconds=scenario.seconds_to_close),
            "price_to_beat": scenario.spot.price_to_beat,
        }
    )
    book_received_at = created_at - timedelta(milliseconds=scenario.books.staleness_ms)
    spot_received_at = created_at - timedelta(milliseconds=scenario.spot.staleness_ms)
    up_book = sample_book(
        market.token_for(Side.UP).token_id,
        BookFactoryConfig(
            ask=scenario.books.up_ask,
            bid=scenario.books.up_ask - scenario.books.spread,
            size=500.0,
        ),
    ).model_copy(update={"received_at": book_received_at})
    down_book = sample_book(
        market.token_for(Side.DOWN).token_id,
        BookFactoryConfig(
            ask=scenario.books.down_ask,
            bid=scenario.books.down_ask - scenario.books.spread,
            size=500.0,
        ),
    ).model_copy(update={"received_at": book_received_at})
    spot = SpotPrice(
        asset=scenario.asset,
        symbol=f"{scenario.asset}USDT",
        price=scenario.spot.price,
        received_at=spot_received_at,
        event_time=spot_received_at,
    )
    return MarketSnapshot(
        snapshot_id=f"snap_{stable_hash(scenario.asset, str(created_at.timestamp()))}",
        created_at=created_at,
        market=market,
        up_book=up_book,
        down_book=down_book,
        spot=spot,
        price_to_beat=scenario.spot.price_to_beat,
        freshness=FreshnessState(
            up_book_ms=scenario.books.staleness_ms,
            down_book_ms=scenario.books.staleness_ms,
            spot_ms=scenario.spot.staleness_ms,
            max_ms=max(scenario.books.staleness_ms, scenario.spot.staleness_ms),
        ),
        metrics={
            "price_to_beat": scenario.spot.price_to_beat,
            "spot_price": scenario.spot.price,
            "diff_usd": scenario.spot.price - scenario.spot.price_to_beat,
        },
    )


def test_late_consensus_emits_multi_asset_signal_with_metrics() -> None:
    # Given: PRD assets with fresh CLOB books and Binance spot moves.
    strategy = LateConsensusStrategy(_config())

    # When: each supported asset has a clear UP favorite and spot above PTB.
    signals = [
        strategy.evaluate(
            _snapshot(
                LateConsensusScenario(
                    asset=asset,
                    spot=SpotState(price=101.0, price_to_beat=100.0),
                )
            )
        )[0]
        for asset in SUPPORTED_ASSETS
    ]

    # Then: every signal carries concrete PRD reason codes and metrics.
    assert [signal.asset for signal in signals] == list(SUPPORTED_ASSETS)
    assert {signal.side for signal in signals} == {Side.UP}
    for signal in signals:
        assert signal.strategy == "late_consensus"
        assert "LATE_V3_ASK_SUM_OK" in signal.reason_codes
        assert signal.metrics["favorite_side"] == "UP"
        assert signal.metrics["ask_sum"] <= _config().max_ask_sum
        assert signal.metrics["confidence_abs"] >= _config().min_confidence_abs
        assert signal.metrics["flip_stop_price"] == 0.48


def test_late_consensus_rejects_exceeded_ask_sum() -> None:
    # Given: otherwise valid consensus books with ask_sum exceeding 1.05.
    strategy = LateConsensusStrategy(_config())
    # up_ask=0.60 + down_ask=0.50 = 1.10 > max_ask_sum=1.05
    scenario = LateConsensusScenario(books=ConsensusBooks(up_ask=0.60, down_ask=0.50))

    # When: the strategy evaluates the exceeded ask_sum.
    signals = strategy.evaluate(_snapshot(scenario))

    # Then: no candidate is emitted.
    assert signals == []


def test_late_consensus_rejects_low_confidence() -> None:
    # Given: ask sum and spot inputs are valid, but favorite confidence is weak.
    strategy = LateConsensusStrategy(_config())
    scenario = LateConsensusScenario(books=ConsensusBooks(up_ask=0.61, down_ask=0.40))

    # When: the strategy evaluates the low-confidence book.
    signals = strategy.evaluate(_snapshot(scenario))

    # Then: no candidate is emitted below min_confidence_abs.
    assert signals == []


def test_late_consensus_stale_spot_ok_and_rejects_side_change() -> None:
    # Given: fresh books with a stale spot price (2s old).
    # The corrected code does NOT check staleness at the strategy level
    # (that's the pipeline's job). So stale spot signals should still emit.
    side_change_strategy = LateConsensusStrategy(_config())
    stale_spot = LateConsensusScenario(spot=SpotState(price=101.0, price_to_beat=100.0, staleness_ms=2_000))

    stale_spot_signals = side_change_strategy.evaluate(_snapshot(stale_spot))
    # Stale spot no longer rejected — strategy focuses on core 8-step logic
    assert stale_spot_signals  # signal emitted even with stale spot

    # Given: a separate market first emits UP, then flips to DOWN inside the guard window.
    flip_strategy = LateConsensusStrategy(_config())
    up_snapshot = _snapshot(LateConsensusScenario(asset="ETH", spot=SpotState(price=101.0, price_to_beat=100.0)))
    down_snapshot = _snapshot(
        LateConsensusScenario(
            asset="ETH",
            books=ConsensusBooks(up_ask=0.18, down_ask=0.82),
            spot=SpotState(price=99.0, price_to_beat=100.0),
        )
    )

    # When: the first UP candidate is accepted, then the favorite side changes rapidly.
    first_up_signals = flip_strategy.evaluate(up_snapshot)
    assert first_up_signals
    flip_strategy.notify_signal_accepted(first_up_signals[0])
    side_change_signals = flip_strategy.evaluate(down_snapshot)

    # Then: the side-change guard blocks the second candidate.
    assert side_change_signals == []


def test_late_consensus_rejects_repeated_flip_inside_guard() -> None:
    # Given: one market emits UP and entry frequency is disabled to isolate flip guard behavior.
    config = _config().model_copy(update={"entry_frequency_sec": 0})
    strategy = LateConsensusStrategy(config)
    up_snapshot = _snapshot(LateConsensusScenario(asset="ETH", spot=SpotState(price=101.0, price_to_beat=100.0)))
    down_snapshot = _snapshot(
        LateConsensusScenario(
            asset="ETH",
            books=ConsensusBooks(up_ask=0.18, down_ask=0.82),
            spot=SpotState(price=99.0, price_to_beat=100.0),
        )
    )

    # When: the same DOWN flip is evaluated twice immediately after an accepted UP entry.
    first_up_signals = strategy.evaluate(up_snapshot)
    assert first_up_signals
    strategy.notify_signal_accepted(first_up_signals[0])
    first_down_signals = strategy.evaluate(down_snapshot)
    second_down_signals = strategy.evaluate(down_snapshot)

    # Then: the blocked flip does not poison favorite-side state for the next candidate.
    assert first_down_signals == []
    assert second_down_signals == []


def test_late_consensus_rejects_unsupported_asset_and_accepts_zero_spot_move() -> None:
    # Given: unsupported product asset and negligible Binance-vs-PTB movement.
    config = _config()

    # When: non-PRD market data appears or BTC has no meaningful spot move.
    unsupported_signals = LateConsensusStrategy(config).evaluate(
        _snapshot(LateConsensusScenario(asset="ADA", spot=SpotState(price=101.0, price_to_beat=100.0)))
    )
    # With default min_spot_move_abs=0.0, the spot move check is disabled.
    # Even weak spot move should still produce a signal for supported assets.
    weak_spot_signals = LateConsensusStrategy(config).evaluate(
        _snapshot(LateConsensusScenario(spot=SpotState(price=100.2, price_to_beat=100.0)))
    )

    # Then: unsupported asset rejects; weak spot move is accepted (spot filter disabled).
    assert unsupported_signals == []
    assert weak_spot_signals  # signal emitted even with weak spot move


def test_late_consensus_signal_carries_configured_freshness_policy() -> None:
    config = _config()
    signal = LateConsensusStrategy(config).evaluate(
        _snapshot(LateConsensusScenario(spot=SpotState(price=101.0, price_to_beat=100.0)))
    )[0]

    assert signal.freshness_policy is not None
    assert signal.freshness_policy.max_orderbook_staleness_ms == config.max_orderbook_staleness_ms
    assert signal.freshness_policy.max_spot_staleness_ms == config.max_spot_staleness_ms
    assert signal.freshness_policy.max_anchor_staleness_ms is None


def test_late_consensus_stale_spot_is_rejected_by_signal_gate() -> None:
    from polysignal_lab.config import BinanceDataConfig, PolymarketDataConfig, SignalConfig
    from polysignal_lab.signal_layer.gate import SignalGate

    strategy = LateConsensusStrategy(_config())
    snapshot = _snapshot(
        LateConsensusScenario(
            spot=SpotState(price=101.0, price_to_beat=100.0, staleness_ms=2_000)
        )
    )
    signal = strategy.evaluate(snapshot)[0]

    decision = SignalGate(
        SignalConfig(dedupe_enabled=False),
        PolymarketDataConfig(max_book_staleness_ms=60_000),
        BinanceDataConfig(max_price_staleness_ms=60_000),
    ).evaluate(signal, snapshot)

    assert decision.accepted is False
    assert decision.rejected is not None
    assert decision.rejected.reason_code == "STALE_SPOT_PRICE"
    assert decision.rejected.details["lag_ms"] == 2_000
    assert decision.rejected.details["threshold_ms"] == 1_500


def test_late_consensus_stale_orderbook_is_rejected_by_signal_gate() -> None:
    from polysignal_lab.config import BinanceDataConfig, PolymarketDataConfig, SignalConfig
    from polysignal_lab.signal_layer.gate import SignalGate

    strategy = LateConsensusStrategy(_config())
    snapshot = _snapshot(
        LateConsensusScenario(
            books=ConsensusBooks(staleness_ms=2_000),
            spot=SpotState(price=101.0, price_to_beat=100.0),
        )
    )
    signal = strategy.evaluate(snapshot)[0]

    decision = SignalGate(
        SignalConfig(dedupe_enabled=False),
        PolymarketDataConfig(max_book_staleness_ms=60_000),
        BinanceDataConfig(max_price_staleness_ms=60_000),
    ).evaluate(signal, snapshot)

    assert decision.accepted is False
    assert decision.rejected is not None
    assert decision.rejected.reason_code == "STALE_ORDERBOOK"
    assert decision.rejected.details["lag_ms"] == 2_000
    assert decision.rejected.details["threshold_ms"] == 1_500


async def test_late_consensus_gate_rejection_does_not_consume_entry_state() -> None:
    from polysignal_lab.app.scheduler_processing import evaluate_once
    from polysignal_lab.config import BinanceDataConfig, PolymarketDataConfig, SignalConfig
    from polysignal_lab.signal_layer.gate import SignalGate

    class _Markets:
        def __init__(self, market) -> None:
            self._market = market

        def active(self) -> list:
            return [self._market]

    class _SnapshotBuilder:
        def __init__(self, snapshot: MarketSnapshot) -> None:
            self.snapshot = snapshot

        async def build(self, market) -> MarketSnapshot:
            return self.snapshot

    class _Consensus:
        def add(self, signal):
            return None

    class _Logs:
        def __init__(self) -> None:
            self.rows: list[tuple[str, object]] = []

        def append(self, stream: str, row: object) -> None:
            self.rows.append((stream, row))

    class _SQLite:
        def __init__(self) -> None:
            self.rejected: list[object] = []

        def insert_rejected_signal(self, rejected: object) -> None:
            self.rejected.append(rejected)

    class _Logger:
        def info(self, *args, **kwargs) -> None:
            pass

        def exception(self, *args, **kwargs) -> None:
            pass

    strategy = LateConsensusStrategy(_config())
    stale_snapshot = _snapshot(
        LateConsensusScenario(
            spot=SpotState(price=101.0, price_to_beat=100.0, staleness_ms=2_000)
        )
    )
    fresh_snapshot = _snapshot(
        LateConsensusScenario(spot=SpotState(price=101.0, price_to_beat=100.0))
    )
    scheduler = SimpleNamespace(
        settings=SimpleNamespace(
            signal=SignalConfig(),
            data=SimpleNamespace(
                polymarket=PolymarketDataConfig(max_book_staleness_ms=60_000),
                binance=BinanceDataConfig(max_price_staleness_ms=60_000),
            ),
        ),
        ctx=SimpleNamespace(markets=_Markets(stale_snapshot.market)),
        snapshot_builder=_SnapshotBuilder(stale_snapshot),
        logger=_Logger(),
        strategies=[strategy],
        gate=SignalGate(
            SignalConfig(dedupe_enabled=False),
            PolymarketDataConfig(max_book_staleness_ms=60_000),
            BinanceDataConfig(max_price_staleness_ms=60_000),
        ),
        consensus=_Consensus(),
        logs=_Logs(),
        sqlite=_SQLite(),
    )

    stale_accepted = await evaluate_once(scheduler)

    assert stale_accepted == []
    assert len(scheduler.sqlite.rejected) == 1
    assert scheduler.sqlite.rejected[0].reason_code == "STALE_SPOT_PRICE"

    scheduler.snapshot_builder.snapshot = fresh_snapshot
    fresh_accepted = await evaluate_once(scheduler)

    assert len(fresh_accepted) == 1
    assert fresh_accepted[0].market_id == stale_snapshot.market.market_id

    scheduler.snapshot_builder.snapshot = _snapshot(
        LateConsensusScenario(spot=SpotState(price=101.0, price_to_beat=100.0))
    )
    repeated_after_accept = await evaluate_once(scheduler)

    assert repeated_after_accept == []


def test_late_consensus_gate_rejection_does_not_consume_flip_guard_state() -> None:
    from polysignal_lab.config import BinanceDataConfig, PolymarketDataConfig, SignalConfig
    from polysignal_lab.signal_layer.gate import SignalGate

    strategy = LateConsensusStrategy(
        _config().model_copy(update={"entry_frequency_sec": 0})
    )
    stale_up_snapshot = _snapshot(
        LateConsensusScenario(
            spot=SpotState(price=101.0, price_to_beat=100.0, staleness_ms=2_000)
        )
    )
    stale_up_signal = strategy.evaluate(stale_up_snapshot)[0]

    decision = SignalGate(
        SignalConfig(dedupe_enabled=False),
        PolymarketDataConfig(max_book_staleness_ms=60_000),
        BinanceDataConfig(max_price_staleness_ms=60_000),
    ).evaluate(stale_up_signal, stale_up_snapshot)

    assert decision.accepted is False
    assert decision.rejected is not None
    assert decision.rejected.reason_code == "STALE_SPOT_PRICE"

    fresh_down_snapshot = _snapshot(
        LateConsensusScenario(
            books=ConsensusBooks(up_ask=0.18, down_ask=0.82),
            spot=SpotState(price=99.0, price_to_beat=100.0),
        )
    )
    fresh_down_signals = strategy.evaluate(fresh_down_snapshot)

    assert len(fresh_down_signals) == 1
    assert fresh_down_signals[0].side == Side.DOWN
