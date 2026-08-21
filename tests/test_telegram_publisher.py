from __future__ import annotations

from typing import Any, cast

import httpx

from polysignal_lab.config import TelegramConfig
from polysignal_lab.publish.telegram_publisher import TelegramPublisher

_TOKEN = "123456789:AA" + "x" * 30
_CHANNEL = "@mychannel"


def _publisher(
    *,
    bot_token: str | None = None,
    channel_id: str | None = None,
    client: Any = None,
) -> TelegramPublisher:
    return TelegramPublisher(
        TelegramConfig(enabled=True, dry_run=False),
        bot_token=bot_token,
        channel_id=channel_id,
        client=cast(httpx.AsyncClient, client) if client is not None else None,
    )


async def test_not_configured_failed_carries_sent_at() -> None:
    result = await _publisher().send("hello", "signal", "sig1")

    assert result.status == "FAILED"
    assert result.error == "TELEGRAM_NOT_CONFIGURED"
    assert result.sent_at


async def test_invalid_credentials_failed_carries_sent_at() -> None:
    result = await _publisher(
        bot_token="not-a-token",
        channel_id="@short",
    ).send("hello", "signal")

    assert result.status == "FAILED"
    assert "TELEGRAM_INVALID_CREDENTIALS" in (result.error or "")
    assert result.sent_at


async def test_http_error_failed_carries_sent_at() -> None:
    class BoomClient:
        async def post(self, *args: Any, **kwargs: Any) -> Any:
            raise httpx.ConnectError("boom")

    result = await _publisher(
        bot_token=_TOKEN,
        channel_id=_CHANNEL,
        client=BoomClient(),
    ).send("hello", "signal")

    assert result.status == "FAILED"
    assert result.error
    assert result.sent_at


async def test_sent_carries_sent_at() -> None:
    class OkClient:
        async def post(self, *args: Any, **kwargs: Any) -> Any:
            return _OkResponse()

    class _OkResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"ok": True, "result": {"message_id": 42}}

    result = await _publisher(
        bot_token=_TOKEN,
        channel_id=_CHANNEL,
        client=OkClient(),
    ).send("hello", "signal")

    assert result.status == "SENT"
    assert result.sent_at
