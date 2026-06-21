from __future__ import annotations

import httpx

from polysignal_lab.config import PolymarketDataConfig
from polysignal_lab.data.rate_limiter import AsyncRateLimiter
from polysignal_lab.domain.orderbook import OrderBook
from polysignal_lab.utils import utc_now


class PolymarketCLOBRestClient:
    def __init__(self, config: PolymarketDataConfig, client: httpx.AsyncClient | None = None):
        self.config = config
        self.client = client or httpx.AsyncClient(timeout=10.0)
        self.rate_limiter = AsyncRateLimiter(config.rest_rate_limit_per_sec)

    async def get_book(self, token_id: str) -> OrderBook:
        await self.rate_limiter.wait()
        response = await self.client.get(f"{self.config.clob_base_url}/book", params={"token_id": token_id})
        response.raise_for_status()
        return OrderBook.from_polymarket(response.json(), received_at=utc_now())

    async def get_books(self, token_ids: list[str]) -> list[OrderBook]:
        return [await self.get_book(token_id) for token_id in token_ids]
