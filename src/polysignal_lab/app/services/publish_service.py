"""
Input: __future__, __future__.annotations, asyncio, collections.abc, collections.abc.Mapping, typing, typing.Any, polysignal_lab.domain.paper_result, polysignal_lab.domain.paper_result.parse_paper_trade_result_row
Output: PublishService, _nautilus_fill_payload
Pos: Service Layer - Business logic

🔄 Self-reference: When this file changes, update this header
"""






from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from polysignal_lab.domain.paper_result import parse_paper_trade_result_row


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

    async def publish_daily_report(self, report: Mapping[str, object]) -> Any:
        payload = report if isinstance(report, Mapping) else report.model_dump(mode="json")
        message = self.formatter.daily_report_message(payload)
        publish = await asyncio.wait_for(
            self.publisher.send(message, "daily_report", None),
            timeout=self.timeout_sec,
        )
        self._persist_publish(publish)
        return publish

    async def publish_nautilus_paper_fill(self, fill: Mapping[str, object]) -> Any:
        payload = _nautilus_fill_payload(fill)
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


def _nautilus_fill_payload(fill: Mapping[str, object]) -> dict[str, object]:
    payload = dict(fill)
    metrics = payload.get("metrics")
    if isinstance(metrics, Mapping):
        for key in (
            "strategy",
            "asset",
            "timeframe",
            "market_id",
            "market_slug",
            "condition_id",
            "token_id",
            "signal_id",
            "side",
        ):
            value = metrics.get(key)
            if payload.get(key) in (None, "") and value not in (None, ""):
                payload[key] = value
    fill_price = _row_float(payload, "fill_price", "price", "last_px")
    shares = _row_float(payload, "shares", "quantity", "last_qty")
    stake = _row_float(payload, "stake_usdc", "notional")
    if stake is None and fill_price is not None and shares is not None:
        stake = fill_price * shares
    _fill_missing(payload, "paper_fill_id", _row_text(payload, "paper_fill_id", "trade_id", "fill_id"))
    _fill_missing(payload, "paper_order_id", _row_text(payload, "paper_order_id", "client_order_id"))
    _fill_missing(payload, "signal_id", _row_text(payload, "signal_id"))
    _fill_missing(payload, "side", _row_text(payload, "side"))
    if fill_price is not None:
        payload["fill_price"] = fill_price
    if shares is not None:
        payload["shares"] = shares
    if stake is not None:
        payload["stake_usdc"] = stake
    return payload


def _row_text(row: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _row_float(row: Mapping[str, object], *keys: str) -> float | None:
    for key in keys:
        value = row.get(key)
        if value is None or value == "":
            continue
        try:
            return float(str(value))
        except (TypeError, ValueError):
            continue
    return None


def _fill_missing(payload: dict[str, object], key: str, value: object) -> None:
    current = payload.get(key)
    if current is None or current == "":
        if value not in (None, ""):
            payload[key] = value
