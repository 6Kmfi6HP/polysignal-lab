"""
Input: __future__, __future__.annotations, datetime, datetime.datetime, datetime.timezone, asyncio, inspect, logging, signal, contextlib
Output: run_nautilus_cli, main
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from datetime import timezone

import asyncio
import logging
from collections.abc import Callable, Sequence
from typing import Any, cast

from polysignal_lab.config import Settings, load_settings
from polysignal_lab.data.anchor_price_service import AnchorPriceStore
from polysignal_lab.domain.market import Market
from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor
from polysignal_lab.nautilus_runtime.node_probes import (
    _runtime_heartbeat_path,
    _runtime_startup_marker_path,
    _write_runtime_startup_marker_best_effort,
    _write_runtime_heartbeat_best_effort,
)
from polysignal_lab.nautilus_runtime.node_signals import (
    _runtime_intercepts_os_signals,
)
from polysignal_lab.nautilus_runtime.signal_sidecar import (
    _InteractiveTelegramBotThread,
    _NautilusReportLoopThread,
    _notify_accepted_signal,
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
    ObservabilityService,
)
from polysignal_lab.nautilus_runtime.node_builder import (
    LiveNode,
    NautilusRuntimeBundle,
    NautilusRuntimeContext,
    build_nautilus_runtime_context,
    PolymarketInstrumentProviderConfig,
    _NautilusNodeLike,
    _NativeStrategyLike,
    _load_runtime_classes,
    _runtime_class_triple,
    build_live_node,
    build_nautilus_runtime,
)
from polysignal_lab.nautilus_runtime.strategy_builder import (
    _build_native_strategies,
    _build_policy,
    _native_core_for,
    build_control,
)
from polysignal_lab.nautilus_runtime.node_shared import (
    _rebind_market_discovery_client,
    _install_sync_os_signal_handlers,
)
from polysignal_lab.nautilus_runtime.node_sidecar import (
    _strategy_names_from_bundle,
    _start_async_cli_sidecars,
    _notify_async_cli_startup,
    _run_async_node_with_report_loop,
    _finalize_async_cli_runtime,
    _run_sync_cli_main,
    _finalize_sync_cli_runtime,
)

UTC = timezone.utc

logger = logging.getLogger(__name__)



def _attach_cache_projections(
    node: _NautilusNodeLike,
    registry: MarketCatalog,
    assembler: MarketViewAssembler,
    strategies: Sequence[_NativeStrategyLike],
) -> tuple[object, object]:
    from polysignal_lab.nautilus_runtime.cache_market_data import NautilusCacheMarketDataProvider

    kernel = getattr(node, "kernel", None)
    nautilus_cache = getattr(node, "cache", None) or getattr(kernel, "cache", None)
    nautilus_portfolio = getattr(node, "portfolio", None) or getattr(kernel, "portfolio", None)
    books = NautilusCacheMarketDataProvider(
        nautilus_cache,
        catalog=registry,
    )
    assembler.books = books
    for strategy in strategies:
        strategy_assembler = getattr(strategy, "assembler", None)
        if hasattr(strategy_assembler, "books"):
            strategy_assembler.books = books
    return nautilus_cache, nautilus_portfolio


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
    discovery_worker: object,
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
        discovery_worker=discovery_worker,
        catalog=registry,
        anchor_store=store,
        health=health,
    )



async def _prepare_nautilus_runtime_context(
    settings: Settings,
) -> tuple[NautilusRuntimeContext, tuple[Market, ...], ObservabilityService]:
    context = build_nautilus_runtime_context(settings)
    context._nautilus_runtime_owned_by_live_node = True
    discovered_markets = tuple(await context.market_universe.refresh_once())
    observability = ObservabilityService(
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


def _build_nautilus_runtime_bundle(
    settings: Settings,
    context: NautilusRuntimeContext,
    discovered_markets: tuple[Market, ...],
    observability: ObservabilityService,
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
    context.nautilus_cache = components.get("cache")
    context.nautilus_portfolio = components.get("portfolio")
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
    runtime_logger = cast(logging.Logger, getattr(bundle.context, "logger", logging.getLogger(__name__)))
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
