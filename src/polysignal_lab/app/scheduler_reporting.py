"""
Input: __future__, __future__.annotations, datetime, datetime.UTC, datetime.datetime, zoneinfo, zoneinfo.ZoneInfo, zoneinfo.ZoneInfoNotFoundError, polysignal_lab.app.scheduler_reporting_build, polysignal_lab.app.scheduler_reporting_equity, polysignal_lab.app.scheduler_reporting_sources, polysignal_lab.app.scheduler_reporting_types, polysignal_lab.domain.paper_result
Output: generate_daily_report, DailyReportInputs
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from polysignal_lab.app.scheduler_reporting_build import _build_daily_report_from_inputs
from polysignal_lab.app.scheduler_reporting_equity import _report_equity_inputs
from polysignal_lab.app.scheduler_reporting_sources import _collect_daily_report_inputs
from polysignal_lab.app.scheduler_reporting_types import DailyReportInputs, _ReportScheduler
from polysignal_lab.domain.paper_result import DailyReport


__all__ = [
    "DailyReportInputs",
    "generate_daily_report",
    "_report_equity_inputs",
]


async def generate_daily_report(scheduler: _ReportScheduler) -> DailyReport | None:
    try:
        report_tz = ZoneInfo(scheduler.settings.app.timezone)
    except ZoneInfoNotFoundError:
        report_tz = UTC
    today = datetime.now(report_tz).date()

    existing = scheduler.persistence.query_json(
        "daily_reports", where="WHERE report_date = ?", params=(today.isoformat(),)
    )
    if existing:
        scheduler.logger.info("Daily report already exists for %s, skipping", today.isoformat())
        return None

    inputs = _collect_daily_report_inputs(scheduler, today=today, report_tz=report_tz)
    return await _build_daily_report_from_inputs(scheduler, inputs)
