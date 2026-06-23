from __future__ import annotations

import html
from datetime import date

from polysignal_lab.domain.paper_result import DailyReport, PaperTradeResult
from polysignal_lab.domain.signal import SignalCandidate


class MessageFormatter:
    def __init__(self, max_chars: int = 4096) -> None:
        self.max_chars = max_chars

    def signal_message(self, signal: SignalCandidate, stake_usdc: float) -> str:
        why = "\n".join(f"- {html.escape(code)}" for code in signal.reason_codes)
        message = f"""[PolySignal Lab]

Market: {html.escape(signal.asset)} Up/Down {html.escape(signal.timeframe)}
Strategy: {html.escape(signal.strategy)}
Action: BUY {html.escape(signal.side.value)}

Reference Entry: {signal.entry_reference_price:.4f}
Max Entry: {signal.max_entry_price:.4f}
Paper Stake: {stake_usdc:.2f} USDC
Confidence: {signal.confidence:.0%}
Time Left: {self._format_seconds(signal.seconds_to_close)}

Why:
{why}

Paper Simulation:
- A virtual paper trade will be opened.
- This is not a real order.

Risk:
- Manual execution only.
- Do not chase above max entry.
- This is a signal, not financial advice.
- No profit guarantee.

Signal ID:
{html.escape(signal.signal_id)}"""
        return self._truncate(message)

    def result_message(self, result: PaperTradeResult) -> str:
        sign = "+" if result.pnl_usdc >= 0 else ""
        message = f"""[PolySignal Lab Result]

Signal: {html.escape(result.signal_id)}
Market: {html.escape(result.asset)} Up/Down {html.escape(result.timeframe)}
Paper Side: {html.escape(result.side.value)}
Paper Entry: {result.entry_price:.4f}
Paper Stake: {result.stake_usdc:.2f} USDC
Paper Shares: {result.shares:.4f}

Result: {html.escape(result.result.value)}
Settlement Value: {result.settlement_value:.4f} USDC
Paper PnL: {sign}{result.pnl_usdc:.4f} USDC
ROI: {sign}{result.roi:.2%}

Strategy:
{html.escape(result.strategy)}

Note:
Paper result only. No real order was placed. No profit guarantee."""
        return self._truncate(message)

    def daily_report_message(self, report: DailyReport) -> str:
        lines = []
        for strategy, row in report.strategy_breakdown.items():
            lines.append(f"- {strategy}: {row.get('closed_positions', 0)} trades, {row.get('win_count', 0)}W / {row.get('loss_count', 0)}L, {row.get('total_pnl_usdc', 0.0):+.2f} USDC")
        strategy_text = "\n".join(lines) if lines else "- No closed trades"
        message = f"""[PolySignal Lab Daily Paper Report]

Date: {report.report_date.isoformat()}
Starting Equity: {report.starting_equity:.2f} USDC
Ending Equity: {report.ending_equity:.2f} USDC
Paper PnL: {report.paper_pnl:+.2f} USDC
Paper ROI: {report.paper_roi:+.2%}

Signals: {report.total_signals}
Paper Filled: {report.paper_fills}
Closed Trades: {report.closed_positions}
Wins: {report.win_count}
Losses: {report.loss_count}
Win Rate: {report.win_rate:.2%}

By Strategy:
{strategy_text}

Notes:
Paper results only. No real trades were placed. No profit guarantee."""
        return self._truncate(message)

    def _format_seconds(self, seconds: int | None) -> str:
        if seconds is None:
            return "unknown"
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def _truncate(self, message: str) -> str:
        if len(message) <= self.max_chars:
            return message
        return message[: self.max_chars - 32] + "\n[truncated for Telegram]"
