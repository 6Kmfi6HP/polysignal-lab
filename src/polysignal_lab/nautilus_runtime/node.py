"""
Input: __future__, __future__.annotations, datetime, datetime.datetime, datetime.timezone, asyncio, inspect, logging, signal, contextlib
Output: run_nautilus_cli, main
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from datetime import datetime, timezone

import asyncio
import inspect
import logging
import signal
from contextlib import suppress
from collections.abc import Callable, Sequence
from typing import Any, cast

from polysignal_lab.config import Settings, load_settings
from polysignal_lab.data.anchor_price_service import AnchorPriceStore
from polysignal_lab.domain.market import Market
from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog, MarketPairMeta
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor
from polysignal_lab.nautilus_runtime.node_crash import (
    _dump_thread_stacks,
    _install_crash_logger,
)
from polysignal_lab.nautilus_runtime.node_probes import (
    _runtime_heartbeat_path,
    _runtime_startup_marker_path,
    _write_runtime_startup_marker_best_effort,
    _write_runtime_heartbeat_best_effort,
)
from polysignal_lab.nautilus_runtime.node_signals import (
    _restore_os_signal_handlers,
    _runtime_intercepts_os_signals,
    _SignalHandlerSnapshot,
)
from polysignal_lab.nautilus_runtime.signal_sidecar import (
    _InteractiveTelegramBotThread,
    _NautilusReportLoopThread,
    _notify_accepted_signal,
    _run_interactive_telegram_bot_until_stop,
    _run_nautilus_report_loop,
    _start_interactive_telegram_bot_thread,
    _start_nautilus_report_loop_thread,
    _stop_interactive_telegram_bot_thread,
    _stop_nautilus_report_loop_thread,
    _stop_nautilus_services,
)
from polysignal_lab.nautilus_runtime.node_cli import (
    run_nautilus_cli_async as run_nautilus_cli_async,
)
from polysignal_lab.nautilus_runtime.observability import (
    NautilusEventStoreAdapter,
    NautilusNotifierAdapter,
    ObservabilityActor,
)
from polysignal_lab.nautilus_runtime.node_builder import (
    LiveNode,
    NautilusRuntimeBundle,
    NautilusRuntimeContext,
    build_nautilus_runtime_context,
    PolymarketInstrumentProviderConfig,
    NautilusActor,
    NautilusActorConfig,
    NautilusStrategy,
    NautilusStrategyConfig,
    _TraderLike,
    _Disposable,
    _NautilusNodeLike,
    _NativeStrategyLike,
    _EmptyBookDataProvider,
    _StaticMarketUniverse,
    _ensure_nautilus_imports,
    _load_runtime_classes,
    _runtime_class_triple,
    _create_configured_live_node,
    _create_market_projection_components,
    _register_markets,
    _instrument_load_ids,
    _build_runtime_context,
    _configured_condition_ids,
    _runtime_components,
    build_live_node,
    build_nautilus_runtime,
)
from polysignal_lab.nautilus_runtime.strategy_builder import (
    _build_native_strategies,
    _build_policy,
    _native_core_for,
    _instrument_id_resolver,
    build_control,
)

UTC = timezone.utc

logger = logging.getLogger(__name__)



def _attach_cache_projections(
    node: _NautilusNodeLike,
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
            strategy_assembler.books = books
        strategy.cache_reader = cache_reader
    return cache_reader


def _register_runtime_trader_components(
    node: _NautilusNodeLike,
    market_rotation_actor: object,
    policy: DecisionPolicyActor,
    strategies: Sequence[_NativeStrategyLike],
) -> None:
    node.trader.add_actor(market_rotation_actor)
    if _is_runtime_policy_actor(policy):
        node.trader.add_actor(policy)
    for strategy in strategies:
        node.trader.add_strategy(strategy)
    node.build()


def _is_runtime_policy_actor(policy: DecisionPolicyActor) -> bool:
    return (
        type(policy) is not DecisionPolicyActor
        and callable(getattr(policy, "on_save", None))
        and callable(getattr(policy, "on_load", None))
    )


def _build_market_rotation_actor(
    *,
    settings: Settings,
    startup_markets: Sequence[Market],
    market_universe: object,
    registry: MarketCatalog,
    store: AnchorPriceStore | None,
    health: object | None,
) -> object:
    _strategy_cls, actor_cls, _policy_cls = _runtime_class_triple()
    actor_factory = cast(Callable[..., object], actor_cls)
    return actor_factory(
        settings=settings,
        startup_markets=tuple(startup_markets),
        market_universe=market_universe,
        catalog=registry,
        anchor_store=store,
        health=health,
    )



async def _prepare_nautilus_runtime_context(
    settings: Settings,
) -> tuple[NautilusRuntimeContext, tuple[Market, ...], ObservabilityActor]:
    context = build_nautilus_runtime_context(settings)
    context._nautilus_runtime_owned_by_live_node = True
    discovered_markets = tuple(await context.market_universe.refresh_once())
    observability = ObservabilityActor(
        health=context.health,
        store=NautilusEventStoreAdapter(context.persistence),
        notifier=NautilusNotifierAdapter(context.publisher),
        accepted_signal_notifier=lambda signal, stake_usdc: _notify_accepted_signal(
            context,
            signal,
            stake_usdc,
        ),
    )
    return context, discovered_markets, observability


def _rebind_market_discovery_client(context: NautilusRuntimeContext) -> None:
    """Replace the startup-phase HTTP client with a fresh connection for live runtime."""
    if context.market_universe is None:
        return
    discovery = getattr(context.market_universe, "discovery", None)
    if discovery is None:
        return
    replace_client = getattr(discovery, "replace_client", None)
    if callable(replace_client):
        _ = replace_client()
        return
    try:
        import httpx
        discovery.client = httpx.AsyncClient(timeout=15.0)
    except Exception:
        context.logger.warning(
            "Failed to replace startup market discovery client before live runtime handoff",
            exc_info=True,
        )


def _build_nautilus_runtime_bundle(
    settings: Settings,
    context: NautilusRuntimeContext,
    discovered_markets: tuple[Market, ...],
    observability: ObservabilityActor,
) -> NautilusRuntimeBundle:
    condition_ids = tuple(market.condition_id for market in discovered_markets if market.condition_id)
    components = build_live_node(
        settings,
        condition_ids=condition_ids,
        markets=discovered_markets,
        market_universe=context.market_universe,
        store=context.sqlite,
        health=context.health,
        observability=observability,
    )
    paper_execution_metadata = {
        "sandbox_book_type": settings.runtime.nautilus.sandbox_book_type,
    }
    context.nautilus_cache_reader = components.get("cache_reader")
    context.paper_execution_metadata = paper_execution_metadata
    policy = cast(DecisionPolicyActor, components["policy"])
    bot = context.telegram_bot
    if bot is not None:
        bot.strategy_control = build_control(policy)


    return NautilusRuntimeBundle(
        context=context,
        components=components,
        bridge_registry=cast(MarketCatalog, components["registry"]),
        node=cast(_NautilusNodeLike, components["node"]),
        observability=observability,
        websocket_tasks=[],
    )


def _install_sync_os_signal_handlers(
    request_stop: Callable[[], None],
) -> Callable[[], None]:
    previous_handlers: list[_SignalHandlerSnapshot] = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        previous_handlers.append((sig, signal.getsignal(sig)))
        _ = signal.signal(sig, lambda _signum, _frame: request_stop())
    return lambda: _restore_os_signal_handlers(previous_handlers)



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
    bot = bundle.context.telegram_bot
    if bot is None:
        return None
    return asyncio.create_task(_run_interactive_telegram_bot_until_stop(bot, telegram_stop))


async def _notify_async_cli_startup(
    bundle: NautilusRuntimeBundle,
    strategy_names: Sequence[str],
    runtime_logger: logging.Logger,
) -> None:
    await asyncio.to_thread(_rebind_market_discovery_client, bundle.context)
    try:
        await bundle.observability.notify_startup(
            strategy_names,
            sandbox_book_type=bundle.context.settings.runtime.nautilus.sandbox_book_type,
        )
    except Exception:
        runtime_logger.exception("Nautilus startup notification failed")


async def _run_async_node_with_report_loop(
    node: _NautilusNodeLike,
    context: NautilusRuntimeContext,
    event: asyncio.Event,
) -> None:
    report_task = asyncio.create_task(_run_nautilus_report_loop(context, event))
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
        await _stop_nautilus_services(bundle.context)
    finally:
        cleanup_signals()



def _prepare_sync_cli_bundle(settings: Settings) -> NautilusRuntimeBundle:
    _write_runtime_startup_marker_best_effort(_runtime_startup_marker_path(settings))
    context, discovered_markets, observability = asyncio.run(
        _prepare_nautilus_runtime_context(settings)
    )
    _rebind_market_discovery_client(context)
    bundle = _build_nautilus_runtime_bundle(
        settings,
        context,
        discovered_markets,
        observability,
    )
    _write_runtime_heartbeat_best_effort(
        _runtime_heartbeat_path(bundle.context.settings),
        phase="starting",
    )
    return bundle


def _run_sync_cli_main(
    bundle: NautilusRuntimeBundle,
    node: _NautilusNodeLike,
    settings: Settings,
    strategy_names: list[str],
    runtime_logger: logging.Logger,
) -> tuple[_InteractiveTelegramBotThread | None, _NautilusReportLoopThread | None]:
    starter = getattr(bundle.observability, "start", None)
    if callable(starter):
        _ = starter()
    telegram_bot_thread = _start_interactive_telegram_bot_thread(bundle.context)
    report_loop_thread = _start_nautilus_report_loop_thread(bundle.context)
    try:
        asyncio.run(
            bundle.observability.notify_startup(
                strategy_names,
                sandbox_book_type=bundle.context.settings.runtime.nautilus.sandbox_book_type,
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
            "LiveNode.run returned unexpectedly with %d strategies active",
            len(strategy_names),
        )
    return telegram_bot_thread, report_loop_thread


def _finalize_sync_cli_runtime(
    bundle: NautilusRuntimeBundle,
    node: _NautilusNodeLike,
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
        asyncio.run(_stop_nautilus_services(bundle.context))
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

    def cleanup_signals() -> None:
        return None
    if _runtime_intercepts_os_signals(bundle.context.settings):
        cleanup_signals = _install_sync_os_signal_handlers(request_stop)
    runtime_logger = cast(logging.Logger, bundle.context.logger)
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
