from __future__ import annotations

import html
import math
from datetime import date
from typing import Literal

from collections.abc import Mapping

from polysignal_lab.domain.enums import TradeResultStatus
from polysignal_lab.domain.reporting_result import (
    report_date_text,
    report_nested_mapping,
    trade_result_display,
    trade_result_number,
    trade_result_status,
)
from polysignal_lab.domain.missing_values import (
    COLLAPSE_COMPONENT,
    missing_value_counter,
)
from polysignal_lab.domain.signal import SignalCandidate

_NA = "n/a"


def _read_number(result: Mapping[str, object], key: str) -> float | None:
    """Read a numeric trade-result field, counting a missing value as a collapse.

    The publish path is a bypass: a missing value must not collapse to zero nor
    interrupt the message, so the caller degrades to ``n/a`` and this helper
    records the collapse.
    """
    value = trade_result_number(result, key)
    if value is None:
        counter = missing_value_counter()
        if counter is not None:
            counter.inc_metric(COLLAPSE_COMPONENT, f"collapsed_{key}")
    return value


def _format_number(result: Mapping[str, object], key: str, spec: str) -> str:
    """Format a numeric trade-result field, degrading missing values to n/a."""
    value = _read_number(result, key)
    return _NA if value is None else format(value, spec)


def _count_collapse(key: str) -> None:
    """Record a single missing-value collapse for ``key`` when a counter is bound."""
    counter = missing_value_counter()
    if counter is not None:
        counter.inc_metric(COLLAPSE_COMPONENT, f"collapsed_{key}")


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

Mode: Sandbox
ID: <code>{html.escape(signal.signal_id)}</code>"""
        return self._truncate(message)

    def result_message(self, result: Mapping[str, object]) -> str:
        pnl = _read_number(result, "pnl_usdc")
        roi = _read_number(result, "roi")
        pnl_text = _NA if pnl is None else f"{'+' if pnl >= 0 else ''}{pnl:.4f}"
        roi_text = _NA if roi is None else f"{'+' if roi >= 0 else ''}{roi:.2%}"
        status = trade_result_status(result)
        match status:
            case TradeResultStatus.WIN:
                emoji = "✅"
            case TradeResultStatus.LOSS:
                emoji = "🔴"
            case _:
                emoji = "⚪"
        asset = trade_result_display(result, "asset")
        timeframe = trade_result_display(result, "timeframe")
        strategy = trade_result_display(result, "strategy")
        side = trade_result_display(result, "side")
        signal_id = trade_result_display(result, "signal_id")
        if not signal_id:
            _count_collapse("signal_id")
        entry_text = _format_number(result, "entry_price", ".4f")
        stake_text = _format_number(result, "stake_usdc", ".2f")
        shares_text = _format_number(result, "shares", ".4f")
        settle_text = _format_number(result, "settlement_value", ".4f")
        message = f"""<b>{emoji} {html.escape(asset)} {html.escape(timeframe)} · {html.escape(status.value)}</b>
<code>{html.escape(strategy)}</code>

Side   {html.escape(side)}
Entry  {entry_text}
Stake  {stake_text} USDC
Shares {shares_text}

PnL    {pnl_text} USDC
ROI    {roi_text}
Settle {settle_text} USDC

Mode: Sandbox
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

Mode: Sandbox
Order  <code>{html.escape(str(fill.get("client_order_id", "")))}</code>
FillID <code>{html.escape(str(fill.get("report_fill_id", "")))}</code>"""
        return self._truncate(message)

    def daily_report_message(self, report: object) -> str:
        equity_currency = _report_text(report, "equity_currency", "USDC")
        equity_source = _report_text(report, "equity_source")
        source_labels = {
            "portfolio": "Portfolio",
            "account_balance": "Account balance",
            "starting_balance": "Starting balance",
            "report_results": "Report results",
        }
        source_line = (
            f"\nSource  {html.escape(source_labels[equity_source])}"
            if equity_source in source_labels
            else ""
        )
        revision = int(_report_float(report, "revision", 1.0))
        title = (
            "📊 Daily Trading Report"
            if revision <= 1
            else f"♻️ Daily Trading Report Correction · Revision {revision}"
        )
        reasons_raw = (
            report.get("telemetry_incomplete_reasons", ())
            if isinstance(report, Mapping)
            else getattr(report, "telemetry_incomplete_reasons", ())
        )
        reasons = (
            [str(reason) for reason in reasons_raw]
            if isinstance(reasons_raw, (list, tuple))
            else []
        )
        telemetry_text = _report_text(
            report,
            "telemetry_status",
            "complete",
        ).upper()
        if reasons:
            telemetry_text += f" ({', '.join(reasons)})"
        lines = []
        strategy_breakdown = report_nested_mapping(report, "strategy_breakdown")
        for strategy, row in strategy_breakdown.items():
            if not isinstance(row, dict):
                continue
            closed = int(row.get("closed_positions", 0))
            voids = int(row.get("void_count", 0))
            trade_word = "trade" if closed == 1 else "trades"
            wl = f"{row.get('win_count', 0)}W/{row.get('loss_count', 0)}L"
            if voids > 0:
                wl += f"/{voids}V"
            lines.append(
                f"• {html.escape(strategy)}: {closed} {trade_word}, "
                f"{wl}, "
                f"{float(row.get('total_pnl_usdc', 0.0)):+.2f} "
                f"{html.escape(equity_currency)}"
            )
        strategy_text = "\n".join(lines) if lines else "• No closed trades"
        rejects_by_reason = report_nested_mapping(report, "rejects_by_reason")
        reject_text = "none"
        if rejects_by_reason:
            reject_text = ", ".join(
                f"{reason}:{count}"
                for reason, count in sorted(rejects_by_reason.items())
                if isinstance(count, (int, float))
            )
        exec_lag_value = _row_optional_float(report, "average_execution_staleness_ms")
        exec_lag = "n/a" if exec_lag_value is None else f"{exec_lag_value:.0f} ms"
        win_count = int(_report_float(report, "win_count"))
        loss_count = int(_report_float(report, "loss_count"))
        void_count = int(_report_float(report, "void_count"))
        wl_line = f"{win_count} / {loss_count}"
        if void_count > 0:
            wl_line += f" / {void_count}V"
        message = f"""<b>{title}</b>
{report_date_text(report)}

Equity  {_report_float(report, "starting_equity"):.2f} → {_report_float(report, "ending_equity"):.2f} {html.escape(equity_currency)}{source_line}
PnL     {_report_float(report, "net_pnl"):+.2f} {html.escape(equity_currency)}
ROI     {_report_float(report, "return_rate"):+.2%}

Signals {int(_report_float(report, "total_signals"))}
Orders  {int(_report_float(report, "order_count"))}
Rejects {int(_report_float(report, "rejected_order_count"))} ({reject_text})
ExecLag {exec_lag}
Telemetry {html.escape(telemetry_text)}
Filled  {int(_report_float(report, "fill_count"))}
Closed  {int(_report_float(report, "closed_positions"))}
W/L     {wl_line}
WR      {_report_float(report, "win_rate"):.2%}

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
        parsed = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _report_float(
    row: Mapping[str, object] | object, key: str, default: float = 0.0
) -> float:
    """Read a numeric report field at the publish convergence point.

    The publish path is an external interface: a missing value degrades to
    the provided default rather than propagating ``None`` upward.
    """
    value = _row_optional_float(row, key)
    return default if value is None else value


def _report_text(
    row: Mapping[str, object] | object, key: str, default: str = ""
) -> str:
    """Read a text report field at the publish convergence point."""
    if isinstance(row, Mapping):
        value = row.get(key, default)
    else:
        value = getattr(row, key, default)
    if value is None:
        return default
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
