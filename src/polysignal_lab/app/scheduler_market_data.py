from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from polysignal_lab.app import scheduler_runtime
from polysignal_lab.domain.market import Market

if TYPE_CHECKING:
    from polysignal_lab.app.scheduler import PolySignalScheduler


def token_ids_for_markets(markets: list[Market]) -> tuple[str, ...]:
    token_ids = (
        token.token_id
        for market in markets
        for token in market.outcome_tokens
        if token.token_id
    )
    return tuple(dict.fromkeys(token_ids))


async def refresh_markets_once(scheduler: PolySignalScheduler) -> None:
    await scheduler.market_universe.refresh_once()
    token_ids = scheduler.market_universe.latest_token_ids
    scheduler._latest_market_token_ids = token_ids
    scheduler._market_refresh_completed = scheduler.market_universe.refresh_completed

    if token_ids:
        try:
            books = await scheduler.rest.get_books(list(token_ids))
            for book in books:
                scheduler.ctx.books.update(book)
        except (httpx.HTTPError, TypeError, ValueError):
            scheduler.logger.exception(
                "Failed to fetch order books for %d tokens", len(token_ids)
            )
    if scheduler._streams_started:
        await sync_market_ws_subscription(scheduler, token_ids)


async def fetch_resolved_markets(scheduler: PolySignalScheduler) -> None:
    open_market_ids = {
        pos.market_id
        for pos in scheduler.wallet.open_positions.values()
        if pos.market_id
    }
    if not open_market_ids:
        return
    try:
        await scheduler.market_universe.fetch_resolved(open_market_ids)
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        scheduler.logger.warning("Failed to fetch resolved markets: %s", exc)


async def stop_market_ws_subscription(scheduler: PolySignalScheduler) -> None:
    if scheduler._market_ws_task is None and not scheduler._market_ws_token_ids:
        return
    scheduler.poly_ws.stop()
    task = scheduler._market_ws_task
    scheduler._market_ws_task = None
    scheduler._market_ws_token_ids = ()
    if task is None:
        return
    if not task.done():
        task.cancel()
        try:
            await task
        except scheduler_runtime.CancelledError:
            pass
    if task in scheduler._ws_tasks:
        scheduler._ws_tasks.remove(task)


async def sync_market_ws_subscription(
    scheduler: PolySignalScheduler, token_ids: tuple[str, ...]
) -> None:
    if scheduler.settings.data.polymarket.use_market_ws:
        if not token_ids:
            await stop_market_ws_subscription(scheduler)
            scheduler.logger.info(
                "No token IDs available for Polymarket WebSocket, falling back to REST polling"
            )
            return
        if (
            token_ids == scheduler._market_ws_token_ids
            and scheduler._market_ws_task is not None
            and not scheduler._market_ws_task.done()
        ):
            return
        await stop_market_ws_subscription(scheduler)
        scheduler.logger.info(
            "Starting Polymarket WebSocket with %d token subscriptions", len(token_ids)
        )
        task = scheduler_runtime.create_task(
            scheduler.poly_ws.subscribe(list(token_ids))
        )
        scheduler._market_ws_task = task
        scheduler._market_ws_token_ids = token_ids
        scheduler._ws_tasks.append(task)
    else:
        await stop_market_ws_subscription(scheduler)
        scheduler.logger.info("Polymarket WebSocket disabled in config, using REST polling")


async def start_websockets(
    scheduler: PolySignalScheduler,
) -> list[scheduler_runtime.Task]:
    scheduler._streams_started = True
    token_ids = scheduler._latest_market_token_ids
    if not scheduler._market_refresh_completed:
        token_ids = token_ids_for_markets(list(scheduler.ctx.markets.markets.values()))
    await sync_market_ws_subscription(scheduler, token_ids)

    if scheduler.settings.data.binance.enabled:
        if scheduler._binance_ws_task is None or scheduler._binance_ws_task.done():
            scheduler.logger.info("Starting Binance Spot WebSocket feed")
            task = scheduler_runtime.create_task(scheduler.binance_ws.run())
            scheduler._binance_ws_task = task
            scheduler._ws_tasks.append(task)
    else:
        scheduler.logger.info("Binance Spot WebSocket disabled in config")

    return list(scheduler._ws_tasks)
