from __future__ import annotations

from dataclasses import replace

import pytest

from polysignal_lab.alpha.types import AlphaDecision, OrderIntentSpec
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_runtime.decision_policy import ApprovedDecision
from polysignal_lab.nautilus_runtime.order_mapping import order_spec_from_decision
from polysignal_lab.strategies.config import LateConsensusConfig
from polysignal_lab.strategies.late_consensus import LateConsensusStrategy
from factories import sample_snapshot


def _decision(
    *,
    intent: OrderIntent | None = None,
    expiry_seconds: int | None = None,
    max_price: float = 0.50,
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
            intent=intent, expiry_seconds=expiry_seconds, pair_id="pair-1"
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
        available_shares=30.0,
    )

    assert spec.instrument_id == "up-token"
    assert spec.price == 0.50
    assert spec.quantity == 22.0
    assert spec.intent == OrderIntent.TAKER_FAK
    assert spec.tags["time_in_force"] == "IOC"
    assert spec.tags["fill_policy"] == "FAK"


def test_order_spec_tags_include_signal_display_metadata() -> None:
    spec = order_spec_from_decision(
        _decision(intent=OrderIntent.TAKER_FAK, max_price=0.55),
        fixed_stake_usdc=11.0,
        best_ask=0.50,
        available_shares=30.0,
    )

    assert spec.tags["asset"] == "BTC"
    assert spec.tags["timeframe"] == "5m"
    assert spec.tags["market_id"] == "btc-5m"
    assert spec.tags["market_slug"] == "btc-updown-5m"
    assert spec.tags["condition_id"] == "condition-btc-5m"
    assert spec.tags["confidence"] == "0.8"


def test_taker_fak_rejects_when_visible_depth_cannot_fill_any_shares() -> None:
    try:
        order_spec_from_decision(
            _decision(intent=OrderIntent.TAKER_FAK),
            fixed_stake_usdc=10.0,
            best_ask=0.50,
            available_shares=0.0,
        )
    except ValueError as exc:
        assert "insufficient depth" in str(exc)
    else:  # pragma: no cover - assertion path
        raise AssertionError("expected insufficient depth rejection")


def test_taker_fok_maps_to_fok_and_requires_full_visible_depth() -> None:
    spec = order_spec_from_decision(
        _decision(intent=OrderIntent.TAKER_FOK),
        fixed_stake_usdc=10.0,
        best_ask=0.50,
        available_shares=20.0,
    )

    assert spec.quantity == 20.0
    assert spec.tags["time_in_force"] == "FOK"

    try:
        order_spec_from_decision(
            _decision(intent=OrderIntent.TAKER_FOK),
            fixed_stake_usdc=10.0,
            best_ask=0.50,
            available_shares=19.99,
        )
    except ValueError as exc:
        assert "full fill" in str(exc)
    else:  # pragma: no cover - assertion path
        raise AssertionError("expected FOK depth rejection")


def test_taker_fok_rejects_unknown_visible_depth() -> None:
    with pytest.raises(ValueError, match="insufficient depth for full fill"):
        order_spec_from_decision(
            _decision(intent=OrderIntent.TAKER_FOK),
            fixed_stake_usdc=10.0,
            best_ask=0.50,
            available_shares=None,
        )


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
    signal = LateConsensusStrategy(
        LateConsensusConfig(entry_frequency_sec=0)
    ).evaluate(sample_snapshot(up_ask=0.82, down_ask=0.18, seconds_to_close=100))[0]

    spec = order_spec_from_decision(
        ApprovedDecision(signal=signal),
        fixed_stake_usdc=10.0,
        best_ask=0.82,
        available_shares=500.0,
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
