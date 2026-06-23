from __future__ import annotations

from datetime import timedelta

import pytest

from polysignal_lab.config import FillModelConfig
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.orderbook import BookLevel, OrderBook
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.paper.preflight import PaperExecutionPreflight, normalize_paper_reject_reason
from polysignal_lab.utils import utc_now


def _signal(**updates) -> SignalCandidate:
    payload = dict(
        signal_id="sig-preflight",
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="mkt-1",
        market_slug="btc-updown-5m",
        condition_id="cond-1",
        token_id="token-up",
        side=Side.UP,
        confidence=0.7,
        entry_reference_price=0.50,
        max_entry_price=0.60,
        seconds_to_close=120,
        data_freshness_ms=100,
        reason_codes=["TEST"],
        metrics={},
        dedupe_key="BTC:5m:mkt-1:UP:test",
    )
    payload.update(updates)
    return SignalCandidate(**payload)


def _book(*, ask: float = 0.50, size: float = 100.0, received_delta_ms: int = 0) -> OrderBook:
    return OrderBook(
        market_id="mkt-1",
        token_id="token-up",
        bids=[BookLevel(price=max(0.01, ask - 0.03), size=size)],
        asks=[BookLevel(price=ask, size=size), BookLevel(price=min(0.99, ask + 0.02), size=size)],
        received_at=utc_now() - timedelta(milliseconds=received_delta_ms),
    )


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("MISSING_ORDERBOOK", "PAPER_MISSING_ORDERBOOK"),
        ("NO_SNAPSHOT", "PAPER_STALE_ORDERBOOK"),
        ("STALE_ORDERBOOK", "PAPER_STALE_ORDERBOOK"),
        ("ASK_ABOVE_MAX_ENTRY", "PAPER_ENTRY_PRICE_MOVED"),
        ("SLIPPAGE_EXCEEDS_MAX_ENTRY", "PAPER_EXTREME_SLIPPAGE"),
        ("INSUFFICIENT_DEPTH", "PAPER_DEPTH_TOO_THIN"),
        ("FOK_INSUFFICIENT_DEPTH", "PAPER_DEPTH_TOO_THIN"),
        ("FAK_NO_LIQUIDITY", "PAPER_DEPTH_TOO_THIN"),
        ("EXPOSURE_LIMIT_REACHED", "PAPER_EXPOSURE_LIMIT_REACHED"),
        ("MAX_OPEN_POSITIONS_REACHED", "PAPER_EXPOSURE_LIMIT_REACHED"),
        ("WALLET_INSUFFICIENT_CASH", "PAPER_WALLET_INSUFFICIENT_CASH"),
        ("GTD_EXPIRED", "PAPER_GTD_EXPIRED"),
        ("MALFORMED_ORDERBOOK", "PAPER_MALFORMED_ORDERBOOK"),
        ("UNKNOWN_REASON", "PAPER_FILL_REJECTED"),
    ],
)
def test_normalize_paper_reject_reason(raw: str, normalized: str) -> None:
    assert normalize_paper_reject_reason(raw) == normalized


def _preflight(*, max_staleness_ms: int = 1000, require_depth_check: bool = True) -> PaperExecutionPreflight:
    return PaperExecutionPreflight(
        FillModelConfig(require_depth_check=require_depth_check, min_fill_ratio=1.0, reject_if_partial=True),
        max_book_staleness_ms=max_staleness_ms,
        fixed_stake_usdc=10.0,
    )


def test_preflight_rejects_missing_book_with_normalized_reason() -> None:
    decision = _preflight().evaluate(_signal(), None, utc_now())
    assert decision.accepted is False
    assert decision.reason_code == "PAPER_MISSING_ORDERBOOK"
    assert decision.metrics["paper_original_reason"] == "MISSING_ORDERBOOK"


def test_preflight_rejects_stale_book() -> None:
    now = utc_now()
    decision = _preflight(max_staleness_ms=100).evaluate(
        _signal(), _book(received_delta_ms=250), now
    )
    assert decision.accepted is False
    assert decision.reason_code == "PAPER_STALE_ORDERBOOK"
    assert decision.metrics["paper_orderbook_fresh"] is False


def test_preflight_rejects_price_moved_above_max_entry() -> None:
    decision = _preflight().evaluate(_signal(max_entry_price=0.55), _book(ask=0.61), utc_now())
    assert decision.accepted is False
    assert decision.reason_code == "PAPER_ENTRY_PRICE_MOVED"


def test_preflight_rejects_full_fill_depth_for_fok() -> None:
    decision = _preflight().evaluate(
        _signal(order_intent=OrderIntent.TAKER_FOK),
        _book(ask=0.50, size=5.0),
        utc_now(),
        OrderIntent.TAKER_FOK,
    )
    assert decision.accepted is False
    assert decision.reason_code == "PAPER_DEPTH_TOO_THIN"
    assert decision.metrics["paper_available_depth_usdc"] < 10.0


def test_preflight_allows_fak_partial_depth() -> None:
    decision = _preflight().evaluate(
        _signal(order_intent=OrderIntent.TAKER_FAK),
        _book(ask=0.50, size=5.0),
        utc_now(),
        OrderIntent.TAKER_FAK,
    )
    assert decision.accepted is True
    assert decision.metrics["paper_depth_revalidated"] is True


def test_preflight_passive_gtd_does_not_require_immediate_depth() -> None:
    decision = _preflight().evaluate(
        _signal(order_intent=OrderIntent.PASSIVE_GTD, max_entry_price=0.01),
        _book(ask=0.80, size=0.1),
        utc_now(),
        OrderIntent.PASSIVE_GTD,
    )
    assert decision.accepted is True
    assert decision.metrics["paper_depth_revalidated"] is False


def test_preflight_rejects_probability_edge_vanished() -> None:
    signal = _signal(
        max_entry_price=0.80,
        metrics={"directional_probability": 0.70, "min_probability_edge": 0.05},
    )
    decision = _preflight().evaluate(signal, _book(ask=0.68, size=100.0), utc_now())
    assert decision.accepted is False
    assert decision.reason_code == "PAPER_EDGE_VANISHED"
    assert decision.metrics["paper_edge_revalidated"] is True
