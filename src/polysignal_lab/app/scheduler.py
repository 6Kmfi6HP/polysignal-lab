"""
Input: __future__, __future__.annotations, asyncio, logging, dataclasses, dataclasses.dataclass, dataclasses.field, pathlib, pathlib.Path, polysignal_lab.app
Output: run_scheduler, ServiceContext, SchedulerServiceContext, build_nautilus_service_context, TelegramStartupConfigError, PolySignalScheduler
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

import asyncio
import logging
import warnings
from dataclasses import dataclass, field
from pathlib import Path

from polysignal_lab.app import (
    scheduler_market_data,
    scheduler_processing,
    scheduler_state,
)
from polysignal_lab.app.services.book_feed_service import BookFeedService
from polysignal_lab.app.services.health_service import HealthService
from polysignal_lab.app.services.persistence_service import PersistenceService
from polysignal_lab.app.services.market_universe_service import MarketUniverseService
from polysignal_lab.app.services.spot_feed_service import SpotFeedService
from polysignal_lab.app.services.publish_service import PublishService
from polysignal_lab.app.services.signal_pipeline import SignalPipeline
from polysignal_lab.app.services.runtime_service import ServiceSupervisor
from polysignal_lab.app.services.snapshot_service import SnapshotService
from polysignal_lab.config import Settings
from polysignal_lab.data.binance_spot_ws import BinanceSpotFeed
from polysignal_lab.data.anchor_price_service import AnchorPriceService
from polysignal_lab.data.market_snapshot import MarketSnapshotBuilder
from polysignal_lab.data.polymarket_clob_rest import PolymarketCLOBRestClient
from polysignal_lab.data.public_market_data_client import PublicMarketDataClient
from polysignal_lab.data.polymarket_clob_ws import PolymarketMarketWebSocket
from polysignal_lab.data.polymarket_rtds_ws import PolymarketRtdsPriceFeed
from polysignal_lab.data.polymarket_market_discovery import MarketDiscovery
from polysignal_lab.data.price_to_beat_provider import PriceToBeatProvider
from polysignal_lab.data.state import MarketRegistry, OrderBookRegistry, SpotRegistry
from polysignal_lab.observability.health import HealthRegistry
from polysignal_lab.domain.market import Market
from polysignal_lab.domain.paper_result import DailyReport, PaperTradeResult
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.data.ctf_resolution_client import CtfResolutionClient
from polysignal_lab.data.gamma_resolution_client import GammaResolutionClient
from polysignal_lab.paper.settlement_resolver import SettlementResolver
from polysignal_lab.paper.settlement_sources import WsResolutionCache

from polysignal_lab.publish.telegram_publisher import (
    TelegramPublisher,
    invalid_telegram_credential_fields,
)
from polysignal_lab.publish.telegram_bot import TelegramBotService
from polysignal_lab.signal_layer.arbiter import SignalArbiter
from polysignal_lab.signal_layer.consensus import ConsensusEngine
from polysignal_lab.signal_layer.formatter import MessageFormatter
from polysignal_lab.signal_layer.gate import SignalGate
from polysignal_lab.storage.jsonl_store import JSONLStore
from polysignal_lab.storage.sqlite_store import SQLiteStore
from polysignal_lab.storage.state_store import StateStore
from polysignal_lab.strategies.execution import build_strategy_schedule


def _make_fill_notifier(_scheduler: object, _strategies: object) -> None:
    raise RuntimeError("Local paper fill notifier was removed; Nautilus emits order/fill callbacks")

@dataclass
class ServiceContext:
    settings: Settings
    markets: MarketRegistry = field(default_factory=MarketRegistry)
    books: OrderBookRegistry = field(default_factory=OrderBookRegistry)
    spots: SpotRegistry = field(default_factory=SpotRegistry)


@dataclass(frozen=True, slots=True)
class TelegramStartupConfigError(RuntimeError):
    missing_fields: tuple[str, ...]

    def __str__(self) -> str:
        fields = ", ".join(self.missing_fields)
        return f"Telegram live publishing is enabled but missing: {fields}"


@dataclass
class SchedulerServiceContext:
    """Lightweight context holding only the services consumed by the Nautilus runtime path.

    PolySignalScheduler composes this context + legacy-only services.
    Build via ``build_nautilus_service_context()``.
    """

    settings: Settings
    market_universe: MarketUniverseService
    health: HealthRegistry
    persistence: PersistenceService
    publisher: TelegramPublisher
    publish_service: PublishService
    sqlite: SQLiteStore
    signal_pipeline: SignalPipeline


def build_nautilus_service_context(
    settings: Settings,
    base_dir: str | Path = ".",
    market_data_client: PublicMarketDataClient | None = None,
) -> SchedulerServiceContext:
    """Build only the services needed by the Nautilus runtime path (~8 services).

    Avoids constructing ~22 legacy-only objects (WebSocket connections,
    settlement resolvers, anchor prices, snapshot builders, supervisors, etc.)
    that ``PolySignalScheduler.__init__`` creates.
    """
    ctx = ServiceContext(settings=settings)
    _market_data: PublicMarketDataClient = (
        market_data_client
        if market_data_client is not None
        else PolymarketCLOBRestClient(settings.data.polymarket)
    )
    _gate = SignalGate(settings.signal, settings.data.polymarket, settings.data.binance)
    _consensus = ConsensusEngine(
        settings.signal.consensus_window_sec,
        settings.signal.consensus_enabled,
    )
    _formatter = MessageFormatter(settings.telegram.max_message_chars)
    publisher = TelegramPublisher(settings.telegram)
    health = HealthRegistry()
    discovery = MarketDiscovery(settings.data.polymarket, settings.markets)
    base = Path(base_dir)
    logs = JSONLStore(base / settings.storage.jsonl_dir)
    state = StateStore(base / settings.storage.state_dir)
    sqlite = SQLiteStore(base / settings.storage.sqlite_path)
    persistence = PersistenceService(logs, sqlite, state)
    market_universe = MarketUniverseService(
        discovery,
        ctx.markets,
        persistence,
        settings=settings,
        logger=logging.getLogger("polysignal_lab.scheduler"),
    )
    signal_pipeline = SignalPipeline(
        [],
        _gate,
        _consensus,
        persistence,
        logger=logging.getLogger("polysignal_lab.scheduler"),
    )
    publish_service = PublishService(
        _formatter,
        publisher,
        persistence,
        timeout_sec=settings.telegram.publish_timeout_sec,
    )
    return SchedulerServiceContext(
        settings=settings,
        market_universe=market_universe,
        health=health,
        persistence=persistence,
        publisher=publisher,
        publish_service=publish_service,
        sqlite=sqlite,
        signal_pipeline=signal_pipeline,
    )


class PolySignalScheduler:
    def __init__(
        self,
        settings: Settings,
        base_dir: str | Path = ".",
        market_data_client: PublicMarketDataClient | None = None,
        *,
        _context: SchedulerServiceContext | None = None,
    ):
        warnings.warn(
            "PolySignalScheduler is legacy; use SchedulerServiceContext for Nautilus runtime",
            DeprecationWarning,
            stacklevel=2,
        )
        if _context is not None:
            self._init_from_context(_context, settings)
            return
        self._init_full(settings, base_dir, market_data_client)

    def _init_from_context(
        self, ctx: SchedulerServiceContext, settings: Settings
    ) -> None:
        """Lightweight init — only services the Nautilus runtime path needs."""
        self.settings = ctx.settings
        self.ctx = ServiceContext(settings=ctx.settings)
        self.health = ctx.health
        self.persistence = ctx.persistence
        self.publisher = ctx.publisher
        self.market_universe = ctx.market_universe
        self.sqlite = ctx.sqlite
        self.signal_pipeline = ctx.signal_pipeline
        self.publish_service = ctx.publish_service
        self.logger = logging.getLogger("polysignal_lab.scheduler")
        self._trading_components_initialized = False
        self._follow_up_signals: list[SignalCandidate] = []
        self._ws_tasks: list[asyncio.Task] = []
        self._market_ws_task: asyncio.Task | None = None
        self._binance_ws_task: asyncio.Task | None = None
        self._latest_market_token_ids: tuple[str, ...] = ()
        self._market_ws_token_ids: tuple[str, ...] = ()
        self._market_refresh_completed = False
        self._streams_started = False
        self._running = False
        self.telegram_bot = None
        self.nautilus_cache_reader = None
        self.paper_execution_metadata = None
        self.strategy_schedule = None
        self.strategies = None
        self.arbiter = None

    def _init_full(
        self,
        settings: Settings,
        base_dir: str | Path = ".",
        market_data_client: PublicMarketDataClient | None = None,
    ) -> None:

    @property
    def rest(self) -> PublicMarketDataClient:
        return self.market_data

    @rest.setter
    def rest(self, client: PublicMarketDataClient) -> None:
        self.market_data = client

    def _initialize_trading_components(self) -> None:
        if self._trading_components_initialized:
            return
        self.strategy_schedule = build_strategy_schedule(self.settings.strategies)
        self.strategies = [entry.strategy for entry in self.strategy_schedule]
        self.signal_pipeline.strategies = self.strategies
        self.signal_pipeline.set_strategy_dependencies(
            {entry.name: tuple(entry.depends_on) for entry in self.strategy_schedule}
        )
        known_strategy_names = {entry.name for entry in self.strategy_schedule}
        disabled = self.persistence.read_state("telegram_disabled_strategies", default=[])
        for name in disabled if isinstance(disabled, list) else []:
            if name in known_strategy_names:
                self.signal_pipeline.set_strategy_enabled(str(name), False)
        self.arbiter = SignalArbiter()
        self._trading_components_initialized = True

    def _validate_telegram_startup(self) -> None:
        telegram = self.settings.telegram
        live_publish_enabled = (
            telegram.enabled
            and not telegram.dry_run
            and (
                telegram.send_signals
                or telegram.send_consensus_signals
                or telegram.send_paper_results
                or telegram.send_daily_report
            )
        )
        if not live_publish_enabled:
            return
        missing: list[str] = []
        if not telegram.resolved_bot_token:
            missing.append(telegram.bot_token_env)
        if not telegram.resolved_channel_id:
            missing.append(telegram.channel_id_env)
        if missing:
            raise TelegramStartupConfigError(tuple(missing))
        invalid = invalid_telegram_credential_fields(
            telegram.resolved_bot_token, telegram.resolved_channel_id
        )
        if invalid:
            fields = tuple(
                telegram.bot_token_env if field == "bot_token" else telegram.channel_id_env
                for field in invalid
            )
            raise TelegramStartupConfigError(fields)

    @staticmethod
    def _token_ids_for_markets(markets: list[Market]) -> tuple[str, ...]:
        return scheduler_market_data.token_ids_for_markets(markets)

    async def refresh_markets_once(self) -> None:
        await scheduler_market_data.refresh_markets_once(self)

    async def _fetch_resolved_markets(self) -> None:
        await scheduler_market_data.fetch_resolved_markets(self)

    async def evaluate_once(self) -> list[SignalCandidate]:
        return await scheduler_processing.evaluate_once(self)

    async def _reseed_ws_books(self, token_ids: list[str]) -> None:
        self.book_feed.market_data = self.market_data
        await self.book_feed.reseed(token_ids)

    async def _stop_market_ws_subscription(self) -> None:
        await scheduler_market_data.stop_market_ws_subscription(self)

    async def _sync_market_ws_subscription(self, token_ids: tuple[str, ...]) -> None:
        await scheduler_market_data.sync_market_ws_subscription(self, token_ids)

    async def start_websockets(self) -> list[asyncio.Task]:
        return await scheduler_market_data.start_websockets(self)

    async def stop(self) -> None:
        raise RuntimeError("Legacy scheduler stop disabled in Nautilus mode")

    def _persist_state(self) -> None:
        scheduler_state.persist_state(self)

    async def process_signal(
        self, signal: SignalCandidate
    ):
        raise RuntimeError("Legacy scheduler process_signal disabled in Nautilus mode")

    async def process_accepted_signals(
        self, signals: list[SignalCandidate]
    ):
        raise RuntimeError("Legacy scheduler process_accepted_signals disabled in Nautilus mode")

    async def check_settlements(self) -> list[PaperTradeResult]:
        from polysignal_lab.app.scheduler_reporting import check_settlements

        return await check_settlements(self)

    async def generate_daily_report(self) -> DailyReport | None:
        from polysignal_lab.app.scheduler_reporting import generate_daily_report

        return await generate_daily_report(self)

    async def run(self) -> None:
        raise RuntimeError("Legacy scheduler runtime disabled in Nautilus mode")


async def run_scheduler(
    settings: Settings | None = None, base_dir: str | Path = "."
) -> None:
    from polysignal_lab.config import load_settings
    from polysignal_lab.observability.logger import configure_logging

    settings = settings or load_settings()
    settings.validate_runtime_environment(environ={})
    configure_logging(settings.app.log_level)

    scheduler = PolySignalScheduler(settings, base_dir=base_dir)
    await scheduler.run()
