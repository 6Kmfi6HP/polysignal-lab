from __future__ import annotations

import html
import logging
from collections.abc import Callable
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

    async def _set_bot_commands(self) -> None:
        if self.application is None or self.application.bot is None:
            return
        from telegram import BotCommand
        commands = [
            BotCommand("start", "主菜单 / 选择操作"),
            BotCommand("positions", "查看 open paper 持仓"),
            BotCommand("status", "系统运行状态"),
            BotCommand("signals", "最近信号"),
            BotCommand("strategies", "策略启停"),
            BotCommand("daily", "每日报告"),
        ]
        try:
            await self.application.bot.set_my_commands(commands)
        except Exception:
            self.logger.warning("Failed to set bot commands")

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
            .concurrent_updates(True)
            .build()
        )
        self.configure_handlers()
        try:
            await self.application.initialize()
            await self._set_bot_commands()
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
        await self._reply_rendered(update, self._format_status, self._back_keyboard)

    async def _positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        await self._reply_rendered(update, self._format_positions, self._back_keyboard)

    async def _signals(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        await self._reply_rendered(update, self._format_signals, self._back_keyboard)

    async def _strategies(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        await self._reply_rendered(update, self._format_strategies, self._strategies_keyboard)

    async def _daily(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        await self._reply_rendered(update, self._format_daily, self._back_keyboard)

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
        data = query.data or ""
        known_actions = {"m", "bk", "p", "st", "sg", "dy", "str"}
        if data.startswith("tg:"):
            name = data[3:]
            if name not in set(self._strategy_names()):
                await query.answer("Unknown strategy", show_alert=True)
                return
        elif data not in known_actions:
            await query.answer("Unknown action", show_alert=True)
            return
        try:
            await query.answer()
        except (TimedOut, NetworkError, TelegramError):
            self._send_failure += 1
        try:
            if data.startswith("tg:"):
                text, keyboard = self._toggle_strategy(data)
            else:
                text, keyboard = self._render_callback(data)
        except Exception:
            await self._edit_or_reply(update, "Action failed", self._back_keyboard())
            self.logger.exception("Telegram callback failed")
            return
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
        rows = self.persistence.restore_open_positions()
        if not rows:
            return "暂无 open paper positions。"
        blocks: list[str] = []
        for row in rows:
            position = PaperPosition.model_validate(row)
            book = self.books.get(position.token_id)
            mark = book.best_bid if book is not None else None
            lines = [
                f"📈 {self._safe(position.asset)} {self._safe(position.timeframe)} · {self._safe(position.side.value)}",
                f"Strategy  {self._safe(position.strategy)}",
                f"Entry     {position.entry_price:.4f}",
            ]
            if mark is None:
                lines.extend(["Mark      n/a (live book unavailable)", "PnL       n/a"])
            else:
                pnl = (mark - position.entry_price) * position.shares
                roi = pnl / position.stake_usdc if position.stake_usdc else 0.0
                sign = "+" if pnl >= 0 else ""
                lines.extend(
                    [
                        f"Mark      {mark:.4f}",
                        f"Shares    {position.shares:.4f}",
                        f"PnL       {sign}{pnl:.2f} USDC ({sign}{roi:.2%})",
                    ]
                )
            lines.extend(
                [
                    f"Opened    {self._format_age(position.opened_at)}",
                    f"ID        {self._safe(position.paper_position_id)}",
                ]
            )
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    def _format_signals(self) -> str:
        accepted = self.persistence.query_json(
            "signals", where="ORDER BY created_at DESC", limit=5
        )
        rejected = self.persistence.query_json(
            "rejected_signals", where="ORDER BY rejected_at DESC", limit=5
        )
        items: list[tuple[datetime, str]] = []
        for row in accepted:
            ts = self._parse_time(row.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc)
            items.append((ts, self._format_accepted_signal(row)))
        for row in rejected:
            ts = self._parse_time(row.get("rejected_at")) or datetime.min.replace(tzinfo=timezone.utc)
            items.append((ts, self._format_rejected_signal(row)))
        if not items:
            return "暂无 recent signals。"
        return "\n\n".join(text for _, text in sorted(items, key=lambda item: item[0], reverse=True)[:5])

    def _format_accepted_signal(self, row: dict[str, Any]) -> str:
        return "\n".join(
            [
                f"🟢 accepted · {self._safe(row.get('asset', '?'))} {self._safe(row.get('timeframe', '?'))} {self._safe(row.get('action', '?'))} {self._safe(row.get('side', '?'))}",
                f"{self._format_age(row.get('created_at'))} · {self._safe(row.get('strategy', '?'))} · {self._safe(row.get('signal_id', '?'))}",
            ]
        )

    def _format_rejected_signal(self, row: dict[str, Any]) -> str:
        candidate = row.get("candidate") if isinstance(row.get("candidate"), dict) else {}
        return "\n".join(
            [
                f"🔴 rejected · {self._safe(candidate.get('asset', '?'))} {self._safe(candidate.get('timeframe', '?'))} {self._safe(candidate.get('action', '?'))} {self._safe(candidate.get('side', '?'))}",
                f"{self._format_age(row.get('rejected_at'))} · {self._safe(candidate.get('strategy', '?'))} · {self._safe(row.get('reason_code', '?'))}",
                f"ID        {self._safe(candidate.get('signal_id', '?'))}",
            ]
        )

    def _format_daily(self) -> str:
        reports = self.persistence.restore_daily_reports(limit=1)
        if not reports:
            return "暂无 daily report。"
        payload = reports[0]
        try:
            report = DailyReport.model_validate(payload)
            return self.formatter.daily_report_message(report)
        except Exception:
            self.logger.exception("Invalid daily report payload")
            return "\n".join(
                [
                    "<b>📊 Daily Paper Report</b>",
                    self._safe(payload.get("report_date", "unknown")),
                    f"Signals {self._safe(payload.get('total_signals', 'unknown'))}",
                    f"PnL     {self._safe(payload.get('total_pnl_usdc', payload.get('paper_pnl', 'unknown')))} USDC",
                    f"WR      {self._safe(payload.get('win_rate', 'unknown'))}",
                    f"ID      {self._safe(payload.get('report_id', 'unknown'))}",
                ]
            )

    def _strategy_names(self) -> list[str]:
        return [
            str(getattr(strategy, "name", ""))
            for strategy in self.signal_pipeline.strategies
            if getattr(strategy, "name", "")
        ]

    def _toggle_callback_for(self, name: str) -> str | None:
        data = f"tg:{name}"
        return data if len(data.encode("utf-8")) <= 64 else None

    def _format_strategies(self) -> str:
        lines = ["⚙️ Strategies"]
        for name in self._strategy_names():
            enabled = self.signal_pipeline.is_strategy_enabled(name)
            prefix = "✅" if enabled else "⏸"
            suffix = ""
            if self._toggle_callback_for(name) is None:
                suffix = " (cannot be toggled from Telegram)"
            reason = self.signal_pipeline.skip_reason_for(name)
            if reason and reason.startswith("dependency_disabled:"):
                suffix = f" ({reason})"
            lines.append(f"{prefix} {self._safe(name)}{suffix}")
        return "\n".join(lines)

    def _strategies_keyboard(self) -> InlineKeyboardMarkup:
        rows: list[list[InlineKeyboardButton]] = []
        for name in self._strategy_names():
            callback_data = self._toggle_callback_for(name)
            if callback_data is None:
                continue
            enabled = self.signal_pipeline.is_strategy_enabled(name)
            label = f"{'⏸' if enabled else '▶️'} {name}"
            rows.append([InlineKeyboardButton(label, callback_data=callback_data)])
        rows.append([InlineKeyboardButton("⬅️ 返回", callback_data="bk")])
        return InlineKeyboardMarkup(rows)

    def _toggle_strategy(self, data: str) -> tuple[str, InlineKeyboardMarkup | None]:
        if not data.startswith("tg:"):
            raise ValueError("Unknown strategy")
        name = data[3:]
        names = set(self._strategy_names())
        if name not in names:
            raise ValueError("Unknown strategy")
        enabled = not self.signal_pipeline.is_strategy_enabled(name)
        self.signal_pipeline.set_strategy_enabled(name, enabled)
        disabled = sorted(self.signal_pipeline.disabled_strategies)
        self.persistence.write_state("telegram_disabled_strategies", disabled)
        self.persistence.insert_system_event(
            {
                "event_id": new_id("strategy_toggle"),
                "event_type": "strategy_toggle",
                "severity": "INFO",
                "created_at": utc_iso(),
                "strategy": name,
                "enabled": enabled,
                "disabled_strategies": disabled,
            }
        )
        return self._format_strategies(), self._strategies_keyboard()

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

    async def _reply_rendered(
        self,
        update: Update,
        render: Callable[[], str],
        keyboard: Callable[[], InlineKeyboardMarkup],
    ) -> None:
        sent = None
        if not self.config.interactive_dry_run:
            sent = await self._reply(update, "处理中…")
        text = render()
        keyboard_markup = keyboard()
        edit_text = getattr(sent, "edit_text", None)
        if edit_text is not None:
            try:
                await edit_text(
                    text=self._truncate(text),
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard_markup,
                )
                self._send_success += 1
                return
            except RetryAfter:
                self._rate_limited += 1
                self._send_failure += 1
            except (TimedOut, NetworkError, TelegramError):
                self._send_failure += 1
        await self._reply(update, text, keyboard_markup)

    async def _reply(
        self, update: Update, text: str, keyboard: InlineKeyboardMarkup | None = None
    ) -> object | None:
        if self.config.interactive_dry_run:
            self.logger.info("telegram interactive_dry_run reply: %s", text)
            return None
        message = update.effective_message
        if message is None:
            self._send_failure += 1
            return None
        try:
            sent = await message.reply_text(
                self._truncate(text),
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
            self._send_success += 1
            return sent
        except RetryAfter:
            self._rate_limited += 1
            self._send_failure += 1
        except (TimedOut, NetworkError, TelegramError):
            self._send_failure += 1
        return None

    def _format_status(self) -> str:
        counts = self.persistence.counts()
        positions = self.persistence.restore_open_positions()
        wallet = self.persistence.restore_latest_wallet_snapshot() or {}
        health = self.persistence.restore_latest_system_event("health_snapshot") or {}
        status = str(health.get("status") or "unknown")
        emoji = "🟢" if status == "ok" else "🟡" if status == "degraded" else "🔴"
        strategies = [getattr(strategy, "name", "?") for strategy in self.signal_pipeline.strategies]
        enabled_count = sum(1 for name in strategies if self.signal_pipeline.is_strategy_enabled(name))
        total_count = len(strategies)
        equity = float(wallet.get("equity", 0.0) or 0.0)
        health_age = self._format_age(health.get("created_at")) if health else "n/a"
        return "\n".join(
            [
                f"{emoji} PolySignal Lab: {self._safe(status)}",
                f"Health age  {health_age}",
                f"Markets     {len(self.markets.markets)} tracked",
                f"Positions   {len(positions)} open",
                f"Wallet      {equity:.2f} USDC equity",
                f"Signals     {counts.get('signals', 0)} accepted / {counts.get('rejected_signals', 0)} rejected",
                f"Strategies  {enabled_count}/{total_count} enabled",
                f"Telegram    {'polling ok' if self._running else 'not polling'}",
            ]
        )

    def _safe(self, value: object) -> str:
        return html.escape(str(value))

    def _parse_time(self, value: object) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    def _format_age(self, value: object) -> str:
        dt = self._parse_time(value)
        if dt is None:
            return "unknown"
        seconds = max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))
        if seconds < 60:
            return f"{seconds}s ago"
        if seconds < 3600:
            return f"{seconds // 60}m ago"
        return f"{seconds // 3600}h{(seconds % 3600) // 60}m ago"

    def _truncate(self, text: str) -> str:
        if len(text) <= self.config.max_message_chars:
            return text
        return text[: self.config.max_message_chars - 32] + "\n[truncated for Telegram]"
