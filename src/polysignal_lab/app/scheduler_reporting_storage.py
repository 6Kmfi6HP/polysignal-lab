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
        with scheduler.sqlite._lock, scheduler.sqlite._conn:
            scheduler.sqlite._conn.execute(
                "DELETE FROM paper_trade_results WHERE paper_trade_id = ?",
                (result.paper_trade_id,),
            )
            if publish_payload is not None:
                scheduler.sqlite._conn.execute(
                    "DELETE FROM telegram_publishes WHERE publish_id = ?",
                    (publish_payload["publish_id"],),
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
        with scheduler.sqlite._lock, scheduler.sqlite._conn:
            scheduler.sqlite._conn.execute(
                "DELETE FROM daily_reports WHERE report_id = ?",
                (report.report_id,),
            )
            if publish_payload is not None:
                scheduler.sqlite._conn.execute(
                    "DELETE FROM telegram_publishes WHERE publish_id = ?",
                    (publish_payload["publish_id"],),
                )
    except sqlite3.Error:
        scheduler.logger.exception(
            "Failed to clean up partial daily report persistence for %s",
            report.report_id,
        )
