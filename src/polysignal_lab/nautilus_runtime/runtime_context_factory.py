"""
Input: __future__, collections.abc, logging, pathlib, typing, polysignal_lab.config, polysignal_lab.app.services, polysignal_lab.domain, polysignal_lab.reporting
Output: NautilusRuntimeContext, build_nautilus_runtime_context
Pos: Nautilus runtime service context factory — replaces legacy PolySignalScheduler DI

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

if TYPE_CHECKING:
    from polysignal_lab.domain.reporting_result import DailyReport

from polysignal_lab.app.services.market_universe_service import MarketUniverseService
from polysignal_lab.app.services.persistence_service import PersistenceService
from polysignal_lab.app.services.publish_service import PublishService
from polysignal_lab.config import Settings
from polysignal_lab.data.polymarket_market_discovery import MarketDiscovery
from polysignal_lab.data.state import MarketRegistry
from polysignal_lab.domain.market import Market
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.observability.health import HealthRegistry
from polysignal_lab.storage.event_projection import report_token_id
from polysignal_lab.publish.telegram_publisher import PublishResult, TelegramPublisher
from polysignal_lab.signal_layer.formatter import MessageFormatter
from polysignal_lab.storage.jsonl_store import JSONLStore
from polysignal_lab.storage.sqlite_store import SQLiteStore
from polysignal_lab.storage.state_store import StateStore


SPOT_DEPENDENT_NATIVE_STRATEGIES: Final = frozenset(
    {
        "binary_momentum",
        "cross_market_bot",
        "dump_hedge",
        "fibonacci_bot",
        "late_consensus",
        "low_side_dual_reversion",
        "mid_price_sizing",
        "ninety_nine_cent_sniper",
        "one_cent_buy",
        "pre_order_market",
        "ptb_diff",
        "skew_mean_reversion",
        "vwap_momentum",
    }
)


SUPPORTED_NATIVE_SPOT_SOURCES: Final = frozenset({"disabled", "polymarket_rtds"})


def validate_native_runtime_settings(settings: Settings) -> None:
    """Reject native strategies without a managed spot-data ingress."""
    spot_source = str(settings.runtime.nautilus.sidecar.spot_source).strip().lower()
    if spot_source not in SUPPORTED_NATIVE_SPOT_SOURCES:
        raise RuntimeError(
            f"unsupported native spot source: {spot_source!r}; "
            "expected 'disabled' or 'polymarket_rtds'"
        )
    if spot_source != "disabled":
        return

    unavailable = tuple(
        name
        for name in settings.strategies.explicit_strategy_names()
        if name in SPOT_DEPENDENT_NATIVE_STRATEGIES
        and bool(getattr(settings.strategies, name).enabled)
    )
    if unavailable:
        names = ", ".join(unavailable)
        raise RuntimeError(
            "Nautilus native runtime has enabled spot-dependent strategies "
            f"({names}) but no managed spot data ingress; configure a Nautilus "
            "spot data client before starting the runtime"
        )


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
        books=None,
        markets=markets,
        formatter=formatter,
    )


def _market_for_report_event(
    markets: MarketRegistry,
    row: Mapping[str, object],
) -> Market | None:
    metrics = row.get("metrics")
    metric_values = metrics if isinstance(metrics, Mapping) else {}
    market_id = str(row.get("market_id") or metric_values.get("market_id") or "")
    if market_id:
        market = markets.get(market_id)
        if market is not None:
            return market
    token_id = report_token_id(row)
    return markets.for_token(token_id) if token_id else None


def _build_publish_service(
    settings: Settings,
    formatter: MessageFormatter,
    persistence: PersistenceService,
    markets: MarketRegistry,
) -> tuple[PublishService, TelegramPublisher]:
    publisher = TelegramPublisher(settings.telegram)
    publish_service = PublishService(
        formatter,
        publisher,
        persistence,
        timeout_sec=settings.telegram.publish_timeout_sec,
        market_lookup=lambda row: _market_for_report_event(markets, row),
    )
    return publish_service, publisher


@dataclass(slots=True)
class NautilusRuntimeContext:
    """Services needed by the Nautilus runtime path."""

    settings: Settings
    market_universe: MarketUniverseService
    markets: MarketRegistry
    health: HealthRegistry
    persistence: PersistenceService
    formatter: MessageFormatter
    publisher: TelegramPublisher
    publish_service: PublishService
    sqlite: SQLiteStore
    discovery: MarketDiscovery
    logger: logging.Logger
    # Runtime state bag (mutable)
    nautilus_cache: object | None = None
    nautilus_portfolio: object | None = None
    market_catalog: object | None = None
    telegram_bot: object | None = None
    execution_metadata: object | None = None
    strategy_schedule: object | None = None
    strategies: object | None = None
    arbiter: object | None = None
    _running: bool = False
    _nautilus_runtime_owned_by_live_node: bool = False

    async def publish_signal_once(
        self,
        signal: SignalCandidate,
        stake_usdc: float,
    ) -> PublishResult:
        publish_service, publisher = _build_publish_service(
            self.settings,
            self.formatter,
            self.persistence,
            self.markets,
        )
        try:
            return cast(
                PublishResult,
                await publish_service.publish_signal(signal, stake_usdc),
            )
        finally:
            await publisher.client.aclose()

    async def generate_daily_report(self) -> DailyReport | None:
        from polysignal_lab.app.reporting import generate_daily_report

        return await generate_daily_report(self)


def build_nautilus_runtime_context(
    settings: Settings,
    base_dir: str | Path = '.',
) -> NautilusRuntimeContext:
    """Build the services needed by the Nautilus runtime path."""
    validate_native_runtime_settings(settings)
    markets = MarketRegistry()
    formatter = MessageFormatter(settings.telegram.max_message_chars)
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
    publish_service, publisher = _build_publish_service(
        settings,
        formatter,
        persistence,
        markets,
    )
    telegram_bot = _maybe_create_telegram_bot(settings, persistence, markets, formatter)
    return NautilusRuntimeContext(
        settings=settings,
        market_universe=market_universe,
        markets=markets,
        health=health,
        persistence=persistence,
        formatter=formatter,
        publisher=publisher,
        publish_service=publish_service,
        sqlite=sqlite,
        discovery=discovery,
        logger=runtime_logger,
        telegram_bot=telegram_bot,
    )
