from __future__ import annotations

from datetime import date

from factories import MarketFactoryConfig, sample_market
from polysignal_lab.domain.enums import MarketStatus, Side
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.paper.report import PaperReportService
from polysignal_lab.paper.settlement import PaperSettlementEngine


def _paper_result_from_confidence(confidence: float, resolved_outcome: Side):
    market = sample_market(MarketFactoryConfig(asset="ETH", timeframe="5m"))
    token = market.token_for(Side.UP)
    position = PaperPosition(
        signal_id=f"sig-{confidence}",
        paper_order_id=f"order-{confidence}",
        paper_fill_id=f"fill-{confidence}",
        strategy="ptb_diff",
        asset=market.asset,
        timeframe=market.timeframe,
        market_id=market.market_id,
        market_slug=market.market_slug,
        token_id=token.token_id,
        side=Side.UP,
        entry_price=0.50,
        shares=20.0,
        stake_usdc=10.0,
        signal_confidence=confidence,
    )
    resolved_market = market.model_copy(
        update={"status": MarketStatus.RESOLVED, "resolved_outcome": resolved_outcome}
    )
    return PaperSettlementEngine().settle(position, resolved_market)


def test_calibration_buckets_use_signal_confidence_from_paper_flow() -> None:
    high_result = _paper_result_from_confidence(0.82, Side.UP)
    medium_result = _paper_result_from_confidence(0.60, Side.DOWN)

    report = PaperReportService().build_daily_report(
        report_date=date(2026, 6, 24),
        starting_equity=1000.0,
        ending_equity=1000.0,
        total_signals=2,
        paper_orders=2,
        paper_fills=2,
        rejected_paper_orders=0,
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
