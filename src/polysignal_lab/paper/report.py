from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Iterable

from polysignal_lab.domain.enums import TradeResultStatus
from polysignal_lab.domain.paper_result import DailyReport, PaperTradeResult


class PaperReportService:
    def build_daily_report(
        self,
        *,
        report_date: date,
        starting_equity: float,
        ending_equity: float,
        total_signals: int,
        paper_orders: int,
        paper_fills: int,
        rejected_paper_orders: int,
        open_positions: int,
        results: Iterable[PaperTradeResult],
        equity_curve: list[float] | None = None,
    ) -> DailyReport:
        result_list = list(results)
        closed = [r for r in result_list if r.result in {TradeResultStatus.WIN, TradeResultStatus.LOSS, TradeResultStatus.VOID, TradeResultStatus.SPLIT}]
        wins = sum(1 for r in closed if r.result == TradeResultStatus.WIN)
        losses = sum(1 for r in closed if r.result == TradeResultStatus.LOSS)
        voids = sum(1 for r in closed if r.result == TradeResultStatus.VOID)
        denominator = wins + losses
        win_rate = wins / denominator if denominator else 0.0
        total_pnl = sum(r.pnl_usdc for r in result_list)
        avg_roi = sum(r.roi for r in result_list) / len(result_list) if result_list else 0.0
        profit = sum(r.pnl_usdc for r in result_list if r.pnl_usdc > 0)
        loss = abs(sum(r.pnl_usdc for r in result_list if r.pnl_usdc < 0))
        profit_factor = profit / loss if loss else None
        curve = equity_curve or [starting_equity, ending_equity]
        max_drawdown = self._max_drawdown(curve)
        return DailyReport(
            report_date=report_date,
            starting_equity=starting_equity,
            ending_equity=ending_equity,
            paper_pnl=ending_equity - starting_equity,
            paper_roi=(ending_equity - starting_equity) / starting_equity if starting_equity else 0.0,
            total_signals=total_signals,
            paper_orders=paper_orders,
            paper_fills=paper_fills,
            rejected_paper_orders=rejected_paper_orders,
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
            strategy_breakdown=self._breakdown(result_list, "strategy"),
            asset_breakdown=self._breakdown(result_list, "asset"),
            timeframe_breakdown=self._breakdown(result_list, "timeframe"),
        )

    def _breakdown(self, results: list[PaperTradeResult], attr: str) -> dict[str, dict[str, float | int]]:
        rows: dict[str, dict[str, float | int]] = defaultdict(lambda: {"closed_positions": 0, "win_count": 0, "loss_count": 0, "void_count": 0, "total_pnl_usdc": 0.0, "average_roi": 0.0})
        roi_sum: dict[str, float] = defaultdict(float)
        for r in results:
            key = str(getattr(r, attr))
            row = rows[key]
            row["closed_positions"] += 1
            row["win_count"] += 1 if r.result == TradeResultStatus.WIN else 0
            row["loss_count"] += 1 if r.result == TradeResultStatus.LOSS else 0
            row["void_count"] += 1 if r.result == TradeResultStatus.VOID else 0
            row["total_pnl_usdc"] += r.pnl_usdc
            roi_sum[key] += r.roi
        for key, row in rows.items():
            count = row["closed_positions"] or 1
            row["average_roi"] = roi_sum[key] / count
            wins = row["win_count"]
            losses = row["loss_count"]
            row["win_rate"] = wins / (wins + losses) if wins + losses else 0.0
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
