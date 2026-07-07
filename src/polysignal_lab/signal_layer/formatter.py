"""
Input: __future__, __future__.annotations, html, typing, typing.Literal, polysignal_lab.domain.enums, polysignal_lab.domain.enums.TradeResultStatus, polysignal_lab.domain.paper_result, polysignal_lab.domain.paper_result.DailyReport, polysignal_lab.domain.paper_result.PaperTradeResult
Output: MessageFormatter
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

import html
from typing import Literal

from polysignal_lab.domain.enums import TradeResultStatus
from polysignal_lab.domain.paper_result import DailyReport, PaperTradeResult
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

    def result_message(self, result: PaperTradeResult) -> str:
        sign = "+" if result.pnl_usdc >= 0 else ""
        match result.result:
            case TradeResultStatus.WIN:
                emoji = "✅"
            case TradeResultStatus.LOSS:
                emoji = "🔴"
            case _:
                emoji = "⚪"
        message = f"""<b>{emoji} {html.escape(result.asset)} {html.escape(result.timeframe)} · {html.escape(result.result.value)}</b>
<code>{html.escape(result.strategy)}</code>

Side   {html.escape(result.side.value)}
Entry  {result.entry_price:.4f}
Stake  {result.stake_usdc:.2f} USDC
Shares {result.shares:.4f}

PnL    {sign}{result.pnl_usdc:.4f} USDC
ROI    {sign}{result.roi:.2%}
Settle {result.settlement_value:.4f} USDC

Mode: Paper
ID: <code>{html.escape(result.signal_id)}</code>"""
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

    def daily_report_message(self, report: DailyReport) -> str:
        lines = []
        for strategy, row in report.strategy_breakdown.items():
            closed = row.get("closed_positions", 0)
            trade_word = "trade" if closed == 1 else "trades"
            lines.append(
                f"• {html.escape(strategy)}: {closed} {trade_word}, "
                f"{row.get('win_count', 0)}W/{row.get('loss_count', 0)}L, "
                f"{row.get('total_pnl_usdc', 0.0):+.2f} USDC"
            )
        strategy_text = "\n".join(lines) if lines else "• No closed trades"
        reject_text = "none"
        if report.paper_rejects_by_reason:
            reject_text = ", ".join(
                f"{reason}:{count}" for reason, count in sorted(report.paper_rejects_by_reason.items())
            )
        exec_lag = (
            "n/a"
            if report.average_execution_staleness_ms is None
            else f"{report.average_execution_staleness_ms:.0f} ms"
        )
        message = f"""<b>📊 Daily Paper Report</b>
{report.report_date.isoformat()}

Equity  {report.starting_equity:.2f} → {report.ending_equity:.2f} USDC
PnL     {report.paper_pnl:+.2f} USDC
ROI     {report.paper_roi:+.2%}

Signals {report.total_signals}
Orders  {report.paper_orders}
Rejects {report.rejected_paper_orders} ({reject_text})
ExecLag {exec_lag}
Filled  {report.paper_fills}
Closed  {report.closed_positions}
W/L     {report.win_count} / {report.loss_count}
WR      {report.win_rate:.2%}

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
