from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from collections.abc import Iterable, Mapping
from typing import Any

from polysignal_lab.domain.enums import TradeResultStatus
from polysignal_lab.domain.missing_values import (
    COLLAPSE_COMPONENT,
    MissingIdentifierError,
    identifier,
    missing_value_counter,
)
from polysignal_lab.domain.reporting_result import (
    DailyReport,
    EquitySource,
    trade_result_display,
    trade_result_number,
    trade_result_status,
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


class _CollapseRecorder:
    """Records a missing-value collapse at most once per (record, field).

    A single closed record is read by several aggregations (totals, per-attribute
    breakdowns, calibration); the collapse counter must reflect distinct missing
    values, not repeat reads, so it stays a trustworthy signal.
    """

    def __init__(self) -> None:
        self._seen: set[tuple[int, str]] = set()

    def count(self, row_id: int, field: str) -> None:
        if (row_id, field) in self._seen:
            return
        self._seen.add((row_id, field))
        counter = missing_value_counter()
        if counter is not None:
            counter.inc_metric(COLLAPSE_COMPONENT, f"collapsed_{field}")


@dataclass(slots=True)
class _ClosedRow:
    """A closed trade result with numeric fields resolved once up front."""

    record: Mapping[str, Any]
    pnl_usdc: float | None
    roi: float | None


def _resolve_closed_rows(
    closed: list[Mapping[str, Any]], recorder: _CollapseRecorder
) -> list[_ClosedRow]:
    """Read numeric fields once per record, recording collapses exactly once."""
    rows: list[_ClosedRow] = []
    for record in closed:
        pnl_usdc = trade_result_number(record, "pnl_usdc")
        roi = trade_result_number(record, "roi")
        row_id = id(record)
        if pnl_usdc is None:
            recorder.count(row_id, "pnl_usdc")
        if roi is None:
            recorder.count(row_id, "roi")
        rows.append(_ClosedRow(record=record, pnl_usdc=pnl_usdc, roi=roi))
    return rows


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
        recorder = _CollapseRecorder()
        closed_rows = _resolve_closed_rows(closed, recorder)
        wins = sum(1 for r in closed if trade_result_status(r) == TradeResultStatus.WIN)
        losses = sum(
            1 for r in closed if trade_result_status(r) == TradeResultStatus.LOSS
        )
        voids = sum(
            1 for r in closed if trade_result_status(r) == TradeResultStatus.VOID
        )
        denominator = len(closed)
        win_rate = wins / denominator if denominator else 0.0
        pnl_values = [row.pnl_usdc for row in closed_rows if row.pnl_usdc is not None]
        roi_values = [row.roi for row in closed_rows if row.roi is not None]
        total_pnl = sum(pnl_values)
        avg_roi = sum(roi_values) / len(roi_values) if roi_values else 0.0
        profit = sum(value for value in pnl_values if value > 0)
        loss = abs(sum(value for value in pnl_values if value < 0))
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
            strategy_breakdown=self._breakdown(closed_rows, "strategy"),
            asset_breakdown=self._breakdown(closed_rows, "asset"),
            timeframe_breakdown=self._breakdown(closed_rows, "timeframe"),
            calibration_breakdown=_calibration_breakdown(closed_rows),
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
            try:
                order_id = identifier(
                    order, {}, "report_order_id", source="_execution_aggregates"
                )
            except MissingIdentifierError:
                counter = missing_value_counter()
                if counter is not None:
                    counter.inc_metric(
                        COLLAPSE_COMPONENT, "collapsed_report_order_id"
                    )
                order_id = ""
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
            try:
                order_id = identifier(
                    fill, {}, "report_order_id", source="_execution_aggregates"
                )
            except MissingIdentifierError:
                counter = missing_value_counter()
                if counter is not None:
                    counter.inc_metric(
                        COLLAPSE_COMPONENT, "collapsed_report_order_id"
                    )
                order_id = ""
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
        self, closed_rows: list[_ClosedRow], attr: str
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
        roi_count: dict[str, int] = defaultdict(int)
        for row in closed_rows:
            record = row.record
            key = trade_result_display(record, attr)
            bucket = rows[key]
            bucket["closed_positions"] += 1
            status = trade_result_status(record)
            bucket["win_count"] += 1 if status == TradeResultStatus.WIN else 0
            bucket["loss_count"] += 1 if status == TradeResultStatus.LOSS else 0
            bucket["void_count"] += 1 if status == TradeResultStatus.VOID else 0
            if row.pnl_usdc is not None:
                bucket["total_pnl_usdc"] += row.pnl_usdc
            if row.roi is not None:
                roi_sum[key] += row.roi
                roi_count[key] += 1
        for key, bucket in rows.items():
            count = bucket["closed_positions"] or 1
            bucket["average_roi"] = (
                roi_sum[key] / roi_count[key] if roi_count[key] else 0.0
            )
            wins = bucket["win_count"]
            bucket["win_rate"] = wins / count if count else 0.0
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
