from polysignal_lab.app.services.market_universe_service import MarketUniverseService
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
