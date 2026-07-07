"""
Input: __future__, __future__.annotations, inspect, pytest, polysignal_lab.config, polysignal_lab.config.PolymarketDataConfig, polysignal_lab.data.polymarket_clob_rest, polysignal_lab.data.polymarket_clob_rest.PolymarketCLOBRestClient, polysignal_lab.domain.orderbook, polysignal_lab.domain.orderbook.OrderBook
Output: test_clob_rest_constructor_does_not_expose_sdk_client, test_clob_rest_instance_does_not_expose_sdk_client, test_get_books_uses_batch_path, test_get_books_falls_back_to_single_book_requests_when_batch_fails
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations
import inspect


import pytest

from polysignal_lab.config import PolymarketDataConfig
from polysignal_lab.data.polymarket_clob_rest import PolymarketCLOBRestClient
from polysignal_lab.domain.orderbook import OrderBook


def test_clob_rest_constructor_does_not_expose_sdk_client() -> None:
    params = inspect.signature(PolymarketCLOBRestClient).parameters
    assert "sdk_client" not in params
    assert "key" not in params
    assert "private_key" not in params
    assert "creds" not in params


def test_clob_rest_instance_does_not_expose_sdk_client() -> None:
    client = PolymarketCLOBRestClient(PolymarketDataConfig())
    assert "sdk_client" not in vars(client)




@pytest.mark.asyncio
async def test_get_books_uses_batch_path(monkeypatch: pytest.MonkeyPatch) -> None:
    client = PolymarketCLOBRestClient(PolymarketDataConfig())
    requested_token_ids: list[str] = []

    def fake_batch(token_ids: list[str]) -> list[object]:
        requested_token_ids.extend(token_ids)
        return [
            {
                "market": "market-1",
                "asset_id": "token-1",
                "bids": [{"price": "0.42", "size": "100"}],
                "asks": [{"price": "0.45", "size": "80"}],
                "last_trade_price": "0.43",
                "min_order_size": "1",
                "tick_size": "0.01",
                "timestamp": "1234567890",
            },
            {
                "market": "market-2",
                "asset_id": "token-2",
                "bids": [{"price": "0.55", "size": "40"}],
                "asks": [{"price": "0.58", "size": "60"}],
                "last_trade_price": "0.56",
                "min_order_size": "1",
                "tick_size": "0.01",
                "timestamp": "1234567891",
            },
        ]

    monkeypatch.setattr(client, "_get_order_books_batch_sync", fake_batch)

    books = await client.get_books(["token-1", "token-2"])

    assert requested_token_ids == ["token-1", "token-2"]
    assert [book.token_id for book in books] == ["token-1", "token-2"]
    assert books[0].best_bid == 0.42
    assert books[1].best_ask == 0.58


@pytest.mark.asyncio
async def test_get_books_falls_back_to_single_book_requests_when_batch_fails() -> None:
    class FallbackRestClient(PolymarketCLOBRestClient):
        def __init__(self) -> None:
            super().__init__(PolymarketDataConfig())
            self.single_requests: list[str] = []

        def _get_order_books_batch_sync(self, token_ids: list[str]) -> list[object]:
            raise RuntimeError("batch unavailable")

        async def get_book(self, token_id: str) -> OrderBook:
            self.single_requests.append(token_id)
            return OrderBook.from_polymarket(
                {
                    "market": f"market-{token_id}",
                    "asset_id": token_id,
                    "bids": [{"price": "0.40", "size": "10"}],
                    "asks": [{"price": "0.41", "size": "12"}],
                }
            )

    client = FallbackRestClient()

    books = await client.get_books(["token-a", "token-b"])

    assert client.single_requests == ["token-a", "token-b"]
    assert [book.token_id for book in books] == ["token-a", "token-b"]
