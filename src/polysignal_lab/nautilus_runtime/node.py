from __future__ import annotations

import asyncio
import logging
from datetime import timezone
from typing import cast

from polysignal_lab.config import Settings, load_settings
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
    _runtime_intercepts_os_signals,
)
from polysignal_lab.nautilus_runtime.observability import (
    NautilusEventStoreAdapter,
    NautilusNotifierAdapter,
    ObservabilityService,
    bind_runtime_observability,
)
from polysignal_lab.nautilus_runtime.runtime_logging import configure_runtime_logging
from polysignal_lab.observability.liveness_watchdog import LivenessWatchdog
from polysignal_lab.nautilus_runtime.runtime_registration import enabled_strategy_names
from polysignal_lab.nautilus_runtime.signal_notifications import (
    _notify_accepted_signal,
    _notify_daily_report,
    _notify_report_result,
)

UTC = timezone.utc
logger = logging.getLogger(__name__)


def _build_liveness_watchdog(
    settings: Settings,
    notifier: NautilusNotifierAdapter,
) -> LivenessWatchdog:
    """Wire alerting and supervised restart to the runtime watchdog."""
    telegram = settings.telegram
    notify_enabled = telegram.enabled and telegram.send_health_alerts

    # One long-lived loop for the watchdog thread, matching the notify outbox:
    # the publisher's httpx client is shared with the startup and signal paths.
    loop: list[asyncio.AbstractEventLoop] = []

    def send(message: str) -> None:
        if not notify_enabled:
            return
        if not loop:
            loop.append(asyncio.new_event_loop())
        _ = loop[0].run_until_complete(notifier.send(message, "health_alert"))

    return LivenessWatchdog(settings, send)


async def _prepare_nautilus_runtime_context(
    settings: Settings,
) -> tuple[NautilusRuntimeContext, ObservabilityService]:
    context = build_nautilus_runtime_context(settings)
    notifier = NautilusNotifierAdapter(context.publisher)
    observability = ObservabilityService(
        health=context.health,
        store=NautilusEventStoreAdapter(context.persistence),
        notifier=notifier,
        liveness_watchdog=_build_liveness_watchdog(settings, notifier),
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
    return context, observability


def _build_nautilus_runtime_bundle(
    settings: Settings,
    context: NautilusRuntimeContext,
    observability: ObservabilityService,
) -> NautilusRuntimeBundle:
    node = build_runtime_node(settings)
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
        stopper = getattr(node, "stop", None)
        if callable(stopper):
            _ = stopper()

    watchdog.set_restart_callback(restart_node)


def run_nautilus_cli(settings: Settings | None = None) -> None:
    resolved = settings or load_settings()
    configure_runtime_logging(resolved)
    bundle = _prepare_sync_cli_bundle(resolved)
    node = bundle.node

    def request_stop() -> None:
        stopper = getattr(node, "stop", None)
        if callable(stopper):
            _ = stopper()
            return
        raise KeyboardInterrupt

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
