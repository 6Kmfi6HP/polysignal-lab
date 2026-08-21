from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import cast

from polysignal_lab.config import Settings, load_settings
from polysignal_lab.nautilus_runtime.node_crash import (
    _asyncio_exception_handler,
    _crash_log_path,
    _install_crash_logger,
)
from polysignal_lab.nautilus_runtime.node_probes import (
    _runtime_heartbeat_path,
    _runtime_startup_marker_path,
    _write_runtime_startup_marker_best_effort,
    _write_runtime_heartbeat_best_effort,
)
from polysignal_lab.nautilus_runtime.os_signals import (
    _install_async_os_signal_handlers,
    _reset_process_stop_request,
    _runtime_intercepts_os_signals,
)
from polysignal_lab.nautilus_runtime.runtime_logging import configure_runtime_logging

logger = logging.getLogger("polysignal_lab.nautilus_runtime.node_cli")


async def run_nautilus_cli_async(
    settings: Settings | None = None,
    stop_event: asyncio.Event | None = None,
) -> object:
    """Run the Nautilus CLI with async orchestration and signal handling."""
    # Delayed import to avoid circular dependency — node module owns
    # the runtime construction and runtime lifecycle helpers that this function
    # orchestrates.
    from polysignal_lab.nautilus_runtime.node import (
        _finalize_async_cli_runtime,
        _notify_async_cli_startup,
        _run_async_node_until_stop,
        _start_runtime_observability,
        _strategy_names_from_bundle,
        build_nautilus_runtime,
    )

    event = stop_event or asyncio.Event()
    if settings is None:
        settings = load_settings()
    configure_runtime_logging(settings)
    _install_crash_logger(
        settings.logging.directory,
        settings.retention.crash_log_max_bytes,
    )
    asyncio.get_running_loop().set_exception_handler(
        _asyncio_exception_handler(
            _crash_log_path(settings.logging.directory),
            settings.retention.crash_log_max_bytes,
        )
    )
    _write_runtime_startup_marker_best_effort(_runtime_startup_marker_path(settings))
    bundle = await build_nautilus_runtime(settings)
    _write_runtime_heartbeat_best_effort(
        _runtime_heartbeat_path(bundle.context.settings),
        phase="starting",
    )
    node = bundle.node
    loop = asyncio.get_running_loop()
    _reset_process_stop_request()

    request_stop: Callable[[], None] = event.set
    runtime_logger = cast(logging.Logger, getattr(bundle.context, "logger", logger))

    def cleanup_signals() -> None:
        return None

    runtime_settings = getattr(bundle.context, "settings", settings)
    if _runtime_intercepts_os_signals(runtime_settings):
        cleanup_signals = _install_async_os_signal_handlers(loop, request_stop)

    try:
        await _start_runtime_observability(bundle)
        strategy_names = _strategy_names_from_bundle(bundle)
        await _notify_async_cli_startup(bundle, strategy_names, runtime_logger)
        print(f"Nautilus runtime ready - {len(strategy_names)} strategies")
        if stop_event is not None and stop_event.is_set():
            return node
        await _run_async_node_until_stop(node, event)
    finally:
        await _finalize_async_cli_runtime(
            bundle,
            event,
            runtime_logger,
            cleanup_signals,
        )
    return node
