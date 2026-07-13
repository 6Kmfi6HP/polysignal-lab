"""
Input: __future__, __future__.annotations, datetime, datetime.UTC, datetime.date, datetime.datetime, datetime.time, datetime.timedelta, datetime.timezone, typing, typing.Any, typing.cast, zoneinfo, zoneinfo.ZoneInfo, polysignal_lab.app.scheduler_reporting_types
Output: _collect_daily_report_inputs, _fill_payloads_with_order_intents, _paper_order_metrics
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

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
        "paper_order_states",
        where=f"WHERE paper_order_id IN ({placeholders})",
        params=missing_order_ids,
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


def _nautilus_fill_rows_for_day(
    scheduler: _ReportScheduler,
    *,
    day_start: datetime,
    day_end: datetime,
) -> tuple[list[dict[str, Any]], bool]:
    from polysignal_lab.nautilus_runtime.projections import project_fill_event

    nautilus_cache = getattr(scheduler, "nautilus_cache", None)
    method = getattr(nautilus_cache, "fills", None)
    if not callable(method):
        return [], False
    raw_rows = method()
    if not isinstance(raw_rows, (list, tuple)):
        return [], False

    rows: list[dict[str, Any]] = []
    for raw_row in raw_rows:
        if raw_row is None:
            continue
        row = project_fill_event(raw_row)
        try:
            timestamp = parse_dt(
                cast(str | datetime | None, row.get("ts") or row.get("created_at"))
            )
        except ValueError:
            continue
        if timestamp is None:
            continue
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        if day_start <= timestamp.astimezone(UTC) < day_end:
            rows.append(row)
    return rows, True


def _timestamp_in_report_window(
    value: object,
    *,
    day_start: datetime,
    day_end: datetime,
) -> bool:
    if not isinstance(value, (str, datetime)):
        return False
    try:
        timestamp = parse_dt(value)
    except ValueError:
        return False
    if timestamp is None:
        return False
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return day_start <= timestamp.astimezone(UTC) < day_end


def _telemetry_incomplete_reasons(
    scheduler: _ReportScheduler,
    *,
    day_start: datetime,
    day_end: datetime,
    fill_source_reason: str | None,
) -> tuple[str, ...]:
    reasons = [fill_source_reason] if fill_source_reason else []

    health = getattr(scheduler, "health", None)
    components = getattr(health, "components", None)
    component = (
        components.get("observability_actor")
        if isinstance(components, dict)
        else None
    )
    metrics = getattr(component, "metrics", None)
    if not isinstance(metrics, dict):
        return tuple(reasons)

    backlog = int(metrics.get("telemetry_writer_backlog", 0) or 0)
    if backlog > 0:
        reasons.append(f"telemetry_writer_backlog:{backlog}")

    drops = int(metrics.get("telemetry_queue_drops", 0) or 0)
    if drops > 0 and _timestamp_in_report_window(
        metrics.get("telemetry_last_drop_at"),
        day_start=day_start,
        day_end=day_end,
    ):
        reasons.append(f"telemetry_queue_drops:{drops}")

    failures = int(metrics.get("telemetry_write_failures", 0) or 0)
    if failures > 0 and _timestamp_in_report_window(
        metrics.get("telemetry_last_failure_at"),
        day_start=day_start,
        day_end=day_end,
    ):
        reasons.append(f"telemetry_write_failures:{failures}")
    return tuple(reasons)


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
    today_fills_raw, native_fills_available = _nautilus_fill_rows_for_day(
        scheduler,
        day_start=day_start,
        day_end=day_end,
    )
    fill_source_reason: str | None = None
    if not today_fills_raw:
        fallback_fills = _nautilus_system_event_rows(
            scheduler,
            "nautilus_fill",
            day_start=day_start,
            day_end=day_end,
        )
        if fallback_fills:
            today_fills_raw = fallback_fills
            fill_source_reason = "paper_fills_best_effort_fallback"
        elif not native_fills_available:
            fill_source_reason = "paper_fill_projection_unavailable"

    today_orders_raw = scheduler.persistence.query_json(
        "paper_order_states",
        where=(
            "WHERE source_event_at >= ? AND source_event_at < ? "
            "AND COALESCE(json_extract(payload_json, '$._projection_invalid'), 0) != 1"
        ),
        params=day_params,
        limit=10_000,
    )
    today_reject_orders_raw = [
        order
        for order in today_orders_raw
        if is_rejected_paper_order_payload(order, _paper_order_metrics(order))
    ]
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
        telemetry_incomplete_reasons=_telemetry_incomplete_reasons(
            scheduler,
            day_start=day_start,
            day_end=day_end,
            fill_source_reason=fill_source_reason,
        ),
    )
