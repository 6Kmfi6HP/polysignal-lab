from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest

from factories import sample_report_result

from polysignal_lab.domain.enums import TradeResultStatus
from polysignal_lab.domain.missing_values import bind_missing_value_counter
from polysignal_lab.observability.health import HealthRegistry, MetricValue
from polysignal_lab.reporting.daily_report import DailyReportService
from polysignal_lab.reporting.strategy_stats import build_strategy_leaderboard_rows


@pytest.fixture(autouse=True)
def _reset_missing_value_counter_after_test() -> Iterator[None]:
    bind_missing_value_counter(None)
    yield
    bind_missing_value_counter(None)


def _missing_pnl_result(signal_id: str = "miss") -> dict[str, object]:
    return sample_report_result(
        signal_id=signal_id,
        report_result_id=f"res-{signal_id}",
        report_position_id=f"pos-{signal_id}",
        market_id=f"market-{signal_id}",
        market_slug=f"market-{signal_id}",
        result=TradeResultStatus.WIN.value,
        pnl_usdc=None,
        roi=None,
    )


def _real_zero_pnl_result(signal_id: str = "zero") -> dict[str, object]:
    return sample_report_result(
        signal_id=signal_id,
        report_result_id=f"res-{signal_id}",
        report_position_id=f"pos-{signal_id}",
        market_id=f"market-{signal_id}",
        market_slug=f"market-{signal_id}",
        result=TradeResultStatus.VOID.value,
        pnl_usdc=0.0,
        roi=0.0,
    )


def _collapse_metrics(registry: HealthRegistry) -> dict[str, MetricValue]:
    components = {c.name: c for c in registry.snapshot().components}
    component = components.get("missing_values")
    return dict(component.metrics) if component is not None else {}


def test_daily_report_missing_pnl_counts_collapse_but_real_zero_does_not() -> None:
    registry = HealthRegistry()
    bind_missing_value_counter(registry)

    report = DailyReportService().build_daily_report(
        report_date=date(2026, 8, 12),
        starting_equity=1000.0,
        ending_equity=1000.0,
        total_signals=2,
        order_count=2,
        fill_count=2,
        rejected_order_count=0,
        open_positions=0,
        results=[_missing_pnl_result(), _real_zero_pnl_result()],
    )

    metrics = _collapse_metrics(registry)
    assert metrics.get("collapsed_pnl_usdc") == 1
    assert metrics.get("collapsed_roi") == 1
    # 真实零是合法值：不产生任何计数
    assert "missing_values" not in {
        c.name for c in HealthRegistry().snapshot().components
    }
    # 缺失盈亏不参与求和：两笔均不影响总额（缺失跳过，真实零为 0）
    assert report.total_pnl_usdc == 0.0
    assert report.closed_positions == 2


def test_daily_report_real_zero_pnl_never_counts_collapse() -> None:
    registry = HealthRegistry()
    bind_missing_value_counter(registry)

    DailyReportService().build_daily_report(
        report_date=date(2026, 8, 12),
        starting_equity=1000.0,
        ending_equity=1000.0,
        total_signals=1,
        order_count=1,
        fill_count=1,
        rejected_order_count=0,
        open_positions=0,
        results=[_real_zero_pnl_result()],
    )

    assert "missing_values" not in {c.name for c in registry.snapshot().components}


def test_daily_report_missing_pnl_excluded_from_sum_average_profit_factor() -> None:
    registry = HealthRegistry()
    bind_missing_value_counter(registry)

    win = sample_report_result(
        signal_id="win",
        result=TradeResultStatus.WIN.value,
        pnl_usdc=6.0,
        roi=0.60,
    )
    loss = sample_report_result(
        signal_id="loss",
        result=TradeResultStatus.LOSS.value,
        pnl_usdc=-10.0,
        roi=-1.0,
    )

    report = DailyReportService().build_daily_report(
        report_date=date(2026, 8, 12),
        starting_equity=1000.0,
        ending_equity=996.0,
        total_signals=3,
        order_count=3,
        fill_count=3,
        rejected_order_count=0,
        open_positions=0,
        results=[win, loss, _missing_pnl_result()],
    )

    # 缺失的那笔不进入求和、盈利、亏损；均值只在有值者上平均（分母=2）。
    assert report.total_pnl_usdc == -4.0
    assert report.profit_factor == 0.6
    assert report.average_roi == (0.60 - 1.0) / 2
    metrics = _collapse_metrics(registry)
    assert metrics.get("collapsed_pnl_usdc") == 1
    assert metrics.get("collapsed_roi") == 1


def test_daily_report_breakdown_excludes_missing_pnl_and_roi() -> None:
    registry = HealthRegistry()
    bind_missing_value_counter(registry)

    present = sample_report_result(
        signal_id="present",
        result=TradeResultStatus.WIN.value,
        pnl_usdc=4.0,
        roi=0.40,
    )
    missing = _missing_pnl_result(signal_id="missing")

    report = DailyReportService().build_daily_report(
        report_date=date(2026, 8, 12),
        starting_equity=1000.0,
        ending_equity=1004.0,
        total_signals=2,
        order_count=2,
        fill_count=2,
        rejected_order_count=0,
        open_positions=0,
        results=[present, missing],
    )

    row = report.strategy_breakdown["ptb_diff"]
    assert row["closed_positions"] == 2
    assert row["total_pnl_usdc"] == 4.0
    assert row["average_roi"] == 0.40  # 只在有值者上平均
    metrics = _collapse_metrics(registry)
    assert metrics.get("collapsed_pnl_usdc") == 1
    assert metrics.get("collapsed_roi") == 1


def test_calibration_breakdown_excludes_missing_entry_price_and_roi() -> None:
    registry = HealthRegistry()
    bind_missing_value_counter(registry)

    present = sample_report_result(
        signal_id="present",
        result=TradeResultStatus.WIN.value,
        entry_price=0.50,
        pnl_usdc=4.0,
        roi=0.40,
        details={"confidence": 0.80},
    )
    missing_entry = sample_report_result(
        signal_id="missing-entry",
        result=TradeResultStatus.WIN.value,
        entry_price=None,
        pnl_usdc=4.0,
        roi=None,
        details={"confidence": 0.80},
    )

    report = DailyReportService().build_daily_report(
        report_date=date(2026, 8, 12),
        starting_equity=1000.0,
        ending_equity=1008.0,
        total_signals=2,
        order_count=2,
        fill_count=2,
        rejected_order_count=0,
        open_positions=0,
        results=[present, missing_entry],
    )

    key = "ptb_diff|BTC|5m|high"
    row = report.calibration_breakdown[key]
    assert row["sample_size"] == 2
    # 缺失的 entry_price 与 roi 不参与均值分子；分母为有值者计数（=1）。
    assert row["average_entry_price"] == 0.50
    assert row["average_return"] == 0.40
    metrics = _collapse_metrics(registry)
    assert metrics.get("collapsed_entry_price") == 1
    assert metrics.get("collapsed_roi") == 1


def test_strategy_leaderboard_excludes_missing_pnl_and_roi() -> None:
    registry = HealthRegistry()
    bind_missing_value_counter(registry)

    present = sample_report_result(
        signal_id="present",
        result=TradeResultStatus.WIN.value,
        pnl_usdc=5.0,
        roi=0.5,
    )
    missing = _missing_pnl_result(signal_id="missing")

    rows = build_strategy_leaderboard_rows([present, missing])

    assert len(rows) == 1
    row = rows[0]
    assert row["closed_positions"] == 2
    assert row["total_pnl_usdc"] == 5.0
    assert row["average_roi"] == 0.5  # 只在有值者上平均
    metrics = _collapse_metrics(registry)
    assert metrics.get("collapsed_pnl_usdc") == 1
    assert metrics.get("collapsed_roi") == 1


def test_daily_report_unbound_counter_still_skips_missing_pnl() -> None:
    # 未绑定计数器（离线/单测场景）：缺失仍不参与求和，且不抛错。
    report = DailyReportService().build_daily_report(
        report_date=date(2026, 8, 12),
        starting_equity=1000.0,
        ending_equity=1000.0,
        total_signals=1,
        order_count=1,
        fill_count=1,
        rejected_order_count=0,
        open_positions=0,
        results=[_missing_pnl_result()],
    )

    assert report.total_pnl_usdc == 0.0
    assert report.average_roi == 0.0
    assert report.profit_factor is None
