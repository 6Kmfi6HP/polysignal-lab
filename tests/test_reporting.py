"""
Input: __future__, __future__.annotations, dataclasses, dataclasses.dataclass, datetime, datetime.date, typing, typing.assert_never, polysignal_lab.domain.enums, polysignal_lab.domain.enums.ExitMode
Output: test_daily_report_includes_strategy_win_rate_and_pnl, test_daily_report_includes_strategy_asset_timeframe_calibration, test_daily_report_aggregates_paper_execution_quality, test_daily_report_normalizes_legacy_raw_paper_reject_reason, test_daily_report_counts_cancelled_rejects_with_reasons, ResultSpec
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, assert_never

from factories import sample_paper_trade_result

from polysignal_lab.domain.enums import ExitMode, Side, TradeResultStatus
from polysignal_lab.paper.report import PaperReportService
from polysignal_lab.signal_layer.formatter import MessageFormatter


@dataclass(frozen=True, slots=True)
class ResultSpec:
    signal_id: str
    status: TradeResultStatus
    pnl_usdc: float
    roi: float
    strategy: str = "ptb_diff"
    asset: str = "BTC"
    timeframe: str = "5m"


def _outcome_value(status: TradeResultStatus) -> float:
    match status:
        case TradeResultStatus.WIN:
            return 1.0
        case TradeResultStatus.LOSS | TradeResultStatus.VOID | TradeResultStatus.UNKNOWN | TradeResultStatus.SPLIT:
            return 0.0
        case unreachable:
            assert_never(unreachable)


def _result(spec: ResultSpec) -> dict[str, Any]:
    return sample_paper_trade_result(
        signal_id=spec.signal_id,
        paper_position_id=f"pos-{spec.signal_id}",
        strategy=spec.strategy,
        asset=spec.asset,
        timeframe=spec.timeframe,
        market_id=f"market-{spec.signal_id}",
        market_slug=f"market-{spec.signal_id}",
        outcome_value=_outcome_value(spec.status),
        settlement_value=10.0 + spec.pnl_usdc,
        pnl_usdc=spec.pnl_usdc,
        roi=spec.roi,
        result=spec.status.value,
        opened_at=date(2026, 6, 21).isoformat(),
    )


def test_daily_report_includes_strategy_win_rate_and_pnl() -> None:
    # Given: stored paper results covering WIN, LOSS, VOID, and retriable UNKNOWN.
    results = [
        _result(ResultSpec("win", TradeResultStatus.WIN, 6.0, 0.60)),
        _result(
            ResultSpec(
                "loss", TradeResultStatus.LOSS, -10.0, -1.0, "vwap_momentum", "ETH", "15m"
            )
        ),
        _result(ResultSpec("void", TradeResultStatus.VOID, 0.0, 0.0)),
        _result(ResultSpec("unknown", TradeResultStatus.UNKNOWN, -10.0, -1.0)),
    ]

    # When: the daily report is built.
    report = PaperReportService().build_daily_report(
        report_date=date(2026, 6, 22),
        starting_equity=1000.0,
        ending_equity=996.0,
        total_signals=4,
        paper_orders=4,
        paper_fills=3,
        rejected_paper_orders=1,
        open_positions=1,
        results=results,
        stale_paper_fills=0,
        equity_currency="pUSD",
        equity_source="portfolio",
    )

    # Then: metrics use real closed states and exclude UNKNOWN from closed PnL.
    assert report.total_signals == 4
    assert report.paper_orders == 4
    assert report.paper_fills == 3
    assert report.rejected_paper_orders == 1
    assert report.open_positions == 1
    assert report.closed_positions == 3
    assert report.win_count == 1
    assert report.loss_count == 1
    assert report.void_count == 1
    assert report.win_rate == 1 / 3
    assert report.total_pnl_usdc == -4.0
    assert report.average_roi == (0.60 - 1.0 + 0.0) / 3
    assert report.profit_factor == 0.6
    assert report.stale_paper_fills == 0
    assert report.strategy_breakdown["ptb_diff"]["closed_positions"] == 2
    assert report.strategy_breakdown["ptb_diff"]["win_rate"] == 0.5
    assert report.asset_breakdown["BTC"]["total_pnl_usdc"] == 6.0
    assert report.timeframe_breakdown["15m"]["loss_count"] == 1

    message = MessageFormatter().daily_report_message(report.model_dump(mode="json"))
    assert "SPLIT" not in message
    assert message.startswith("<b>📊 Daily Paper Report</b>")
    assert "Equity  1000.00 → 996.00 pUSD" in message
    assert "Source  portfolio" in message
    assert "PnL     -4.00 pUSD" in message
    assert "+6.00 USDC" in message
    assert "<b>Strategies</b>" in message

    legacy_payload = report.model_dump(mode="json")
    legacy_payload.pop("equity_currency")
    legacy_payload.pop("equity_source")
    legacy_message = MessageFormatter().daily_report_message(legacy_payload)
    assert "Equity  1000.00 → 996.00 USDC" in legacy_message
    assert "Source  " not in legacy_message
    assert "PnL     -4.00 USDC" in legacy_message
    assert {
        TradeResultStatus.WIN.value,
        TradeResultStatus.LOSS.value,
        TradeResultStatus.VOID.value,
        TradeResultStatus.UNKNOWN.value,
    } == {"WIN", "LOSS", "VOID", "UNKNOWN"}


def test_daily_report_counts_split_as_closed_without_win_loss_void() -> None:
    result = _result(ResultSpec("split", TradeResultStatus.SPLIT, 2.0, 0.20))

    report = PaperReportService().build_daily_report(
        report_date=date(2026, 6, 22),
        starting_equity=1000.0,
        ending_equity=1002.0,
        total_signals=1,
        paper_orders=1,
        paper_fills=1,
        rejected_paper_orders=0,
        open_positions=0,
        results=[result],
    )

    assert report.closed_positions == 1
    assert report.win_count == 0
    assert report.loss_count == 0
    assert report.void_count == 0
    assert report.total_pnl_usdc == 2.0
    assert report.strategy_breakdown["ptb_diff"]["closed_positions"] == 1


def test_daily_report_includes_strategy_asset_timeframe_calibration() -> None:
    result = {
        **_result(ResultSpec("calibrated-win", TradeResultStatus.WIN, 4.0, 0.40)),
        "details": {"confidence": 0.80},
    }

    report = PaperReportService().build_daily_report(
        report_date=date(2026, 6, 22),
        starting_equity=1000.0,
        ending_equity=1004.0,
        total_signals=1,
        paper_orders=1,
        paper_fills=1,
        rejected_paper_orders=0,
        open_positions=0,
        results=[result],
    )

    row = report.calibration_breakdown["ptb_diff|BTC|5m|high"]
    assert row["strategy"] == "ptb_diff"
    assert row["asset"] == "BTC"
    assert row["timeframe"] == "5m"
    assert row["confidence_bucket"] == "high"
    assert row["sample_size"] == 1
    assert row["wins"] == 1
    assert row["losses"] == 0
    assert row["calibration_status"] == "insufficient_data"
    assert row["average_entry_price"] == 0.50
    assert row["average_return"] == 0.40


def test_daily_report_aggregates_paper_execution_quality() -> None:
    order_payloads = [
        {
            "paper_order_id": "po-fill",
            "status": "FILLED",
            "order_intent": "taker_fok",
            "metrics": {
                "paper_order_intent": "taker_fok",
                "paper_orderbook_staleness_ms": 42.0,
                "paper_available_depth_usdc": 50.0,
            },
        },
        {
            "paper_order_id": "po-partial",
            "status": "PARTIAL",
            "order_intent": "taker_fak",
            "metrics": {
                "paper_order_intent": "taker_fak",
                "paper_orderbook_staleness_ms": 64.0,
                "paper_available_depth_usdc": 4.0,
            },
        },
        {
            "paper_order_id": "po-reject",
            "status": "REJECTED",
            "order_intent": None,
            "reject_reason": "PAPER_ENTRY_PRICE_MOVED",
            "metrics": {
                "paper_order_intent": None,
                "paper_normalized_reason": "PAPER_ENTRY_PRICE_MOVED",
                "paper_original_reason": "ASK_ABOVE_MAX_ENTRY",
                "paper_orderbook_staleness_ms": 20.0,
                "paper_available_depth_usdc": 100.0,
            },
        },
    ]
    fill_payloads = [
        {"paper_order_id": "po-fill", "fill_ratio": 1.0},
        {"paper_order_id": "po-partial", "fill_ratio": 0.4},
    ]

    report = PaperReportService().build_daily_report(
        report_date=date(2026, 6, 22),
        starting_equity=1000.0,
        ending_equity=1000.0,
        total_signals=3,
        paper_orders=3,
        paper_fills=2,
        rejected_paper_orders=1,
        open_positions=1,
        results=[],
        paper_order_payloads=order_payloads,
        paper_fill_payloads=fill_payloads,
        paper_execution_assumptions={"slippage_bps": 25.0, "require_depth_check": True},
    )

    assert report.paper_attempts_by_intent == {
        "default": 1,
        "taker_fak": 1,
        "taker_fok": 1,
    }
    assert report.paper_fills_by_intent == {"taker_fak": 1, "taker_fok": 1}
    assert report.paper_partial_fills_by_intent == {"taker_fak": 1}
    assert report.paper_rejects_by_reason == {"PAPER_ENTRY_PRICE_MOVED": 1}
    assert report.paper_rejects_by_original_reason == {"ASK_ABOVE_MAX_ENTRY": 1}
    assert report.average_execution_staleness_ms == 42.0
    assert report.average_executable_depth_usdc == 154.0 / 3
    assert report.paper_execution_assumptions["slippage_bps"] == 25.0
