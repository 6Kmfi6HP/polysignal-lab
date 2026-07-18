"""
Input: __future__, __future__.annotations, importlib, dataclasses, dataclasses.replace, pathlib, pathlib.Path, pytest, polysignal_lab.alpha.types, polysignal_lab.alpha.types.(
Output: test_decision_policy_preserves_gate_first_failure_reasons, test_manual_disable_uses_pipeline_reason_without_touching_gate, test_approved_decision_preserves_order_intent_fields, test_candidate_from_decision_uses_market_view_time_for_identity, test_candidate_from_decision_preserves_reduce_only_intent, test_decision_policy_module_imports_without_nautilus_dependency, test_decision_policy_exposes_domain_state_not_nautilus_lifecycle, test_decision_policy_is_owned_by_strategy_not_separate_actor, test_state_round_trips_disabled_strategies, test_decision_policy_preserves_strategy_freshness_policy
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

import importlib
from dataclasses import replace
from pathlib import Path

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
    DecisionPolicy,
    RejectedDecision,
    candidate_from_decision,
)
from polysignal_lab.signal_layer.gate import SignalGate
from polysignal_lab.utils import utc_now


class _ExplodingGate:
    def evaluate(self, *_args: object) -> object:
        raise AssertionError("disabled strategies must not touch gate")


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
    ],
)
def test_decision_policy_preserves_gate_first_failure_reasons(
    case: str, expected_reason: str
) -> None:
    actor = DecisionPolicy(gate=_gate(dedupe_enabled=False))
    result = actor.evaluate(_decision_for(case), _view_for(case))
    assert isinstance(result, RejectedDecision)
    assert result.reason_code == expected_reason


def test_manual_disable_uses_pipeline_reason_without_touching_gate() -> None:
    actor = DecisionPolicy(gate=_ExplodingGate(), disabled_strategies={"alpha"})  # type: ignore[arg-type]
    result = actor.evaluate(_decision(), _view())
    assert isinstance(result, RejectedDecision)
    assert result.reason_code == "manual_disabled"


def test_approved_decision_preserves_order_intent_fields() -> None:
    actor = DecisionPolicy(gate=_gate(dedupe_enabled=False))
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
    assert result.decision.order_intent is not None
    assert result.decision.order_intent.intent == OrderIntent.PASSIVE_GTD
    assert result.decision.expiry_seconds == 300
    assert result.decision.pair_id == "pair-1"
    assert result.decision.hedge_leg is True
    assert result.publish.order_intent == OrderIntent.PASSIVE_GTD
    assert result.publish.expiry_seconds == 300


def test_candidate_from_decision_uses_market_view_time_for_identity() -> None:
    view = _view()
    decision = _decision()
    first = candidate_from_decision(decision, view)
    second = candidate_from_decision(decision, view)
    assert first.created_at == view.created_at
    assert first.snapshot_id == view.view_id
    assert first.signal_id == second.signal_id


def test_candidate_from_decision_preserves_reduce_only_intent() -> None:
    decision = _decision(
        order_intent=OrderIntentSpec(
            intent=OrderIntent.TAKER_FAK,
            reduce_only=True,
        )
    )
    candidate = candidate_from_decision(decision, _view())
    assert candidate.reduce_only is True


def test_decision_policy_module_imports_without_nautilus_dependency() -> None:
    module = importlib.import_module("polysignal_lab.nautilus_runtime.decision_policy")
    source = Path(module.__file__).read_text(encoding="utf-8")  # type: ignore[arg-type]
    assert "nautilus_trader" not in source
    assert module.DecisionPolicy is DecisionPolicy


def test_decision_policy_exposes_domain_state_not_nautilus_lifecycle() -> None:
    actor = DecisionPolicy(disabled_strategies={"manual"})
    assert "manual" in actor.disabled_strategies
    assert not hasattr(actor, "on_start")


def test_decision_policy_is_owned_by_strategy_not_separate_actor() -> None:
    module = importlib.import_module("polysignal_lab.nautilus_runtime.decision_policy")
    assert module.DecisionPolicy is DecisionPolicy
    assert not hasattr(module, "DecisionPolicyActor")


def test_state_round_trips_disabled_strategies() -> None:
    actor = DecisionPolicy(disabled_strategies={"manual", "alpha"})
    payload = actor.save_state()
    restored = DecisionPolicy()
    restored.load_state(payload)
    assert restored.disabled_strategies == {"manual", "alpha"}


def test_decision_policy_preserves_strategy_freshness_policy() -> None:
    policy = FreshnessPolicy(max_orderbook_staleness_ms=50, max_spot_staleness_ms=50)
    actor = DecisionPolicy(
        gate=_gate(dedupe_enabled=False),
        strategy_freshness_policies={"alpha": policy},
    )
    # Threshold comes from strategy policy when present.
    assert actor.orderbook_trade_threshold_ms("alpha") <= 100.0
    result = actor.evaluate(_decision(), _view(book_freshness_ms=101))
    assert isinstance(result, RejectedDecision)
    assert result.reason_code == "STALE_ORDERBOOK"


def test_batch_arbitration_keeps_opposite_legs_in_same_pair() -> None:
    actor = DecisionPolicy(gate=_gate(dedupe_enabled=False))
    up = _decision(
        side=Side.UP,
        order_intent=OrderIntentSpec(OrderIntent.PASSIVE_GTD, expiry_seconds=300, pair_id="p1"),
    )
    down = _decision(
        side=Side.DOWN,
        order_intent=OrderIntentSpec(OrderIntent.PASSIVE_GTD, expiry_seconds=300, pair_id="p1"),
    )
    view = _view()
    result = actor.batch_arbitrate([(up, view), (down, view)])
    assert list(result) == [up, down] or set(id(x) for x in result) == {id(up), id(down)}


def test_batch_arbitration_rejects_incomplete_pair() -> None:
    actor = DecisionPolicy(gate=_gate(dedupe_enabled=False))
    up = _decision(
        side=Side.UP,
        order_intent=OrderIntentSpec(OrderIntent.PASSIVE_GTD, expiry_seconds=300, pair_id="p1"),
    )
    result = actor.batch_arbitrate([(up, _view())])
    assert result == []
    assert result.rejections[0][1].reason_code == "INCOMPLETE_PAIR"


def test_batch_arbitration_returns_survivors_in_input_order() -> None:
    actor = DecisionPolicy(gate=_gate(dedupe_enabled=False))
    beta = _decision(strategy="beta", market_id="market-2")
    alpha = _decision(strategy="alpha", market_id="market-1")
    result = actor.batch_arbitrate([(beta, _view(market_id="market-2")), (alpha, _view())])
    assert result == [beta, alpha]


def test_batch_commit_handoff_requires_exact_market_view_identity() -> None:
    actor = DecisionPolicy(gate=_gate(dedupe_enabled=True))
    decision = _decision()
    view = _view()
    stale_view = replace(view, up=replace(view.up, freshness_ms=101))
    assert actor.batch_arbitrate([(decision, view)]) == [decision]
    result = actor.evaluate(decision, stale_view)
    assert isinstance(result, RejectedDecision)
    assert result.reason_code == "STALE_ORDERBOOK"
    assert isinstance(actor.evaluate(decision, view), ApprovedDecision)


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
