from __future__ import annotations

import asyncio

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
