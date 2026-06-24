from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from factories import BookFactoryConfig, MarketFactoryConfig, sample_book, sample_market, sample_spot

from polysignal_lab.app.services.signal_pipeline import SignalPipeline
from polysignal_lab.app import scheduler_processing
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import FreshnessState, MarketSnapshot
from polysignal_lab.signal_layer.gate import GateDecision
from polysignal_lab.strategies.base import BaseStrategy
from polysignal_lab.strategies.execution import StrategyScheduleEntry


@dataclass
class _FakeStrategy(BaseStrategy):
    name: str
    calls: int = 0

    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        self.calls += 1
        return [_candidate(self.name, snapshot)]


class _FakePersistence:
    def __init__(self) -> None:
        self.logs: list[tuple[str, object]] = []
        self.statuses: list[object] = []

    def append_log(self, stream: str, payload: object) -> None:
        self.logs.append((stream, payload))

    def insert_strategy_status(self, status: object) -> None:
        self.statuses.append(status)

    def insert_rejected_signal(self, rejected: object) -> None:
        raise AssertionError("disabled strategies must not produce rejected signals")


class _FakeGate:
    def evaluate(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> GateDecision:
        return GateDecision(True, signal=candidate)


class _FakeConsensus:
    def add(self, signal: SignalCandidate) -> None:
        return None


class _FakeLogger:
    def exception(self, *_args, **_kwargs) -> None:
        raise AssertionError("unexpected exception log")


async def test_manual_disabled_strategy_skips_without_mutating_list() -> None:
    snapshot = _snapshot()
    first = _FakeStrategy("first")
    second = _FakeStrategy("second")
    persistence = _FakePersistence()
    pipeline = SignalPipeline(
        [first, second], _FakeGate(), _FakeConsensus(), persistence
    )
    pipeline.set_strategy_enabled("first", False)
    scheduler = SimpleNamespace(
        signal_pipeline=pipeline,
        strategies=[first, second],
        strategy_schedule=[
            _entry(first, 0),
            _entry(second, 1),
        ],
        gate=_FakeGate(),
        consensus=_FakeConsensus(),
        persistence=persistence,
        logger=_FakeLogger(),
    )

    envelopes = await scheduler_processing.evaluate_candidates_ordered(
        scheduler, [(0, snapshot)]
    )

    assert [envelope.strategy_name for envelope in envelopes] == ["second"]
    assert [strategy.name for strategy in scheduler.strategies] == ["first", "second"]
    assert first.calls == 0
    assert second.calls == 1
    assert persistence.statuses[0].strategy == "first"
    assert persistence.statuses[0].status == "inactive"
    assert persistence.statuses[0].reason == "manual_disabled"


async def test_dependency_disabled_skips_dependent_strategy() -> None:
    snapshot = _snapshot()
    base = _FakeStrategy("base")
    dependent = _FakeStrategy("dependent")
    persistence = _FakePersistence()
    pipeline = SignalPipeline([base, dependent], _FakeGate(), _FakeConsensus(), persistence)
    pipeline.set_strategy_dependencies({"dependent": ("base",)})
    pipeline.set_strategy_enabled("base", False)
    scheduler = SimpleNamespace(
        signal_pipeline=pipeline,
        strategies=[base, dependent],
        strategy_schedule=[
            _entry(base, 0),
            _entry(dependent, 1, depends_on=("base",)),
        ],
        gate=_FakeGate(),
        consensus=_FakeConsensus(),
        persistence=persistence,
        logger=_FakeLogger(),
    )

    envelopes = await scheduler_processing.evaluate_candidates_ordered(
        scheduler, [(0, snapshot)]
    )

    assert envelopes == []
    assert base.calls == 0
    assert dependent.calls == 0
    assert [(s.strategy, s.reason) for s in persistence.statuses] == [
        ("base", "manual_disabled"),
        ("dependent", "dependency_disabled:base"),
    ]


def _entry(
    strategy: _FakeStrategy, index: int, *, depends_on: tuple[str, ...] = ()
) -> StrategyScheduleEntry:
    return StrategyScheduleEntry(
        strategy=strategy,
        name=strategy.name,
        priority=10 + index,
        depends_on=depends_on,
        execution_mode="stateful",
        strategy_config_index=index,
    )


def _snapshot() -> MarketSnapshot:
    market = sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m", seconds_to_close=120))
    return MarketSnapshot(
        snapshot_id=f"snapshot-{market.market_id}",
        market=market,
        up_book=sample_book(market.token_for(Side.UP).token_id, BookFactoryConfig(ask=0.45, bid=0.44, size=500)),
        down_book=sample_book(market.token_for(Side.DOWN).token_id, BookFactoryConfig(ask=0.55, bid=0.54, size=500)),
        spot=sample_spot(),
        price_to_beat=market.price_to_beat,
        freshness=FreshnessState(max_ms=10, up_book_ms=10, down_book_ms=10, spot_ms=10),
    )


def _candidate(strategy: str, snapshot: MarketSnapshot) -> SignalCandidate:
    return SignalCandidate.build(
        strategy=strategy,
        asset=snapshot.market.asset,
        timeframe=snapshot.market.timeframe,
        market_id=snapshot.market.market_id,
        market_slug=snapshot.market.market_slug,
        condition_id=snapshot.market.condition_id,
        token_id=snapshot.market.token_for(Side.UP).token_id,
        side=Side.UP,
        confidence=0.75,
        entry_reference_price=0.45,
        max_entry_price=0.60,
        seconds_to_close=snapshot.seconds_to_close,
        data_freshness_ms=snapshot.freshness.max_ms,
        reason_codes=["FAKE"],
        metrics={"max_spread": 0.2},
        snapshot_id=snapshot.snapshot_id,
    )
