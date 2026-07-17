"""
Input: __future__, __future__.annotations, logging, collections.abc, collections.abc.Callable, datetime, datetime.UTC, datetime.datetime, datetime.time, telegram, polysignal_lab.app.services.persistence_service, polysignal_lab.config, polysignal_lab.data.state, polysignal_lab.nautilus_runtime.observability, polysignal_lab.reporting.strategy_stats, polysignal_lab.publish.telegram_render, polysignal_lab.signal_layer.formatter, polysignal_lab.utils
Output: TelegramBotService, _position_display_payload
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telegram import InlineKeyboardMarkup, Update
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
from polysignal_lab.config import TelegramConfig
from polysignal_lab.data.state import MarketRegistry
from polysignal_lab.nautilus_runtime.observability import StrategyControl
from polysignal_lab.storage.event_projection import report_token_id
from polysignal_lab.reporting.strategy_stats import build_strategy_leaderboard_rows
from polysignal_lab.publish import telegram_render
from polysignal_lab.signal_layer.formatter import MessageFormatter
from polysignal_lab.utils import new_id, utc_iso


class TelegramBotService:
    name = "telegram_bot"

    def __init__(
        self,
        *,
        config: TelegramConfig,
        persistence: PersistenceService,
        strategy_control: StrategyControl,
        strategy_names: list[str],
        books: object | None,
        markets: MarketRegistry,
        formatter: MessageFormatter,
        scheduler: Any | None = None,
        application: Application[Any, Any, Any, Any, Any, Any] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.persistence = persistence
        self.strategy_control = strategy_control
        self.strategy_names = list(strategy_names)
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
            BotCommand("positions", "查看 open 持仓"),
            BotCommand("status", "系统运行状态"),
            BotCommand("signals", "最近信号"),
            BotCommand("strategies", "策略启停"),
            BotCommand("daily", "每日报告"),
            BotCommand("leaderboard", "各策略输赢战绩"),
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
        self.application.add_handler(CommandHandler("leaderboard", self._leaderboard))
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

    async def _leaderboard(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        await self._reply_rendered(
            update,
            lambda: self._format_leaderboard("all"),
            lambda: self._leaderboard_keyboard("all"),
        )

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
            case "lb":
                return self._format_leaderboard("all"), self._leaderboard_keyboard("all")
            case "lbt":
                return self._format_leaderboard("today"), self._leaderboard_keyboard("today")
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
        known_actions = {"m", "bk", "p", "st", "sg", "dy", "str", "lb", "lbt"}
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

    def _book_for_token(self, token_id: str) -> object | None:
        if self.books is None:
            return None
        reader = getattr(self.books, "book_for_token", None)
        if callable(reader):
            return reader(token_id)
        getter = getattr(self.books, "get", None)
        if callable(getter):
            return getter(token_id)
        return None

    def _market_for_position(self, row: dict[str, Any]) -> object | None:
        metrics = row.get("metrics")
        metric_values = metrics if isinstance(metrics, dict) else {}
        market_id = str(row.get("market_id") or metric_values.get("market_id") or "")
        if market_id:
            market = self.markets.get(market_id)
            if market is not None:
                return market
        token_id = report_token_id(row)
        return self.markets.for_token(token_id) if token_id else None

    def _format_positions(self) -> str:
        rows = self.persistence.query_report_open_positions()
        if not rows:
            return "暂无 open positions。"
        blocks: list[str] = []
        for row in rows:
            payload = _position_display_payload(
                row,
                market=self._market_for_position(row),
            )
            if not payload.get("side"):
                continue
            token_id = str(payload.get("token_id") or "")
            book = self._book_for_token(token_id) if token_id else None
            mark = getattr(book, "best_bid", None) if book is not None else None
            entry_price = float(payload.get("entry_price") or 0.0)
            shares = float(payload.get("shares") or 0.0)
            stake_usdc = float(payload.get("stake_usdc") or 0.0)
            lines = [
                f"📈 {self._safe(payload.get('asset'))} {self._safe(payload.get('timeframe'))} · {self._safe(payload.get('side'))}",
                f"Strategy  {self._safe(payload.get('strategy'))}",
                f"Entry     {entry_price:.4f}",
            ]
            if mark is None:
                lines.extend(["Mark      n/a (live book unavailable)", "PnL       n/a"])
            else:
                pnl = (mark - entry_price) * shares
                roi = pnl / stake_usdc if stake_usdc else 0.0
                sign = "+" if pnl >= 0 else ""
                lines.extend(
                    [
                        f"Mark      {mark:.4f}",
                        f"Shares    {shares:.4f}",
                        f"PnL       {sign}{pnl:.2f} USDC ({sign}{roi:.2%})",
                    ]
                )
            lines.extend(
                [
                    f"Opened    {self._format_age(payload.get('opened_at'))}",
                    f"ID        {self._safe(payload.get('report_position_id'))}",
                ]
            )
            blocks.append("\n".join(lines))
        if not blocks:
            return "暂无 open positions。"
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
        raw_candidate = row.get("candidate")
        candidate = raw_candidate if isinstance(raw_candidate, dict) else {}
        return "\n".join(
            [
                f"🔴 rejected · {self._safe(candidate.get('asset', '?'))} {self._safe(candidate.get('timeframe', '?'))} {self._safe(candidate.get('action', '?'))} {self._safe(candidate.get('side', '?'))}",
                f"{self._format_age(row.get('rejected_at'))} · {self._safe(candidate.get('strategy', '?'))} · {self._safe(row.get('reason_code', '?'))}",
                f"ID        {self._safe(candidate.get('signal_id', '?'))}",
            ]
        )

    def _format_daily(self) -> str:
        reports = self.persistence.query_daily_reports(limit=1)
        if not reports:
            return "暂无 daily report。"
        payload = reports[0]
        try:
            return self.formatter.daily_report_message(payload)
        except Exception:
            self.logger.exception("Invalid daily report payload")
            return "\n".join(
                [
                    "<b>📊 Daily Trading Report</b>",
                    self._safe(payload.get("report_date", "unknown")),
                    f"Signals {self._safe(payload.get('total_signals', 'unknown'))}",
                    f"PnL     {self._safe(payload.get('total_pnl_usdc', payload.get('net_pnl', 'unknown')))} USDC",
                    f"WR      {self._safe(payload.get('win_rate', 'unknown'))}",
                    f"ID      {self._safe(payload.get('report_id', 'unknown'))}",
                ]
            )

    def _report_timezone(self) -> ZoneInfo:
        timezone_name = "Asia/Bangkok"
        if self.scheduler is not None and hasattr(self.scheduler, "settings"):
            timezone_name = getattr(self.scheduler.settings.app, "timezone", timezone_name)
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")

    def _today_closed_bounds(self) -> tuple[datetime, datetime]:
        report_tz = self._report_timezone()
        today = datetime.now(report_tz).date()
        day_start_local = datetime.combine(today, time.min, tzinfo=report_tz)
        day_end_local = datetime.combine(today + timedelta(days=1), time.min, tzinfo=report_tz)
        return day_start_local.astimezone(UTC), day_end_local.astimezone(UTC)

    def _format_leaderboard(self, scope: Literal["all", "today"]) -> str:
        since: datetime | None = None
        until: datetime | None = None
        if scope == "today":
            since, until = self._today_closed_bounds()
        rows_raw = self.persistence.query_closed_trade_results(since=since, until=until)
        rows = build_strategy_leaderboard_rows(rows_raw)
        return self.formatter.strategy_leaderboard_message(rows, scope=scope)

    def _strategy_names(self) -> list[str]:
        return [name for name in self.strategy_names if name]

    def _toggle_callback_for(self, name: str) -> str | None:
        return telegram_render.toggle_callback_for(name)

    def _is_strategy_enabled(self, name: str) -> bool:
        return self.strategy_control.is_strategy_enabled(name)

    def _set_strategy_enabled(self, name: str, enabled: bool) -> None:
        self.strategy_control.set_strategy_enabled(name, enabled)

    def _disabled_strategy_names(self) -> list[str]:
        payload = self.strategy_control.status_payload()
        disabled = payload.get("disabled_strategies", ())
        if isinstance(disabled, list):
            return sorted(str(name) for name in disabled)
        return []


    def _format_strategies(self) -> str:
        lines = ["⚙️ Strategies"]
        for name in self._strategy_names():
            enabled = self._is_strategy_enabled(name)
            prefix = "✅" if enabled else "⏸"
            suffix = ""
            if self._toggle_callback_for(name) is None:
                suffix = " (cannot be toggled from Telegram)"
            reason = self.strategy_control.skip_reason_for(name)
            if reason and reason.startswith("dependency_disabled:"):
                suffix = f" ({reason})"
            lines.append(f"{prefix} {self._safe(name)}{suffix}")
        return "\n".join(lines)

    def _strategies_keyboard(self) -> InlineKeyboardMarkup:
        return telegram_render.strategies_keyboard(
            self._strategy_names(),
            is_enabled=self._is_strategy_enabled,
        )

    def _toggle_strategy(self, data: str) -> tuple[str, InlineKeyboardMarkup | None]:
        if not data.startswith("tg:"):
            raise ValueError("Unknown strategy")
        name = data[3:]
        names = set(self._strategy_names())
        if name not in names:
            raise ValueError("Unknown strategy")
        enabled = not self._is_strategy_enabled(name)
        self._set_strategy_enabled(name, enabled)
        disabled = self._disabled_strategy_names()
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
        return telegram_render.main_keyboard()

    def _leaderboard_keyboard(self, scope: Literal["all", "today"]) -> InlineKeyboardMarkup:
        return telegram_render.leaderboard_keyboard(scope)

    def _back_keyboard(self) -> InlineKeyboardMarkup:
        return telegram_render.back_keyboard()

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
        positions = self.persistence.query_report_open_positions()
        account = self.persistence.query_latest_report_account_snapshot() or {}
        health = self.persistence.query_latest_system_event("health_snapshot") or {}
        status = str(health.get("status") or "unknown")
        emoji = "🟢" if status == "ok" else "🟡" if status == "degraded" else "🔴"
        strategies = list(self.strategy_names)
        enabled_count = sum(1 for name in strategies if self._is_strategy_enabled(name))
        total_count = len(strategies)
        equity = float(account.get("equity", 0.0) or 0.0)
        health_age = self._format_age(health.get("created_at")) if health else "n/a"
        return "\n".join(
            [
                f"{emoji} PolySignal Lab: {self._safe(status)}",
                f"Health age  {health_age}",
                f"Markets     {len(self.markets.markets)} tracked",
                f"Positions   {len(positions)} open",
                f"Account     {equity:.2f} USDC equity",
                f"Signals     {counts.get('signals', 0)} accepted / {counts.get('rejected_signals', 0)} rejected",
                f"Strategies  {enabled_count}/{total_count} enabled",
                f"Telegram    {'polling ok' if self._running else 'not polling'}",
            ]
        )

    def _safe(self, value: object) -> str:
        return telegram_render.safe_text(value)

    def _parse_time(self, value: object) -> datetime | None:
        return telegram_render.parse_time(value)

    def _format_age(self, value: object) -> str:
        return telegram_render.format_age(value)

    def _truncate(self, text: str) -> str:
        return telegram_render.truncate_text(text, self.config.max_message_chars)


def _position_display_payload(
    row: dict[str, Any],
    *,
    market: object | None = None,
) -> dict[str, Any]:
    return telegram_render.position_display_payload(row, market=market)


def _row_float(row: dict[str, Any], *keys: str) -> float | None:
    return telegram_render.row_float(row, *keys)
