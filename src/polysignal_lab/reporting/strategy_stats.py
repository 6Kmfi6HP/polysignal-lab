from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any, assert_never

from polysignal_lab.domain.enums import TradeResultStatus
from polysignal_lab.domain.reporting_result import trade_result_float, trade_result_status, trade_result_text
from polysignal_lab.reporting.daily_report import _is_closed_result


def build_strategy_leaderboard_rows(
    results: Iterable[Mapping[str, Any]],
) -> list[dict[str, float | int | str]]:
    closed = [r for r in results if _is_closed_result(r)]
    rows: dict[str, dict[str, float | int | str]] = {}
    roi_sum: dict[str, float] = defaultdict(float)
    for result in closed:
        strategy = trade_result_text(result, "strategy")
        entry = rows.setdefault(
            strategy,
            {
                "strategy": strategy,
                "closed_positions": 0,
                "win_count": 0,
                "loss_count": 0,
                "void_count": 0,
                "total_pnl_usdc": 0.0,
                "average_roi": 0.0,
                "win_rate": 0.0,
            },
        )
        entry["closed_positions"] = int(entry["closed_positions"]) + 1
        match trade_result_status(result):
            case TradeResultStatus.WIN:
                entry["win_count"] = int(entry["win_count"]) + 1
            case TradeResultStatus.LOSS:
                entry["loss_count"] = int(entry["loss_count"]) + 1
            case TradeResultStatus.VOID:
                entry["void_count"] = int(entry["void_count"]) + 1
            case TradeResultStatus.SPLIT:
                pass
            case TradeResultStatus.UNKNOWN:
                pass
            case unreachable:
                assert_never(unreachable)
        entry["total_pnl_usdc"] = float(entry["total_pnl_usdc"]) + trade_result_float(result, "pnl_usdc")
        roi_sum[strategy] += trade_result_float(result, "roi")
    for strategy, entry in rows.items():
        count = int(entry["closed_positions"])
        entry["average_roi"] = roi_sum[strategy] / count if count else 0.0
        wins = int(entry["win_count"])
        entry["win_rate"] = wins / count if count else 0.0
    return sorted(rows.values(), key=lambda row: float(row["total_pnl_usdc"]), reverse=True)
