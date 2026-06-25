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
