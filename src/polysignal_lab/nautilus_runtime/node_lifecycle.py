from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Callable, Sequence
from contextlib import suppress
from typing import cast

from polysignal_lab.config import Settings
from polysignal_lab.domain.missing_values import bind_missing_value_counter
from polysignal_lab.nautilus_runtime.node_builder import (
    NautilusRuntimeBundle,
    _Disposable,
)
from polysignal_lab.nautilus_runtime.node_crash import (
    _crash_log_path,
    _dump_thread_stacks,
    _install_crash_logger,
)
from polysignal_lab.nautilus_runtime.signal_notifications import (
    _stop_nautilus_services,
)

logger = logging.getLogger("polysignal_lab.nautilus_runtime.node_lifecycle")


def _strategy_names_from_bundle(bundle: NautilusRuntimeBundle) -> list[str]:
    return [str(name) for name in bundle.strategy_names if str(name)]


async def _start_runtime_observability(
    bundle: NautilusRuntimeBundle,
) -> None:
    starter = getattr(bundle.observability, "start", None)
    if callable(starter):
        _ = starter()


async def _notify_async_cli_startup(
    bundle: NautilusRuntimeBundle,
    strategy_names: Sequence[str],
    runtime_logger: logging.Logger,
) -> None:
    try:
        await bundle.observability.notify_startup(
            strategy_names,
            sandbox_book_type=bundle.context.settings.runtime.nautilus.sandbox_book_type,
        )
    except Exception:
        runtime_logger.exception("Nautilus startup notification failed")


async def _run_node_async(node: object) -> None:
    run_async = getattr(node, "run_async", None)
    if callable(run_async):
        result = run_async()
        if inspect.isawaitable(result):
            await result
        return
    if _is_pyo3_livenode(node):
        raise RuntimeError(
            "PyO3 LiveNode cannot run via run_nautilus_cli_async: run() is "
            "blocking and must execute on the thread that constructed the node, "
            "but async orchestration offloads it to a worker thread (the pyo3 "
            "unsendable panic in issue #69). Use the synchronous "
            "run_nautilus_cli entry point to run live Nautilus."
        )
    run = getattr(node, "run")
    result = await asyncio.to_thread(run)
    if inspect.isawaitable(result):
        await result


def _is_pyo3_livenode(node: object) -> bool:
    cls = type(node)
    return cls.__name__ == "LiveNode" and str(getattr(cls, "__module__", "")).startswith(
        "nautilus_trader"
    )


async def _stop_node_async(node: object) -> None:
    stop_async = getattr(node, "stop_async", None)
    if callable(stop_async):
        result = stop_async()
    elif _is_pyo3_livenode(node):
        # PyO3 LiveNode is unsendable. Cross-thread stop() is the panic observed
        # in Issue #69; the official run() consumes a process signal/owner intent.
        from polysignal_lab.nautilus_runtime.os_signals import request_process_stop

        request_process_stop()
        return
    else:
        stop = getattr(node, "stop", None)
        result = await asyncio.to_thread(stop) if callable(stop) else None
    if inspect.isawaitable(result):
        await result


async def _run_async_node_until_stop(
    node: object,
    event: asyncio.Event,
) -> None:
    try:
        run_task = asyncio.create_task(_run_node_async(node))
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
            await _stop_node_async(node)
            try:
                await asyncio.wait_for(run_task, timeout=30.0)
            except asyncio.TimeoutError:
                logger.error("Nautilus node did not stop within 30 seconds")
                _ = run_task.cancel()
                with suppress(asyncio.CancelledError):
                    await run_task
        for task in pending:
            _ = task.cancel()
            with suppress(asyncio.CancelledError):
                await task
    finally:
        if isinstance(node, _Disposable):
            node.dispose()


async def _finalize_async_cli_runtime(
    bundle: NautilusRuntimeBundle,
    event: asyncio.Event,
    runtime_logger: logging.Logger,
    cleanup_signals: Callable[[], None],
) -> None:
    try:
        event.set()
        try:
            await bundle.observability.notify_shutdown()
        except Exception:
            runtime_logger.exception("Nautilus shutdown notification failed")
        stopper = getattr(bundle.observability, "stop", None)
        if callable(stopper):
            _ = stopper()
        await _stop_nautilus_services(bundle.context)
    finally:
        from polysignal_lab.nautilus_runtime.observability import (
            bind_runtime_observability,
        )

        bind_runtime_observability(None)
        bind_missing_value_counter(None)
        cleanup_signals()


def _run_sync_cli_main(
    bundle: NautilusRuntimeBundle,
    node: object,
    settings: Settings,
    strategy_names: list[str],
    runtime_logger: logging.Logger,
) -> None:
    starter = getattr(bundle.observability, "start", None)
    if callable(starter):
        _ = starter()
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
    _install_crash_logger(
        settings.logging.directory,
        settings.retention.crash_log_max_bytes,
    )
    _run_live_node(node, runtime_logger)
    if strategy_names:
        _dump_thread_stacks(_crash_log_path(settings.logging.directory))
        runtime_logger.warning(
            "LiveNode.run returned unexpectedly with %d strategies active",
            len(strategy_names),
        )


_NODE_POLL_INTERVAL_SEC = 0.01


def _run_live_node(node: object, runtime_logger: logging.Logger) -> None:
    """Run the LiveNode's event loop via ``run()``.

    1.x shipped a ``start()`` + ``poll()`` pair because its ``run()`` never
    fired synchronous Python clock timers (stranding recovery/rotation
    heartbeats). 2.0 removed both: ``run()`` owns the loop on the current
    thread (msgbus is thread-local), fires the Python clock, and handles
    SIGINT/SIGTERM gracefully — the same stop-intent contract the watchdog
    relies on via ``request_process_stop()``. A callable ``run`` therefore
    supersedes the legacy pair; anything without it (test doubles) falls back.
    """
    run_method = getattr(node, "run", None)
    if callable(run_method):
        run_method()
        return
    start_method = cast(Callable[..., None], getattr(node, "start"))
    poll_method = cast(Callable[..., int], getattr(node, "poll"))
    start_method()
    try:
        while bool(getattr(node, "is_running")):
            _ = poll_method()
            time.sleep(_NODE_POLL_INTERVAL_SEC)
    except Exception:
        runtime_logger.exception("LiveNode poll loop crashed")
        raise


def _finalize_sync_cli_runtime(
    bundle: NautilusRuntimeBundle,
    node: object,
    runtime_logger: logging.Logger,
    cleanup_signals: Callable[[], None],
) -> None:
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
        from polysignal_lab.nautilus_runtime.observability import (
            bind_runtime_observability,
        )

        bind_runtime_observability(None)
        bind_missing_value_counter(None)
        cleanup_signals()
