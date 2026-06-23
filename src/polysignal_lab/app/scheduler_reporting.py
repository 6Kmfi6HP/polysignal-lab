from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, assert_never

from polysignal_lab.app.scheduler_reporting_storage import (
    delete_daily_report_rows,
    delete_paper_result_rows,
)
from polysignal_lab.domain.enums import MarketStatus, PositionStatus, TradeResultStatus
from polysignal_lab.domain.market import Market
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.paper_result import DailyReport, PaperTradeResult
from polysignal_lab.paper.report import PaperReportService

if TYPE_CHECKING:
    from polysignal_lab.app.scheduler import PolySignalScheduler


@dataclass(frozen=True, slots=True)
class SchedulerPersistenceError(RuntimeError):
    operation: str
    reason: str

    def __str__(self) -> str:
        return f"{self.operation} failed: {self.reason}"


async def check_settlements(scheduler: PolySignalScheduler) -> list[PaperTradeResult]:
    settled: list[PaperTradeResult] = []
    if not scheduler.wallet.open_positions:
        return settled

    for position in list(scheduler.wallet.open_positions.values()):
        cash_balance = scheduler.wallet.cash_balance
        realized_pnl = scheduler.wallet.realized_pnl
        position_status = position.status
        position_closed_at = position.closed_at
        was_open = position.paper_position_id in scheduler.wallet.open_positions
        market = scheduler.ctx.markets.get(position.market_id)
        if market is None:
            try:
                market_data = scheduler.sqlite.query_json(
                    "markets",
                    where="WHERE market_id = ?",
                    params=(position.market_id,),
                )
                if market_data:
                    market = Market.model_validate(market_data[0])
            except (IndexError, sqlite3.Error, TypeError, ValueError):
                pass
        if market is None:
            continue
        match market.status:
            case MarketStatus.CANCELLED:
                try:
                    result = scheduler.settlement.settle(position, market)
                except (KeyError, OSError, sqlite3.Error, TypeError, ValueError) as exc:
                    scheduler.logger.error(
                        "Failed to settle position %s: %s",
                        position.paper_position_id,
                        exc,
                    )
                    continue
            case MarketStatus.RESOLVED:
                try:
                    result = scheduler.settlement.settle(position, market)
                except (KeyError, OSError, sqlite3.Error, TypeError, ValueError) as exc:
                    scheduler.logger.error(
                        "Failed to settle position %s: %s",
                        position.paper_position_id,
                        exc,
                    )
                    continue
                match result.result:
                    case TradeResultStatus.UNKNOWN:
                        scheduler.logger.warning(
                            "Market %s (%s) is RESOLVED but has no resolved_outcome",
                            market.market_slug,
                            market.market_id,
                        )
                        continue
                    case TradeResultStatus.WIN | TradeResultStatus.LOSS | TradeResultStatus.VOID:
                        pass
                    case unreachable:
                        assert_never(unreachable)
            case MarketStatus.ACTIVE | MarketStatus.CLOSED | MarketStatus.UNKNOWN:
                book = scheduler.ctx.books.get(position.token_id)
                if book is None:
                    continue
                try:
                    result = scheduler.exits.evaluate(position, book)
                except (KeyError, OSError, sqlite3.Error, TypeError, ValueError) as exc:
                    scheduler.logger.error(
                        "Failed to evaluate paper exit for position %s: %s",
                        position.paper_position_id,
                        exc,
                    )
                    continue
                if result is None:
                    continue
            case unreachable:
                assert_never(unreachable)

        try:
            await _store_paper_result(scheduler, result, position)
        except SchedulerPersistenceError as exc:
            scheduler.wallet.cash_balance = cash_balance
            scheduler.wallet.realized_pnl = realized_pnl
            position.status = position_status
            position.closed_at = position_closed_at
            if was_open:
                scheduler.wallet.open_positions[position.paper_position_id] = position
            else:
                scheduler.wallet.open_positions.pop(position.paper_position_id, None)
            scheduler.logger.error(
                "Failed to persist paper result for %s: %s",
                position.paper_position_id,
                exc,
            )
            continue

        settled.append(result)
        scheduler.logger.info(
            "Closed paper position %s for market %s via %s: %s (pnl=%.2f)",
            position.paper_position_id,
            market.market_slug,
            result.exit_mode.value,
            result.result.value,
            result.pnl_usdc,
        )

    return settled


async def _store_paper_result(
    scheduler: PolySignalScheduler, result: PaperTradeResult, position: PaperPosition
) -> None:
    publish_payload: dict[str, str | None] | None = None
    try:
        if scheduler.settings.telegram.send_paper_results:
            message = scheduler.formatter.result_message(result)
            publish = await scheduler.publisher.send(
                message, "paper_result", result.signal_id
            )
            publish_payload = publish.as_dict()
            scheduler.sqlite.insert_telegram_publish(publish_payload)
        scheduler.sqlite.insert_paper_trade_result(result)
        scheduler.sqlite.upsert_paper_position(position)
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        delete_paper_result_rows(scheduler, result, publish_payload)
        raise SchedulerPersistenceError("paper result persistence", str(exc)) from exc

    scheduler.logs.append("paper_trade_results", result)
    if publish_payload is not None:
        scheduler.logs.append("telegram_publishes", publish_payload)


async def generate_daily_report(scheduler: PolySignalScheduler) -> DailyReport | None:
    today = date.today()
    today_iso = today.isoformat()

    existing = scheduler.sqlite.query_json(
        "daily_reports", where="WHERE report_date = ?", params=(today_iso,)
    )
    if existing:
        scheduler.logger.info("Daily report already exists for %s, skipping", today_iso)
        return None

    today_results_raw = scheduler.sqlite.query_json(
        "paper_trade_results",
        where="WHERE DATE(closed_at) = ?",
        params=(today_iso,),
    )
    trade_results = [PaperTradeResult(**result) for result in today_results_raw]

    today_fills_raw = scheduler.sqlite.query_json(
        "paper_fills",
        where="WHERE DATE(created_at) = ?",
        params=(today_iso,),
        limit=10000,
    )
    today_orders_raw = scheduler.sqlite.query_json(
        "paper_orders",
        where="WHERE DATE(created_at) = ?",
        params=(today_iso,),
        limit=10000,
    )
    today_signals_raw = scheduler.sqlite.query_json(
        "signals",
        where="WHERE DATE(created_at) = ?",
        params=(today_iso,),
        limit=10000,
    )
    rejected_paper_orders = sum(
        1 for order in today_orders_raw if order.get("status") == "REJECTED"
    )
    stale_paper_fills = sum(
        1
        for order in today_orders_raw
        if order.get("status") == "FILLED"
        and order.get("metrics", {}).get("orderbook_fresh") is False
    )

    try:
        report = PaperReportService().build_daily_report(
            report_date=today,
            starting_equity=scheduler.wallet.starting_balance,
            ending_equity=scheduler.wallet.equity,
            total_signals=len(today_signals_raw),
            paper_orders=len(today_orders_raw),
            paper_fills=len(today_fills_raw),
            rejected_paper_orders=rejected_paper_orders,
            open_positions=scheduler.wallet.open_position_count,
            results=trade_results,
            equity_curve=[scheduler.wallet.starting_balance, scheduler.wallet.equity],
            stale_paper_fills=stale_paper_fills,
        )
    except (KeyError, TypeError, ValueError) as exc:
        scheduler.logger.error("Failed to build daily report: %s", exc)
        return None

    publish_payload: dict[str, str | None] | None = None
    if scheduler.settings.telegram.send_daily_report:
        try:
            message = scheduler.formatter.daily_report_message(report)
            publish = await scheduler.publisher.send(message, "daily_report", None)
            publish_payload = publish.as_dict()
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            scheduler.logger.error("Failed to publish daily report: %s", exc)
            return None

    try:
        scheduler.sqlite.insert_daily_report(report)
        if publish_payload is not None:
            scheduler.sqlite.insert_telegram_publish(publish_payload)
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        delete_daily_report_rows(scheduler, report, publish_payload)
        scheduler.logger.error("Failed to store daily report: %s", exc)
        return None

    scheduler.logs.append("daily_reports", report)
    if publish_payload is not None:
        scheduler.logs.append("telegram_publishes", publish_payload)

    scheduler.logger.info(
        "Generated daily report for %s: %d closed trades, pnl=%.2f",
        today_iso,
        len(trade_results),
        report.paper_pnl,
    )
    return report
