"""
Input: __future__, __future__.annotations, dataclasses, dataclasses.dataclass, types, types.SimpleNamespace, factories, factories.BookFactoryConfig, factories.MarketFactoryConfig, factories.sample_book
Output: test_stage_split_preserves_serial_accepted_signals, test_parallel_generation_ordered_commit_matches_serial_state, _FakeMarkets, _FakeSnapshotBuilder, _FakeLogger, _FakeGate, _FakeConsensus, _FakeLogs, _FakeSQLite, _FakeWallet
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from factories import BookFactoryConfig, MarketFactoryConfig, sample_book, sample_market, sample_spot

from polysignal_lab.config import Settings
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import FreshnessState, MarketSnapshot
from polysignal_lab.signal_layer.gate import GateDecision
from polysignal_lab.signal_layer.arbiter import SignalArbiter
from polysignal_lab.strategies.base import BaseStrategy
from polysignal_lab.strategies.execution import StrategyScheduleEntry


class _FakeMarkets:
    def __init__(self, snapshots: list[MarketSnapshot]) -> None:
        self._snapshots = snapshots

    def active(self):
        return [snapshot.market for snapshot in self._snapshots]


class _FakeSnapshotBuilder:
    def __init__(self, snapshots: list[MarketSnapshot]) -> None:
        self._by_market_id = {snapshot.market.market_id: snapshot for snapshot in snapshots}

    async def build(self, market):
        return self._by_market_id[market.market_id]


class _FakeLogger:
    def info(self, *_args, **_kwargs) -> None:
        pass

    def exception(self, *_args, **_kwargs) -> None:
        pass


class _FakeGate:
    def __init__(self) -> None:
        self.evaluated_count = 0

    def evaluate(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> GateDecision:
        self.evaluated_count += 1
        return GateDecision(True, signal=candidate)


class _FakeConsensus:
    def __init__(self) -> None:
        self.added_count = 0

    def add(self, signal: SignalCandidate) -> None:
        self.added_count += 1
        return None


class _FakeLogs:
    def append(self, *_args, **_kwargs) -> None:
        pass


class _FakeSQLite:
    def insert_rejected_signal(self, *_args, **_kwargs) -> None:
        pass

    def counts(self) -> dict[str, int]:
        return {}

class _FakeWallet:
    def __init__(self) -> None:
        self.cash_balance = 1000.0

    def snapshot(self):
        return SimpleNamespace(cash_balance=self.cash_balance)



@dataclass
class _FakeStrategy(BaseStrategy):
    name: str
    candidates_by_market: dict[str, list[SignalCandidate]]

    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        return list(self.candidates_by_market.get(snapshot.market.market_id, []))


class _FakeScheduler:
    def __init__(self, snapshots: list[MarketSnapshot], entries: list[StrategyScheduleEntry]) -> None:
        self.settings = Settings()
        self.ctx = SimpleNamespace(markets=_FakeMarkets(snapshots))
        self.snapshot_builder = _FakeSnapshotBuilder(snapshots)
        self.strategy_schedule = entries
        self.strategies = [entry.strategy for entry in entries]
        self.gate = _FakeGate()
        self.consensus = _FakeConsensus()
        self.logs = _FakeLogs()
        self.sqlite = _FakeSQLite()
        self.wallet = _FakeWallet()
        self.logger = _FakeLogger()

    async def evaluate_once(self) -> list[SignalCandidate]:
        from polysignal_lab.app.scheduler_processing import evaluate_once

        return await evaluate_once(self)


async def test_stage_split_preserves_serial_accepted_signals() -> None:
    from polysignal_lab.app.scheduler_processing import evaluate_once

    snapshot = _snapshot("BTC", "5m")
    candidate = _candidate("fake_strategy", snapshot)
    strategy = _FakeStrategy("fake_strategy", {snapshot.market.market_id: [candidate]})
    scheduler = _FakeScheduler(
        [snapshot],
        [
            StrategyScheduleEntry(
                strategy=strategy,
                name=strategy.name,
                priority=100,
                depends_on=(),
                execution_mode="stateful",
                strategy_config_index=0,
            )
        ],
    )

    accepted = await evaluate_once(scheduler)

    assert [signal.strategy for signal in accepted] == ["fake_strategy"]
    assert scheduler.gate.evaluated_count == 1
    assert scheduler.consensus.added_count == 1


async def test_parallel_generation_ordered_commit_matches_serial_state() -> None:
    snapshots = [_snapshot("BTC", "5m"), _snapshot("ETH", "5m")]
    candidates = [_candidate("first", snapshots[0]), _candidate("second", snapshots[1])]
    serial_scheduler = _scheduler_pair_member(
        snapshots, candidates, execution_mode="stateful"
    )
    parallel_scheduler = _scheduler_pair_member(
        snapshots, candidates, execution_mode="stateless"
    )
    serial_scheduler.arbiter = SignalArbiter()
    parallel_scheduler.arbiter = SignalArbiter()
    for scheduler in (serial_scheduler, parallel_scheduler):
        scheduler.settings.signal.max_snapshot_concurrency = 2

    serial = await serial_scheduler.evaluate_once()
    parallel = await parallel_scheduler.evaluate_once()

    assert [signal.signal_id for signal in parallel] == [
        signal.signal_id for signal in serial
    ]
    assert (
        parallel_scheduler.wallet.snapshot().cash_balance
        == serial_scheduler.wallet.snapshot().cash_balance
    )
    assert parallel_scheduler.sqlite.counts() == serial_scheduler.sqlite.counts()
    assert parallel_scheduler.gate.evaluated_count == serial_scheduler.gate.evaluated_count
    assert parallel_scheduler.consensus.added_count == serial_scheduler.consensus.added_count


def _scheduler_pair_member(
    snapshots: list[MarketSnapshot],
    candidates: list[SignalCandidate],
    *,
    execution_mode: str,
) -> _FakeScheduler:
    first, second = candidates
    strategies = [
        _FakeStrategy("first", {snapshots[0].market.market_id: [first]}),
        _FakeStrategy("second", {snapshots[1].market.market_id: [second]}),
    ]
    scheduler = _FakeScheduler(
        snapshots,
        [
            StrategyScheduleEntry(
                strategy=strategy,
                name=strategy.name,
                priority=10 + index,
                depends_on=(),
                execution_mode=execution_mode,
                strategy_config_index=index,
            )
            for index, strategy in enumerate(strategies)
        ],
    )
    return scheduler


def _snapshot(asset: str, timeframe: str) -> MarketSnapshot:
    market = sample_market(
        MarketFactoryConfig(asset=asset, timeframe=timeframe, seconds_to_close=120)
    )
    return MarketSnapshot(
        snapshot_id=f"snapshot-{market.market_id}",
        market=market,
        up_book=sample_book(
            market.token_for(Side.UP).token_id,
            BookFactoryConfig(ask=0.45, bid=0.44, size=500),
        ),
        down_book=sample_book(
            market.token_for(Side.DOWN).token_id,
            BookFactoryConfig(ask=0.55, bid=0.54, size=500),
        ),
        spot=sample_spot(),
        price_to_beat=market.price_to_beat,
        freshness=FreshnessState(max_ms=10, up_book_ms=10, down_book_ms=10, spot_ms=10),
    )


def _candidate(strategy: str, snapshot: MarketSnapshot, side: Side = Side.UP) -> SignalCandidate:
    return SignalCandidate.build(
        strategy=strategy,
        asset=snapshot.market.asset,
        timeframe=snapshot.market.timeframe,
        market_id=snapshot.market.market_id,
        market_slug=snapshot.market.market_slug,
        condition_id=snapshot.market.condition_id,
        token_id=snapshot.market.token_for(side).token_id,
        side=side,
        confidence=0.75,
        entry_reference_price=snapshot.ask_for(side) or 0.45,
        max_entry_price=0.60,
        seconds_to_close=snapshot.seconds_to_close,
        data_freshness_ms=snapshot.freshness.max_ms,
        reason_codes=["FAKE"],
        metrics={"max_spread": 0.2},
        snapshot_id=snapshot.snapshot_id,
    )
