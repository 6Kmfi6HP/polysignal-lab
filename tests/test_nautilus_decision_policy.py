"""
Input: __future__, __future__.annotations, importlib, sys, dataclasses, dataclasses.replace, pathlib, pathlib.Path, types, types.ModuleType
Output: test_decision_policy_preserves_gate_first_failure_reasons, test_manual_disable_uses_pipeline_reason_without_touching_gate, test_dependency_disable_uses_pipeline_reason_without_touching_gate, test_approved_decision_preserves_order_intent_fields, test_approved_decision_includes_consensus_signal_when_engine_merges, test_candidate_from_decision_uses_market_view_time_for_identity, test_decision_policy_module_imports_without_nautilus_dependency, test_nautilus_decision_policy_actor_exposes_domain_state_not_nautilus_lifecycle, test_nautilus_decision_policy_actor_constructs_without_nautilus_installed, test_nautilus_decision_policy_actor_on_save_on_load_delegate_to_policy_state, test_runtime_classes_expose_registerable_nautilus_policy_actor
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import importlib
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from polysignal_lab.alpha.types import (
    AlphaDecision,
    FreshnessView,
    MarketView,
    OrderIntentSpec,
    SideBookView,
    SpotView,
)
from polysignal_lab.config import BinanceDataConfig, PolymarketDataConfig, SignalConfig
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.freshness import FreshnessPolicy
from polysignal_lab.nautilus_runtime.decision_policy import (
    ApprovedDecision,
    DecisionPolicyActor,
    RejectedDecision,
    candidate_from_decision,
)
from polysignal_lab.signal_layer.arbiter import SignalArbiter
from polysignal_lab.signal_layer.consensus import ConsensusEngine
from polysignal_lab.signal_layer.gate import SignalGate
from polysignal_lab.utils import utc_now


class _ExplodingGate:
    def evaluate(self, *_args: object) -> object:
        raise AssertionError("disabled strategies must not touch gate")


class _ExplodingConsensus:
    def add(self, *_args: object) -> object:
        raise AssertionError("disabled strategies must not touch consensus")


@pytest.mark.parametrize(
    ("case", "expected_reason"),
    [
        ("market_inactive", "MARKET_NOT_ACTIVE"),
        ("time_window", "OUTSIDE_ENTRY_WINDOW"),
        ("book_freshness", "STALE_ORDERBOOK"),
        ("spot_freshness", "STALE_SPOT_PRICE"),
        ("spread", "SPREAD_TOO_WIDE"),
        ("max_entry", "ASK_ABOVE_MAX_ENTRY"),
        ("gtd_expiry", "GTD_EXPIRY_EXCEEDS_24H"),
        ("confidence", "CONFIDENCE_TOO_LOW"),
        ("dedupe", "DUPLICATE_SIGNAL"),
        ("rate_limit", "CHANNEL_RATE_LIMIT"),
    ],
)
def test_decision_policy_preserves_gate_first_failure_reasons(
    case: str, expected_reason: str
) -> None:
    actor = _actor_for(case)
    decision = _decision_for(case)
    view = _view_for(case)

    if case in {"dedupe", "rate_limit"}:
        first = actor.evaluate(decision, view)
        assert isinstance(first, ApprovedDecision)

    result = actor.evaluate(decision, view)

    assert isinstance(result, RejectedDecision)
    assert result.reason_code == expected_reason
    assert result.detail["reason_code"] == expected_reason


def test_manual_disable_uses_pipeline_reason_without_touching_gate() -> None:
    actor = DecisionPolicyActor(
        gate=_ExplodingGate(),
        consensus=_ExplodingConsensus(),
        disabled_strategies={"alpha"},
    )

    result = actor.evaluate(_decision(), _view())

    assert isinstance(result, RejectedDecision)
    assert result.reason_code == "manual_disabled"


def test_dependency_disable_uses_pipeline_reason_without_touching_gate() -> None:
    actor = DecisionPolicyActor(
        gate=_ExplodingGate(),
        consensus=_ExplodingConsensus(),
        disabled_strategies={"base"},
        dependencies={"alpha": ("base",)},
    )

    result = actor.evaluate(_decision(), _view())

    assert isinstance(result, RejectedDecision)
    assert result.reason_code == "dependency_disabled:base"


def test_approved_decision_preserves_order_intent_fields() -> None:
    actor = _actor_for("accepted")
    decision = _decision(
        order_intent=OrderIntentSpec(
            intent=OrderIntent.PASSIVE_GTD,
            expiry_seconds=300,
            pair_id="pair-1",
        ),
        hedge_leg=True,
    )

    result = actor.evaluate(decision, _view())

    assert isinstance(result, ApprovedDecision)
    assert result.signal.order_intent == OrderIntent.PASSIVE_GTD
    assert result.signal.expiry_seconds == 300
    assert result.signal.pair_id == "pair-1"
    assert result.signal.hedge_leg is True


def test_approved_decision_includes_consensus_signal_when_engine_merges() -> None:
    actor = DecisionPolicyActor(
        gate=_gate(dedupe_enabled=False),
        consensus=ConsensusEngine(window_sec=45, enabled=True),
    )
    view = _view()
    first = actor.evaluate(_decision(strategy="alpha"), view)
    second = actor.evaluate(_decision(strategy="beta"), view)

    assert isinstance(first, ApprovedDecision)
    assert first.signal.created_at == view.created_at
    assert first.consensus is None
    assert isinstance(second, ApprovedDecision)
    assert second.signal.created_at == view.created_at
    assert second.consensus is not None
    assert second.consensus.strategy == "consensus"
    assert second.consensus.created_at == view.created_at
    assert second.consensus.source_signal_ids == [
        first.signal.signal_id,
        second.signal.signal_id,
    ]


def test_candidate_from_decision_uses_market_view_time_for_identity() -> None:
    view = _view()
    decision = _decision()

    first = candidate_from_decision(decision, view)
    second = candidate_from_decision(decision, view)

    assert first.created_at == view.created_at
    assert first.signal_id == second.signal_id


def test_candidate_from_decision_preserves_reduce_only_intent() -> None:
    view = _view()
    decision = _decision(
        order_intent=OrderIntentSpec(
            intent=OrderIntent.TAKER_FAK,
            reduce_only=True,
        )
    )

    candidate = candidate_from_decision(decision, view)

    assert candidate.reduce_only is True
    assert candidate.order_intent == OrderIntent.TAKER_FAK


def test_decision_policy_module_imports_without_nautilus_dependency() -> None:
    source = Path("src/polysignal_lab/nautilus_runtime/decision_policy.py").read_text(
        encoding="utf-8"
    )

    assert "nautilus_trader" not in source
    module = importlib.import_module("polysignal_lab.nautilus_runtime.decision_policy")
    assert module.DecisionPolicyActor is DecisionPolicyActor


def test_decision_policy_actor_exposes_domain_state_not_nautilus_lifecycle() -> None:
    actor = DecisionPolicyActor(disabled_strategies={"manual"})

    assert callable(actor.save_state)
    assert callable(actor.load_state)
    assert not hasattr(actor, "on_save")
    assert not hasattr(actor, "on_load")


def test_nautilus_decision_policy_actor_constructs_without_nautilus_installed() -> None:
    from polysignal_lab.nautilus_runtime.decision_policy_actor import (
        NautilusDecisionPolicyActor,
    )

    actor = NautilusDecisionPolicyActor(disabled_strategies={"manual"})

    assert isinstance(actor, DecisionPolicyActor)
    assert actor.save_state()["disabled_strategies"] == ["manual"]


def test_nautilus_decision_policy_actor_on_save_on_load_delegate_to_policy_state() -> None:
    from polysignal_lab.nautilus_bridge.state import decode_state, state_key
    from polysignal_lab.nautilus_runtime.decision_policy_actor import (
        NautilusDecisionPolicyActor,
    )

    actor = NautilusDecisionPolicyActor(
        disabled_strategies={"base", "manual"},
        dependencies={"dependent": ("base", "other")},
    )
    restored = NautilusDecisionPolicyActor()

    saved = actor.on_save()
    restored.on_load(saved)

    assert state_key("decision_policy") in saved
    assert decode_state("decision_policy", saved) == {
        "disabled_strategies": ["base", "manual"],
        "strategy_dependencies": {"dependent": ["base", "other"]},
    }
    assert restored.save_state() == actor.save_state()
    assert restored.evaluate(_decision(strategy="dependent"), _view()).reason_code == (
        "dependency_disabled:base"
    )


def test_runtime_classes_expose_registerable_nautilus_policy_actor(monkeypatch) -> None:
    runtime_module_name = "polysignal_lab.nautilus_runtime.decision_policy_actor"
    missing = object()
    previous_runtime_module = sys.modules.get(runtime_module_name, missing)
    _ = sys.modules.pop(runtime_module_name, None)

    nautilus_module = ModuleType("nautilus_trader")
    common_module = ModuleType("nautilus_trader.common")
    actor_module = ModuleType("nautilus_trader.common.actor")
    config_module = ModuleType("nautilus_trader.config")
    trading_module = ModuleType("nautilus_trader.trading")
    strategy_module = ModuleType("nautilus_trader.trading.strategy")

    class FakeActor:
        def __init__(self, *, config: object) -> None:
            self.actor_config = config

    class FakeStrategy:
        def __init__(self, *, config: object) -> None:
            self.strategy_config = config

    actor_module.Actor = FakeActor
    config_module.ActorConfig = lambda: "actor-config"
    config_module.StrategyConfig = lambda: "strategy-config"
    strategy_module.Strategy = FakeStrategy
    nautilus_module.common = common_module
    nautilus_module.config = config_module
    nautilus_module.trading = trading_module
    common_module.actor = actor_module
    trading_module.strategy = strategy_module

    monkeypatch.setitem(sys.modules, "nautilus_trader", nautilus_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.common", common_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.common.actor", actor_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.config", config_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.trading", trading_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.trading.strategy", strategy_module)

    try:
        module = importlib.import_module(runtime_module_name)
        actor = module.NautilusDecisionPolicyActor(disabled_strategies={"manual"})
        node = SimpleNamespace(trader=SimpleNamespace(actors=[]))
        node.trader.add_actor = node.trader.actors.append

        node.trader.add_actor(actor)

        assert isinstance(actor, FakeActor)
        assert isinstance(actor, DecisionPolicyActor)
        assert actor.actor_config == "actor-config"
        assert node.trader.actors == [actor]
    finally:
        if previous_runtime_module is missing:
            _ = sys.modules.pop(runtime_module_name, None)
        else:
            sys.modules[runtime_module_name] = previous_runtime_module


def test_state_round_trips_disabled_strategies_and_dependencies() -> None:
    actor = DecisionPolicyActor(
        disabled_strategies={"base", "manual"},
        dependencies={"dependent": ("base", "other")},
        strategy_freshness_policies={
            "dependent": FreshnessPolicy(max_orderbook_staleness_ms=1000)
        },
    )
    restored = DecisionPolicyActor()

    restored.load_state(actor.save_state())

    assert restored.save_state() == {
        "disabled_strategies": ["base", "manual"],
        "strategy_dependencies": {"dependent": ["base", "other"]},
    }
    assert restored.evaluate(_decision(strategy="dependent"), _view()).reason_code == (
        "dependency_disabled:base"
    )



def test_load_state_preserves_preseeded_disabled_strategies_and_dependencies() -> None:
    actor = DecisionPolicyActor(
        disabled_strategies={"vwap_momentum"},
        dependencies={"dependent": ("vwap_momentum",)},
    )

    actor.load_state({"disabled_strategies": [], "strategy_dependencies": {}})

    assert actor.save_state() == {
        "disabled_strategies": ["vwap_momentum"],
        "strategy_dependencies": {"dependent": ["vwap_momentum"]},
    }
    assert actor.evaluate(_decision(strategy="vwap_momentum"), _view()).reason_code == (
        "manual_disabled"
    )

@pytest.mark.parametrize(
    ("policy", "view_kwargs", "expected_reason"),
    [
        (
            FreshnessPolicy(max_orderbook_staleness_ms=1000),
            {"book_freshness_ms": 2000},
            "STALE_ORDERBOOK",
        ),
        (
            FreshnessPolicy(max_spot_staleness_ms=1000),
            {"spot_freshness_ms": 2000},
            "STALE_SPOT_PRICE",
        ),
    ],
)
def test_decision_policy_preserves_strategy_freshness_policy(
    policy: FreshnessPolicy, view_kwargs: dict[str, int], expected_reason: str
) -> None:
    actor = DecisionPolicyActor(
        gate=_gate(dedupe_enabled=False),
        strategy_freshness_policies={"alpha": policy},
    )

    result = actor.evaluate(_decision(), _view(**view_kwargs))

    assert isinstance(result, RejectedDecision)
    assert result.reason_code == expected_reason
    assert result.detail["policy_source"] == "strategy_and_global"


def test_missing_side_book_rejects_as_missing_orderbook() -> None:
    actor = _actor_for("accepted")
    view = _view()
    missing_up_book = replace(
        view.up,
        best_bid=None,
        best_ask=None,
        spread=None,
        freshness_ms=None,
        min_order_size=None,
        tick_size=None,
        last_trade_price=None,
        last_trade_size=None,
        last_trade_timestamp=None,
        received_at=None,
        ask_levels=(),
    )

    result = actor.evaluate(_decision(), replace(view, up=missing_up_book))

    assert isinstance(result, RejectedDecision)
    assert result.reason_code == "MISSING_ORDERBOOK"
    assert result.detail["lag_ms"] is None


def test_batch_arbitration_keeps_opposite_legs_in_same_pair() -> None:
    actor = DecisionPolicyActor(
        gate=_gate(dedupe_enabled=False),
        arbiter=SignalArbiter(),
    )
    up = _decision(
        side=Side.UP,
        order_intent=OrderIntentSpec(
            OrderIntent.PASSIVE_GTD,
            expiry_seconds=300,
            pair_id="pair-1",
        ),
    )
    down = _decision(
        side=Side.DOWN,
        order_intent=OrderIntentSpec(
            OrderIntent.PASSIVE_GTD,
            expiry_seconds=300,
            pair_id="pair-1",
        ),
    )

    assert actor.batch_arbitrate([(up, _view()), (down, _view())]) == [up, down]


def test_invalid_batch_candidate_cannot_suppress_valid_opposite_candidate() -> None:
    actor = _actor_for("accepted")
    invalid = _decision(side=Side.UP, max_entry_price=0.10)
    valid = _decision(side=Side.DOWN, max_entry_price=0.90)
    view = _view_for("accepted")

    assert actor.batch_arbitrate([(invalid, view), (valid, view)]) == [valid]


def test_batch_prevalidation_does_not_consume_gate_state_for_suppressed_candidate() -> None:
    actor = DecisionPolicyActor(gate=_gate(dedupe_enabled=True))
    up = _decision(side=Side.UP)
    down = _decision(side=Side.DOWN)
    view = _view()

    assert actor.batch_arbitrate([(up, view), (down, view)]) == []
    assert actor.gate.deduper.snapshot() == {}
    assert len(actor.gate.rate_limiter._global) == 0


def test_batch_arbitration_rejects_incomplete_pair_without_committing_gate_state() -> None:
    actor = DecisionPolicyActor(gate=_gate(dedupe_enabled=True))
    up = _decision(
        order_intent=OrderIntentSpec(
            OrderIntent.PASSIVE_GTD,
            expiry_seconds=300,
            pair_id="pair-1",
        )
    )

    result = actor.batch_arbitrate([(up, _view())])

    assert result == []
    assert [(decision, rejected.reason_code) for decision, rejected in result.rejections] == [
        (up, "INCOMPLETE_PAIR")
    ]
    assert actor.gate.deduper.snapshot() == {}
    assert len(actor.gate.rate_limiter._global) == 0


def test_batch_arbitration_rejects_duplicate_pair_leg() -> None:
    actor = DecisionPolicyActor(gate=_gate(dedupe_enabled=False))
    up = _decision(
        side=Side.UP,
        order_intent=OrderIntentSpec(
            OrderIntent.PASSIVE_GTD,
            expiry_seconds=300,
            pair_id="pair-1",
        ),
    )
    duplicate_up = replace(up, token_id="token-up-duplicate")
    down = _decision(
        side=Side.DOWN,
        order_intent=OrderIntentSpec(
            OrderIntent.PASSIVE_GTD,
            expiry_seconds=300,
            pair_id="pair-1",
        ),
    )

    result = actor.batch_arbitrate([(up, _view()), (duplicate_up, _view()), (down, _view())])

    assert result == []
    assert [rejected.reason_code for _, rejected in result.rejections] == [
        "MALFORMED_PAIR",
        "MALFORMED_PAIR",
        "MALFORMED_PAIR",
    ]


def test_batch_arbitration_records_ambiguity_rejections() -> None:
    actor = DecisionPolicyActor(gate=_gate(dedupe_enabled=False))
    up = _decision(side=Side.UP)
    down = _decision(side=Side.DOWN)

    result = actor.batch_arbitrate([(up, _view()), (down, _view())])

    assert result == []
    assert [rejected.reason_code for _, rejected in result.rejections] == [
        "ARBITRATION_SUPPRESSED",
        "ARBITRATION_SUPPRESSED",
    ]


def test_batch_arbitration_returns_survivors_in_original_input_order() -> None:
    actor = DecisionPolicyActor(gate=_gate(dedupe_enabled=False))
    beta = _decision(strategy="beta", market_id="market-2", token_id="token-beta")
    alpha = _decision(strategy="alpha", market_id="market-1", token_id="token-alpha")

    result = actor.batch_arbitrate([(beta, _view(market_id="market-2")), (alpha, _view())])

    assert result == [beta, alpha]


def test_batch_commit_handoff_requires_exact_market_view_identity() -> None:
    actor = DecisionPolicyActor(gate=_gate(dedupe_enabled=True))
    decision = _decision()
    view = _view()
    stale_view = replace(view, up=replace(view.up, freshness_ms=101))

    assert actor.batch_arbitrate([(decision, view)]) == [decision]

    result = actor.evaluate(decision, stale_view)

    assert isinstance(result, RejectedDecision)
    assert result.reason_code == "STALE_ORDERBOOK"
    assert isinstance(actor.evaluate(decision, view), ApprovedDecision)


def test_complete_pair_commits_policy_for_both_legs_before_evaluation() -> None:
    actor = DecisionPolicyActor(gate=_gate(dedupe_enabled=True, max_signals_per_market=2))
    up = _decision(
        side=Side.UP,
        order_intent=OrderIntentSpec(
            OrderIntent.PASSIVE_GTD,
            expiry_seconds=300,
            pair_id="pair-1",
        ),
    )
    down = _decision(
        side=Side.DOWN,
        order_intent=OrderIntentSpec(
            OrderIntent.PASSIVE_GTD,
            expiry_seconds=300,
            pair_id="pair-1",
        ),
    )
    view = _view()

    assert actor.batch_arbitrate([(down, view), (up, view)]) == [down, up]
    assert isinstance(actor.evaluate(down, view), ApprovedDecision)
    assert isinstance(actor.evaluate(up, view), ApprovedDecision)


def test_complete_pair_rejects_before_mutating_gate_when_capacity_is_insufficient() -> None:
    actor = DecisionPolicyActor(gate=_gate(dedupe_enabled=True, max_signals_per_market=1))
    up = _decision(
        side=Side.UP,
        order_intent=OrderIntentSpec(
            OrderIntent.PASSIVE_GTD,
            expiry_seconds=300,
            pair_id="pair-1",
        ),
    )
    down = _decision(
        side=Side.DOWN,
        order_intent=OrderIntentSpec(
            OrderIntent.PASSIVE_GTD,
            expiry_seconds=300,
            pair_id="pair-1",
        ),
    )
    view = _view()

    result = actor.batch_arbitrate([(up, view), (down, view)])

    assert result == []
    assert [rejected.reason_code for _, rejected in result.rejections] == [
        "CHANNEL_RATE_LIMIT",
        "CHANNEL_RATE_LIMIT",
    ]
    assert actor.gate.deduper.snapshot() == {}
    assert len(actor.gate.rate_limiter._global) == 0


def _actor_for(case: str) -> DecisionPolicyActor:
    if case == "dedupe":
        return DecisionPolicyActor(gate=_gate(dedupe_enabled=True))
    if case == "rate_limit":
        return DecisionPolicyActor(
            gate=_gate(dedupe_enabled=False, max_signals_per_hour=1)
        )
    return DecisionPolicyActor(gate=_gate(dedupe_enabled=False))


def _gate(
    *,
    dedupe_enabled: bool,
    max_signals_per_hour: int = 60,
    max_signals_per_market: int = 50,
) -> SignalGate:
    return SignalGate(
        SignalConfig(
            min_confidence_to_publish=0.50,
            dedupe_enabled=dedupe_enabled,
            max_signals_per_hour=max_signals_per_hour,
            max_signals_per_market=max_signals_per_market,
        ),
        PolymarketDataConfig(max_book_staleness_ms=100),
        BinanceDataConfig(max_price_staleness_ms=100),
    )


def _decision_for(case: str) -> AlphaDecision:
    if case == "time_window":
        return _decision(seconds_to_close=0)
    if case == "max_entry":
        return _decision(max_entry_price=0.40)
    if case == "gtd_expiry":
        return _decision(
            order_intent=OrderIntentSpec(
                intent=OrderIntent.PASSIVE_GTD,
                expiry_seconds=86_401,
            )
        )
    if case == "confidence":
        return _decision(confidence=0.49)
    return _decision()


def _view_for(case: str) -> MarketView:
    if case == "market_inactive":
        return _view(market_is_active=False)
    if case == "book_freshness":
        return _view(book_freshness_ms=101)
    if case == "spot_freshness":
        return _view(spot_freshness_ms=101)
    if case == "spread":
        return _view(spread=0.20)
    if case == "max_entry":
        return _view(ask=0.45)
    return _view()


def _decision(
    *,
    strategy: str = "alpha",
    market_id: str = "market-1",
    token_id: str | None = None,
    side: Side = Side.UP,
    confidence: float = 0.75,
    seconds_to_close: int | None = 120,
    max_entry_price: float = 0.60,
    order_intent: OrderIntentSpec | None = None,
    hedge_leg: bool = False,
) -> AlphaDecision:
    return AlphaDecision(
        strategy=strategy,
        asset="BTC",
        timeframe="5m",
        market_id=market_id,
        market_slug="btc-updown-5m-test",
        condition_id="condition-1",
        token_id=token_id or ("token-up" if side == Side.UP else "token-down"),
        side=side,
        confidence=confidence,
        entry_reference_price=0.45,
        max_entry_price=max_entry_price,
        seconds_to_close=seconds_to_close,
        data_freshness_ms=10,
        reason_codes=("UNIT",),
        metrics={"max_spread": 0.10},
        order_intent=order_intent,
        hedge_leg=hedge_leg,
    )


def _view(
    *,
    market_id: str = "market-1",
    market_is_active: bool = True,
    ask: float = 0.45,
    spread: float = 0.03,
    book_freshness_ms: int = 10,
    spot_freshness_ms: int = 10,
) -> MarketView:
    created_at = utc_now()
    up = SideBookView(
        token_id="token-up",
        best_bid=max(0.01, ask - spread),
        best_ask=ask,
        spread=spread,
        freshness_ms=book_freshness_ms,
    )
    down = replace(up, token_id="token-down")
    return MarketView(
        view_id=f"view-{market_id}",
        market_id=market_id,
        market_slug="btc-updown-5m-test",
        condition_id="condition-1",
        asset="BTC",
        timeframe="5m",
        start_ts=None,
        end_ts=None,
        created_at=created_at,
        seconds_to_close=120,
        up=up,
        down=down,
        spot=SpotView(
            asset="BTC",
            symbol="BTCUSDT",
            price=100_000.0,
            source="test",
            freshness_ms=spot_freshness_ms,
        ),
        price_to_beat=100_000.0,
        up_trades=(),
        down_trades=(),
        metrics={"market_is_active": market_is_active},
        freshness=FreshnessView(
            up_book_ms=book_freshness_ms,
            down_book_ms=book_freshness_ms,
            spot_ms=spot_freshness_ms,
            max_ms=max(book_freshness_ms, spot_freshness_ms),
        ),
    )
