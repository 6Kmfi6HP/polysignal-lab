"""Signal/publish/telegram sidecar helpers extracted from node.py."""
from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, date, datetime
from typing import Protocol, cast, runtime_checkable

from polysignal_lab.app.scheduler import PolySignalScheduler
from polysignal_lab.app import scheduler_health
from polysignal_lab.app.services.publish_service import PublishService
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.publish.telegram_publisher import TelegramPublisher

logger = logging.getLogger("polysignal_lab.nautilus_runtime.signal_sidecar")


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


_InteractiveTelegramBotThread = tuple[threading.Thread, threading.Event]
_NautilusReportLoopThread = tuple[threading.Thread, threading.Event]


async def _stop_nautilus_scheduler(scheduler: object) -> None:
    if bool(getattr(scheduler, "_nautilus_runtime_owned_by_live_node", False)):
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
