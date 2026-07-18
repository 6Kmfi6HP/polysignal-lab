"""
Input: __future__, __future__.annotations, dataclasses, dataclasses.replace, polysignal_lab.alpha.types, polysignal_lab.alpha.types.FreshnessView, polysignal_lab.alpha.types.MarketView, polysignal_lab.config, polysignal_lab.config.BinanceDataConfig, polysignal_lab.config.PolymarketDataConfig
Output: test_signal_gate_records_prd_reason_details, test_signal_gate_does_not_apply_channel_rate_limit, test_signal_candidate_carries_freshness_policy, test_gate_rejects_strategy_policy_stale_orderbook_with_details, test_gate_uses_strictest_threshold_when_global_is_lower, test_gate_uses_global_threshold_when_strategy_has_no_policy, test_gate_distinguishes_missing_orderbook_from_stale_orderbook, test_gate_distinguishes_missing_spot_from_stale_spot, test_ptb_diff_fresh_orderbook_candidate_has_metrics_not_fresh_reason, test_ptb_diff_stale_spot_candidate_is_rejected_by_gate
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""










from __future__ import annotations

from dataclasses import replace

from polysignal_lab.alpha.types import AlphaDecision, FreshnessView, MarketView, OrderIntentSpec
from polysignal_lab.config import BinanceDataConfig, PolymarketDataConfig, SignalConfig
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.freshness import FreshnessPolicy
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.signal_layer.gate import SignalGate
from factories import sample_market_view
from signal_helpers import (
    ptb_decision_from_view,
    ptb_decisions_from_view,
    ptb_signals_from_view,
)


async def _ptb_signal(view, settings):
    return ptb_decision_from_view(view, settings)


async def test_signal_gate_records_prd_reason_details(market_view, settings) -> None:
    signal = replace(await _ptb_signal(market_view, settings), confidence=0.1)
    gate = SignalGate(settings.signal, settings.data.polymarket, settings.data.binance)

    decision = gate.evaluate(signal, market_view)

    assert decision.accepted is False
    assert decision.rejected is not None
    assert decision.rejected.reason_code == "CONFIDENCE_TOO_LOW"
    assert decision.rejected.details["strategy"] == signal.strategy
    assert decision.rejected.details["asset"] == signal.asset
    assert decision.rejected.details["timeframe"] == signal.timeframe
    assert decision.rejected.details["market_id"] == signal.market_id
    assert decision.rejected.details["side"] == signal.side.value
    assert decision.rejected.details["confidence"] == signal.confidence


async def test_signal_gate_does_not_apply_channel_rate_limit(
    market_view, settings
) -> None:
    """Submit-rate limits belong to Nautilus RiskEngine, not SignalGate."""
    signal = await _ptb_signal(market_view, settings)
    config = SignalConfig(
        min_confidence_to_publish=settings.signal.min_confidence_to_publish,
        dedupe_enabled=False,
        max_signals_per_hour=1,
        max_signals_per_market=5,
    )
    gate = SignalGate(config, settings.data.polymarket, settings.data.binance)

    first = gate.evaluate(signal, market_view)
    second = gate.evaluate(signal, market_view)

    assert first.accepted is True
    assert second.accepted is True
    assert second.rejected is None


def test_signal_candidate_carries_freshness_policy() -> None:
    policy = FreshnessPolicy(
        max_orderbook_staleness_ms=1_500,
        max_spot_staleness_ms=1_500,
    )

    signal = SignalCandidate.build(
        strategy="unit",
        asset="BTC",
        timeframe="5m",
        market_id="mkt-1",
        market_slug="btc-updown-5m-test",
        condition_id="condition-1",
        token_id="token-up",
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.82,
        max_entry_price=0.92,
        seconds_to_close=90,
        data_freshness_ms=10,
        reason_codes=["UNIT"],
        metrics={},
        freshness_policy=policy,
    )

    assert signal.freshness_policy == policy
    assert signal.model_dump()["freshness_policy"] == {
        "max_orderbook_staleness_ms": 1_500,
        "max_spot_staleness_ms": 1_500,
        "max_anchor_staleness_ms": None,
    }


def _freshness_signal(
    policy: FreshnessPolicy | None = None,
    *,
    reduce_only: bool = False,
) -> AlphaDecision:
    _ = policy  # applied via evaluate(..., freshness_policy=)
    return AlphaDecision(
        strategy="unit",
        asset="BTC",
        timeframe="5m",
        market_id="mkt-1",
        market_slug="btc-updown-5m-test",
        condition_id="condition-1",
        token_id="token-up",
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.82,
        max_entry_price=0.92,
        seconds_to_close=90,
        data_freshness_ms=10,
        reason_codes=("UNIT",),
        metrics={"max_spread": 0.20},
        order_intent=OrderIntentSpec(
            intent=OrderIntent.TAKER_IOC,
            reduce_only=reduce_only,
        )
        if reduce_only
        else None,
        hedge_leg=False,
    )


def _freshness_view(*, book_age_ms: int | None, spot_age_ms: int | None) -> MarketView:
    view = sample_market_view(
        up_ask=0.82,
        down_ask=0.18,
        include_up_book=book_age_ms is not None,
        include_down_book=False,
        include_spot=spot_age_ms is not None,
        book_freshness_ms=book_age_ms,
        spot_freshness_ms=spot_age_ms,
        up_bid=0.80,
        metrics={"max_spread": 0.20},
    )
    return replace(
        view,
        market_id="mkt-1",
        market_slug="btc-updown-5m-test",
        condition_id="condition-1",
        up=replace(view.up, token_id="token-up"),
    )


def test_gate_rejects_market_identity_mismatch() -> None:
    decision = _freshness_signal()
    view = replace(
        _freshness_view(book_age_ms=100, spot_age_ms=100),
        market_id="other-market",
    )

    result = SignalGate(
        SignalConfig(dedupe_enabled=False),
        PolymarketDataConfig(),
        BinanceDataConfig(),
    ).evaluate(decision, view)

    assert result.rejected is not None
    assert result.rejected.reason_code == "MARKET_ID_MISMATCH"


def test_gate_rejects_condition_identity_mismatch() -> None:
    decision = _freshness_signal()
    view = replace(
        _freshness_view(book_age_ms=100, spot_age_ms=100),
        condition_id="other-condition",
    )

    result = SignalGate(
        SignalConfig(dedupe_enabled=False),
        PolymarketDataConfig(),
        BinanceDataConfig(),
    ).evaluate(decision, view)

    assert result.rejected is not None
    assert result.rejected.reason_code == "CONDITION_ID_MISMATCH"


def test_gate_rejects_token_side_identity_mismatch() -> None:
    decision = _freshness_signal()
    view = replace(
        _freshness_view(book_age_ms=100, spot_age_ms=100),
        up=replace(
            _freshness_view(book_age_ms=100, spot_age_ms=100).up,
            token_id="other-token",
        ),
    )

    result = SignalGate(
        SignalConfig(dedupe_enabled=False),
        PolymarketDataConfig(),
        BinanceDataConfig(),
    ).evaluate(decision, view)

    assert result.rejected is not None
    assert result.rejected.reason_code == "TOKEN_SIDE_MISMATCH"


def test_gate_rejects_strategy_policy_stale_orderbook_with_details() -> None:
    gate = SignalGate(
        SignalConfig(dedupe_enabled=False),
        PolymarketDataConfig(max_book_staleness_ms=60_000),
        BinanceDataConfig(max_price_staleness_ms=60_000),
    )
    policy = FreshnessPolicy(max_orderbook_staleness_ms=1_500, max_spot_staleness_ms=1_500)
    signal = _freshness_signal(policy)
    view = _freshness_view(book_age_ms=2_000, spot_age_ms=100)

    decision = gate.evaluate(signal, view, freshness_policy=policy)

    assert decision.accepted is False
    assert decision.rejected is not None
    assert decision.rejected.reason_code == "STALE_ORDERBOOK"
    assert decision.rejected.details["lag_ms"] == 2_000
    assert decision.rejected.details["threshold_ms"] == 1_500
    assert decision.rejected.details["source"] == "orderbook"
    assert decision.rejected.details["policy_source"] == "strategy_and_global"


def test_gate_uses_strictest_threshold_when_global_is_lower() -> None:
    gate = SignalGate(
        SignalConfig(dedupe_enabled=False),
        PolymarketDataConfig(max_book_staleness_ms=1_000),
        BinanceDataConfig(max_price_staleness_ms=60_000),
    )
    policy = FreshnessPolicy(max_orderbook_staleness_ms=5_000, max_spot_staleness_ms=5_000)
    signal = _freshness_signal(policy)
    view = _freshness_view(book_age_ms=2_000, spot_age_ms=100)

    decision = gate.evaluate(signal, view, freshness_policy=policy)

    assert decision.accepted is False
    assert decision.rejected is not None
    assert decision.rejected.reason_code == "STALE_ORDERBOOK"
    assert decision.rejected.details["lag_ms"] == 2_000
    assert decision.rejected.details["threshold_ms"] == 1_000
    assert decision.rejected.details["policy_source"] == "strategy_and_global"


def test_gate_uses_global_threshold_when_strategy_has_no_policy() -> None:
    gate = SignalGate(
        SignalConfig(dedupe_enabled=False),
        PolymarketDataConfig(max_book_staleness_ms=60_000),
        BinanceDataConfig(max_price_staleness_ms=60_000),
    )
    signal = _freshness_signal(policy=None)
    view = _freshness_view(book_age_ms=2_000, spot_age_ms=100)

    decision = gate.evaluate(signal, view)

    assert decision.accepted is True


def test_gate_distinguishes_missing_orderbook_from_stale_orderbook() -> None:
    gate = SignalGate(SignalConfig(dedupe_enabled=False), PolymarketDataConfig(), BinanceDataConfig())
    policy = FreshnessPolicy(max_orderbook_staleness_ms=1_500, max_spot_staleness_ms=1_500)
    signal = _freshness_signal(policy)
    view = _freshness_view(book_age_ms=None, spot_age_ms=100)

    decision = gate.evaluate(signal, view, freshness_policy=policy)

    assert decision.accepted is False
    assert decision.rejected is not None
    assert decision.rejected.reason_code == "MISSING_ORDERBOOK"
    assert decision.rejected.details["lag_ms"] is None
    assert decision.rejected.details["threshold_ms"] == 1_500


def test_gate_distinguishes_missing_spot_from_stale_spot() -> None:
    gate = SignalGate(SignalConfig(dedupe_enabled=False), PolymarketDataConfig(), BinanceDataConfig())
    policy = FreshnessPolicy(max_orderbook_staleness_ms=1_500, max_spot_staleness_ms=1_500)
    signal = _freshness_signal(policy)
    missing = gate.evaluate(
        signal, _freshness_view(book_age_ms=100, spot_age_ms=None), freshness_policy=policy
    )
    stale = gate.evaluate(
        signal, _freshness_view(book_age_ms=100, spot_age_ms=2_000), freshness_policy=policy
    )

    assert missing.rejected is not None
    assert missing.rejected.reason_code == "MISSING_SPOT_PRICE"
    assert missing.rejected.details["threshold_ms"] == 1_500
    assert stale.rejected is not None
    assert stale.rejected.reason_code == "STALE_SPOT_PRICE"
    assert stale.rejected.details["lag_ms"] == 2_000
    assert stale.rejected.details["threshold_ms"] == 1_500


async def test_ptb_diff_fresh_orderbook_candidate_has_metrics_not_fresh_reason(
    market_view, settings
) -> None:
    signals = ptb_signals_from_view(market_view, settings)

    assert signals
    metrics = signals[0].metrics
    assert metrics["orderbook_freshness_ms"] <= metrics["max_lag_ms"]
    assert isinstance(metrics["orderbook_freshness_ms"], int | float)
    assert isinstance(metrics["spot_freshness_ms"], int | float)
    assert isinstance(metrics["max_lag_ms"], int | float)
    assert "PTB_ORDERBOOK_FRESH" not in signals[0].reason_codes


async def test_ptb_diff_stale_spot_candidate_is_rejected_by_gate(market_view, settings) -> None:
    assert market_view.spot is not None
    stale_view = replace(
        market_view,
        spot=replace(market_view.spot, freshness_ms=3_000, received_at=None),
        freshness=FreshnessView(
            up_book_ms=market_view.freshness.up_book_ms,
            down_book_ms=market_view.freshness.down_book_ms,
            spot_ms=3_000,
            max_ms=3_000,
        ),
    )
    decisions = ptb_decisions_from_view(stale_view, settings)
    assert decisions
    lag_ms = int(settings.strategies.ptb_diff.exit_config.market_data_max_lag_sec * 1000)
    policy = FreshnessPolicy(
        max_orderbook_staleness_ms=lag_ms,
        max_spot_staleness_ms=lag_ms,
    )

    gate = SignalGate(settings.signal, settings.data.polymarket, settings.data.binance)
    decision = gate.evaluate(decisions[0], stale_view, freshness_policy=policy)

    assert decision.accepted is False
    assert decision.rejected is not None
    assert decision.rejected.reason_code == "STALE_SPOT_PRICE"
    assert decision.rejected.details["lag_ms"] == 3_000
    assert decision.rejected.details["threshold_ms"] == lag_ms


async def test_ptb_diff_stale_orderbook_candidate_has_no_fresh_reason(
    market_view, settings
) -> None:
    stale_view = replace(
        market_view,
        up=replace(market_view.up, freshness_ms=3_000, received_at=None),
        down=replace(market_view.down, freshness_ms=3_000, received_at=None),
        freshness=FreshnessView(
            up_book_ms=3_000,
            down_book_ms=3_000,
            spot_ms=market_view.freshness.spot_ms,
            max_ms=3_000,
        ),
    )
    decisions = ptb_decisions_from_view(stale_view, settings)
    assert decisions
    assert "PTB_ORDERBOOK_FRESH" not in decisions[0].reason_codes
    lag_ms = int(settings.strategies.ptb_diff.exit_config.market_data_max_lag_sec * 1000)
    policy = FreshnessPolicy(
        max_orderbook_staleness_ms=lag_ms,
        max_spot_staleness_ms=lag_ms,
    )

    gate = SignalGate(settings.signal, settings.data.polymarket, settings.data.binance)
    decision = gate.evaluate(decisions[0], stale_view, freshness_policy=policy)

    assert decision.accepted is False
    assert decision.rejected is not None
    assert decision.rejected.reason_code == "STALE_ORDERBOOK"
    assert decision.rejected.details["lag_ms"] == 3_000
    assert decision.rejected.details["threshold_ms"] == lag_ms


def test_reduce_only_exit_bypasses_entry_confidence_and_rate_limit() -> None:
    gate = SignalGate(
        SignalConfig(
            dedupe_enabled=True,
            min_confidence_to_publish=0.50,
            max_signals_per_hour=1,
            max_signals_per_market=1,
        ),
        PolymarketDataConfig(max_book_staleness_ms=60_000),
        BinanceDataConfig(max_price_staleness_ms=60_000),
    )
    entry = _freshness_signal()
    close = replace(_freshness_signal(reduce_only=True), confidence=0.10)
    view = _freshness_view(book_age_ms=100, spot_age_ms=100)

    assert entry.dedupe_key != close.dedupe_key
    assert gate.evaluate(entry, view).accepted is True
    decision = gate.evaluate(close, view)

    assert decision.accepted is True

    gate = SignalGate(
        SignalConfig(dedupe_enabled=False),
        PolymarketDataConfig(max_book_staleness_ms=60_000),
        BinanceDataConfig(max_price_staleness_ms=60_000),
    )
    signal = replace(
        _freshness_signal(reduce_only=True),
        max_entry_price=0.10,
        order_intent=OrderIntentSpec(intent=OrderIntent.TAKER_IOC, reduce_only=True),
    )
    view = _freshness_view(book_age_ms=100, spot_age_ms=100)

    decision = gate.evaluate(signal, view)

    assert decision.accepted is True


def test_reduce_only_exit_survives_entry_batch_rejection() -> None:
    gate = SignalGate(
        SignalConfig(
            dedupe_enabled=True,
            max_signals_per_hour=10,
            max_signals_per_market=10,
        ),
        PolymarketDataConfig(max_book_staleness_ms=60_000),
        BinanceDataConfig(max_price_staleness_ms=60_000),
    )
    entry = _freshness_signal()
    close = replace(_freshness_signal(reduce_only=True), confidence=0.10)
    view = _freshness_view(book_age_ms=100, spot_age_ms=100)

    assert gate.evaluate(entry, view).accepted is True
    decisions = gate.commit([entry, close], view)

    assert decisions[0].accepted is True
    assert decisions[0].decision == entry
    assert decisions[1].accepted is True
    assert decisions[1].decision == close

    gate = SignalGate(
        SignalConfig(
            dedupe_enabled=True,
            min_confidence_to_publish=0.50,
            max_signals_per_hour=1,
            max_signals_per_market=1,
        ),
        PolymarketDataConfig(max_book_staleness_ms=60_000),
        BinanceDataConfig(max_price_staleness_ms=60_000),
    )
    close = replace(
        _freshness_signal(reduce_only=True),
        confidence=0.10,
        seconds_to_close=0,
    )
    base = _freshness_view(book_age_ms=100, spot_age_ms=100)
    view = replace(base, spot=None, up=replace(base.up, spread=0.9))

    assert gate.evaluate(close, view).accepted is True
    assert gate.evaluate(close, view).accepted is True
