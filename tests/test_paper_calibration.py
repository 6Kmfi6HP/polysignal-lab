from __future__ import annotations

from datetime import date

from factories import BookFactoryConfig, MarketFactoryConfig, sample_book, sample_market
from polysignal_lab.config import PaperTradingConfig, PolymarketDataConfig
from polysignal_lab.domain.enums import MarketStatus, Side
from polysignal_lab.domain.market import Market
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.paper.report import PaperReportService
from polysignal_lab.paper.settlement import PaperSettlementEngine
from polysignal_lab.paper.simulator import PaperSimulator
from polysignal_lab.paper.wallet import PaperWallet


def _signal(market: Market, confidence: float) -> SignalCandidate:
    token = market.token_for(Side.UP)
    return SignalCandidate.build(
        strategy="ptb_diff",
        asset=market.asset,
        timeframe=market.timeframe,
        market_id=market.market_id,
        market_slug=market.market_slug,
        condition_id=market.condition_id,
        token_id=token.token_id,
        side=Side.UP,
        confidence=confidence,
        entry_reference_price=0.50,
        max_entry_price=0.70,
        seconds_to_close=120,
        data_freshness_ms=10,
        reason_codes=["TEST_SIGNAL"],
        metrics={"source": "test"},
    )


def _paper_result_from_real_flow(confidence: float, resolved_outcome: Side):
    market = sample_market(MarketFactoryConfig(asset="ETH", timeframe="5m"))
    signal = _signal(market, confidence)
    book = sample_book(signal.token_id, BookFactoryConfig(ask=0.50, bid=0.49, size=100.0))
    wallet = PaperWallet(starting_balance=1000.0)
    simulator = PaperSimulator(PaperTradingConfig(), PolymarketDataConfig(), wallet)

    simulated = simulator.process_signal(signal, book)
    assert simulated.position is not None

    resolved_market = market.model_copy(
        update={"status": MarketStatus.RESOLVED, "resolved_outcome": resolved_outcome}
    )
    return PaperSettlementEngine(wallet).settle(simulated.position, resolved_market)


def test_calibration_buckets_use_signal_confidence_from_paper_flow() -> None:
    high_result = _paper_result_from_real_flow(0.82, Side.UP)
    medium_result = _paper_result_from_real_flow(0.60, Side.DOWN)

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
