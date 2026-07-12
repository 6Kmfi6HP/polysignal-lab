"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Mapping, dataclasses, dataclasses.replace, datetime, datetime.datetime, datetime.timezone, types, types.SimpleNamespace, polysignal_lab.alpha.cross_market_core
Output: test_group_assembler_rejects_excessive_skew, test_group_assembler_rejects_equally_stale_views, test_group_assembler_rejects_missing_freshness, test_group_assembler_honors_per_call_age_limit, test_group_assembler_accepts_acceptable_skew, test_cross_market_pair_id_reaches_native_order_tags, test_cross_market_decisions_use_native_decision_pipeline, test_cross_market_leg_failure_marks_basket, test_cross_market_state_roundtrip, AllowAllPolicy
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

from polysignal_lab.alpha.cross_market_core import CrossMarketAlphaCore, RelationType
from polysignal_lab.alpha.types import (
    AlphaDecision,
    FreshnessView,
    MarketGroupView,
    MarketView,
    SideBookView,
)
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_runtime.decision_policy import (
    ApprovedDecision,
    DecisionPolicy,
    RejectedDecision,
    candidate_from_decision,
)
from polysignal_lab.nautilus_runtime.group_views import MarketGroupViewAssembler
from polysignal_lab.nautilus_runtime.native_order import submit_approved_decision
from polysignal_lab.nautilus_runtime.strategy.decision_pipeline import (
    DecisionPipeline,
    DecisionPipelineState,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _view(
    condition_id: str,
    asset: str = "BTC",
    timeframe: str = "5m",
    ask: float = 0.20,
    freshness_ms: int = 100,
) -> MarketView:
    now = datetime.now(timezone.utc)
    return MarketView(
        view_id=f"view-{condition_id}",
        market_id=f"market-{condition_id}",
        market_slug=f"{asset.lower()}-{condition_id}",
        condition_id=condition_id,
        asset=asset,
        timeframe=timeframe,
        start_ts=now,
        end_ts=now,
        created_at=now,
        seconds_to_close=120,
        up=SideBookView(
            token_id=f"{condition_id}-up",
            best_bid=None,
            best_ask=ask,
            spread=0.0,
            freshness_ms=freshness_ms,
            ask_levels=((ask, 100.0),),
        ),
        down=SideBookView(
            token_id=f"{condition_id}-down",
            best_bid=1.0 - ask,
            best_ask=1.0 - ask + 0.01,
            spread=0.01,
            freshness_ms=freshness_ms,
            ask_levels=((1.0 - ask + 0.01, 100.0),),
        ),
        spot=None,
        price_to_beat=100_000.0,
        up_trades=(),
        down_trades=(),
        metrics={},
        freshness=FreshnessView(
            up_book_ms=freshness_ms,
            down_book_ms=freshness_ms,
            spot_ms=None,
            max_ms=freshness_ms,
        ),
    )


_DEFAULT_CFG = SimpleNamespace(
    enabled=True,
    assets=["BTC", "ETH"],
    timeframes=["5m"],
    min_edge=0.01,
    max_leg_timeout_seconds=1.5,
    max_basket_notional=50.0,
    min_depth_shares=5,
    fee_rate=0.01,
)


def _core(relation_id: str = "btc-eth-rel") -> CrossMarketAlphaCore:
    core = CrossMarketAlphaCore(_DEFAULT_CFG)
    core.register_relation(
        relation_id,
        RelationType.EXHAUSTIVE_MUTUALLY_EXCLUSIVE,
        ["cond-btc", "cond-eth"],
        [Side.UP, Side.UP],
    )
    return core


def _group(
    relation_id: str = "btc-eth-rel",
    freshness_ms: int = 100,
) -> MarketGroupView:
    now = datetime.now(timezone.utc)
    return MarketGroupView(
        group_id="group-1",
        relation_id=relation_id,
        created_at=now,
        views_by_condition_id={
            "cond-btc": _view("cond-btc", "BTC", "5m", 0.20, freshness_ms),
            "cond-eth": _view("cond-eth", "ETH", "5m", 0.15, freshness_ms),
        },
        max_source_skew_ms=2000,
        metrics={},
    )


class AllowAllPolicy(DecisionPolicy):
    """Policy that approves every decision without gate/arbiter checks."""

    def decide(
        self, decision: AlphaDecision, view: MarketView
    ) -> ApprovedDecision:
        return ApprovedDecision(signal=candidate_from_decision(decision, view))


class _RecordingSink:
    def __init__(self, submitted: list[ApprovedDecision]) -> None:
        self.submitted = submitted

    def submit_order(
        self,
        approved: ApprovedDecision,
        *,
        view: MarketView,
    ) -> object:
        _ = view
        self.submitted.append(approved)
        return SimpleNamespace(order_id=f"order-{len(self.submitted)}")

    def remember_metrics(self, order: object, approved: ApprovedDecision) -> None:
        _ = order, approved

    def record_signal(self, signal: SignalCandidate) -> None:
        _ = signal

    def notify_accepted(self, signal: SignalCandidate) -> None:
        _ = signal

    def record_decision(self, decision: AlphaDecision, *, accepted: bool) -> None:
        _ = decision, accepted

    def record_rejected(self, rejected: RejectedDecision) -> None:
        _ = rejected

    def note_progress(self, event: str) -> None:
        _ = event


# ── MarketGroupViewAssembler tests ──────────────────────────────────────────


def test_group_assembler_rejects_excessive_skew() -> None:
    """Assembler must reject groups whose max freshness skew exceeds threshold."""
    assembler = MarketGroupViewAssembler(max_source_skew_ms=500)
    now = datetime.now(timezone.utc)
    group = assembler.assemble(
        relation_id="rel-1",
        views_by_condition_id={
            "a": _view("a", freshness_ms=100),
            "b": _view("b", freshness_ms=1000),
        },
        created_at=now,
        max_source_skew_ms=500,
    )
    assert group is None


def test_group_assembler_rejects_equally_stale_views() -> None:
    assembler = MarketGroupViewAssembler(
        max_source_skew_ms=5_000,
        max_view_age_ms=10_000,
    )
    now = datetime.now(timezone.utc)

    group = assembler.assemble(
        relation_id="rel-stale",
        views_by_condition_id={
            "a": _view("a", freshness_ms=120_000),
            "b": _view("b", freshness_ms=121_000),
        },
        created_at=now,
    )

    assert group is None


def test_group_assembler_rejects_missing_freshness() -> None:
    view = _view("b", freshness_ms=100)
    view_without_freshness = replace(
        view,
        freshness=replace(view.freshness, max_ms=None),
    )
    assembler = MarketGroupViewAssembler(max_view_age_ms=2_000)

    group = assembler.assemble(
        relation_id="rel-missing",
        views_by_condition_id={
            "a": _view("a", freshness_ms=100),
            "b": view_without_freshness,
        },
        created_at=datetime.now(timezone.utc),
    )

    assert group is None


def test_group_assembler_honors_per_call_age_limit() -> None:
    assembler = MarketGroupViewAssembler(max_view_age_ms=2_000)

    group = assembler.assemble(
        relation_id="rel-call-limit",
        views_by_condition_id={
            "a": _view("a", freshness_ms=200),
            "b": _view("b", freshness_ms=200),
        },
        created_at=datetime.now(timezone.utc),
        max_view_age_ms=100,
    )

    assert group is None


def test_group_assembler_accepts_acceptable_skew() -> None:
    assembler = MarketGroupViewAssembler(
        max_source_skew_ms=2_000,
        max_view_age_ms=2_000,
    )
    now = datetime.now(timezone.utc)
    group = assembler.assemble(
        relation_id="rel-1",
        views_by_condition_id={
            "a": _view("a", freshness_ms=100),
            "b": _view("b", freshness_ms=100),
        },
        created_at=now,
        max_source_skew_ms=2000,
    )
    assert group is not None
    assert isinstance(group, MarketGroupView)
    assert group.relation_id == "rel-1"


def test_cross_market_pair_id_reaches_native_order_tags() -> None:
    # Given
    group = _group()
    decision = _core().evaluate_group(group)[0]
    view = group.views_by_condition_id[decision.condition_id]
    approved = AllowAllPolicy().decide(decision, view)

    class RecordingOrderFactory:
        def limit(self, **kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(**kwargs)

    class RecordingStrategy:
        def __init__(self) -> None:
            self.order_factory = RecordingOrderFactory()
            self.submitted: list[SimpleNamespace] = []

        def submit_order(self, order: SimpleNamespace) -> None:
            self.submitted.append(order)

    strategy = RecordingStrategy()

    # When
    order = submit_approved_decision(
        strategy,
        approved,
        fixed_stake_usdc=10.0,
        best_ask=view.book_for(approved.signal.side).best_ask,
        instrument_id_resolver=lambda token_id: f"{token_id}.POLYMARKET",
    )

    # Then
    assert strategy.submitted == [order]
    assert "pair_id=btc-eth-rel" in order.tags


def test_cross_market_decisions_use_native_decision_pipeline() -> None:
    # Given
    group = _group()
    decisions = tuple(_core().evaluate_group(group))
    submitted: list[ApprovedDecision] = []
    state = DecisionPipelineState()
    pipeline = DecisionPipeline(
        AllowAllPolicy(),
        is_active_condition=lambda _condition_id: True,
    )
    sink = _RecordingSink(submitted)

    # When
    for decision in decisions:
        view = group.views_by_condition_id[decision.condition_id]
        pipeline.handle_decision(decision, view, state=state, sink=sink)

    # Then
    assert len(submitted) == len(decisions)
    assert len(state.submitted_orders) == len(decisions)


def test_cross_market_leg_failure_marks_basket() -> None:
    core = _core()
    core.on_leg_failure("btc-eth-rel", "cond-btc", Side.UP)
    basket = core._active_baskets.get("btc-eth-rel", {})
    assert basket.get("failed") is True


def test_cross_market_state_roundtrip() -> None:
    """Core state encodes basket state and decodes back."""
    from polysignal_lab.nautilus_bridge.state import decode_state, save_strategy_state

    core = _core()
    core._active_baskets["btc-eth-rel"] = {
        "fills": {"cond-btc": {"side": "UP", "price": 0.20, "shares": 10}},
        "markets": {"cond-btc", "cond-eth"},
        "failed": False,
    }
    raw = save_strategy_state("cross_market_bot", core)
    decoded = decode_state("cross_market_bot", raw)
    assert isinstance(decoded, Mapping)
    assert "_active_baskets" in decoded
