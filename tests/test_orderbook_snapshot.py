"""
Input: __future__, __future__.annotations, datetime, datetime.timedelta, pytest, polysignal_lab.data.orderbook_payload, polysignal_lab.utils, polysignal_lab.utils.utc_now, factories, factories.BookFactoryConfig
Output: test_orderbook_best_bid_ask_spread_depth, test_parse_orderbook_from_polymarket_payload, test_parse_orderbook_rejects_missing_token_id, test_parse_orderbook_ignores_invalid_levels, test_staleness_detection, test_snapshot_builder_derived_metrics
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from datetime import timedelta

import pytest

from polysignal_lab.data.orderbook_payload import (
    InvalidOrderBookPayload,
    JsonObject,
    parse_order_book_payload,
)
from polysignal_lab.utils import utc_now
from factories import BookFactoryConfig, sample_book


def test_orderbook_best_bid_ask_spread_depth():
    book = sample_book("token", BookFactoryConfig(ask=0.60, bid=0.57, size=100))
    assert book.best_ask == 0.60
    assert book.best_bid == 0.57
    assert book.spread is not None
    assert round(book.spread, 2) == 0.03
    assert book.depth_until(0.65) > 60


def test_parse_orderbook_from_polymarket_payload():
    payload: JsonObject = {
        "market": "m1",
        "asset_id": "tok1",
        "bids": [{"price": "0.45", "size": "100"}],
        "asks": [{"price": "0.46", "size": "150"}],
        "last_trade_price": "0.455",
    }
    book = parse_order_book_payload(payload)
    assert book.market_id == "m1"
    assert book.token_id == "tok1"
    assert book.best_bid == 0.45
    assert book.best_ask == 0.46


def test_parse_orderbook_rejects_missing_token_id():
    with pytest.raises(InvalidOrderBookPayload):
        _ = parse_order_book_payload({"bids": [], "asks": []})


def test_parse_orderbook_ignores_invalid_levels():
    book = parse_order_book_payload(
        {
            "asset_id": "tok1",
            "bids": [
                {"price": "-0.1", "size": "10"},
                {"price": "NaN", "size": "10"},
                {"price": "0.44", "size": "0"},
                {"price": "0.45", "size": "10"},
            ],
            "asks": [
                {"price": "0", "size": "10"},
                {"price": "0.47", "size": "-1"},
                {"price": "0.48", "size": "12"},
            ],
        }
    )

    assert [(level.price, level.size) for level in book.bids] == [(0.45, 10.0)]
    assert [(level.price, level.size) for level in book.asks] == [(0.48, 12.0)]


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
