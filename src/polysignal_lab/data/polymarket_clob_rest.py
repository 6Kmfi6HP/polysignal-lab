from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Protocol, cast

import httpx
from pydantic import JsonValue, TypeAdapter

from polysignal_lab.config import PolymarketDataConfig
from polysignal_lab.data.rate_limiter import AsyncRateLimiter
from polysignal_lab.domain.orderbook import OrderBook
from polysignal_lab.utils import safe_float, utc_now

JsonObject = dict[str, JsonValue]
JSON_VALUE_ADAPTER = TypeAdapter(JsonValue)


class _CLOBSDKClient(Protocol):
    def get_order_books(self, params: Sequence[object]) -> object: ...


class PolymarketCLOBRestClient:
    def __init__(
        self,
        config: PolymarketDataConfig,
        client: httpx.AsyncClient | None = None,
    ):
        self.config = config
        self.client = client or httpx.AsyncClient(timeout=10.0)
        self._sdk_client_instance: _CLOBSDKClient | None = None
        self.rate_limiter = AsyncRateLimiter(config.rest_rate_limit_per_sec)

    async def get_book(self, token_id: str) -> OrderBook:
        payload = await self._get_public_json("/book", token_id)
        return OrderBook.from_polymarket(payload, received_at=utc_now())

    async def get_mid(self, token_id: str) -> float | None:
        payload = await self._get_public_json("/midpoint", token_id)
        return safe_float(
            payload.get("mid_price") or payload.get("mid") or payload.get("midpoint")
        )

    async def get_spread(self, token_id: str) -> float | None:
        payload = await self._get_public_json("/spread", token_id)
        return safe_float(payload.get("spread"))

    async def get_books(self, token_ids: list[str]) -> list[OrderBook]:
        if not token_ids:
            return []
        try:
            return await self._get_books_batch(token_ids)
        except Exception:
            return [await self.get_book(token_id) for token_id in token_ids]

    async def _get_books_batch(self, token_ids: list[str]) -> list[OrderBook]:
        await self.rate_limiter.wait()
        received_at = utc_now()
        payloads = await asyncio.to_thread(self._get_order_books_batch_sync, token_ids)
        return [
            OrderBook.from_polymarket(
                _sdk_book_payload(payload), received_at=received_at
            )
            for payload in payloads
        ]

    def _get_order_books_batch_sync(self, token_ids: list[str]) -> list[object]:
        from py_clob_client_v2.clob_types import BookParams

        params = [BookParams(token_id=token_id) for token_id in token_ids]
        result = self._sdk_client().get_order_books(params)
        return result if isinstance(result, list) else []

    def _sdk_client(self) -> _CLOBSDKClient:
        if self._sdk_client_instance is None:
            from py_clob_client_v2 import ClobClient as PublicCLOBClient

            self._sdk_client_instance = PublicCLOBClient(
                host=self.config.clob_base_url,
                chain_id=self.config.chain_id,
            )
        return cast(_CLOBSDKClient, self._sdk_client_instance)

    async def _get_public_json(self, path: str, token_id: str) -> JsonObject:
        await self.rate_limiter.wait()
        response = await self.client.get(
            f"{self.config.clob_base_url}{path}", params={"token_id": token_id}
        )
        response.raise_for_status()
        payload = JSON_VALUE_ADAPTER.validate_python(response.json())
        return payload if isinstance(payload, dict) else {}


def _sdk_book_payload(book: object) -> JsonObject:
    if isinstance(book, dict):
        payload = book
    else:
        raw_payload = getattr(book, "__dict__", {})
        payload = raw_payload() if callable(raw_payload) else raw_payload
    validated = JSON_VALUE_ADAPTER.validate_python(payload)
    return cast(JsonObject, validated) if isinstance(validated, dict) else {}
