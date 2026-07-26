from __future__ import annotations

import asyncio
import logging
import queue
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, cast

from polysignal_lab.app import scheduler_health
from polysignal_lab.domain.signal import SignalCandidate

logger = logging.getLogger("polysignal_lab.nautilus_runtime.signal_notifications")

# Single process-wide outbox: Strategy callbacks only put(); one worker drains.
# Trading paths must never block on Telegram I/O (Nautilus side-effect isolation).
_OUTBOX: queue.SimpleQueue[object] = queue.SimpleQueue()
_worker_thread: threading.Thread | None = None
_WORKER_LOCK = threading.Lock()
_STOP = object()


@dataclass(frozen=True, slots=True)
class _AcceptedSignalJob:
    services: object
    signal: SignalCandidate
    stake_usdc: float


@dataclass(frozen=True, slots=True)
class _ReportResultJob:
    services: object
    result: Mapping[str, object]


class _PublishResultLike(Protocol):
    def as_dict(self) -> dict[str, str | None]: ...


class _AcceptedSignalPublisher(Protocol):
    async def publish_signal_once(
        self,
        signal: SignalCandidate,
        stake_usdc: float,
    ) -> _PublishResultLike: ...


class _ReportResultPublisher(Protocol):
    async def publish_report_result_once(
        self,
        result: Mapping[str, object],
    ) -> _PublishResultLike: ...


async def _stop_nautilus_services(services: object) -> None:
    """Mark services as stopped and persist final health snapshot."""
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


def _ensure_outbox_worker() -> None:
    """Start or restart the notify outbox worker if it is not alive.

    A dead worker with a sticky started flag is a silent-drop mode: strategy
    callbacks keep enqueueing while Telegram never drains. Detect liveness on
    every enqueue so the process self-heals without touching trading state.
    """
    global _worker_thread
    with _WORKER_LOCK:
        if _worker_thread is not None and _worker_thread.is_alive():
            return
        thread = threading.Thread(
            target=_outbox_worker_loop,
            name="polysignal-notify-outbox",
            daemon=True,
        )
        thread.start()
        _worker_thread = thread


def _outbox_worker_loop() -> None:
    """Drain notify jobs on a dedicated thread with one event loop.

    One long-lived loop avoids asyncio.run() per job (loop create/teardown and
    re-entrancy hazards) while keeping Strategy callbacks free of await.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        while True:
            job = _OUTBOX.get()
            if job is _STOP:
                return
            try:
                if isinstance(job, _AcceptedSignalJob):
                    _publish_accepted_signal_in_background(
                        job.services,
                        job.signal,
                        job.stake_usdc,
                        loop=loop,
                    )
                elif isinstance(job, _ReportResultJob):
                    _publish_report_result_in_background(
                        job.services,
                        job.result,
                        loop=loop,
                    )
            except Exception:
                logger.exception("notify outbox worker failed")
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            logger.debug("notify outbox asyncgen shutdown failed", exc_info=True)
        asyncio.set_event_loop(None)
        loop.close()


def _audit_accepted_signal_publish_failure(
    services: object,
    signal: SignalCandidate,
    exc: BaseException,
) -> None:
    """Persist a best-effort failure record; never raise into the outbox loop."""
    persistence = getattr(services, "persistence", None)
    insert = getattr(persistence, "insert_system_event", None) if persistence else None
    if not callable(insert):
        return
    try:
        from polysignal_lab.utils import new_id, redact_text, utc_iso

        event = {
            "event_id": new_id(
                "evt",
                "accepted_signal_publish_failed",
                str(signal.signal_id),
            ),
            "event_type": "accepted_signal_publish_failed",
            "severity": "WARNING",
            "created_at": utc_iso(),
            "signal_id": signal.signal_id,
            "strategy": signal.strategy,
            "market_id": signal.market_id,
            "error_type": type(exc).__name__,
            "error": redact_text(str(exc)),
        }
        insert(event)
        append_log = getattr(persistence, "append_log", None)
        if callable(append_log):
            append_log("system_events", event)
        insert_publish = getattr(persistence, "insert_telegram_publish", None)
        if callable(insert_publish):
            insert_publish(
                {
                    "publish_id": new_id("tg", "failed", str(signal.signal_id)),
                    "message_type": "signal",
                    "status": "FAILED",
                    "signal_id": signal.signal_id,
                    "telegram_message_id": None,
                    "error": redact_text(str(exc)),
                    "sent_at": None,
                }
            )
    except Exception:
        cast(logging.Logger, getattr(services, "logger", logger)).debug(
            "Failed to audit accepted_signal_publish_failed", exc_info=True
        )


def _publish_accepted_signal_in_background(
    services: object,
    signal: SignalCandidate,
    stake_usdc: float,
    *,
    loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    try:
        if loop is None:
            publish = asyncio.run(
                _publish_accepted_signal_once(services, signal, stake_usdc)
            )
        else:
            publish = loop.run_until_complete(
                _publish_accepted_signal_once(services, signal, stake_usdc)
            )
        scheduler_health.note_publish_result(services, publish)
    except Exception as exc:
        cast(logging.Logger, getattr(services, "logger", logger)).warning(
            "Nautilus accepted signal publish failed for %s: %s",
            signal.signal_id,
            exc,
        )
        _audit_accepted_signal_publish_failure(services, signal, exc)


def _notify_accepted_signal(
    services: object,
    signal: SignalCandidate,
    stake_usdc: float,
) -> None:
    if not getattr(getattr(services, "settings", None), "telegram", None):
        return
    if not getattr(getattr(services, "settings").telegram, "send_signals", False):
        return
    _ensure_outbox_worker()
    _OUTBOX.put(_AcceptedSignalJob(services, signal, stake_usdc))


async def _publish_report_result_once(
    services: object,
    result: Mapping[str, object],
) -> dict[str, str | None]:
    publish = await cast(_ReportResultPublisher, services).publish_report_result_once(
        result
    )
    return publish.as_dict()


def _audit_report_result_publish_failure(
    services: object,
    result: Mapping[str, object],
    exc: BaseException,
) -> None:
    persistence = getattr(services, "persistence", None)
    insert = getattr(persistence, "insert_system_event", None) if persistence else None
    if not callable(insert):
        return
    try:
        from polysignal_lab.utils import new_id, redact_text, utc_iso

        event = {
            "event_id": new_id(
                "evt",
                "report_result_publish_failed",
                str(result.get("report_result_id") or ""),
            ),
            "event_type": "report_result_publish_failed",
            "severity": "WARNING",
            "created_at": utc_iso(),
            "report_result_id": result.get("report_result_id"),
            "report_position_id": result.get("report_position_id"),
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
            "Failed to audit report_result_publish_failed", exc_info=True
        )


def _publish_report_result_in_background(
    services: object,
    result: Mapping[str, object],
    *,
    loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    try:
        if loop is None:
            publish = asyncio.run(_publish_report_result_once(services, result))
        else:
            publish = loop.run_until_complete(
                _publish_report_result_once(services, result)
            )
        scheduler_health.note_publish_result(services, publish)
    except Exception as exc:
        cast(logging.Logger, getattr(services, "logger", logger)).warning(
            "Nautilus early-exit report result publish failed for %s: %s",
            result.get("report_result_id"),
            exc,
        )
        _audit_report_result_publish_failure(services, result, exc)


def _notify_report_result(
    services: object,
    result: Mapping[str, object],
) -> None:
    if not getattr(getattr(services, "settings", None), "telegram", None):
        return
    if not getattr(
        getattr(services, "settings").telegram, "send_report_results", False
    ):
        return
    _ensure_outbox_worker()
    _OUTBOX.put(_ReportResultJob(services, dict(result)))
