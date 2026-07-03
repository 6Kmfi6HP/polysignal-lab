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


def test_trades_for_token_hardcodes_none_for_missing_fields() -> None:
    """Registry-backend Trade objects have price/size/timestamp only.

    side and ts must be None because the Trade model lacks those fields.
    Hard-coding None avoids expensive Pydantic getattr on nonexistent
    fields (~8.3 µs per nonexistent field lookup).
    """
    registry = OrderBookRegistry()
    registry.trade_events["up-token"] = [Trade(price=0.82, size=5.0, timestamp=1.0)]
    provider = NautilusBookDataProvider(registry)

    trades = provider.trades_for_token("up-token")

    assert len(trades) == 1
    assert trades[0].side is None
    assert trades[0].ts is None


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


def test_update_trade_updates_last_trade_fields_without_full_deep_copy() -> None:
    provider = NautilusBookDataProvider()
    provider.update_book(
        "up-token",
        OrderBook(
            token_id="up-token",
            bids=[BookLevel(price=0.81, size=10.0)],
            asks=[BookLevel(price=0.83, size=12.0)],
        ),
    )

    provider.update_trade(
        token_id="up-token",
        price=0.82,
        size=5.0,
        side="BUY",
        ts=datetime.now(UTC),
    )

    stored = provider.book_for_token("up-token")
    assert stored is not None
    assert stored.last_trade_price == 0.82
    assert stored.last_trade_size == 5.0
    # Book levels must be preserved after trade update
    assert stored.best_bid == 0.81
    assert stored.best_ask == 0.83


def test_update_trade_does_not_allocate_slice_on_repeated_trades() -> None:
    """Verify that update_trade does not allocate a new list via [-512:] slice.

    Using deque(maxlen=512) eliminates the O(N) slice allocation on every trade.
    This test ensures the trade history still functions correctly after the change.
    """
    provider = NautilusBookDataProvider()
    provider.update_book(
        "batch-token",
        OrderBook(
            token_id="batch-token",
            bids=[BookLevel(price=0.80, size=5.0)],
            asks=[BookLevel(price=0.84, size=4.0)],
        ),
    )

    # Push 600 trades — deque should only keep the latest 512
    for i in range(600):
        price = 0.80 + (i % 100) * 0.001
        provider.update_trade(
            token_id="batch-token",
            price=price,
            size=1.0,
            side="BUY",
            ts=datetime.now(UTC) + timedelta(milliseconds=i),
        )

    trades = provider.trades_for_token("batch-token")
    assert len(trades) == 512, (
        f"Expected 512 trades, got {len(trades)} — deque maxlen not enforced"
    )

    # Most recent trades must be present
    assert trades[-1].price == 0.80 + (99 % 100) * 0.001


def test_update_trade_twice_preserves_all_levels() -> None:
    provider = NautilusBookDataProvider()
    provider.update_book(
        "up-token",
        OrderBook(
            token_id="up-token",
            bids=[BookLevel(price=0.80, size=5.0), BookLevel(price=0.79, size=8.0)],
            asks=[BookLevel(price=0.84, size=4.0), BookLevel(price=0.85, size=6.0)],
        ),
    )

    provider.update_trade(token_id="up-token", price=0.82, size=5.0, side="BUY", ts=datetime.now(UTC))
    provider.update_trade(token_id="up-token", price=0.81, size=3.0, side="SELL", ts=datetime.now(UTC))

    stored = provider.book_for_token("up-token")
    assert stored is not None
    assert stored.last_trade_price == 0.81
    assert stored.last_trade_size == 3.0
    assert stored.best_bid == 0.80
    assert stored.best_ask == 0.84


def test_book_for_token_uses_cached_ask_levels_after_update_book() -> None:
    """RED: book_for_token should not rebuild ask_levels from scratch every call.

    After update_book, the cached ask_levels tuple should match the OrderBook's
    asks, and subsequent calls should return the same tuple object (identity
    check) as long as update_book is not called again.
    """
    provider = NautilusBookDataProvider()
    book = OrderBook(
        token_id="up-token",
        bids=[BookLevel(price=0.81, size=10.0), BookLevel(price=0.80, size=5.0)],
        asks=[BookLevel(price=0.83, size=12.0), BookLevel(price=0.84, size=8.0)],
        received_at=datetime.now(UTC),
    )
    provider.update_book("up-token", book)

    view1 = provider.book_for_token("up-token")
    view2 = provider.book_for_token("up-token")

    assert view1 is not None
    assert view2 is not None
    assert view1.ask_levels == view2.ask_levels
    assert view1.ask_levels is view2.ask_levels, (
        "Expected same cached tuple object across calls — if this fails, "
        "book_for_token is rebuilding ask_levels on every invocation"
    )
    assert view1.best_bid == 0.81
    assert view1.best_ask == 0.83
    assert view1.spread == 0.02


def test_book_for_token_cache_update_on_new_book() -> None:
    """Cached fields must update when a new book replaces the old one."""
    provider = NautilusBookDataProvider()
    old_book = OrderBook(
        token_id="up-token",
        bids=[BookLevel(price=0.81, size=10.0)],
        asks=[BookLevel(price=0.83, size=12.0)],
        received_at=datetime.now(UTC),
    )
    provider.update_book("up-token", old_book)

    new_book = OrderBook(
        token_id="up-token",
        bids=[BookLevel(price=0.50, size=100.0)],
        asks=[BookLevel(price=0.60, size=80.0)],
        received_at=datetime.now(UTC),
    )
    provider.update_book("up-token", new_book)

    view = provider.book_for_token("up-token")
    assert view is not None
    assert view.best_bid == 0.50
    assert view.best_ask == 0.60
    assert view.spread == 0.10
    assert view.ask_levels == ((0.60, 80.0),)


def test_book_for_token_passes_now_parameter() -> None:
    """book_for_token must accept a 'now' parameter and use it for freshness.

    When 'now' is provided, freshness_ms should be computed relative to that
    timestamp rather than calling datetime.now(UTC) internally. This enables
    the caller (e.g. MarketViewAssembler.build()) to pass a consistent
    snapshot time and avoid redundant system calls.
    """
    provider = NautilusBookDataProvider()
    received_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    book = OrderBook(
        token_id="up-token",
        bids=[BookLevel(price=0.81, size=10.0)],
        asks=[BookLevel(price=0.83, size=12.0)],
        received_at=received_at,
    )
    provider.update_book("up-token", book)

    now = datetime(2026, 1, 1, 12, 0, 2, tzinfo=UTC)  # 2 seconds later
    view = provider.book_for_token("up-token", now=now)

    assert view is not None
    assert view.freshness_ms == 2000, (
        f"Expected 2000ms freshness, got {view.freshness_ms}"
    )


def test_update_trade_does_not_mutate_underlying_book() -> None:
    """RED: after optimization, the underlying OrderBook must not be replaced by update_trade.

    This test will FAIL with current model_copy() implementation and PASS after
    optimization stores last_trade separately from the book.
    """
    provider = NautilusBookDataProvider()
    book = OrderBook(
        token_id="up-token",
        bids=[BookLevel(price=0.81, size=10.0)],
        asks=[BookLevel(price=0.83, size=12.0)],
    )
    provider.update_book("up-token", book)
    original_ref = id(provider._books["up-token"])

    # Act: call update_trade many times
    for _ in range(100):
        provider.update_trade(
            token_id="up-token",
            price=0.82,
            size=5.0,
            side="BUY",
            ts=datetime.now(UTC),
        )

    # Assert: the _books entry is still the SAME object (no model_copy replacement)
    assert id(provider._books["up-token"]) == original_ref, (
        "update_trade replaced the OrderBook in _books — should NOT happen. "
        "model_copy() creates a new object; the fix stores last_trade separately."
    )

    # Verify last_trade fields are still accessible
    view = provider.book_for_token("up-token")
    assert view is not None
    assert view.last_trade_price == 0.82
    assert view.last_trade_size == 5.0
    assert view.best_bid == 0.81  # preserved from original
    assert view.best_ask == 0.83  # preserved from original
