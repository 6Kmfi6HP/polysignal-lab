"""
Input: __future__, __future__.annotations, sqlite3, typing, typing.TYPE_CHECKING, polysignal_lab.domain.paper_result, polysignal_lab.domain.paper_result.DailyReport, polysignal_lab.domain.paper_result.PaperTradeResult
Output: delete_paper_result_rows, delete_daily_report_rows
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

import sqlite3

from polysignal_lab.domain.paper_result import DailyReport, PaperTradeResult


def delete_paper_result_rows(
    scheduler: object,
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
    scheduler: object,
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
