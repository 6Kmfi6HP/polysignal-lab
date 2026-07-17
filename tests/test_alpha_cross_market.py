"""
Input: __future__, __future__.annotations, datetime, datetime.datetime, datetime.timezone, polysignal_lab.alpha.cross_market_core
Output: test_cross_market_group_core_emits_expected_candidates, test_cross_market_group_walks_ask_depth_before_emitting, test_cross_market_leg_failure_marks_basket_failed
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""








from __future__ import annotations

from datetime import datetime, timezone

from polysignal_lab.alpha.cross_market_core import CrossMarketAlphaCore, RelationType
from polysignal_lab.alpha.types import MarketGroupView, MarketView
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.strategy_config import CrossMarketBotConfig
from alpha_equivalence import normalize_decision
from factories import sample_market_view


def _view(asset: str, ask: float, *, ask_levels: tuple[tuple[float, float], ...] | None = None) -> MarketView:
    return sample_market_view(
        asset=asset,
        up_ask=ask,
        down_ask=0.60,
        up_ask_levels=ask_levels,
    )


def _group_view(relation_id: str, *views: MarketView) -> MarketGroupView:
    return MarketGroupView(
        group_id="batch-1",
        relation_id=relation_id,
        created_at=datetime(2026, 6, 25, tzinfo=timezone.utc),
        views_by_condition_id={view.condition_id: view for view in views},
        max_source_skew_ms=10,
        metrics={},
    )


def test_cross_market_group_core_emits_expected_candidates() -> None:
    btc = _view("BTC", 0.20)
    eth = _view("ETH", 0.21)
    relation_id = "btc-eth-exhaustive"
    config = CrossMarketBotConfig(assets=["BTC", "ETH"], fee_rate=0.0, min_edge=0.01)
    core = CrossMarketAlphaCore(config)
    core.register_relation(
        relation_id,
        RelationType.EXHAUSTIVE_MUTUALLY_EXCLUSIVE,
        [btc.condition_id, eth.condition_id],
        [Side.UP, Side.UP],
    )

    decisions = core.evaluate_group(_group_view(relation_id, btc, eth))

    assert len(decisions) == 2
    assert all(normalize_decision(decision)["pair_id"] == relation_id for decision in decisions)


def test_cross_market_group_walks_ask_depth_before_emitting() -> None:
    relation_id = "btc-eth-depth"
    config = CrossMarketBotConfig(assets=["BTC", "ETH"], fee_rate=0.0, min_edge=0.01, min_depth_shares=5)
    core = CrossMarketAlphaCore(config)

    shallow = _view("BTC", 0.20, ask_levels=((0.20, 1.0),))
    eth = _view("ETH", 0.20, ask_levels=((0.20, 5.0),))
    core.register_relation(
        relation_id,
        RelationType.EXHAUSTIVE_MUTUALLY_EXCLUSIVE,
        [shallow.condition_id, eth.condition_id],
        [Side.UP, Side.UP],
    )
    assert core.evaluate_group(_group_view(relation_id, shallow, eth)) == []

    btc = _view("BTC", 0.20, ask_levels=((0.20, 1.0), (0.22, 4.0)))
    core = CrossMarketAlphaCore(config)
    core.register_relation(
        relation_id,
        RelationType.EXHAUSTIVE_MUTUALLY_EXCLUSIVE,
        [btc.condition_id, eth.condition_id],
        [Side.UP, Side.UP],
    )
    decisions = core.evaluate_group(_group_view(relation_id, btc, eth))

    assert decisions
    assert round(decisions[0].max_entry_price, 3) == 0.216


def test_cross_market_workflow_is_expressed_only_by_pair_id() -> None:
    btc = _view("BTC", 0.20)
    eth = _view("ETH", 0.21)
    relation_id = "btc-eth-exhaustive"
    core = CrossMarketAlphaCore(CrossMarketBotConfig(assets=["BTC", "ETH"], fee_rate=0.0))
    core.register_relation(
        relation_id,
        RelationType.EXHAUSTIVE_MUTUALLY_EXCLUSIVE,
        [btc.condition_id, eth.condition_id],
        [Side.UP, Side.UP],
    )
    decisions = core.evaluate_group(_group_view(relation_id, btc, eth))

    assert decisions
    assert {decision.order_intent.pair_id for decision in decisions} == {relation_id}
    assert not hasattr(core, "_active_baskets")
