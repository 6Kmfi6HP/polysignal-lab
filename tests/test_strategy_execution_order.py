"""
Input: __future__, __future__.annotations, asyncio, time, pytest, polysignal_lab.domain.enums, polysignal_lab.domain.enums.Side, polysignal_lab.domain.signal, polysignal_lab.domain.signal.SignalCandidate, polysignal_lab.signal_layer.arbiter
Output: test_strategy_execution_defaults_preserve_yaml_order, test_strategy_dependency_cycle_is_rejected, test_snapshot_building_uses_bounded_concurrency, test_stateless_strategies_run_in_parallel_ready_set, test_arbitration_suppressed_candidates_notify_rejection_without_gate_commit, test_dependencies_order_evaluation_and_commit_before_dependents, test_stateless_dependencies_complete_before_dependent_evaluation, test_per_market_strategy_cannot_depend_on_cross_market_strategy, test_dependencies_complete_for_all_markets_before_dependent_level, _RecordingStrategy
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import asyncio
import time

import pytest
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.signal_layer.arbiter import SignalArbiter

from polysignal_lab.config import Settings
from polysignal_lab.strategies.execution import (
    StrategyScheduleEntry,
    build_strategy_schedule,
    validate_strategy_dag,
)
from test_signal_pipeline_equivalence import _FakeScheduler, _FakeStrategy, _candidate, _snapshot


class _RecordingStrategy(_FakeStrategy):
    def __init__(self, name: str, candidates_by_market: dict[str, list[SignalCandidate]]) -> None:
        super().__init__(name, candidates_by_market)
        self.accepted_signal_ids: list[str] = []
        self.rejected_signal_ids: list[tuple[str, str]] = []

    def notify_signal_accepted(self, signal: SignalCandidate) -> None:
        self.accepted_signal_ids.append(signal.signal_id)

    def notify_signal_rejected(self, signal: SignalCandidate, rejected) -> None:
        self.rejected_signal_ids.append((signal.signal_id, rejected.reason_code))


class _OrderingStrategy(_RecordingStrategy):
    def __init__(
        self,
        name: str,
        candidates_by_market: dict[str, list[SignalCandidate]],
        events: list[str],
    ) -> None:
        super().__init__(name, candidates_by_market)
        self.events = events

    def evaluate(self, snapshot):
        self.events.append(f"evaluate:{self.name}")
        return super().evaluate(snapshot)

    def notify_signal_accepted(self, signal: SignalCandidate) -> None:
        self.events.append(f"commit:{self.name}")
        super().notify_signal_accepted(signal)


def test_strategy_execution_defaults_preserve_yaml_order() -> None:
    settings = Settings.from_yaml("config/signal_bot.yaml")
    schedule = build_strategy_schedule(settings.strategies)

    assert [entry.strategy_config_index for entry in schedule] == list(range(len(schedule)))
    assert all(entry.priority == 100 for entry in schedule)
    assert all(
        entry.execution_mode == "stateful"
        for entry in schedule
        if entry.name != "cross_market_bot"
    )
    lab_settings = Settings.from_yaml("config/signal_bot.lab.yaml")
    lab_schedule = build_strategy_schedule(lab_settings.strategies)
    assert next(
        entry for entry in lab_schedule if entry.name == "cross_market_bot"
    ).execution_mode == "cross_market"


def test_strategy_dependency_cycle_is_rejected() -> None:
    schedule = [
        ("a", ["b"]),
        ("b", ["a"]),
    ]

    with pytest.raises(ValueError, match="strategy dependency cycle"):
        validate_strategy_dag(schedule)


async def test_snapshot_building_uses_bounded_concurrency() -> None:
    snapshots = [_snapshot("BTC", "5m"), _snapshot("ETH", "5m"), _snapshot("SOL", "5m")]
    strategy = _FakeStrategy("noop", {})
    scheduler = _FakeScheduler(
        snapshots,
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
    scheduler.settings.signal.max_snapshot_concurrency = 2
    active = 0
    peak = 0

    async def build(market):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return scheduler.snapshot_builder._by_market_id[market.market_id]

    scheduler.snapshot_builder.build = build

    await scheduler.evaluate_once()

    assert peak == 2


async def test_stateless_strategies_run_in_parallel_ready_set() -> None:
    snapshot = _snapshot("BTC", "5m")
    strategies = [_FakeStrategy(name, {}) for name in ("fast_a", "fast_b", "fast_c")]
    scheduler = _FakeScheduler(
        [snapshot],
        [
            StrategyScheduleEntry(
                strategy=strategy,
                name=strategy.name,
                priority=100,
                depends_on=(),
                execution_mode="stateless",
                strategy_config_index=index,
            )
            for index, strategy in enumerate(strategies)
        ],
    )
    started: list[str] = []

    def slow_evaluate(name: str):
        started.append(name)
        time.sleep(0.05)
        return []

    for entry in scheduler.strategy_schedule:
        entry.strategy.evaluate = lambda snapshot, name=entry.name: slow_evaluate(name)

    start = time.perf_counter()
    await scheduler.evaluate_once()
    elapsed = time.perf_counter() - start

    assert set(started) == {entry.name for entry in scheduler.strategy_schedule}
    assert elapsed < 0.11


async def test_arbitration_suppressed_candidates_notify_rejection_without_gate_commit() -> None:
    snapshot = _snapshot("BTC", "5m")
    market_id = snapshot.market.market_id
    up_candidate = _candidate("up_strategy", snapshot, Side.UP)
    down_candidate = _candidate("down_strategy", snapshot, Side.DOWN)
    up_strategy = _RecordingStrategy("up_strategy", {market_id: [up_candidate]})
    down_strategy = _RecordingStrategy("down_strategy", {market_id: [down_candidate]})
    scheduler = _FakeScheduler(
        [snapshot],
        [
            StrategyScheduleEntry(
                strategy=up_strategy,
                name=up_strategy.name,
                priority=100,
                depends_on=(),
                execution_mode="stateful",
                strategy_config_index=0,
            ),
            StrategyScheduleEntry(
                strategy=down_strategy,
                name=down_strategy.name,
                priority=100,
                depends_on=(),
                execution_mode="stateful",
                strategy_config_index=1,
            ),
        ],
    )
    scheduler.arbiter = SignalArbiter(conflict_policy="suppress_ambiguous")

    accepted = await scheduler.evaluate_once()

    assert accepted == []
    assert scheduler.gate.evaluated_count == 0
    assert scheduler.consensus.added_count == 0
    assert up_strategy.accepted_signal_ids == []
    assert down_strategy.accepted_signal_ids == []
    assert up_strategy.rejected_signal_ids == [
        (up_candidate.signal_id, "ARBITRATION_SUPPRESSED")
    ]
    assert down_strategy.rejected_signal_ids == [
        (down_candidate.signal_id, "ARBITRATION_SUPPRESSED")
    ]


async def test_dependencies_order_evaluation_and_commit_before_dependents() -> None:
    snapshot = _snapshot("BTC", "5m")
    market_id = snapshot.market.market_id
    events: list[str] = []
    dependency = _OrderingStrategy(
        "dependency",
        {market_id: [_candidate("dependency", snapshot)]},
        events,
    )
    dependent = _OrderingStrategy(
        "dependent",
        {market_id: [_candidate("dependent", snapshot)]},
        events,
    )
    scheduler = _FakeScheduler(
        [snapshot],
        [
            StrategyScheduleEntry(
                strategy=dependent,
                name=dependent.name,
                priority=10,
                depends_on=("dependency",),
                execution_mode="stateful",
                strategy_config_index=0,
            ),
            StrategyScheduleEntry(
                strategy=dependency,
                name=dependency.name,
                priority=100,
                depends_on=(),
                execution_mode="stateful",
                strategy_config_index=1,
            ),
        ],
    )
    scheduler.arbiter = SignalArbiter()

    accepted = await scheduler.evaluate_once()

    assert [signal.strategy for signal in accepted] == ["dependency", "dependent"]
    assert events == [
        "evaluate:dependency",
        "evaluate:dependent",
        "commit:dependency",
        "commit:dependent",
    ]


async def test_stateless_dependencies_complete_before_dependent_evaluation() -> None:
    snapshot = _snapshot("BTC", "5m")
    market_id = snapshot.market.market_id
    events: list[str] = []
    dependency = _OrderingStrategy(
        "dependency",
        {market_id: [_candidate("dependency", snapshot)]},
        events,
    )
    dependent = _OrderingStrategy(
        "dependent",
        {market_id: [_candidate("dependent", snapshot)]},
        events,
    )

    def slow_dependency_evaluate(snapshot):
        time.sleep(0.05)
        events.append("evaluate:dependency")
        return _FakeStrategy.evaluate(dependency, snapshot)

    dependency.evaluate = slow_dependency_evaluate
    scheduler = _FakeScheduler(
        [snapshot],
        [
            StrategyScheduleEntry(
                strategy=dependent,
                name=dependent.name,
                priority=10,
                depends_on=("dependency",),
                execution_mode="stateful",
                strategy_config_index=0,
            ),
            StrategyScheduleEntry(
                strategy=dependency,
                name=dependency.name,
                priority=100,
                depends_on=(),
                execution_mode="stateless",
                strategy_config_index=1,
            ),
        ],
    )
    scheduler.arbiter = SignalArbiter()

    accepted = await scheduler.evaluate_once()

    assert [signal.strategy for signal in accepted] == ["dependency", "dependent"]
    assert events == [
        "evaluate:dependency",
        "evaluate:dependent",
        "commit:dependency",
        "commit:dependent",
    ]


async def test_per_market_strategy_cannot_depend_on_cross_market_strategy() -> None:
    snapshot = _snapshot("BTC", "5m")
    events: list[str] = []
    cross_market = _FakeStrategy("cross_market", {})
    dependent = _OrderingStrategy(
        "dependent",
        {snapshot.market.market_id: [_candidate("dependent", snapshot)]},
        events,
    )
    scheduler = _FakeScheduler(
        [snapshot],
        [
            StrategyScheduleEntry(
                strategy=dependent,
                name=dependent.name,
                priority=10,
                depends_on=(cross_market.name,),
                execution_mode="stateful",
                strategy_config_index=0,
            ),
            StrategyScheduleEntry(
                strategy=cross_market,
                name=cross_market.name,
                priority=100,
                depends_on=(),
                execution_mode="cross_market",
                strategy_config_index=1,
            ),
        ],
    )

    with pytest.raises(ValueError, match="cross_market dependency.*dependent"):
        await scheduler.evaluate_once()
    assert events == []


async def test_dependencies_complete_for_all_markets_before_dependent_level() -> None:
    snapshots = [_snapshot("BTC", "5m"), _snapshot("ETH", "5m")]
    events: list[str] = []
    dependency = _OrderingStrategy(
        "dependency",
        {
            snapshot.market.market_id: [_candidate("dependency", snapshot)]
            for snapshot in snapshots
        },
        events,
    )
    dependent = _OrderingStrategy(
        "dependent",
        {
            snapshot.market.market_id: [_candidate("dependent", snapshot)]
            for snapshot in snapshots
        },
        events,
    )

    def evaluate_dependency(snapshot):
        events.append(f"evaluate:dependency:{snapshot.market.asset}")
        return _FakeStrategy.evaluate(dependency, snapshot)

    def evaluate_dependent(snapshot):
        events.append(f"evaluate:dependent:{snapshot.market.asset}")
        return _FakeStrategy.evaluate(dependent, snapshot)

    dependency.evaluate = evaluate_dependency
    dependent.evaluate = evaluate_dependent
    scheduler = _FakeScheduler(
        snapshots,
        [
            StrategyScheduleEntry(
                strategy=dependent,
                name=dependent.name,
                priority=10,
                depends_on=("dependency",),
                execution_mode="stateful",
                strategy_config_index=0,
            ),
            StrategyScheduleEntry(
                strategy=dependency,
                name=dependency.name,
                priority=100,
                depends_on=(),
                execution_mode="stateful",
                strategy_config_index=1,
            ),
        ],
    )
    scheduler.arbiter = SignalArbiter()

    accepted = await scheduler.evaluate_once()

    assert [signal.strategy for signal in accepted] == [
        "dependency",
        "dependency",
        "dependent",
        "dependent",
    ]
    assert events[:4] == [
        "evaluate:dependency:BTC",
        "evaluate:dependency:ETH",
        "evaluate:dependent:BTC",
        "evaluate:dependent:ETH",
    ]