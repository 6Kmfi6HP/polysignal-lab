"""
Input: __future__, __future__.annotations, datetime, datetime.date, datetime.datetime, datetime.timezone, typing, typing.TYPE_CHECKING, zoneinfo, zoneinfo.ZoneInfo
Output: None
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError



def _configured_report_date(scheduler: object) -> date:
    try:
        report_tz = ZoneInfo(scheduler.settings.app.timezone)
    except ZoneInfoNotFoundError:
        report_tz = timezone.utc
    return datetime.now(report_tz).date()


async def _generate_iteration_report(
    scheduler: object, last_report_date: date | None
) -> date | None:
    report_date = _configured_report_date(scheduler)
    if last_report_date == report_date:
        return last_report_date
    try:
        report = await scheduler.generate_daily_report()
        if report:
            return report.report_date
    except Exception as exc:
        scheduler.logger.error("generate_daily_report failed: %s", exc)
    return last_report_date
