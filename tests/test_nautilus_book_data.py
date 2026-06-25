from __future__ import annotations

from datetime import UTC, datetime, timedelta

from polysignal_lab.data.state import OrderBookRegistry
from polysignal_lab.domain.orderbook import OrderBook, BookLevel
from polysignal_lab.domain.trade import Trade
from polysignal_lab.nautilus_runtime.book_data import NautilusBookDataProvider


def _book(token_id: str = "up-token") -> OrderBook:
    now = datetime.now(UTC)
    return OrderBook(
        token_id=token_id,
        bids=[BookLevel(price=0.81, size=10.0)],
        asks=[BookLevel(price=0.83, size=12.0)],
        received_at=now,
        source_timestamp=now.isoformat(),
    )


def test_book_for_token_converts_orderbook_to_side_view() -> None:
    registry = OrderBookRegistry()
    registry.update(_book())
    provider = NautilusBookDataProvider(registry)

    view = provider.book_for_token("up-token")

    assert view is not None
    assert view.token_id == "up-token"
    assert view.best_bid == 0.81
    assert view.best_ask == 0.83
    assert view.spread == 0.02
    assert view.ask_levels == ((0.83, 12.0),)
    assert view.received_at is not None


def test_trades_for_token_uses_registry_recent_trades_copy() -> None:
    registry = OrderBookRegistry()
    registry.trade_events["up-token"] = [Trade(price=0.82, size=5.0, timestamp=1.0)]
    provider = NautilusBookDataProvider(registry)

    trades = provider.trades_for_token("up-token")

    assert len(trades) == 1
    assert trades[0].price == 0.82
    assert trades[0].size == 5.0
    assert trades[0].side is None


def test_empty_book_has_no_best_prices() -> None:
    provider = NautilusBookDataProvider()
    provider.update_book(
        "empty-token",
        OrderBook(token_id="empty-token", bids=[], asks=[], received_at=datetime.now(UTC)),
    )

    view = provider.book_for_token("empty-token")
    snapshot = provider.snapshot_for_token("empty-token")

    assert view is not None
    assert view.best_bid is None
    assert view.best_ask is None
    assert view.spread is None
    assert snapshot is not None
    assert snapshot.bid is None
    assert snapshot.ask is None


def test_snapshot_freshness_falls_back_to_book_received_at() -> None:
    provider = NautilusBookDataProvider()
    received_at = datetime.now(UTC) - timedelta(milliseconds=25)
    provider.update_book(
        "up-token",
        OrderBook(
            token_id="up-token",
            bids=[BookLevel(price=0.80, size=3.0)],
            asks=[BookLevel(price=0.84, size=4.0)],
            received_at=received_at,
        ),
    )

    snapshot = provider.snapshot_for_token("up-token")

    assert snapshot is not None
    assert snapshot.freshness_ms is not None
    assert snapshot.freshness_ms >= 0
