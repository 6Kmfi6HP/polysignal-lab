from __future__ import annotations
import sqlite3


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
    scheduler.market_universe.discovery = scheduler.discovery
    scheduler.book_feed.market_data = scheduler.market_data
    markets = await scheduler.market_universe.refresh_once()
    for market in scheduler.ctx.markets.active():
        try:
            scheduler.anchor_prices.capture_for_market(market)
        except (OSError, sqlite3.Error, TypeError, ValueError):
            pass
    token_ids = scheduler.market_universe.latest_token_ids or token_ids_for_markets(markets)
    scheduler._latest_market_token_ids = token_ids
    scheduler._market_refresh_completed = scheduler.market_universe.refresh_completed

    if token_ids:
        try:
            books = await scheduler.market_data.get_books(list(token_ids))
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
        scheduler.market_universe.discovery = scheduler.discovery
        await scheduler.market_universe.fetch_resolved(open_market_ids)
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        scheduler.logger.warning("Failed to fetch resolved markets: %s", exc)


async def stop_market_ws_subscription(scheduler: PolySignalScheduler) -> None:
    await scheduler.book_feed.stop_subscription()
    scheduler._market_ws_task = scheduler.book_feed.market_task
    scheduler._market_ws_token_ids = scheduler.book_feed.token_ids
    scheduler._ws_tasks = [
        *scheduler.book_feed.tasks,
        *scheduler.spot_feed.tasks(),
    ]


async def sync_market_ws_subscription(
    scheduler: PolySignalScheduler, token_ids: tuple[str, ...]
) -> None:
    scheduler.book_feed.config = scheduler.settings.data.polymarket
    scheduler.book_feed.websocket = scheduler.poly_ws
    await scheduler.book_feed.sync_subscription(token_ids)
    scheduler._market_ws_task = scheduler.book_feed.market_task
    scheduler._market_ws_token_ids = scheduler.book_feed.token_ids
    scheduler._ws_tasks = [
        *scheduler.book_feed.tasks,
        *scheduler.spot_feed.tasks(),
    ]


async def start_websockets(
    scheduler: PolySignalScheduler,
) -> list[scheduler_runtime.Task]:
    scheduler._streams_started = True
    token_ids = scheduler._latest_market_token_ids
    if not scheduler._market_refresh_completed:
        token_ids = token_ids_for_markets(list(scheduler.ctx.markets.markets.values()))
    await sync_market_ws_subscription(scheduler, token_ids)
    scheduler.spot_feed.feed = scheduler.binance_ws
    scheduler.spot_feed.enabled = scheduler.settings.data.binance.enabled
    await scheduler.spot_feed.start()
    scheduler._binance_ws_task = scheduler.spot_feed.task
    scheduler._ws_tasks = [
        *scheduler.book_feed.tasks,
        *scheduler.spot_feed.tasks(),
    ]
    return list(scheduler._ws_tasks)
