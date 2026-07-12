"""
Input: __future__, __future__.annotations, dataclasses, dataclasses.replace, polysignal_lab.alpha.types, polysignal_lab.alpha.types.AlphaDecision, polysignal_lab.alpha.types.OrderIntentSpec, polysignal_lab.domain.enums, polysignal_lab.domain.enums.OrderIntent, polysignal_lab.domain.enums.Side
Output: test_taker_fak_maps_to_ioc_limit_at_best_ask_and_checks_depth, test_reduce_only_order_intent_reaches_native_order_plan, test_order_spec_tags_include_signal_display_metadata, test_taker_fok_maps_to_fok_without_depth_precheck, test_fok_order_mapping_does_not_pre_reject_missing_depth, test_passive_gtd_maps_expiry_seconds_to_gtd_tags, test_contracts_metric_overrides_fixed_stake_quantity_for_hedge, test_approved_signal_candidate_preserves_gtd_expiry_and_pair_metadata, test_late_consensus_maps_to_current_favorite_ask_not_price_ceiling, test_missing_order_intent_uses_paper_safe_taker_at_max_entry_price
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from dataclasses import replace

from polysignal_lab.alpha.types import AlphaDecision, OrderIntentSpec
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_runtime.decision_policy import ApprovedDecision
from polysignal_lab.nautilus_runtime.order_mapping import order_spec_from_decision
from polysignal_lab.domain.strategy_config import LateConsensusConfig
from polysignal_lab.alpha.late_consensus_core import LateConsensusAlphaCore
from polysignal_lab.alpha.legacy_snapshot_adapter import decision_to_signal, market_view_from_snapshot
from factories import sample_snapshot


def _decision(
    *,
    intent: OrderIntent | None = None,
    expiry_seconds: int | None = None,
    max_price: float = 0.50,
    reduce_only: bool = False,
) -> AlphaDecision:
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
        entry_reference_price=max_price - 0.02,
        max_entry_price=max_price,
        seconds_to_close=60,
        data_freshness_ms=20,
        reason_codes=("TEST",),
        metrics={},
        order_intent=OrderIntentSpec(
            intent=intent, expiry_seconds=expiry_seconds, pair_id="pair-1",
            reduce_only=reduce_only,
        )
        if intent
        else None,
        hedge_leg=False,
    )


def test_taker_fak_maps_to_ioc_limit_at_best_ask_and_checks_depth() -> None:
    spec = order_spec_from_decision(
        _decision(intent=OrderIntent.TAKER_FAK, max_price=0.55),
        fixed_stake_usdc=11.0,
        best_ask=0.50,
    )

    assert spec.instrument_id == "up-token"
    assert spec.price == 0.50
    assert spec.quantity == 22.0
    assert spec.intent == OrderIntent.TAKER_FAK
    assert spec.tags["time_in_force"] == "IOC"
    assert spec.tags["fill_policy"] == "FAK"


def test_reduce_only_order_intent_reaches_native_order_plan() -> None:
    spec = order_spec_from_decision(
        _decision(intent=OrderIntent.TAKER_FAK, reduce_only=True),
        fixed_stake_usdc=10.0,
        best_ask=0.50,
        best_bid=0.45,
    )

    assert spec.reduce_only is True
    assert spec.price == 0.45


def test_order_spec_tags_include_signal_display_metadata() -> None:
    spec = order_spec_from_decision(
        _decision(intent=OrderIntent.TAKER_FAK, max_price=0.55),
        fixed_stake_usdc=11.0,
        best_ask=0.50,
    )

    assert spec.tags["asset"] == "BTC"
    assert spec.tags["timeframe"] == "5m"
    assert spec.tags["market_id"] == "btc-5m"
    assert spec.tags["market_slug"] == "btc-updown-5m"
    assert spec.tags["condition_id"] == "condition-btc-5m"
    assert spec.tags["confidence"] == "0.8"


def test_taker_fok_maps_to_fok_without_depth_precheck() -> None:
    spec = order_spec_from_decision(
        _decision(intent=OrderIntent.TAKER_FOK),
        fixed_stake_usdc=10.0,
        best_ask=0.50,
    )

    assert spec.quantity == 20.0
    assert spec.tags["time_in_force"] == "FOK"


def test_fok_order_mapping_does_not_pre_reject_missing_depth() -> None:
    signal = SignalCandidate.build(
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        token_id="up-token",
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.48,
        max_entry_price=0.50,
        seconds_to_close=60,
        data_freshness_ms=20,
        reason_codes=["TEST"],
        metrics={},
        order_intent=OrderIntent.TAKER_FOK,
        hedge_leg=False,
    )
    approved = ApprovedDecision(signal=signal)

    spec = order_spec_from_decision(
        approved,
        fixed_stake_usdc=10.0,
        best_ask=0.50,
    )

    assert spec.intent == OrderIntent.TAKER_FOK
    assert spec.price == 0.50
    assert spec.quantity == 20.0
    assert spec.tags["time_in_force"] == "FOK"


def test_passive_gtd_maps_expiry_seconds_to_gtd_tags() -> None:
    spec = order_spec_from_decision(
        _decision(intent=OrderIntent.PASSIVE_GTD, expiry_seconds=45),
        fixed_stake_usdc=10.0,
    )

    assert spec.price == 0.50
    assert spec.quantity == 20.0
    assert spec.expiry_seconds == 45
    assert spec.tags["time_in_force"] == "GTD"
    assert spec.tags["expire_seconds"] == "45"


def test_contracts_metric_overrides_fixed_stake_quantity_for_hedge() -> None:
    spec = order_spec_from_decision(
        replace(
            _decision(
                intent=OrderIntent.PASSIVE_GTD, expiry_seconds=45, max_price=0.40
            ),
            metrics={"contracts": 3.5},
            hedge_leg=True,
        ),
        fixed_stake_usdc=10.0,
    )

    assert spec.quantity == 3.5
    assert spec.hedge_leg is True


def test_approved_signal_candidate_preserves_gtd_expiry_and_pair_metadata() -> None:
    signal = SignalCandidate.build(
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        token_id="up-token",
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.48,
        max_entry_price=0.50,
        seconds_to_close=60,
        data_freshness_ms=20,
        reason_codes=["TEST"],
        metrics={},
        order_intent=OrderIntent.PASSIVE_GTD,
        expiry_seconds=45,
        pair_id="pair-1",
    )

    spec = order_spec_from_decision(
        ApprovedDecision(signal=signal), fixed_stake_usdc=10.0
    )

    assert spec.intent == OrderIntent.PASSIVE_GTD
    assert spec.expiry_seconds == 45
    assert spec.pair_id == "pair-1"
    assert spec.tags["expire_seconds"] == "45"


def test_late_consensus_maps_to_current_favorite_ask_not_price_ceiling() -> None:
    snapshot = sample_snapshot(up_ask=0.82, down_ask=0.18, seconds_to_close=100)
    view = market_view_from_snapshot(snapshot)
    assert view is not None
    decisions = LateConsensusAlphaCore(
        LateConsensusConfig(entry_frequency_sec=0)
    ).evaluate(view)
    signal = decision_to_signal(decisions[0], view.view_id, None)

    spec = order_spec_from_decision(
        ApprovedDecision(signal=signal),
        fixed_stake_usdc=10.0,
        best_ask=0.82,
    )

    assert spec.intent == OrderIntent.TAKER_IOC
    assert spec.price == 0.82
    assert spec.quantity == signal.metrics["contracts"]


def test_missing_order_intent_uses_paper_safe_taker_at_max_entry_price() -> None:
    spec = order_spec_from_decision(
        _decision(intent=None, max_price=0.40), fixed_stake_usdc=10.0
    )

    assert spec.price == 0.40
    assert spec.quantity == 25.0
    assert spec.intent == OrderIntent.TAKER_IOC
    assert spec.tags["time_in_force"] == "IOC"
    assert spec.tags["paper_safe_default"] == "true"
