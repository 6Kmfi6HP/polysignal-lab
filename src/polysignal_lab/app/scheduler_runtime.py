from __future__ import annotations

import asyncio
from asyncio import CancelledError, sleep
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from polysignal_lab.app import scheduler_health
from polysignal_lab.domain.market import Market
from polysignal_lab.domain.signal import SignalCandidate

if TYPE_CHECKING:
    from polysignal_lab.app.scheduler import PolySignalScheduler


async def _notify_startup(scheduler: PolySignalScheduler) -> None:
    """Send a startup notification via Telegram (respects dry_run)."""
    telegram = scheduler.settings.telegram
    if not telegram.enabled:
        return
    if not scheduler.strategies:
        scheduler.logger.info("Skipping startup notification: no strategies loaded")
        return
    strategy_names = ", ".join(
        s.name for s in scheduler.strategies if hasattr(s, "name")
    )
    msg = (
        f"<b>PolySignal Lab</b> started\n"
        f"Mode: {scheduler.settings.app.mode}\n"
        f"Strategies: {strategy_names}"
    )
    result = await scheduler.publisher.send(msg, "startup")
    if result.status == "DRY_RUN":
        scheduler.logger.info(
            "Startup notification: dry_run mode, would send: %s", msg
        )
    elif result.status == "SENT":
        scheduler.logger.info(
            "Startup notification sent to Telegram (msg_id=%s)",
            result.telegram_message_id,
        )
    else:
        scheduler.logger.warning(
            "Startup notification failed: %s", result.error or result.status
        )

async def _notify_shutdown(scheduler: PolySignalScheduler) -> None:
    """Send a shutdown notification via Telegram (respects dry_run)."""
    telegram = scheduler.settings.telegram
    if not telegram.enabled:
        return
    msg = "<b>PolySignal Lab</b> stopped"
    result = await scheduler.publisher.send(msg, "shutdown")
    if result.status == "DRY_RUN":
        scheduler.logger.info(
            "Shutdown notification: dry_run mode, would send: %s", msg
        )
    elif result.status == "SENT":
        scheduler.logger.info(
            "Shutdown notification sent to Telegram (msg_id=%s)",
            result.telegram_message_id,
        )
    else:
        scheduler.logger.warning(
            "Shutdown notification failed: %s", result.error or result.status
        )



async def stop(scheduler: PolySignalScheduler) -> None:
    scheduler.logger.info("Shutting down scheduler")
    scheduler._running = False

    scheduler._persist_state()
    scheduler_health.persist_health_snapshot(scheduler)

    # Fire shutdown notification with 3s timeout — don't block shutdown if Telegram is slow
    try:
        await asyncio.wait_for(_notify_shutdown(scheduler), timeout=3)
    except (asyncio.TimeoutError, Exception):
        pass

    try:
        await scheduler.supervisor.stop_all()
    except Exception:
        scheduler.logger.exception("Service supervisor shutdown failed")

    scheduler._ws_tasks.clear()
    scheduler._market_ws_task = None
    scheduler._binance_ws_task = None
    scheduler._market_ws_token_ids = ()
    scheduler._streams_started = False

    scheduler.logger.info("Scheduler shutdown complete")


async def run(scheduler: PolySignalScheduler) -> None:
    scheduler.logger.info("Starting PolySignal Lab scheduler run loop")
    scheduler._running = True

    scheduler._validate_telegram_startup()
    scheduler._initialize_trading_components()

    loop_count = 1
    last_report_date: date | None = None

    try:
        await scheduler.supervisor.start_all()
        await _notify_startup(scheduler)

        await scheduler.refresh_markets_once()
        await scheduler._fetch_resolved_markets()
        await scheduler.start_websockets()

        while scheduler._running:
            scheduler.logger.info("=== Run %d ===", loop_count)

            if loop_count % 5 == 0:
                try:
                    await scheduler.refresh_markets_once()
                    await scheduler._fetch_resolved_markets()
                except Exception as exc:
                    scheduler.logger.error("refresh_markets_once failed: %s", exc)

            active_markets = scheduler.ctx.markets.active()
            for market in active_markets:
                seconds_to_close = None
                if market.end_ts:
                    seconds_to_close = int(
                        (market.end_ts - datetime.now(timezone.utc)).total_seconds()
                    )
                scheduler.logger.info(
                    "MARKET %-40s asset=%-5s tf=%-3s secs=%-8s up_ask=%-5s down_ask=%-5s",
                    market.market_slug,
                    market.asset,
                    market.timeframe,
                    seconds_to_close if seconds_to_close else "N/A",
                    getattr(market, "up_ask", "?"),
                    getattr(market, "down_ask", "?"),
                )

            accepted = await _evaluate_iteration(scheduler, active_markets)
            await _process_iteration_signals(scheduler, accepted)
            await _check_iteration_settlements(scheduler)
            last_report_date = await _generate_iteration_report(
                scheduler, last_report_date
            )

            await asyncio.to_thread(scheduler._persist_state)
            await asyncio.to_thread(scheduler_health.persist_health_snapshot, scheduler)
            loop_count += 1
            await sleep(scheduler.settings.markets.refresh_interval_sec)
    except CancelledError:
        scheduler.logger.info("Scheduler cancelled, shutting down")
    finally:
        await scheduler.stop()


async def _evaluate_iteration(
    scheduler: PolySignalScheduler, active_markets: list[Market]
) -> list[SignalCandidate]:
    accepted: list[SignalCandidate] = []
    try:
        accepted = await scheduler.evaluate_once()
    except Exception as exc:
        scheduler.logger.error("evaluate_once failed: %s", exc)

    if not accepted:
        scheduler.logger.info(
            "SIGNAL_DIAG: %d active markets, %d strategies loaded, 0 signals passed all gates",
            len(active_markets),
            len(scheduler.strategies),
        )
        for strategy in scheduler.strategies:
            strategy_name = (
                strategy.name if hasattr(strategy, "name") else type(strategy).__name__
            )
            scheduler.logger.info(
                "SIGNAL_DIAG: strategy=%s window_checks=active", strategy_name
            )
    return accepted


async def _process_iteration_signals(
    scheduler: PolySignalScheduler, accepted: list[SignalCandidate]
) -> None:
    if not accepted:
        scheduler.logger.info("No accepted signals this iteration")
        return
    try:
        summary = await scheduler.process_accepted_signals(accepted)
        scheduler.logger.info(
            "Processed %d signals: %d stored, %d published, %d filled",
            summary["total"],
            summary["stored"],
            summary["published"],
            summary["filled"],
        )
    except Exception as exc:
        scheduler.logger.error("process_accepted_signals failed: %s", exc)


def _tick_resting_orders(_scheduler: PolySignalScheduler) -> None:
    return None


async def _check_iteration_settlements(scheduler: PolySignalScheduler) -> None:
    try:
        settled = await scheduler.check_settlements()
        if settled:
            scheduler.logger.info("Settled %d positions", len(settled))
    except Exception as exc:
        scheduler.logger.error("check_settlements failed: %s", exc)


def _configured_report_date(scheduler: PolySignalScheduler) -> date:
    try:
        report_tz = ZoneInfo(scheduler.settings.app.timezone)
    except ZoneInfoNotFoundError:
        report_tz = timezone.utc
    return datetime.now(report_tz).date()


async def _generate_iteration_report(
    scheduler: PolySignalScheduler, last_report_date: date | None
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
