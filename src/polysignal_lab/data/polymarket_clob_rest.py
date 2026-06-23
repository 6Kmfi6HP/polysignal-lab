from __future__ import annotations

import httpx
from pydantic import JsonValue, TypeAdapter

from polysignal_lab.config import PolymarketDataConfig
from polysignal_lab.data.rate_limiter import AsyncRateLimiter
from polysignal_lab.domain.orderbook import OrderBook
from polysignal_lab.utils import safe_float, utc_now

JsonObject = dict[str, JsonValue]
JSON_VALUE_ADAPTER = TypeAdapter(JsonValue)


class PolymarketCLOBRestClient:
    def __init__(self, config: PolymarketDataConfig, client: httpx.AsyncClient | None = None):
        self.config = config
        self.client = client or httpx.AsyncClient(timeout=10.0)
        self.rate_limiter = AsyncRateLimiter(config.rest_rate_limit_per_sec)

    async def get_book(self, token_id: str) -> OrderBook:
        payload = await self._get_public_json("/book", token_id)
        return OrderBook.from_polymarket(payload, received_at=utc_now())

    async def get_mid(self, token_id: str) -> float | None:
        payload = await self._get_public_json("/midpoint", token_id)
        return safe_float(payload.get("mid_price") or payload.get("mid") or payload.get("midpoint"))

    async def get_spread(self, token_id: str) -> float | None:
        payload = await self._get_public_json("/spread", token_id)
        return safe_float(payload.get("spread"))

    async def get_books(self, token_ids: list[str]) -> list[OrderBook]:
        return [await self.get_book(token_id) for token_id in token_ids]

    async def _get_public_json(self, path: str, token_id: str) -> JsonObject:
        await self.rate_limiter.wait()
        response = await self.client.get(f"{self.config.clob_base_url}{path}", params={"token_id": token_id})
        response.raise_for_status()
        payload = JSON_VALUE_ADAPTER.validate_python(response.json())
        return payload if isinstance(payload, dict) else {}
