from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from polysignal_lab.domain.paper_result import DailyReport, PaperTradeResult

if TYPE_CHECKING:
    from polysignal_lab.app.scheduler import PolySignalScheduler


def delete_paper_result_rows(
    scheduler: PolySignalScheduler,
    result: PaperTradeResult,
    publish_payload: dict[str, str | None] | None,
) -> None:
    try:
        scheduler.persistence.delete_paper_result_rows(
            result.paper_trade_id,
            publish_payload["publish_id"] if publish_payload is not None else None,
        )
    except sqlite3.Error:
        scheduler.logger.exception(
            "Failed to clean up partial paper result persistence for %s",
            result.paper_trade_id,
        )


def delete_daily_report_rows(
    scheduler: PolySignalScheduler,
    report: DailyReport,
    publish_payload: dict[str, str | None] | None,
) -> None:
    try:
        scheduler.persistence.delete_daily_report_rows(
            report.report_id,
            publish_payload["publish_id"] if publish_payload is not None else None,
        )
    except sqlite3.Error:
        scheduler.logger.exception(
            "Failed to clean up partial daily report persistence for %s",
            report.report_id,
        )
