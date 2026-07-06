"""TradingNode assembly and entry point for the Nautilus runtime mode.

Wires all actors, assemblers, wrappers, and data paths from Tasks 3-12
into a credential-free paper-safe runtime.  No live Polymarket execution,
no private key/env-var reading, no allowance scripts.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

UTC = timezone.utc
import asyncio
import atexit
import inspect
import importlib
import logging
import signal
import threading
import traceback
from contextlib import suppress
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace, TracebackType
from typing import Protocol, cast, runtime_checkable

from polysignal_lab.alpha.types import AlphaCore, TradeView
from polysignal_lab.app.scheduler import PolySignalScheduler
from polysignal_lab.app import scheduler_health
from polysignal_lab.app.services.publish_service import PublishService
from polysignal_lab.data.anchor_price_service import AnchorPriceStore
from polysignal_lab.config import Settings, load_settings
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.market import Market
from polysignal_lab.publish.telegram_publisher import TelegramPublisher
from polysignal_lab.nautilus_runtime.custom_data_state import StrategyCustomDataState
from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog, MarketPairMeta
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor
from polysignal_lab.nautilus_runtime.observability import (
    DecisionPolicyControl,
    NautilusEventStoreAdapter,
    NautilusNotifierAdapter,
    ObservabilityActor,
)
from polysignal_lab.signal_layer.arbiter import SignalArbiter
from polysignal_lab.signal_layer.consensus import ConsensusEngine
from polysignal_lab.signal_layer.gate import SignalGate
from polysignal_lab.observability.runtime_health import (
    write_runtime_heartbeat,
    write_runtime_startup_marker,
)
from polysignal_lab.strategies.execution import build_strategy_schedule

class _TraderLike(Protocol):
    def add_actor(self, actor: object) -> None: ...
    def add_strategy(self, strategy: object) -> None: ...

@runtime_checkable
class _Disposable(Protocol):
    def dispose(self) -> None: ...


class _TradingNodeLike(Protocol):
    trader: _TraderLike

    def build(self) -> None: ...
    def run(self) -> None: ...




class _NativeStrategyLike(Protocol):
    strategy_name: str


class _PublishResultLike(Protocol):
    def as_dict(self) -> dict[str, str | None]: ...


class _PublishServiceLike(Protocol):
    formatter: object
    persistence: object
    timeout_sec: float

    async def publish_signal(
        self,
        signal: SignalCandidate,
        stake_usdc: float,
    ) -> _PublishResultLike: ...


class _InteractiveBotLike(Protocol):
    async def start(self) -> object: ...
    async def stop(self) -> object: ...

class _EmptyBookDataProvider:
    def book_for_token(self, token_id: str) -> None:
        _ = token_id
        return None

    def trades_for_token(self, token_id: str) -> tuple[TradeView, ...]:
        _ = token_id
        return ()


# Stub placeholders — _ensure_nautilus_imports() overwrites them at runtime.
LiveNode: object | None = None
PolymarketInstrumentProviderConfig: Callable[..., object] = SimpleNamespace
NautilusActor: type[object] | None = None
NautilusActorConfig: Callable[[], object] | None = None
NautilusStrategy: type[object] | None = None
NautilusStrategyConfig: Callable[[], object] | None = None



class _StaticMarketUniverse:
    def __init__(self, markets: tuple[Market, ...]) -> None:
        self._markets: tuple[Market, ...] = markets

    async def refresh_once(self) -> list[Market]:
        return list(self._markets)

    def refresh_once_sync(self) -> list[Market]:
        return list(self._markets)


logger = logging.getLogger(__name__)

def _runtime_heartbeat_path(settings: Settings) -> Path:
    return Path(settings.storage.state_dir) / "runtime_heartbeat.json"


def _runtime_startup_marker_path(settings: Settings) -> Path:
    return Path(settings.storage.state_dir) / "runtime_startup.json"


def _log_probe_write_failure(path: Path) -> None:
    logger.warning("Failed to write runtime probe state: %s", path, exc_info=True)


def _write_runtime_startup_marker_best_effort(path: Path) -> None:
    try:
        _ = write_runtime_startup_marker(path)
    except OSError:
        _log_probe_write_failure(path)


def _write_runtime_heartbeat_best_effort(
    path: Path,
    *,
    phase: str,
    fatal: bool = False,
    fatal_reason: str | None = None,
) -> None:
    try:
        _ = write_runtime_heartbeat(
            path,
            phase=phase,
            fatal=fatal,
            fatal_reason=fatal_reason,
        )
    except OSError:
        _log_probe_write_failure(path)


def _runtime_progress_callback(settings: Settings) -> Callable[[str], None]:
    path = _runtime_heartbeat_path(settings)

    def note_progress(phase: str) -> None:
        _write_runtime_heartbeat_best_effort(path, phase=phase)

    return note_progress



@dataclass(slots=True)
class NautilusRuntimeBundle:
    """Wired Nautilus TradingNode runtime components."""

    scheduler: PolySignalScheduler
    components: dict[str, object]
    bridge_registry: MarketCatalog
    node: _TradingNodeLike
    observability: ObservabilityActor
    websocket_tasks: list[asyncio.Task[object]]



def _ensure_nautilus_imports() -> None:
    """Lazy-import Nautilus LiveNode and runtime helpers into module globals.

    Uses module-level placeholders so tests on py3.11 can monkeypatch before
    the first real call triggers the import chain.  Reads the guard from
    ``sys.modules`` so a ``monkeypatch.setattr`` on the string path always
    takes effect even if this function's ``__globals__`` references a stale
    module object.
    """
    global LiveNode, PolymarketInstrumentProviderConfig, NautilusActor, NautilusStrategy
    global NautilusActorConfig, NautilusStrategyConfig

    mod = sys.modules.get(__name__)
    module_live_node = getattr(mod, "LiveNode", None) if mod is not None else None
    current_live_node = module_live_node or LiveNode
    if current_live_node is not None:
        # Sync our __globals__ from the live module entry so subsequent
        # calls that reach this function use patched values together.
        LiveNode = current_live_node
        if mod is not None:
            PolymarketInstrumentProviderConfig = cast(Callable[..., object], getattr(mod, "PolymarketInstrumentProviderConfig", PolymarketInstrumentProviderConfig))
            NautilusActor = cast(type[object] | None, getattr(mod, "NautilusActor", NautilusActor))
            NautilusActorConfig = cast(Callable[[], object] | None, getattr(mod, "NautilusActorConfig", NautilusActorConfig))
            NautilusStrategy = cast(type[object] | None, getattr(mod, "NautilusStrategy", NautilusStrategy))
            NautilusStrategyConfig = cast(Callable[[], object] | None, getattr(mod, "NautilusStrategyConfig", NautilusStrategyConfig))
        return

    live_mod = importlib.import_module("nautilus_trader.live")
    provider_mod = importlib.import_module("nautilus_trader.adapters.polymarket.providers")
    actor_mod = importlib.import_module("nautilus_trader.common.actor")
    strategy_mod = importlib.import_module("nautilus_trader.trading.strategy")
    config_mod = importlib.import_module("nautilus_trader.config")

    LiveNode = getattr(live_mod, "LiveNode")
    PolymarketInstrumentProviderConfig = cast(
        Callable[..., object],
        getattr(provider_mod, "PolymarketInstrumentProviderConfig"),
    )
    NautilusActor = cast(type[object], getattr(actor_mod, "Actor"))
    NautilusActorConfig = cast(Callable[[], object], getattr(config_mod, "ActorConfig"))
    NautilusStrategy = cast(type[object], getattr(strategy_mod, "Strategy"))
    NautilusStrategyConfig = cast(Callable[[], object], getattr(config_mod, "StrategyConfig"))


def _load_runtime_classes() -> tuple[type[object], type[object]]:
    from polysignal_lab.nautilus_runtime.runtime_classes import (
        NautilusMarketRotationActor,
        NautilusPolySignalNativeStrategy,
    )

    return NautilusPolySignalNativeStrategy, NautilusMarketRotationActor


def _create_configured_live_node(
    settings: Settings,
    configured_markets: Sequence[Market],
) -> tuple[_TradingNodeLike, object]:
    _ensure_nautilus_imports()
    if PolymarketInstrumentProviderConfig is None:
        raise RuntimeError("Nautilus PolymarketInstrumentProviderConfig is unavailable")
    instrument_config = PolymarketInstrumentProviderConfig(
        load_ids=_instrument_load_ids(configured_markets),
    )
    from polysignal_lab.nautilus_runtime.live_node import build_paper_live_node

    node = build_paper_live_node(settings, instrument_config=instrument_config)
    return cast(_TradingNodeLike, node), instrument_config


def _create_market_projection_components(
    configured_markets: Sequence[Market],
) -> tuple[MarketCatalog, MarketViewAssembler]:
    catalog = MarketCatalog()
    _register_markets(catalog, configured_markets)
    custom_data = StrategyCustomDataState()
    assembler = MarketViewAssembler(
        catalog=catalog,
        books=_EmptyBookDataProvider(),
        custom_data=custom_data,
    )
    return catalog, assembler


def _attach_cache_projections(
    node: _TradingNodeLike,
    registry: MarketCatalog,
    assembler: MarketViewAssembler,
    strategies: Sequence[_NativeStrategyLike],
) -> object:
    from polysignal_lab.nautilus_runtime.cache_market_data import NautilusCacheMarketDataProvider
    from polysignal_lab.nautilus_runtime.cache_reader import NautilusCacheReader

    kernel = getattr(node, "kernel", None)
    nautilus_cache = getattr(node, "cache", None) or getattr(kernel, "cache", None)
    books = NautilusCacheMarketDataProvider(
        nautilus_cache,
        catalog=registry,
    )
    assembler.books = books
    cache_reader = NautilusCacheReader(
        nautilus_cache,
        portfolio=getattr(node, "portfolio", None) or getattr(kernel, "portfolio", None),
    )
    for strategy in strategies:
        strategy_assembler = getattr(strategy, "assembler", None)
        if hasattr(strategy_assembler, "books"):
            setattr(strategy_assembler, "books", books)
        setattr(strategy, "cache_reader", cache_reader)
    return cache_reader


def _register_runtime_trader_components(
    node: _TradingNodeLike,
    market_rotation_actor: object,
    strategies: Sequence[_NativeStrategyLike],
) -> None:
    node.trader.add_actor(market_rotation_actor)
    for strategy in strategies:
        node.trader.add_strategy(strategy)
    node.build()


def _build_market_rotation_actor(
    *,
    settings: Settings,
    startup_markets: Sequence[Market],
    market_universe: object,
    registry: MarketCatalog,
    store: AnchorPriceStore | None,
    health: object | None,
) -> object:
    _strategy_cls, actor_cls = _load_runtime_classes()
    actor_factory = cast(Callable[..., object], actor_cls)
    return actor_factory(
        settings=settings,
        startup_markets=tuple(startup_markets),
        market_universe=market_universe,
        catalog=registry,
        anchor_store=store,
        health=health,
    )


def _runtime_components(
    *,
    node: _TradingNodeLike,
    config: object,
    registry: MarketCatalog,
    market_rotation_actor: object,
    assembler: MarketViewAssembler,
    policy: DecisionPolicyActor,
    strategies: Sequence[_NativeStrategyLike],
    cache_reader: object,
) -> dict[str, object]:
    return {
        "node": node,
        "config": config,
        "registry": registry,
        "market_rotation_actor": market_rotation_actor,
        "assembler": assembler,
        "policy": policy,
        "strategies": list(strategies),
        "strategy_names": [strategy.strategy_name for strategy in strategies],
        "cache_reader": cache_reader,
    }


def build_trading_node(
    settings: Settings | None = None,
    *,
    condition_ids: Sequence[str] = (),
    markets: Sequence[Market] = (),
    market_universe: object | None = None,
    store: AnchorPriceStore | None = None,
    health: object | None = None,
    observability: ObservabilityActor | None = None,
) -> dict[str, object]:
    """Build the Nautilus-owned paper runtime wiring."""
    context = _build_runtime_context(settings, condition_ids, markets, market_universe)
    settings, configured_markets, configured_condition_ids = context[:3]
    runtime_market_universe, node, config, registry, assembler, policy = context[3:]
    market_rotation_actor = _build_market_rotation_actor(
        settings=settings,
        startup_markets=configured_markets,
        market_universe=runtime_market_universe,
        registry=registry,
        store=store,
        health=health,
    )
    strategies = _build_native_strategies(
        settings,
        assembler,
        policy,
        configured_condition_ids,
        registry,
        observability,
    )
    _register_runtime_trader_components(node, market_rotation_actor, strategies)
    cache_reader = _attach_cache_projections(node, registry, assembler, strategies)
    return _runtime_components(
        node=node,
        config=config,
        registry=registry,
        market_rotation_actor=market_rotation_actor,
        assembler=assembler,
        policy=policy,
        strategies=strategies,
        cache_reader=cache_reader,
    )

def _build_runtime_context(
    settings: Settings | None,
    condition_ids: Sequence[str],
    markets: Sequence[Market],
    market_universe: object | None,
) -> tuple[object, ...]:
    if settings is None:
        settings = load_settings()
    configured_markets = tuple(markets)
    configured_condition_ids = _configured_condition_ids(condition_ids, configured_markets)
    runtime_market_universe = (
        market_universe if market_universe is not None else _StaticMarketUniverse(configured_markets)
    )
    node, config = _create_configured_live_node(settings, configured_markets)
    registry, assembler = _create_market_projection_components(configured_markets)
    policy = _build_policy(settings)
    return (
        settings,
        configured_markets,
        configured_condition_ids,
        runtime_market_universe,
        node,
        config,
        registry,
        assembler,
        policy,
    )

def _configured_condition_ids(
    condition_ids: Sequence[str],
    markets: Sequence[Market],
) -> tuple[str, ...]:
    explicit_ids = tuple(str(condition_id) for condition_id in condition_ids if str(condition_id))
    if explicit_ids:
        return explicit_ids
    return tuple(market.condition_id for market in markets if market.condition_id)


def _instrument_load_ids(markets: Sequence[Market]) -> frozenset[str]:
    from polysignal_lab.nautilus_runtime.instrument_mapping import polymarket_instrument_id

    load_ids: set[str] = set()
    for market in markets:
        for token in market.outcome_tokens:
            if token.token_id and market.condition_id:
                load_ids.add(polymarket_instrument_id(market.condition_id, token.token_id))
    return frozenset(load_ids)


def _register_markets(
    registry: MarketCatalog,
    markets: Sequence[Market],
) -> None:
    for market in markets:
        try:
            registry.register(MarketPairMeta.from_market(market))
        except (KeyError, ValueError) as exc:
            logger.debug("skipping runtime market registration for %s: %s", market.market_id, exc)


def _build_native_strategies(
    settings: Settings,
    assembler: MarketViewAssembler,
    policy: DecisionPolicyActor,
    condition_ids: Sequence[str],
    registry: MarketCatalog,
    observability: ObservabilityActor | None,
) -> list[_NativeStrategyLike]:
    strategy_cls, _actor_cls = _load_runtime_classes()
    strategy_type = cast(Callable[..., _NativeStrategyLike], strategy_cls)
    instrument_id_resolver = _instrument_id_resolver(registry)
    strategy_book_type = settings.runtime.nautilus.sandbox_book_type
    strategies: list[_NativeStrategyLike] = []
    strategy_names: set[str] = set()
    for name in settings.strategies.explicit_strategy_names():
        if name in strategy_names:
            continue
        strategy_names.add(name)
        cfg = cast(object | None, getattr(settings.strategies, name, None))
        if cfg is None:
            continue

        core = _native_core_for(name, cfg)
        if core is None:
            logger.warning("no native alpha core for strategy %s", name)
            continue

        strategy = _create_native_strategy(
            strategy_type,
            settings,
            assembler,
            policy,
            configured_condition_ids=condition_ids,
            strategy_name=name,
            core=core,
            fixed_stake=_fixed_stake_for(cfg),
            strategy_book_type=strategy_book_type,
            instrument_id_resolver=instrument_id_resolver,
            registry=registry,
            observability=observability,
        )
        _attach_strategy_custom_data(strategy, assembler)
        strategies.append(strategy)

    return strategies


def _create_native_strategy(
    strategy_type: Callable[..., _NativeStrategyLike],
    settings: Settings,
    assembler: MarketViewAssembler,
    policy: DecisionPolicyActor,
    *,
    configured_condition_ids: Sequence[str],
    strategy_name: str,
    core: AlphaCore,
    fixed_stake: float,
    strategy_book_type: str,
    instrument_id_resolver: Callable[[str], object],
    registry: MarketCatalog,
    observability: ObservabilityActor | None,
) -> _NativeStrategyLike:
    return strategy_type(
        core=core,
        assembler=assembler,
        condition_ids=tuple(configured_condition_ids),
        strategy_name=strategy_name,
        policy=policy,
        fixed_stake_usdc=fixed_stake,
        book_type=strategy_book_type,
        instrument_id_resolver=instrument_id_resolver,
        registry=registry,
        observability=observability,
        exit_model=settings.paper_trading.exit_model,
        progress_callback=_runtime_progress_callback(settings),
        unsubscribe_exited=settings.runtime.nautilus.market_rotation.unsubscribe_exited,
        l1_book_snapshot_interval_ms=settings.runtime.nautilus.l1_book_snapshot_interval_ms,
    )


def _attach_strategy_custom_data(
    strategy: _NativeStrategyLike,
    assembler: MarketViewAssembler,
) -> None:
    custom_data = getattr(strategy, "custom_data", None)
    if not isinstance(custom_data, StrategyCustomDataState):
        custom_data = StrategyCustomDataState()
        setattr(strategy, "custom_data", custom_data)
    strategy_assembler = getattr(strategy, "assembler", assembler)
    with_custom_data = getattr(strategy_assembler, "with_custom_data", None)
    if callable(with_custom_data):
        setattr(strategy, "assembler", with_custom_data(custom_data))
    elif hasattr(strategy_assembler, "custom_data"):
        setattr(strategy_assembler, "custom_data", custom_data)


def _instrument_id_resolver(registry: MarketCatalog) -> Callable[[str], object]:
    def resolve(token_id: str) -> object:
        instrument_id = registry.instrument_id_for_token(token_id)
        if instrument_id is None:
            raise ValueError(f"token_id {token_id!r} is not registered in the Nautilus runtime catalog")
        return instrument_id

    return resolve


async def _stop_nautilus_scheduler(scheduler: object) -> None:
    if bool(getattr(scheduler, "_nautilus_runtime_owned_by_trading_node", False)):
        setattr(scheduler, "_running", False)
        try:
            scheduler_health.persist_health_snapshot(cast(PolySignalScheduler, scheduler))
        except Exception as exc:
            cast(logging.Logger, getattr(scheduler, "logger", logger)).warning(
                "Failed to persist Nautilus health snapshot: %s",
                exc,
            )
        return

    setattr(scheduler, "_running", False)
    try:
        scheduler_health.persist_health_snapshot(cast(PolySignalScheduler, scheduler))
    except Exception as exc:
        cast(logging.Logger, getattr(scheduler, "logger", logger)).warning(
            "Failed to persist Nautilus health snapshot: %s",
            exc,
        )


def _fresh_publish_service(
    scheduler: PolySignalScheduler,
) -> tuple[PublishService, TelegramPublisher]:
    base_service = cast(_PublishServiceLike, scheduler.publish_service)
    publisher = TelegramPublisher(scheduler.settings.telegram)
    publish_service = PublishService(
        base_service.formatter,
        publisher,
        base_service.persistence,
        timeout_sec=base_service.timeout_sec,
    )
    return publish_service, publisher


async def _publish_accepted_signal_once(
    scheduler: PolySignalScheduler,
    signal: SignalCandidate,
    stake_usdc: float,
) -> dict[str, str | None]:
    publish_service, publisher = _fresh_publish_service(scheduler)
    try:
        publish = await cast(_PublishServiceLike, publish_service).publish_signal(signal, stake_usdc)
        return publish.as_dict()
    finally:
        await publisher.client.aclose()


def _publish_accepted_signal_in_background(
    scheduler: PolySignalScheduler,
    signal: SignalCandidate,
    stake_usdc: float,
) -> None:
    try:
        publish = asyncio.run(_publish_accepted_signal_once(scheduler, signal, stake_usdc))
        scheduler_health.note_publish_result(scheduler, publish)
    except Exception as exc:
        scheduler.logger.warning(
            "Nautilus accepted signal publish failed for %s: %s",
            signal.signal_id,
            exc,
        )


def _notify_accepted_signal(
    scheduler: PolySignalScheduler,
    signal: SignalCandidate,
    stake_usdc: float,
) -> None:
    if not getattr(scheduler.settings.telegram, "send_signals", False):
        return
    thread = threading.Thread(
        target=_publish_accepted_signal_in_background,
        args=(scheduler, signal, stake_usdc),
        daemon=True,
    )
    thread.start()






_InteractiveTelegramBotThread = tuple[threading.Thread, threading.Event]


async def _run_interactive_telegram_bot_until_stop(
    bot: object,
    stop: asyncio.Event,
) -> None:
    start = getattr(bot, "start", None)
    stop_bot = getattr(bot, "stop", None)
    if not callable(start) or not callable(stop_bot):
        return
    try:
        _ = await cast(Callable[[], Awaitable[object]], start)()
        _ = await stop.wait()
    finally:
        _ = await cast(Callable[[], Awaitable[object]], stop_bot)()


def _start_interactive_telegram_bot_thread(
    scheduler: PolySignalScheduler,
) -> _InteractiveTelegramBotThread | None:
    bot = cast(object | None, getattr(scheduler, "telegram_bot", None))
    if bot is None:
        return None
    stop_event = threading.Event()
    runtime_logger = cast(logging.Logger, getattr(scheduler, "logger", logger))

    def _run() -> None:
        async def _main() -> None:
            try:
                typed_bot = cast(_InteractiveBotLike, bot)
                _ = await typed_bot.start()
                while not stop_event.is_set():
                    await asyncio.sleep(0.5)
            finally:
                _ = await cast(_InteractiveBotLike, bot).stop()

        try:
            asyncio.run(_main())
        except Exception:
            runtime_logger.exception("Interactive Telegram bot thread exited with error")

    thread = threading.Thread(
        target=_run,
        name="telegram-interactive-bot",
        daemon=True,
    )
    thread.start()
    return thread, stop_event


def _stop_interactive_telegram_bot_thread(
    handle: _InteractiveTelegramBotThread | None,
    *,
    timeout_sec: float = 15.0,
) -> None:
    if handle is None:
        return
    thread, stop_event = handle
    stop_event.set()
    thread.join(timeout=timeout_sec)


_NautilusReportLoopThread = tuple[threading.Thread, threading.Event]


def _start_nautilus_report_loop_thread(
    scheduler: PolySignalScheduler,
) -> _NautilusReportLoopThread:
    stop_event = threading.Event()
    runtime_logger = cast(logging.Logger, getattr(scheduler, "logger", logger))

    def _run() -> None:
        async def _main() -> None:
            asyncio_stop = asyncio.Event()

            async def _watch_stop() -> None:
                while not stop_event.is_set():
                    await asyncio.sleep(0.5)
                asyncio_stop.set()

            watcher = asyncio.create_task(_watch_stop())
            try:
                await _run_nautilus_report_loop(scheduler, asyncio_stop)
            finally:
                _ = watcher.cancel()
                with suppress(asyncio.CancelledError):
                    await watcher

        try:
            asyncio.run(_main())
        except Exception:
            runtime_logger.exception("Nautilus report loop thread exited with error")

    thread = threading.Thread(
        target=_run,
        name="nautilus-report-loop",
        daemon=True,
    )
    thread.start()
    return thread, stop_event


def _stop_nautilus_report_loop_thread(
    handle: _NautilusReportLoopThread | None,
    *,
    timeout_sec: float = 15.0,
) -> None:
    if handle is None:
        return
    thread, stop_event = handle
    stop_event.set()
    thread.join(timeout=timeout_sec)



async def _prepare_nautilus_runtime_context(
    settings: Settings,
) -> tuple[PolySignalScheduler, tuple[Market, ...], ObservabilityActor]:
    scheduler = PolySignalScheduler(settings)
    _initialize_nautilus_scheduler_components(scheduler)
    setattr(scheduler, "_nautilus_runtime_owned_by_trading_node", True)
    discovered_markets = tuple(await scheduler.market_universe.refresh_once())
    observability = ObservabilityActor(
        health=scheduler.health,
        store=NautilusEventStoreAdapter(scheduler.persistence),
        notifier=NautilusNotifierAdapter(scheduler.publisher),
        accepted_signal_notifier=lambda signal, stake_usdc: _notify_accepted_signal(
            scheduler,
            signal,
            stake_usdc,
        ),
    )
    return scheduler, discovered_markets, observability


def _rebind_market_discovery_client(scheduler: PolySignalScheduler) -> None:
    discovery = cast(object, getattr(scheduler, "discovery", None))
    client = getattr(discovery, "client", None)
    if client is None:
        return
    replace_client = getattr(discovery, "replace_client", None)
    if callable(replace_client):
        _ = replace_client()
        return
    try:
        import httpx

        setattr(discovery, "client", httpx.AsyncClient(timeout=15.0))
    except Exception:
        scheduler.logger.warning(
            "Failed to replace startup market discovery client before live runtime handoff",
            exc_info=True,
        )


def _build_nautilus_runtime_bundle(
    settings: Settings,
    scheduler: PolySignalScheduler,
    discovered_markets: tuple[Market, ...],
    observability: ObservabilityActor,
) -> NautilusRuntimeBundle:
    condition_ids = tuple(market.condition_id for market in discovered_markets if market.condition_id)
    components = build_trading_node(
        settings,
        condition_ids=condition_ids,
        markets=discovered_markets,
        market_universe=scheduler.market_universe,
        store=getattr(scheduler, "sqlite", None),
        health=scheduler.health,
        observability=observability,
    )
    paper_execution_metadata = {
        "sandbox_book_type": settings.runtime.nautilus.sandbox_book_type,
    }
    setattr(scheduler, "nautilus_cache_reader", components.get("cache_reader"))
    setattr(scheduler, "paper_execution_metadata", paper_execution_metadata)

    return NautilusRuntimeBundle(
        scheduler=scheduler,
        components=components,
        bridge_registry=cast(MarketCatalog, components["registry"]),
        node=cast(_TradingNodeLike, components["node"]),
        observability=observability,
        websocket_tasks=[],
    )


def _native_core_for(name: str, cfg: object) -> AlphaCore | None:
    """Return the alpha core for a strategy name, or None."""
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

    core_factory = cast(
        Callable[[object], AlphaCore] | None,
        {
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
        }.get(name),
    )
    if core_factory is None:
        return None
    return core_factory(cfg)


def _fixed_stake_for(cfg: object) -> float:
    stake_usdc = cast(object, getattr(cfg, "stake_usdc", None))
    if isinstance(stake_usdc, (int, float, str)):
        return float(stake_usdc)
    basket_notional = cast(object, getattr(cfg, "basket_notional", 10.0))
    if isinstance(basket_notional, (int, float, str)):
        return float(basket_notional)
    return 10.0


def _build_policy(settings: Settings) -> DecisionPolicyActor:
    return DecisionPolicyActor(
        gate=SignalGate(
            settings.signal,
            settings.data.polymarket,
            settings.data.binance,
        ),
        arbiter=SignalArbiter(),
        consensus=ConsensusEngine(
            window_sec=settings.signal.consensus_window_sec,
            enabled=settings.signal.consensus_enabled,
        ),
    )


def build_control(policy: DecisionPolicyActor) -> DecisionPolicyControl:
    """Build a StrategyControl adapter from a DecisionPolicyActor."""
    return DecisionPolicyControl(policy)


def _initialize_nautilus_scheduler_components(scheduler: PolySignalScheduler) -> None:
    """Initialize scheduler state needed by Nautilus without legacy local paper."""
    initialized = cast(object, getattr(scheduler, "_trading_components_initialized", False))
    if initialized is True:
        return
    scheduler.strategy_schedule = build_strategy_schedule(scheduler.settings.strategies)
    scheduler.strategies = [entry.strategy for entry in scheduler.strategy_schedule]
    scheduler.signal_pipeline.strategies = scheduler.strategies
    scheduler.signal_pipeline.set_strategy_dependencies(
        {entry.name: tuple(entry.depends_on) for entry in scheduler.strategy_schedule}
    )
    known_strategy_names = {entry.name for entry in scheduler.strategy_schedule}
    disabled_raw = cast(object, scheduler.persistence.read_state("telegram_disabled_strategies", default=[]))
    disabled_names: tuple[str, ...] = ()
    if isinstance(disabled_raw, list):
        disabled_names = tuple(str(name) for name in cast(list[object], disabled_raw))
    for name in disabled_names:
        if name in known_strategy_names:
            scheduler.signal_pipeline.set_strategy_enabled(name, False)
    scheduler.arbiter = SignalArbiter()
    setattr(scheduler, "_trading_components_initialized", True)

async def build_nautilus_runtime(settings: Settings | None = None) -> NautilusRuntimeBundle:
    """Build the default Nautilus runtime without PolySignal market-data ownership."""
    if settings is None:
        settings = load_settings()

    scheduler, discovered_markets, observability = await _prepare_nautilus_runtime_context(settings)
    return _build_nautilus_runtime_bundle(settings, scheduler, discovered_markets, observability)
async def _run_nautilus_housekeeping_once(
    scheduler: PolySignalScheduler,
    last_report_date: date | None,
) -> date | None:
    from polysignal_lab.app.scheduler_runtime import _generate_iteration_report  # pyright: ignore[reportPrivateUsage] - runtime reuses scheduler's existing report generator.

    return await _generate_iteration_report(scheduler, last_report_date)


async def _run_nautilus_report_loop(
    scheduler: PolySignalScheduler,
    stop_event: asyncio.Event,
) -> None:
    last_report_date = None
    interval_sec = max(float(scheduler.settings.markets.refresh_interval_sec), 1.0)
    while not stop_event.is_set():
        last_report_date = await _run_nautilus_housekeeping_once(
            scheduler,
            last_report_date,
        )
        try:
            _ = await asyncio.wait_for(stop_event.wait(), timeout=interval_sec)
        except asyncio.TimeoutError:
            continue




def _runtime_intercepts_os_signals(settings: object | None) -> bool:
    runtime_settings = getattr(settings, "runtime", None)
    nautilus_settings = getattr(runtime_settings, "nautilus", None)
    return bool(getattr(nautilus_settings, "intercept_os_signals", False))


_SignalHandler = signal.Handlers | int | Callable[..., object] | None
_SignalHandlerSnapshot = tuple[signal.Signals, _SignalHandler]


def _restore_os_signal_handlers(
    previous_handlers: Sequence[_SignalHandlerSnapshot],
) -> None:
    for sig, previous in reversed(previous_handlers):
        with suppress(ValueError, OSError, RuntimeError):
            _ = signal.signal(sig, previous)


def _install_async_os_signal_handlers(
    loop: asyncio.AbstractEventLoop,
    request_stop: Callable[[], None],
) -> Callable[[], None]:
    loop_handlers: list[_SignalHandlerSnapshot] = []
    sync_handlers: list[_SignalHandlerSnapshot] = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        previous = signal.getsignal(sig)
        try:
            loop.add_signal_handler(sig, request_stop)
        except (NotImplementedError, RuntimeError):
            _ = signal.signal(sig, lambda _signum, _frame: request_stop())
            sync_handlers.append((sig, previous))
        else:
            loop_handlers.append((sig, previous))

    def cleanup() -> None:
        for sig, previous in reversed(loop_handlers):
            with suppress(NotImplementedError, RuntimeError):
                _ = loop.remove_signal_handler(sig)
            _restore_os_signal_handlers(((sig, previous),))
        _restore_os_signal_handlers(sync_handlers)

    return cleanup


def _install_sync_os_signal_handlers(
    request_stop: Callable[[], None],
) -> Callable[[], None]:
    previous_handlers: list[_SignalHandlerSnapshot] = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        previous_handlers.append((sig, signal.getsignal(sig)))
        _ = signal.signal(sig, lambda _signum, _frame: request_stop())
    return lambda: _restore_os_signal_handlers(previous_handlers)


def _dump_thread_stacks(log_path: str) -> None:
    """Write all thread stack traces to a file that survives container restart."""
    try:
        _crash_dir = Path(log_path).parent
        _crash_dir.mkdir(parents=True, exist_ok=True)
        frames = sys._current_frames()  # pyright: ignore[reportPrivateUsage] - crash diagnostics need live thread frames.
        lines: list[str] = [
            f"=== crash dump {datetime.now(UTC).isoformat()} ===",
            f"threads={len(frames)}",
        ]
        for tid, stack in frames.items():
            lines.append(f"\n--- thread {tid} ---")
            stack_summary = cast(Sequence[traceback.FrameSummary], traceback.extract_stack(stack))
            for frame in stack_summary:
                lines.append(f"  {frame.filename}:{frame.lineno} {frame.name}")
                if frame.line:
                    lines.append(f"    {frame.line.strip()}")
        with open(log_path, "a", encoding="utf-8") as fh:
            _ = fh.write("\n".join(lines) + "\n")
    except Exception:
        pass


def _install_crash_logger(log_dir: str) -> None:
    """Install hooks that capture crash context before exit.

    Writes to ``log_dir/crash.log`` which survives container restarts
    when ``log_dir`` is a mounted volume.
    """
    crash_path = f"{log_dir.rstrip('/')}/crash.log"

    def crash_excepthook(typ: type[BaseException], val: BaseException, tb: TracebackType | None) -> None:
        _dump_thread_stacks(crash_path)
        try:
            with open(crash_path, "a", encoding="utf-8") as fh:
                traceback.print_exception(typ, val, tb, file=fh)
        except Exception:
            pass
        sys.__excepthook__(typ, val, tb)

    sys.excepthook = crash_excepthook

    def _atexit_dump() -> None:
        _dump_thread_stacks(crash_path)
        try:
            with open(crash_path, "a", encoding="utf-8") as fh:
                _ = fh.write(f"=== atexit {datetime.now(UTC).isoformat()} ===\n")
        except Exception:
            pass

    _ = atexit.register(_atexit_dump)


def _strategy_names_from_bundle(bundle: NautilusRuntimeBundle) -> list[str]:
    strategies = bundle.components.get("strategies", ())
    strategy_sequence: Sequence[object] = (
        strategies
        if isinstance(strategies, Sequence)
        else ()
    )
    return [str(getattr(strategy, "strategy_name", "")) for strategy in strategy_sequence]


async def _start_async_cli_sidecars(
    bundle: NautilusRuntimeBundle,
    telegram_stop: asyncio.Event,
) -> asyncio.Task[None] | None:
    starter = getattr(bundle.observability, "start", None)
    if callable(starter):
        _ = starter()
    bot = cast(object | None, getattr(bundle.scheduler, "telegram_bot", None))
    if bot is None:
        return None
    return asyncio.create_task(_run_interactive_telegram_bot_until_stop(bot, telegram_stop))


async def _notify_async_cli_startup(
    bundle: NautilusRuntimeBundle,
    strategy_names: Sequence[str],
    runtime_logger: logging.Logger,
) -> None:
    await asyncio.to_thread(_rebind_market_discovery_client, bundle.scheduler)
    try:
        await bundle.observability.notify_startup(
            strategy_names,
            sandbox_book_type=bundle.scheduler.settings.runtime.nautilus.sandbox_book_type,
        )
    except Exception:
        runtime_logger.exception("Nautilus startup notification failed")


async def _run_async_node_with_report_loop(
    node: _TradingNodeLike,
    scheduler: PolySignalScheduler,
    event: asyncio.Event,
) -> None:
    report_task = asyncio.create_task(_run_nautilus_report_loop(scheduler, event))
    try:
        run_task = asyncio.create_task(asyncio.to_thread(node.run))
        stop_waiter = asyncio.create_task(event.wait())
        done, pending = await asyncio.wait(
            [run_task, stop_waiter],
            return_when=asyncio.FIRST_COMPLETED,
        )
        if run_task in done:
            if stop_waiter in pending:
                _ = stop_waiter.cancel()
            await run_task
        elif stop_waiter in done:
            stopper = getattr(node, "stop", None)
            if callable(stopper):
                _ = stopper()
            await run_task
    finally:
        _ = report_task.cancel()
        with suppress(asyncio.CancelledError):
            await report_task


async def _finalize_async_cli_runtime(
    bundle: NautilusRuntimeBundle,
    event: asyncio.Event,
    telegram_stop: asyncio.Event,
    telegram_task: asyncio.Task[None] | None,
    runtime_logger: logging.Logger,
    cleanup_signals: Callable[[], None],
) -> None:
    try:
        event.set()
        telegram_stop.set()
        if telegram_task is not None:
            with suppress(asyncio.CancelledError):
                await telegram_task
        try:
            await bundle.observability.notify_shutdown()
        except Exception:
            runtime_logger.exception("Nautilus shutdown notification failed")
        stopper = getattr(bundle.observability, "stop", None)
        if callable(stopper):
            _ = stopper()
        await _stop_nautilus_scheduler(bundle.scheduler)
    finally:
        cleanup_signals()


async def run_nautilus_cli_async(
    settings: Settings | None = None,
    stop_event: asyncio.Event | None = None,
) -> _TradingNodeLike:
    """Run the Nautilus CLI with async orchestration and signal handling."""
    event = stop_event or asyncio.Event()
    if settings is None:
        settings = load_settings()
    _write_runtime_startup_marker_best_effort(_runtime_startup_marker_path(settings))
    bundle = await build_nautilus_runtime(settings)
    _write_runtime_heartbeat_best_effort(
        _runtime_heartbeat_path(bundle.scheduler.settings),
        phase="starting",
    )
    node = bundle.node
    loop = asyncio.get_running_loop()

    request_stop: Callable[[], None] = event.set
    runtime_logger = cast(logging.Logger, getattr(bundle.scheduler, "logger", logger))
    cleanup_signals: Callable[[], None] = lambda: None
    runtime_settings = getattr(bundle.scheduler, "settings", settings)
    if _runtime_intercepts_os_signals(runtime_settings):
        cleanup_signals = _install_async_os_signal_handlers(loop, request_stop)

    telegram_stop = asyncio.Event()
    telegram_task: asyncio.Task[None] | None = None
    try:
        telegram_task = await _start_async_cli_sidecars(bundle, telegram_stop)
        strategy_names = _strategy_names_from_bundle(bundle)
        await _notify_async_cli_startup(bundle, strategy_names, runtime_logger)
        print(f"Nautilus runtime ready — {len(strategy_names)} strategies")
        if stop_event is not None and stop_event.is_set():
            return node
        await _run_async_node_with_report_loop(node, bundle.scheduler, event)
    finally:
        await _finalize_async_cli_runtime(
            bundle,
            event,
            telegram_stop,
            telegram_task,
            runtime_logger,
            cleanup_signals,
        )
    return node


def _prepare_sync_cli_bundle(settings: Settings) -> NautilusRuntimeBundle:
    _write_runtime_startup_marker_best_effort(_runtime_startup_marker_path(settings))
    scheduler, discovered_markets, observability = asyncio.run(
        _prepare_nautilus_runtime_context(settings)
    )
    _rebind_market_discovery_client(scheduler)
    bundle = _build_nautilus_runtime_bundle(
        settings,
        scheduler,
        discovered_markets,
        observability,
    )
    _write_runtime_heartbeat_best_effort(
        _runtime_heartbeat_path(bundle.scheduler.settings),
        phase="starting",
    )
    return bundle


def _run_sync_cli_main(
    bundle: NautilusRuntimeBundle,
    node: _TradingNodeLike,
    settings: Settings,
    strategy_names: list[str],
    runtime_logger: logging.Logger,
) -> tuple[_InteractiveTelegramBotThread | None, _NautilusReportLoopThread | None]:
    starter = getattr(bundle.observability, "start", None)
    if callable(starter):
        _ = starter()
    telegram_bot_thread = _start_interactive_telegram_bot_thread(bundle.scheduler)
    report_loop_thread = _start_nautilus_report_loop_thread(bundle.scheduler)
    try:
        asyncio.run(
            bundle.observability.notify_startup(
                strategy_names,
                sandbox_book_type=bundle.scheduler.settings.runtime.nautilus.sandbox_book_type,
            )
        )
    except Exception:
        runtime_logger.exception("Nautilus startup notification failed")
    print(f"Nautilus runtime ready — {len(strategy_names)} strategies")
    _install_crash_logger(settings.storage.jsonl_dir)
    run_method = cast(Callable[..., None], getattr(node, "run"))
    if "raise_exception" in inspect.signature(run_method).parameters:
        run_method(raise_exception=True)
    else:
        run_method()
    if strategy_names:
        _dump_thread_stacks(f"{settings.storage.jsonl_dir.rstrip('/')}/crash.log")
        runtime_logger.warning(
            "TradingNode.run returned unexpectedly with %d strategies active",
            len(strategy_names),
        )
    return telegram_bot_thread, report_loop_thread


def _finalize_sync_cli_runtime(
    bundle: NautilusRuntimeBundle,
    node: _TradingNodeLike,
    telegram_bot_thread: _InteractiveTelegramBotThread | None,
    report_loop_thread: _NautilusReportLoopThread | None,
    runtime_logger: logging.Logger,
    cleanup_signals: Callable[[], None],
) -> None:
    _stop_nautilus_report_loop_thread(report_loop_thread)
    _stop_interactive_telegram_bot_thread(telegram_bot_thread)
    try:
        try:
            asyncio.run(bundle.observability.notify_shutdown())
        except Exception:
            runtime_logger.exception("Nautilus shutdown notification failed")
        stopper = getattr(bundle.observability, "stop", None)
        if callable(stopper):
            _ = stopper()
        asyncio.run(_stop_nautilus_scheduler(bundle.scheduler))
        if isinstance(node, _Disposable):
            node.dispose()
    finally:
        cleanup_signals()


def run_nautilus_cli(settings: Settings | None = None) -> None:
    """Entry point for the ``nautilus`` CLI mode — sync wrapper."""
    if settings is None:
        settings = load_settings()
    bundle = _prepare_sync_cli_bundle(settings)
    node = bundle.node

    def request_stop() -> None:
        stopper = getattr(node, "stop", None)
        if callable(stopper):
            _ = stopper()
            return
        raise KeyboardInterrupt

    cleanup_signals: Callable[[], None] = lambda: None
    if _runtime_intercepts_os_signals(getattr(bundle.scheduler, "settings", settings)):
        cleanup_signals = _install_sync_os_signal_handlers(request_stop)
    runtime_logger = cast(logging.Logger, getattr(bundle.scheduler, "logger", logger))
    strategy_names = _strategy_names_from_bundle(bundle)
    telegram_bot_thread: _InteractiveTelegramBotThread | None = None
    report_loop_thread: _NautilusReportLoopThread | None = None
    try:
        telegram_bot_thread, report_loop_thread = _run_sync_cli_main(
            bundle,
            node,
            settings,
            strategy_names,
            runtime_logger,
        )
    finally:
        _finalize_sync_cli_runtime(
            bundle,
            node,
            telegram_bot_thread,
            report_loop_thread,
            runtime_logger,
            cleanup_signals,
        )


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
