from __future__ import annotations

from datetime import timedelta

import pytest

from polysignal_lab.config import FillModelConfig
from polysignal_lab.data.state import OrderBookRegistry
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
        ("RECONNECT_RESEED_FAILED", "PAPER_STALE_ORDERBOOK"),
        ("TICK_SIZE_CHANGE_RESEED_REQUIRED", "PAPER_STALE_ORDERBOOK"),
        ("BOOK_SEQUENCE_INVALID", "PAPER_STALE_ORDERBOOK"),
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

@pytest.mark.parametrize(
    "stale_reason",
    [
        "RECONNECT_RESEED_FAILED",
        "TICK_SIZE_CHANGE_RESEED_REQUIRED",
        "BOOK_SEQUENCE_INVALID",
    ],
)
def test_preflight_normalizes_registry_stale_reasons(stale_reason: str) -> None:
    registry = OrderBookRegistry()
    book = _book()
    registry.update_from_snapshot(book)
    registry.mark_stale(book.token_id, stale_reason)
    preflight = PaperExecutionPreflight(
        FillModelConfig(require_depth_check=True, min_fill_ratio=1.0, reject_if_partial=True),
        max_book_staleness_ms=1000,
        fixed_stake_usdc=10.0,
        registry=registry,
    )

    decision = preflight.evaluate(_signal(), book, utc_now())

    assert decision.accepted is False
    assert decision.reason_code == "PAPER_STALE_ORDERBOOK"
    assert decision.metrics["paper_original_reason"] == stale_reason
    assert decision.metrics["paper_normalized_reason"] == "PAPER_STALE_ORDERBOOK"


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


def test_preflight_rejects_fak_slippage_above_limit() -> None:
    decision = _preflight().evaluate(
        _signal(order_intent=OrderIntent.TAKER_FAK, max_entry_price=0.60),
        _book(ask=0.599, size=100.0),
        utc_now(),
        OrderIntent.TAKER_FAK,
    )
    assert decision.accepted is False
    assert decision.reason_code == "PAPER_EXTREME_SLIPPAGE"
    assert decision.metrics["paper_original_reason"] == "SLIPPAGE_EXCEEDS_MAX_ENTRY"


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



def test_preflight_revalidates_stored_probability_edge() -> None:
    signal = _signal(
        max_entry_price=0.80,
        metrics={
            "directional_probability": 0.70,
            "entry_prob": 0.60,
            "probability_edge": 0.10,
        },
    )
    decision = _preflight().evaluate(signal, _book(ask=0.72, size=100.0), utc_now())
    assert decision.accepted is False
    assert decision.reason_code == "PAPER_EDGE_VANISHED"
    assert decision.metrics["paper_edge_revalidated"] is True


def test_preflight_accepts_refs_style_min_token_price_edge() -> None:
    entry_price = 0.60
    min_token_price = 0.55
    signal = _signal(
        max_entry_price=0.80,
        metrics={
            "directional_probability": entry_price,
            "entry_prob": entry_price,
            "probability_edge": entry_price - min_token_price,
            "min_token_price": min_token_price,
        },
    )

    decision = _preflight().evaluate(signal, _book(ask=entry_price, size=100.0), utc_now())

    assert decision.accepted is True
    assert decision.reason_code == "PAPER_ACCEPTED"
    assert decision.metrics["paper_edge_revalidated"] is True
    assert decision.metrics["paper_execution_min_token_price"] == min_token_price