"""
Input: __future__, __future__.annotations, datetime, datetime.date, factories, factories.MarketFactoryConfig, factories.sample_market, polysignal_lab.app.scheduler_reporting, polysignal_lab.app.scheduler_reporting._paper_trade_result_from_projection, polysignal_lab.domain.enums
Output: test_projection_settlement_builds_result_from_nautilus_position_row, test_projection_settlement_rejects_zero_money_fields, test_unknown_projection_does_not_inflate_win_rate
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from datetime import date

from factories import MarketFactoryConfig, sample_market, sample_paper_trade_result
from polysignal_lab.app._settlement_check import _paper_trade_result_from_projection
from polysignal_lab.domain.enums import (
    MarketStatus,
    Side,
    TradeResultStatus,
)
from polysignal_lab.paper.report import PaperReportService


def _resolved_market(outcome: Side | None, status: MarketStatus = MarketStatus.RESOLVED):
    return sample_market(
        MarketFactoryConfig(asset="BTC", timeframe="5m", seconds_to_close=-1)
    ).model_copy(update={"status": status, "resolved_outcome": outcome})


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
            "stake_usdc": 10.0,
            "token_id": market.token_for(Side.UP).token_id,
            "ts": date(2026, 6, 21).isoformat(),
        },
        market=market,
        outcome_value=1.0,
        details={"source": "test"},
    )

    assert result is not None
    assert result["result"] == TradeResultStatus.WIN.value
    assert result["outcome_value"] == 1.0
    assert result["settlement_value"] == 25.0
    assert result["pnl_usdc"] == 15.0
    assert result["paper_position_id"] == "pos-1"


def test_projection_settlement_rejects_missing_opened_timestamp() -> None:
    market = _resolved_market(Side.UP)

    result = _paper_trade_result_from_projection(
        {
            "position_id": "pos-no-time",
            "signal_id": "sig-no-time",
            "strategy": "ptb_diff",
            "asset": "BTC",
            "timeframe": "5m",
            "quantity": 25.0,
            "avg_entry_price": 0.40,
            "token_id": market.token_for(Side.UP).token_id,
        },
        market=market,
        outcome_value=1.0,
        details={"source": "test"},
    )

    assert result is None


def test_projection_settlement_rejects_missing_money() -> None:
    market = _resolved_market(Side.UP)

    result = _paper_trade_result_from_projection(
        {
            "position_id": "pos-no-stake",
            "signal_id": "sig-no-stake",
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

    assert result is None


def test_projection_settlement_rejects_missing_numeric_money() -> None:
    market = _resolved_market(Side.UP)

    result = _paper_trade_result_from_projection(
        {
            "position_id": "pos-nan",
            "signal_id": "sig-nan",
            "strategy": "ptb_diff",
            "asset": "BTC",
            "timeframe": "5m",
            "quantity": float("nan"),
            "avg_entry_price": 0.40,
            "stake_usdc": 10.0,
            "token_id": market.token_for(Side.UP).token_id,
            "ts": date(2026, 6, 21).isoformat(),
        },
        market=market,
        outcome_value=1.0,
        details={"source": "test"},
    )

    assert result is None


def test_projection_settlement_rejects_zero_money_fields() -> None:
    market = _resolved_market(Side.UP)

    result = _paper_trade_result_from_projection(
        {
            "position_id": "pos-zero-money",
            "signal_id": "sig-zero-money",
            "strategy": "ptb_diff",
            "asset": "BTC",
            "timeframe": "5m",
            "quantity": 0.0,
            "avg_entry_price": 0.0,
            "stake_usdc": 0.0,
            "token_id": market.token_for(Side.UP).token_id,
            "ts": date(2026, 6, 21).isoformat(),
        },
        market=market,
        outcome_value=1.0,
        details={"source": "test"},
    )

    assert result is None


def test_unknown_projection_does_not_inflate_win_rate() -> None:
    unknown = sample_paper_trade_result(
        signal_id="sig-unknown",
        paper_position_id="pos-unknown",
        market_id="market-unknown",
        market_slug="market-unknown",
        outcome_value=0.0,
        settlement_value=0.0,
        pnl_usdc=0.0,
        roi=0.0,
        result=TradeResultStatus.UNKNOWN.value,
        opened_at=date(2026, 6, 21).isoformat(),
    )
    win = sample_paper_trade_result(
        signal_id="sig-win",
        paper_position_id="pos-win",
        market_id="market-win",
        market_slug="market-win",
        opened_at=date(2026, 6, 21).isoformat(),
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
