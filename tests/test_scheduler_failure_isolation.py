"""
Input: asyncio, pytest, polysignal_lab.app.services.publish_service, polysignal_lab.app.services.publish_service.PublishService
Output: test_publish_timeout_does_not_hang_signal_processing, _Formatter, _SlowPublisher, _Persistence, _Signal
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""









import asyncio

import pytest

from polysignal_lab.app.services.publish_service import PublishService


class _Formatter:
    def signal_message(self, signal, stake_usdc: float) -> str:
        return "signal-message"


class _SlowPublisher:
    async def send(self, message: str, message_type: str, signal_id: str):
        await asyncio.sleep(10)


class _Persistence:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def append_log(self, stream, payload):
        self.rows.append({"stream": stream, "payload": payload})


class _Signal:
    signal_id = "sig-1"


async def test_publish_timeout_does_not_hang_signal_processing() -> None:
    service = PublishService(
        formatter=_Formatter(),
        publisher=_SlowPublisher(),
        persistence=_Persistence(),
        timeout_sec=0.01,
    )

    with pytest.raises(TimeoutError):
        await service.publish_signal(_Signal(), stake_usdc=10.0)
