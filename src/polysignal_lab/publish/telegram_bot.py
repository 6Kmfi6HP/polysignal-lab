from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType, ParseMode
from telegram.error import NetworkError, RetryAfter, TelegramError, TimedOut
from telegram.ext import (
    AIORateLimiter,
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from polysignal_lab.app.services.persistence_service import PersistenceService
from polysignal_lab.app.services.signal_pipeline import SignalPipeline
from polysignal_lab.config import TelegramConfig
from polysignal_lab.data.state import MarketRegistry, OrderBookRegistry
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.paper_result import DailyReport
from polysignal_lab.signal_layer.formatter import MessageFormatter
from polysignal_lab.utils import new_id, utc_iso


class TelegramBotService:
    name = "telegram_bot"

    def __init__(
        self,
        *,
        config: TelegramConfig,
        persistence: PersistenceService,
        signal_pipeline: SignalPipeline,
        books: OrderBookRegistry,
        markets: MarketRegistry,
        formatter: MessageFormatter,
        scheduler: Any | None = None,
        application: Application | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.persistence = persistence
        self.signal_pipeline = signal_pipeline
        self.books = books
        self.markets = markets
        self.formatter = formatter
        self.scheduler = scheduler
        self.application = application
        self.logger = logger or logging.getLogger("polysignal_lab.telegram_bot")
        self._running = False
        self._last_update_id: int | None = None
        self._last_update_at: str | None = None
        self._error: str | None = None
        self._poll_success = 0
        self._poll_failure = 0
        self._send_success = 0
        self._send_failure = 0
        self._rate_limited = 0
        self._unauthorized_updates = 0

    def configure_handlers(self) -> None:
        if self.application is None:
            raise RuntimeError("telegram application is not configured")
        self.application.add_handler(CommandHandler("start", self._start))
        self.application.add_handler(CommandHandler("positions", self._positions))
        self.application.add_handler(CommandHandler("status", self._status))
        self.application.add_handler(CommandHandler("signals", self._signals))
        self.application.add_handler(CommandHandler("strategies", self._strategies))
        self.application.add_handler(CommandHandler("daily", self._daily))
        self.application.add_handler(CallbackQueryHandler(self._callback))

    async def start(self) -> None:
        if not self.config.interactive_enabled:
            return
        if self.config.interactive_dry_run:
            self.logger.info("Telegram interactive bot interactive_dry_run enabled")
        if not self.config.resolved_bot_token:
            self._error = "missing bot token"
            self.logger.warning("Telegram interactive bot disabled: missing bot token")
            return
        if not self.config.interactive_allowed_chat_ids:
            self._error = "no allowed chat ids"
            self.logger.warning("Telegram interactive bot disabled: no allowed chat ids")
            return
        if self.scheduler is not None and hasattr(self.scheduler, "strategy_schedule"):
            self.signal_pipeline.set_strategy_dependencies(
                {entry.name: tuple(entry.depends_on) for entry in self.scheduler.strategy_schedule}
            )
        self.application = self.application or (
            ApplicationBuilder()
            .token(self.config.resolved_bot_token)
            .rate_limiter(AIORateLimiter(max_retries=self.config.retry_attempts))
            .build()
        )
        self.configure_handlers()
        try:
            await self.application.initialize()
            await self.application.start()
            if self.application.updater is None:
                raise RuntimeError("telegram application updater is not available")
            await self.application.updater.start_polling(
                poll_interval=self.config.interactive_poll_interval_sec,
                timeout=self.config.interactive_poll_timeout_sec,
                allowed_updates=("message", "callback_query"),
                drop_pending_updates=self.config.interactive_drop_pending_updates_on_start,
            )
        except RetryAfter as exc:
            self._rate_limited += 1
            self._poll_failure += 1
            self._error = f"rate limited: retry after {exc.retry_after}s"
            self.logger.warning("Telegram interactive bot rate limited")
            return
        except (TimedOut, NetworkError, TelegramError, RuntimeError) as exc:
            self._poll_failure += 1
            self._error = type(exc).__name__
            self.logger.warning("Telegram interactive bot start failed: %s", type(exc).__name__)
            return
        self._running = True
        self._poll_success += 1
        self._error = None

    async def stop(self) -> None:
        self._running = False
        if self.application is None:
            return
        if self.application.updater is not None and self.application.updater.running:
            await self.application.updater.stop()
        if self.application.running:
            await self.application.stop()
        await self.application.shutdown()
        self.application = None

    def _authorized(self, update: Update) -> bool:
        chat = update.effective_chat
        user = update.effective_user
        allowed_ids = set(self.config.interactive_allowed_chat_ids)
        allowed = (
            chat is not None
            and user is not None
            and str(chat.type) == ChatType.PRIVATE
            and int(chat.id) in allowed_ids
            and int(user.id) in allowed_ids
        )
        if allowed:
            self._last_update_id = getattr(update, "update_id", None)
            self._last_update_at = utc_iso()
            return True
        self._unauthorized_updates += 1
        self.logger.warning(
            "Unauthorized Telegram interactive update chat_id=%s user_id=%s",
            getattr(chat, "id", None),
            getattr(user, "id", None),
        )
        return False

    def health(self) -> dict[str, object]:
        if not self.config.interactive_enabled:
            status = "disabled"
        elif self._running and self._error is None:
            status = "ok"
        else:
            status = "degraded" if self._error else "disabled"
        return {
            "name": self.name,
            "status": status,
            "metrics": {
                "enabled": self.config.interactive_enabled,
                "running": self._running,
                "authorized_chat_count": len(self.config.interactive_allowed_chat_ids),
                "last_update_id": self._last_update_id,
                "last_update_at": self._last_update_at,
                "poll_success": self._poll_success,
                "poll_failure": self._poll_failure,
                "send_success": self._send_success,
                "send_failure": self._send_failure,
                "rate_limited": self._rate_limited,
                "unauthorized_updates": self._unauthorized_updates,
            },
            "error": self._error,
        }

    async def _start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        await self._reply(update, "PolySignal Lab\n选择操作：", self._main_keyboard())

    async def _status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        await self._reply(update, self._format_status(), self._back_keyboard())

    async def _positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        await self._reply(update, self._format_positions(), self._back_keyboard())

    async def _signals(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        await self._reply(update, self._format_signals(), self._back_keyboard())

    async def _strategies(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        await self._reply(update, self._format_strategies(), self._strategies_keyboard())

    async def _daily(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        await self._reply(update, self._format_daily(), self._back_keyboard())

    def _render_callback(self, data: str) -> tuple[str, InlineKeyboardMarkup | None]:
        match data:
            case "m" | "bk":
                return "PolySignal Lab\n选择操作：", self._main_keyboard()
            case "p":
                return self._format_positions(), self._back_keyboard()
            case "st":
                return self._format_status(), self._back_keyboard()
            case "sg":
                return self._format_signals(), self._back_keyboard()
            case "dy":
                return self._format_daily(), self._back_keyboard()
            case "str":
                return self._format_strategies(), self._strategies_keyboard()
            case _:
                raise ValueError("Unknown action")

    async def _callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None:
            return
        if not self._authorized(update):
            await query.answer("Unauthorized", show_alert=True)
            return
        try:
            if (query.data or "").startswith("tg:"):
                text, keyboard = self._toggle_strategy(query.data or "")
            else:
                text, keyboard = self._render_callback(query.data or "")
        except ValueError as exc:
            await query.answer(str(exc), show_alert=True)
            return
        except Exception:
            await query.answer("Action failed", show_alert=True)
            self.logger.exception("Telegram callback failed")
            return
        await query.answer()
        await self._edit_or_reply(update, text, keyboard)

    async def _edit_or_reply(
        self, update: Update, text: str, keyboard: InlineKeyboardMarkup | None = None
    ) -> None:
        if self.config.interactive_dry_run:
            self.logger.info("telegram interactive_dry_run callback reply: %s", text)
            return
        query = update.callback_query
        try:
            if query is not None and getattr(query, "message", None) is not None:
                await query.edit_message_text(
                    text=self._truncate(text),
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                )
                self._send_success += 1
            else:
                await self._reply(update, text, keyboard)
        except RetryAfter:
            self._rate_limited += 1
            self._send_failure += 1
        except (TimedOut, NetworkError, TelegramError):
            self._send_failure += 1

    def _format_positions(self) -> str:
        return "暂无 open paper positions。"

    def _format_signals(self) -> str:
        return "暂无 recent signals。"

    def _format_daily(self) -> str:
        return "暂无 daily report。"

    def _format_strategies(self) -> str:
        return "⚙️ Strategies"

    def _strategies_keyboard(self) -> InlineKeyboardMarkup:
        return self._back_keyboard()

    def _toggle_strategy(self, data: str) -> tuple[str, InlineKeyboardMarkup | None]:
        raise ValueError("Unknown strategy")

    def _main_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("💼 持仓", callback_data="p"),
                    InlineKeyboardButton("📊 状态", callback_data="st"),
                ],
                [
                    InlineKeyboardButton("📡 最近信号", callback_data="sg"),
                    InlineKeyboardButton("⚙️ 策略", callback_data="str"),
                ],
                [InlineKeyboardButton("📋 每日报告", callback_data="dy")],
            ]
        )

    def _back_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ 返回", callback_data="bk")]])

    async def _reply(
        self, update: Update, text: str, keyboard: InlineKeyboardMarkup | None = None
    ) -> None:
        if self.config.interactive_dry_run:
            self.logger.info("telegram interactive_dry_run reply: %s", text)
            return
        message = update.effective_message
        if message is None:
            self._send_failure += 1
            return
        try:
            await message.reply_text(
                self._truncate(text),
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
            self._send_success += 1
        except RetryAfter:
            self._rate_limited += 1
            self._send_failure += 1
        except (TimedOut, NetworkError, TelegramError):
            self._send_failure += 1

    def _format_status(self) -> str:
        counts = self.persistence.counts()
        return "\n".join(
            [
                "🟢 PolySignal Lab: ok",
                f"Markets     {len(self.markets.markets)} tracked",
                f"Signals     {counts.get('signals', 0)} accepted / {counts.get('rejected_signals', 0)} rejected",
            ]
        )

    def _truncate(self, text: str) -> str:
        if len(text) <= self.config.max_message_chars:
            return text
        return text[: self.config.max_message_chars - 32] + "\n[truncated for Telegram]"
