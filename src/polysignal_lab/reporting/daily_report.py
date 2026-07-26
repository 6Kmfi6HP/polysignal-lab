from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from collections.abc import Iterable, Mapping
from typing import Any

from polysignal_lab.domain.enums import TradeResultStatus
from polysignal_lab.domain.reporting_result import (
    DailyReport,
    EquitySource,
    trade_result_float,
    trade_result_status,
    trade_result_text,
)
from polysignal_lab.reporting.aggregates import (
    average as _average,
    calibration_breakdown as _calibration_breakdown,
    is_closed_result as _is_closed_result,
    optional_float as _optional_float,
)
from polysignal_lab.reporting.rejections import (
    is_rejected_order_payload,
    normalize_reject_reason,
)


class DailyReportService:
    def build_daily_report(
        self,
        *,
        report_date: date,
        starting_equity: float,
        ending_equity: float,
        equity_currency: str = "USDC",
        equity_source: EquitySource | None = None,
        total_signals: int,
        order_count: int,
        fill_count: int,
        rejected_order_count: int,
        open_positions: int,
        results: Iterable[Mapping[str, Any]],
        equity_curve: list[float] | None = None,
        stale_fill_count: int = 0,
        order_payloads: Iterable[dict[str, Any]] = (),
        fill_payloads: Iterable[dict[str, Any]] = (),
        reject_payloads: Iterable[dict[str, Any]] | None = None,
        execution_assumptions: dict[str, Any] | None = None,
        telemetry_incomplete_reasons: Iterable[str] = (),
    ) -> DailyReport:
        result_list = list(results)
        incomplete_reasons = sorted(set(telemetry_incomplete_reasons))
        closed = [r for r in result_list if _is_closed_result(r)]
        wins = sum(1 for r in closed if trade_result_status(r) == TradeResultStatus.WIN)
        losses = sum(
            1 for r in closed if trade_result_status(r) == TradeResultStatus.LOSS
        )
        voids = sum(
            1 for r in closed if trade_result_status(r) == TradeResultStatus.VOID
        )
        denominator = len(closed)
        win_rate = wins / denominator if denominator else 0.0
        total_pnl = sum(trade_result_float(r, "pnl_usdc") for r in closed)
        avg_roi = (
            sum(trade_result_float(r, "roi") for r in closed) / len(closed)
            if closed
            else 0.0
        )
        profit = sum(
            trade_result_float(r, "pnl_usdc")
            for r in closed
            if trade_result_float(r, "pnl_usdc") > 0
        )
        loss = abs(
            sum(
                trade_result_float(r, "pnl_usdc")
                for r in closed
                if trade_result_float(r, "pnl_usdc") < 0
            )
        )
        profit_factor = profit / loss if loss else None
        curve = equity_curve or [starting_equity, ending_equity]
        max_drawdown = self._max_drawdown(curve)
        execution_aggregates = self._execution_aggregates(
            order_payloads,
            fill_payloads,
            execution_assumptions or {},
            reject_payloads=reject_payloads,
        )
        return DailyReport(
            report_date=report_date,
            starting_equity=starting_equity,
            ending_equity=ending_equity,
            equity_currency=equity_currency,
            equity_source=equity_source,
            net_pnl=ending_equity - starting_equity,
            return_rate=(ending_equity - starting_equity) / starting_equity
            if starting_equity
            else 0.0,
            total_signals=total_signals,
            order_count=order_count,
            fill_count=fill_count,
            rejected_order_count=rejected_order_count,
            stale_fill_count=stale_fill_count,
            order_attempts_by_intent=execution_aggregates["order_attempts_by_intent"],
            fills_by_intent=execution_aggregates["fills_by_intent"],
            partial_fills_by_intent=execution_aggregates["partial_fills_by_intent"],
            rejects_by_reason=execution_aggregates["rejects_by_reason"],
            rejects_by_original_reason=execution_aggregates[
                "rejects_by_original_reason"
            ],
            average_execution_staleness_ms=execution_aggregates[
                "average_execution_staleness_ms"
            ],
            average_executable_depth_usdc=execution_aggregates[
                "average_executable_depth_usdc"
            ],
            execution_assumptions=execution_aggregates["execution_assumptions"],
            telemetry_status=("incomplete" if incomplete_reasons else "complete"),
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

    def _execution_aggregates(
        self,
        order_payloads: Iterable[dict[str, Any]],
        fill_payloads: Iterable[dict[str, Any]],
        assumptions: dict[str, Any],
        *,
        reject_payloads: Iterable[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        orders = list(order_payloads)
        reject_orders = list(reject_payloads) if reject_payloads is not None else orders
        fills = list(fill_payloads)
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
                metrics.get("order_intent") or order.get("order_intent") or "default"
            )
            order_id = str(order.get("report_order_id") or "")
            if order_id:
                order_intents[order_id] = intent
            attempts[intent] += 1
            staleness = _optional_float(metrics.get("orderbook_staleness_ms"))
            if staleness is not None:
                staleness_values.append(staleness)
            depth = _optional_float(metrics.get("available_depth_usdc"))
            if depth is not None:
                depth_values.append(depth)
        for order in reject_orders:
            metrics_payload = order.get("metrics")
            metrics = metrics_payload if isinstance(metrics_payload, dict) else {}
            if is_rejected_order_payload(order, metrics):
                normalized = normalize_reject_reason(
                    metrics.get("normalized_reason") or order.get("reject_reason")
                )
                original = str(
                    metrics.get("original_reason")
                    or order.get("reject_reason")
                    or "UNKNOWN"
                )
                rejects[normalized] += 1
                original_rejects[original] += 1
        fills_by_intent: Counter[str] = Counter()
        partial_by_intent: Counter[str] = Counter()
        for fill in fills:
            order_id = str(fill.get("report_order_id") or "")
            intent = str(
                fill.get("order_intent") or order_intents.get(order_id, "default")
            )
            fills_by_intent[intent] += 1
            fill_ratio = _optional_float(fill.get("fill_ratio"))
            if fill_ratio is not None and fill_ratio < 0.999:
                partial_by_intent[intent] += 1
        return {
            "order_attempts_by_intent": dict(sorted(attempts.items())),
            "fills_by_intent": dict(sorted(fills_by_intent.items())),
            "partial_fills_by_intent": dict(sorted(partial_by_intent.items())),
            "rejects_by_reason": dict(sorted(rejects.items())),
            "rejects_by_original_reason": dict(sorted(original_rejects.items())),
            "average_execution_staleness_ms": _average(staleness_values),
            "average_executable_depth_usdc": _average(depth_values),
            "execution_assumptions": dict(sorted(assumptions.items())),
        }

    def _breakdown(
        self, results: list[Mapping[str, Any]], attr: str
    ) -> dict[str, dict[str, float | int]]:
        rows: dict[str, dict[str, float | int]] = defaultdict(
            lambda: {
                "closed_positions": 0,
                "win_count": 0,
                "loss_count": 0,
                "void_count": 0,
                "total_pnl_usdc": 0.0,
                "average_roi": 0.0,
            }
        )
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
