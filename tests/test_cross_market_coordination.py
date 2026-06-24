from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from dataclasses import dataclass

from polysignal_lab.domain.snapshot_batch import SnapshotBatch, CrossMarketEvaluationContext
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.strategies.base import BaseStrategy
from polysignal_lab.strategies.execution import StrategyScheduleEntry
from test_signal_pipeline_equivalence import _FakeScheduler, _candidate
from test_signal_pipeline_equivalence import _snapshot


def test_cross_market_context_contains_all_relation_legs() -> None:
    snapshot_btc = _snapshot("BTC", "5m")
    snapshot_eth = _snapshot("ETH", "5m")
    batch = SnapshotBatch(
        batch_id="batch-1",
        as_of=datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc),
        market_order=(snapshot_btc.market.market_id, snapshot_eth.market.market_id),
        snapshots={
            snapshot_btc.market.market_id: snapshot_btc,
            snapshot_eth.market.market_id: snapshot_eth,
        },
        max_source_skew_ms=500,
    )
    context = CrossMarketEvaluationContext(
        relation_id="btc-eth",
        snapshots_by_condition_id={
            snapshot_btc.market.condition_id: snapshot_btc,
            snapshot_eth.market.condition_id: snapshot_eth,
        },
        batch=batch,
    )

    assert set(context.snapshots_by_condition_id) == {
        snapshot_btc.market.condition_id,
        snapshot_eth.market.condition_id,
    }


@dataclass
class _GroupStrategy(BaseStrategy):
    name: str
    emitted: SignalCandidate
    seen_contexts: list[CrossMarketEvaluationContext]

    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        raise AssertionError("cross-market scheduler path must call evaluate_group")

    def evaluate_group(
        self, context: CrossMarketEvaluationContext
    ) -> list[SignalCandidate]:
        self.seen_contexts.append(context)
        return [self.emitted]


async def test_cross_market_strategy_receives_snapshot_batch_once() -> None:
    snapshot_btc = _snapshot("BTC", "5m")
    snapshot_eth = _snapshot("ETH", "5m")
    strategy = _GroupStrategy(
        name="cross",
        emitted=_candidate("cross", snapshot_btc),
        seen_contexts=[],
    )
    scheduler = _FakeScheduler(
        [snapshot_btc, snapshot_eth],
        [
            StrategyScheduleEntry(
                strategy=strategy,
                name=strategy.name,
                priority=100,
                depends_on=(),
                execution_mode="cross_market",
                strategy_config_index=0,
            )
        ],
    )

    accepted = await scheduler.evaluate_once()

    assert [signal.strategy for signal in accepted] == ["cross"]
    assert len(strategy.seen_contexts) == 1
    assert set(strategy.seen_contexts[0].snapshots_by_condition_id) == {
        snapshot_btc.market.condition_id,
        snapshot_eth.market.condition_id,
    }


async def test_cross_market_partial_relation_skips_group_evaluation() -> None:
    snapshot_btc = _snapshot("BTC", "5m")
    missing_condition_id = "missing-condition"
    strategy = _GroupStrategy(
        name="cross",
        emitted=_candidate("cross", snapshot_btc),
        seen_contexts=[],
    )
    strategy._relations = [
        SimpleNamespace(
            relation_id="btc-missing",
            condition_ids=[snapshot_btc.market.condition_id, missing_condition_id],
        )
    ]
    scheduler = _FakeScheduler(
        [snapshot_btc],
        [
            StrategyScheduleEntry(
                strategy=strategy,
                name=strategy.name,
                priority=100,
                depends_on=(),
                execution_mode="cross_market",
                strategy_config_index=0,
            )
        ],
    )

    accepted = await scheduler.evaluate_once()

    assert accepted == []
    assert strategy.seen_contexts == []
    assert scheduler.gate.evaluated_count == 0
