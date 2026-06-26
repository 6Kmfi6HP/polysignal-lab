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
            "max_entry_price": "0.84",
            "entry_reference_price": "0.82",
        },
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
