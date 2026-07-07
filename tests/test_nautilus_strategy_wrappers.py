"""
Input: __future__, __future__.annotations, dataclasses, dataclasses.dataclass, dataclasses.replace, datetime, datetime.UTC, datetime.datetime, pytest, polysignal_lab.alpha.types
Output: test_each_wrapper_constructs_without_nautilus_and_subscribes_required_data, test_each_wrapper_preserves_custom_data_names, test_evaluate_condition_uses_assembler_core_policy_and_submits_only_approved, test_approved_decision_binds_and_accepts_before_submit, test_approved_fok_with_unknown_depth_rolls_back_before_accepting, test_locally_accepted_order_event_does_not_double_apply_core_acceptance, test_submitted_exchange_alias_prevents_duplicate_core_acceptance, test_policy_rejected_decision_rolls_back_bound_transient_state, test_candidate_less_policy_rejection_rolls_back_transient_state, test_stateful_core_round_trips_through_shared_state_codec
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime

import pytest

from polysignal_lab.alpha.types import (
    AlphaDecision,
    AlphaFillEvent,
    FreshnessView,
    MarketView,
    OrderIntentSpec,
    SideBookView,
    SpotView,
)
from polysignal_lab.alpha.vwap_momentum_core import VWAPMomentumAlphaCore
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.decision_policy import (
    ApprovedDecision,
    RejectedDecision,
)
from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy
from polysignal_lab.nautilus_runtime.strategies.base import DEFAULT_DATA_NAMES as COMPAT_DATA_NAMES
from polysignal_lab.strategies.config import VWAPMomentumConfig


REQUIRED_DATA_NAMES = {
    "order_book_deltas",
    "order_book_depth",
    "spot_prices",
    "price_to_beat",
}


WRAPPERS = [
    "ptb_diff",
    "skew_mean_reversion",
    "binary_momentum",
    "fibonacci_bot",
    "one_cent_buy",
    "ninety_nine_cent_sniper",
    "late_consensus",
    "vwap_momentum",
    "dump_hedge",
    "mid_price_sizing",
    "pre_order_market",
    "low_side_dual_reversion",
]


class FakeAssembler:
    def __init__(self, view: MarketView | None):
        self.view = view
        self.condition_ids: list[str] = []

    def build(self, condition_id: str) -> MarketView | None:
        self.condition_ids.append(condition_id)
        return self.view


class FakeCore:
    def __init__(self, decisions: list[AlphaDecision]):
        self.decisions = decisions
        self.views: list[MarketView] = []
        self.rejections = 0
        self.rejected_events = []
        self.fills: list[AlphaFillEvent] = []
        self.fill_notifications = []
        self.fill_lifecycle: list[str] = []
        self.state = {"seen": ["before"]}
        self.fill_returns: list[AlphaDecision] = []

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        self.views.append(view)
        return self.decisions

    def on_order_rejected(self, _event) -> None:
        self.rejections += 1

    def on_notify_fill(self, market_id: str, side: Side, shares: float) -> None:
        self.fill_lifecycle.append("notify")
        self.fill_notifications.append((market_id, side, shares))

    def on_order_filled(self, event: AlphaFillEvent) -> list[AlphaDecision]:
        self.fill_lifecycle.append("filled")
        self.fills.append(event)
        return self.fill_returns

    def save_state(self):
        return self.state

    def load_state(self, payload):
        self.state = dict(payload)


class ControlledVWAPCore(VWAPMomentumAlphaCore):
    def __init__(self, decisions: list[AlphaDecision]):
        super().__init__(VWAPMomentumConfig(hedge_enabled=True))
        self.decisions = decisions
        self.views: list[MarketView] = []
        self.fills: list[AlphaFillEvent] = []
        self.fill_notifications: list[tuple[str, Side, float]] = []

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        self.views.append(view)
        return self.decisions

    def on_notify_fill(self, market_id: str, side: Side, shares: float) -> None:
        self.fill_notifications.append((market_id, side, shares))
        super().on_notify_fill(market_id, side, shares)

    def on_order_filled(self, event: AlphaFillEvent) -> list[AlphaDecision]:
        self.fills.append(event)
        return super().on_order_filled(event)


class RollbackCore(FakeCore):
    def __init__(self, decisions: list[AlphaDecision]):
        super().__init__(decisions)
        self.transient_markers: dict[str, str] = {}
        self.bind_calls: list[tuple[str, str]] = []
        self.accepted_events = []
        self.lifecycle: list[tuple[str, str]] = []

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        decisions = super().evaluate(view)
        for decision in decisions:
            self.transient_markers[decision.market_id] = "pending"
        return decisions

    def bind_signal(self, market_id: str, signal_id: str) -> None:
        self.bind_calls.append((market_id, signal_id))
        self.lifecycle.append(("bind", signal_id))

    def on_order_accepted(self, event) -> None:
        self.accepted_events.append(event)
        self.lifecycle.append(("accepted", event.order_id))
        self.transient_markers.pop(event.market_id, None)

    def on_order_rejected(self, event) -> None:
        self.rejected_events.append(event)
        self.lifecycle.append(("rejected", event.order_id))
        self.transient_markers.pop(event.market_id, None)


class FakePolicy:
    def __init__(self, approvals: list[bool] | None = None):
        self.approvals = approvals or [True]
        self.calls: list[tuple[AlphaDecision, MarketView]] = []

    def decide(self, decision: AlphaDecision, view: MarketView):
        self.calls.append((decision, view))
        approve = self.approvals[min(len(self.calls) - 1, len(self.approvals) - 1)]
        if approve:
            return ApprovedDecision(signal=_signal_from_decision(decision))
        return RejectedDecision(
            reason_code="TEST_REJECTED",
            detail={},
            candidate=_signal_from_decision(decision),
        )


class FakeSubmitter:
    def __init__(self):
        self.specs = []

    def __call__(self, spec):
        self.specs.append(spec)
        return "submitted"


@dataclass(frozen=True)
class FakeFill:
    order_id: str = "order-1"
    client_order_id: str = "client-1"
    market_id: str = "btc-5m"
    condition_id: str = "condition-btc-5m"
    token_id: str = "up-token"
    side: Side = Side.UP
    reason: str | None = None
    price: float = 0.49
    quantity: float = 3.0
    liquidity_side: str = "TAKER"
    ts_event: datetime = datetime(2026, 1, 1, tzinfo=UTC)
    metrics: dict[str, object] | None = None
    tags: dict[str, str] | None = None


def _view() -> MarketView:
    return MarketView(
        view_id="view-1",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        asset="BTC",
        timeframe="5m",
        start_ts=None,
        end_ts=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        seconds_to_close=60,
        up=SideBookView(
            token_id="up-token",
            best_bid=0.48,
            best_ask=0.50,
            spread=0.02,
            freshness_ms=10,
        ),
        down=SideBookView(
            token_id="down-token",
            best_bid=0.49,
            best_ask=0.51,
            spread=0.02,
            freshness_ms=10,
        ),
        spot=SpotView(
            asset="BTC",
            symbol="BTC/USD",
            price=100_000.0,
            source="test",
            freshness_ms=10,
        ),
        price_to_beat=100_100.0,
        up_trades=(),
        down_trades=(),
        metrics={},
        freshness=FreshnessView(up_book_ms=10, down_book_ms=10, spot_ms=10, max_ms=10),
    )


def _decision(
    *,
    side: Side = Side.UP,
    hedge_leg: bool = False,
    order_intent: OrderIntentSpec | None = None,
) -> AlphaDecision:
    return AlphaDecision(
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        token_id="up-token" if side == Side.UP else "down-token",
        side=side,
        confidence=0.8,
        entry_reference_price=0.48,
        max_entry_price=0.50 if side == Side.UP else 0.51,
        seconds_to_close=60,
        data_freshness_ms=20,
        reason_codes=("TEST",),
        metrics={},
        order_intent=order_intent,
        hedge_leg=hedge_leg,
    )


def _signal_from_decision(decision: AlphaDecision) -> SignalCandidate:
    return SignalCandidate.build(
        strategy=decision.strategy,
        asset=decision.asset,
        timeframe=decision.timeframe,
        market_id=decision.market_id,
        market_slug=decision.market_slug,
        condition_id=decision.condition_id,
        token_id=decision.token_id,
        side=decision.side,
        confidence=decision.confidence,
        entry_reference_price=decision.entry_reference_price,
        max_entry_price=decision.max_entry_price,
        seconds_to_close=decision.seconds_to_close,
        data_freshness_ms=decision.data_freshness_ms,
        reason_codes=list(decision.reason_codes),
        metrics=dict(decision.metrics),
        order_intent=decision.order_intent.intent if decision.order_intent else None,
        expiry_seconds=decision.order_intent.expiry_seconds
        if decision.order_intent
        else None,
        pair_id=decision.order_intent.pair_id if decision.order_intent else None,
        hedge_leg=decision.hedge_leg,
    )


@pytest.mark.parametrize("strategy_name", WRAPPERS)
def test_each_wrapper_constructs_without_nautilus_and_subscribes_required_data(
    strategy_name: str,
) -> None:
    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=FakeAssembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name=strategy_name,
        data_names=COMPAT_DATA_NAMES,
        registry=MarketCatalog(),
    )

    assert REQUIRED_DATA_NAMES.issubset(set(strategy.data_names))


@pytest.mark.parametrize("strategy_name", WRAPPERS)
def test_each_wrapper_preserves_custom_data_names(strategy_name: str) -> None:
    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=FakeAssembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name=strategy_name,
        data_names=("custom_feed",),
        registry=MarketCatalog(),
    )

    assert strategy.data_names == ("custom_feed",)


def test_evaluate_condition_uses_assembler_core_policy_and_submits_only_approved() -> (
    None
):
    view = _view()
    approved = _decision(side=Side.UP)
    rejected = _decision(side=Side.DOWN)
    core = FakeCore([approved, rejected])
    policy = FakePolicy([True, False])

    class FakeOrderFactory:
        def limit(self, **kwargs):
            return kwargs

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.order_factory = FakeOrderFactory()
            self.submitted = []

        def submit_order(self, order):
            self.submitted.append(order)

    strategy = FakeNativeStrategy(
        core=core,
        assembler=FakeAssembler(view),
        policy=policy,
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        fixed_stake_usdc=10.0,
        registry=MarketCatalog(),
    )

    strategy.evaluate_condition("condition-btc-5m")

    assert core.views == [view]
    assert [call[0] for call in policy.calls] == [approved, rejected]
    assert len(strategy.submitted) == 1
    assert strategy.submitted[0]["instrument_id"] == "up-token"
    assert len(strategy.rejected_decisions) == 1


@pytest.mark.skip(reason="compat wrapper lifecycle — removed with CompatPolySignalNautilusStrategy")
def test_approved_decision_binds_and_accepts_before_submit() -> None:
    view = _view()
    decision = _decision()
    core = RollbackCore([decision])
    policy = FakePolicy([True])
    submitted = []

    def submitter(spec):
        core.lifecycle.append(("submit", spec.instrument_id))
        submitted.append(spec)

    strategy = PolySignalNautilusStrategy(
        core=core,
        assembler=FakeAssembler(view),
        policy=policy,
        submitter=submitter,
        condition_ids=("condition-btc-5m",),
        strategy_name="vwap_momentum",
        fixed_stake_usdc=10.0,
    )

    result = strategy.evaluate_condition("condition-btc-5m")

    assert len(core.accepted_events) == 1
    accepted = core.accepted_events[0]
    signal_id = accepted.order_id
    assert core.bind_calls == [(decision.market_id, signal_id)]
    assert core.lifecycle == [
        ("bind", signal_id),
        ("accepted", signal_id),
        ("submit", "up-token"),
    ]
    assert accepted.market_id == decision.market_id
    assert accepted.condition_id == view.condition_id
    assert accepted.token_id == decision.token_id
    assert accepted.side == decision.side
    assert accepted.client_order_id == signal_id
    assert accepted.reason is None
    assert accepted.ts_event == view.created_at
    assert core.transient_markers == {}
    assert result == submitted


@pytest.mark.skip(reason="compat wrapper lifecycle — removed with CompatPolySignalNautilusStrategy; ORDER_MAPPING_FAILED covered by test_native_strategy_records_rejection_when_order_mapping_fails")
def test_approved_fok_with_unknown_depth_rolls_back_before_accepting() -> None:
    view = replace(_view(), up=replace(_view().up, best_ask=None))
    decision = _decision(order_intent=OrderIntentSpec(OrderIntent.TAKER_FOK))
    core = RollbackCore([decision])
    policy = FakePolicy([True])

    class FakeOrderFactory:
        def limit(self, **kwargs):
            return kwargs

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.order_factory = FakeOrderFactory()

        def submit_order(self, order):
            pass

    strategy = FakeNativeStrategy(
        core=core,
        assembler=FakeAssembler(view),
        policy=policy,
        condition_ids=("condition-btc-5m",),
        strategy_name="vwap_momentum",
        fixed_stake_usdc=10.0,
        registry=MarketCatalog(),
    )

    strategy.evaluate_condition("condition-btc-5m")

    assert len(strategy.rejected_decisions) == 1
    assert strategy.rejected_decisions[0].reason_code == "ORDER_MAPPING_FAILED"


@pytest.mark.skip(reason="compat wrapper lifecycle — removed with CompatPolySignalNautilusStrategy")
def test_locally_accepted_order_event_does_not_double_apply_core_acceptance() -> None:
    view = _view()
    decision = _decision()
    core = RollbackCore([decision])
    policy = FakePolicy([True])
    strategy = PolySignalNautilusStrategy(
        core=core,
        assembler=FakeAssembler(view),
        policy=policy,
        submitter=FakeSubmitter(),
        condition_ids=("condition-btc-5m",),
        strategy_name="vwap_momentum",
        fixed_stake_usdc=10.0,
    )

    strategy.evaluate_condition("condition-btc-5m")
    accepted_id = core.accepted_events[0].order_id
    strategy.on_order_accepted(
        replace(FakeFill(), order_id=accepted_id, client_order_id="exchange-client")
    )
    strategy.on_order_accepted(
        replace(FakeFill(), order_id="exchange-order", client_order_id=accepted_id)
    )
    strategy.on_order_accepted(
        replace(
            FakeFill(),
            order_id="exchange-order-2",
            client_order_id="exchange-client-2",
            tags={"signal_id": accepted_id},
        )
    )

    assert [event.order_id for event in core.accepted_events] == [accepted_id]


@pytest.mark.skip(reason="compat wrapper lifecycle — removed with CompatPolySignalNautilusStrategy")
def test_submitted_exchange_alias_prevents_duplicate_core_acceptance() -> None:
    view = _view()
    decision = _decision()
    core = RollbackCore([decision])
    strategy = PolySignalNautilusStrategy(
        core=core,
        assembler=FakeAssembler(view),
        policy=FakePolicy([True]),
        submitter=FakeSubmitter(),
        condition_ids=("condition-btc-5m",),
        strategy_name="vwap_momentum",
        fixed_stake_usdc=10.0,
    )

    strategy.evaluate_condition("condition-btc-5m")
    signal_id = core.accepted_events[0].order_id
    strategy.on_order_submitted(
        replace(
            FakeFill(),
            order_id="exchange-order",
            client_order_id="exchange-client",
            tags={"signal_id": signal_id},
        )
    )
    strategy.on_order_accepted(
        replace(
            FakeFill(),
            order_id="exchange-order",
            client_order_id="exchange-client",
            tags=None,
        )
    )

    assert [event.order_id for event in core.accepted_events] == [signal_id]


@pytest.mark.skip(reason="compat wrapper lifecycle — removed with CompatPolySignalNautilusStrategy")
def test_policy_rejected_decision_rolls_back_bound_transient_state() -> None:
    view = _view()
    decision = _decision()
    core = RollbackCore([decision])
    policy = FakePolicy([False])
    strategy = PolySignalNautilusStrategy(
        core=core,
        assembler=FakeAssembler(view),
        policy=policy,
        submitter=FakeSubmitter(),
        condition_ids=("condition-btc-5m",),
        strategy_name="vwap_momentum",
        fixed_stake_usdc=10.0,
    )

    result = strategy.evaluate_condition("condition-btc-5m")

    rejected = strategy.rejected_decisions[0]
    assert result == []
    assert rejected.candidate is not None
    assert core.bind_calls == [(decision.market_id, rejected.candidate.signal_id)]
    assert core.transient_markers == {}
    assert len(core.rejected_events) == 1
    event = core.rejected_events[0]
    assert event.market_id == decision.market_id
    assert event.condition_id == view.condition_id
    assert event.token_id == decision.token_id
    assert event.side == decision.side
    assert event.order_id == rejected.candidate.signal_id
    assert event.reason == "TEST_REJECTED"
    assert event.ts_event == view.created_at


@pytest.mark.skip(reason="compat wrapper lifecycle — removed with CompatPolySignalNautilusStrategy")
def test_candidate_less_policy_rejection_rolls_back_transient_state() -> None:
    view = _view()
    decision = _decision()
    core = RollbackCore([decision])

    class CandidateLessRejectPolicy:
        def decide(self, decision: AlphaDecision, view: MarketView):
            return RejectedDecision(
                reason_code="manual_disabled", detail={}, candidate=None
            )

    strategy = PolySignalNautilusStrategy(
        core=core,
        assembler=FakeAssembler(view),
        policy=CandidateLessRejectPolicy(),
        submitter=FakeSubmitter(),
        condition_ids=("condition-btc-5m",),
        strategy_name="vwap_momentum",
        fixed_stake_usdc=10.0,
    )

    result = strategy.evaluate_condition("condition-btc-5m")

    rollback_id = f"policy_rejected:{decision.strategy}:{decision.market_id}:0"
    assert result == []
    assert strategy.rejected_decisions == [
        RejectedDecision(reason_code="manual_disabled", detail={}, candidate=None)
    ]
    assert core.bind_calls == [(decision.market_id, rollback_id)]
    assert core.transient_markers == {}
    assert len(core.rejected_events) == 1
    event = core.rejected_events[0]
    assert event.market_id == decision.market_id
    assert event.condition_id == view.condition_id
    assert event.token_id == decision.token_id
    assert event.side == decision.side
    assert event.order_id == rollback_id
    assert event.reason == "manual_disabled"
    assert event.ts_event == view.created_at


def test_stateful_core_round_trips_through_shared_state_codec() -> None:
    core = FakeCore([])
    strategy = PolySignalNativeStrategy(
        core=core,
        assembler=FakeAssembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        registry=MarketCatalog(),
    )

    state = strategy.on_save()
    restored_core = FakeCore([])
    restored = PolySignalNativeStrategy(
        core=restored_core,
        assembler=FakeAssembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        registry=MarketCatalog(),
    )

    restored.on_load(state)

    assert restored_core.state == {"seen": ["before"]}


@pytest.mark.skip(reason="compat wrapper lifecycle — removed with CompatPolySignalNautilusStrategy")
def test_fill_callback_routes_vwap_hedge_decisions_through_policy_and_submitter() -> (
    None
):
    view = _view()
    core = FakeCore([])
    core.fill_returns = [_decision(side=Side.DOWN, hedge_leg=True)]
    policy = FakePolicy([True])
    submitter = FakeSubmitter()
    strategy = PolySignalNautilusStrategy(
        core=core,
        assembler=FakeAssembler(view),
        policy=policy,
        submitter=submitter,
        condition_ids=("condition-btc-5m",),
        strategy_name="vwap_momentum",
        fixed_stake_usdc=10.0,
    )

    strategy.on_order_filled(FakeFill())

    assert core.fill_lifecycle == ["notify", "filled"]
    assert core.fill_notifications == [("btc-5m", Side.UP, 3.0)]
    assert len(core.fills) == 1
    assert len(policy.calls) == 1
    assert len(submitter.specs) == 1
    assert submitter.specs[0].hedge_leg is True
    assert not hasattr(strategy, "_follow_up_signals")

@pytest.mark.skip(reason="compat wrapper lifecycle — removed with CompatPolySignalNautilusStrategy")
def test_non_vwap_gtd_hedge_fill_reaches_core_fill_handler() -> None:
    core = FakeCore([])
    strategy = PolySignalNautilusStrategy(
        core=core,
        assembler=FakeAssembler(_view()),
        policy=FakePolicy([True]),
        submitter=FakeSubmitter(),
        condition_ids=("condition-btc-5m",),
        strategy_name="low_side_dual_reversion",
        fixed_stake_usdc=10.0,
    )

    submitted = strategy.on_order_filled(
        replace(
            FakeFill(),
            metrics={"hedge_leg": True, "order_intent": OrderIntent.PASSIVE_GTD.value},
        )
    )

    assert "filled" in core.fill_lifecycle
    assert len(core.fills) == 1


@pytest.mark.skip(reason="compat wrapper lifecycle — removed with CompatPolySignalNautilusStrategy")
def test_vwap_gtd_hedge_fill_skips_notify_but_reaches_fill_handler() -> None:
    core = FakeCore([])
    core.fill_returns = [_decision(side=Side.DOWN, hedge_leg=True)]
    strategy = PolySignalNautilusStrategy(
        core=core,
        assembler=FakeAssembler(_view()),
        policy=FakePolicy([True]),
        submitter=FakeSubmitter(),
        condition_ids=("condition-btc-5m",),
        strategy_name="vwap_momentum",
        fixed_stake_usdc=10.0,
    )

    submitted = strategy.on_order_filled(
        replace(
            FakeFill(),
            metrics={"hedge_leg": True, "order_intent": OrderIntent.PASSIVE_GTD.value},
        )
    )

    assert submitted == []
    assert core.fill_lifecycle == ["filled"]
    assert core.fill_notifications == []


@pytest.mark.skip(reason="compat wrapper lifecycle — removed with CompatPolySignalNautilusStrategy")
def test_fill_callback_reattaches_approved_vwap_metrics_for_hedges() -> None:
    view = _view()
    vwap_decision = replace(
        _decision(),
        strategy="vwap_momentum",
        confidence=0.25,
        metrics={
            "opposite_token_id": "down-token",
            "condition_id": "condition-btc-5m",
            "seconds_to_close": 60,
        },
    )
    core = ControlledVWAPCore([vwap_decision])
    policy = FakePolicy([True])
    submitter = FakeSubmitter()
    strategy = PolySignalNautilusStrategy(
        core=core,
        assembler=FakeAssembler(view),
        policy=policy,
        submitter=submitter,
        condition_ids=("condition-btc-5m",),
        strategy_name="vwap_momentum",
        fixed_stake_usdc=10.0,
    )

    strategy.evaluate_condition("condition-btc-5m")
    signal_id = next(iter(strategy._locally_accepted_order_ids))
    assert submitter.specs[0].tags["signal_id"] == signal_id

    strategy.on_order_filled(
        replace(FakeFill(), order_id=signal_id, client_order_id="exchange-client")
    )

    assert len(submitter.specs) == 2
    hedge_decision = policy.calls[-1][0]
    assert hedge_decision.hedge_leg is True
    assert hedge_decision.token_id == "down-token"
    assert hedge_decision.condition_id == "condition-btc-5m"
    assert core.fills[-1].metrics["asset"] == "BTC"
    assert core.fills[-1].metrics["market_slug"] == "btc-updown-5m"
    assert core.fills[-1].metrics["signal_confidence"] == 0.25

    core.decisions = [replace(vwap_decision, confidence=0.31)]
    accepted_before = set(strategy._locally_accepted_order_ids)
    strategy.evaluate_condition("condition-btc-5m")
    override_signal_id = next(
        iter(set(strategy._locally_accepted_order_ids) - accepted_before)
    )

    strategy.on_order_filled(
        replace(
            FakeFill(),
            order_id=override_signal_id,
            client_order_id="exchange-client-2",
            metrics={"signal_confidence": 0.93},
        )
    )

    assert policy.calls[-1][0].confidence == 0.93
    assert core.fills[-1].metrics["signal_confidence"] == 0.93


@pytest.mark.skip(reason="compat wrapper lifecycle — removed with CompatPolySignalNautilusStrategy")
def test_stored_vwap_hedge_fill_does_not_stage_reverse_hedge() -> None:
    view = _view()
    vwap_decision = replace(
        _decision(),
        strategy="vwap_momentum",
        metrics={
            "opposite_token_id": "down-token",
            "condition_id": "condition-btc-5m",
            "seconds_to_close": 60,
        },
    )
    core = ControlledVWAPCore([vwap_decision])
    policy = FakePolicy([True])
    submitter = FakeSubmitter()
    strategy = PolySignalNautilusStrategy(
        core=core,
        assembler=FakeAssembler(view),
        policy=policy,
        submitter=submitter,
        condition_ids=("condition-btc-5m",),
        strategy_name="vwap_momentum",
        fixed_stake_usdc=10.0,
    )

    strategy.evaluate_condition("condition-btc-5m")
    entry_signal_id = submitter.specs[0].tags["signal_id"]
    strategy.on_order_filled(
        replace(FakeFill(), order_id=entry_signal_id, client_order_id="exchange-client")
    )
    hedge_signal_id = submitter.specs[1].tags["signal_id"]

    submitted = strategy.on_order_filled(
        replace(
            FakeFill(),
            order_id=hedge_signal_id,
            client_order_id="hedge-client",
            side=Side.DOWN,
            token_id="down-token",
            quantity=3.0,
        )
    )

    assert submitted == []
    assert len(submitter.specs) == 2
    assert core.fill_notifications == [("btc-5m", Side.UP, 3.0)]


@pytest.mark.skip(reason="compat wrapper lifecycle — removed with CompatPolySignalNautilusStrategy")
def test_approved_decision_with_consensus_submits_without_second_core_acceptance() -> (
    None
):
    view = _view()
    decision = _decision()
    consensus = _signal_from_decision(_decision(side=Side.DOWN))
    core = RollbackCore([decision])
    submitter = FakeSubmitter()

    class ConsensusPolicy:
        def decide(self, policy_decision: AlphaDecision, policy_view: MarketView):
            return ApprovedDecision(
                signal=_signal_from_decision(policy_decision), consensus=consensus
            )

    strategy = PolySignalNautilusStrategy(
        core=core,
        assembler=FakeAssembler(view),
        policy=ConsensusPolicy(),
        submitter=submitter,
        condition_ids=("condition-btc-5m",),
        strategy_name="vwap_momentum",
        fixed_stake_usdc=10.0,
    )

    result = strategy.evaluate_condition("condition-btc-5m")

    assert result == submitter.specs
    assert [spec.instrument_id for spec in submitter.specs] == [
        "up-token",
        "down-token",
    ]
    assert len(core.accepted_events) == 1
    assert core.bind_calls == [
        (decision.market_id, submitter.specs[0].tags["signal_id"])
    ]
    assert core.lifecycle == [
        ("bind", submitter.specs[0].tags["signal_id"]),
        ("accepted", submitter.specs[0].tags["signal_id"]),
    ]


@pytest.mark.skip(reason="compat wrapper lifecycle — removed with CompatPolySignalNautilusStrategy")
def test_consensus_submitted_alias_fill_skips_source_core_lifecycle() -> None:
    view = _view()
    decision = _decision()
    consensus = _signal_from_decision(
        replace(_decision(side=Side.DOWN), strategy="consensus")
    )
    core = FakeCore([decision])
    submitter = FakeSubmitter()

    class ConsensusPolicy:
        def decide(self, policy_decision: AlphaDecision, policy_view: MarketView):
            return ApprovedDecision(
                signal=_signal_from_decision(policy_decision), consensus=consensus
            )

    strategy = PolySignalNautilusStrategy(
        core=core,
        assembler=FakeAssembler(view),
        policy=ConsensusPolicy(),
        submitter=submitter,
        condition_ids=("condition-btc-5m",),
        strategy_name="vwap_momentum",
        fixed_stake_usdc=10.0,
    )

    strategy.evaluate_condition("condition-btc-5m")
    consensus_signal_id = submitter.specs[1].tags["signal_id"]
    assert submitter.specs[1].tags["strategy"] == "consensus"
    strategy.on_order_submitted(
        replace(
            FakeFill(),
            order_id="exchange-consensus",
            client_order_id="exchange-consensus-client",
            tags={"signal_id": consensus_signal_id, "strategy": "consensus"},
        )
    )

    submitted = strategy.on_order_filled(
        replace(
            FakeFill(),
            order_id="exchange-consensus",
            client_order_id="exchange-consensus-client",
            side=Side.DOWN,
            token_id="down-token",
        )
    )

    assert submitted == []
    assert core.fill_lifecycle == []
    assert core.fill_notifications == []
    assert core.fills == []
