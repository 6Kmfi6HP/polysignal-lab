"""
Input: __future__, logging, pathlib, polysignal_lab.config, polysignal_lab.app.services
Output: NautilusRuntimeContext, build_nautilus_runtime_context
Pos: Nautilus runtime service context factory — replaces legacy PolySignalScheduler DI

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polysignal_lab.domain.paper_result import DailyReport

from polysignal_lab.app.services.market_universe_service import MarketUniverseService
from polysignal_lab.app.services.persistence_service import PersistenceService
from polysignal_lab.app.services.publish_service import PublishService
from polysignal_lab.config import Settings
from polysignal_lab.data.polymarket_market_discovery import MarketDiscovery
from polysignal_lab.data.state import MarketRegistry, OrderBookRegistry
from polysignal_lab.observability.health import HealthRegistry
from polysignal_lab.paper.settlement_resolver import SettlementResolver
from polysignal_lab.publish.telegram_publisher import TelegramPublisher
from polysignal_lab.signal_layer.formatter import MessageFormatter
from polysignal_lab.storage.jsonl_store import JSONLStore
from polysignal_lab.storage.sqlite_store import SQLiteStore
from polysignal_lab.storage.state_store import StateStore


class _PlaceholderStrategyControl:
    """No-op control until ``_build_nautilus_runtime_bundle`` binds DecisionPolicyControl."""

    def set_strategy_enabled(self, name: str, enabled: bool) -> None:
        _ = (name, enabled)

    def is_strategy_enabled(self, name: str) -> bool:
        _ = name
        return True

    def status_payload(self) -> dict[str, object]:
        return {"disabled_strategies": []}

    def skip_reason_for(self, name: str) -> str | None:
        _ = name
        return None


def _strategy_names_from_settings(settings: Settings) -> list[str]:
    return [name for name in settings.strategies.explicit_strategy_names()]


def _maybe_create_telegram_bot(
    settings: Settings,
    persistence: PersistenceService,
    markets: MarketRegistry,
    formatter: MessageFormatter,
) -> object | None:
    if not settings.telegram.interactive_enabled:
        return None
    from polysignal_lab.publish.telegram_bot import TelegramBotService

    return TelegramBotService(
        config=settings.telegram,
        persistence=persistence,
        strategy_control=_PlaceholderStrategyControl(),
        strategy_names=_strategy_names_from_settings(settings),
        books=OrderBookRegistry(),
        markets=markets,
        formatter=formatter,
    )


def _build_settlement_resolver(settings: Settings, logger: logging.Logger) -> SettlementResolver:
    from polysignal_lab.data.ctf_resolution_client import CtfResolutionClient
    from polysignal_lab.data.gamma_resolution_client import GammaResolutionClient
    from polysignal_lab.paper.settlement_sources import WsResolutionCache

    settlement = settings.data.polymarket.settlement
    chain = None
    polygon_rpc_url = settlement.polygon_rpc_url.strip()
    if settlement.chain_enabled and polygon_rpc_url:
        chain = CtfResolutionClient(
            polygon_rpc_url,
            timeout_sec=settlement.chain_timeout_sec,
            contract="0x4D97DCd97eC945f40cF65F87097ACe5EA0476045",
        )
    gamma = (
        GammaResolutionClient(settings.data.polymarket.gamma_base_url)
        if settlement.gamma_enabled
        else None
    )
    ws_cache = WsResolutionCache() if settlement.ws_enabled else None
    return SettlementResolver(chain, gamma, ws_cache, logger=logger)


@dataclass(slots=True)
class NautilusRuntimeContext:
    """Services needed by the Nautilus runtime path."""

    settings: Settings
    market_universe: MarketUniverseService
    markets: MarketRegistry
    health: HealthRegistry
    persistence: PersistenceService
    publisher: TelegramPublisher
    publish_service: PublishService
    sqlite: SQLiteStore
    discovery: MarketDiscovery
    logger: logging.Logger
    settlement_resolver: SettlementResolver

    # Runtime state bag (mutable)
    nautilus_cache: object | None = None
    nautilus_portfolio: object | None = None
    telegram_bot: object | None = None
    paper_execution_metadata: object | None = None
    strategy_schedule: object | None = None
    strategies: object | None = None
    arbiter: object | None = None
    _running: bool = False
    _nautilus_runtime_owned_by_live_node: bool = False

    async def generate_daily_report(self) -> DailyReport | None:
        from polysignal_lab.app.scheduler_reporting import generate_daily_report

        return await generate_daily_report(self)


def build_nautilus_runtime_context(
    settings: Settings,
    base_dir: str | Path = '.',
) -> NautilusRuntimeContext:
    """Build the services needed by the Nautilus runtime path."""
    markets = MarketRegistry()
    formatter = MessageFormatter(settings.telegram.max_message_chars)
    publisher = TelegramPublisher(settings.telegram)
    health = HealthRegistry()
    discovery = MarketDiscovery(settings.data.polymarket, settings.markets)
    base = Path(base_dir)
    logs = JSONLStore(base / settings.storage.jsonl_dir)
    state = StateStore(base / settings.storage.state_dir)
    sqlite = SQLiteStore(base / settings.storage.sqlite_path)
    persistence = PersistenceService(logs, sqlite, state)
    runtime_logger = logging.getLogger('polysignal_lab.runtime')
    market_universe = MarketUniverseService(
        discovery,
        markets,
        persistence,
        settings=settings,
        logger=runtime_logger,
    )
    publish_service = PublishService(
        formatter,
        publisher,
        persistence,
        timeout_sec=settings.telegram.publish_timeout_sec,
    )
    telegram_bot = _maybe_create_telegram_bot(settings, persistence, markets, formatter)
    settlement_resolver = _build_settlement_resolver(settings, runtime_logger)
    return NautilusRuntimeContext(
        settings=settings,
        market_universe=market_universe,
        markets=markets,
        health=health,
        persistence=persistence,
        publisher=publisher,
        publish_service=publish_service,
        sqlite=sqlite,
        discovery=discovery,
        logger=runtime_logger,
        telegram_bot=telegram_bot,
        settlement_resolver=settlement_resolver,
    )
