"""
Input: __future__, __future__.annotations, json, httpx, pytest, polysignal_lab.config, polysignal_lab.config.Settings, polysignal_lab.nautilus_runtime.runtime_context_factory, polysignal_lab.nautilus_runtime.runtime_context_factory.build_nautilus_runtime_context
Output: test_runtime_uses_configured_telegram_publish_timeout, test_nautilus_runtime_does_not_construct_legacy_orderbook_for_telegram, test_telegram_qa_default_message_is_compact, test_missing_telegram_credentials_fail_live_publish, test_malformed_telegram_credentials_fail_live_publish, test_mocked_telegram_send_returns_sent_and_redacts_token, test_failed_telegram_response_redacts_token, test_invalid_publisher_credentials_fail_without_http_request, test_telegram_qa_records_actual_dry_run_invocation, test_telegram_qa_records_actual_live_failure_invocation
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

import json

import httpx
import pytest

from polysignal_lab.config import Settings, TelegramConfig
from polysignal_lab.nautilus_runtime.runtime_context_factory import build_nautilus_runtime_context
from polysignal_lab.publish.telegram_qa import DEFAULT_MESSAGE, parse_args, run
from polysignal_lab.publish.telegram_publisher import TelegramPublisher


VALID_TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
VALID_CHANNEL = "-1001234567890"


def _live_telegram_config() -> TelegramConfig:
    return TelegramConfig(
        enabled=True,
        dry_run=False,
        send_signals=True,
        send_consensus_signals=False,
        send_paper_results=False,
        send_daily_report=False,
        retry_attempts=1,
    )


def test_runtime_uses_configured_telegram_publish_timeout(tmp_path) -> None:
    settings = Settings(telegram=TelegramConfig(publish_timeout_sec=20.0))
    runtime = build_nautilus_runtime_context(settings, base_dir=tmp_path)

    assert runtime.publish_service.timeout_sec == 20.0


def test_nautilus_runtime_does_not_construct_legacy_orderbook_for_telegram(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    captured: dict[str, object] = {}

    class FakeBot:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("polysignal_lab.publish.telegram_bot.TelegramBotService", FakeBot)
    settings = Settings()
    settings.telegram.interactive_enabled = True

    build_nautilus_runtime_context(settings, base_dir=tmp_path)

    assert captured["books"] is None


def test_telegram_qa_default_message_is_compact() -> None:
    assert DEFAULT_MESSAGE == "<b>PolySignal Lab</b>\nTelegram QA send · Mode: Paper"
    assert parse_args([]).message == DEFAULT_MESSAGE
    for removed in (
        "No real order",
        "No profit guarantee",
        "Not financial advice",
        "Paper-only Telegram QA",
    ):
        assert removed not in DEFAULT_MESSAGE


async def test_missing_telegram_credentials_fail_live_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHANNEL_ID", raising=False)
    publisher = TelegramPublisher(_live_telegram_config())

    result = await publisher.send("Paper-only QA signal.", "signal", "sig1")

    assert result.status == "FAILED"
    assert result.error == "TELEGRAM_NOT_CONFIGURED"


async def test_malformed_telegram_credentials_fail_live_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "not-a-token")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "bad channel")
    publisher = TelegramPublisher(_live_telegram_config())

    result = await publisher.send("Paper-only QA signal.", "signal", "sig1")

    message = str(result.error)
    assert result.status == "FAILED"
    assert "bot_token" in message
    assert "channel_id" in message
    assert "not-a-token" not in message
    assert "bad channel" not in message


async def test_mocked_telegram_send_returns_sent_and_redacts_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 321}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    publisher = TelegramPublisher(
        _live_telegram_config(),
        bot_token=VALID_TOKEN,
        channel_id=VALID_CHANNEL,
        client=client,
    )

    result = await publisher.send("Paper-only QA signal. No profit guarantee.", "signal", "sig1")

    payload = result.as_dict()
    assert result.status == "SENT"
    assert result.telegram_message_id == "321"
    assert len(requests) == 1
    assert json.loads(requests[0].content)["chat_id"] == VALID_CHANNEL
    assert VALID_TOKEN not in json.dumps(payload, sort_keys=True)


async def test_failed_telegram_response_redacts_token() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(401, request=request, json={"ok": False})
        )
    )
    publisher = TelegramPublisher(
        _live_telegram_config(),
        bot_token=VALID_TOKEN,
        channel_id=VALID_CHANNEL,
        client=client,
    )

    result = await publisher.send("Paper-only QA signal.", "signal", "sig1")

    assert result.status == "FAILED"
    assert result.error is not None
    assert VALID_TOKEN not in result.error
    assert "1234...fghi" in result.error


async def test_invalid_publisher_credentials_fail_without_http_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    publisher = TelegramPublisher(
        _live_telegram_config(),
        bot_token="bad-token",
        channel_id="bad channel",
        client=client,
    )

    result = await publisher.send("Paper-only QA signal.", "signal", "sig1")

    assert result.status == "FAILED"
    assert result.error == "TELEGRAM_INVALID_CREDENTIALS: bot_token, channel_id"
    assert requests == []


async def test_telegram_qa_records_actual_dry_run_invocation(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_path = tmp_path / "actual-dry-run-evidence.json"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", VALID_CHANNEL)
    options = parse_args(["--evidence", str(evidence_path)])

    exit_code = await run(options)

    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert evidence["status"] == "DRY_RUN"
    assert evidence["dry_run"] is True
    assert evidence["mode"] == "dry_run"
    assert evidence["evidence_path"] == str(evidence_path)
    assert evidence["command"] == (
        ".venv/bin/python -m polysignal_lab.publish.telegram_qa "
        f"--evidence {evidence_path}"
    )


async def test_telegram_qa_records_actual_live_failure_invocation(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_path = tmp_path / "actual-live-failure-evidence.json"
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHANNEL_ID", raising=False)
    options = parse_args(["--live", "--evidence", str(evidence_path)])

    exit_code = await run(options)

    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert exit_code == 2
    assert evidence["status"] == "FAILED"
    assert evidence["dry_run"] is False
    assert evidence["mode"] == "live"
    assert evidence["evidence_path"] == str(evidence_path)
    assert evidence["command"] == (
        ".venv/bin/python -m polysignal_lab.publish.telegram_qa --live "
        f"--evidence {evidence_path}"
    )
    assert evidence["error"] == "TELEGRAM_NOT_CONFIGURED"
