"""
Input: __future__, __future__.annotations, json, shlex, types, types.SimpleNamespace, httpx, pytest, polysignal_lab.config, polysignal_lab.config.Settings, polysignal_lab.config.TelegramConfig
Output: test_runtime_uses_configured_telegram_publish_timeout, test_runtime_owns_scoped_signal_publisher_lifecycle, test_nautilus_runtime_context_has_no_parallel_market_registry, test_nautilus_runtime_rejects_unreachable_interactive_telegram_control, test_telegram_qa_default_message_is_compact, test_missing_telegram_credentials_fail_live_publish, test_malformed_telegram_credentials_fail_live_publish, test_mocked_telegram_send_returns_sent_and_redacts_token, test_daily_report_publish_id_is_stable_across_retries, test_failed_telegram_response_redacts_token
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

import json
import shlex
from types import SimpleNamespace

import httpx
import pytest

from polysignal_lab.config import Settings, TelegramConfig
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_runtime.runtime_context_factory import build_nautilus_runtime_context
from polysignal_lab.publish.telegram_qa import DEFAULT_MESSAGE, parse_args, run
from polysignal_lab.publish.telegram_publisher import PublishResult, TelegramPublisher


VALID_TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
VALID_CHANNEL = "-1001234567890"


def _live_telegram_config() -> TelegramConfig:
    return TelegramConfig(
        enabled=True,
        dry_run=False,
        send_signals=True,
        send_consensus_signals=False,
        send_report_results=False,
        send_daily_report=False,
        retry_attempts=1,
    )


def test_runtime_uses_configured_telegram_publish_timeout(tmp_path) -> None:
    settings = Settings(telegram=TelegramConfig(publish_timeout_sec=20.0))
    runtime = build_nautilus_runtime_context(settings, base_dir=tmp_path)

    assert runtime.publish_service.timeout_sec == 20.0


async def test_runtime_owns_scoped_signal_publisher_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    publishers = []

    class FakeTelegramPublisher:
        def __init__(self, config: TelegramConfig) -> None:
            self.config = config
            self.closed = False
            self.client = SimpleNamespace(aclose=self._close)
            publishers.append(self)

        async def _close(self) -> None:
            self.closed = True

        async def send(
            self,
            message: str,
            message_type: str,
            signal_id: str | None = None,
        ) -> PublishResult:
            _ = message
            return PublishResult(
                publish_id="tg-verify",
                message_type=message_type,
                status="DRY_RUN",
                signal_id=signal_id,
            )

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.runtime_context_factory.TelegramPublisher",
        FakeTelegramPublisher,
    )
    runtime = build_nautilus_runtime_context(Settings(), base_dir=tmp_path)
    signal = SignalCandidate.build(
        strategy="test",
        asset="BTC",
        timeframe="5m",
        market_id="market-1",
        market_slug="btc-updown-5m",
        condition_id="condition-1",
        token_id="up-token",
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.5,
        max_entry_price=0.55,
        seconds_to_close=120,
        data_freshness_ms=100,
        reason_codes=["EDGE"],
        metrics={},
    )

    result = await runtime.publish_signal_once(signal, 10.0)

    assert result.status == "DRY_RUN"
    assert len(publishers) == 2
    assert publishers[0].closed is False
    assert publishers[1].closed is True


def test_nautilus_runtime_context_has_no_parallel_market_registry(tmp_path) -> None:
    runtime = build_nautilus_runtime_context(Settings(), base_dir=tmp_path)

    assert not hasattr(runtime, "markets")
    assert runtime.publish_service.market_lookup is None


def test_nautilus_runtime_rejects_unreachable_interactive_telegram_control(
    tmp_path,
) -> None:
    settings = Settings()
    settings.telegram.interactive_enabled = True

    with pytest.raises(RuntimeError, match="interactive Telegram control"):
        build_nautilus_runtime_context(settings, base_dir=tmp_path)


def test_telegram_qa_default_message_is_compact() -> None:
    assert DEFAULT_MESSAGE == "<b>PolySignal Lab</b>\nTelegram QA send · Mode: Sandbox"
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


async def test_daily_report_publish_id_is_stable_across_retries() -> None:
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
    key = "daily_report:2026-07-13:r1"

    first = await publisher.send("Daily report", "daily_report", publish_id=key)
    second = await publisher.send("Daily report", "daily_report", publish_id=key)

    assert first.publish_id == key
    assert second.publish_id == key


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
    assert evidence["command"] == shlex.join(
        [
            ".venv/bin/python",
            "-m",
            "polysignal_lab.publish.telegram_qa",
            "--evidence",
            str(evidence_path),
        ]
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
    assert evidence["command"] == shlex.join(
        [
            ".venv/bin/python",
            "-m",
            "polysignal_lab.publish.telegram_qa",
            "--live",
            "--evidence",
            str(evidence_path),
        ]
    )
    assert evidence["error"] == "TELEGRAM_NOT_CONFIGURED"
