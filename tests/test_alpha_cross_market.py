"""
Input: __future__, __future__.annotations, datetime, datetime.datetime, datetime.timezone, polysignal_lab.alpha.cross_market_core, polysignal_lab.alpha.cross_market_core.CrossMarketAlphaCore, polysignal_lab.alpha.cross_market_core.MarketRelation, polysignal_lab.alpha.cross_market_core.RelationType, polysignal_lab.alpha.ptb_diff_core
Output: test_cross_market_group_core_matches_legacy_group_candidates, test_cross_market_group_walks_ask_depth_before_emitting, test_cross_market_leg_failure_marks_basket_failed
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from datetime import datetime, timezone

from polysignal_lab.alpha.cross_market_core import CrossMarketAlphaCore, MarketRelation, RelationType
from polysignal_lab.alpha.ptb_diff_core import decision_to_signal, market_view_from_snapshot
from polysignal_lab.alpha.types import MarketGroupView
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.snapshot_batch import CrossMarketEvaluationContext, SnapshotBatch
from polysignal_lab.strategies.cross_market_bot import CrossMarketBotConfig, CrossMarketBotStrategy
from alpha_equivalence import normalize_candidate, normalize_decision
from factories import BookFactoryConfig, sample_book, sample_snapshot
from polysignal_lab.domain.orderbook import BookLevel


def _snapshot(asset: str, ask: float):
    snapshot = sample_snapshot(asset=asset, up_ask=ask, down_ask=0.60)
    return snapshot.model_copy(
        update={
            "up_book": sample_book(
                snapshot.market.token_for(Side.UP).token_id,
                BookFactoryConfig(ask=ask, bid=max(0.01, ask - 0.01), size=500),
            )
        }
    )


def _snapshot_with_up_asks(asset: str, asks: list[BookLevel]):
    snapshot = _snapshot(asset, asks[0].price)
    return snapshot.model_copy(
        update={
            "up_book": snapshot.up_book.model_copy(update={"asks": asks}),
        }
    )


def _group_view(relation_id: str, *snapshots) -> MarketGroupView:
    views = {}
    for snapshot in snapshots:
        view = market_view_from_snapshot(snapshot)
        assert view is not None
        views[snapshot.market.condition_id] = view
    return MarketGroupView(
        group_id="batch-1",
        relation_id=relation_id,
        created_at=datetime(2026, 6, 25, tzinfo=timezone.utc),
        views_by_condition_id=views,
        max_source_skew_ms=10,
        metrics={},
    )


def _context(relation_id: str, *snapshots) -> CrossMarketEvaluationContext:
    return CrossMarketEvaluationContext(
        relation_id=relation_id,
        snapshots_by_condition_id={snapshot.market.condition_id: snapshot for snapshot in snapshots},
        batch=SnapshotBatch(
            batch_id="batch-1",
            as_of=datetime(2026, 6, 25, tzinfo=timezone.utc),
            market_order=tuple(snapshot.market.market_id for snapshot in snapshots),
            snapshots={snapshot.market.market_id: snapshot for snapshot in snapshots},
            max_source_skew_ms=10,
        ),
    )


def test_cross_market_group_core_matches_legacy_group_candidates() -> None:
    btc = _snapshot("BTC", 0.20)
    eth = _snapshot("ETH", 0.21)
    relation_id = "btc-eth-exhaustive"
    config = CrossMarketBotConfig(assets=["BTC", "ETH"], fee_rate=0.0, min_edge=0.01)
    strategy = CrossMarketBotStrategy(config)
    strategy.register_relation(
        relation_id,
        RelationType.EXHAUSTIVE_MUTUALLY_EXCLUSIVE,
        [btc.market.condition_id, eth.market.condition_id],
        [Side.UP, Side.UP],
    )
    core = CrossMarketAlphaCore(config)
    core.register_relation(
        relation_id,
        RelationType.EXHAUSTIVE_MUTUALLY_EXCLUSIVE,
        [btc.market.condition_id, eth.market.condition_id],
        [Side.UP, Side.UP],
    )

    legacy = strategy.evaluate_group(_context(relation_id, btc, eth))
    decisions = core.evaluate_group(_group_view(relation_id, btc, eth))
    signals = [decision_to_signal(decision, None, strategy.freshness_policy) for decision in decisions]

    assert [normalize_candidate(signal) for signal in legacy] == [normalize_candidate(signal) for signal in signals]
    assert [normalize_candidate(signal) for signal in legacy] == [normalize_decision(decision) for decision in decisions]


def test_cross_market_group_walks_ask_depth_before_emitting() -> None:
    relation_id = "btc-eth-depth"
    config = CrossMarketBotConfig(assets=["BTC", "ETH"], fee_rate=0.0, min_edge=0.01, min_depth_shares=5)
    core = CrossMarketAlphaCore(config)

    shallow = _snapshot_with_up_asks("BTC", [BookLevel(price=0.20, size=1)])
    eth = _snapshot_with_up_asks("ETH", [BookLevel(price=0.20, size=5)])
    core.register_relation(
        relation_id,
        RelationType.EXHAUSTIVE_MUTUALLY_EXCLUSIVE,
        [shallow.market.condition_id, eth.market.condition_id],
        [Side.UP, Side.UP],
    )
    assert core.evaluate_group(_group_view(relation_id, shallow, eth)) == []

    btc = _snapshot_with_up_asks("BTC", [BookLevel(price=0.20, size=1), BookLevel(price=0.22, size=4)])
    core = CrossMarketAlphaCore(config)
    core.register_relation(
        relation_id,
        RelationType.EXHAUSTIVE_MUTUALLY_EXCLUSIVE,
        [btc.market.condition_id, eth.market.condition_id],
        [Side.UP, Side.UP],
    )
    decisions = core.evaluate_group(_group_view(relation_id, btc, eth))

    assert decisions
    assert round(decisions[0].max_entry_price, 3) == 0.216


def test_cross_market_leg_failure_marks_basket_failed() -> None:
    btc = _snapshot("BTC", 0.20)
    eth = _snapshot("ETH", 0.21)
    relation_id = "btc-eth-exhaustive"
    core = CrossMarketAlphaCore(CrossMarketBotConfig(assets=["BTC", "ETH"], fee_rate=0.0))
    core.register_relation(
        relation_id,
        RelationType.EXHAUSTIVE_MUTUALLY_EXCLUSIVE,
        [btc.market.condition_id, eth.market.condition_id],
        [Side.UP, Side.UP],
    )
    assert core.evaluate_group(_group_view(relation_id, btc, eth))

    core.on_leg_failure(relation_id, btc.market.market_id, Side.UP)

    assert core._active_baskets[relation_id]["failed"] is True
    assert core._active_baskets[relation_id]["failed_leg"] == {"market_id": btc.market.market_id, "side": Side.UP}
