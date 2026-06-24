from __future__ import annotations

from typing import Any


class SnapshotService:
    name = "snapshot"

    def __init__(self, builder: Any) -> None:
        self.builder = builder

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def build(self, market: Any) -> Any:
        return await self.builder.build(market)

    def health(self) -> dict[str, object]:
        return {"name": self.name, "status": "ok", "metrics": {}}
