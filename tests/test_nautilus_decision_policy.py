from __future__ import annotations

from dataclasses import replace

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
from polysignal_lab.nautilus_runtime.decision_policy import (
    ApprovedDecision,
    DecisionPolicyActor,
    RejectedDecision,
)
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

    first = actor.evaluate(_decision(strategy="alpha"), _view())
    second = actor.evaluate(_decision(strategy="beta"), _view())

    assert isinstance(first, ApprovedDecision)
    assert first.consensus is None
    assert isinstance(second, ApprovedDecision)
    assert second.consensus is not None
    assert second.consensus.strategy == "consensus"
    assert second.consensus.source_signal_ids == [
        first.signal.signal_id,
        second.signal.signal_id,
    ]


def test_state_round_trips_disabled_strategies_and_dependencies() -> None:
    actor = DecisionPolicyActor(
        disabled_strategies={"base", "manual"},
        dependencies={"dependent": ("base", "other")},
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


def _actor_for(case: str) -> DecisionPolicyActor:
    if case == "dedupe":
        return DecisionPolicyActor(gate=_gate(dedupe_enabled=True))
    if case == "rate_limit":
        return DecisionPolicyActor(
            gate=_gate(dedupe_enabled=False, max_signals_per_hour=1)
        )
    return DecisionPolicyActor(gate=_gate(dedupe_enabled=False))


def _gate(
    *, dedupe_enabled: bool, max_signals_per_hour: int = 60
) -> SignalGate:
    return SignalGate(
        SignalConfig(
            min_confidence_to_publish=0.50,
            dedupe_enabled=dedupe_enabled,
            max_signals_per_hour=max_signals_per_hour,
            max_signals_per_market=50,
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
        market_id="market-1",
        market_slug="btc-updown-5m-test",
        condition_id="condition-1",
        token_id="token-up",
        side=Side.UP,
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
        view_id="view-1",
        market_id="market-1",
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
