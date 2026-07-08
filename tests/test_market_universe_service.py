"""
Input: pytest, sqlite3, polysignal_lab.app.services.market_universe_service, polysignal_lab.app.services.market_universe_service.MarketUniverseService, polysignal_lab.domain.enums, polysignal_lab.domain.enums.MarketStatus, polysignal_lab.data.state, polysignal_lab.data.state.MarketRegistry, factories, factories.MarketFactoryConfig
Output: test_market_universe_refresh_keeps_registry_empty_when_no_markets, test_market_universe_refresh_appends_market_log_only_on_change, test_market_universe_refresh_keeps_tokens_when_persistence_fails, test_market_universe_refresh_passes_rotation_window_options, test_market_universe_refresh_does_not_apply_rotation_window_options_in_legacy_mode, test_market_universe_resolved_refresh_keeps_registry_when_persistence_fails, test_market_universe_resolved_refresh_continues_after_sqlite_failure, test_fetch_resolved_uses_exact_market_lookup_for_open_ids, _Discovery, _Persistence
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







import pytest
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


class _DiscoverOnly:
    def __init__(self, market):
        self.market = market
        self.kwargs = None

    async def discover(self, *, include_next_periods: int = 0, stale_grace_sec: int = 0):
        self.kwargs = {
            "include_next_periods": include_next_periods,
            "stale_grace_sec": stale_grace_sec,
        }
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


class _RecordingPersistence:
    def __init__(self):
        self.appended = []

    def upsert_market(self, market):
        pass

    def append_log(self, stream, payload):
        self.appended.append((stream, payload))


async def test_market_universe_refresh_appends_market_log_only_on_change(settings) -> None:
    market = sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m"))
    discovery = _OneMarketDiscovery(market)
    persistence = _RecordingPersistence()
    service = MarketUniverseService(discovery, MarketRegistry(), persistence)

    await service.refresh_once()
    await service.refresh_once()

    assert len(persistence.appended) == 1

    discovery.market = market.model_copy(update={"status": MarketStatus.CLOSED})
    await service.refresh_once()

    assert len(persistence.appended) == 2


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


async def test_market_universe_refresh_passes_rotation_window_options(settings) -> None:
    market = sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m"))
    discovery = _DiscoverOnly(market)
    settings.runtime.nautilus.market_rotation.include_next_periods = 2
    settings.runtime.nautilus.market_rotation.stale_grace_sec = 7
    service = MarketUniverseService(
        discovery,
        MarketRegistry(),
        _Persistence(),
        settings=settings,
    )

    await service.refresh_once()

    assert discovery.kwargs == {
        "include_next_periods": 2,
        "stale_grace_sec": 7,
    }


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


@pytest.mark.anyio
async def test_fetch_resolved_uses_exact_market_lookup_for_open_ids(monkeypatch) -> None:
    from polysignal_lab.config import Settings

    calls: list[str] = []

    class _Response:
        status_code = 200
        def json(self) -> dict[str, object]:
            return {
                "id": "market-1",
                "conditionId": "condition-1",
                "slug": "slug-1",
                "umaResolutionStatus": "resolved",
                "outcomePrices": '["1", "0"]',
                "clobTokenIds": '["token-up", "token-down"]',
                "outcomes": '["Up", "Down"]',
            }
        def raise_for_status(self) -> None:
            return None

    class _Client:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        async def get(self, url: str, params: dict[str, str] | None = None):
            calls.append(url)
            return _Response()

    monkeypatch.setattr("polysignal_lab.app.services.market_universe_service.httpx.AsyncClient", _Client)
    registry = MarketRegistry()
    registry.upsert_many([sample_market().model_copy(update={"market_id": "market-1", "condition_id": "condition-1"})])
    service = MarketUniverseService(discovery=object(), markets=registry, persistence=_Persistence(), settings=Settings())

    resolved = await service.fetch_resolved({"market-1"})

    assert resolved[0].market_id == "market-1"
    assert resolved[0].status == MarketStatus.RESOLVED
    assert calls == ["https://gamma-api.polymarket.com/markets/market-1"]
