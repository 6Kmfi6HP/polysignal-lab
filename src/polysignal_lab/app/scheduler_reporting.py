"""
Input: __future__, __future__.annotations, sqlite3, dataclasses, dataclasses.dataclass, datetime, datetime.UTC, datetime.date, datetime.datetime, datetime.time
Output: generate_daily_report, DailyReportInputs
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from polysignal_lab.app import scheduler_health
from polysignal_lab.app._settlement_check import (
    _existing_result_for_position,
    _nautilus_positions,
    _paper_trade_result_from_projection,
    _projection_float,
    _projection_side,
    _publish_paper_result_best_effort,
    _store_projection_result,
)
from polysignal_lab.app.scheduler_reporting_storage import (
    delete_daily_report_rows,
)
from polysignal_lab.domain.paper_result import DailyReport, PaperTradeResult
from polysignal_lab.paper.report import (
    PaperReportService,
    is_rejected_paper_order_payload,
)
from polysignal_lab.utils import parse_dt



@dataclass(frozen=True, slots=True)
class DailyReportInputs:
    today: date
    today_iso: str
    today_signals_raw: list[dict[str, object]]
    today_orders_raw: list[dict[str, object]]
    today_fills_raw: list[dict[str, object]]
    today_reject_orders_raw: list[dict[str, object]]
    trade_results: list[PaperTradeResult]



def _utc_text_bound(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _paper_order_metrics(order: dict[str, object]) -> dict[str, object]:
    metrics_payload = order.get("metrics")
    return metrics_payload if isinstance(metrics_payload, dict) else {}


def _paper_terminal_at(order: dict[str, object]) -> datetime | None:
    metrics = _paper_order_metrics(order)
    terminal_raw = metrics.get("paper_terminal_at") or metrics.get("paper_cancelled_at")
    if terminal_raw is not None and not isinstance(terminal_raw, (str, datetime)):
        terminal_raw = str(terminal_raw)
    terminal_at = parse_dt(cast(str | datetime | None, terminal_raw))
    if terminal_at is None:
        return None
    if terminal_at.tzinfo is None:
        terminal_at = terminal_at.replace(tzinfo=UTC)
    return terminal_at.astimezone(UTC)


def _paper_order_intent(order: dict[str, object]) -> str:
    metrics = _paper_order_metrics(order)
    return str(
        metrics.get("paper_order_intent")
        or order.get("order_intent")
        or "default"
    )


def _fill_payloads_with_order_intents(
    scheduler: object,
    fills: list[dict[str, object]],
    orders: list[dict[str, object]],
) -> list[dict[str, object]]:
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

    enriched: list[dict[str, object]] = []
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
    scheduler: object,
    event_type: str,
    *,
    day_start: datetime,
    day_end: datetime,
) -> list[dict[str, object]]:
    rows = scheduler.persistence.query_json(
        "system_events",
        where="WHERE event_type=? AND created_at >= ? AND created_at < ?",
        params=(event_type, _utc_text_bound(day_start), _utc_text_bound(day_end)),
        limit=10000,
    )
    return [row for row in rows if isinstance(row, dict)]


def _nautilus_projection_rows(
    scheduler: object,
    name: str,
) -> list[dict[str, object]]:
    from polysignal_lab.nautilus_runtime.projections import (
        project_fill_event,
        project_order_event,
        project_position,
    )

    PROJECTORS: dict[str, tuple[str, object]] = {
        "read_orders": ("orders", project_order_event),
        "read_fills": ("fills", project_fill_event),
        "read_positions": ("positions", project_position),
    }
    cache_attr, projector = PROJECTORS.get(name, (None, None))
    if cache_attr is None:
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
    scheduler: object,
    name: str,
    *,
    day_start: datetime,
    day_end: datetime,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in _nautilus_projection_rows(scheduler, name):
        timestamp = parse_dt(cast(str | datetime | None, row.get("ts") or row.get("created_at")))
        if timestamp is None:
            continue
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        timestamp = timestamp.astimezone(UTC)
        if day_start <= timestamp < day_end:
            rows.append(row)
    return rows

def _report_equity_inputs(scheduler: object) -> tuple[float, float, int]:
    starting_equity = float(scheduler.settings.paper_trading.starting_balance_usdc)
    nautilus_cache = getattr(scheduler, "nautilus_cache", None)
    if nautilus_cache is None:
        return starting_equity, starting_equity, 0
    return _report_equity_inputs_from_nautilus_cache(
        nautilus_cache,
        nautilus_portfolio=getattr(scheduler, "nautilus_portfolio", None),
        starting_equity=starting_equity,
    )


def _report_equity_inputs_from_nautilus_cache(
    nautilus_cache: object,
    *,
    nautilus_portfolio: object | None = None,
    starting_equity: float,
) -> tuple[float, float, int]:
    from polysignal_lab.nautilus_runtime.projections import (
        project_account,
        project_portfolio_snapshot,
        project_position,
    )

    ending_equity = starting_equity
    open_positions = 0

    # Account
    account = None
    account_method = getattr(nautilus_cache, "account", None)
    if callable(account_method):
        account = account_method()
    account_projection = project_account(account) if account is not None else None

    # Portfolio snapshot
    portfolio = nautilus_portfolio or getattr(nautilus_cache, "portfolio", None)
    if callable(portfolio):
        portfolio = portfolio()
    portfolio_projection = (
        project_portfolio_snapshot(portfolio, account=account)
        if portfolio is not None
        else None
    )
    portfolio_equity = _projection_float(
        cast(dict[str, object] | None, portfolio_projection), "equity"
    )
    if portfolio_equity is not None:
        ending_equity = portfolio_equity
    elif isinstance(account_projection, dict):
        balances = account_projection.get("balances")
        if isinstance(balances, list):
            for balance in balances:
                if not isinstance(balance, dict):
                    continue
                if str(balance.get("currency", "")).upper() != "USDC":
                    continue
                total = _projection_float(balance, "total")
                if total is not None:
                    ending_equity = total
                    break

    # Positions
    positions_method = getattr(nautilus_cache, "positions", None)
    positions = positions_method() if callable(positions_method) else []
    if isinstance(positions, (list, tuple)):
        projected = [project_position(p) for p in positions if p is not None]
        open_positions = sum(
            1
            for p in projected
            if isinstance(p, dict) and not bool(p.get("is_closed"))
        )

    return starting_equity, ending_equity, open_positions


def _collect_daily_report_inputs(
    scheduler: object,
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

    trade_results = [
        PaperTradeResult(**result)
        for result in scheduler.persistence.query_json(
            "paper_trade_results",
            where=day_closed_where,
            params=day_params,
        )
    ]
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
    today_terminal_orders_raw: list[dict[str, object]] = []
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


async def _build_daily_report_from_inputs(
    scheduler: object,
    inputs: DailyReportInputs,
) -> DailyReport | None:
    today_fill_payloads = _fill_payloads_with_order_intents(
        scheduler, inputs.today_fills_raw, inputs.today_orders_raw
    )
    rejected_paper_orders = sum(
        1
        for order in inputs.today_reject_orders_raw
        if is_rejected_paper_order_payload(order, _paper_order_metrics(order))
    )
    stale_paper_fills = sum(
        1
        for order in inputs.today_orders_raw
        if order.get("status") == "FILLED"
        and _paper_order_metrics(order).get("orderbook_fresh") is False
    )
    paper_execution_assumptions = {
        "max_book_staleness_ms": scheduler.settings.data.polymarket.max_book_staleness_ms,
    }
    execution_metadata = getattr(scheduler, "paper_execution_metadata", None)
    if isinstance(execution_metadata, dict):
        paper_execution_assumptions.update(execution_metadata)

    starting_equity, ending_equity, open_positions = _report_equity_inputs(scheduler)
    try:
        report = PaperReportService().build_daily_report(
            report_date=inputs.today,
            starting_equity=starting_equity,
            ending_equity=ending_equity,
            total_signals=len(inputs.today_signals_raw),
            paper_orders=len(inputs.today_orders_raw),
            paper_fills=len(inputs.today_fills_raw),
            rejected_paper_orders=rejected_paper_orders,
            open_positions=open_positions,
            results=inputs.trade_results,
            equity_curve=[starting_equity, ending_equity],
            stale_paper_fills=stale_paper_fills,
            paper_order_payloads=inputs.today_orders_raw,
            paper_fill_payloads=today_fill_payloads,
            paper_reject_payloads=inputs.today_reject_orders_raw,
            paper_execution_assumptions=paper_execution_assumptions,
        )
    except (KeyError, TypeError, ValueError) as exc:
        scheduler.logger.error("Failed to build daily report: %s", exc)
        return None

    publish_payload: dict[str, str | None] | None = None
    if scheduler.settings.telegram.send_daily_report:
        try:
            publish = await scheduler.publish_service.publish_daily_report(report)
            publish_payload = publish.as_dict()
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            scheduler.logger.error("Failed to publish daily report: %s", exc)
            return None

    try:
        scheduler.persistence.insert_daily_report(report)
        scheduler_health.note_storage_success(scheduler, "sqlite")
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        scheduler_health.note_storage_failure(scheduler, "sqlite", exc)
        delete_daily_report_rows(scheduler, report, publish_payload)
        scheduler.logger.error("Failed to store daily report: %s", exc)
        return None

    try:
        scheduler.persistence.append_log("daily_reports", report)
        scheduler_health.note_storage_success(scheduler, "jsonl")
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        scheduler_health.note_storage_failure(scheduler, "jsonl", exc)
        scheduler.logger.error("Failed to store daily report log: %s", exc)
        return None

    scheduler.logger.info(
        "Generated daily report for %s: %d closed trades, pnl=%.2f",
        inputs.today_iso,
        len(inputs.trade_results),
        report.paper_pnl,
    )
    return report


async def generate_daily_report(scheduler: object) -> DailyReport | None:
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
