from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from polysignal_lab.app import scheduler_health
from polysignal_lab.app.scheduler_reporting_storage import (
    delete_daily_report_rows,
    delete_paper_result_rows,
)
from polysignal_lab.domain.enums import ExitMode, Side, TradeResultStatus
from polysignal_lab.domain.market import Market
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.paper_result import DailyReport, PaperTradeResult
from polysignal_lab.paper.report import (
    PaperReportService,
    is_rejected_paper_order_payload,
)
from polysignal_lab.utils import new_id, parse_dt, redact_text, utc_iso, utc_now

if TYPE_CHECKING:
    from polysignal_lab.app.scheduler import PolySignalScheduler


@dataclass(frozen=True, slots=True)
class SchedulerPersistenceError(RuntimeError):
    operation: str
    reason: str

    def __str__(self) -> str:
        return f"{self.operation} failed: {self.reason}"


async def check_settlements(scheduler: PolySignalScheduler) -> list[PaperTradeResult]:
    cache_reader = _nautilus_cache_reader(scheduler)
    if cache_reader is None:
        return []
    read_positions = getattr(cache_reader, "read_positions", None)
    if not callable(read_positions):
        return []
    raw_positions = read_positions()
    if not isinstance(raw_positions, list):
        return []

    settled: list[PaperTradeResult] = []
    for projection in raw_positions:
        if not isinstance(projection, dict):
            continue
        if bool(projection.get("is_closed")):
            continue
        market_id = str(projection.get("market_id") or "")
        token_id = str(projection.get("token_id") or projection.get("instrument_id") or "")
        if not market_id or not token_id:
            continue
        market = scheduler.ctx.markets.get(market_id)
        if market is None:
            rows = scheduler.persistence.query_json(
                "markets",
                where="WHERE market_id = ?",
                params=(market_id,),
            )
            if not rows:
                continue
            try:
                market = Market.model_validate(rows[0])
            except (TypeError, ValueError):
                continue
        decision = await scheduler.settlement_resolver.resolve_market(market)
        outcome_value: float | None
        if decision.status == "resolved":
            outcome_value = decision.outcome_value_for(token_id)
        elif decision.status == "cancelled":
            outcome_value = _projection_float(projection, "avg_entry_price")
        else:
            continue
        if outcome_value is None:
            continue
        result = _paper_trade_result_from_projection(
            projection,
            market=market,
            outcome_value=outcome_value,
            details=decision.details,
        )
        await _store_projection_result(scheduler, result)
        if decision.conflict:
            event = {
                "event_id": new_id("evt", "settlement_conflict", result.paper_trade_id),
                "event_type": "settlement_conflict",
                "severity": "WARNING",
                "created_at": utc_iso(),
                "market_id": decision.market_id,
                "condition_id": decision.condition_id,
                "paper_trade_id": result.paper_trade_id,
                "conflict_sources": list(decision.conflict_sources),
            }
            try:
                scheduler.persistence.insert_system_event(event)
                scheduler.persistence.append_log("system_events", event)
            except (OSError, sqlite3.Error, TypeError, ValueError):
                scheduler.logger.warning(
                    "Failed to audit settlement conflict for %s",
                    decision.market_id,
                )
        settled.append(result)
    return settled


def _paper_trade_result_from_projection(
    projection: dict[str, object],
    *,
    market: Market,
    outcome_value: float,
    details: dict[str, object],
) -> PaperTradeResult:
    quantity = _projection_float(projection, "quantity") or 0.0
    entry_price = _projection_float(projection, "avg_entry_price") or 0.0
    stake = quantity * entry_price
    settlement_value = quantity * float(outcome_value)
    pnl = settlement_value - stake
    token_id = str(projection.get("token_id") or projection.get("instrument_id") or "")
    side = _projection_side(projection, market, token_id)
    if outcome_value == 1.0:
        result_status = TradeResultStatus.WIN
    elif outcome_value == 0.0:
        result_status = TradeResultStatus.LOSS
    elif 0.0 < outcome_value < 1.0:
        result_status = TradeResultStatus.VOID
    else:
        result_status = TradeResultStatus.WIN if pnl > 0 else TradeResultStatus.LOSS
    ts_raw = projection.get("ts")
    opened_at = parse_dt(cast(str | datetime | None, ts_raw)) if ts_raw else None
    return PaperTradeResult(
        paper_trade_id=new_id("ptr"),
        signal_id=str(projection.get("signal_id") or ""),
        paper_position_id=str(
            projection.get("paper_position_id") or projection.get("position_id") or ""
        ),
        strategy=str(projection.get("strategy") or market.asset),
        asset=str(projection.get("asset") or market.asset),
        timeframe=str(projection.get("timeframe") or market.timeframe),
        market_id=market.market_id,
        market_slug=market.market_slug,
        side=side,
        entry_price=entry_price,
        shares=quantity,
        stake_usdc=stake,
        exit_mode=ExitMode.RESOLUTION,
        outcome_value=float(outcome_value),
        settlement_value=settlement_value,
        pnl_usdc=pnl,
        roi=pnl / stake if stake else 0.0,
        result=result_status,
        opened_at=opened_at or utc_now(),
        closed_at=utc_now(),
        details=details,
    )


def _projection_side(projection: dict[str, object], market: Market, token_id: str) -> Side:
    raw_side = projection.get("side")
    if raw_side is not None:
        try:
            return Side(str(raw_side).upper())
        except ValueError:
            pass
    for token in market.outcome_tokens:
        if token.token_id == token_id:
            return token.side
    return Side.UP


async def _store_projection_result(
    scheduler: PolySignalScheduler,
    result: PaperTradeResult,
) -> None:
    scheduler.persistence.insert_paper_trade_result(result)
    scheduler.persistence.append_log("paper_trade_results", result)
    await _publish_paper_result_best_effort(scheduler, result)


async def _store_paper_result(
    scheduler: PolySignalScheduler, result: PaperTradeResult, position: PaperPosition
) -> None:
    try:
        scheduler.persistence.insert_paper_trade_result(result)
        scheduler.persistence.upsert_paper_position(position)
        scheduler_health.note_storage_success(scheduler, "sqlite")
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        scheduler_health.note_storage_failure(scheduler, "sqlite", exc)
        delete_paper_result_rows(scheduler, result, None)
        raise SchedulerPersistenceError("paper result persistence", str(exc)) from exc

    try:
        scheduler.persistence.append_log("paper_trade_results", result)
        scheduler_health.note_storage_success(scheduler, "jsonl")
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        scheduler_health.note_storage_failure(scheduler, "jsonl", exc)
        raise SchedulerPersistenceError("paper result log persistence", str(exc)) from exc
    await _publish_paper_result_best_effort(scheduler, result)


async def _publish_paper_result_best_effort(
    scheduler: PolySignalScheduler, result: PaperTradeResult
) -> None:
    if not scheduler.settings.telegram.send_paper_results:
        return
    try:
        publish = await scheduler.publish_service.publish_paper_result(result)
        scheduler_health.note_publish_result(scheduler, publish.as_dict())
    except Exception as exc:
        scheduler.logger.warning(
            "Paper result publish failed after durable persistence for %s: %s",
            result.paper_trade_id,
            exc,
        )
        event = {
            "event_id": new_id("evt", "paper_result_publish_failed", result.paper_trade_id),
            "event_type": "paper_result_publish_failed",
            "severity": "WARNING",
            "created_at": utc_iso(),
            "paper_trade_id": result.paper_trade_id,
            "paper_position_id": result.paper_position_id,
            "signal_id": result.signal_id,
            "error_type": type(exc).__name__,
            "error": redact_text(str(exc)),
        }
        try:
            scheduler.persistence.insert_system_event(event)
            scheduler.persistence.append_log("system_events", event)
        except (OSError, sqlite3.Error, TypeError, ValueError):
            scheduler.logger.exception(
                "Failed to audit paper result publish failure for %s",
                result.paper_trade_id,
            )


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
    scheduler: PolySignalScheduler,
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
    scheduler: PolySignalScheduler,
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
    scheduler: PolySignalScheduler,
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

def _nautilus_cache_reader(scheduler: PolySignalScheduler) -> object | None:
    return getattr(scheduler, "nautilus_cache_reader", None)


def _projection_float(source: dict[str, object] | None, key: str) -> float | None:
    if not isinstance(source, dict):
        return None
    value = source.get(key)
    if not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _report_equity_inputs(scheduler: PolySignalScheduler) -> tuple[float, float, int]:
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


async def generate_daily_report(scheduler: PolySignalScheduler) -> DailyReport | None:
    try:
        report_tz = ZoneInfo(scheduler.settings.app.timezone)
    except ZoneInfoNotFoundError:
        report_tz = UTC
    today = datetime.now(report_tz).date()
    today_iso = today.isoformat()
    day_start_local = datetime.combine(today, time.min, tzinfo=report_tz)
    day_end_local = datetime.combine(today + timedelta(days=1), time.min, tzinfo=report_tz)
    day_start = day_start_local.astimezone(UTC)
    day_end = day_end_local.astimezone(UTC)
    day_params = (_utc_text_bound(day_start), _utc_text_bound(day_end))
    day_created_where = "WHERE created_at >= ? AND created_at < ?"
    day_closed_where = "WHERE closed_at >= ? AND closed_at < ?"

    existing = scheduler.persistence.query_json(
        "daily_reports", where="WHERE report_date = ?", params=(today_iso,)
    )
    if existing:
        scheduler.logger.info("Daily report already exists for %s, skipping", today_iso)
        return None

    today_results_raw = scheduler.persistence.query_json(
        "paper_trade_results",
        where=day_closed_where,
        params=day_params,
    )
    trade_results = [PaperTradeResult(**result) for result in today_results_raw]

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
    today_terminal_orders_raw = []
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
    today_fill_payloads = _fill_payloads_with_order_intents(
        scheduler, today_fills_raw, today_orders_raw
    )
    rejected_paper_orders = sum(
        1
        for order in today_reject_orders_raw
        if is_rejected_paper_order_payload(order, _paper_order_metrics(order))
    )
    stale_paper_fills = sum(
        1
        for order in today_orders_raw
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
            report_date=today,
            starting_equity=starting_equity,
            ending_equity=ending_equity,
            total_signals=len(today_signals_raw),
            paper_orders=len(today_orders_raw),
            paper_fills=len(today_fills_raw),
            rejected_paper_orders=rejected_paper_orders,
            open_positions=open_positions,
            results=trade_results,
            equity_curve=[starting_equity, ending_equity],
            stale_paper_fills=stale_paper_fills,
            paper_order_payloads=today_orders_raw,
            paper_fill_payloads=today_fill_payloads,
            paper_reject_payloads=today_reject_orders_raw,
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
        today_iso,
        len(trade_results),
        report.paper_pnl,
    )
    return report
