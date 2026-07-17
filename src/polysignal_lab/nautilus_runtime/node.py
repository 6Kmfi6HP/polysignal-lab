"""
Input: __future__, __future__.annotations, datetime, datetime.datetime, datetime.timezone, asyncio, inspect, logging, signal, contextlib
Output: run_nautilus_cli, main
Pos: Application code

Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from datetime import timezone

import asyncio
import logging
from collections.abc import Callable, Sequence
from typing import cast

from polysignal_lab.config import Settings, load_settings
from polysignal_lab.data.anchor_price_service import AnchorPriceStore
from polysignal_lab.domain.market import Market
from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicy
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
    _notify_accepted_signal,
    _notify_report_result,
    _start_interactive_telegram_bot_thread,  # noqa: F401  # re-exported for tests and lazy imports
    _stop_interactive_telegram_bot_thread,  # noqa: F401
    _stop_nautilus_services,  # noqa: F401
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
    NautilusRuntimeBundle,
    NautilusRuntimeContext,
    build_nautilus_runtime_context,
    PolymarketInstrumentProviderConfig,  # noqa: F401
    _Disposable,  # noqa: F401
    _NativeStrategyLike,
    _load_runtime_classes,  # noqa: F401
    _runtime_class_triple,
    build_live_node,
    build_nautilus_runtime,  # noqa: F401
)
from polysignal_lab.nautilus_runtime.strategy_builder import (
    _build_native_strategies,  # noqa: F401
    _build_policy,  # noqa: F401
    _native_core_for,  # noqa: F401
    )
from polysignal_lab.nautilus_runtime.node_shared import (
    _rebind_market_discovery_client,
    _install_sync_os_signal_handlers,
)
from polysignal_lab.nautilus_runtime.node_sidecar import (
    _strategy_names_from_bundle,
    _start_async_cli_sidecars,  # noqa: F401
    _notify_async_cli_startup,  # noqa: F401
    _run_async_node_with_report_loop,  # noqa: F401
    _finalize_async_cli_runtime,  # noqa: F401
    _run_sync_cli_main,
    _finalize_sync_cli_runtime,
)

UTC = timezone.utc

logger = logging.getLogger(__name__)



def _attach_cache_projections(
    node: object,
    registry: MarketCatalog,
    assembler: MarketViewAssembler,
    strategies: Sequence[_NativeStrategyLike],
) -> tuple[object, object]:
    from polysignal_lab.nautilus_runtime.node_builder_components import (
        CacheBoundBookDataProvider,
    )

    _ = registry
    handle_cache = getattr(node, "cache", None)
    handle_portfolio = getattr(node, "portfolio", None)
    kernel = getattr(node, "node", None) or getattr(node, "kernel", None)
    nautilus_cache = (
        handle_cache
        or getattr(node, "cache", None)
        or getattr(kernel, "cache", None)
    )
    nautilus_portfolio = (
        handle_portfolio
        or getattr(node, "portfolio", None)
        or getattr(kernel, "portfolio", None)
    )
    if nautilus_cache is None or nautilus_portfolio is None:
        from_components_cache = None
        from_components_portfolio = None
        for component in (*strategies, getattr(node, "trader", None)):
            if component is None:
                continue
            from_components_cache = getattr(component, "cache", None)
            from_components_portfolio = getattr(component, "portfolio", None)
            if from_components_cache is not None and from_components_portfolio is not None:
                break
        nautilus_cache = nautilus_cache or from_components_cache
        nautilus_portfolio = nautilus_portfolio or from_components_portfolio
    if nautilus_cache is not None and hasattr(node, "_cache"):
        setattr(node, "_cache", nautilus_cache)
    if nautilus_portfolio is not None and hasattr(node, "_portfolio"):
        setattr(node, "_portfolio", nautilus_portfolio)

    books = getattr(assembler, "books", None)
    if not isinstance(books, CacheBoundBookDataProvider):
        raise RuntimeError("MarketView assembler must use CacheBoundBookDataProvider")
    if nautilus_cache is None:
        # Leave unbound: reads fail closed until Cache exists.
        return nautilus_cache, nautilus_portfolio

    books.bind_cache(nautilus_cache)
    for strategy in strategies:
        strategy_assembler = getattr(strategy, "assembler", None)
        if strategy_assembler is None:
            continue
        strategy_books = getattr(strategy_assembler, "books", None)
        if strategy_books is books:
            continue
        if isinstance(strategy_books, CacheBoundBookDataProvider):
            strategy_books.bind_cache(nautilus_cache)
            continue
        if hasattr(strategy_assembler, "books"):
            strategy_assembler.books = books
    return nautilus_cache, nautilus_portfolio


def _register_runtime_trader_components(
    node: object,
    market_rotation_actor: object,
    policy: DecisionPolicy | None,
    strategies: Sequence[_NativeStrategyLike],
    *,
    settings: Settings,
    configured_markets: Sequence[Market],
    configured_condition_ids: Sequence[str],
    reporting_actor: object | None = None,
) -> list[_NativeStrategyLike]:
    """Register actors/strategies on LiveNode kernel; return kernel-owned strategies."""

    kernel = getattr(node, "node", node)
    trader = getattr(node, "trader", None)

    supports_importable = callable(getattr(kernel, "add_strategy_from_config", None)) and callable(
        getattr(kernel, "add_actor_from_config", None)
    )
    if supports_importable:
        from nautilus_trader.core import nautilus_pyo3

        from polysignal_lab.nautilus_runtime.decision_policy_actor import (
            DecisionPolicyActor,
            DecisionPolicyActorConfig,
        )
        from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy
        from polysignal_lab.nautilus_runtime.runtime_configs import PolySignalStrategyConfig

        def fqn(component: type[object]) -> str:
            return f"{component.__module__}:{component.__qualname__}"

        policy_config = DecisionPolicyActorConfig.build(settings)
        kernel.add_actor_from_config(
            nautilus_pyo3.ImportableActorConfig(
                actor_path=fqn(DecisionPolicyActor),
                config_path=fqn(DecisionPolicyActorConfig),
                config=policy_config.importable_dict(),
            )
        )
        enabled_strategy_names = tuple(
            name
            for name in settings.strategies.explicit_strategy_names()
            if bool(getattr(settings.strategies, name).enabled)
        )
        if enabled_strategy_names:
            strategy_config = PolySignalStrategyConfig.build(
                settings,
                tuple(configured_markets),
                tuple(configured_condition_ids),
            )
            kernel.add_strategy_from_config(
                nautilus_pyo3.ImportableStrategyConfig(
                    strategy_path=fqn(PolySignalNativeStrategy),
                    config_path=fqn(PolySignalStrategyConfig),
                    config=strategy_config.importable_dict(),
                )
            )
        _load_runtime_trader_state(node)
        return []

    if trader is None:
        raise RuntimeError("LiveNode runtime requires a trader facade for actor/strategy wiring")
    trader.add_actor(market_rotation_actor)
    if reporting_actor is not None:
        trader.add_actor(reporting_actor)
    for strategy in strategies:
        trader.add_strategy(strategy)
    _load_runtime_trader_state(node)
    build = getattr(node, "build", None)
    if callable(build):
        build()
    return list(strategies)


def _load_runtime_trader_state(node: object) -> None:
    config = getattr(node, "config", None)
    if not bool(getattr(config, "load_state", False)):
        return
    trader = getattr(node, "trader", None)
    load = getattr(trader, "load", None) if trader is not None else None
    if not callable(load):
        raise RuntimeError("native state persistence requires Trader.load()")
    load()


def _build_market_rotation_actor(
    *,
    settings: Settings,
    startup_markets: Sequence[Market],
    market_universe: object,
    discovery_worker: object,
    registry: MarketCatalog,
    store: AnchorPriceStore | None,
    health: object | None,
    markets_projection: object | None = None,
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
        markets_projection=markets_projection,
    )



async def _prepare_nautilus_runtime_context(
    settings: Settings,
) -> tuple[NautilusRuntimeContext, tuple[Market, ...], ObservabilityService]:
    from polysignal_lab.nautilus_runtime.live_node import (
        validate_polymarket_market_data_credentials,
    )

    validate_polymarket_market_data_credentials()
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
        report_result_notifier=lambda result: _notify_report_result(context, result),
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
        reporting_services=context,
    )
    execution_metadata = {
        "sandbox_book_type": settings.runtime.nautilus.sandbox_book_type,
    }
    context.nautilus_cache = components.get("cache")
    context.nautilus_portfolio = components.get("portfolio")
    context.market_catalog = components.get("registry")
    context.execution_metadata = execution_metadata
    bot = context.telegram_bot
    if bot is not None:
        nautilus_cache = context.nautilus_cache
        if nautilus_cache is not None:
            from polysignal_lab.nautilus_runtime.cache_market_data import (
                NautilusCacheMarketDataProvider,
            )

            bot.books = NautilusCacheMarketDataProvider(
                nautilus_cache,
                catalog=cast(MarketCatalog, components["registry"]),
            )


    return NautilusRuntimeBundle(
        context=context,
        components=components,
        bridge_registry=cast(MarketCatalog, components["registry"]),
        node=components["node"],
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
    try:
        telegram_bot_thread = _run_sync_cli_main(
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
