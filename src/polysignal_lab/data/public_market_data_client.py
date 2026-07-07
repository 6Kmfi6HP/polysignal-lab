"""
Input: __future__, __future__.annotations, typing, typing.Protocol, polysignal_lab.domain.orderbook, polysignal_lab.domain.orderbook.OrderBook
Output: PublicMarketDataClient
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from typing import Protocol

from polysignal_lab.domain.orderbook import OrderBook


class PublicMarketDataClient(Protocol):
    async def get_book(self, token_id: str) -> OrderBook: ...
    async def get_books(self, token_ids: list[str]) -> list[OrderBook]: ...
    async def get_mid(self, token_id: str) -> float | None: ...
    async def get_spread(self, token_id: str) -> float | None: ...
