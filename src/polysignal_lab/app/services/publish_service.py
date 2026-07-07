"""
Input: __future__, __future__.annotations, asyncio, collections.abc, collections.abc.Mapping, typing, typing.Any
Output: PublishService
Pos: Service Layer - Business logic

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any


class PublishService:
    name = "publish"

    def __init__(
        self,
        formatter: Any,
        publisher: Any,
        persistence: Any,
        *,
        timeout_sec: float = 5.0,
    ) -> None:
        self.formatter = formatter
        self.publisher = publisher
        self.persistence = persistence
        self.timeout_sec = timeout_sec

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    def health(self) -> dict[str, object]:
        return {"name": self.name, "status": "ok", "metrics": {"timeout_sec": self.timeout_sec}}

    async def publish_signal(self, signal: Any, stake_usdc: float) -> Any:
        message = self.formatter.signal_message(signal, stake_usdc)
        publish = await asyncio.wait_for(
            self.publisher.send(message, "signal", signal.signal_id),
            timeout=self.timeout_sec,
        )
        self._persist_publish(publish)
        return publish

    async def publish_paper_result(self, result: Any) -> Any:
        message = self.formatter.result_message(result)
        publish = await asyncio.wait_for(
            self.publisher.send(message, "paper_result", result.signal_id),
            timeout=self.timeout_sec,
        )
        self._persist_publish(publish)
        return publish

    async def publish_daily_report(self, report: Any) -> Any:
        message = self.formatter.daily_report_message(report)
        publish = await asyncio.wait_for(
            self.publisher.send(message, "daily_report", None),
            timeout=self.timeout_sec,
        )
        self._persist_publish(publish)
        return publish

    async def publish_nautilus_paper_fill(self, fill: Mapping[str, object]) -> Any:
        message = self.formatter.nautilus_fill_message(dict(fill))
        signal_id = fill.get("signal_id")
        publish = await asyncio.wait_for(
            self.publisher.send(
                message,
                "nautilus_paper_fill",
                str(signal_id) if isinstance(signal_id, str) and signal_id else None,
            ),
            timeout=self.timeout_sec,
        )
        self._persist_publish(publish)
        return publish

    def _persist_publish(self, publish: Any) -> None:
        payload = publish.as_dict()
        self.persistence.append_log("telegram_publishes", payload)
        self.persistence.insert_telegram_publish(payload)
