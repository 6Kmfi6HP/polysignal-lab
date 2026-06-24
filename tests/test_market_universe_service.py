import sqlite3

from polysignal_lab.app.services.market_universe_service import MarketUniverseService
from polysignal_lab.domain.enums import MarketStatus
from polysignal_lab.data.state import MarketRegistry
from factories import MarketFactoryConfig, sample_market


class _Discovery:
    async def active_markets(self):
        return []

    async def resolved_markets(self):
        return []


class _Persistence:
    def append_log(self, stream, payload):
        pass

    def upsert_market(self, market):
        pass


async def test_market_universe_refresh_keeps_registry_empty_when_no_markets(settings) -> None:
    registry = MarketRegistry()
    service = MarketUniverseService(_Discovery(), registry, _Persistence())

    await service.refresh_once()

    assert service.active_markets() == []


class _OneMarketDiscovery:
    def __init__(self, market):
        self.market = market

    async def active_markets(self):
        return [self.market]


class _FailingPersistence:
    def upsert_market(self, market):
        raise OSError("disk full")

    def append_log(self, stream, payload):
        raise AssertionError("append_log should not run after upsert failure")


class _ResolvedMarketDiscovery:
    def __init__(self, *markets):
        self.markets = list(markets)

    async def resolved_markets(self):
        return self.markets


class _FailFirstSqlitePersistence:
    def __init__(self):
        self.attempts = 0
        self.persisted = []

    def upsert_market(self, market):
        self.attempts += 1
        if self.attempts == 1:
            raise sqlite3.OperationalError("database is locked")
        self.persisted.append(market)

    def append_log(self, stream, payload):
        pass


async def test_market_universe_refresh_keeps_tokens_when_persistence_fails(settings) -> None:
    market = sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m"))
    service = MarketUniverseService(
        _OneMarketDiscovery(market),
        MarketRegistry(),
        _FailingPersistence(),
    )

    await service.refresh_once()

    assert service.active_markets() == [market]
    assert service.latest_token_ids == tuple(token.token_id for token in market.outcome_tokens)


async def test_market_universe_resolved_refresh_keeps_registry_when_persistence_fails(settings) -> None:
    market = sample_market(
        MarketFactoryConfig(asset="BTC", timeframe="5m", seconds_to_close=-1)
    ).model_copy(update={"status": MarketStatus.RESOLVED})
    service = MarketUniverseService(
        _ResolvedMarketDiscovery(market),
        MarketRegistry(),
        _FailingPersistence(),
    )

    resolved = await service.fetch_resolved({"ignored-by-callable-discovery"})

    assert resolved == [market]
    assert service.markets.get(market.market_id) == market


async def test_market_universe_resolved_refresh_continues_after_sqlite_failure(settings) -> None:
    failed_market = sample_market(
        MarketFactoryConfig(asset="BTC", timeframe="5m", seconds_to_close=-1)
    ).model_copy(update={"status": MarketStatus.RESOLVED})
    next_market = sample_market(
        MarketFactoryConfig(asset="ETH", timeframe="15m", seconds_to_close=-1)
    ).model_copy(update={"status": MarketStatus.RESOLVED})
    persistence = _FailFirstSqlitePersistence()
    service = MarketUniverseService(
        _ResolvedMarketDiscovery(failed_market, next_market),
        MarketRegistry(),
        persistence,
    )

    resolved = await service.fetch_resolved({"ignored-by-callable-discovery"})

    assert resolved == [failed_market, next_market]
    assert service.markets.get(failed_market.market_id) == failed_market
    assert service.markets.get(next_market.market_id) == next_market
    assert persistence.persisted == [next_market]
