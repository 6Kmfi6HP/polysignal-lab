"""
Input: __future__, __future__.annotations, collections, collections.Counter, collections.defaultdict, datetime, datetime.date, typing, typing.Any, typing.Iterable
Output: normalize_paper_reject_reason, is_rejected_paper_order_payload, PaperReportService
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from collections.abc import Iterable, Mapping
from typing import Any

from polysignal_lab.domain.enums import TradeResultStatus
from polysignal_lab.domain.paper_result import (
    DailyReport,
    trade_result_float,
    trade_result_status,
    trade_result_text,
)
from polysignal_lab.paper.report_aggregates import (
    average as _average,
    calibration_breakdown as _calibration_breakdown,
    is_closed_result as _is_closed_result,
    optional_float as _optional_float,
)
from polysignal_lab.paper.report_rejections import (
    is_rejected_paper_order_payload,
    normalize_paper_reject_reason,
)


class PaperReportService:
    def build_daily_report(
        self,
        *,
        report_date: date,
        starting_equity: float,
        ending_equity: float,
        equity_currency: str = "USDC",
        total_signals: int,
        paper_orders: int,
        paper_fills: int,
        rejected_paper_orders: int,
        open_positions: int,
        results: Iterable[Mapping[str, Any]],
        equity_curve: list[float] | None = None,
        stale_paper_fills: int = 0,
        paper_order_payloads: Iterable[dict[str, Any]] = (),
        paper_fill_payloads: Iterable[dict[str, Any]] = (),
        paper_reject_payloads: Iterable[dict[str, Any]] | None = None,
        paper_execution_assumptions: dict[str, Any] | None = None,
        telemetry_incomplete_reasons: Iterable[str] = (),
    ) -> DailyReport:
        result_list = list(results)
        incomplete_reasons = sorted(set(telemetry_incomplete_reasons))
        closed = [r for r in result_list if _is_closed_result(r)]
        wins = sum(1 for r in closed if trade_result_status(r) == TradeResultStatus.WIN)
        losses = sum(1 for r in closed if trade_result_status(r) == TradeResultStatus.LOSS)
        voids = sum(1 for r in closed if trade_result_status(r) == TradeResultStatus.VOID)
        denominator = len(closed)
        win_rate = wins / denominator if denominator else 0.0
        total_pnl = sum(trade_result_float(r, "pnl_usdc") for r in closed)
        avg_roi = sum(trade_result_float(r, "roi") for r in closed) / len(closed) if closed else 0.0
        profit = sum(trade_result_float(r, "pnl_usdc") for r in closed if trade_result_float(r, "pnl_usdc") > 0)
        loss = abs(sum(trade_result_float(r, "pnl_usdc") for r in closed if trade_result_float(r, "pnl_usdc") < 0))
        profit_factor = profit / loss if loss else None
        curve = equity_curve or [starting_equity, ending_equity]
        max_drawdown = self._max_drawdown(curve)
        execution_aggregates = self._paper_execution_aggregates(
            paper_order_payloads,
            paper_fill_payloads,
            paper_execution_assumptions or {},
            paper_reject_payloads=paper_reject_payloads,
        )
        return DailyReport(
            report_date=report_date,
            starting_equity=starting_equity,
            ending_equity=ending_equity,
            equity_currency=equity_currency,
            paper_pnl=ending_equity - starting_equity,
            paper_roi=(ending_equity - starting_equity) / starting_equity if starting_equity else 0.0,
            total_signals=total_signals,
            paper_orders=paper_orders,
            paper_fills=paper_fills,
            rejected_paper_orders=rejected_paper_orders,
            stale_paper_fills=stale_paper_fills,
            paper_attempts_by_intent=execution_aggregates["paper_attempts_by_intent"],
            paper_fills_by_intent=execution_aggregates["paper_fills_by_intent"],
            paper_partial_fills_by_intent=execution_aggregates[
                "paper_partial_fills_by_intent"
            ],
            paper_rejects_by_reason=execution_aggregates["paper_rejects_by_reason"],
            paper_rejects_by_original_reason=execution_aggregates[
                "paper_rejects_by_original_reason"
            ],
            average_execution_staleness_ms=execution_aggregates[
                "average_execution_staleness_ms"
            ],
            average_executable_depth_usdc=execution_aggregates[
                "average_executable_depth_usdc"
            ],
            paper_execution_assumptions=execution_aggregates[
                "paper_execution_assumptions"
            ],
            telemetry_status=(
                "incomplete" if incomplete_reasons else "complete"
            ),
            telemetry_incomplete_reasons=incomplete_reasons,
            open_positions=open_positions,
            closed_positions=len(closed),
            win_count=wins,
            loss_count=losses,
            void_count=voids,
            win_rate=win_rate,
            total_pnl_usdc=total_pnl,
            average_roi=avg_roi,
            max_drawdown=max_drawdown,
            profit_factor=profit_factor,
            strategy_breakdown=self._breakdown(closed, "strategy"),
            asset_breakdown=self._breakdown(closed, "asset"),
            timeframe_breakdown=self._breakdown(closed, "timeframe"),
            calibration_breakdown=_calibration_breakdown(closed),
        )

    def _paper_execution_aggregates(
        self,
        paper_orders: Iterable[dict[str, Any]],
        paper_fills: Iterable[dict[str, Any]],
        assumptions: dict[str, Any],
        *,
        paper_reject_payloads: Iterable[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        orders = list(paper_orders)
        reject_orders = (
            list(paper_reject_payloads)
            if paper_reject_payloads is not None
            else orders
        )
        fills = list(paper_fills)
        order_intents: dict[str, str] = {}
        attempts: Counter[str] = Counter()
        rejects: Counter[str] = Counter()
        original_rejects: Counter[str] = Counter()
        staleness_values: list[float] = []
        depth_values: list[float] = []
        for order in orders:
            metrics_payload = order.get("metrics")
            metrics = metrics_payload if isinstance(metrics_payload, dict) else {}
            intent = str(
                metrics.get("paper_order_intent")
                or order.get("order_intent")
                or "default"
            )
            order_id = str(order.get("paper_order_id") or "")
            if order_id:
                order_intents[order_id] = intent
            attempts[intent] += 1
            staleness = _optional_float(metrics.get("paper_orderbook_staleness_ms"))
            if staleness is not None:
                staleness_values.append(staleness)
            depth = _optional_float(metrics.get("paper_available_depth_usdc"))
            if depth is not None:
                depth_values.append(depth)
        for order in reject_orders:
            metrics_payload = order.get("metrics")
            metrics = metrics_payload if isinstance(metrics_payload, dict) else {}
            if is_rejected_paper_order_payload(order, metrics):
                normalized = normalize_paper_reject_reason(
                    metrics.get("paper_normalized_reason")
                    or order.get("reject_reason")
                )
                original = str(
                    metrics.get("paper_original_reason")
                    or order.get("reject_reason")
                    or "UNKNOWN"
                )
                rejects[normalized] += 1
                original_rejects[original] += 1
        fills_by_intent: Counter[str] = Counter()
        partial_by_intent: Counter[str] = Counter()
        for fill in fills:
            order_id = str(fill.get("paper_order_id") or "")
            intent = str(
                fill.get("paper_order_intent")
                or fill.get("order_intent")
                or order_intents.get(order_id, "default")
            )
            fills_by_intent[intent] += 1
            fill_ratio = _optional_float(fill.get("fill_ratio"))
            if fill_ratio is not None and fill_ratio < 0.999:
                partial_by_intent[intent] += 1
        return {
            "paper_attempts_by_intent": dict(sorted(attempts.items())),
            "paper_fills_by_intent": dict(sorted(fills_by_intent.items())),
            "paper_partial_fills_by_intent": dict(sorted(partial_by_intent.items())),
            "paper_rejects_by_reason": dict(sorted(rejects.items())),
            "paper_rejects_by_original_reason": dict(sorted(original_rejects.items())),
            "average_execution_staleness_ms": _average(staleness_values),
            "average_executable_depth_usdc": _average(depth_values),
            "paper_execution_assumptions": dict(sorted(assumptions.items())),
        }


    def _breakdown(self, results: list[Mapping[str, Any]], attr: str) -> dict[str, dict[str, float | int]]:
        rows: dict[str, dict[str, float | int]] = defaultdict(lambda: {"closed_positions": 0, "win_count": 0, "loss_count": 0, "void_count": 0, "total_pnl_usdc": 0.0, "average_roi": 0.0})
        roi_sum: dict[str, float] = defaultdict(float)
        for r in results:
            key = trade_result_text(r, attr)
            row = rows[key]
            row["closed_positions"] += 1
            status = trade_result_status(r)
            row["win_count"] += 1 if status == TradeResultStatus.WIN else 0
            row["loss_count"] += 1 if status == TradeResultStatus.LOSS else 0
            row["void_count"] += 1 if status == TradeResultStatus.VOID else 0
            row["total_pnl_usdc"] += trade_result_float(r, "pnl_usdc")
            roi_sum[key] += trade_result_float(r, "roi")
        for key, row in rows.items():
            count = row["closed_positions"] or 1
            row["average_roi"] = roi_sum[key] / count
            wins = row["win_count"]
            row["win_rate"] = wins / count if count else 0.0
        return dict(rows)

    def _max_drawdown(self, curve: list[float]) -> float:
        if not curve:
            return 0.0
        peak = curve[0]
        max_dd = 0.0
        for value in curve:
            peak = max(peak, value)
            if peak > 0:
                max_dd = max(max_dd, (peak - value) / peak)
        return max_dd
