from __future__ import annotations

import asyncio
import sqlite3
from typing import Any

from polysignal_lab.app import scheduler_health
from polysignal_lab.app.daily_report.equity import (
    _report_equity_inputs,
    _sandbox_base_currency,
)
from polysignal_lab.app.daily_report.sources import (
    _fill_payloads_with_order_intents,
    _order_metrics,
)
from polysignal_lab.app.daily_report.types import DailyReportInputs, _ReportScheduler
from polysignal_lab.domain.reporting_result import DailyReport, trade_result_float
from polysignal_lab.reporting.aggregates import is_closed_result
from polysignal_lab.reporting.daily_report import DailyReportService
from polysignal_lab.reporting.rejections import is_rejected_order_payload


async def _build_daily_report_from_inputs(
    scheduler: _ReportScheduler,
    inputs: DailyReportInputs,
) -> DailyReport | None:
    report = _build_report(scheduler, inputs)
    if report is None:
        return None

    send_daily_report = scheduler.settings.telegram.send_daily_report
    persisted = _claim_and_log_report(
        scheduler,
        report,
        enqueue_publish=send_daily_report,
    )
    if persisted is None:
        return None
    report, created = persisted

    if send_daily_report and not await _publish_report(scheduler, report):
        return report

    scheduler.logger.info(
        "%s daily report for %s: %d closed trades, pnl=%.2f",
        "Generated" if created else "Reused",
        inputs.today_iso,
        report.closed_positions,
        report.net_pnl,
    )
    return report


def _build_report(
    scheduler: _ReportScheduler,
    inputs: DailyReportInputs,
) -> DailyReport | None:
    today_fill_payloads = _fill_payloads_with_order_intents(
        scheduler, inputs.today_fills_raw, inputs.today_orders_raw
    )
    rejected_order_count = sum(
        1
        for order in inputs.today_reject_orders_raw
        if is_rejected_order_payload(order, _order_metrics(order))
    )
    stale_fill_count = sum(
        1
        for order in inputs.today_orders_raw
        if order.get("status") == "FILLED"
        and _order_metrics(order).get("orderbook_fresh") is False
    )
    execution_assumptions = {
        "max_book_staleness_ms": scheduler.settings.data.polymarket.max_book_staleness_ms,
    }
    execution_metadata = getattr(scheduler, "execution_metadata", None)
    if isinstance(execution_metadata, dict):
        execution_assumptions.update(execution_metadata)

    day_closed_pnl = _day_closed_pnl(inputs.trade_results)
    starting_equity, ending_equity, open_positions, equity_source = (
        _report_equity_inputs(scheduler, day_closed_pnl=day_closed_pnl)
    )
    telemetry_incomplete_reasons = inputs.telemetry_incomplete_reasons
    if equity_source == "report_results":
        telemetry_incomplete_reasons = (
            *telemetry_incomplete_reasons,
            "equity_derived_from_report_results",
        )
    try:
        return DailyReportService().build_daily_report(
            report_date=inputs.today,
            starting_equity=starting_equity,
            ending_equity=ending_equity,
            equity_currency=_sandbox_base_currency(scheduler.settings),
            equity_source=equity_source,
            total_signals=len(inputs.today_signals_raw),
            order_count=len(inputs.today_orders_raw),
            fill_count=len(inputs.today_fills_raw),
            rejected_order_count=rejected_order_count,
            open_positions=open_positions,
            results=inputs.trade_results,
            equity_curve=[starting_equity, ending_equity],
            stale_fill_count=stale_fill_count,
            order_payloads=inputs.today_orders_raw,
            fill_payloads=today_fill_payloads,
            reject_payloads=inputs.today_reject_orders_raw,
            execution_assumptions=execution_assumptions,
            telemetry_incomplete_reasons=telemetry_incomplete_reasons,
        )
    except (KeyError, TypeError, ValueError) as exc:
        scheduler.logger.error("Failed to build daily report: %s", exc)
        return None


def _day_closed_pnl(results: list[dict[str, Any]]) -> float | None:
    closed = [result for result in results if is_closed_result(result)]
    if not closed:
        return None
    return sum(trade_result_float(result, "pnl_usdc") for result in closed)


def _claim_and_log_report(
    scheduler: _ReportScheduler,
    report: DailyReport,
    *,
    enqueue_publish: bool,
) -> tuple[DailyReport, bool] | None:
    try:
        persisted, created = scheduler.persistence.claim_daily_report(
            report,
            enqueue_publish=enqueue_publish,
        )
        scheduler_health.note_storage_success(scheduler, "sqlite")
    except (OSError, sqlite3.Error, KeyError, TypeError, ValueError) as exc:
        scheduler_health.note_storage_failure(scheduler, "sqlite", exc)
        scheduler.logger.error("Failed to claim daily report: %s", exc)
        return None

    if not created:
        return persisted, False

    try:
        scheduler.persistence.append_log("daily_reports", persisted)
        scheduler_health.note_storage_success(scheduler, "jsonl")
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        scheduler_health.note_storage_failure(scheduler, "jsonl", exc)
        scheduler.logger.error("Failed to store daily report log: %s", exc)
        return None
    return persisted, True


async def _retry_pending_daily_report_publishes(
    scheduler: _ReportScheduler,
    *,
    before_date: str,
) -> None:
    try:
        reports = scheduler.persistence.pending_daily_report_publishes(
            before_date=before_date,
        )
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        scheduler_health.note_storage_failure(scheduler, "sqlite", exc)
        scheduler.logger.error("Failed to restore pending report publishes: %s", exc)
        return
    for report in reports:
        await _publish_report(scheduler, report)


async def _publish_report(
    scheduler: _ReportScheduler,
    report: DailyReport,
) -> bool:
    lease_sec = max(
        float(scheduler.settings.telegram.publish_timeout_sec) * 2.0,
        30.0,
    )
    try:
        intent = scheduler.persistence.claim_daily_report_publish(
            report.report_id,
            lease_sec=lease_sec,
        )
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        scheduler_health.note_storage_failure(scheduler, "sqlite", exc)
        scheduler.logger.error("Failed to claim daily report publish: %s", exc)
        return False

    if intent is None:
        return True

    intent_id = str(intent["intent_id"])
    attempt_count = int(intent["attempt_count"])
    idempotency_key = str(intent["idempotency_key"])
    try:
        while True:
            authorization = scheduler.persistence.authorize_daily_report_publish(
                intent_id,
                attempt_count,
                lease_sec=lease_sec,
            )
            if authorization == "AUTHORIZED":
                break
            if authorization == "STALE":
                scheduler.logger.info(
                    "Skipped superseded daily report publish for %s",
                    intent_id,
                )
                return True
            if authorization == "EXPIRED":
                intent = scheduler.persistence.claim_daily_report_publish(
                    report.report_id,
                    lease_sec=lease_sec,
                )
                if intent is None:
                    return True
                intent_id = str(intent["intent_id"])
                attempt_count = int(intent["attempt_count"])
                idempotency_key = str(intent["idempotency_key"])
                continue
            if authorization == "BUSY":
                await asyncio.sleep(0.1)
                continue
            raise ValueError(
                f"Unknown daily report publish authorization: {authorization}"
            )
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        scheduler_health.note_storage_failure(scheduler, "sqlite", exc)
        scheduler.logger.error("Failed to authorize daily report publish: %s", exc)
        return False

    try:
        publish = await scheduler.publish_service.deliver_daily_report(
            report,
            idempotency_key=idempotency_key,
        )
        publish_payload = publish.as_dict()
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        scheduler.logger.error("Failed to publish daily report: %s", exc)
        return False

    try:
        effective_publish = scheduler.persistence.complete_daily_report_publish(
            intent_id,
            attempt_count,
            publish_payload,
        )
        if effective_publish is None:
            scheduler.logger.error(
                "Ignored stale daily report publish completion for %s",
                intent_id,
            )
            return False
        scheduler_health.note_storage_success(scheduler, "sqlite")
    except (OSError, sqlite3.Error, KeyError, TypeError, ValueError) as exc:
        scheduler_health.note_storage_failure(scheduler, "sqlite", exc)
        scheduler.logger.error("Failed to complete daily report publish: %s", exc)
        return False

    scheduler_health.note_publish_result(scheduler, effective_publish)
    try:
        scheduler.persistence.append_log("telegram_publishes", effective_publish)
        scheduler_health.note_storage_success(scheduler, "jsonl")
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        scheduler_health.note_storage_failure(scheduler, "jsonl", exc)
        scheduler.logger.error("Failed to store publish log: %s", exc)
    return True
