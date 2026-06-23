from __future__ import annotations

from asyncio import CancelledError, Task, create_task, sleep
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from polysignal_lab.domain.market import Market
from polysignal_lab.domain.signal import SignalCandidate

if TYPE_CHECKING:
    from polysignal_lab.app.scheduler import PolySignalScheduler


async def stop(scheduler: PolySignalScheduler) -> None:
    scheduler.logger.info("Shutting down scheduler")
    scheduler._running = False

    scheduler.poly_ws.stop()
    scheduler.binance_ws.stop()

    for task in scheduler._ws_tasks:
        if not task.done():
            task.cancel()
            try:
                await task
            except (CancelledError, Exception):
                pass
    scheduler._ws_tasks.clear()
    scheduler._market_ws_task = None
    scheduler._binance_ws_task = None
    scheduler._market_ws_token_ids = ()
    scheduler._streams_started = False

    scheduler._persist_state()

    try:
        scheduler.sqlite.close()
    except Exception:
        pass

    scheduler.logger.info("Scheduler shutdown complete")


async def run(scheduler: PolySignalScheduler) -> None:
    scheduler.logger.info("Starting PolySignal Lab scheduler run loop")
    scheduler._running = True

    scheduler._validate_telegram_startup()
    scheduler._initialize_trading_components()
    await scheduler._restore_wallet_state()
    await scheduler.refresh_markets_once()
    await scheduler._fetch_resolved_markets()
    await scheduler.start_websockets()

    loop_count = 1
    last_report_date: date | None = None

    try:
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

            scheduler._persist_state()
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


async def _check_iteration_settlements(scheduler: PolySignalScheduler) -> None:
    try:
        settled = await scheduler.check_settlements()
        if settled:
            scheduler.logger.info("Settled %d positions", len(settled))
    except Exception as exc:
        scheduler.logger.error("check_settlements failed: %s", exc)


async def _generate_iteration_report(
    scheduler: PolySignalScheduler, last_report_date: date | None
) -> date | None:
    today = date.today()
    if last_report_date == today:
        return last_report_date
    try:
        report = await scheduler.generate_daily_report()
        if report:
            return today
    except Exception as exc:
        scheduler.logger.error("generate_daily_report failed: %s", exc)
    return last_report_date
