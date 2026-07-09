"""
Input: __future__, __future__.annotations, anyio.to_thread, typing, typing.Final, typing.Protocol, httpx, pydantic, pydantic.JsonValue, pydantic.TypeAdapter, polysignal_lab.config, polysignal_lab.data.orderbook_payload, polysignal_lab.data.rate_limiter, polysignal_lab.domain.orderbook, polysignal_lab.utils
Output: PolymarketCLOBRestClient
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""








from __future__ import annotations

from typing import TYPE_CHECKING, Final, Protocol

from anyio.to_thread import run_sync
import httpx
from pydantic import JsonValue, TypeAdapter, ValidationError

from polysignal_lab.config import PolymarketDataConfig
from polysignal_lab.data.orderbook_payload import (
    InvalidOrderBookPayload,
    JsonObject,
    json_object,
    parse_order_book_payload,
)
from polysignal_lab.data.rate_limiter import AsyncRateLimiter
from polysignal_lab.domain.orderbook import OrderBook
from polysignal_lab.utils import safe_float, utc_now

JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)

if TYPE_CHECKING:
    from py_clob_client_v2.clob_types import BookParams as _BookParams


class _RestResponse(Protocol):
    def raise_for_status(self) -> None: ...

    def json(self) -> JsonValue: ...


class _RestClient(Protocol):
    async def get(self, url: str, *, params: dict[str, str] | None = None) -> _RestResponse: ...


class _HttpxRestResponse:
    def __init__(self, response: httpx.Response) -> None:
        self._response: httpx.Response = response

    def raise_for_status(self) -> None:
        _ = self._response.raise_for_status()

    def json(self) -> JsonValue:
        return JSON_VALUE_ADAPTER.validate_python(self._response.json())


class _HttpxRestClient:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient = httpx.AsyncClient(timeout=10.0)

    async def get(self, url: str, *, params: dict[str, str] | None = None) -> _RestResponse:
        return _HttpxRestResponse(await self._client.get(url, params=params))


class _BatchOrderBookClient(Protocol):
    def get_order_books(self, params: list[_BookParams]) -> JsonValue: ...


class PolymarketCLOBRestClient:
    def __init__(
        self,
        config: PolymarketDataConfig,
        client: _RestClient | None = None,
    ) -> None:
        self.config: PolymarketDataConfig = config
        self.client: _RestClient = client or _HttpxRestClient()
        self._sdk_client_instance: _BatchOrderBookClient | None = None
        self.rate_limiter: AsyncRateLimiter = AsyncRateLimiter(config.rest_rate_limit_per_sec)

    async def get_book(self, token_id: str) -> OrderBook:
        payload = await self._get_public_json("/book", token_id)
        return parse_order_book_payload(payload, received_at=utc_now())

    async def get_mid(self, token_id: str) -> float | None:
        payload = await self._get_public_json("/midpoint", token_id)
        return safe_float(payload.get("mid_price") or payload.get("mid") or payload.get("midpoint"))

    async def get_spread(self, token_id: str) -> float | None:
        payload = await self._get_public_json("/spread", token_id)
        return safe_float(payload.get("spread"))

    async def get_books(self, token_ids: list[str]) -> list[OrderBook]:
        if not token_ids:
            return []
        try:
            return await self._get_books_batch(token_ids)
        except (InvalidOrderBookPayload, RuntimeError, ValidationError):
            return [await self.get_book(token_id) for token_id in token_ids]

    async def _get_books_batch(self, token_ids: list[str]) -> list[OrderBook]:
        await self.rate_limiter.wait()
        received_at = utc_now()
        payloads = await run_sync(self._get_order_books_batch_sync, token_ids)
        return [
            parse_order_book_payload(_sdk_book_payload(payload), received_at=received_at)
            for payload in payloads
        ]

    def _get_order_books_batch_sync(self, token_ids: list[str]) -> list[JsonValue]:
        from py_clob_client_v2.clob_types import BookParams

        params = [BookParams(token_id=token_id) for token_id in token_ids]
        payload = JSON_VALUE_ADAPTER.validate_python(self._sdk_client().get_order_books(params))
        return payload if isinstance(payload, list) else []

    def _sdk_client(self) -> _BatchOrderBookClient:
        if self._sdk_client_instance is None:
            from py_clob_client_v2 import ClobClient as PublicCLOBClient

            client: _BatchOrderBookClient = PublicCLOBClient(
                host=self.config.clob_base_url,
                chain_id=self.config.chain_id,
            )
            self._sdk_client_instance = client
        return self._sdk_client_instance

    async def _get_public_json(self, path: str, token_id: str) -> JsonObject:
        await self.rate_limiter.wait()
        response = await self.client.get(
            f"{self.config.clob_base_url}{path}",
            params={"token_id": token_id},
        )
        response.raise_for_status()
        payload = JSON_VALUE_ADAPTER.validate_python(response.json())
        return json_object(payload)


def _sdk_book_payload(book: JsonValue) -> JsonObject:
    return json_object(book)
