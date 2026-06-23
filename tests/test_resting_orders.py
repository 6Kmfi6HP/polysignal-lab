from __future__ import annotations
import time
import pytest
from polysignal_lab.paper.order_intent_executor import (
    BestAskTakerExecutor, PassiveGtdExecutor, MultiLegCoordinator,
    IntentDispatchResult, RestingOrder,
)
from polysignal_lab.domain.enums import OrderIntent, OrderStatus, Side
from polysignal_lab.domain.orderbook import BookLevel, OrderBook
from polysignal_lab.domain.paper_order import PaperOrder
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.paper.wallet import PaperWallet
from polysignal_lab.data.state import OrderBookRegistry
from polysignal_lab.config import FillModelConfig
from polysignal_lab.utils import utc_now
from factories import sample_book, BookFactoryConfig

def _make_order(token_id="t-up", stake=10.0, limit=1.0) -> PaperOrder:
    return PaperOrder(
        signal_id="sig-1", asset="BTC", timeframe="5m",
        strategy="test", market_id="mkt-1", market_slug="s",
        token_id=token_id, side=Side.UP,
        limit_price=limit, reference_price=0.5, stake_usdc=stake,
    )

def _make_deep_book(token_id="t-up") -> OrderBook:
    return OrderBook(
        token_id=token_id, bids=[BookLevel(price=0.45, size=100)],
        asks=[BookLevel(price=0.45, size=10), BookLevel(price=0.50, size=50)],
        received_at=utc_now(),
    )

def _make_signal(signal_id="sig-1", token_id="t-up", pair_id=None, hedge_leg=False) -> SignalCandidate:
    return SignalCandidate.build(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="mkt-1", market_slug="s", condition_id="c",
        token_id=token_id, side=Side.DOWN if hedge_leg else Side.UP, confidence=0.7,
        entry_reference_price=0.45, max_entry_price=0.50,
        seconds_to_close=300, data_freshness_ms=100,
        reason_codes=["T"], metrics={},
        order_intent=OrderIntent.TAKER_FOK, pair_id=pair_id,
        hedge_leg=hedge_leg,
    )

def test_fak_fills_all_at_best_ask():
    executor = BestAskTakerExecutor(FillModelConfig(slippage_bps=0), 60000)
    order = _make_order(limit=0.60, stake=4.5)
    book = _make_deep_book()
    result = executor.execute(order, book, OrderIntent.TAKER_FAK)
    assert result.status == OrderStatus.FILLED
    assert len(result.fills) == 1
    assert result.fills[0].fill_price == 0.45
    assert result.fills[0].shares == 10.0  # 4.5 / 0.45

def test_fak_partial_fill():
    executor = BestAskTakerExecutor(FillModelConfig(slippage_bps=0), 60000)
    order = _make_order(limit=0.45, stake=20.0)  # only 4.5 USDC depth at 0.45
    book = OrderBook(
        token_id="t-up", bids=[BookLevel(price=0.40, size=100)],
        asks=[BookLevel(price=0.45, size=2)],
        received_at=utc_now(),
    )
    result = executor.execute(order, book, OrderIntent.TAKER_FAK)
    assert result.status == OrderStatus.PARTIAL
    assert result.fills[0].stake_usdc < 20.0

def test_fak_rejects_no_ask():
    executor = BestAskTakerExecutor(FillModelConfig(slippage_bps=0), 60000)
    order = _make_order(limit=0.50)
    book = OrderBook(token_id="t-up", bids=[], asks=[], received_at=utc_now())
    result = executor.execute(order, book, OrderIntent.TAKER_FAK)
    assert result.status == OrderStatus.REJECTED
    assert result.reject_reason == "MISSING_BEST_ASK"

def test_fak_rejects_malformed_ask():
    executor = BestAskTakerExecutor(FillModelConfig(slippage_bps=0), 60000)
    order = _make_order(limit=0.50)
    book = OrderBook(
        token_id="t-up", bids=[BookLevel(price=0.40, size=100)],
        asks=[BookLevel(price=0, size=10), BookLevel(price=0.45, size=-1)],
        received_at=utc_now(),
    )
    result = executor.execute(order, book, OrderIntent.TAKER_FAK)
    assert result.status == OrderStatus.REJECTED
    assert result.reject_reason == "MALFORMED_ORDERBOOK"

def test_fak_multi_level_shares():
    executor = BestAskTakerExecutor(FillModelConfig(slippage_bps=0), 60000)
    order = _make_order(limit=0.60, stake=14.5)
    book = OrderBook(
        token_id="t-up", bids=[BookLevel(price=0.40, size=100)],
        asks=[BookLevel(price=0.45, size=10), BookLevel(price=0.50, size=20)],
        received_at=utc_now(),
    )
    result = executor.execute(order, book, OrderIntent.TAKER_FAK)
    expected_shares = 4.5 / 0.45 + 10.0 / 0.50
    assert result.status == OrderStatus.FILLED
    assert result.fills[0].stake_usdc == pytest.approx(14.5)
    assert result.fills[0].shares == pytest.approx(expected_shares)
    assert result.fills[0].fill_price == pytest.approx(14.5 / expected_shares)

def test_fok_fills_when_depth_sufficient():
    executor = BestAskTakerExecutor(FillModelConfig(slippage_bps=0), 60000)
    order = _make_order(limit=0.55, stake=4.5)
    book = _make_deep_book()
    result = executor.execute(order, book, OrderIntent.TAKER_FOK)
    assert result.status == OrderStatus.FILLED

def test_fok_rejects_insufficient_depth():
    executor = BestAskTakerExecutor(FillModelConfig(slippage_bps=0), 60000)
    order = _make_order(limit=0.45, stake=100.0)
    book = _make_deep_book()
    result = executor.execute(order, book, OrderIntent.TAKER_FOK)
    assert result.status == OrderStatus.REJECTED
    assert result.reject_reason == "FOK_INSUFFICIENT_DEPTH"

def test_fok_multi_level_shares():
    executor = BestAskTakerExecutor(FillModelConfig(slippage_bps=0), 60000)
    order = _make_order(limit=0.60, stake=14.5)
    book = OrderBook(
        token_id="t-up", bids=[BookLevel(price=0.40, size=100)],
        asks=[BookLevel(price=0.45, size=10), BookLevel(price=0.50, size=20)],
        received_at=utc_now(),
    )
    result = executor.execute(order, book, OrderIntent.TAKER_FOK)
    expected_shares = 4.5 / 0.45 + 10.0 / 0.50
    assert result.status == OrderStatus.FILLED
    assert result.fills[0].shares == pytest.approx(expected_shares)
    assert result.fills[0].fill_price == pytest.approx(14.5 / expected_shares)

def test_gtd_enqueue_returns_resting():
    executor = PassiveGtdExecutor()
    order = _make_order(limit=0.35)
    sig = SignalCandidate.build(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="mkt-1", market_slug="s", condition_id="c",
        token_id="t-up", side=Side.UP, confidence=0.6,
        entry_reference_price=0.35, max_entry_price=0.35,
        seconds_to_close=300, data_freshness_ms=100,
        reason_codes=["T"], metrics={},
        order_intent=OrderIntent.PASSIVE_GTD, expiry_seconds=200,
    )
    result = executor.enqueue(order, sig)
    assert result.status == OrderStatus.RESTING
    assert executor.resting_count == 1

def test_gtd_tick_fills_when_bid_matches():
    executor = PassiveGtdExecutor()
    wallet = PaperWallet(1000)
    order = _make_order(limit=0.35, stake=3.5)
    sig = SignalCandidate.build(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="mkt-1", market_slug="s", condition_id="c",
        token_id="t-up", side=Side.UP, confidence=0.6,
        entry_reference_price=0.35, max_entry_price=0.35,
        seconds_to_close=300, data_freshness_ms=100,
        reason_codes=["T"], metrics={},
        order_intent=OrderIntent.PASSIVE_GTD, expiry_seconds=300,
    )
    executor.enqueue(order, sig)
    books = OrderBookRegistry()
    books.update(sample_book("t-up", BookFactoryConfig(ask=0.55, bid=0.35, size=100)))
    results = executor.tick(books, wallet)
    assert len(results) == 1
    assert results[0].status == OrderStatus.FILLED
    assert executor.resting_count == 0

def test_gtd_tick_no_fill_bid_below_limit():
    executor = PassiveGtdExecutor()
    wallet = PaperWallet(1000)
    order = _make_order(limit=0.35, stake=3.5)
    sig = SignalCandidate.build(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="mkt-1", market_slug="s", condition_id="c",
        token_id="t-up", side=Side.UP, confidence=0.6,
        entry_reference_price=0.35, max_entry_price=0.35,
        seconds_to_close=300, data_freshness_ms=100,
        reason_codes=["T"], metrics={},
        order_intent=OrderIntent.PASSIVE_GTD, expiry_seconds=300,
    )
    executor.enqueue(order, sig)
    books = OrderBookRegistry()
    books.update(sample_book("t-up", BookFactoryConfig(ask=0.55, bid=0.30, size=100)))
    results = executor.tick(books, wallet)
    assert len(results) == 0
    assert executor.resting_count == 1

def test_gtd_tick_expires_past_expiry():
    executor = PassiveGtdExecutor()
    wallet = PaperWallet(1000)
    order = _make_order(limit=0.35, stake=3.5)
    sig = SignalCandidate.build(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="mkt-1", market_slug="s", condition_id="c",
        token_id="t-up", side=Side.UP, confidence=0.6,
        entry_reference_price=0.35, max_entry_price=0.35,
        seconds_to_close=300, data_freshness_ms=100,
        reason_codes=["T"], metrics={},
        order_intent=OrderIntent.PASSIVE_GTD, expiry_seconds=300,
    )
    # Manually force expiry_ts to past
    sig = sig.model_copy(update={"created_at": utc_now().replace(year=2020)})
    executor.enqueue(order, sig)
    books = OrderBookRegistry()
    books.update(sample_book("t-up", BookFactoryConfig(ask=0.55, bid=0.35, size=100)))
    results = executor.tick(books, wallet)
    assert len(results) == 1
    assert results[0].status == OrderStatus.CANCELLED
    assert results[0].reject_reason == "GTD_EXPIRED"
    assert executor.resting_count == 0

def test_multi_leg_fok_pair_both_filled():
    from polysignal_lab.domain.signal import SignalCandidate as SC
    from polysignal_lab.domain.enums import Side
    sig1 = SC.build(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="mkt-1", market_slug="s", condition_id="c",
        token_id="t-up", side=Side.UP, confidence=0.7,
        entry_reference_price=0.45, max_entry_price=0.50,
        seconds_to_close=300, data_freshness_ms=100,
        reason_codes=["T"], metrics={},
        order_intent=OrderIntent.TAKER_FOK, pair_id="mkt:dual",
    )
    sig2 = SC.build(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="mkt-1", market_slug="s", condition_id="c",
        token_id="t-down", side=Side.DOWN, confidence=0.7,
        entry_reference_price=0.45, max_entry_price=0.50,
        seconds_to_close=300, data_freshness_ms=100,
        reason_codes=["T"], metrics={},
        order_intent=OrderIntent.TAKER_FOK, pair_id="mkt:dual",
        hedge_leg=True,
    )
    coord = MultiLegCoordinator()
    coord.register(sig1)
    coord.register(sig2)
    order1 = _make_order("t-up", limit=0.50, stake=4.5)
    order2 = _make_order("t-down", limit=0.50, stake=4.5)
    book1 = _make_deep_book("t-up")
    book2 = _make_deep_book("t-down")
    executor = BestAskTakerExecutor(FillModelConfig(slippage_bps=0), 60000)
    coord.record_pending(sig1, order1, book1)
    result = coord.try_execute_fok_pair(sig2, order2, book2, executor)
    assert result is not None
    assert result.status == OrderStatus.FILLED
    assert len(result.fills) == 2

def test_fok_pair_atomic_rollback():
    sig1 = _make_signal("sig-leg-1", "t-up", pair_id="mkt:atomic", hedge_leg=False)
    sig2 = _make_signal("sig-leg-2", "t-down", pair_id="mkt:atomic", hedge_leg=True)
    coord = MultiLegCoordinator()
    coord.register(sig1)
    coord.register(sig2)
    order1 = _make_order("t-up", limit=0.50, stake=4.5)
    order2 = _make_order("t-down", limit=0.50, stake=100.0)
    book1 = _make_deep_book("t-up")
    book2 = _make_deep_book("t-down")
    executor = BestAskTakerExecutor(FillModelConfig(slippage_bps=0), 60000)
    coord.record_pending(sig1, order1, book1)

    result = coord.try_execute_fok_pair(sig2, order2, book2, executor)

    assert result is not None
    assert result.status == OrderStatus.REJECTED
    assert order1.status == OrderStatus.REJECTED
    assert order2.status == OrderStatus.REJECTED
    assert order1.reject_reason == "FOK_PAIR_REJECTED"
    assert order2.reject_reason == "FOK_INSUFFICIENT_DEPTH"

def test_any_leg_failed_reports_correctly():
    sig1 = _make_signal("sig-leg-1", "t-up", pair_id="mkt:failed", hedge_leg=False)
    sig2 = _make_signal("sig-leg-2", "t-down", pair_id="mkt:failed", hedge_leg=True)
    coord = MultiLegCoordinator()
    coord.register(sig1)
    coord.register(sig2)
    order1 = _make_order("t-up", limit=0.50, stake=4.5)
    order2 = _make_order("t-down", limit=0.50, stake=100.0)
    book1 = _make_deep_book("t-up")
    book2 = _make_deep_book("t-down")
    executor = BestAskTakerExecutor(FillModelConfig(slippage_bps=0), 60000)
    coord.record_pending(sig1, order1, book1)

    coord.try_execute_fok_pair(sig2, order2, book2, executor)

    assert coord.any_leg_failed("mkt:failed") is True
