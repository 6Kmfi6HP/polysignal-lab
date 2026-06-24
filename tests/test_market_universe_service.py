from polysignal_lab.app.services.market_universe_service import MarketUniverseService
from polysignal_lab.data.state import MarketRegistry


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
