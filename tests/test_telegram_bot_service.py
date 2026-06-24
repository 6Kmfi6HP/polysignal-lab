from __future__ import annotations

from types import SimpleNamespace

import pytest
from telegram.ext import CallbackQueryHandler, CommandHandler

from polysignal_lab.app.services.signal_pipeline import SignalPipeline
from polysignal_lab.config import TelegramConfig
from polysignal_lab.data.state import MarketRegistry, OrderBookRegistry
from polysignal_lab.publish.telegram_bot import TelegramBotService
from polysignal_lab.signal_layer.formatter import MessageFormatter
from telegram import InlineKeyboardMarkup


class _FakeUpdater:
    def __init__(self, calls: list[tuple[str, dict[str, object]]]) -> None:
        self.calls = calls
        self.running = False

    async def start_polling(self, **kwargs: object) -> None:
        self.calls.append(("updater.start_polling", dict(kwargs)))
        self.running = True

    async def stop(self) -> None:
        self.calls.append(("updater.stop", {}))
        self.running = False


class _FakeApplication:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.handlers: list[object] = []
        self.updater = _FakeUpdater(self.calls)
        self.running = False

    def add_handler(self, handler: object) -> None:
        self.handlers.append(handler)

    async def initialize(self) -> None:
        self.calls.append(("initialize", {}))

    async def start(self) -> None:
        self.calls.append(("start", {}))
        self.running = True

    async def stop(self) -> None:
        self.calls.append(("stop", {}))
        self.running = False

    async def shutdown(self) -> None:
        self.calls.append(("shutdown", {}))


class _FakePersistence:
    def __init__(self) -> None:
        self.state: dict[str, object] = {}

    def counts(self) -> dict[str, int]:
        return {}

    def restore_open_positions(self) -> list[dict[str, object]]:
        return []

    def restore_latest_wallet_snapshot(self) -> dict[str, object] | None:
        return None

    def restore_latest_system_event(self, event_type: str) -> dict[str, object] | None:
        return None

    def restore_daily_reports(self, limit: int = 100) -> list[dict[str, object]]:
        return []

    def query_json(self, table: str, limit: int = 100, where: str = "", params=()) -> list[dict[str, object]]:
        return []

    def read_state(self, name: str, default: object = None) -> object:
        return self.state.get(name, default)

    def write_state(self, name: str, value: object) -> None:
        self.state[name] = value

    def insert_system_event(self, event: dict[str, object]) -> None:
        self.state["last_event"] = event


class _FakeMessage:
    def __init__(self) -> None:
        self.replies: list[dict[str, object]] = []

    async def reply_text(self, text: str, **kwargs: object) -> None:
        self.replies.append({"text": text, **kwargs})


def _service(
    *,
    allowed: tuple[int, ...] = (123,),
    enabled: bool = True,
    dry_run: bool = False,
    application: _FakeApplication | None = None,
) -> TelegramBotService:
    config = TelegramConfig(
        interactive_enabled=enabled,
        interactive_dry_run=dry_run,
        interactive_allowed_chat_ids=allowed,
        retry_attempts=1,
    )
    return TelegramBotService(
        config=config,
        persistence=_FakePersistence(),
        signal_pipeline=SignalPipeline([], object(), object(), None),
        books=OrderBookRegistry(),
        markets=MarketRegistry(),
        formatter=MessageFormatter(),
        application=application,
    )


def _update(chat_id: int, user_id: int, chat_type: str = "private") -> SimpleNamespace:
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id, type=chat_type),
        effective_user=SimpleNamespace(id=user_id),
        effective_message=_FakeMessage(),
        callback_query=None,
    )


def test_telegram_bot_registers_ptb_handlers() -> None:
    app = _FakeApplication()
    service = _service(application=app)

    service.configure_handlers()

    command_names = {
        command
        for handler in app.handlers
        if isinstance(handler, CommandHandler)
        for command in handler.commands
    }
    assert command_names == {"start", "positions", "status", "signals", "strategies", "daily"}
    assert any(isinstance(handler, CallbackQueryHandler) for handler in app.handlers)


async def test_telegram_bot_start_uses_embedded_ptb_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _FakeApplication()
    service = _service(application=app)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")

    await service.start()

    assert [name for name, _ in app.calls[:3]] == [
        "initialize",
        "start",
        "updater.start_polling",
    ]
    assert service.health()["status"] == "ok"


async def test_telegram_bot_start_polling_uses_drop_pending_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _FakeApplication()
    service = _service(application=app)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")

    await service.start()

    polling = dict(app.calls[2][1])
    assert polling["allowed_updates"] == ("message", "callback_query")
    assert polling["drop_pending_updates"] is True
    assert polling["poll_interval"] == 0.0
    assert polling["timeout"] == 30


async def test_telegram_bot_stop_uses_ptb_shutdown_order(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _FakeApplication()
    service = _service(application=app)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
    await service.start()

    await service.stop()

    assert [name for name, _ in app.calls[-3:]] == ["updater.stop", "stop", "shutdown"]
    assert service.health()["metrics"]["running"] is False


async def test_telegram_bot_rejects_group_chat() -> None:
    service = _service()
    update = _update(123, 123, chat_type="group")

    await service._status(update, SimpleNamespace())

    assert update.effective_message.replies == []
    assert service.health()["metrics"]["unauthorized_updates"] == 1


async def test_telegram_bot_rejects_private_chat_not_in_allowlist() -> None:
    service = _service(allowed=(123,))
    update = _update(123, 999, chat_type="private")

    await service._status(update, SimpleNamespace())

    assert update.effective_message.replies == []
    assert service.health()["metrics"]["unauthorized_updates"] == 1


class _FakeCallbackQuery:
    def __init__(self, data: str, chat_id: int = 123, user_id: int = 123) -> None:
        self.data = data
        self.answers: list[dict[str, object]] = []
        self.edits: list[dict[str, object]] = []
        self.message = _FakeMessage()
        self.from_user = SimpleNamespace(id=user_id)
        self.chat_id = chat_id

    async def answer(self, text: str | None = None, **kwargs: object) -> None:
        self.answers.append({"text": text, **kwargs})

    async def edit_message_text(self, text: str, **kwargs: object) -> None:
        self.edits.append({"text": text, **kwargs})


def _callback_update(query: _FakeCallbackQuery, *, chat_id: int = 123, user_id: int = 123, chat_type: str = "private") -> SimpleNamespace:
    return SimpleNamespace(
        update_id=42,
        effective_chat=SimpleNamespace(id=chat_id, type=chat_type),
        effective_user=SimpleNamespace(id=user_id),
        effective_message=query.message,
        callback_query=query,
    )


def test_telegram_bot_uses_ptb_inline_keyboard_markup() -> None:
    service = _service()

    keyboard = service._main_keyboard()

    assert isinstance(keyboard, InlineKeyboardMarkup)
    callback_values = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert callback_values == ["p", "st", "sg", "str", "dy"]
    assert all(1 <= len(value.encode("utf-8")) <= 64 for value in callback_values)


async def test_telegram_bot_callback_always_answers() -> None:
    service = _service()

    known = _FakeCallbackQuery("st")
    await service._callback(_callback_update(known), SimpleNamespace())
    unknown = _FakeCallbackQuery("unknown")
    await service._callback(_callback_update(unknown), SimpleNamespace())
    unauthorized = _FakeCallbackQuery("st", user_id=999)
    await service._callback(_callback_update(unauthorized, user_id=999), SimpleNamespace())

    assert len(known.answers) == 1
    assert known.answers[0]["text"] is None
    assert len(unknown.answers) == 1
    assert unknown.answers[0]["text"] == "Unknown action"
    assert unknown.answers[0]["show_alert"] is True
    assert unauthorized.answers[0]["text"] == "Unauthorized"
    assert unauthorized.answers[0]["show_alert"] is True


async def test_telegram_bot_interactive_dry_run_logs_no_send(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    caplog.set_level(logging.INFO)
    service = _service(dry_run=True)
    update = _update(123, 123)

    await service._status(update, SimpleNamespace())

    assert update.effective_message.replies == []
    assert "telegram interactive_dry_run reply" in caplog.text
    assert service.health()["metrics"]["send_success"] == 0
