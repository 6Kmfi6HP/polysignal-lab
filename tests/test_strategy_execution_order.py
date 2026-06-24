from __future__ import annotations

import asyncio
import time

import pytest

from polysignal_lab.config import Settings
from polysignal_lab.strategies.execution import build_strategy_schedule, validate_strategy_dag
from polysignal_lab.strategies.execution import StrategyScheduleEntry
from test_signal_pipeline_equivalence import _FakeScheduler, _FakeStrategy, _snapshot


def test_strategy_execution_defaults_preserve_yaml_order() -> None:
    settings = Settings.from_yaml("config/signal_bot.yaml")
    schedule = build_strategy_schedule(settings.strategies)

    assert [entry.strategy_config_index for entry in schedule] == list(range(len(schedule)))
    assert all(entry.priority == 100 for entry in schedule)
    assert all(entry.execution_mode == "stateful" for entry in schedule)


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
