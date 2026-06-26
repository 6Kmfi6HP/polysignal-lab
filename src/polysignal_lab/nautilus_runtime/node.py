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
from polysignal_lab.paper.exit_engine import PaperExitEngine
from polysignal_lab.config import Settings, load_settings
from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
from polysignal_lab.nautilus_bridge.market_registry import PolymarketMarketRegistry
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.book_data import NautilusBookDataProvider
from polysignal_lab.nautilus_runtime.data_ingestor import NautilusDataIngestor
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor
from polysignal_lab.nautilus_runtime.matching import NautilusMatchingPaperExecutionClient
from polysignal_lab.nautilus_runtime.group_views import MarketGroupViewAssembler
from polysignal_lab.nautilus_runtime.observability import (
    DecisionPolicyControl,
    NautilusEventStoreAdapter,
    NautilusNotifierAdapter,
    ObservabilityActor,
)
from polysignal_lab.nautilus_runtime.orchestrator import NautilusOrchestrator
from polysignal_lab.nautilus_runtime.position_policy import PositionPolicyActor
from polysignal_lab.nautilus_runtime.settlement import SettlementActor
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
from polysignal_lab.paper.settlement import PaperSettlementEngine
from polysignal_lab.paper.wallet import PaperWallet

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
    paper_client: NautilusMatchingPaperExecutionClient
    observability: ObservabilityActor
    orchestrator: NautilusOrchestrator
    websocket_tasks: list[asyncio.Task]


def build_trading_node(
    settings: Settings | None = None,
    *,
    condition_ids: Sequence[str] = (),
    store: Any = None,
    wallet: PaperWallet | None = None,
) -> dict[str, Any]:
    """Build the Nautilus paper runtime wiring as a component dict.

    Returns a dict of wired components (no Nautilus TradingNode dependency).
    Callers use the components directly for the default paper-safe mode.
    """
    if settings is None:
        settings = load_settings()

    # -- Data infrastructure --
    registry = PolymarketMarketRegistry()
    sidecar = ExternalDataSidecar()
    assembler = MarketViewAssembler(registry=registry, books=None, sidecar=sidecar)
    group_assembler = MarketGroupViewAssembler()

    # -- Wallet & execution --
    wallet = wallet or PaperWallet(
        starting_balance=settings.paper_trading.starting_balance_usdc
    )
    paper_client = NautilusMatchingPaperExecutionClient(
        wallet=wallet,
        accuracy_mode=settings.runtime.nautilus.matching_accuracy_mode,
        max_book_staleness_ms=settings.data.polymarket.max_book_staleness_ms,
    )

    # -- Decision policy --
    policy = DecisionPolicyActor()

    # -- Position & settlement --
    position_policy = PositionPolicyActor(settings.paper_trading.exit_model, wallet=wallet)
    settlement_engine = PaperSettlementEngine(wallet)
    settlement_actor = SettlementActor(
        settlement_engine=settlement_engine,
        wallet=wallet,
        logger=logger,
    )

    # -- Observability --
    observability = ObservabilityActor(health=None, notifier=None)

    # -- Strategy wrappers --
    strategies: list[PolySignalNautilusStrategy] = []
    strategy_names = set()

    for name in settings.strategies.explicit_strategy_names():
        if name in strategy_names:
            continue
        strategy_names.add(name)
        cfg = getattr(settings.strategies, name, None)
        if cfg is None:
            continue

        wrapper = _build_wrapper(name, cfg, assembler, policy, paper_client, condition_ids)
        if wrapper is not None:
            strategies.append(wrapper)

    return {
        "registry": registry,
        "sidecar": sidecar,
        "assembler": assembler,
        "group_assembler": group_assembler,
        "wallet": wallet,
        "paper_client": paper_client,
        "policy": policy,
        "position_policy": position_policy,
        "settlement_actor": settlement_actor,
        "observability": observability,
        "strategies": strategies,
        "strategy_names": sorted(strategy_names),
    }


def _build_wrapper(
    name: str,
    cfg: Any,
    assembler: MarketViewAssembler,
    policy: DecisionPolicyActor,
    paper_client: NautilusMatchingPaperExecutionClient,
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
        wallet=scheduler.wallet,
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
        matching_client=components["paper_client"],
        price_to_beat_provider=scheduler.ptb,
    )

    observability = ObservabilityActor(
        health=scheduler.health,
        store=NautilusEventStoreAdapter(scheduler.persistence),
        notifier=NautilusNotifierAdapter(scheduler.publisher),
    )

    websocket_tasks = await scheduler_market_data.start_websockets(scheduler)

    orchestrator = NautilusOrchestrator(
        scheduler=scheduler,
        registered_strategies=components["strategies"],
        data_ingestor=data_ingestor,
        book_data_provider=book_data_provider,
        paper_client=components["paper_client"],
        position_policy=components["position_policy"],
        settlement_actor=components["settlement_actor"],
        observability=observability,
        health=scheduler.health,
        refresh_interval_sec=settings.markets.refresh_interval_sec,
    )

    return NautilusRuntimeBundle(
        scheduler=scheduler,
        components=components,
        bridge_registry=components["registry"],
        sidecar=components["sidecar"],
        book_data_provider=book_data_provider,
        data_ingestor=data_ingestor,
        paper_client=components["paper_client"],
        observability=observability,
        orchestrator=orchestrator,
        websocket_tasks=websocket_tasks,
    )


async def run_nautilus_cli_async(settings: Settings | None = None,
                                 stop_event: asyncio.Event | None = None) -> None:
    """Run the Nautilus CLI with async orchestrator loop and signal handling."""
    event = stop_event or asyncio.Event()
    bundle = await build_nautilus_runtime(settings)
    loop = asyncio.get_running_loop()

    def request_stop() -> None:
        bundle.orchestrator.stop()
        event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, request_stop)
        except (NotImplementedError, RuntimeError):
            signal.signal(sig, lambda _signum, _frame: request_stop())

    try:
        paper_client = bundle.components["paper_client"]
        await bundle.observability.notify_startup(
            [s.strategy_name for s in bundle.components["strategies"]],
            paper_engine=paper_client.paper_engine,
            accuracy_mode=paper_client.accuracy_mode,
        )
        await bundle.orchestrator.run(event)
    finally:
        request_stop()
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
