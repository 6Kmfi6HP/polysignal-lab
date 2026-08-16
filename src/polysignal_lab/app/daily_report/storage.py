from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from polysignal_lab.domain import missing_values
from polysignal_lab.domain.reporting_result import DailyReport


def delete_report_result_rows(
    scheduler: Any,
    result: Mapping[str, Any],
    publish_payload: dict[str, str | None] | None,
) -> None:
    try:
        report_result_id = missing_values.identifier(
            result, {}, "report_result_id", source="delete_report_result_rows"
        )
    except missing_values.MissingIdentifierError:
        counter = missing_values.missing_value_counter()
        if counter is not None:
            counter.inc_metric(
                missing_values.COLLAPSE_COMPONENT, "collapsed_report_result_id"
            )
        return
    try:
        scheduler.persistence.delete_report_result_rows(
            report_result_id,
            publish_payload["publish_id"] if publish_payload is not None else None,
        )
    except sqlite3.Error:
        scheduler.logger.exception(
            "Failed to clean up partial report result persistence for %s",
            report_result_id,
        )


def delete_daily_report_rows(
    scheduler: Any,
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
