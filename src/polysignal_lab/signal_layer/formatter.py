"""
Input: __future__, __future__.annotations, html, typing, typing.Literal, polysignal_lab.domain.enums, polysignal_lab.domain.enums.TradeResultStatus, polysignal_lab.domain.paper_result, polysignal_lab.domain.paper_result.report_date_text, polysignal_lab.domain.paper_result.report_float, polysignal_lab.domain.paper_result.report_nested_mapping, polysignal_lab.domain.paper_result.report_text, polysignal_lab.domain.paper_result.trade_result_float, polysignal_lab.domain.paper_result.trade_result_status, polysignal_lab.domain.paper_result.trade_result_text
Output: PaperTradeResultRow helpers, DailyReportRow helpers, MessageFormatter
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import html
from typing import Literal

from collections.abc import Mapping

from polysignal_lab.domain.enums import TradeResultStatus
from polysignal_lab.domain.paper_result import (
    report_date_text,
    report_float,
    report_nested_mapping,
    report_text,
    trade_result_float,
    trade_result_status,
    trade_result_text,
)
from polysignal_lab.domain.signal import SignalCandidate


class MessageFormatter:
    def __init__(self, max_chars: int = 4096) -> None:
        self.max_chars = max_chars

    def signal_message(self, signal: SignalCandidate, stake_usdc: float) -> str:
        why = "\n".join(f"• {html.escape(code)}" for code in signal.reason_codes)
        message = f"""<b>🟢 {html.escape(signal.asset)} {html.escape(signal.timeframe)} · {html.escape(signal.action.value)} {html.escape(signal.side.value)}</b>
<code>{html.escape(signal.strategy)}</code>

Entry  {signal.entry_reference_price:.4f}
Max    {signal.max_entry_price:.4f}
Stake  {stake_usdc:.2f} USDC
Conf   {signal.confidence:.0%}
Close  {self._format_seconds(signal.seconds_to_close)}

<b>Why</b>
{why}

Mode: Paper
ID: <code>{html.escape(signal.signal_id)}</code>"""
        return self._truncate(message)

    def result_message(self, result: Mapping[str, object]) -> str:
        pnl_usdc = trade_result_float(result, "pnl_usdc")
        sign = "+" if pnl_usdc >= 0 else ""
        status = trade_result_status(result)
        match status:
            case TradeResultStatus.WIN:
                emoji = "✅"
            case TradeResultStatus.LOSS:
                emoji = "🔴"
            case _:
                emoji = "⚪"
        asset = trade_result_text(result, "asset")
        timeframe = trade_result_text(result, "timeframe")
        strategy = trade_result_text(result, "strategy")
        side = trade_result_text(result, "side")
        signal_id = trade_result_text(result, "signal_id")
        message = f"""<b>{emoji} {html.escape(asset)} {html.escape(timeframe)} · {html.escape(status.value)}</b>
<code>{html.escape(strategy)}</code>

Side   {html.escape(side)}
Entry  {trade_result_float(result, "entry_price"):.4f}
Stake  {trade_result_float(result, "stake_usdc"):.2f} USDC
Shares {trade_result_float(result, "shares"):.4f}

PnL    {sign}{pnl_usdc:.4f} USDC
ROI    {sign}{trade_result_float(result, "roi"):.2%}
Settle {trade_result_float(result, "settlement_value"):.4f} USDC

Mode: Paper
ID: <code>{html.escape(signal_id)}</code>"""
        return self._truncate(message)

    def nautilus_fill_message(self, fill: dict[str, object]) -> str:
        fill_price = _float_value(fill.get("fill_price", 0.0))
        shares = _float_value(fill.get("shares", 0.0))
        stake_usdc = _float_value(fill.get("stake_usdc", 0.0))
        message = f"""<b>🟦 {html.escape(str(fill.get("asset", "")))} {html.escape(str(fill.get("timeframe", "")))} · FILL {html.escape(str(fill.get("side", "")))}</b>
<code>{html.escape(str(fill.get("strategy", "")))}</code>

Fill   {fill_price:.4f}
Shares {shares:.4f}
Stake  {stake_usdc:.2f} USDC

Mode: Paper
Order  <code>{html.escape(str(fill.get("client_order_id", "")))}</code>
FillID <code>{html.escape(str(fill.get("paper_fill_id", "")))}</code>"""
        return self._truncate(message)

    def daily_report_message(self, report: Mapping[str, object]) -> str:
        equity_currency = report_text(report, "equity_currency", "USDC")
        revision = int(report_float(report, "revision", 1.0))
        title = (
            "📊 Daily Paper Report"
            if revision <= 1
            else f"♻️ Daily Paper Report Correction · Revision {revision}"
        )
        lines = []
        strategy_breakdown = report_nested_mapping(report, "strategy_breakdown")
        for strategy, row in strategy_breakdown.items():
            if not isinstance(row, dict):
                continue
            closed = int(row.get("closed_positions", 0))
            trade_word = "trade" if closed == 1 else "trades"
            lines.append(
                f"• {html.escape(strategy)}: {closed} {trade_word}, "
                f"{row.get('win_count', 0)}W/{row.get('loss_count', 0)}L, "
                f"{float(row.get('total_pnl_usdc', 0.0)):+.2f} USDC"
            )
        strategy_text = "\n".join(lines) if lines else "• No closed trades"
        rejects_by_reason = report_nested_mapping(report, "paper_rejects_by_reason")
        reject_text = "none"
        if rejects_by_reason:
            reject_text = ", ".join(
                f"{reason}:{count}"
                for reason, count in sorted(rejects_by_reason.items())
                if isinstance(count, (int, float))
            )
        exec_lag_value = _row_optional_float(report, "average_execution_staleness_ms")
        exec_lag = "n/a" if exec_lag_value is None else f"{exec_lag_value:.0f} ms"
        message = f"""<b>{title}</b>
{report_date_text(report)}

Equity  {report_float(report, 'starting_equity'):.2f} → {report_float(report, 'ending_equity'):.2f} {html.escape(equity_currency)}
PnL     {report_float(report, 'paper_pnl'):+.2f} {html.escape(equity_currency)}
ROI     {report_float(report, 'paper_roi'):+.2%}

Signals {int(report_float(report, 'total_signals'))}
Orders  {int(report_float(report, 'paper_orders'))}
Rejects {int(report_float(report, 'rejected_paper_orders'))} ({reject_text})
ExecLag {exec_lag}
Filled  {int(report_float(report, 'paper_fills'))}
Closed  {int(report_float(report, 'closed_positions'))}
W/L     {int(report_float(report, 'win_count'))} / {int(report_float(report, 'loss_count'))}
WR      {report_float(report, 'win_rate'):.2%}

<b>Strategies</b>
{strategy_text}"""
        return self._truncate(message)

    def strategy_leaderboard_message(
        self,
        rows: list[dict[str, float | int | str]],
        scope: Literal["all", "today"] = "all",
    ) -> str:
        scope_label = "累计" if scope == "all" else "今日"
        header = f"<b>🏆 Strategy Leaderboard ({scope_label})</b>"
        if not rows:
            return f"{header}\n暂无已结算策略战绩。"
        lines = []
        for row in rows:
            closed = int(row.get("closed_positions", 0))
            trade_word = "trade" if closed == 1 else "trades"
            lines.append(
                f"• {html.escape(str(row.get('strategy', '?')))}: {closed} {trade_word}, "
                f"{int(row.get('win_count', 0))}W/{int(row.get('loss_count', 0))}L/"
                f"{int(row.get('void_count', 0))}V, "
                f"{float(row.get('total_pnl_usdc', 0.0)):+.2f} USDC, "
                f"WR {float(row.get('win_rate', 0.0)):.1%}"
            )
        message = header + "\n" + "\n".join(lines)
        return self._truncate(message)

    def _format_seconds(self, seconds: int | None) -> str:
        if seconds is None:
            return "unknown"
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def _truncate(self, message: str) -> str:
        if len(message) <= self.max_chars:
            return message
        return message[: self.max_chars - 32] + "\n[truncated for Telegram]"


def _float_value(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _row_optional_float(row: Mapping[str, object] | object, key: str) -> float | None:
    if isinstance(row, Mapping):
        value = row.get(key)
    else:
        value = getattr(row, key, None)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except ValueError:
        return None
