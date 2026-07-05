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
from datetime import date, datetime, timezone

from polysignal_lab.domain.enums import PositionStatus, Side
from polysignal_lab.domain.orderbook import BookLevel, OrderBook
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.paper_result import DailyReport


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

    def restore_open_positions(self) -> list[dict[str, object]]:
        return self.positions

    def restore_latest_wallet_snapshot(self) -> dict[str, object] | None:
        return self.wallet

    def restore_latest_system_event(self, event_type: str) -> dict[str, object] | None:
        assert event_type == "health_snapshot"
        return self.health_event

    def restore_daily_reports(self, limit: int = 100) -> list[dict[str, object]]:
        return self.reports[:limit]

    def restore_closed_trade_results(
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
        if table == "paper_trade_results":
            return self.trade_results[:limit]
        raise AssertionError(table)


def _formatting_service(persistence: _FormattingPersistence) -> TelegramBotService:
    return TelegramBotService(
        config=TelegramConfig(interactive_enabled=True, interactive_allowed_chat_ids=(123,)),
        persistence=persistence,
        signal_pipeline=SignalPipeline([], object(), object(), persistence),
        books=OrderBookRegistry(),
        markets=MarketRegistry(),
        formatter=MessageFormatter(),
    )


def test_telegram_bot_positions_marks_live_book_when_available() -> None:
    persistence = _FormattingPersistence()
    position = PaperPosition(
        signal_id="sig_1",
        paper_order_id="po_1",
        paper_fill_id="pf_1",
        strategy="vwap_momentum",
        asset="BTC",
        timeframe="15m",
        market_id="m_1",
        market_slug="btc-15m",
        token_id="token-up",
        side=Side.UP,
        entry_price=0.64,
        shares=500.0,
        stake_usdc=320.0,
        opened_at=datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc),
        status=PositionStatus.OPEN,
    )
    persistence.positions = [position.model_dump(mode="json")]
    service = _formatting_service(persistence)
    service.books.update(
        OrderBook(
            token_id="token-up",
            bids=[BookLevel(price=0.71, size=100)],
            asks=[BookLevel(price=0.72, size=100)],
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
    position = PaperPosition(
        signal_id="sig_1",
        paper_order_id="po_1",
        paper_fill_id="pf_1",
        strategy="vwap_momentum",
        asset="BTC",
        timeframe="15m",
        market_id="m_1",
        market_slug="btc-15m",
        token_id="missing-token",
        side=Side.UP,
        entry_price=0.64,
        shares=500.0,
        stake_usdc=320.0,
        status=PositionStatus.OPEN,
    )
    persistence.positions = [position.model_dump(mode="json")]
    service = _formatting_service(persistence)

    text = service._format_positions()

    assert "Mark      n/a (live book unavailable)" in text
    assert "PnL       n/a" in text


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
        paper_pnl=5.0,
        paper_roi=0.005,
        total_signals=2,
        paper_orders=2,
        paper_fills=1,
        rejected_paper_orders=1,
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

    assert "<b>📊 Daily Paper Report</b>" in text
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
    service = _formatting_service(persistence)
    persistence.positions = [{}, {}, {}]
    service.markets.markets["m1"] = object()
    service.markets.markets["m2"] = object()
    service.signal_pipeline.strategies = [SimpleNamespace(name="a"), SimpleNamespace(name="b")]
    service.signal_pipeline.set_strategy_enabled("b", False)

    text = service._format_status()

    assert "🟢 PolySignal Lab: ok" in text
    assert "Markets     2 tracked" in text
    assert "Positions   3 open" in text
    assert "Wallet      987.50 USDC equity" in text
    assert "Signals     142 accepted / 91 rejected" in text
    assert "Strategies  1/2 enabled" in text

def test_telegram_bot_strategies_menu_uses_short_callback_data() -> None:
    persistence = _FormattingPersistence()
    service = _formatting_service(persistence)
    service.signal_pipeline.strategies = [
        SimpleNamespace(name="vwap_momentum"),
        SimpleNamespace(name="late_consensus"),
        SimpleNamespace(name="x" * 70),
    ]

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
    service = _formatting_service(persistence)
    service.signal_pipeline.strategies = [SimpleNamespace(name="vwap_momentum")]

    text, keyboard = service._toggle_strategy("tg:vwap_momentum")

    assert "⏸ vwap_momentum" in text
    assert "vwap_momentum" in service.signal_pipeline.disabled_strategies
    assert persistence.state["telegram_disabled_strategies"] == ["vwap_momentum"]
    event = persistence.state["last_event"]
    assert event["event_type"] == "strategy_toggle"
    assert event["strategy"] == "vwap_momentum"
    assert event["enabled"] is False
    assert isinstance(keyboard, InlineKeyboardMarkup)


def test_telegram_bot_strategy_toggle_rejects_unknown_strategy() -> None:
    persistence = _FormattingPersistence()
    service = _formatting_service(persistence)
    service.signal_pipeline.strategies = [SimpleNamespace(name="vwap_momentum")]

    with pytest.raises(ValueError, match="Unknown strategy"):
        service._toggle_strategy("tg:not_real")


def test_telegram_bot_leaderboard_all_time() -> None:
    from polysignal_lab.domain.enums import ExitMode, Side, TradeResultStatus
    from polysignal_lab.domain.paper_result import PaperTradeResult

    persistence = _FormattingPersistence()
    result = PaperTradeResult(
        signal_id="sig-1",
        paper_position_id="pos-1",
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="m-1",
        market_slug="btc-5m",
        side=Side.UP,
        entry_price=0.50,
        shares=20.0,
        stake_usdc=10.0,
        exit_mode=ExitMode.RESOLUTION,
        outcome_value=1.0,
        settlement_value=12.4,
        pnl_usdc=2.4,
        roi=0.24,
        result=TradeResultStatus.WIN,
        opened_at=datetime(2026, 6, 21, tzinfo=timezone.utc),
        closed_at=datetime(2026, 6, 22, tzinfo=timezone.utc),
    )
    persistence.trade_results = [result.model_dump(mode="json")]
    service = _formatting_service(persistence)

    text = service._format_leaderboard("all")

    assert "累计" in text
    assert "ptb_diff" in text
    assert "1W" in text or "1W/" in text


def test_telegram_bot_leaderboard_today_filters_by_closed_at(monkeypatch: pytest.MonkeyPatch) -> None:
    from polysignal_lab.domain.enums import ExitMode, Side, TradeResultStatus
    from polysignal_lab.domain.paper_result import PaperTradeResult

    persistence = _FormattingPersistence()
    today_result = PaperTradeResult(
        signal_id="sig-today",
        paper_position_id="pos-today",
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="m-1",
        market_slug="btc-5m",
        side=Side.UP,
        entry_price=0.50,
        shares=20.0,
        stake_usdc=10.0,
        exit_mode=ExitMode.RESOLUTION,
        outcome_value=1.0,
        settlement_value=12.4,
        pnl_usdc=2.4,
        roi=0.24,
        result=TradeResultStatus.WIN,
        opened_at=datetime(2026, 7, 5, 1, 0, tzinfo=timezone.utc),
        closed_at=datetime(2026, 7, 5, 2, 0, tzinfo=timezone.utc),
    )
    old_result = PaperTradeResult(
        signal_id="sig-old",
        paper_position_id="pos-old",
        strategy="vwap_momentum",
        asset="BTC",
        timeframe="5m",
        market_id="m-2",
        market_slug="btc-5m",
        side=Side.UP,
        entry_price=0.50,
        shares=20.0,
        stake_usdc=10.0,
        exit_mode=ExitMode.RESOLUTION,
        outcome_value=0.0,
        settlement_value=0.0,
        pnl_usdc=-10.0,
        roi=-1.0,
        result=TradeResultStatus.LOSS,
        opened_at=datetime(2026, 7, 4, 1, 0, tzinfo=timezone.utc),
        closed_at=datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc),
    )
    persistence.trade_results = [
        today_result.model_dump(mode="json"),
        old_result.model_dump(mode="json"),
    ]
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
