"""
Input: __future__, __future__.annotations, re, dataclasses, dataclasses.dataclass, typing, typing.Final, anyio, httpx, pydantic
Output: invalid_telegram_credential_fields, PublishResult, TelegramPublisher
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

import anyio
import httpx
from pydantic import JsonValue, TypeAdapter

from polysignal_lab.config import TelegramConfig
from polysignal_lab.utils import mask_secret, new_id, redact_text, utc_iso


TELEGRAM_RESPONSE_ADAPTER: Final = TypeAdapter(dict[str, JsonValue])
TELEGRAM_TOKEN_RE: Final = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,}$")
TELEGRAM_CHANNEL_RE: Final = re.compile(r"^(@[A-Za-z][A-Za-z0-9_]{4,31}|-?\d{5,20})$")


@dataclass
class PublishResult:
    publish_id: str
    message_type: str
    status: str
    signal_id: str | None = None
    telegram_message_id: str | None = None
    error: str | None = None
    sent_at: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "publish_id": self.publish_id,
            "message_type": self.message_type,
            "status": self.status,
            "signal_id": self.signal_id,
            "telegram_message_id": self.telegram_message_id,
            "error": self.error,
            "sent_at": self.sent_at,
        }


def invalid_telegram_credential_fields(
    bot_token: str | None, channel_id: str | None
) -> tuple[str, ...]:
    invalid: list[str] = []
    if bot_token and not TELEGRAM_TOKEN_RE.fullmatch(bot_token):
        invalid.append("bot_token")
    if channel_id and not TELEGRAM_CHANNEL_RE.fullmatch(channel_id):
        invalid.append("channel_id")
    return tuple(invalid)


class TelegramPublisher:
    def __init__(
        self,
        config: TelegramConfig,
        bot_token: str | None = None,
        channel_id: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        self.bot_token = bot_token or config.resolved_bot_token
        self.channel_id = channel_id or config.resolved_channel_id
        self.client = client or httpx.AsyncClient(timeout=10.0)

    async def send(
        self,
        message: str,
        message_type: str,
        signal_id: str | None = None,
        *,
        publish_id: str | None = None,
    ) -> PublishResult:
        publish_id = publish_id or new_id("tg")
        if not self.config.enabled or self.config.dry_run:
            return PublishResult(publish_id=publish_id, message_type=message_type, status="DRY_RUN", signal_id=signal_id, sent_at=utc_iso())
        if not self.bot_token or not self.channel_id:
            return PublishResult(publish_id=publish_id, message_type=message_type, status="FAILED", signal_id=signal_id, error="TELEGRAM_NOT_CONFIGURED")
        invalid = invalid_telegram_credential_fields(self.bot_token, self.channel_id)
        if invalid:
            return PublishResult(
                publish_id=publish_id,
                message_type=message_type,
                status="FAILED",
                signal_id=signal_id,
                error=f"TELEGRAM_INVALID_CREDENTIALS: {', '.join(invalid)}",
            )
        text = message[: self.config.max_message_chars]
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": self.channel_id, "text": text, "parse_mode": self.config.parse_mode}
        last_error: str | None = None
        for attempt in range(max(1, self.config.retry_attempts)):
            try:
                response = await self.client.post(url, json=payload)
                response.raise_for_status()
                data = TELEGRAM_RESPONSE_ADAPTER.validate_python(response.json())
                result = data.get("result")
                msg_id = ""
                if isinstance(result, dict):
                    message_id = result.get("message_id")
                    if message_id is not None:
                        msg_id = str(message_id)
                return PublishResult(publish_id=publish_id, message_type=message_type, status="SENT", signal_id=signal_id, telegram_message_id=msg_id, sent_at=utc_iso())
            except (httpx.HTTPError, ValueError) as exc:
                last_error = _redact_telegram_error(exc, self.bot_token)
                await anyio.sleep(min(2 ** attempt, 5))
        return PublishResult(publish_id=publish_id, message_type=message_type, status="FAILED", signal_id=signal_id, error=last_error)


def _redact_telegram_error(exc: httpx.HTTPError | ValueError, bot_token: str) -> str:
    return redact_text(str(exc).replace(bot_token, mask_secret(bot_token)))
