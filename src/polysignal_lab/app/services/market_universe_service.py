from __future__ import annotations

import logging
import sqlite3
from typing import Any, assert_never

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
        discover_active = getattr(self.discovery, "active_markets", None)
        markets = await (discover_active() if callable(discover_active) else self.discovery.discover())
        self.markets.upsert_many(markets)
        for market in markets:
            try:
                self.persistence.upsert_market(market)
                self.persistence.append_log("markets", market)
            except (OSError, sqlite3.Error, TypeError, ValueError):
                pass
        self.latest_token_ids = token_ids_for_markets(markets)
        self.refresh_completed = True
        return markets

    async def fetch_resolved(self, open_market_ids: set[str] | None = None) -> list[Market]:
        resolved_markets = getattr(self.discovery, "resolved_markets", None)
        if callable(resolved_markets):
            markets = await resolved_markets()
            return self._store_resolved(markets)
        if not open_market_ids or self.settings is None:
            return []

        params = {"closed": "true", "limit": "200", "offset": "0"}
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{self.settings.data.polymarket.gamma_base_url}/markets",
                params=params,
            )
            if response.status_code != 200:
                return []
            data = response.json()
            if not isinstance(data, list):
                return []

        payloads = self.discovery._flatten_markets(data)
        resolved: list[Market] = []
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
            match = self.discovery._match_crypto_updown(payload)
            asset, timeframe = match if match else ("UNKNOWN", "UNKNOWN")
            market = Market.from_gamma(payload, asset=asset, timeframe=timeframe)
            match market.status:
                case MarketStatus.RESOLVED | MarketStatus.CANCELLED:
                    resolved.append(market)
                case MarketStatus.ACTIVE | MarketStatus.CLOSED | MarketStatus.UNKNOWN:
                    continue
                case unreachable:
                    assert_never(unreachable)
        stored = self._store_resolved(resolved)
        if stored:
            self.logger.info("Fetched %d resolved markets from Gamma API", len(stored))
        return stored

    def active_markets(self) -> list[Market]:
        return self.markets.active()

    def token_ids(self) -> tuple[str, ...]:
        return token_ids_for_markets(list(self.markets.markets.values()))

    def _store_resolved(self, markets: list[Market]) -> list[Market]:
        for market in markets:
            self.markets.upsert_many([market])
            self.persistence.upsert_market(market)
        return markets
