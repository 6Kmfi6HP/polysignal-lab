"""
Input: __future__, __future__.annotations, asyncio, collections.abc, collections.abc.Callable, collections.abc.Mapping, typing, typing.Any, polysignal_lab.domain.paper_result, polysignal_lab.domain.paper_result.parse_paper_trade_result_row, polysignal_lab.paper.event_projection.normalize_paper_fill
Output: PublishService
Pos: Service Layer - Business logic

🔄 Self-reference: When this file changes, update this header
"""






from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any

from polysignal_lab.domain.paper_result import parse_paper_trade_result_row
from polysignal_lab.paper.event_projection import normalize_paper_fill


class PublishService:
    name = "publish"

    def __init__(
        self,
        formatter: Any,
        publisher: Any,
        persistence: Any,
        *,
        timeout_sec: float = 5.0,
        market_lookup: Callable[[Mapping[str, object]], object | None] | None = None,
    ) -> None:
        self.formatter = formatter
        self.publisher = publisher
        self.persistence = persistence
        self.timeout_sec = timeout_sec
        self.market_lookup = market_lookup

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

    async def publish_paper_result(self, result: Mapping[str, object]) -> Any:
        payload = parse_paper_trade_result_row(result)
        message = self.formatter.result_message(payload)
        signal_id = payload.get("signal_id")
        publish = await asyncio.wait_for(
            self.publisher.send(message, "paper_result", str(signal_id) if signal_id else None),
            timeout=self.timeout_sec,
        )
        self._persist_publish(publish)
        return publish

    async def deliver_daily_report(self, report: Mapping[str, object]) -> Any:
        payload = report if isinstance(report, Mapping) else report.model_dump(mode="json")
        message = self.formatter.daily_report_message(payload)
        return await asyncio.wait_for(
            self.publisher.send(message, "daily_report", None),
            timeout=self.timeout_sec,
        )

    async def publish_daily_report(self, report: Mapping[str, object]) -> Any:
        publish = await self.deliver_daily_report(report)
        self._persist_publish(publish)
        return publish

    async def publish_nautilus_paper_fill(self, fill: Mapping[str, object]) -> Any:
        market = self.market_lookup(fill) if self.market_lookup is not None else None
        payload = normalize_paper_fill(fill, market=market)
        message = self.formatter.nautilus_fill_message(payload)
        signal_id = payload.get("signal_id")
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
