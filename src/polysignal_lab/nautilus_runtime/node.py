from __future__ import annotations

import asyncio
import logging
from datetime import timezone
from typing import cast

from polysignal_lab.config import Settings, load_settings
from polysignal_lab.domain.market import Market as Market
from polysignal_lab.domain.missing_values import bind_missing_value_counter
from polysignal_lab.nautilus_runtime.node_builder import (
    NautilusRuntimeBundle,
    NautilusRuntimeContext,
    PolymarketInstrumentProviderConfig as PolymarketInstrumentProviderConfig,
    _Disposable as _Disposable,
    build_live_node as build_live_node,
    build_nautilus_runtime as build_nautilus_runtime,
    build_nautilus_runtime_context as build_nautilus_runtime_context,
    build_runtime_node,
)
from polysignal_lab.nautilus_runtime.node_cli import (
    run_nautilus_cli_async as run_nautilus_cli_async,
)
from polysignal_lab.nautilus_runtime.node_probes import (
    _runtime_heartbeat_path,
    _runtime_startup_marker_path,
    _write_runtime_heartbeat_best_effort,
    _write_runtime_startup_marker_best_effort,
)
from polysignal_lab.nautilus_runtime.node_lifecycle import (
    _finalize_async_cli_runtime as _finalize_async_cli_runtime,
    _finalize_sync_cli_runtime,
    _notify_async_cli_startup as _notify_async_cli_startup,
    _run_async_node_until_stop as _run_async_node_until_stop,
    _run_sync_cli_main,
    _start_runtime_observability as _start_runtime_observability,
    _strategy_names_from_bundle,
)
from polysignal_lab.nautilus_runtime.os_signals import (
    _install_sync_os_signal_handlers,
    _reset_process_stop_request,
    _runtime_intercepts_os_signals,
    request_process_stop,
)
from polysignal_lab.nautilus_runtime.observability import (
    NautilusEventStoreAdapter,
    NautilusNotifierAdapter,
    ObservabilityService,
    bind_runtime_observability,
)
from polysignal_lab.nautilus_runtime.runtime_logging import configure_runtime_logging
from polysignal_lab.observability.liveness_watchdog import (
    HealthAlertDispatcher,
    LivenessWatchdog,
)
from polysignal_lab.publish.telegram_publisher import TelegramPublisher
from polysignal_lab.nautilus_runtime.runtime_registration import enabled_strategy_names
from polysignal_lab.nautilus_runtime.signal_notifications import (
    _notify_accepted_signal,
    _notify_daily_report,
    _notify_report_result,
)

UTC = timezone.utc
logger = logging.getLogger(__name__)


def _build_liveness_watchdog(settings: Settings) -> LivenessWatchdog:
    """Wire alerting and restart recovery to the runtime watchdog.

    Health alerts travel through a dispatcher that owns both its delivery
    thread and its asyncio loop: the watchdog poll never awaits Telegram, and
    a send can never hit a closed application event loop (issue69 live failure
    ``RuntimeError: Event loop is closed`` — the old closure cached one loop
    and the runtime's shared httpx client). Each attempt gets a fresh
    publisher, so no loop-bound client is ever reused.
    """
    telegram = settings.telegram
    notify_enabled = telegram.enabled and telegram.send_health_alerts
    if not notify_enabled:
        return LivenessWatchdog(settings, lambda _message: None)
    dispatcher = HealthAlertDispatcher(
        settings,
        publisher_factory=lambda: TelegramPublisher(settings.telegram),
    )
    return LivenessWatchdog(settings, dispatcher.submit, dispatcher=dispatcher)


async def _prepare_nautilus_runtime_context(
    settings: Settings,
) -> tuple[NautilusRuntimeContext, ObservabilityService]:
    context = build_nautilus_runtime_context(settings)
    notifier = NautilusNotifierAdapter(context.publisher)
    observability = ObservabilityService(
        health=context.health,
        store=NautilusEventStoreAdapter(context.persistence),
        notifier=notifier,
        liveness_watchdog=_build_liveness_watchdog(settings),
        accepted_signal_notifier=lambda signal, stake_usdc: _notify_accepted_signal(
            context,
            signal,
            stake_usdc,
        ),
        report_result_notifier=lambda result: _notify_report_result(context, result),
        daily_report_notifier=lambda framework_time: _notify_daily_report(
            context,
            framework_time,
        ),
    )
    # Importable strategies resolve this process-local handle during construction.
    bind_runtime_observability(observability)
    # Missing-value collapses on the persistence path are counted into the same
    # health registry; unbound (offline scripts, tests) simply means no counting.
    bind_missing_value_counter(context.health)
    return context, observability


def _current_markets_for_build(settings: Settings) -> tuple[Market, ...]:
    """Best-effort current market set for node build (adapter cache pre-fill).

    issue69 live evidence: the Polymarket adapter returns OK from a subscribe
    for an uncached instrument without ever sending a wire subscription, while
    the engine records it as subscribed and never retries. Passing the current
    markets into build_runtime_node pre-fills the adapter's instrument cache via
    load_ids, so first subscriptions actually land on the wire. A page-capped
    discovery avoids the gamma events pagination that 422s past ~2000 rows, and
    discovery failure must never block node construction (incremental provider
    refresh covers the gap later).
    """
    try:
        from polysignal_lab.data.polymarket_market_discovery import (  # pyright: ignore[reportAttributeAccessIssue]
            MarketDiscovery,
        )

        rotation = getattr(getattr(getattr(settings, "runtime", None), "nautilus", None), "market_rotation", None)
        include_next = (
            getattr(rotation, "include_next_periods", 0) if rotation is not None else 0
        )
        discovery = MarketDiscovery(
            settings.data.polymarket,
            settings.markets,
        )
        return tuple(
            discovery.discover_sync(
                include_next_periods=int(include_next),
                max_event_pages=2,
            )
        )
    except Exception:
        logger.warning(
            "runtime market discovery unavailable; node built with empty market set",
            exc_info=True,
        )
        return ()


def _build_nautilus_runtime_bundle(
    settings: Settings,
    context: NautilusRuntimeContext,
    observability: ObservabilityService,
) -> NautilusRuntimeBundle:
    node = build_runtime_node(
        settings,
        markets=_current_markets_for_build(settings),
    )
    context.nautilus_cache = getattr(node, "cache", None)
    context.nautilus_portfolio = getattr(node, "portfolio", None)
    return NautilusRuntimeBundle(
        context=context,
        node=node,
        observability=observability,
        strategy_names=enabled_strategy_names(settings),
    )


def _prepare_sync_cli_bundle(settings: Settings) -> NautilusRuntimeBundle:
    _write_runtime_startup_marker_best_effort(_runtime_startup_marker_path(settings))
    context, observability = asyncio.run(_prepare_nautilus_runtime_context(settings))
    bundle = _build_nautilus_runtime_bundle(settings, context, observability)
    _write_runtime_heartbeat_best_effort(
        _runtime_heartbeat_path(bundle.context.settings),
        phase="starting",
    )
    return bundle


def _bind_supervised_restart(bundle: NautilusRuntimeBundle, node: object) -> None:
    watchdog = bundle.observability.liveness_watchdog
    if watchdog is None:
        return

    def restart_node(reason: str) -> None:
        logger.error("supervised_node_restart reason=%s", reason)
        request_process_stop()

    watchdog.set_restart_callback(restart_node)


def run_nautilus_cli(settings: Settings | None = None) -> None:
    resolved = settings or load_settings()
    configure_runtime_logging(resolved)
    bundle = _prepare_sync_cli_bundle(resolved)
    _reset_process_stop_request()
    node = bundle.node

    def request_stop() -> None:
        request_process_stop()

    _bind_supervised_restart(bundle, node)

    def cleanup_signals() -> None:
        return None

    if _runtime_intercepts_os_signals(bundle.context.settings):
        cleanup_signals = _install_sync_os_signal_handlers(request_stop)
    runtime_logger = cast(
        logging.Logger,
        getattr(bundle.context, "logger", logging.getLogger(__name__)),
    )
    strategy_names = _strategy_names_from_bundle(bundle)
    try:
        _run_sync_cli_main(
            bundle,
            node,
            resolved,
            strategy_names,
            runtime_logger,
        )
    finally:
        _finalize_sync_cli_runtime(
            bundle,
            node,
            runtime_logger,
            cleanup_signals,
        )


def main() -> int:
    try:
        run_nautilus_cli()
    except RuntimeError as exc:
        print(f"nautilus: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
