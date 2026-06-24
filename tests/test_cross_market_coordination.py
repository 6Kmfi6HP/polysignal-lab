from __future__ import annotations

from datetime import datetime, timezone

from polysignal_lab.domain.snapshot_batch import SnapshotBatch, CrossMarketEvaluationContext
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
