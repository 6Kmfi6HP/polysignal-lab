"""
Input: __future__, __future__.annotations, asyncio, logging, threading, collections.abc, collections.abc.Awaitable, collections.abc.Callable, contextlib, contextlib.suppress
Output: outbound signal/report notifications and runtime health shutdown
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable, Mapping
from typing import Protocol, cast

from polysignal_lab.app import scheduler_health
from polysignal_lab.domain.signal import SignalCandidate

logger = logging.getLogger("polysignal_lab.nautilus_runtime.signal_notifications")


class _PublishResultLike(Protocol):
    def as_dict(self) -> dict[str, str | None]: ...


class _AcceptedSignalPublisher(Protocol):
    async def publish_signal_once(
        self,
        signal: SignalCandidate,
        stake_usdc: float,
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


async def _publish_report_result_once(
    services: object,
    result: Mapping[str, object],
) -> dict[str, str | None]:
    publish_service = getattr(services, "publish_service", None)
    publish_fn = (
        None
        if publish_service is None
        else getattr(publish_service, "publish_report_result", None)
    )
    if not callable(publish_fn):
        raise RuntimeError("publish_service.publish_report_result is not available")
    publish = await cast(Callable[..., Awaitable[object]], publish_fn)(result)
    as_dict = getattr(publish, "as_dict", None)
    if not callable(as_dict):
        return {}
    return cast(dict[str, str | None], as_dict())


def _publish_report_result_in_background(
    services: object,
    result: Mapping[str, object],
) -> None:
    try:
        publish = asyncio.run(_publish_report_result_once(services, result))
        scheduler_health.note_publish_result(services, publish)
    except Exception as exc:
        cast(logging.Logger, getattr(services, "logger", logger)).warning(
            "Nautilus early-exit report result publish failed for %s: %s",
            result.get("report_result_id"),
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
                "Failed to audit report_result_publish_failed",
                exc_info=True,
            )


def _notify_report_result(
    services: object,
    result: Mapping[str, object],
) -> None:
    if not getattr(getattr(services, "settings", None), "telegram", None):
        return
    if not getattr(getattr(services, "settings").telegram, "send_report_results", False):
        return
    thread = threading.Thread(
        target=_publish_report_result_in_background,
        args=(services, dict(result)),
        daemon=True,
    )
    thread.start()
