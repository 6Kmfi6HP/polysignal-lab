"""
Input: __future__, __future__.annotations, logging, dataclasses, dataclasses.dataclass, pathlib, pathlib.Path, typing, typing.TYPE_CHECKING, typing.Final
Output: validate_native_runtime_settings, build_nautilus_runtime_context, NautilusRuntimeContext
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

if TYPE_CHECKING:
    from polysignal_lab.domain.reporting_result import DailyReport

from polysignal_lab.app.services.persistence_service import PersistenceService
from polysignal_lab.app.services.publish_service import PublishService
from polysignal_lab.config import Settings
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.observability.health import HealthRegistry
from polysignal_lab.publish.telegram_publisher import PublishResult, TelegramPublisher
from polysignal_lab.signal_layer.formatter import MessageFormatter
from polysignal_lab.storage.jsonl_store import JSONLStore
from polysignal_lab.storage.sqlite_store import SQLiteStore
from polysignal_lab.storage.state_store import StateStore


SPOT_DEPENDENT_NATIVE_STRATEGIES: Final = frozenset(
    {
        "binary_momentum",
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
    spot_source = str(settings.runtime.nautilus.spot_data.source).strip().lower()
    if spot_source not in SUPPORTED_NATIVE_SPOT_SOURCES:
        raise RuntimeError(
            f"unsupported native spot source: {spot_source!r}; "
            "expected 'disabled' or 'polymarket_rtds'"
        )
    if settings.telegram.interactive_enabled:
        raise RuntimeError(
            "interactive Telegram control is unavailable in the Nautilus-native runtime"
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


def _build_publish_service(
    settings: Settings,
    formatter: MessageFormatter,
    persistence: PersistenceService,
) -> tuple[PublishService, TelegramPublisher]:
    publisher = TelegramPublisher(settings.telegram)
    publish_service = PublishService(
        formatter,
        publisher,
        persistence,
        timeout_sec=settings.telegram.publish_timeout_sec,
    )
    return publish_service, publisher


@dataclass(slots=True)
class NautilusRuntimeContext:
    """Services needed by the Nautilus runtime path."""

    settings: Settings
    health: HealthRegistry
    persistence: PersistenceService
    formatter: MessageFormatter
    publisher: TelegramPublisher
    publish_service: PublishService
    sqlite: SQLiteStore
    logger: logging.Logger
    _running: bool = False

    async def publish_signal_once(
        self,
        signal: SignalCandidate,
        stake_usdc: float,
    ) -> PublishResult:
        publish_service, publisher = _build_publish_service(
            self.settings,
            self.formatter,
            self.persistence,
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
    formatter = MessageFormatter(settings.telegram.max_message_chars)
    health = HealthRegistry()
    base = Path(base_dir)
    logs = JSONLStore(base / settings.storage.jsonl_dir)
    state = StateStore(base / settings.storage.state_dir)
    sqlite = SQLiteStore(base / settings.storage.sqlite_path)
    persistence = PersistenceService(logs, sqlite, state)
    runtime_logger = logging.getLogger('polysignal_lab.runtime')
    publish_service, publisher = _build_publish_service(
        settings,
        formatter,
        persistence,
    )
    return NautilusRuntimeContext(
        settings=settings,
        health=health,
        persistence=persistence,
        formatter=formatter,
        publisher=publisher,
        publish_service=publish_service,
        sqlite=sqlite,
        logger=runtime_logger,
    )
