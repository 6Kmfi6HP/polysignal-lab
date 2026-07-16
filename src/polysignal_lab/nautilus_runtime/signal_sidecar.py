"""
Input: __future__, __future__.annotations, asyncio, logging, threading, collections.abc, collections.abc.Awaitable, collections.abc.Callable, contextlib, contextlib.suppress
Output: _PublishResultLike, _AcceptedSignalPublisher, _InteractiveBotLike
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from datetime import date
from typing import Protocol, cast

from polysignal_lab.app import scheduler_health
from polysignal_lab.domain.signal import SignalCandidate

logger = logging.getLogger("polysignal_lab.nautilus_runtime.signal_sidecar")


class _PublishResultLike(Protocol):
    def as_dict(self) -> dict[str, str | None]: ...


class _AcceptedSignalPublisher(Protocol):
    async def publish_signal_once(
        self,
        signal: SignalCandidate,
        stake_usdc: float,
    ) -> _PublishResultLike: ...


class _InteractiveBotLike(Protocol):
    async def start(self) -> object: ...
    async def stop(self) -> object: ...


_InteractiveTelegramBotThread = tuple[threading.Thread, threading.Event]
_NautilusReportLoopThread = tuple[threading.Thread, threading.Event]


async def _stop_nautilus_services(services: object) -> None:
    """Mark services as stopped and persist final health snapshot."""
    if bool(getattr(services, "_nautilus_runtime_owned_by_live_node", False)):
        setattr(services, "_running", False)
        try:
            scheduler_health.persist_health_snapshot(services)
        except Exception as exc:
            cast(logging.Logger, getattr(services, "logger", logger)).warning(
                "Failed to persist Nautilus health snapshot: %s",
                exc,
            )
        return

    setattr(services, "_running", False)
    try:
        scheduler_health.persist_health_snapshot(services)
    except Exception as exc:
        cast(logging.Logger, getattr(services, "logger", logger)).warning(
            "Failed to persist Nautilus health snapshot: %s",
            exc,
        )


async def _publish_accepted_signal_once(
    services: object,
    signal: SignalCandidate,
    stake_usdc: float,
) -> dict[str, str | None]:
    publish = await cast(_AcceptedSignalPublisher, services).publish_signal_once(
        signal,
        stake_usdc,
    )
    return publish.as_dict()


def _publish_accepted_signal_in_background(
    services: object,
    signal: SignalCandidate,
    stake_usdc: float,
) -> None:
    try:
        publish = asyncio.run(_publish_accepted_signal_once(services, signal, stake_usdc))
        scheduler_health.note_publish_result(services, publish)
    except Exception as exc:
        cast(logging.Logger, getattr(services, "logger", logger)).warning(
            "Nautilus accepted signal publish failed for %s: %s",
            signal.signal_id,
            exc,
        )


def _notify_accepted_signal(
    services: object,
    signal: SignalCandidate,
    stake_usdc: float,
) -> None:
    if not getattr(getattr(services, "settings", None), "telegram", None):
        return
    if not getattr(getattr(services, "settings").telegram, "send_signals", False):
        return
    thread = threading.Thread(
        target=_publish_accepted_signal_in_background,
        args=(services, signal, stake_usdc),
        daemon=True,
    )
    thread.start()


async def _publish_paper_result_once(
    services: object,
    result: Mapping[str, object],
) -> dict[str, str | None]:
    publish_service = getattr(services, "publish_service", None)
    publish_fn = (
        None
        if publish_service is None
        else getattr(publish_service, "publish_paper_result", None)
    )
    if not callable(publish_fn):
        raise RuntimeError("publish_service.publish_paper_result is not available")
    publish = await cast(Callable[..., Awaitable[object]], publish_fn)(result)
    as_dict = getattr(publish, "as_dict", None)
    if not callable(as_dict):
        return {}
    return cast(dict[str, str | None], as_dict())


def _publish_paper_result_in_background(
    services: object,
    result: Mapping[str, object],
) -> None:
    try:
        publish = asyncio.run(_publish_paper_result_once(services, result))
        scheduler_health.note_publish_result(services, publish)
    except Exception as exc:
        cast(logging.Logger, getattr(services, "logger", logger)).warning(
            "Nautilus early-exit paper result publish failed for %s: %s",
            result.get("paper_trade_id"),
            exc,
        )
        persistence = getattr(services, "persistence", None)
        insert = None if persistence is None else getattr(persistence, "insert_system_event", None)
        if not callable(insert):
            return
        try:
            from polysignal_lab.utils import new_id, redact_text, utc_iso

            event = {
                "event_id": new_id(
                    "evt",
                    "paper_result_publish_failed",
                    str(result.get("paper_trade_id") or ""),
                ),
                "event_type": "paper_result_publish_failed",
                "severity": "WARNING",
                "created_at": utc_iso(),
                "paper_trade_id": result.get("paper_trade_id"),
                "paper_position_id": result.get("paper_position_id"),
                "signal_id": result.get("signal_id"),
                "error_type": type(exc).__name__,
                "error": redact_text(str(exc)),
            }
            insert(event)
            append_log = getattr(persistence, "append_log", None)
            if callable(append_log):
                append_log("system_events", event)
        except Exception:
            cast(logging.Logger, getattr(services, "logger", logger)).debug(
                "Failed to audit paper_result_publish_failed",
                exc_info=True,
            )


def _notify_paper_result(
    services: object,
    result: Mapping[str, object],
) -> None:
    if not getattr(getattr(services, "settings", None), "telegram", None):
        return
    if not getattr(getattr(services, "settings").telegram, "send_paper_results", False):
        return
    thread = threading.Thread(
        target=_publish_paper_result_in_background,
        args=(services, dict(result)),
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
    services: object,
) -> _InteractiveTelegramBotThread | None:
    bot = cast(object | None, getattr(services, "telegram_bot", None))
    if bot is None:
        return None
    stop_event = threading.Event()
    runtime_logger = cast(logging.Logger, getattr(services, "logger", logger))

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
    services: object,
) -> _NautilusReportLoopThread:
    stop_event = threading.Event()
    runtime_logger = cast(logging.Logger, getattr(services, "logger", logger))

    def _run() -> None:
        async def _main() -> None:
            asyncio_stop = asyncio.Event()

            async def _watch_stop() -> None:
                while not stop_event.is_set():
                    await asyncio.sleep(0.5)
                asyncio_stop.set()

            watcher = asyncio.create_task(_watch_stop())
            try:
                await _run_nautilus_report_loop(services, asyncio_stop)
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
    services: object,
    last_report_date: date | None,
) -> date | None:
    from polysignal_lab.app._settlement_check import check_settlements
    from polysignal_lab.app.scheduler_shared import _generate_iteration_report

    try:
        settled = await check_settlements(services)
        if settled:
            cast(logging.Logger, getattr(services, "logger", logger)).info(
                "Nautilus settlement projections recorded: %d",
                len(settled),
            )
            last_report_date = None
    except Exception:
        cast(logging.Logger, getattr(services, "logger", logger)).exception(
            "Nautilus settlement check failed; continuing report loop"
        )
    return await _generate_iteration_report(services, last_report_date)


async def _run_nautilus_report_loop(
    services: object,
    stop_event: asyncio.Event,
) -> None:
    last_report_date = None
    settings = getattr(services, "settings", None)
    interval_sec = 60.0
    if settings is not None:
        interval_sec = max(float(getattr(settings.markets, "refresh_interval_sec", 60)), 1.0)
    while not stop_event.is_set():
        last_report_date = await _run_nautilus_housekeeping_once(
            services,
            last_report_date,
        )
        try:
            _ = await asyncio.wait_for(stop_event.wait(), timeout=interval_sec)
        except asyncio.TimeoutError:
            continue
