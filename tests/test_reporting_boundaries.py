"""
Input: __future__, __future__.annotations, datetime, datetime.date, datetime.datetime, factories, factories.sample_report_result, polysignal_lab.domain.enums, polysignal_lab.domain.enums.TradeResultStatus, polysignal_lab.domain.reporting_models
Output: test_daily_report_ignores_boolean_execution_depth, test_daily_report_handles_non_string_reject_reason, test_daily_report_preserves_native_reject_reason, test_daily_report_counts_cancelled_rejects_with_reasons, test_daily_report_ignores_boolean_trade_result_numbers, test_strategy_leaderboard_ignores_boolean_trade_result_numbers, test_report_numeric_accessors_ignore_booleans, test_confidence_bucket_ignores_boolean_confidence, test_confidence_bucket_ignores_non_numeric_confidence, test_report_numeric_accessors_ignore_non_finite_values
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""


from __future__ import annotations

from datetime import date
from datetime import datetime

from factories import sample_report_result

from polysignal_lab.domain.enums import TradeResultStatus
from polysignal_lab.domain.reporting_models import report_float, account_float
from polysignal_lab.domain.reporting_result import trade_result_float
from polysignal_lab.app.reporting_sources import _order_terminal_at
from polysignal_lab.reporting.aggregates import confidence_bucket, optional_float
from polysignal_lab.reporting.daily_report import DailyReportService
from polysignal_lab.reporting.strategy_stats import build_strategy_leaderboard_rows


def test_daily_report_ignores_boolean_execution_depth() -> None:
    report = DailyReportService().build_daily_report(
        report_date=date(2026, 6, 22),
        starting_equity=1000.0,
        ending_equity=1000.0,
        total_signals=2,
        order_count=2,
        fill_count=0,
        rejected_order_count=0,
        open_positions=0,
        results=[],
        order_payloads=[
            {
                "report_order_id": "bool-depth",
                "status": "FILLED",
                "metrics": {"available_depth_usdc": True},
            },
            {
                "report_order_id": "numeric-depth",
                "status": "FILLED",
                "metrics": {"available_depth_usdc": 7.0},
            },
        ],
    )

    assert report.average_executable_depth_usdc == 7.0


def test_daily_report_handles_non_string_reject_reason() -> None:
    report = DailyReportService().build_daily_report(
        report_date=date(2026, 6, 22),
        starting_equity=1000.0,
        ending_equity=1000.0,
        total_signals=1,
        order_count=1,
        fill_count=0,
        rejected_order_count=1,
        open_positions=0,
        results=[],
        order_payloads=[
            {
                "report_order_id": "bad-reason",
                "status": "REJECTED",
                "metrics": {
                    "normalized_reason": True,
                    "original_reason": True,
                },
            },
        ],
    )

    assert report.rejects_by_reason == {"ORDER_REJECTED": 1}
    assert report.rejects_by_original_reason == {"True": 1}


def test_daily_report_preserves_native_reject_reason() -> None:
    report = DailyReportService().build_daily_report(
        report_date=date(2026, 6, 22),
        starting_equity=1000.0,
        ending_equity=1000.0,
        total_signals=1,
        order_count=1,
        fill_count=0,
        rejected_order_count=1,
        open_positions=0,
        results=[],
        order_payloads=[
            {
                "report_order_id": "po-legacy-reject",
                "status": "REJECTED",
                "reject_reason": "ASK_ABOVE_MAX_ENTRY",
                "metrics": {},
            },
        ],
    )

    assert report.rejects_by_reason == {"ASK_ABOVE_MAX_ENTRY": 1}
    assert report.rejects_by_original_reason == {"ASK_ABOVE_MAX_ENTRY": 1}


def test_daily_report_counts_cancelled_rejects_with_reasons() -> None:
    report = DailyReportService().build_daily_report(
        report_date=date(2026, 6, 22),
        starting_equity=1000.0,
        ending_equity=1000.0,
        total_signals=1,
        order_count=1,
        fill_count=0,
        rejected_order_count=1,
        open_positions=0,
        results=[],
        order_payloads=[
            {
                "report_order_id": "po-cancelled-reject",
                "status": "CANCELLED",
                "order_intent": "passive_gtd",
                "reject_reason": "GTD_EXPIRED",
                "metrics": {
                    "order_intent": "passive_gtd",
                    "orderbook_staleness_ms": 18.0,
                    "available_depth_usdc": 12.0,
                },
            },
        ],
    )

    assert report.order_attempts_by_intent == {"passive_gtd": 1}
    assert report.rejects_by_reason == {"GTD_EXPIRED": 1}
    assert report.rejects_by_original_reason == {"GTD_EXPIRED": 1}


def test_daily_report_ignores_boolean_trade_result_numbers() -> None:
    result = sample_report_result(
        report_result_id="pt-bool-pnl",
        result=TradeResultStatus.WIN.value,
        pnl_usdc=True,
        roi=True,
    )

    report = DailyReportService().build_daily_report(
        report_date=date(2026, 6, 22),
        starting_equity=1000.0,
        ending_equity=1000.0,
        total_signals=1,
        order_count=1,
        fill_count=1,
        rejected_order_count=0,
        open_positions=0,
        results=[result],
    )

    assert report.total_pnl_usdc == 0.0
    assert report.average_roi == 0.0


def test_strategy_leaderboard_ignores_boolean_trade_result_numbers() -> None:
    result = sample_report_result(
        report_result_id="pt-bool-leaderboard",
        strategy="bool_strategy",
        result=TradeResultStatus.WIN.value,
        pnl_usdc=True,
        roi=True,
    )

    rows = build_strategy_leaderboard_rows([result])

    assert rows[0]["total_pnl_usdc"] == 0.0
    assert rows[0]["average_roi"] == 0.0


def test_report_numeric_accessors_ignore_booleans() -> None:
    row = {"cash_balance": True, "total_pnl_usdc": True}

    assert account_float(row, "cash_balance") == 0.0
    assert report_float(row, "total_pnl_usdc") == 0.0


def test_confidence_bucket_ignores_boolean_confidence() -> None:
    assert confidence_bucket(True) == "low"


def test_confidence_bucket_ignores_non_numeric_confidence() -> None:
    assert confidence_bucket("bad") == "low"


def test_report_numeric_accessors_ignore_non_finite_values() -> None:
    row = {"cash_balance": "NaN", "total_pnl_usdc": "Infinity"}

    assert account_float(row, "cash_balance") == 0.0
    assert report_float(row, "total_pnl_usdc") == 0.0


def test_report_numeric_helpers_ignore_huge_json_integers() -> None:
    huge = 10**4000
    row = {
        "cash_balance": huge,
        "total_pnl_usdc": huge,
        "pnl_usdc": huge,
    }

    assert account_float(row, "cash_balance") == 0.0
    assert report_float(row, "total_pnl_usdc") == 0.0
    assert trade_result_float(row, "pnl_usdc") == 0.0
    assert optional_float(huge) is None
    assert confidence_bucket(huge) == "low"


def test_daily_report_ignores_non_finite_trade_and_execution_numbers() -> None:
    result = sample_report_result(
        report_result_id="pt-nonfinite-pnl",
        result=TradeResultStatus.WIN.value,
        pnl_usdc="Infinity",
        roi="NaN",
    )

    report = DailyReportService().build_daily_report(
        report_date=date(2026, 6, 22),
        starting_equity=1000.0,
        ending_equity=1000.0,
        total_signals=2,
        order_count=2,
        fill_count=1,
        rejected_order_count=0,
        open_positions=0,
        results=[result],
        order_payloads=[
            {"report_order_id": "bad-depth", "status": "FILLED", "metrics": {"available_depth_usdc": "Infinity"}},
            {"report_order_id": "good-depth", "status": "FILLED", "metrics": {"available_depth_usdc": 8.0}},
        ],
    )

    assert report.total_pnl_usdc == 0.0
    assert report.average_roi == 0.0
    assert report.average_executable_depth_usdc == 8.0


def test_daily_report_ignores_huge_trade_and_execution_numbers() -> None:
    huge = 10**4000
    result = sample_report_result(
        report_result_id="pt-huge-pnl",
        result=TradeResultStatus.WIN.value,
        pnl_usdc=huge,
        roi=huge,
        details={"confidence": huge},
    )

    report = DailyReportService().build_daily_report(
        report_date=date(2026, 6, 22),
        starting_equity=1000.0,
        ending_equity=1000.0,
        total_signals=2,
        order_count=2,
        fill_count=1,
        rejected_order_count=0,
        open_positions=0,
        results=[result],
        order_payloads=[
            {
                "report_order_id": "huge-depth",
                "status": "FILLED",
                "metrics": {
                    "available_depth_usdc": huge,
                    "orderbook_staleness_ms": huge,
                },
            },
            {
                "report_order_id": "good-depth",
                "status": "FILLED",
                "metrics": {"available_depth_usdc": 8.0},
            },
        ],
    )

    assert report.total_pnl_usdc == 0.0
    assert report.average_roi == 0.0
    assert report.average_executable_depth_usdc == 8.0
    assert report.calibration_breakdown["ptb_diff|BTC|5m|low"]["sample_size"] == 1


def test_strategy_leaderboard_ignores_non_finite_trade_result_numbers() -> None:
    result = sample_report_result(
        report_result_id="pt-nonfinite-leaderboard",
        strategy="nonfinite_strategy",
        result=TradeResultStatus.WIN.value,
        pnl_usdc="Infinity",
        roi="NaN",
    )

    rows = build_strategy_leaderboard_rows([result])

    assert rows[0]["total_pnl_usdc"] == 0.0
    assert rows[0]["average_roi"] == 0.0


def test_order_terminal_at_ignores_malformed_timestamp() -> None:
    order = {"metrics": {"terminal_at": "not-a-date"}}

    assert _order_terminal_at(order) is None
    assert _order_terminal_at({"metrics": {"terminal_at": datetime(2026, 6, 22)}}) is not None
