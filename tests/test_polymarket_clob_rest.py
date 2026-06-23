from __future__ import annotations
from collections.abc import Sequence
from typing import Protocol, cast


import pytest

from polysignal_lab.config import PolymarketDataConfig
from polysignal_lab.data.polymarket_clob_rest import PolymarketCLOBRestClient
from polysignal_lab.domain.orderbook import OrderBook


class TokenParam(Protocol):
    token_id: str


class FakeBatchClient:
    def __init__(self) -> None:
        self.params: Sequence[TokenParam] = ()

    def get_order_books(self, params: Sequence[object]) -> list[dict[str, object]]:
        self.params = [
            cast(TokenParam, param)
            for param in params
            if isinstance(getattr(param, "token_id", None), str)
        ]
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


class FailingBatchClient:
    def get_order_books(self, params: Sequence[object]) -> list[dict[str, object]]:
        raise RuntimeError("batch unavailable")


@pytest.mark.asyncio
async def test_get_books_uses_sdk_batch_request() -> None:
    sdk_client = FakeBatchClient()
    client = PolymarketCLOBRestClient(PolymarketDataConfig(), sdk_client=sdk_client)

    books = await client.get_books(["token-1", "token-2"])

    assert [param.token_id for param in sdk_client.params] == ["token-1", "token-2"]
    assert [book.token_id for book in books] == ["token-1", "token-2"]
    assert books[0].best_bid == 0.42
    assert books[1].best_ask == 0.58


@pytest.mark.asyncio
async def test_get_books_falls_back_to_single_book_requests_when_batch_fails() -> None:
    class FallbackRestClient(PolymarketCLOBRestClient):
        def __init__(self) -> None:
            super().__init__(PolymarketDataConfig(), sdk_client=FailingBatchClient())
            self.single_requests: list[str] = []

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
