"""
Input: __future__, __future__.annotations, datetime, datetime.date, factories, factories.MarketFactoryConfig, factories.sample_market, polysignal_lab.app.reporting_projection, polysignal_lab.domain.enums
Output: test_calibration_buckets_use_signal_confidence_from_paper_flow
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from datetime import date

from factories import MarketFactoryConfig, sample_market

from polysignal_lab.app.reporting_projection import report_result_from_projection
from polysignal_lab.domain.enums import Side
from polysignal_lab.reporting.daily_report import DailyReportService


def _paper_result_from_confidence(confidence: float, resolved_outcome: Side):
    market = sample_market(MarketFactoryConfig(asset="ETH", timeframe="5m"))
    token = market.token_for(Side.UP)
    outcome_value = 1.0 if resolved_outcome is Side.UP else 0.0
    return report_result_from_projection(
        {
            "position_id": f"pos-{confidence}",
            "signal_id": f"sig-{confidence}",
            "strategy": "ptb_diff",
            "asset": market.asset,
            "timeframe": market.timeframe,
            "market_id": market.market_id,
            "market_slug": market.market_slug,
            "token_id": token.token_id,
            "side": Side.UP.value,
            "quantity": 20.0,
            "avg_entry_price": 0.50,
            "stake_usdc": 10.0,
            "signal_confidence": confidence,
            "ts": date(2026, 6, 24).isoformat(),
        },
        market=market,
        outcome_value=outcome_value,
        details={"confidence": confidence},
    )


def test_calibration_buckets_use_signal_confidence_from_paper_flow() -> None:
    high_result = _paper_result_from_confidence(0.82, Side.UP)
    medium_result = _paper_result_from_confidence(0.60, Side.DOWN)
    assert high_result is not None
    assert medium_result is not None

    report = DailyReportService().build_daily_report(
        report_date=date(2026, 6, 24),
        starting_equity=1000.0,
        ending_equity=1000.0,
        total_signals=2,
        order_count=2,
        fill_count=2,
        rejected_order_count=0,
        open_positions=0,
        results=[high_result, medium_result],
    )

    high_key = "ptb_diff|ETH|5m|high"
    medium_key = "ptb_diff|ETH|5m|medium"
    assert high_key in report.calibration_breakdown
    assert medium_key in report.calibration_breakdown
    assert report.calibration_breakdown[high_key]["sample_size"] == 1
    assert report.calibration_breakdown[high_key]["wins"] == 1
    assert report.calibration_breakdown[medium_key]["sample_size"] == 1
    assert report.calibration_breakdown[medium_key]["losses"] == 1
