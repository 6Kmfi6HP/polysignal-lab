"""
Input: __future__, __future__.annotations, datetime, datetime.date, datetime.datetime, datetime.timezone, types, types.SimpleNamespace, pytest, telegram.ext
Output: test_telegram_bot_registers_ptb_handlers, test_telegram_bot_start_uses_embedded_ptb_lifecycle, test_telegram_bot_start_polling_uses_drop_pending_updates, test_telegram_bot_stop_uses_ptb_shutdown_order, test_telegram_bot_rejects_group_chat, test_telegram_bot_rejects_private_chat_not_in_allowlist, test_telegram_bot_uses_ptb_inline_keyboard_markup, test_telegram_bot_callback_always_answers, test_telegram_bot_callback_answers_before_rendering, test_telegram_bot_status_replies_before_rendering
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""









from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from telegram.ext import CallbackQueryHandler, CommandHandler

from factories import sample_report_result

from polysignal_lab.config import TelegramConfig
from polysignal_lab.data.state import MarketRegistry
from polysignal_lab.domain.enums import PositionStatus, Side
from polysignal_lab.alpha.types import SideBookView
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.domain.reporting_result import DailyReport
from polysignal_lab.publish.telegram_bot import TelegramBotService
from polysignal_lab.signal_layer.formatter import MessageFormatter
from telegram import InlineKeyboardMarkup


class _FakeBooks:
    def __init__(self) -> None:
        self._books: dict[str, SideBookView] = {}

    def update(self, book: SideBookView) -> None:
        self._books[book.token_id] = book

    def get(self, token_id: str) -> SideBookView | None:
        return self._books.get(token_id)


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
        self.bot = SimpleNamespace()
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

    def query_report_open_positions(self) -> list[dict[str, object]]:
        return []

    def query_latest_report_account_snapshot(self) -> dict[str, object] | None:
        return None

    def query_latest_system_event(self, event_type: str) -> dict[str, object] | None:
        return None

    def query_daily_reports(self, limit: int = 100) -> list[dict[str, object]]:
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
    strategy_control: _FakeStrategyControl | None = None,
    strategy_names: list[str] | None = None,
) -> TelegramBotService:
    config = TelegramConfig(
        interactive_enabled=enabled,
        interactive_dry_run=dry_run,
        interactive_allowed_chat_ids=allowed,
        retry_attempts=1,
    )
    control = strategy_control or _FakeStrategyControl()
    return TelegramBotService(
        config=config,
        persistence=_FakePersistence(),
        strategy_control=control,
        strategy_names=strategy_names or [],
        books=_FakeBooks(),
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
    assert command_names == {
        "start",
        "positions",
        "status",
        "signals",
        "strategies",
        "daily",
        "leaderboard",
    }
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
    assert callback_values == ["p", "st", "sg", "str", "dy", "lb"]
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

async def test_telegram_bot_callback_answers_before_rendering() -> None:
    service = _service()
    events: list[str] = []

    def format_status() -> str:
        events.append("render")
        return "status"

    known = _FakeCallbackQuery("st")

    async def answer(text: str | None = None, **kwargs: object) -> None:
        events.append("answer")
        known.answers.append({"text": text, **kwargs})

    service._format_status = format_status
    known.answer = answer

    await service._callback(_callback_update(known), SimpleNamespace())

    assert events[:2] == ["answer", "render"]

async def test_telegram_bot_status_replies_before_rendering() -> None:
    service = _service()
    update = _update(123, 123)
    events: list[str] = []

    placeholder = SimpleNamespace()

    async def edit_text(text: str, **kwargs: object) -> None:
        events.append(f"edit:{text}")
        placeholder.edit = {"text": text, **kwargs}

    async def reply_text(text: str, **kwargs: object) -> object:
        events.append(f"reply:{text}")
        update.effective_message.replies.append({"text": text, **kwargs})
        placeholder.edit_text = edit_text
        return placeholder

    def format_status() -> str:
        events.append("render")
        return "status"

    update.effective_message.reply_text = reply_text
    service._format_status = format_status

    await service._status(update, SimpleNamespace())

    assert events == ["reply:处理中…", "render", "edit:status"]
    assert len(update.effective_message.replies) == 1


async def test_telegram_bot_interactive_dry_run_logs_no_send(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    caplog.set_level(logging.INFO)
    service = _service(dry_run=True)
    update = _update(123, 123)

    await service._status(update, SimpleNamespace())

    assert update.effective_message.replies == []
    assert "telegram interactive_dry_run reply" in caplog.text
    assert service.health()["metrics"]["send_success"] == 0
class _FakeStrategyControl:
    def __init__(self, disabled: list[str] | None = None) -> None:
        self.disabled = set(disabled or [])

    def set_strategy_enabled(self, name: str, enabled: bool) -> None:
        if enabled:
            self.disabled.discard(name)
        else:
            self.disabled.add(name)

    def is_strategy_enabled(self, name: str) -> bool:
        return name not in self.disabled

    def status_payload(self) -> dict[str, object]:
        return {"disabled_strategies": sorted(self.disabled)}

    def skip_reason_for(self, name: str) -> str | None:
        if name in self.disabled:
            return "manual_disabled"
        return None


class _FormattingPersistence(_FakePersistence):
    def __init__(self) -> None:
        super().__init__()
        self.positions: list[dict[str, object]] = []
        self.signals: list[dict[str, object]] = []
        self.rejected: list[dict[str, object]] = []
        self.reports: list[dict[str, object]] = []
        self.trade_results: list[dict[str, object]] = []
        self.wallet: dict[str, object] | None = None
        self.health_event: dict[str, object] | None = None
        self.table_counts = {"signals": 0, "rejected_signals": 0}

    def counts(self) -> dict[str, int]:
        return self.table_counts

    def query_report_open_positions(self) -> list[dict[str, object]]:
        return self.positions

    def query_latest_report_account_snapshot(self) -> dict[str, object] | None:
        return self.wallet

    def query_latest_system_event(self, event_type: str) -> dict[str, object] | None:
        assert event_type == "health_snapshot"
        return self.health_event

    def query_daily_reports(self, limit: int = 100) -> list[dict[str, object]]:
        return self.reports[:limit]

    def query_closed_trade_results(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50_000,
    ) -> list[dict[str, object]]:
        rows = self.trade_results
        if since is None and until is None:
            return rows[:limit]
        filtered: list[dict[str, object]] = []
        for row in rows:
            closed_at = row.get("closed_at")
            if closed_at is None:
                continue
            closed_dt = datetime.fromisoformat(str(closed_at).replace("Z", "+00:00"))
            if since is not None and closed_dt < since:
                continue
            if until is not None and closed_dt >= until:
                continue
            filtered.append(row)
        return filtered[:limit]

    def query_json(self, table: str, limit: int = 100, where: str = "", params=()) -> list[dict[str, object]]:
        if table == "signals":
            return self.signals[:limit]
        if table == "rejected_signals":
            return self.rejected[:limit]
        if table == "report_results":
            return self.trade_results[:limit]
        raise AssertionError(table)


def _formatting_service(
    persistence: _FormattingPersistence,
    *,
    strategy_control: _FakeStrategyControl | None = None,
    strategy_names: list[str] | None = None,
) -> TelegramBotService:
    return TelegramBotService(
        config=TelegramConfig(interactive_enabled=True, interactive_allowed_chat_ids=(123,)),
        persistence=persistence,
        strategy_control=strategy_control or _FakeStrategyControl(),
        strategy_names=strategy_names or [],
        books=_FakeBooks(),
        markets=MarketRegistry(),
        formatter=MessageFormatter(),
    )


def test_telegram_bot_positions_marks_live_book_when_available() -> None:
    persistence = _FormattingPersistence()
    position = {
        "report_position_id": "pp-1",
        "signal_id": "sig_1",
        "report_order_id": "po_1",
        "report_fill_id": "pf_1",
        "strategy": "vwap_momentum",
        "asset": "BTC",
        "timeframe": "15m",
        "market_id": "m_1",
        "market_slug": "btc-15m",
        "token_id": "token-up",
        "side": Side.UP.value,
        "entry_price": 0.64,
        "shares": 500.0,
        "stake_usdc": 320.0,
        "opened_at": datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc).isoformat(),
        "status": PositionStatus.OPEN.value,
    }
    persistence.positions = [position]
    service = _formatting_service(persistence)
    service.books.update(
        SideBookView(
            token_id="token-up",
            best_bid=0.71,
            best_ask=0.72,
            spread=0.01,
            freshness_ms=0,
            ask_levels=((0.72, 100.0),),
        )
    )

    text = service._format_positions()

    assert "📈 BTC 15m · UP" in text
    assert "Strategy  vwap_momentum" in text
    assert "Entry     0.6400" in text
    assert "Mark      0.7100" in text
    assert "Shares    500.0000" in text
    assert "PnL       +35.00 USDC (+10.94%)" in text
    assert "ID        " in text


def test_telegram_bot_positions_shows_mark_na_without_live_book() -> None:
    persistence = _FormattingPersistence()
    position = {
        "report_position_id": "pp-2",
        "signal_id": "sig_1",
        "report_order_id": "po_1",
        "report_fill_id": "pf_1",
        "strategy": "vwap_momentum",
        "asset": "BTC",
        "timeframe": "15m",
        "market_id": "m_1",
        "market_slug": "btc-15m",
        "token_id": "missing-token",
        "side": Side.UP.value,
        "entry_price": 0.64,
        "shares": 500.0,
        "stake_usdc": 320.0,
        "status": PositionStatus.OPEN.value,
    }
    persistence.positions = [position]
    service = _formatting_service(persistence)

    text = service._format_positions()

    assert "Mark      n/a (live book unavailable)" in text
    assert "PnL       n/a" in text


def test_telegram_bot_positions_accepts_projected_nautilus_rows() -> None:
    persistence = _FormattingPersistence()
    persistence.positions = [
        {
            "position_id": "P-001",
            "instrument_id": "token-up.POLYMARKET",
            "avg_entry_price": 0.64,
            "signed_qty": 500.0,
            "opened_at": "2026-06-24T12:00:00Z",
        }
    ]
    service = _formatting_service(persistence)
    service.markets.upsert_many(
        [
            Market(
                market_id="m_1",
                market_slug="btc-15m",
                condition_id="condition-1",
                asset="BTC",
                timeframe="15m",
                outcome_tokens=[
                    OutcomeToken(
                        token_id="token-up",
                        side=Side.UP,
                        outcome_name="Up",
                        market_id="m_1",
                    )
                ],
            )
        ]
    )
    service.books.update(
        SideBookView(
            token_id="token-up",
            best_bid=0.71,
            best_ask=0.72,
            spread=0.01,
            freshness_ms=0,
            ask_levels=((0.72, 100.0),),
        )
    )

    text = service._format_positions()

    assert "📈 BTC 15m · UP" in text
    assert "Entry     0.6400" in text
    assert "Shares    500.0000" in text
    assert "PnL       +35.00 USDC (+10.94%)" in text
    assert "ID        P-001" in text


def test_telegram_bot_positions_skips_rows_without_side() -> None:
    persistence = _FormattingPersistence()
    persistence.positions = [
        {
            "position_id": "P-no-side",
            "market_id": "m_1",
            "market_slug": "btc-15m",
            "asset": "BTC",
            "timeframe": "15m",
            "token_id": "token-up",
            "avg_entry_price": 0.64,
            "quantity": 500.0,
            "opened_at": "2026-06-24T12:00:00Z",
        }
    ]
    service = _formatting_service(persistence)

    text = service._format_positions()

    assert text == "暂无 open positions。"
    assert "· UP" not in text


def test_telegram_bot_signals_merges_accepted_and_rejected() -> None:
    persistence = _FormattingPersistence()
    persistence.signals = [
        {
            "signal_id": "sig_new",
            "strategy": "vwap_momentum",
            "asset": "BTC",
            "timeframe": "15m",
            "action": "BUY",
            "side": "UP",
            "created_at": "2026-06-24T12:02:00Z",
        }
    ]
    persistence.rejected = [
        {
            "rejected_id": "rej_old",
            "reason_code": "stale_book",
            "rejected_at": "2026-06-24T12:00:00Z",
            "candidate": {
                "signal_id": "sig_old",
                "strategy": "late_consensus",
                "asset": "ETH",
                "timeframe": "5m",
                "action": "BUY",
                "side": "DOWN",
            },
        }
    ]
    service = _formatting_service(persistence)

    text = service._format_signals()

    assert "🟢 accepted · BTC 15m BUY UP" in text
    assert "vwap_momentum · sig_new" in text
    assert "🔴 rejected · ETH 5m BUY DOWN" in text
    assert "late_consensus · stale_book" in text
    assert text.index("sig_new") < text.index("sig_old")


def test_telegram_bot_daily_validates_payload_before_formatter() -> None:
    persistence = _FormattingPersistence()
    report = DailyReport(
        report_date=date(2026, 6, 24),
        starting_equity=1000.0,
        ending_equity=1005.0,
        net_pnl=5.0,
        return_rate=0.005,
        total_signals=2,
        order_count=2,
        fill_count=1,
        rejected_order_count=1,
        open_positions=1,
        closed_positions=1,
        win_count=1,
        loss_count=0,
        void_count=0,
        win_rate=1.0,
        total_pnl_usdc=5.0,
        average_roi=0.005,
        max_drawdown=0.0,
        profit_factor=None,
    )
    persistence.reports = [report.model_dump(mode="json")]
    service = _formatting_service(persistence)

    text = service._format_daily()

    assert "<b>📊 Daily Trading Report</b>" in text
    assert "2026-06-24" in text


def test_telegram_bot_status_includes_health_wallet_counts_and_disabled_strategies() -> None:
    persistence = _FormattingPersistence()
    persistence.table_counts = {"signals": 142, "rejected_signals": 91}
    persistence.wallet = {"equity": 987.5, "cash_balance": 900.0, "open_position_count": 3}
    persistence.health_event = {
        "status": "ok",
        "created_at": "2026-06-24T12:00:00Z",
        "components": [],
    }
    service = _formatting_service(persistence, strategy_names=["a", "b"], strategy_control=_FakeStrategyControl(["b"]))
    persistence.positions = [{}, {}, {}]
    service.markets.markets["m1"] = object()
    service.markets.markets["m2"] = object()

    text = service._format_status()

    assert "🟢 PolySignal Lab: ok" in text
    assert "Markets     2 tracked" in text
    assert "Positions   3 open" in text
    assert "Account     987.50 USDC equity" in text
    assert "Signals     142 accepted / 91 rejected" in text
    assert "Strategies  1/2 enabled" in text

def test_telegram_bot_strategies_menu_uses_short_callback_data() -> None:
    persistence = _FormattingPersistence()
    service = _formatting_service(
        persistence,
        strategy_names=["vwap_momentum", "late_consensus", "x" * 70],
    )

    text = service._format_strategies()
    keyboard = service._strategies_keyboard()

    assert "✅ vwap_momentum" in text
    assert "✅ late_consensus" in text
    assert "cannot be toggled from Telegram" in text
    values = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert "tg:vwap_momentum" in values
    assert "tg:late_consensus" in values
    assert all(len(value.encode("utf-8")) <= 64 for value in values)
    assert "tg:" + "x" * 70 not in values


def test_telegram_bot_strategy_toggle_persists_state_and_event() -> None:
    persistence = _FormattingPersistence()
    service = _formatting_service(persistence, strategy_names=["vwap_momentum"])

    text, keyboard = service._toggle_strategy("tg:vwap_momentum")

    assert "⏸ vwap_momentum" in text
    assert "vwap_momentum" in service.strategy_control.status_payload()["disabled_strategies"]
    assert persistence.state["telegram_disabled_strategies"] == ["vwap_momentum"]
    event = persistence.state["last_event"]
    assert event["event_type"] == "strategy_toggle"
    assert event["strategy"] == "vwap_momentum"
    assert event["enabled"] is False
    assert isinstance(keyboard, InlineKeyboardMarkup)


def test_telegram_bot_strategy_control_updates_policy() -> None:
    persistence = _FormattingPersistence()
    control = _FakeStrategyControl(["vwap_momentum"])
    service = _formatting_service(
        persistence,
        strategy_names=["vwap_momentum"],
        strategy_control=control,
    )

    text, keyboard = service._toggle_strategy("tg:vwap_momentum")

    assert "✅ vwap_momentum" in text
    assert control.is_strategy_enabled("vwap_momentum") is True
    assert persistence.state["telegram_disabled_strategies"] == []
    assert persistence.state["last_event"]["enabled"] is True
    assert isinstance(keyboard, InlineKeyboardMarkup)


def test_telegram_bot_strategy_toggle_rejects_unknown_strategy() -> None:
    persistence = _FormattingPersistence()
    service = _formatting_service(persistence, strategy_names=["vwap_momentum"])

    with pytest.raises(ValueError, match="Unknown strategy"):
        service._toggle_strategy("tg:not_real")


def test_telegram_bot_leaderboard_all_time() -> None:
    from polysignal_lab.domain.enums import TradeResultStatus

    persistence = _FormattingPersistence()
    result = sample_report_result(
        signal_id="sig-1",
        report_position_id="pos-1",
        market_id="m-1",
        market_slug="btc-5m",
        outcome_value=1.0,
        settlement_value=12.4,
        pnl_usdc=2.4,
        roi=0.24,
        result=TradeResultStatus.WIN.value,
        opened_at=datetime(2026, 6, 21, tzinfo=timezone.utc).isoformat(),
        closed_at=datetime(2026, 6, 22, tzinfo=timezone.utc).isoformat(),
    )
    persistence.trade_results = [result]
    service = _formatting_service(persistence)

    text = service._format_leaderboard("all")

    assert "累计" in text
    assert "ptb_diff" in text
    assert "1W" in text or "1W/" in text


def test_telegram_bot_leaderboard_today_filters_by_closed_at(monkeypatch: pytest.MonkeyPatch) -> None:
    from polysignal_lab.domain.enums import TradeResultStatus

    persistence = _FormattingPersistence()
    today_result = sample_report_result(
        signal_id="sig-today",
        report_position_id="pos-today",
        market_id="m-1",
        market_slug="btc-5m",
        outcome_value=1.0,
        settlement_value=12.4,
        pnl_usdc=2.4,
        roi=0.24,
        result=TradeResultStatus.WIN.value,
        opened_at=datetime(2026, 7, 5, 1, 0, tzinfo=timezone.utc).isoformat(),
        closed_at=datetime(2026, 7, 5, 2, 0, tzinfo=timezone.utc).isoformat(),
    )
    old_result = sample_report_result(
        signal_id="sig-old",
        report_position_id="pos-old",
        strategy="vwap_momentum",
        market_id="m-2",
        market_slug="btc-5m",
        outcome_value=0.0,
        settlement_value=0.0,
        pnl_usdc=-10.0,
        roi=-1.0,
        result=TradeResultStatus.LOSS.value,
        opened_at=datetime(2026, 7, 4, 1, 0, tzinfo=timezone.utc).isoformat(),
        closed_at=datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc).isoformat(),
    )
    persistence.trade_results = [today_result, old_result]
    service = _formatting_service(persistence)
    service.scheduler = SimpleNamespace(
        settings=SimpleNamespace(app=SimpleNamespace(timezone="Asia/Bangkok"))
    )
    monkeypatch.setattr(
        "polysignal_lab.publish.telegram_bot.datetime",
        SimpleNamespace(
            now=lambda tz=None: datetime(2026, 7, 5, 10, 0, tzinfo=tz),
            combine=datetime.combine,
        ),
    )

    text = service._format_leaderboard("today")

    assert "今日" in text
    assert "ptb_diff" in text
    assert "vwap_momentum" not in text


def test_telegram_bot_leaderboard_today_title() -> None:
    persistence = _FormattingPersistence()
    service = _formatting_service(persistence)
    service.scheduler = SimpleNamespace(
        settings=SimpleNamespace(app=SimpleNamespace(timezone="UTC"))
    )

    text = service._format_leaderboard("today")

    assert "今日" in text
    assert "暂无已结算策略战绩" in text


def test_telegram_bot_leaderboard_callback_renders_today() -> None:
    persistence = _FormattingPersistence()
    service = _formatting_service(persistence)
    service.scheduler = SimpleNamespace(
        settings=SimpleNamespace(app=SimpleNamespace(timezone="UTC"))
    )

    text, keyboard = service._render_callback("lbt")

    assert "今日" in text
    assert keyboard is not None
    values = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert "lbt" in values
    assert "lb" in values
