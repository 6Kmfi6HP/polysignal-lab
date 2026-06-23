from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from polysignal_lab.app import scheduler as scheduler_module
from polysignal_lab.app.scheduler import PolySignalScheduler, TelegramStartupConfigError
from polysignal_lab.config import PaperTradingConfig, PolymarketDataConfig, Settings, StrategyConfig
from polysignal_lab.domain.market import Market
from polysignal_lab.paper.simulator import PaperSimulator
from polysignal_lab.paper.wallet import PaperWallet
from polysignal_lab.strategies.base import BaseStrategy
from factories import MarketFactoryConfig, sample_market


class FakeDiscovery:
    def __init__(self, batches: Sequence[list[Market]], events: list[str]) -> None:
        self._batches = list(batches)
        self._events = events
        self.calls = 0

    async def discover(self) -> list[Market]:
        self._events.append("discover")
        if self.calls >= len(self._batches):
            return self._batches[-1] if self._batches else []
        batch = self._batches[self.calls]
        self.calls += 1
        return batch


class FakeRest:
    async def get_books(self, token_ids: list[str]) -> list[object]:
        return []


class RecordingPolymarketWs:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.subscriptions: list[tuple[str, ...]] = []
        self.stop_count = 0
        self.running = False

    async def subscribe(self, token_ids: list[str]) -> None:
        self.events.append("poly_subscribe")
        self.subscriptions.append(tuple(token_ids))
        self.running = True

    def stop(self) -> None:
        self.stop_count += 1
        self.running = False


class RecordingBinanceWs:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.stop_count = 0

    async def run(self) -> None:
        self.events.append("binance_run")

    def stop(self) -> None:
        self.stop_count += 1


def _scheduler(tmp_path: Path) -> PolySignalScheduler:
    settings = Settings()
    settings.telegram.enabled = False
    settings.telegram.send_signals = False
    settings.telegram.send_paper_results = False
    settings.telegram.send_daily_report = False
    settings.data.binance.enabled = False
    settings.data.polymarket.use_market_ws = True
    settings.markets.refresh_interval_sec = 0
    return PolySignalScheduler(settings, base_dir=tmp_path)


async def test_refresh_markets_before_starting_streams(tmp_path: Path) -> None:
    # Given: startup discovery returns token-bearing markets.
    scheduler = _scheduler(tmp_path)
    market = sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m"))
    events: list[str] = []

    async def refresh_markets_once() -> None:
        events.append("discover")
        scheduler.ctx.markets.upsert_many([market])

    async def start_websockets() -> list[object]:
        events.append("streams_started")
        assert scheduler.ctx.markets.active()
        return []

    async def evaluate_once() -> list[object]:
        scheduler._running = False
        return []

    async def generate_daily_report() -> None:
        return None

    scheduler.refresh_markets_once = refresh_markets_once
    scheduler.start_websockets = start_websockets
    scheduler.evaluate_once = evaluate_once
    scheduler.check_settlements = evaluate_once
    scheduler.generate_daily_report = generate_daily_report

    # When: the scheduler run loop starts.
    await scheduler.run()

    # Then: market discovery happens before any websocket startup.
    assert events[:2] == ["discover", "streams_started"]


async def test_live_telegram_settings_validate_before_market_discovery(tmp_path: Path) -> None:
    # Given: live Telegram publishing is enabled without exported credentials.
    scheduler = _scheduler(tmp_path)
    scheduler.settings.telegram.enabled = True
    scheduler.settings.telegram.dry_run = False
    scheduler.settings.telegram.bot_token_env = "POLYSIGNAL_TEST_MISSING_BOT_TOKEN"
    scheduler.settings.telegram.channel_id_env = "POLYSIGNAL_TEST_MISSING_CHANNEL_ID"
    events: list[str] = []

    async def refresh_markets_once() -> None:
        events.append("discover")

    scheduler.refresh_markets_once = refresh_markets_once

    # When: the scheduler starts.
    with pytest.raises(RuntimeError):
        await scheduler.run()

    # Then: startup validation fails before market discovery or websocket startup.
    assert events == []


async def test_initial_discovery_failure_prevents_stream_startup(tmp_path: Path) -> None:
    # Given: the initial market discovery fails during scheduler startup.
    scheduler = _scheduler(tmp_path)
    events: list[str] = []

    async def refresh_markets_once() -> None:
        events.append("discover_raise")
        raise RuntimeError("discovery failed")

    async def start_websockets() -> list[scheduler_module.asyncio.Task]:
        events.append("streams_started")
        scheduler._running = False
        return []

    scheduler.refresh_markets_once = refresh_markets_once
    scheduler.start_websockets = start_websockets

    # When: the scheduler run loop starts.
    with pytest.raises(RuntimeError, match="discovery failed"):
        await scheduler.run()

    # Then: startup stops immediately and never starts websocket streams.
    assert events == ["discover_raise"]


async def test_live_telegram_validation_runs_before_strategy_and_paper_initialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: live Telegram publishing will fail startup validation.
    settings = Settings()
    settings.telegram.enabled = True
    settings.telegram.dry_run = False
    settings.telegram.send_signals = True
    settings.telegram.send_consensus_signals = False
    settings.telegram.send_paper_results = False
    settings.telegram.send_daily_report = False
    settings.data.binance.enabled = False
    settings.data.polymarket.use_market_ws = False
    settings.markets.refresh_interval_sec = 0
    events: list[str] = []

    def record_build_strategies(config: StrategyConfig) -> list[BaseStrategy]:
        events.append("strategy_load")
        return []

    class RecordingPaperWallet(PaperWallet):
        def __init__(self, starting_balance: float = 1000.0) -> None:
            events.append("wallet_init")
            super().__init__(starting_balance)

    def record_paper_simulator(
        config: PaperTradingConfig,
        data_config: PolymarketDataConfig,
        wallet: PaperWallet,
    ) -> PaperSimulator:
        events.append("paper_init")
        return PaperSimulator(config, data_config, wallet)

    def validate_telegram_startup(self: PolySignalScheduler) -> None:
        events.append("telegram_validate")
        raise TelegramStartupConfigError(("TELEGRAM_BOT_TOKEN",))

    monkeypatch.setattr(scheduler_module, "build_strategies", record_build_strategies)
    monkeypatch.setattr(scheduler_module, "PaperWallet", RecordingPaperWallet)
    monkeypatch.setattr(scheduler_module, "PaperSimulator", record_paper_simulator)
    monkeypatch.setattr(PolySignalScheduler, "_validate_telegram_startup", validate_telegram_startup)
    scheduler = PolySignalScheduler(settings, base_dir=tmp_path)

    # When: the scheduler starts.
    with pytest.raises(TelegramStartupConfigError):
        await scheduler.run()

    # Then: live Telegram validation is the first startup gate and prevents later initialization.
    assert events == ["telegram_validate"]


async def test_market_ws_subscribes_after_token_discovery(tmp_path: Path) -> None:
    # Given: startup discovery can find one active Polymarket market with Up/Down token ids.
    scheduler = _scheduler(tmp_path)
    market = sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m"))
    events: list[str] = []
    poly_ws = RecordingPolymarketWs(events)
    scheduler.discovery = FakeDiscovery([[market]], events)
    scheduler.rest = FakeRest()
    scheduler.poly_ws = poly_ws

    async def evaluate_once() -> list[object]:
        await scheduler_module.asyncio.sleep(0)
        scheduler._running = False
        return []

    async def generate_daily_report() -> None:
        return None

    scheduler.evaluate_once = evaluate_once
    scheduler.check_settlements = evaluate_once
    scheduler.generate_daily_report = generate_daily_report

    # When: the scheduler starts normally.
    await scheduler.run()

    # Then: the Polymarket subscription receives the non-empty discovered token set.
    expected_tokens = tuple(token.token_id for token in market.outcome_tokens)
    assert poly_ws.subscriptions == [expected_tokens]


async def test_empty_market_refresh_does_not_subscribe_market_ws(tmp_path: Path) -> None:
    # Given: an existing subscription has been started from a prior non-empty discovery.
    scheduler = _scheduler(tmp_path)
    market = sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m"))
    events: list[str] = []
    poly_ws = RecordingPolymarketWs(events)
    scheduler.discovery = FakeDiscovery([[market], []], events)
    scheduler.rest = FakeRest()
    scheduler.poly_ws = poly_ws
    await scheduler.refresh_markets_once()
    tasks = await scheduler.start_websockets()
    for task in tasks:
        await task

    # When: the next market refresh discovers no token ids.
    await scheduler.refresh_markets_once()

    # Then: the old market websocket is stopped and no empty subscription is sent.
    assert poly_ws.stop_count == 1
    assert () not in poly_ws.subscriptions
    assert len(poly_ws.subscriptions) == 1


async def test_market_ws_resubscribes_when_token_set_changes(tmp_path: Path) -> None:
    # Given: a running market websocket subscription for one token set.
    scheduler = _scheduler(tmp_path)
    first_market = sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m"))
    second_market = sample_market(MarketFactoryConfig(asset="ETH", timeframe="15m"))
    events: list[str] = []
    poly_ws = RecordingPolymarketWs(events)
    scheduler.discovery = FakeDiscovery([[first_market], [second_market]], events)
    scheduler.rest = FakeRest()
    scheduler.poly_ws = poly_ws
    await scheduler.refresh_markets_once()
    tasks = await scheduler.start_websockets()
    for task in tasks:
        await task

    # When: discovery returns a changed token set.
    await scheduler.refresh_markets_once()
    await scheduler_module.asyncio.sleep(0)

    # Then: the scheduler stops the old subscription and starts a new non-empty one.
    assert poly_ws.stop_count == 1
    assert poly_ws.subscriptions == [
        tuple(token.token_id for token in first_market.outcome_tokens),
        tuple(token.token_id for token in second_market.outcome_tokens),
    ]
