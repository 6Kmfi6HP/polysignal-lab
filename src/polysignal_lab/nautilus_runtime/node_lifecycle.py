"""
Input: __future__, __future__.annotations, asyncio, inspect, logging, collections.abc, collections.abc.Callable, collections.abc.Sequence, contextlib, contextlib.suppress
Output: None
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable, Sequence
from contextlib import suppress
from typing import cast

from polysignal_lab.config import Settings
from polysignal_lab.nautilus_runtime.node_builder import (
    NautilusRuntimeBundle,
    _Disposable,
)
from polysignal_lab.nautilus_runtime.node_crash import (
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
    run = getattr(node, "run")
    result = await asyncio.to_thread(run)
    if inspect.isawaitable(result):
        await result


async def _stop_node_async(node: object) -> None:
    stop_async = getattr(node, "stop_async", None)
    if callable(stop_async):
        result = stop_async()
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
        cleanup_signals()
