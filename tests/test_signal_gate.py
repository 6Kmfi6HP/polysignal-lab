"""
Input: __future__, __future__.annotations, datetime, datetime.timedelta, polysignal_lab.config, polysignal_lab.config.BinanceDataConfig, polysignal_lab.config.PolymarketDataConfig, polysignal_lab.config.SignalConfig, polysignal_lab.domain.enums, polysignal_lab.domain.enums.MarketStatus
Output: test_signal_gate_records_prd_reason_details, test_signal_deduper_prevents_duplicate_channel_publish, test_signal_rate_limiter_rejects_after_channel_limit, test_signal_candidate_carries_freshness_policy, test_gate_rejects_strategy_policy_stale_orderbook_with_details, test_gate_uses_strictest_threshold_when_global_is_lower, test_gate_uses_global_threshold_when_strategy_has_no_policy, test_gate_distinguishes_missing_orderbook_from_stale_orderbook, test_gate_distinguishes_missing_spot_from_stale_spot, test_ptb_diff_fresh_orderbook_candidate_has_metrics_not_fresh_reason
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from datetime import timedelta

from polysignal_lab.config import BinanceDataConfig, PolymarketDataConfig, SignalConfig
from polysignal_lab.domain.enums import MarketStatus, Side
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.domain.orderbook import BookLevel, OrderBook
from polysignal_lab.domain.freshness import FreshnessPolicy
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import FreshnessState, MarketSnapshot
from polysignal_lab.domain.spot import SpotPrice
from polysignal_lab.signal_layer.gate import SignalGate
from polysignal_lab.strategies.ptb_diff import PTBDiffStrategy
from polysignal_lab.utils import utc_now


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


def _freshness_signal(policy: FreshnessPolicy | None = None) -> SignalCandidate:
    return SignalCandidate.build(
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
        freshness_policy=policy,
        reason_codes=["UNIT"],
        metrics={"max_spread": 0.20},
    )


def _freshness_snapshot(*, book_age_ms: int | None, spot_age_ms: int | None) -> MarketSnapshot:
    now = utc_now()
    market = Market(
        market_id="mkt-1",
        market_slug="btc-updown-5m-test",
        condition_id="condition-1",
        question_id="question-1",
        question="BTC Up or Down?",
        asset="BTC",
        timeframe="5m",
        start_ts=now - timedelta(seconds=210),
        end_ts=now + timedelta(seconds=90),
        status=MarketStatus.ACTIVE,
        resolution_source="test",
        outcome_tokens=[
            OutcomeToken(token_id="token-up", side=Side.UP, outcome_name="Up", market_id="mkt-1"),
            OutcomeToken(token_id="token-down", side=Side.DOWN, outcome_name="Down", market_id="mkt-1"),
        ],
    )
    up_book = None
    if book_age_ms is not None:
        up_book = OrderBook(
            market_id="mkt-1",
            token_id="token-up",
            bids=[BookLevel(price=0.80, size=100.0)],
            asks=[BookLevel(price=0.82, size=100.0)],
            received_at=now - timedelta(milliseconds=book_age_ms),
        )
    spot = None
    if spot_age_ms is not None:
        spot = SpotPrice(
            asset="BTC",
            symbol="BTCUSDT",
            price=100_000.0,
            received_at=now - timedelta(milliseconds=spot_age_ms),
            event_time=now - timedelta(milliseconds=spot_age_ms),
        )
    return MarketSnapshot(
        snapshot_id="snap-freshness",
        created_at=now,
        market=market,
        up_book=up_book,
        down_book=None,
        spot=spot,
        freshness=FreshnessState(
            up_book_ms=book_age_ms,
            down_book_ms=None,
            spot_ms=spot_age_ms,
            max_ms=max(x for x in (book_age_ms, spot_age_ms) if x is not None) if book_age_ms is not None or spot_age_ms is not None else None,
        ),
    )


def test_gate_rejects_strategy_policy_stale_orderbook_with_details() -> None:
    gate = SignalGate(
        SignalConfig(dedupe_enabled=False),
        PolymarketDataConfig(max_book_staleness_ms=60_000),
        BinanceDataConfig(max_price_staleness_ms=60_000),
    )
    signal = _freshness_signal(
        FreshnessPolicy(max_orderbook_staleness_ms=1_500, max_spot_staleness_ms=1_500)
    )
    snapshot = _freshness_snapshot(book_age_ms=2_000, spot_age_ms=100)

    decision = gate.evaluate(signal, snapshot)

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
    signal = _freshness_signal(
        FreshnessPolicy(max_orderbook_staleness_ms=5_000, max_spot_staleness_ms=5_000)
    )
    snapshot = _freshness_snapshot(book_age_ms=2_000, spot_age_ms=100)

    decision = gate.evaluate(signal, snapshot)

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
    snapshot = _freshness_snapshot(book_age_ms=2_000, spot_age_ms=100)

    decision = gate.evaluate(signal, snapshot)

    assert decision.accepted is True


def test_gate_distinguishes_missing_orderbook_from_stale_orderbook() -> None:
    gate = SignalGate(SignalConfig(dedupe_enabled=False), PolymarketDataConfig(), BinanceDataConfig())
    signal = _freshness_signal(
        FreshnessPolicy(max_orderbook_staleness_ms=1_500, max_spot_staleness_ms=1_500)
    )
    snapshot = _freshness_snapshot(book_age_ms=None, spot_age_ms=100)

    decision = gate.evaluate(signal, snapshot)

    assert decision.accepted is False
    assert decision.rejected is not None
    assert decision.rejected.reason_code == "MISSING_ORDERBOOK"
    assert decision.rejected.details["lag_ms"] is None
    assert decision.rejected.details["threshold_ms"] == 1_500


def test_gate_distinguishes_missing_spot_from_stale_spot() -> None:
    gate = SignalGate(SignalConfig(dedupe_enabled=False), PolymarketDataConfig(), BinanceDataConfig())
    signal = _freshness_signal(
        FreshnessPolicy(max_orderbook_staleness_ms=1_500, max_spot_staleness_ms=1_500)
    )
    missing = gate.evaluate(signal, _freshness_snapshot(book_age_ms=100, spot_age_ms=None))
    stale = gate.evaluate(signal, _freshness_snapshot(book_age_ms=100, spot_age_ms=2_000))

    assert missing.rejected is not None
    assert missing.rejected.reason_code == "MISSING_SPOT_PRICE"
    assert missing.rejected.details["threshold_ms"] == 1_500
    assert stale.rejected is not None
    assert stale.rejected.reason_code == "STALE_SPOT_PRICE"
    assert stale.rejected.details["lag_ms"] == 2_000
    assert stale.rejected.details["threshold_ms"] == 1_500


async def test_ptb_diff_fresh_orderbook_candidate_has_metrics_not_fresh_reason(
    snapshot, settings
) -> None:
    strategy = PTBDiffStrategy(settings.strategies.ptb_diff)
    signals = strategy.evaluate(snapshot)

    assert signals
    metrics = signals[0].metrics
    assert metrics["orderbook_freshness_ms"] <= metrics["max_lag_ms"]
    assert isinstance(metrics["orderbook_freshness_ms"], int | float)
    assert isinstance(metrics["spot_freshness_ms"], int | float)
    assert isinstance(metrics["max_lag_ms"], int | float)
    assert "PTB_ORDERBOOK_FRESH" not in signals[0].reason_codes

async def test_ptb_diff_stale_spot_candidate_is_rejected_by_gate(snapshot, settings) -> None:
    stale_snapshot = snapshot.model_copy(
        update={
            "spot": snapshot.spot.model_copy(
                update={"received_at": snapshot.created_at - timedelta(seconds=3)}
            ),
            "freshness": snapshot.freshness.model_copy(
                update={"spot_ms": 3_000, "max_ms": 3_000}
            ),
        }
    )
    strategy = PTBDiffStrategy(settings.strategies.ptb_diff)
    signals = strategy.evaluate(stale_snapshot)

    assert signals

    gate = SignalGate(settings.signal, settings.data.polymarket, settings.data.binance)
    decision = gate.evaluate(signals[0], stale_snapshot)

    assert decision.accepted is False
    assert decision.rejected is not None
    assert decision.rejected.reason_code == "STALE_SPOT_PRICE"
    assert decision.rejected.details["lag_ms"] == 3_000
    assert (
        decision.rejected.details["threshold_ms"]
        == settings.strategies.ptb_diff.exit_config.market_data_max_lag_sec * 1000
    )


async def test_ptb_diff_stale_orderbook_candidate_has_no_fresh_reason(
    snapshot, settings
) -> None:
    stale_snapshot = snapshot.model_copy(
        update={
            "up_book": snapshot.up_book.model_copy(
                update={"received_at": snapshot.created_at - timedelta(seconds=3)}
            ),
            "down_book": snapshot.down_book.model_copy(
                update={"received_at": snapshot.created_at - timedelta(seconds=3)}
            ),
            "freshness": snapshot.freshness.model_copy(
                update={"up_book_ms": 3_000, "down_book_ms": 3_000, "max_ms": 3_000}
            ),
        }
    )
    strategy = PTBDiffStrategy(settings.strategies.ptb_diff)
    signals = strategy.evaluate(stale_snapshot)

    assert signals
    assert "PTB_ORDERBOOK_FRESH" not in signals[0].reason_codes

    gate = SignalGate(settings.signal, settings.data.polymarket, settings.data.binance)
    decision = gate.evaluate(signals[0], stale_snapshot)

    assert decision.accepted is False
    assert decision.rejected is not None
    assert decision.rejected.reason_code == "STALE_ORDERBOOK"
    assert decision.rejected.details["lag_ms"] == 3_000
    assert (
        decision.rejected.details["threshold_ms"]
        == settings.strategies.ptb_diff.exit_config.market_data_max_lag_sec * 1000
    )
