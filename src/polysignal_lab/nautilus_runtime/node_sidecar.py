"""
Input: __future__, __future__.annotations, asyncio, inspect, logging, contextlib, collections.abc, collections.abc.Callable, collections.abc.Sequence, typing, typing.cast
Output: _strategy_names_from_bundle, _start_async_cli_sidecars, _notify_async_cli_startup, _run_async_node_with_report_loop, _finalize_async_cli_runtime, _run_sync_cli_main, _finalize_sync_cli_runtime
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
    NautilusRuntimeContext,
    _Disposable,
    _NautilusNodeLike,
)
from polysignal_lab.nautilus_runtime.node_crash import (
    _dump_thread_stacks,
    _install_crash_logger,
)
from polysignal_lab.nautilus_runtime.signal_sidecar import (
    _InteractiveTelegramBotThread,
    _NautilusReportLoopThread,
    _run_interactive_telegram_bot_until_stop,
    _run_nautilus_report_loop,
    _start_interactive_telegram_bot_thread,
    _start_nautilus_report_loop_thread,
    _stop_interactive_telegram_bot_thread,
    _stop_nautilus_report_loop_thread,
    _stop_nautilus_services,
)

logger = logging.getLogger("polysignal_lab.nautilus_runtime.node_sidecar")


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
    from polysignal_lab.nautilus_runtime.node_shared import _rebind_market_discovery_client

    await asyncio.to_thread(_rebind_market_discovery_client, bundle.context)
    try:
        await bundle.observability.notify_startup(
            strategy_names,
            sandbox_book_type=bundle.context.settings.runtime.nautilus.sandbox_book_type,
        )
    except Exception:
        runtime_logger.exception("Nautilus startup notification failed")


async def _run_node_async(node: _NautilusNodeLike) -> None:
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


async def _stop_node_async(node: _NautilusNodeLike) -> None:
    stop_async = getattr(node, "stop_async", None)
    if callable(stop_async):
        result = stop_async()
    else:
        stop = getattr(node, "stop", None)
        result = await asyncio.to_thread(stop) if callable(stop) else None
    if inspect.isawaitable(result):
        await result


async def _run_async_node_with_report_loop(
    node: _NautilusNodeLike,
    context: NautilusRuntimeContext,
    event: asyncio.Event,
) -> None:
    report_task = asyncio.create_task(_run_nautilus_report_loop(context, event))
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
        _ = report_task.cancel()
        with suppress(asyncio.CancelledError):
            await report_task
        if isinstance(node, _Disposable):
            node.dispose()


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
            "TradingNode.run returned unexpectedly with %d strategies active",
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
