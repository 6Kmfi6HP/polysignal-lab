from __future__ import annotations

from datetime import UTC, datetime, timedelta

from polysignal_lab.alpha.types import NautilusOrderSpec
from polysignal_lab.domain.enums import OrderIntent, OrderStatus, Side
from polysignal_lab.domain.orderbook import BookLevel, OrderBook
from polysignal_lab.nautilus_runtime.matching import (
    MatchingAccuracySettings,
    NautilusMatchingPaperExecutionClient,
)
from polysignal_lab.paper.wallet import PaperWallet


def _spec(
    *,
    token_id: str = "token-up",
    price: float = 0.82,
    quantity: float = 3.0,
    intent: OrderIntent = OrderIntent.TAKER_IOC,
    max_entry_price: str = "0.84",
) -> NautilusOrderSpec:
    return NautilusOrderSpec(
        instrument_id=token_id,
        side=Side.UP,
        price=price,
        quantity=quantity,
        intent=intent,
        expiry_seconds=None,
        pair_id="pair-1",
        reduce_only=False,
        hedge_leg=False,
        tags={
            "strategy": "late_consensus",
            "asset": "BTC",
            "timeframe": "5m",
            "market_id": "btc-5m",
            "condition_id": "condition-btc-5m",
            "signal_id": "signal-1",
            "confidence": "0.71",
            "max_entry_price": max_entry_price,
            "entry_reference_price": "0.82",
        },
    )


def _book(*, token_id: str = "token-up", ask_price: float = 0.82, ask_size: float = 500.0) -> OrderBook:
    return OrderBook(
        token_id=token_id,
        bids=[BookLevel(price=0.80, size=100.0)],
        asks=[BookLevel(price=ask_price, size=ask_size)],
        received_at=datetime.now(UTC),
    )


def test_accuracy_settings_match_spec_modes() -> None:
    fast_l1 = MatchingAccuracySettings.from_mode("fast_l1")
    depth_l2 = MatchingAccuracySettings.from_mode("depth_l2")
    queue_l2 = MatchingAccuracySettings.from_mode("queue_l2")

    assert fast_l1.book_type == "L1_MBP"
    assert fast_l1.liquidity_consumption is False
    assert depth_l2.book_type == "L2_MBP"
    assert depth_l2.liquidity_consumption is True
    assert depth_l2.queue_position is False
    assert queue_l2.queue_position is True


def test_matching_client_constructs_without_credentials() -> None:
    client = NautilusMatchingPaperExecutionClient(
        wallet=PaperWallet(),
        accuracy_mode="depth_l2",
    )

    assert client.paper_engine == "nautilus_matching"
    assert client.accuracy_mode == "depth_l2"


def test_submit_without_book_rejects() -> None:
    client = NautilusMatchingPaperExecutionClient(wallet=PaperWallet())

    result = client.submit_spec(_spec())

    assert result.status == OrderStatus.REJECTED
    assert result.reason == "MISSING_ORDERBOOK"


def test_update_book_rejects_stale_book_before_matching() -> None:
    client = NautilusMatchingPaperExecutionClient(
        wallet=PaperWallet(),
        max_book_staleness_ms=1_000,
    )
    stale_book = OrderBook(
        token_id="token-up",
        bids=[BookLevel(price=0.80, size=10.0)],
        asks=[BookLevel(price=0.83, size=10.0)],
        received_at=datetime.now(UTC) - timedelta(seconds=2),
    )

    client.update_book("token-up", stale_book)
    result = client.submit_spec(_spec())

    assert result.status == OrderStatus.REJECTED
    assert result.reason == "STALE_ORDERBOOK"


def test_update_trade_records_recent_trade_for_queue_mode() -> None:
    client = NautilusMatchingPaperExecutionClient(
        wallet=PaperWallet(),
        accuracy_mode="queue_l2",
    )
    ts_event = datetime.now(UTC)

    client.update_trade("token-up", price=0.84, size=2.5, side="BUY", ts_event=ts_event)
    trades = client.recent_trades_for("token-up")

    assert len(trades) == 1
    assert trades[0].price == 0.84
    assert trades[0].size == 2.5
    assert trades[0].side == "BUY"
    assert trades[0].ts_event == ts_event


def test_taker_fills_at_book_price_not_slippage_model() -> None:
    client = NautilusMatchingPaperExecutionClient(wallet=PaperWallet())
    client.update_book("token-up", _book(ask_price=0.82, ask_size=500.0))

    result = client.submit_spec(_spec(quantity=10.0, max_entry_price="0.83"))

    assert result.status == OrderStatus.FILLED
    assert result.fills[0].fill_price == 0.82
    assert result.order is not None
    assert result.order.limit_price == 0.83
    assert result.order.reference_price == 0.82
    assert result.positions[0].paper_position_id in client.wallet.open_positions


def test_best_ask_above_max_entry_is_rejected() -> None:
    client = NautilusMatchingPaperExecutionClient(wallet=PaperWallet())
    client.update_book("token-up", _book(ask_price=0.84, ask_size=500.0))

    result = client.submit_spec(_spec(quantity=10.0, max_entry_price="0.83"))

    assert result.status == OrderStatus.REJECTED
    assert result.reason == "PRICE_ABOVE_LIMIT"


def test_fok_rejects_when_full_depth_unavailable() -> None:
    client = NautilusMatchingPaperExecutionClient(wallet=PaperWallet())
    client.update_book("token-up", _book(ask_price=0.82, ask_size=5.0))

    result = client.submit_spec(
        _spec(quantity=10.0, intent=OrderIntent.TAKER_FOK, max_entry_price="0.83")
    )

    assert result.status == OrderStatus.REJECTED
    assert result.reason == "INSUFFICIENT_DEPTH"


def test_liquidity_consumption_prevents_reusing_same_level() -> None:
    client = NautilusMatchingPaperExecutionClient(wallet=PaperWallet())
    client.update_book("token-up", _book(ask_price=0.82, ask_size=12.0))

    first = client.submit_spec(_spec(quantity=10.0, max_entry_price="0.83"))
    second = client.submit_spec(_spec(quantity=10.0, max_entry_price="0.83"))

    assert first.status == OrderStatus.FILLED
    assert first.fills[0].shares == 10.0
    assert second.status == OrderStatus.FILLED
    assert second.fills[0].shares == 2.0
