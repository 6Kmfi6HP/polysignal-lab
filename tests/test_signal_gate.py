from __future__ import annotations

from polysignal_lab.config import SignalConfig
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.freshness import FreshnessPolicy
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.signal_layer.gate import SignalGate
from polysignal_lab.strategies.ptb_diff import PTBDiffStrategy


async def _ptb_signal(snapshot, settings):
    return PTBDiffStrategy(settings.strategies.ptb_diff).evaluate(snapshot)[0]


async def test_signal_gate_records_prd_reason_details(snapshot, settings) -> None:
    # Given: a signal below the publish confidence threshold.
    signal = (await _ptb_signal(snapshot, settings)).model_copy(
        update={"confidence": 0.1}
    )
    gate = SignalGate(settings.signal, settings.data.polymarket, settings.data.binance)

    # When: the gate evaluates the signal.
    decision = gate.evaluate(signal, snapshot)

    # Then: the rejection contains concrete PRD audit fields.
    assert decision.accepted is False
    assert decision.rejected is not None
    assert decision.rejected.reason_code == "CONFIDENCE_TOO_LOW"
    assert decision.rejected.details["strategy"] == signal.strategy
    assert decision.rejected.details["asset"] == signal.asset
    assert decision.rejected.details["timeframe"] == signal.timeframe
    assert decision.rejected.details["market_id"] == signal.market_id
    assert decision.rejected.details["side"] == signal.side.value
    assert decision.rejected.details["confidence"] == signal.confidence


async def test_signal_deduper_prevents_duplicate_channel_publish(
    snapshot, settings
) -> None:
    # Given: dedupe is enabled and the same channel signal is evaluated twice.
    signal = await _ptb_signal(snapshot, settings)
    config = settings.signal.model_copy(update={"max_signals_per_hour": 10})
    gate = SignalGate(config, settings.data.polymarket, settings.data.binance)

    # When: both evaluations run through the real gate.
    first = gate.evaluate(signal, snapshot)
    second = gate.evaluate(signal, snapshot)

    # Then: only the first signal is publishable and the second is rejected safely.
    assert first.accepted is True
    assert second.accepted is False
    assert second.rejected is not None
    assert second.rejected.reason_code == "DUPLICATE_SIGNAL"
    assert second.rejected.details["dedupe_key"] == signal.dedupe_key


async def test_signal_rate_limiter_rejects_after_channel_limit(
    snapshot, settings
) -> None:
    # Given: dedupe is disabled so rate limiting is the only repeated-signal gate.
    signal = await _ptb_signal(snapshot, settings)
    config = SignalConfig(
        min_confidence_to_publish=settings.signal.min_confidence_to_publish,
        dedupe_enabled=False,
        max_signals_per_hour=1,
        max_signals_per_market=5,
    )
    gate = SignalGate(config, settings.data.polymarket, settings.data.binance)

    # When: two signals pass all earlier checks in the same hour.
    first = gate.evaluate(signal, snapshot)
    second = gate.evaluate(signal, snapshot)

    # Then: the channel limit rejects the second publish attempt.
    assert first.accepted is True
    assert second.accepted is False
    assert second.rejected is not None
    assert second.rejected.reason_code == "CHANNEL_RATE_LIMIT"
    assert second.rejected.details["market_id"] == signal.market_id


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
