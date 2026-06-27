"""TradingNode assembly and entry point for the Nautilus runtime mode.

Wires all actors, assemblers, wrappers, and data paths from Tasks 3-12
into a credential-free paper-safe runtime.  No live Polymarket execution,
no private key/env-var reading, no allowance scripts.
"""
from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from polysignal_lab.app import scheduler_market_data
from polysignal_lab.app.scheduler import PolySignalScheduler
from polysignal_lab.config import Settings, load_settings
from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
from polysignal_lab.nautilus_bridge.market_registry import PolymarketMarketRegistry
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.book_data import NautilusBookDataProvider
from polysignal_lab.nautilus_runtime.data_ingestor import NautilusDataIngestor
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor
from polysignal_lab.nautilus_runtime.observability import (
    DecisionPolicyControl,
    NautilusEventStoreAdapter,
    NautilusNotifierAdapter,
    ObservabilityActor,
)
from polysignal_lab.signal_layer.arbiter import SignalArbiter
from polysignal_lab.strategies.execution import build_strategy_schedule
from polysignal_lab.nautilus_runtime.strategies import (
    BinaryMomentumNautilusStrategy,
    DumpHedgeNautilusStrategy,
    FibonacciBotNautilusStrategy,
    LateConsensusNautilusStrategy,
    LowSideDualReversionNautilusStrategy,
    MidPriceSizingNautilusStrategy,
    NinetyNineCentSniperNautilusStrategy,
    OneCentBuyNautilusStrategy,
    PTBDiffNautilusStrategy,
    PolySignalNautilusStrategy,
    PreOrderMarketNautilusStrategy,
    SkewMeanReversionNautilusStrategy,
    VWAPMomentumNautilusStrategy,
)

# Module-level lazy Nautilus type placeholders (testability on py3.11).
# Tests monkeypatch these before lazy import resolves them.
TradingNode = None
PolymarketInstrumentProviderConfig = None
build_paper_trading_node_config = None
register_paper_factories = None

class _NoopMatchingSink:
    """No-op matching sink for the data ingestor when running under TradingNode.

    The Nautilus DataEngine handles its own market feeds; the external data
    ingestor only needs to update the PolySignal book_data_provider for the
    assembler. This sink satisfies the MatchingBookSink protocol without
    duplicating book state into a paper matching client.
    """

    def update_book(self, token_id: str, book: object) -> None:
        pass

    def update_trade(
        self,
        token_id: str,
        price: float,
        size: float,
        side: str | None,
        ts_event: object | None,
    ) -> None:
        pass


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class NautilusRuntimeBundle:
    """Wired runtime components ready for the orchestrator loop."""

    scheduler: PolySignalScheduler
    components: dict[str, Any]
    bridge_registry: PolymarketMarketRegistry
    sidecar: ExternalDataSidecar
    book_data_provider: NautilusBookDataProvider
    data_ingestor: NautilusDataIngestor
    node: Any  # TradingNode
    observability: ObservabilityActor
    websocket_tasks: list[asyncio.Task]


def _ensure_nautilus_imports() -> None:
    """Lazy-import Nautilus TradingNode and Polymarket helpers into module globals.

    Uses module-level placeholders so tests on py3.11 can monkeypatch before
    the first real call triggers the import chain.
    """
    global TradingNode, PolymarketInstrumentProviderConfig
    global build_paper_trading_node_config, register_paper_factories

    if TradingNode is not None:
        return  # already resolved (or monkeypatched)

    from nautilus_trader.live.node import TradingNode as _TradingNode
    from nautilus_trader.adapters.polymarket.providers import PolymarketInstrumentProviderConfig as _PolymarketInstrumentProviderConfig
    from polysignal_lab.nautilus_runtime.trading_node import (
        build_paper_trading_node_config as _build_paper_trading_node_config,
        register_paper_factories as _register_paper_factories,
    )

    TradingNode = _TradingNode
    PolymarketInstrumentProviderConfig = _PolymarketInstrumentProviderConfig
    build_paper_trading_node_config = _build_paper_trading_node_config
    register_paper_factories = _register_paper_factories


def build_trading_node(
    settings: Settings | None = None,
    *,
    condition_ids: Sequence[str] = (),
    store: Any = None,
    wallet: Any = None,
) -> dict[str, Any]:
    """Build the Nautilus-owned paper runtime wiring."""
    if settings is None:
        settings = load_settings()

    _ensure_nautilus_imports()

    instrument_config = PolymarketInstrumentProviderConfig(load_ids=frozenset())
    config = build_paper_trading_node_config(settings, instrument_config=instrument_config)
    node = TradingNode(config=config)
    register_paper_factories(node)

    registry = PolymarketMarketRegistry()
    sidecar = ExternalDataSidecar()
    assembler = MarketViewAssembler(registry=registry, books=None, sidecar=sidecar)
    policy = DecisionPolicyActor()
    strategies = _build_native_strategies(settings, assembler, policy, condition_ids)
    for strategy in strategies:
        node.trader.add_strategy(strategy)
    node.build()

    return {
        "node": node,
        "config": config,
        "registry": registry,
        "sidecar": sidecar,
        "assembler": assembler,
        "policy": policy,
        "strategies": strategies,
        "strategy_names": [strategy.strategy_name for strategy in strategies],
    }


def _build_native_strategies(
    settings: Settings,
    assembler: MarketViewAssembler,
    policy: DecisionPolicyActor,
    condition_ids: Sequence[str],
) -> list:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    strategies: list = []
    strategy_names: set[str] = set()

    for name in settings.strategies.explicit_strategy_names():
        if name in strategy_names:
            continue
        strategy_names.add(name)
        cfg = getattr(settings.strategies, name, None)
        if cfg is None:
            continue

        fixed_stake = float(getattr(cfg, "stake_usdc", None) or getattr(cfg, "basket_notional", 10.0))

        strategy = PolySignalNativeStrategy(
            core=_native_core_for(name, cfg),
            assembler=assembler,
            condition_ids=list(condition_ids),
            strategy_name=name,
            policy=policy,
            fixed_stake_usdc=fixed_stake,
        )
        strategies.append(strategy)

    return strategies


def _native_core_for(name: str, cfg: Any = None):
    """Return the alpha core for a strategy name, or None."""
    # Map strategy names to their AlphaCore classes
    from polysignal_lab.alpha.binary_momentum_core import BinaryMomentumAlphaCore
    from polysignal_lab.alpha.cross_market_core import CrossMarketAlphaCore
    from polysignal_lab.alpha.dump_hedge_core import DumpHedgeAlphaCore
    from polysignal_lab.alpha.fibonacci_core import FibonacciAlphaCore
    from polysignal_lab.alpha.late_consensus_core import LateConsensusAlphaCore
    from polysignal_lab.alpha.low_side_dual_reversion_core import LowSideDualReversionAlphaCore
    from polysignal_lab.alpha.mid_price_sizing_core import MidPriceSizingAlphaCore
    from polysignal_lab.alpha.ninety_nine_cent_sniper_core import NinetyNineCentSniperAlphaCore
    from polysignal_lab.alpha.one_cent_buy_core import OneCentBuyAlphaCore
    from polysignal_lab.alpha.pre_order_market_core import PreOrderMarketAlphaCore
    from polysignal_lab.alpha.ptb_diff_core import PTBDiffAlphaCore
    from polysignal_lab.alpha.skew_mean_reversion_core import SkewMeanReversionAlphaCore
    from polysignal_lab.alpha.vwap_momentum_core import VWAPMomentumAlphaCore
    mapping = {
        "ptb_diff": PTBDiffAlphaCore,
        "skew_mean_reversion": SkewMeanReversionAlphaCore,
        "binary_momentum": BinaryMomentumAlphaCore,
        "fibonacci_bot": FibonacciAlphaCore,
        "one_cent_buy": OneCentBuyAlphaCore,
        "ninety_nine_cent_sniper": NinetyNineCentSniperAlphaCore,
        "late_consensus": LateConsensusAlphaCore,
        "vwap_momentum": VWAPMomentumAlphaCore,
        "dump_hedge": DumpHedgeAlphaCore,
        "mid_price_sizing": MidPriceSizingAlphaCore,
        "pre_order_market": PreOrderMarketAlphaCore,
        "low_side_dual_reversion": LowSideDualReversionAlphaCore,
        "cross_market_bot": CrossMarketAlphaCore,
    }
    cls = mapping.get(name)
    if cls is None:
        return None
    return cls(config=cfg) if cfg is not None else cls()

def _build_wrapper(
    name: str,
    cfg: Any,
    assembler: MarketViewAssembler,
    policy: DecisionPolicyActor,
    paper_client: Any,
    condition_ids: Sequence[str],
) -> PolySignalNautilusStrategy | None:
    """Build a strategy wrapper by name."""
    fixed_stake = float(getattr(cfg, "stake_usdc", None) or getattr(cfg, "basket_notional", 10.0))

    wrapper_kwargs = dict(
        config=cfg,
        assembler=assembler,
        condition_ids=list(condition_ids),
        policy=policy,
        submitter=lambda spec: paper_client.submit_spec(spec),
        fixed_stake_usdc=fixed_stake,
    )

    mapping = {
        "ptb_diff": PTBDiffNautilusStrategy,
        "skew_mean_reversion": SkewMeanReversionNautilusStrategy,
        "binary_momentum": BinaryMomentumNautilusStrategy,
        "fibonacci_bot": FibonacciBotNautilusStrategy,
        "one_cent_buy": OneCentBuyNautilusStrategy,
        "ninety_nine_cent_sniper": NinetyNineCentSniperNautilusStrategy,
        "late_consensus": LateConsensusNautilusStrategy,
        "vwap_momentum": VWAPMomentumNautilusStrategy,
        "dump_hedge": DumpHedgeNautilusStrategy,
        "mid_price_sizing": MidPriceSizingNautilusStrategy,
        "pre_order_market": PreOrderMarketNautilusStrategy,
        "low_side_dual_reversion": LowSideDualReversionNautilusStrategy,
    }
    cls = mapping.get(name)
    if cls is None:
        logger.warning("no nautilus wrapper for strategy %s", name)
        return None
    return cls(**wrapper_kwargs)


def build_control(policy: DecisionPolicyActor) -> DecisionPolicyControl:
    """Build a StrategyControl adapter from a DecisionPolicyActor."""
    return DecisionPolicyControl(policy)

def _initialize_nautilus_scheduler_components(scheduler: PolySignalScheduler) -> None:
    """Initialize scheduler state needed by Nautilus without legacy local paper."""
    from polysignal_lab.paper.exit_engine import PaperExitEngine
    from polysignal_lab.paper.settlement import PaperSettlementEngine
    from polysignal_lab.paper.wallet import PaperWallet
    if scheduler._trading_components_initialized:
        return
    scheduler.strategy_schedule = build_strategy_schedule(scheduler.settings.strategies)
    scheduler.strategies = [entry.strategy for entry in scheduler.strategy_schedule]
    scheduler.signal_pipeline.strategies = scheduler.strategies
    scheduler.signal_pipeline.set_strategy_dependencies(
        {entry.name: tuple(entry.depends_on) for entry in scheduler.strategy_schedule}
    )
    known_strategy_names = {entry.name for entry in scheduler.strategy_schedule}
    disabled = scheduler.persistence.read_state("telegram_disabled_strategies", default=[])
    for name in disabled if isinstance(disabled, list) else []:
        if name in known_strategy_names:
            scheduler.signal_pipeline.set_strategy_enabled(str(name), False)
    scheduler.arbiter = SignalArbiter()
    scheduler.wallet = PaperWallet(scheduler.settings.paper_trading.starting_balance_usdc)
    scheduler.paper = None
    scheduler.exits = PaperExitEngine(scheduler.settings.paper_trading.exit_model, scheduler.wallet)
    scheduler.settlement = PaperSettlementEngine(scheduler.wallet)
    scheduler.paper_portfolio.configure(
        wallet=scheduler.wallet,
        paper=None,
        exits=scheduler.exits,
        settlement=scheduler.settlement,
        markets=scheduler.ctx.markets,
        books=scheduler.ctx.books,
        persistence=scheduler.persistence,
    )
    scheduler._trading_components_initialized = True


async def build_nautilus_runtime(settings: Settings | None = None) -> NautilusRuntimeBundle:
    """Build and wire the complete Nautilus runtime with a PolySignal-owned scheduler."""
    if settings is None:
        settings = load_settings()

    scheduler = PolySignalScheduler(settings)
    _initialize_nautilus_scheduler_components(scheduler)
    await scheduler_market_data.refresh_markets_once(scheduler)

    book_data_provider = NautilusBookDataProvider(scheduler.ctx.books)

    condition_ids = tuple(m.condition_id for m in scheduler.ctx.markets.active())
    components = build_trading_node(
        settings,
        condition_ids=condition_ids,
    )

    # Wire real book data provider into the assembler
    components["assembler"].books = book_data_provider

    data_ingestor = NautilusDataIngestor(
        markets=scheduler.ctx.markets,
        books=scheduler.ctx.books,
        spots=scheduler.ctx.spots,
        bridge_registry=components["registry"],
        sidecar=components["sidecar"],
        book_data_provider=book_data_provider,
        matching_client=_NoopMatchingSink(),
        price_to_beat_provider=scheduler.ptb,
    )

    observability = ObservabilityActor(
        health=scheduler.health,
        store=NautilusEventStoreAdapter(scheduler.persistence),
        notifier=NautilusNotifierAdapter(scheduler.publisher),
    )

    websocket_tasks = await scheduler_market_data.start_websockets(scheduler)

    return NautilusRuntimeBundle(
        scheduler=scheduler,
        components=components,
        bridge_registry=components["registry"],
        sidecar=components["sidecar"],
        book_data_provider=book_data_provider,
        data_ingestor=data_ingestor,
        node=components["node"],
        observability=observability,
        websocket_tasks=websocket_tasks,
    )


async def _data_sync_loop(
    data_ingestor: Any,
    *,
    refresh_interval_sec: float,
    stop_event: asyncio.Event,
) -> None:
    """Periodically sync market data into the bridge registry and assembler."""
    while not stop_event.is_set():
        try:
            data_ingestor.sync_all()
        except Exception:
            logger.exception("data sync error")
        await asyncio.sleep(refresh_interval_sec)


async def run_nautilus_cli_async(settings: Settings | None = None,
                                 stop_event: asyncio.Event | None = None) -> None:
    """Run the Nautilus CLI with async orchestrator loop and signal handling."""
    event = stop_event or asyncio.Event()
    bundle = await build_nautilus_runtime(settings)
    try:
        refresh_interval_sec = bundle.scheduler.settings.markets.refresh_interval_sec
    except AttributeError:
        refresh_interval_sec = 60

    node = bundle.node
    loop = asyncio.get_running_loop()

    def request_stop() -> None:
        event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, request_stop)
        except (NotImplementedError, RuntimeError):
            signal.signal(sig, lambda _signum, _frame: request_stop())

    sync_task = asyncio.create_task(
        _data_sync_loop(bundle.data_ingestor, refresh_interval_sec=refresh_interval_sec, stop_event=event),
    )

    try:
        print(f"Nautilus runtime ready — {len(bundle.components['strategies'])} strategies")
        run_task = asyncio.create_task(asyncio.to_thread(node.run))
        stop_waiter = asyncio.create_task(event.wait())
        done, pending = await asyncio.wait(
            [run_task, stop_waiter],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    finally:
        event.set()
        sync_task.cancel()
        try:
            await sync_task
        except asyncio.CancelledError:
            pass
        dispose = getattr(node, "dispose", None)
        if callable(dispose):
            dispose()
        await bundle.scheduler.stop()


def run_nautilus_cli(settings: Settings | None = None) -> None:
    """Entry point for the ``nautilus`` CLI mode — sync wrapper."""
    asyncio.run(run_nautilus_cli_async(settings))


def main() -> int:
    """``polysignal-nautilus`` script entry point."""
    try:
        run_nautilus_cli()
    except RuntimeError as exc:
        print(f"nautilus: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
