"""
Input: __future__, __future__.annotations, html, collections.abc, collections.abc.Callable, datetime, datetime.datetime, datetime.timezone, telegram, typing, typing.Any, typing.Literal
Output: main_keyboard, back_keyboard, leaderboard_keyboard, strategies_keyboard, toggle_callback_for, safe_text, parse_time, format_age, truncate_text, position_display_payload, row_float
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

import html
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Literal

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def toggle_callback_for(name: str) -> str | None:
    data = f"tg:{name}"
    return data if len(data.encode("utf-8")) <= 64 else None


def main_keyboard() -> InlineKeyboardMarkup:
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
            [InlineKeyboardButton("🏆 策略战绩", callback_data="lb")],
        ]
    )


def leaderboard_keyboard(scope: Literal["all", "today"]) -> InlineKeyboardMarkup:
    if scope == "today":
        toggle_row = [
            InlineKeyboardButton("📅 今日 ✓", callback_data="lbt"),
            InlineKeyboardButton("📈 累计", callback_data="lb"),
        ]
    else:
        toggle_row = [
            InlineKeyboardButton("📅 今日", callback_data="lbt"),
            InlineKeyboardButton("📈 累计 ✓", callback_data="lb"),
        ]
    return InlineKeyboardMarkup([toggle_row, [InlineKeyboardButton("⬅️ 返回", callback_data="bk")]])


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ 返回", callback_data="bk")]])


def strategies_keyboard(
    strategy_names: list[str],
    *,
    is_enabled: Callable[[str], bool],
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for name in strategy_names:
        callback_data = toggle_callback_for(name)
        if callback_data is None:
            continue
        enabled = bool(is_enabled(name))
        label = f"{'⏸' if enabled else '▶️'} {name}"
        rows.append([InlineKeyboardButton(label, callback_data=callback_data)])
    rows.append([InlineKeyboardButton("⬅️ 返回", callback_data="bk")])
    return InlineKeyboardMarkup(rows)


def safe_text(value: object) -> str:
    return html.escape(str(value))


def parse_time(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def format_age(value: object) -> str:
    dt = parse_time(value)
    if dt is None:
        return "unknown"
    seconds = max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    return f"{seconds // 3600}h{(seconds % 3600) // 60}m ago"


def truncate_text(text: str, max_message_chars: int) -> str:
    if len(text) <= max_message_chars:
        return text
    return text[: max_message_chars - 32] + "\n[truncated for Telegram]"


def position_display_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize open-position rows for Telegram display without PaperPosition."""
    payload = dict(row)
    raw_metrics = payload.get("metrics")
    metrics = raw_metrics if isinstance(raw_metrics, dict) else {}
    token_id = str(payload.get("token_id") or payload.get("instrument_id") or "")
    head, _, _ = token_id.partition(".")
    token_id = head or token_id
    entry_price = row_float(payload, "entry_price", "avg_entry_price", "price")
    shares = row_float(payload, "shares", "quantity")
    stake = row_float(payload, "stake_usdc")
    if stake is None and entry_price is not None and shares is not None:
        stake = entry_price * abs(shares)
    side = str(payload.get("side") or metrics.get("side") or "").upper()
    if side not in {"UP", "DOWN"}:
        side = ""
    return {
        **payload,
        "paper_position_id": payload.get("paper_position_id") or payload.get("position_id") or "",
        "token_id": token_id,
        "side": side,
        "asset": payload.get("asset") or metrics.get("asset") or "",
        "timeframe": payload.get("timeframe") or metrics.get("timeframe") or "",
        "strategy": payload.get("strategy") or metrics.get("strategy") or "",
        "entry_price": entry_price if entry_price is not None else 0.0,
        "shares": shares if shares is not None else 0.0,
        "stake_usdc": stake if stake is not None else 0.0,
        "opened_at": payload.get("opened_at") or payload.get("ts") or payload.get("created_at"),
    }


def row_float(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = row.get(key)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None
