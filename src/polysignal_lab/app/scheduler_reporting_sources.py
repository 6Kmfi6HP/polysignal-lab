"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Callable, datetime, datetime.UTC, datetime.date, datetime.datetime, datetime.time, datetime.timedelta, datetime.timezone, typing, typing.Any, typing.cast, zoneinfo, zoneinfo.ZoneInfo, polysignal_lab.app.scheduler_reporting_types
Output: _collect_daily_report_inputs, _fill_payloads_with_order_intents, _paper_order_metrics
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Any, cast
from zoneinfo import ZoneInfo

from polysignal_lab.app.scheduler_reporting_types import DailyReportInputs, _ReportScheduler
from polysignal_lab.paper.report_rejections import is_rejected_paper_order_payload
from polysignal_lab.utils import parse_dt


def _utc_text_bound(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _paper_order_metrics(order: dict[str, Any]) -> dict[str, Any]:
    metrics_payload = order.get("metrics")
    return metrics_payload if isinstance(metrics_payload, dict) else {}


def _paper_terminal_at(order: dict[str, Any]) -> datetime | None:
    metrics = _paper_order_metrics(order)
    terminal_raw = metrics.get("paper_terminal_at") or metrics.get("paper_cancelled_at")
    if terminal_raw is not None and not isinstance(terminal_raw, (str, datetime)):
        terminal_raw = str(terminal_raw)
    try:
        terminal_at = parse_dt(cast(str | datetime | None, terminal_raw))
    except ValueError:
        return None
    if terminal_at is None:
        return None
    if terminal_at.tzinfo is None:
        terminal_at = terminal_at.replace(tzinfo=UTC)
    return terminal_at.astimezone(UTC)


def _paper_order_intent(order: dict[str, Any]) -> str:
    metrics = _paper_order_metrics(order)
    return str(
        metrics.get("paper_order_intent")
        or order.get("order_intent")
        or "default"
    )


def _fill_payloads_with_order_intents(
    scheduler: _ReportScheduler,
    fills: list[dict[str, Any]],
    orders: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    today_order_ids = {
        str(order.get("paper_order_id") or "")
        for order in orders
        if order.get("paper_order_id")
    }
    missing_order_ids = tuple(
        sorted(
            {
                str(fill.get("paper_order_id") or "")
                for fill in fills
                if fill.get("paper_order_id")
            }
            - today_order_ids
        )
    )
    if not missing_order_ids:
        return fills

    placeholders = ",".join("?" for _ in missing_order_ids)
    fill_orders = scheduler.persistence.query_json(
        "system_events",
        where=(
            f"WHERE event_type=? AND json_extract(payload_json, '$.paper_order_id') "
            f"IN ({placeholders})"
        ),
        params=("nautilus_order", *missing_order_ids),
        limit=len(missing_order_ids),
    )
    orders_by_id = {
        str(order.get("paper_order_id") or ""): order
        for order in fill_orders
        if order.get("paper_order_id")
    }
    if not orders_by_id:
        return fills

    enriched: list[dict[str, Any]] = []
    for fill in fills:
        order = orders_by_id.get(str(fill.get("paper_order_id") or ""))
        if order is None:
            enriched.append(fill)
            continue
        enriched_fill = dict(fill)
        enriched_fill.setdefault("order_intent", _paper_order_intent(order))
        enriched.append(enriched_fill)
    return enriched


def _nautilus_system_event_rows(
    scheduler: _ReportScheduler,
    event_type: str,
    *,
    day_start: datetime,
    day_end: datetime,
) -> list[dict[str, Any]]:
    rows = scheduler.persistence.query_json(
        "system_events",
        where="WHERE event_type=? AND created_at >= ? AND created_at < ?",
        params=(event_type, _utc_text_bound(day_start), _utc_text_bound(day_end)),
        limit=10000,
    )
    return [row for row in rows if isinstance(row, dict)]


def _nautilus_projection_rows(
    scheduler: _ReportScheduler,
    name: str,
) -> list[dict[str, Any]]:
    from polysignal_lab.nautilus_runtime.projections import (
        project_fill_event,
        project_order_event,
        project_position,
    )

    projectors: dict[str, tuple[str, Callable[[Any], dict[str, Any]]]] = {
        "read_orders": ("orders", project_order_event),
        "read_fills": ("fills", project_fill_event),
        "read_positions": ("positions", project_position),
    }
    cache_attr, projector = projectors.get(name, (None, None))
    if cache_attr is None or projector is None:
        return []

    nautilus_cache = getattr(scheduler, "nautilus_cache", None)
    if nautilus_cache is None:
        return []
    method = getattr(nautilus_cache, cache_attr, None)
    if not callable(method):
        return []
    rows = method()
    if not isinstance(rows, (list, tuple)):
        return []
    return [projector(row) for row in rows if row is not None]


def _nautilus_projection_rows_for_day(
    scheduler: _ReportScheduler,
    name: str,
    *,
    day_start: datetime,
    day_end: datetime,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _nautilus_projection_rows(scheduler, name):
        try:
            timestamp = parse_dt(cast(str | datetime | None, row.get("ts") or row.get("created_at")))
        except ValueError:
            continue
        if timestamp is None:
            continue
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        timestamp = timestamp.astimezone(UTC)
        if day_start <= timestamp < day_end:
            rows.append(row)
    return rows


def _collect_daily_report_inputs(
    scheduler: _ReportScheduler,
    *,
    today: date,
    report_tz: ZoneInfo | timezone,
) -> DailyReportInputs:
    today_iso = today.isoformat()
    day_start_local = datetime.combine(today, time.min, tzinfo=report_tz)
    day_end_local = datetime.combine(today + timedelta(days=1), time.min, tzinfo=report_tz)
    day_start = day_start_local.astimezone(UTC)
    day_end = day_end_local.astimezone(UTC)
    day_params = (_utc_text_bound(day_start), _utc_text_bound(day_end))
    day_created_where = "WHERE created_at >= ? AND created_at < ?"
    day_closed_where = "WHERE closed_at >= ? AND closed_at < ?"

    trade_results = cast(
        list[dict[str, Any]],
        scheduler.persistence.query_json(
            "paper_trade_results",
            where=day_closed_where,
            params=day_params,
        ),
    )
    today_fills_raw = _nautilus_system_event_rows(
        scheduler,
        "nautilus_fill",
        day_start=day_start,
        day_end=day_end,
    )
    if not today_fills_raw:
        today_fills_raw = _nautilus_projection_rows_for_day(
            scheduler,
            "read_fills",
            day_start=day_start,
            day_end=day_end,
        )
    today_orders_raw = _nautilus_system_event_rows(
        scheduler,
        "nautilus_order",
        day_start=day_start,
        day_end=day_end,
    )
    using_nautilus_order_rows = bool(today_orders_raw)
    if not today_orders_raw:
        today_orders_raw = _nautilus_projection_rows_for_day(
            scheduler,
            "read_orders",
            day_start=day_start,
            day_end=day_end,
        )
        using_nautilus_order_rows = bool(today_orders_raw)
    today_terminal_orders_raw: list[dict[str, Any]] = []
    if using_nautilus_order_rows:
        today_order_ids = {
            str(order.get("paper_order_id") or "")
            for order in today_orders_raw
            if order.get("paper_order_id")
        }
        terminal_candidates = _nautilus_system_event_rows(
            scheduler,
            "nautilus_order",
            day_start=day_start,
            day_end=day_end,
        )
        for order in terminal_candidates:
            if str(order.get("status") or "").upper() not in {"REJECTED", "CANCELLED"}:
                continue
            order_id = str(order.get("paper_order_id") or "")
            if order_id in today_order_ids:
                continue
            terminal_at = _paper_terminal_at(order)
            if terminal_at is None or not (day_start <= terminal_at < day_end):
                continue
            if not is_rejected_paper_order_payload(order, _paper_order_metrics(order)):
                continue
            today_terminal_orders_raw.append(order)
    today_reject_orders_raw = [*today_orders_raw, *today_terminal_orders_raw]
    today_signals_raw = scheduler.persistence.query_json(
        "signals",
        where=day_created_where,
        params=day_params,
        limit=10000,
    )
    return DailyReportInputs(
        today=today,
        today_iso=today_iso,
        today_signals_raw=today_signals_raw,
        today_orders_raw=today_orders_raw,
        today_fills_raw=today_fills_raw,
        today_reject_orders_raw=today_reject_orders_raw,
        trade_results=trade_results,
    )
