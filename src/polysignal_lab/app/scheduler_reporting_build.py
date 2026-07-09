"""
Input: __future__, __future__.annotations, sqlite3, polysignal_lab.app.scheduler_reporting_equity, polysignal_lab.app.scheduler_reporting_sources, polysignal_lab.app.scheduler_reporting_storage, polysignal_lab.app.scheduler_reporting_types, polysignal_lab.app.scheduler_health, polysignal_lab.domain.paper_result, polysignal_lab.paper.report
Output: _build_daily_report_from_inputs
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

import sqlite3

from polysignal_lab.app import scheduler_health
from polysignal_lab.app.scheduler_reporting_equity import _report_equity_inputs
from polysignal_lab.app.scheduler_reporting_sources import (
    _fill_payloads_with_order_intents,
    _paper_order_metrics,
)
from polysignal_lab.app.scheduler_reporting_storage import delete_daily_report_rows
from polysignal_lab.app.scheduler_reporting_types import DailyReportInputs, _ReportScheduler
from polysignal_lab.domain.paper_result import DailyReport
from polysignal_lab.paper.report import PaperReportService
from polysignal_lab.paper.report_rejections import is_rejected_paper_order_payload


async def _build_daily_report_from_inputs(
    scheduler: _ReportScheduler,
    inputs: DailyReportInputs,
) -> DailyReport | None:
    today_fill_payloads = _fill_payloads_with_order_intents(
        scheduler, inputs.today_fills_raw, inputs.today_orders_raw
    )
    rejected_paper_orders = sum(
        1
        for order in inputs.today_reject_orders_raw
        if is_rejected_paper_order_payload(order, _paper_order_metrics(order))
    )
    stale_paper_fills = sum(
        1
        for order in inputs.today_orders_raw
        if order.get("status") == "FILLED"
        and _paper_order_metrics(order).get("orderbook_fresh") is False
    )
    paper_execution_assumptions = {
        "max_book_staleness_ms": scheduler.settings.data.polymarket.max_book_staleness_ms,
    }
    execution_metadata = getattr(scheduler, "paper_execution_metadata", None)
    if isinstance(execution_metadata, dict):
        paper_execution_assumptions.update(execution_metadata)

    starting_equity, ending_equity, open_positions = _report_equity_inputs(scheduler)
    try:
        report = PaperReportService().build_daily_report(
            report_date=inputs.today,
            starting_equity=starting_equity,
            ending_equity=ending_equity,
            total_signals=len(inputs.today_signals_raw),
            paper_orders=len(inputs.today_orders_raw),
            paper_fills=len(inputs.today_fills_raw),
            rejected_paper_orders=rejected_paper_orders,
            open_positions=open_positions,
            results=inputs.trade_results,
            equity_curve=[starting_equity, ending_equity],
            stale_paper_fills=stale_paper_fills,
            paper_order_payloads=inputs.today_orders_raw,
            paper_fill_payloads=today_fill_payloads,
            paper_reject_payloads=inputs.today_reject_orders_raw,
            paper_execution_assumptions=paper_execution_assumptions,
        )
    except (KeyError, TypeError, ValueError) as exc:
        scheduler.logger.error("Failed to build daily report: %s", exc)
        return None

    publish_payload: dict[str, str | None] | None = None
    if scheduler.settings.telegram.send_daily_report:
        try:
            publish = await scheduler.publish_service.publish_daily_report(report)
            publish_payload = publish.as_dict()
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            scheduler.logger.error("Failed to publish daily report: %s", exc)
            return None

    try:
        scheduler.persistence.insert_daily_report(report)
        scheduler_health.note_storage_success(scheduler, "sqlite")
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        scheduler_health.note_storage_failure(scheduler, "sqlite", exc)
        delete_daily_report_rows(scheduler, report, publish_payload)
        scheduler.logger.error("Failed to store daily report: %s", exc)
        return None

    try:
        scheduler.persistence.append_log("daily_reports", report)
        scheduler_health.note_storage_success(scheduler, "jsonl")
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        scheduler_health.note_storage_failure(scheduler, "jsonl", exc)
        scheduler.logger.error("Failed to store daily report log: %s", exc)
        return None

    scheduler.logger.info(
        "Generated daily report for %s: %d closed trades, pnl=%.2f",
        inputs.today_iso,
        len(inputs.trade_results),
        report.paper_pnl,
    )
    return report
