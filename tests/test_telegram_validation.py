from __future__ import annotations

import json

import httpx
import pytest

from polysignal_lab.app.scheduler import PolySignalScheduler, TelegramStartupConfigError
from polysignal_lab.config import Settings, TelegramConfig
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


def test_missing_telegram_credentials_fail_startup_when_publish_enabled(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: live Telegram signal publishing is enabled without exported env vars.
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHANNEL_ID", raising=False)
    settings = Settings(telegram=_live_telegram_config())
    scheduler = PolySignalScheduler(settings, base_dir=tmp_path)

    # When / Then: startup validation fails before a live publisher can run.
    with pytest.raises(TelegramStartupConfigError) as error:
        scheduler._validate_telegram_startup()
    assert "TELEGRAM_BOT_TOKEN" in str(error.value)
    assert "TELEGRAM_CHANNEL_ID" in str(error.value)


def test_malformed_telegram_credentials_fail_startup_when_publish_enabled(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: live Telegram publishing has malformed exported credentials.
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "not-a-token")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "bad channel")
    settings = Settings(telegram=_live_telegram_config())
    scheduler = PolySignalScheduler(settings, base_dir=tmp_path)

    # When / Then: validation rejects field names without leaking values.
    with pytest.raises(TelegramStartupConfigError) as error:
        scheduler._validate_telegram_startup()
    message = str(error.value)
    assert "TELEGRAM_BOT_TOKEN" in message
    assert "TELEGRAM_CHANNEL_ID" in message
    assert "not-a-token" not in message
    assert "bad channel" not in message


async def test_mocked_telegram_send_returns_sent_and_redacts_token() -> None:
    # Given: a live publisher with a mocked Telegram sendMessage endpoint.
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

    # When: a signal message is sent through the real publisher surface.
    result = await publisher.send("Paper-only QA signal. No profit guarantee.", "signal", "sig1")

    # Then: the send result is successful and the result payload has no full token.
    payload = result.as_dict()
    assert result.status == "SENT"
    assert result.telegram_message_id == "321"
    assert len(requests) == 1
    assert json.loads(requests[0].content)["chat_id"] == VALID_CHANNEL
    assert VALID_TOKEN not in json.dumps(payload, sort_keys=True)


async def test_failed_telegram_response_redacts_token() -> None:
    # Given: Telegram returns an HTTP failure that includes the token-bearing URL.
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

    # When: the publisher records the failed send.
    result = await publisher.send("Paper-only QA signal.", "signal", "sig1")

    # Then: the error is useful but does not contain the full token.
    assert result.status == "FAILED"
    assert result.error is not None
    assert VALID_TOKEN not in result.error
    assert "1234...fghi" in result.error


async def test_invalid_publisher_credentials_fail_without_http_request() -> None:
    # Given: malformed explicit credentials are passed to a live publisher.
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

    # When: a send is attempted.
    result = await publisher.send("Paper-only QA signal.", "signal", "sig1")

    # Then: malformed credentials fail locally and no token-bearing URL is requested.
    assert result.status == "FAILED"
    assert result.error == "TELEGRAM_INVALID_CREDENTIALS: bot_token, channel_id"
    assert requests == []


async def test_telegram_qa_records_actual_dry_run_invocation(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: dry-run QA writes to a caller-selected evidence path.
    evidence_path = tmp_path / "actual-dry-run-evidence.json"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", VALID_CHANNEL)
    options = parse_args(["--evidence", str(evidence_path)])

    # When: the QA command runs.
    exit_code = await run(options)

    # Then: the artifact records the actual mode and evidence target.
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
    # Given: live QA is requested without exported Telegram credentials.
    evidence_path = tmp_path / "actual-live-failure-evidence.json"
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHANNEL_ID", raising=False)
    options = parse_args(["--live", "--evidence", str(evidence_path)])

    # When: the QA command runs.
    exit_code = await run(options)

    # Then: the failure artifact still records the actual live invocation.
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
