"""
Input: __future__, __future__.annotations, inspect, logging, sqlite3, collections.abc, collections.abc.Awaitable, collections.abc.Callable, typing, typing.Any
Output: MarketUniverseService
Pos: Service Layer - Business logic

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

import inspect
import logging
import sqlite3
from collections.abc import Awaitable, Callable
from typing import Any, cast

import httpx

from polysignal_lab.app.scheduler_market_data import token_ids_for_markets
from polysignal_lab.config import Settings
from polysignal_lab.data.state import MarketRegistry
from polysignal_lab.domain.enums import MarketStatus
from polysignal_lab.domain.market import Market


class MarketUniverseService:
    name = "market_universe"

    def __init__(
        self,
        discovery: Any,
        markets: MarketRegistry,
        persistence: Any,
        *,
        settings: Settings | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.discovery = discovery
        self.markets = markets
        self.persistence = persistence
        self.settings = settings
        self.logger = logger or logging.getLogger("polysignal_lab.scheduler.market_universe")
        self.latest_token_ids: tuple[str, ...] = ()
        self.refresh_completed = False

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    def health(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": "ok",
            "metrics": {"active_markets": len(self.active_markets())},
        }

    async def refresh_once(self) -> list[Market]:
        discover_active = cast(
            Callable[[], Awaitable[list[Market]]] | None,
            getattr(self.discovery, "active_markets", None),
        )
        if callable(discover_active):
            markets = await discover_active()
        else:
            discover = cast(
                Callable[..., Awaitable[list[Market]]],
                self.discovery.discover,
            )
            markets = await discover(**self._discover_kwargs(discover))
        changed_ids = {
            market.market_id
            for market in markets
            if self.markets.get(market.market_id) != market
        }
        self.markets.upsert_many(markets)
        for market in markets:
            try:
                self.persistence.upsert_market(market)
                # Skip the JSONL append when the payload is unchanged since the
                # last refresh — with a 10s refresh interval, unconditional
                # appends duplicated ~10KB per market per refresh (~1.3GB/day).
                if market.market_id in changed_ids:
                    self.persistence.append_log("markets", market)
            except (OSError, sqlite3.Error, TypeError, ValueError):
                pass
        self.latest_token_ids = token_ids_for_markets(markets)
        self.refresh_completed = True
        return markets

    def refresh_once_sync(self) -> list[Market]:
        discover_active = cast(
            Callable[[], list[Market]] | None,
            getattr(self.discovery, "active_markets_sync", None),
        )
        if callable(discover_active):
            markets = discover_active()
        else:
            discover = cast(
                Callable[..., list[Market]],
                getattr(self.discovery, "discover_sync"),
            )
            markets = discover(**self._discover_kwargs(discover))
        changed_ids = {
            market.market_id
            for market in markets
            if self.markets.get(market.market_id) != market
        }
        self.markets.upsert_many(markets)
        for market in markets:
            try:
                self.persistence.upsert_market(market)
                if market.market_id in changed_ids:
                    self.persistence.append_log("markets", market)
            except (OSError, sqlite3.Error, TypeError, ValueError):
                pass
        self.latest_token_ids = token_ids_for_markets(markets)
        self.refresh_completed = True
        return markets

    async def fetch_resolved(self, open_market_ids: set[str] | None = None) -> list[Market]:
        resolved_markets = cast(
            Callable[[], Awaitable[list[Market]]] | None,
            getattr(self.discovery, "resolved_markets", None),
        )
        if callable(resolved_markets):
            markets = await resolved_markets()
            return self._store_resolved(markets)
        if self.settings is None:
            return []
        resolved: list[Market] = []
        async with httpx.AsyncClient(timeout=15.0) as client:
            for market_id in sorted(open_market_ids or ()):
                local_market = self.markets.get(market_id)
                response = await client.get(
                    f"{self.settings.data.polymarket.gamma_base_url}/markets/{market_id}"
                )
                if response.status_code == 404 and local_market is not None and local_market.condition_id:
                    response = await client.get(
                        f"{self.settings.data.polymarket.gamma_base_url}/markets",
                        params={"condition_ids": local_market.condition_id, "closed": "true"},
                    )
                if response.status_code != 200:
                    continue
                data = response.json()
                payload = data[0] if isinstance(data, list) and data else data
                if not isinstance(payload, dict):
                    continue
                match = (
                    self.discovery._match_crypto_updown(payload)
                    if hasattr(self.discovery, "_match_crypto_updown")
                    else None
                )
                asset, timeframe = match if match else (
                    (local_market.asset, local_market.timeframe)
                    if local_market
                    else ("UNKNOWN", "UNKNOWN")
                )
                market = Market.from_gamma(payload, asset=asset, timeframe=timeframe)
                if market.status in {MarketStatus.RESOLVED, MarketStatus.CANCELLED}:
                    resolved.append(market)
        stored = self._store_resolved(resolved)
        if stored:
            self.logger.info("Fetched %d resolved markets from Gamma API", len(stored))
        return stored

    def active_markets(self) -> list[Market]:
        return self.markets.active()

    def token_ids(self) -> tuple[str, ...]:
        return token_ids_for_markets(list(self.markets.markets.values()))

    def _discover_kwargs(
        self,
        discover: Callable[..., object],
    ) -> dict[str, int]:
        if self.settings is None or self.settings.runtime.engine != "nautilus":
            return {}
        try:
            parameters = inspect.signature(discover).parameters
        except (TypeError, ValueError):
            return {}
        kwargs = {
            "include_next_periods": max(
                int(self.settings.runtime.nautilus.market_rotation.include_next_periods),
                0,
            ),
            "stale_grace_sec": max(
                int(self.settings.runtime.nautilus.market_rotation.stale_grace_sec),
                0,
            ),
        }
        if any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        ):
            return kwargs
        return {name: value for name, value in kwargs.items() if name in parameters}

    def _store_resolved(self, markets: list[Market]) -> list[Market]:
        for market in markets:
            self.markets.upsert_many([market])
            try:
                self.persistence.upsert_market(market)
            except (OSError, sqlite3.Error, TypeError, ValueError):
                pass
        return markets
