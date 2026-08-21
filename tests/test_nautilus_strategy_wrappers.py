from __future__ import annotations

from datetime import UTC, datetime

import pytest

from polysignal_lab.alpha.types import (
    AlphaDecision,
    FreshnessView,
    MarketView,
    OrderIntentSpec,
    SideBookView,
    SpotView,
)
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.decision_policy import (
    ApprovedDecision,
    BatchArbitrationResult,
    DecisionPolicy,
    RejectedDecision,
)
from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

DEFAULT_DATA_NAMES = (
    "order_book_deltas",
    "order_book_depth",
    "spot_prices",
    "price_to_beat",
)

REQUIRED_DATA_NAMES = set(DEFAULT_DATA_NAMES)


def _mark_condition_ready(strategy: object, condition_id: str) -> None:
    """Drive a condition into READY (feed subscription converged)."""
    from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
        begin_market_book_generation,
        observe_market_book_side,
    )

    now = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    begin_market_book_generation(
        strategy,  # pyright: ignore[reportArgumentType]
        condition_id,
        now=now,
    )
    observe_market_book_side(
        strategy,  # pyright: ignore[reportArgumentType]
        condition_id,
        Side.UP,
        received_at=now,
        book_at=now,
    )
    observe_market_book_side(
        strategy,  # pyright: ignore[reportArgumentType]
        condition_id,
        Side.DOWN,
        received_at=now,
        book_at=now,
    )


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

    def build(
        self,
        condition_id: str,
        *,
        created_at: datetime | None = None,
    ) -> MarketView | None:
        _ = created_at
        self.condition_ids.append(condition_id)
        return self.view


class FakeCore:
    def __init__(self, decisions: list[AlphaDecision]):
        self.decisions = decisions
        self.views: list[MarketView] = []
        self.state = {"seen": ["before"]}

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        self.views.append(view)
        return self.decisions

    def save_state(self):
        return self.state

    def load_state(self, payload):
        self.state = dict(payload)


class FakePolicy(DecisionPolicy):
    def __init__(self, approvals: list[bool] | None = None):
        super().__init__()
        self.approvals = approvals or [True]
        self.calls: list[tuple[AlphaDecision, MarketView]] = []

    def decide(self, decision: AlphaDecision, view: MarketView):
        self.calls.append((decision, view))
        approve = self.approvals[min(len(self.calls) - 1, len(self.approvals) - 1)]
        if approve:
            publish = _signal_from_decision(decision)
            return ApprovedDecision(decision=decision, publish=publish)
        return RejectedDecision(
            reason_code="TEST_REJECTED",
            detail={},
            decision=decision,
            publish=_signal_from_decision(decision),
        )

    def batch_arbitrate(
        self, decisions: list[tuple[AlphaDecision, MarketView]]
    ) -> BatchArbitrationResult:
        approvals: list[ApprovedDecision] = []
        rejections: list[tuple[AlphaDecision, RejectedDecision]] = []
        for decision, view in decisions:
            result = self.decide(decision, view)
            if isinstance(result, ApprovedDecision):
                approvals.append(result)
            else:
                rejections.append((decision, result))
        return BatchArbitrationResult(
            approvals=tuple(approvals),
            rejections=tuple(rejections),
        )

    def orderbook_readiness_threshold_ms(self) -> float:
        return 60_000.0

    def orderbook_trade_threshold_ms(self, strategy: str) -> float:
        _ = strategy
        return 60_000.0


def _attach_decision_policy(
    strategy: PolySignalNativeStrategy,
    policy: FakePolicy,
) -> DecisionPolicy:
    strategy.policy = policy
    strategy._decision_pipeline.policy = policy
    return strategy.policy


def _view() -> MarketView:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return MarketView(
        view_id="view-1",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        asset="BTC",
        timeframe="5m",
        start_ts=None,
        end_ts=None,
        created_at=now,
        seconds_to_close=60,
        spot=SpotView(
            asset="BTC",
            symbol="BTCUSDT",
            price=100_000.0,
            source="test",
            freshness_ms=10,
        ),
        up=SideBookView(
            token_id="up-token",
            best_bid=0.48,
            best_ask=0.50,
            spread=0.02,
            freshness_ms=20,
            ask_levels=(),
        ),
        down=SideBookView(
            token_id="down-token",
            best_bid=0.49,
            best_ask=0.51,
            spread=0.02,
            freshness_ms=20,
            ask_levels=(),
        ),
        price_to_beat=None,
        up_trades=(),
        down_trades=(),
        metrics={"market_is_active": True},
        freshness=FreshnessView(up_book_ms=20, down_book_ms=20, spot_ms=10, max_ms=20),
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
        data_names=DEFAULT_DATA_NAMES,
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
    submitted: list[object] = []

    class FakeOrderFactory:
        def limit(self, **kwargs):
            return kwargs

    strategy = PolySignalNativeStrategy(
        core=core,
        assembler=FakeAssembler(view),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        fixed_stake_usdc=10.0,
        registry=MarketCatalog(),
    )
    _policy = _attach_decision_policy(strategy, policy)

    class CapturingSubmitter:
        def submit(self, approved: ApprovedDecision, view: MarketView) -> object:
            _ = approved, view
            order = FakeOrderFactory().limit(instrument_id="up-token")
            submitted.append(order)
            return order

    strategy._decision_pipeline.submitter = CapturingSubmitter()
    _mark_condition_ready(strategy, "condition-btc-5m")
    strategy.evaluate_condition("condition-btc-5m")

    assert core.views == [view]
    assert [call[0] for call in policy.calls] == [approved, rejected]
    assert len(submitted) == 1
    assert submitted[0]["instrument_id"] == "up-token"
    assert len(strategy.rejected_decisions) == 1


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
