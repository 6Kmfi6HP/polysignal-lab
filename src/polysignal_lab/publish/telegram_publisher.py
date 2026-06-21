from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

from polysignal_lab.config import TelegramConfig
from polysignal_lab.utils import mask_secret, new_id, utc_iso, utc_now


@dataclass
class PublishResult:
    publish_id: str
    message_type: str
    status: str
    signal_id: str | None = None
    telegram_message_id: str | None = None
    error: str | None = None
    sent_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class TelegramPublisher:
    def __init__(self, config: TelegramConfig, bot_token: str | None = None, channel_id: str | None = None, client: httpx.AsyncClient | None = None):
        self.config = config
        self.bot_token = bot_token or config.resolved_bot_token
        self.channel_id = channel_id or config.resolved_channel_id
        self.client = client or httpx.AsyncClient(timeout=10.0)

    async def send(self, message: str, message_type: str, signal_id: str | None = None) -> PublishResult:
        publish_id = new_id("tg")
        if not self.config.enabled or self.config.dry_run:
            return PublishResult(publish_id=publish_id, message_type=message_type, status="DRY_RUN", signal_id=signal_id, sent_at=utc_iso())
        if not self.bot_token or not self.channel_id:
            return PublishResult(publish_id=publish_id, message_type=message_type, status="FAILED", signal_id=signal_id, error="TELEGRAM_NOT_CONFIGURED")
        text = message[: self.config.max_message_chars]
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": self.channel_id, "text": text, "parse_mode": self.config.parse_mode}
        last_error: str | None = None
        for attempt in range(max(1, self.config.retry_attempts)):
            try:
                response = await self.client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                msg_id = str((data.get("result") or {}).get("message_id", ""))
                return PublishResult(publish_id=publish_id, message_type=message_type, status="SENT", signal_id=signal_id, telegram_message_id=msg_id, sent_at=utc_iso())
            except Exception as exc:
                last_error = str(exc).replace(self.bot_token, mask_secret(self.bot_token)) if self.bot_token else str(exc)
                await asyncio.sleep(min(2 ** attempt, 5))
        return PublishResult(publish_id=publish_id, message_type=message_type, status="FAILED", signal_id=signal_id, error=last_error)
