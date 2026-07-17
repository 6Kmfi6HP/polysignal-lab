"""
Input: __future__, __future__.annotations, datetime, datetime.UTC, datetime.datetime, zoneinfo, zoneinfo.ZoneInfo, zoneinfo.ZoneInfoNotFoundError, polysignal_lab.app.reporting_build, polysignal_lab.app.reporting_build.(
Output: generate_daily_report
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from polysignal_lab.app.reporting_build import (
    _build_daily_report_from_inputs,
    _retry_pending_daily_report_publishes,
)
from polysignal_lab.app.reporting_equity import _report_equity_inputs
from polysignal_lab.app.reporting_sources import _collect_daily_report_inputs
from polysignal_lab.app.reporting_types import DailyReportInputs, _ReportScheduler
from polysignal_lab.domain.reporting_result import DailyReport


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

    if scheduler.settings.telegram.send_daily_report:
        await _retry_pending_daily_report_publishes(
            scheduler,
            before_date=today.isoformat(),
        )

    inputs = _collect_daily_report_inputs(scheduler, today=today, report_tz=report_tz)
    return await _build_daily_report_from_inputs(scheduler, inputs)
