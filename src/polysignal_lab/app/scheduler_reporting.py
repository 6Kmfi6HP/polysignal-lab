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
    _nautilus_cache_reader,
    _paper_trade_result_from_projection,
    _projection_float,
    _projection_side,
    _publish_paper_result_best_effort,
    _store_paper_result,
    _store_projection_result,
    check_settlements,
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
        "paper_orders",
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


def _nautilus_projection_rows(
    scheduler: object,
    name: str,
) -> list[dict[str, object]]:
    reader = getattr(scheduler, "nautilus_cache_reader", None)
    method = getattr(reader, name, None)
    if not callable(method):
        return []
    rows = method()
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


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
    cache_reader = _nautilus_cache_reader(scheduler)
    if cache_reader is None:
        return starting_equity, starting_equity, 0
    return _report_equity_inputs_from_nautilus_cache(
        cache_reader,
        starting_equity=starting_equity,
    )


def _report_equity_inputs_from_nautilus_cache(
    cache_reader: object,
    *,
    starting_equity: float,
) -> tuple[float, float, int]:
    ending_equity = starting_equity
    open_positions = 0

    read_account_projection = getattr(cache_reader, "read_account_projection", None)
    snapshot_portfolio_projection = getattr(cache_reader, "snapshot_portfolio_projection", None)
    read_positions = getattr(cache_reader, "read_positions", None)

    portfolio_projection = (
        snapshot_portfolio_projection()
        if callable(snapshot_portfolio_projection)
        else None
    )
    account_projection = (
        read_account_projection()
        if callable(read_account_projection)
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
    positions = read_positions() if callable(read_positions) else []
    if isinstance(positions, list):
        open_positions = sum(
            1
            for position in positions
            if isinstance(position, dict) and not bool(position.get("is_closed"))
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
    today_fills_raw = scheduler.persistence.query_json(
        "paper_fills",
        where=day_created_where,
        params=day_params,
        limit=10000,
    )
    if not today_fills_raw:
        today_fills_raw = _nautilus_projection_rows_for_day(
            scheduler,
            "read_fills",
            day_start=day_start,
            day_end=day_end,
        )
    today_orders_raw = scheduler.persistence.query_json(
        "paper_orders",
        where=day_created_where,
        params=day_params,
        limit=10000,
    )
    using_nautilus_order_rows = False
    if not today_orders_raw:
        today_orders_raw = _nautilus_projection_rows_for_day(
            scheduler,
            "read_orders",
            day_start=day_start,
            day_end=day_end,
        )
        using_nautilus_order_rows = bool(today_orders_raw)
    today_order_ids = {
        str(order.get("paper_order_id") or "")
        for order in today_orders_raw
        if order.get("paper_order_id")
    }
    today_terminal_orders_raw: list[dict[str, object]] = []
    if not using_nautilus_order_rows:
        terminal_order_candidates = scheduler.persistence.query_json(
            "paper_orders",
            where="WHERE status IN (?, ?)",
            params=("REJECTED", "CANCELLED"),
            limit=10000,
        )
        for order in terminal_order_candidates:
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
    fill_cfg = scheduler.settings.paper_trading.fill_model
    paper_execution_assumptions = {
        "max_book_staleness_ms": scheduler.settings.data.polymarket.max_book_staleness_ms,
        "min_fill_ratio": fill_cfg.min_fill_ratio,
        "reject_if_partial": fill_cfg.reject_if_partial,
        "require_depth_check": fill_cfg.require_depth_check,
        "slippage_bps": fill_cfg.slippage_bps,
    }
    execution_metadata = getattr(scheduler, "paper_execution_metadata", None)
    if isinstance(execution_metadata, dict):
        paper_execution_assumptions.update(
            {
                key: execution_metadata[key]
                for key in ("paper_engine", "accuracy_mode")
                if execution_metadata.get(key)
            }
        )

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
