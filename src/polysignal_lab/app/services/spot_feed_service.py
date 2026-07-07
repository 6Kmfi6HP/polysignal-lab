"""
Input: __future__, __future__.annotations, asyncio, logging, typing, typing.Any
Output: SpotFeedService
Pos: Service Layer - Business logic

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import asyncio
import logging
from typing import Any


class SpotFeedService:
    name = "spot_feed"

    def __init__(
        self,
        feed: Any,
        *,
        enabled: bool = True,
        logger: logging.Logger | None = None,
    ) -> None:
        self.feed = feed
        self.enabled = enabled
        self.logger = logger or logging.getLogger("polysignal_lab.scheduler.spot_feed")
        self.task: asyncio.Task | None = None

    async def start(self) -> None:
        if not self.enabled:
            self.logger.info("Spot WebSocket feed disabled in config")
            return
        if self.task is None or self.task.done():
            self.logger.info("Starting Spot WebSocket feed")
            self.task = asyncio.create_task(self.feed.run())

    async def stop(self) -> None:
        self.feed.stop()
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):
                pass
        self.task = None

    def tasks(self) -> list[asyncio.Task]:
        return [self.task] if self.task is not None else []

    def health(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": "ok",
            "metrics": {"running": bool(self.task and not self.task.done())},
        }
