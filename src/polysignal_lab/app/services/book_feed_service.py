from __future__ import annotations

import asyncio
import logging
from typing import Any

from polysignal_lab.config import PolymarketDataConfig


class BookFeedService:
    name = "book_feed"

    def __init__(
        self,
        config: PolymarketDataConfig,
        market_data: Any,
        books: Any,
        websocket: Any | None = None,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.market_data = market_data
        self.books = books
        self.websocket = websocket
        self.logger = logger or logging.getLogger("polysignal_lab.scheduler.book_feed")
        self.tasks: list[asyncio.Task] = []
        self.market_task: asyncio.Task | None = None
        self.token_ids: tuple[str, ...] = ()
        self.started = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        if self.websocket is not None:
            self.websocket.stop()
        for task in list(self.tasks):
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self.tasks.clear()
        self.market_task = None
        self.token_ids = ()
        self.started = False

    async def stop_subscription(self) -> None:
        if self.market_task is None and not self.token_ids:
            return
        if self.websocket is not None:
            self.websocket.stop()
        task = self.market_task
        self.market_task = None
        self.token_ids = ()
        if task is None:
            return
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if task in self.tasks:
            self.tasks.remove(task)

    async def sync_subscription(self, token_ids: tuple[str, ...]) -> None:
        if self.config.use_market_ws:
            if not token_ids:
                await self.stop_subscription()
                self.logger.info(
                    "No token IDs available for Polymarket WebSocket, falling back to REST polling"
                )
                return
            if (
                token_ids == self.token_ids
                and self.market_task is not None
                and not self.market_task.done()
            ):
                return
            await self.stop_subscription()
            if self.websocket is None:
                return
            self.logger.info(
                "Starting Polymarket WebSocket with %d token subscriptions", len(token_ids)
            )
            task = asyncio.create_task(self.websocket.subscribe(list(token_ids)))
            self.market_task = task
            self.token_ids = token_ids
            self.tasks.append(task)
        else:
            await self.stop_subscription()
            self.logger.info("Polymarket WebSocket disabled in config, using REST polling")

    async def reseed(self, token_ids: list[str]) -> None:
        refreshed: set[str] = set()
        try:
            for book in await self.market_data.get_books(token_ids):
                if hasattr(self.books, "update_from_snapshot"):
                    self.books.update_from_snapshot(book)
                else:
                    self.books.update(book)
                refreshed.add(book.token_id)
        except Exception as exc:
            self.logger.exception("Failed to reseed order books on WebSocket reconnect: %s", exc)
        finally:
            for token_id in set(token_ids) - refreshed:
                self.books.mark_stale(token_id, "RECONNECT_RESEED_FAILED")

    def health(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": "ok",
            "metrics": {"tasks": len(self.tasks), "subscriptions": len(self.token_ids)},
        }
