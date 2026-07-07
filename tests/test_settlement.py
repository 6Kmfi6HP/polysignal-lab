"""
Input: __future__, __future__.annotations, datetime, datetime.date, factories, factories.MarketFactoryConfig, factories.sample_market, polysignal_lab.app.scheduler_reporting, polysignal_lab.app.scheduler_reporting._paper_trade_result_from_projection, polysignal_lab.domain.enums
Output: test_paper_settlement_engine_module_is_removed, test_projection_settlement_builds_result_from_nautilus_position_row, test_unknown_projection_does_not_inflate_win_rate
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

from datetime import date

from factories import MarketFactoryConfig, sample_market
from polysignal_lab.app.scheduler_reporting import _paper_trade_result_from_projection
from polysignal_lab.domain.enums import (
    ExitMode,
    MarketStatus,
    Side,
    TradeResultStatus,
)
from polysignal_lab.domain.paper_result import PaperTradeResult
from polysignal_lab.paper.report import PaperReportService


def _resolved_market(outcome: Side | None, status: MarketStatus = MarketStatus.RESOLVED):
    return sample_market(
        MarketFactoryConfig(asset="BTC", timeframe="5m", seconds_to_close=-1)
    ).model_copy(update={"status": status, "resolved_outcome": outcome})


def test_paper_settlement_engine_module_is_removed() -> None:
    from pathlib import Path

    assert not Path("src/polysignal_lab/paper/settlement.py").exists()


def test_projection_settlement_builds_result_from_nautilus_position_row() -> None:
    market = _resolved_market(Side.UP)

    result = _paper_trade_result_from_projection(
        {
            "position_id": "pos-1",
            "signal_id": "sig-up",
            "strategy": "ptb_diff",
            "asset": "BTC",
            "timeframe": "5m",
            "quantity": 25.0,
            "avg_entry_price": 0.40,
            "token_id": market.token_for(Side.UP).token_id,
            "ts": date(2026, 6, 21).isoformat(),
        },
        market=market,
        outcome_value=1.0,
        details={"source": "test"},
    )

    assert result.result == TradeResultStatus.WIN
    assert result.outcome_value == 1.0
    assert result.settlement_value == 25.0
    assert result.pnl_usdc == 15.0
    assert result.paper_position_id == "pos-1"


def test_unknown_projection_does_not_inflate_win_rate() -> None:
    unknown = PaperTradeResult(
        signal_id="sig-unknown",
        paper_position_id="pos-unknown",
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="market-unknown",
        market_slug="market-unknown",
        side=Side.UP,
        entry_price=0.50,
        shares=20.0,
        stake_usdc=10.0,
        exit_mode=ExitMode.RESOLUTION,
        outcome_value=0.0,
        settlement_value=0.0,
        pnl_usdc=0.0,
        roi=0.0,
        result=TradeResultStatus.UNKNOWN,
        opened_at=date(2026, 6, 21),
    )
    win = PaperTradeResult(
        signal_id="sig-win",
        paper_position_id="pos-win",
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="market-win",
        market_slug="market-win",
        side=Side.UP,
        entry_price=0.50,
        shares=20.0,
        stake_usdc=10.0,
        exit_mode=ExitMode.RESOLUTION,
        outcome_value=1.0,
        settlement_value=20.0,
        pnl_usdc=10.0,
        roi=1.0,
        result=TradeResultStatus.WIN,
        opened_at=date(2026, 6, 21),
    )

    report = PaperReportService().build_daily_report(
        report_date=date(2026, 6, 22),
        starting_equity=1000.0,
        ending_equity=1010.0,
        total_signals=2,
        paper_orders=2,
        paper_fills=2,
        rejected_paper_orders=0,
        open_positions=1,
        results=[unknown, win],
    )

    assert report.closed_positions == 1
    assert report.win_count == 1
    assert report.win_rate == 1.0
    assert report.total_pnl_usdc == 10.0
