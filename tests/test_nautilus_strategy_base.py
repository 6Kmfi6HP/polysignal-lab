from __future__ import annotations

from datetime import UTC, datetime

from polysignal_lab.alpha.types import AlphaDecision, MarketView, OrderIntentSpec
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.nautilus_bridge.state import state_key
from polysignal_lab.nautilus_bridge.strategy_base import PolySignalNautilusStrategy, is_nautilus_available
from polysignal_lab.nautilus_bridge.strategies.ptb_diff import PTBDiffNautilusStrategy
from polysignal_lab.strategies.config import PTBDiffConfig, PTBTriggerConfig


class FakeAssembler:
    def __init__(self, view: MarketView | None):
        self.view = view

    def build(self, condition_id: str) -> MarketView | None:
        return self.view


class FakeCore:
    def __init__(self, decisions: list[AlphaDecision]):
        self.decisions = decisions

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        return self.decisions


def _decision() -> AlphaDecision:
    return AlphaDecision(
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        token_id="up-token",
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.82,
        max_entry_price=0.92,
        seconds_to_close=60,
        data_freshness_ms=20,
        reason_codes=("PTB_DIFF_THRESHOLD_OK",),
        metrics={"diff_usd": 120.0},
        order_intent=OrderIntentSpec(intent=OrderIntent.PASSIVE_GTD, expiry_seconds=45, pair_id="pair-1"),
        hedge_leg=False,
    )


def test_strategy_base_imports_without_nautilus_installed() -> None:
    assert isinstance(is_nautilus_available(), bool)


def test_strategy_base_returns_no_intents_when_view_not_ready() -> None:
    strategy = PolySignalNautilusStrategy(
        core=FakeCore([_decision()]),
        assembler=FakeAssembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
    )

    assert strategy.evaluate_condition("condition-btc-5m") == []
    assert strategy.submitted_intents == []


def test_strategy_base_records_decision_order_intents() -> None:
    strategy = PolySignalNautilusStrategy(
        core=FakeCore([_decision()]),
        assembler=FakeAssembler(object()),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
    )

    intents = strategy.evaluate_condition("condition-btc-5m")

    assert intents == [OrderIntentSpec(intent=OrderIntent.PASSIVE_GTD, expiry_seconds=45, pair_id="pair-1")]
    assert strategy.submitted_intents == intents


def test_strategy_base_save_load_uses_versioned_bytes() -> None:
    strategy = PolySignalNautilusStrategy(
        core=FakeCore([]),
        assembler=FakeAssembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
    )
    strategy.accepted_state["condition-btc-5m"] = "accepted"

    state = strategy.on_save()
    restored = PolySignalNautilusStrategy(
        core=FakeCore([]),
        assembler=FakeAssembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
    )
    restored.on_load(state)

    assert set(state) == {state_key("ptb_diff")}
    assert restored.accepted_state == {"condition-btc-5m": "accepted"}


def test_ptb_nautilus_strategy_constructs_with_core_without_nautilus_dependency() -> None:
    config = PTBDiffConfig(
        triggers=[
            PTBTriggerConfig(
                name="test_up",
                side=Side.UP,
                min_diff_usd=80.0,
                max_token_price=0.92,
                min_token_price=0.80,
                min_seconds_to_close=0,
                max_seconds_to_close=120,
            )
        ]
    )

    strategy = PTBDiffNautilusStrategy(config=config, assembler=FakeAssembler(None), condition_ids=("condition-btc-5m",))

    assert strategy.strategy_name == "ptb_diff"


# ── Batch evaluation tests (nautilus runtime) ─────────────────────────────────


from polysignal_lab.nautilus_runtime.execution import PaperExecutionResult
from polysignal_lab.nautilus_runtime.strategies.base import PolySignalNautilusStrategy as RuntimeStrategy
from polysignal_lab.domain.enums import OrderStatus


class _MockBook:
    best_ask: float | None = None
    ask_levels: tuple = ()


class _MockView:
    condition_id: str = "condition-btc-5m"

    def book_for(self, side):
        return _MockBook()

    @property
    def created_at(self):
        from datetime import datetime, timezone
        return datetime.now(timezone.utc)


class RuntimeFakePolicy:
    def evaluate(self, decision, view):
        from polysignal_lab.nautilus_runtime.decision_policy import ApprovedDecision
        from polysignal_lab.domain.signal import SignalCandidate
        candidate = SignalCandidate.build(
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
            expiry_seconds=decision.order_intent.expiry_seconds if decision.order_intent else None,
            pair_id=decision.order_intent.pair_id if decision.order_intent else None,
            hedge_leg=decision.hedge_leg,
        )
        return ApprovedDecision(signal=candidate)


def test_runtime_strategy_evaluate_all_conditions_clears_tracking_and_captures_results() -> None:
    submitted = []

    def submitter(spec):
        submitted.append(spec)
        return PaperExecutionResult(status=OrderStatus.FILLED)

    strategy = RuntimeStrategy(
        core=FakeCore([_decision()]),
        assembler=FakeAssembler(_MockView()),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        submitter=submitter,
    )
    strategy.submitted_specs.append(object())

    batch = strategy.evaluate_all_conditions()

    assert batch.strategy == "ptb_diff"
    assert len(batch.submitted_specs) == 1
    assert len(batch.execution_results) == 1
    assert batch.execution_results[0].status == OrderStatus.FILLED
    assert submitted == list(batch.submitted_specs)

def test_runtime_strategy_fok_depth_counts_asks_through_max_entry() -> None:
    decision = AlphaDecision(
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        token_id="up-token",
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.50,
        max_entry_price=0.52,
        seconds_to_close=60,
        data_freshness_ms=20,
        reason_codes=("TEST",),
        metrics={},
        order_intent=OrderIntentSpec(intent=OrderIntent.TAKER_FOK, pair_id="pair-1"),
        hedge_leg=False,
    )

    class Book:
        best_ask = 0.50
        ask_levels = ((0.50, 10.0), (0.52, 10.0), (0.53, 100.0))

    class View(_MockView):
        def book_for(self, side):
            return Book()

    strategy = RuntimeStrategy(
        core=FakeCore([decision]),
        assembler=FakeAssembler(View()),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        fixed_stake_usdc=10.0,
    )

    specs = strategy.evaluate_condition("condition-btc-5m")

    assert len(specs) == 1
    assert specs[0].intent == OrderIntent.TAKER_FOK
    assert specs[0].quantity == 20.0
    assert strategy.rejected_decisions == []


def test_runtime_strategy_evaluate_all_conditions_uses_override_condition_ids() -> None:
    class RecordingAssembler(FakeAssembler):
        def __init__(self):
            super().__init__(object())
            self.seen = []

        def build(self, condition_id: str):
            self.seen.append(condition_id)
            return self.view

    assembler = RecordingAssembler()
    strategy = RuntimeStrategy(
        core=FakeCore([]),
        assembler=assembler,
        condition_ids=("old",),
        strategy_name="ptb_diff",
    )

    batch = strategy.evaluate_all_conditions(("new",))

    assert assembler.seen == ["new"]
    assert batch.submitted_specs == ()
