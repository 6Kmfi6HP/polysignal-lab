from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, assert_never

import httpx

from polysignal_lab.app import scheduler_runtime
from polysignal_lab.domain.enums import MarketStatus
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
    markets = await scheduler.discovery.discover()
    scheduler.ctx.markets.upsert_many(markets)
    for market in markets:
        try:
            scheduler.sqlite.upsert_market(market)
            scheduler.logs.append("markets", market)
        except (OSError, sqlite3.Error, TypeError, ValueError):
            pass

    for market in scheduler.ctx.markets.active():
        try:
            scheduler.anchor_prices.capture_for_market(market)
        except (OSError, sqlite3.Error, TypeError, ValueError):
            pass

    token_ids = token_ids_for_markets(markets)
    scheduler._latest_market_token_ids = token_ids
    scheduler._market_refresh_completed = True

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

    params = {"closed": "true", "limit": "200", "offset": "0"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{scheduler.settings.data.polymarket.gamma_base_url}/markets",
                params=params,
            )
            if response.status_code != 200:
                return
            data = response.json()
            if not isinstance(data, list):
                return

            payloads = scheduler.discovery._flatten_markets(data)
            updated = 0
            for payload in payloads:
                market_id = str(
                    payload.get("id")
                    or payload.get("market")
                    or payload.get("conditionId")
                    or payload.get("slug")
                    or ""
                )
                if market_id not in open_market_ids:
                    continue

                try:
                    match = scheduler.discovery._match_crypto_updown(payload)
                    asset, timeframe = match if match else ("UNKNOWN", "UNKNOWN")
                    market = Market.from_gamma(payload, asset=asset, timeframe=timeframe)
                    match market.status:
                        case MarketStatus.RESOLVED | MarketStatus.CANCELLED:
                            scheduler.ctx.markets.upsert_many([market])
                            scheduler.sqlite.upsert_market(market)
                            updated += 1
                        case (
                            MarketStatus.ACTIVE
                            | MarketStatus.CLOSED
                            | MarketStatus.UNKNOWN
                        ):
                            continue
                        case unreachable:
                            assert_never(unreachable)
                except (KeyError, OSError, sqlite3.Error, TypeError, ValueError):
                    pass

            if updated > 0:
                scheduler.logger.info("Fetched %d resolved markets from Gamma API", updated)
    except (httpx.HTTPError, TypeError, ValueError) as exc:
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
