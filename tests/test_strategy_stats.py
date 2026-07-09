"""
Input: __future__, __future__.annotations, datetime, datetime.datetime, datetime.timezone, typing, typing.assert_never, polysignal_lab.domain.enums, polysignal_lab.domain.enums.ExitMode, polysignal_lab.domain.enums.Side
Output: test_strategy_leaderboard_win_rate_counts_voids_as_closed, test_strategy_leaderboard_excludes_unknown_results, test_strategy_leaderboard_sorts_by_total_pnl_desc
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from factories import sample_paper_trade_result

from polysignal_lab.domain.enums import TradeResultStatus
from polysignal_lab.paper.strategy_stats import build_strategy_leaderboard_rows


def _trade(
    *,
    strategy: str = "ptb_diff",
    result: TradeResultStatus = TradeResultStatus.WIN,
    pnl_usdc: float = 1.0,
    roi: float = 0.1,
    signal_id: str = "sig-1",
) -> dict[str, Any]:
    return sample_paper_trade_result(
        signal_id=signal_id,
        paper_position_id=f"pos-{signal_id}",
        strategy=strategy,
        market_id=f"market-{signal_id}",
        market_slug=f"market-{signal_id}",
        outcome_value=1.0 if result == TradeResultStatus.WIN else 0.0,
        settlement_value=10.0 + pnl_usdc,
        pnl_usdc=pnl_usdc,
        roi=roi,
        result=result.value,
        opened_at=datetime(2026, 6, 21, tzinfo=timezone.utc).isoformat(),
        closed_at=datetime(2026, 6, 22, tzinfo=timezone.utc).isoformat(),
    )


def test_strategy_leaderboard_win_rate_counts_voids_as_closed() -> None:
    results = [
        _trade(signal_id="win", result=TradeResultStatus.WIN, pnl_usdc=2.4, roi=0.24),
        _trade(signal_id="void", result=TradeResultStatus.VOID, pnl_usdc=0.0, roi=0.0),
    ]

    rows = build_strategy_leaderboard_rows(results)

    assert len(rows) == 1
    row = rows[0]
    assert row["strategy"] == "ptb_diff"
    assert row["closed_positions"] == 2
    assert row["win_count"] == 1
    assert row["loss_count"] == 0
    assert row["void_count"] == 1
    assert row["win_rate"] == 0.5
    assert row["total_pnl_usdc"] == 2.4


def test_strategy_leaderboard_excludes_unknown_results() -> None:
    results = [
        _trade(signal_id="win", result=TradeResultStatus.WIN),
        _trade(signal_id="unknown", result=TradeResultStatus.UNKNOWN, pnl_usdc=-10.0, roi=-1.0),
    ]

    rows = build_strategy_leaderboard_rows(results)

    assert len(rows) == 1
    assert rows[0]["closed_positions"] == 1
    assert rows[0]["win_count"] == 1
    assert rows[0]["win_rate"] == 1.0


def test_strategy_leaderboard_sorts_by_total_pnl_desc() -> None:
    results = [
        _trade(strategy="alpha", signal_id="a1", pnl_usdc=5.0, roi=0.5),
        _trade(strategy="beta", signal_id="b1", pnl_usdc=10.0, roi=1.0),
        _trade(
            strategy="alpha",
            signal_id="a2",
            result=TradeResultStatus.LOSS,
            pnl_usdc=-2.0,
            roi=-0.2,
        ),
    ]

    rows = build_strategy_leaderboard_rows(results)

    assert [row["strategy"] for row in rows] == ["beta", "alpha"]
    assert rows[0]["total_pnl_usdc"] == 10.0
    assert rows[1]["total_pnl_usdc"] == 3.0
    assert rows[1]["win_count"] == 1
    assert rows[1]["loss_count"] == 1
