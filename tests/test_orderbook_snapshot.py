"""
Input: __future__, __future__.annotations, datetime, datetime.timedelta, polysignal_lab.domain.orderbook, polysignal_lab.domain.orderbook.OrderBook, polysignal_lab.utils, polysignal_lab.utils.utc_now, factories, factories.BookFactoryConfig
Output: test_orderbook_best_bid_ask_spread_depth, test_orderbook_from_polymarket_payload, test_staleness_detection, test_snapshot_builder_derived_metrics
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from datetime import timedelta

from polysignal_lab.domain.orderbook import OrderBook
from polysignal_lab.utils import utc_now
from factories import BookFactoryConfig, sample_book


def test_orderbook_best_bid_ask_spread_depth():
    book = sample_book("token", BookFactoryConfig(ask=0.60, bid=0.57, size=100))
    assert book.best_ask == 0.60
    assert book.best_bid == 0.57
    assert round(book.spread, 2) == 0.03
    assert book.depth_until(0.65) > 60


def test_orderbook_from_polymarket_payload():
    payload = {
        "market": "m1",
        "asset_id": "tok1",
        "bids": [{"price": "0.45", "size": "100"}],
        "asks": [{"price": "0.46", "size": "150"}],
        "last_trade_price": "0.455",
    }
    book = OrderBook.from_polymarket(payload)
    assert book.market_id == "m1"
    assert book.token_id == "tok1"
    assert book.best_bid == 0.45
    assert book.best_ask == 0.46


def test_staleness_detection():
    book = sample_book("token")
    assert book.is_fresh(1500)
    old = book.model_copy(update={"received_at": utc_now() - timedelta(seconds=5)})
    assert not old.is_fresh(1500)


async def test_snapshot_builder_derived_metrics(snapshot):
    assert snapshot.ask_sum == 1.0
    assert round(snapshot.ask_skew, 2) == 0.64
    assert snapshot.favorite_side.value == "UP"
    assert snapshot.metrics["diff_usd"] == 120.0
    assert snapshot.freshness.max_ms is not None
