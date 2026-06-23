from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path

from polysignal_lab.app import (
    scheduler_market_data,
    scheduler_processing,
    scheduler_reporting,
    scheduler_runtime,
    scheduler_state,
)
from polysignal_lab.config import Settings
from polysignal_lab.data.binance_spot_ws import BinanceSpotFeed
from polysignal_lab.data.market_snapshot import MarketSnapshotBuilder
from polysignal_lab.data.polymarket_clob_rest import PolymarketCLOBRestClient
from polysignal_lab.data.polymarket_clob_ws import PolymarketMarketWebSocket
from polysignal_lab.data.polymarket_market_discovery import MarketDiscovery
from polysignal_lab.data.price_to_beat_provider import PriceToBeatProvider
from polysignal_lab.data.state import MarketRegistry, OrderBookRegistry, SpotRegistry
from polysignal_lab.domain.market import Market
from polysignal_lab.domain.paper_result import DailyReport, PaperTradeResult
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.paper.exit_engine import PaperExitEngine
from polysignal_lab.paper.settlement import PaperSettlementEngine
from polysignal_lab.paper.simulator import PaperSimulator
from polysignal_lab.paper.wallet import PaperWallet
from polysignal_lab.publish.telegram_publisher import (
    TelegramPublisher,
    invalid_telegram_credential_fields,
)
from polysignal_lab.signal_layer.consensus import ConsensusEngine
from polysignal_lab.signal_layer.formatter import MessageFormatter
from polysignal_lab.signal_layer.gate import SignalGate
from polysignal_lab.storage.jsonl_store import JSONLStore
from polysignal_lab.storage.sqlite_store import SQLiteStore
from polysignal_lab.storage.state_store import StateStore
from polysignal_lab.strategies.factory import build_strategies


from polysignal_lab.domain.paper_order import PaperFill, PaperOrder
from polysignal_lab.domain.enums import Side
from polysignal_lab.strategies.base import BaseStrategy


def _make_fill_notifier(strategies: list[BaseStrategy]) -> object:
    """Create a callback that notifies strategies when paper fills/cancels occur."""
    def notify(order: PaperOrder, event: str, fill: PaperFill | None = None, pair_id: str | None = None) -> None:
        for strat in strategies:
            if not hasattr(strat, "name") or strat.name != order.strategy:
                continue
            if event == "filled" and fill is not None:
                strat.notify_fill(order.market_id, order.side, fill.fill_price, fill.shares)
            elif event == "cancelled":
                strat.notify_cancel(order.market_id, order.side, order.reject_reason or "GTD_EXPIRED")
            elif event == "leg_failed" and pair_id is not None:
                strat.notify_leg_failure(pair_id, order.market_id, order.side)

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


class PolySignalScheduler:
    def __init__(self, settings: Settings, base_dir: str | Path = "."):
        self.settings = settings
        self.ctx = ServiceContext(settings=settings)
        self.discovery = MarketDiscovery(settings.data.polymarket, settings.markets)
        self.rest = PolymarketCLOBRestClient(settings.data.polymarket)
        self.ptb = PriceToBeatProvider(use_crypto_price_api=settings.data.polymarket.use_crypto_price_api)
        self.snapshot_builder = MarketSnapshotBuilder(self.ctx.books, self.ctx.spots, self.ptb)
        self.gate = SignalGate(settings.signal, settings.data.polymarket, settings.data.binance)
        self.consensus = ConsensusEngine(
            settings.signal.consensus_window_sec, settings.signal.consensus_enabled
        )
        self.formatter = MessageFormatter(settings.telegram.max_message_chars)
        self.publisher = TelegramPublisher(settings.telegram)
        self.logger = logging.getLogger("polysignal_lab.scheduler")
        self._trading_components_initialized = False

        self.poly_ws = PolymarketMarketWebSocket(settings.data.polymarket, self.ctx.books)
        self.binance_ws = BinanceSpotFeed(settings.data.binance, self.ctx.spots)

        base = Path(base_dir)
        self.logs = JSONLStore(base / settings.storage.jsonl_dir)
        self.state = StateStore(base / settings.storage.state_dir)
        self.sqlite = SQLiteStore(base / settings.storage.sqlite_path)

        self._ws_tasks: list[asyncio.Task] = []
        self._market_ws_task: asyncio.Task | None = None
        self._binance_ws_task: asyncio.Task | None = None
        self._latest_market_token_ids: tuple[str, ...] = ()
        self._market_ws_token_ids: tuple[str, ...] = ()
        self._market_refresh_completed = False
        self._streams_started = False
        self._running = False

    def _initialize_trading_components(self) -> None:
        if self._trading_components_initialized:
            return
        self.strategies = build_strategies(self.settings.strategies)
        self.wallet = PaperWallet(self.settings.paper_trading.starting_balance_usdc)
        self.paper = PaperSimulator(
            self.settings.paper_trading, self.settings.data.polymarket, self.wallet
        )
        self.paper.fill_notifier = _make_fill_notifier(self.strategies)
        self.exits = PaperExitEngine(self.settings.paper_trading.exit_model, self.wallet)
        self.settlement = PaperSettlementEngine(self.wallet)
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

    async def _restore_wallet_state(self) -> None:
        await scheduler_state.restore_wallet_state(self)

    async def refresh_markets_once(self) -> None:
        await scheduler_market_data.refresh_markets_once(self)

    async def _fetch_resolved_markets(self) -> None:
        await scheduler_market_data.fetch_resolved_markets(self)

    async def evaluate_once(self) -> list[SignalCandidate]:
        return await scheduler_processing.evaluate_once(self)

    async def _stop_market_ws_subscription(self) -> None:
        await scheduler_market_data.stop_market_ws_subscription(self)

    async def _sync_market_ws_subscription(self, token_ids: tuple[str, ...]) -> None:
        await scheduler_market_data.sync_market_ws_subscription(self, token_ids)

    async def start_websockets(self) -> list[asyncio.Task]:
        return await scheduler_market_data.start_websockets(self)

    async def stop(self) -> None:
        await scheduler_runtime.stop(self)

    def _persist_state(self) -> None:
        scheduler_state.persist_state(self)

    async def process_signal(
        self, signal: SignalCandidate
    ) -> scheduler_processing.ProcessSignalResult:
        return await scheduler_processing.process_signal(self, signal)

    async def process_accepted_signals(
        self, signals: list[SignalCandidate]
    ) -> scheduler_processing.AcceptedSignalSummary:
        return await scheduler_processing.process_accepted_signals(self, signals)

    async def check_settlements(self) -> list[PaperTradeResult]:
        return await scheduler_reporting.check_settlements(self)

    async def generate_daily_report(self) -> DailyReport | None:
        return await scheduler_reporting.generate_daily_report(self)

    async def run(self) -> None:
        await scheduler_runtime.run(self)


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
