from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Protocol

from polysignal_lab.config import Settings
from polysignal_lab.observability.liveness_alert import (
    AlertState,
    evaluate_liveness_alert,
)
from polysignal_lab.observability.runtime_health import (
    _replay_grace_active,
    _utc_now,
    evaluate_liveness,
    read_runtime_heartbeat,
    read_runtime_startup_started_at,
)
from polysignal_lab.publish.telegram_publisher import PublishResult
from polysignal_lab.utils import redact_text

logger = logging.getLogger("polysignal_lab.observability.liveness_watchdog")


def _parse_restart_ts(value: str) -> datetime:
    """Parse an ISO timestamp from the restart history file."""
    try:
        return datetime.fromisoformat(value).astimezone(UTC)
    except (ValueError, TypeError):
        # A corrupt entry is ignored rather than crashing the watchdog.
        return datetime.fromtimestamp(0, tz=UTC)


# ── Health-alert delivery boundary ──────────────────────────────────────────
#
# The application event loop is the thing the watchdog exists to report on, so
# alert sends must never run on it and must never cache a loop that the runtime
# may close (issue69 live failure: the watchdog cached one event loop plus the
# runtime's shared httpx client, and after the app loop was closed the send log
# looped "Failed to send runtime health alert: RuntimeError: Event loop is
# closed"). The dispatcher below owns its delivery thread AND its asyncio loop;
# a loop that is closed or unusable is discarded and rebound, never reused.

_LOOP_FATAL_MARKERS = (
    "event loop is closed",
    "no running event loop",
    "attached to a different loop",
    "different event loop",
    "cannot run the event loop",
)


def _loop_fatal(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _LOOP_FATAL_MARKERS)


class _CloseableClient(Protocol):
    async def aclose(self) -> None: ...


class HealthAlertPublisher(Protocol):
    """A publisher the dispatcher can send one health alert through."""

    async def send(self, message: str, message_type: str) -> PublishResult: ...

    @property
    def client(self) -> _CloseableClient: ...


@dataclass(frozen=True, slots=True)
class HealthAlertDispatchStats:
    """Observable delivery counters; all fields are monotonically non-decreasing."""

    enqueued: int = 0
    deduplicated: int = 0
    dropped: int = 0
    sent: int = 0
    failed_attempts: int = 0
    rebinds: int = 0
    last_error: str | None = None


class HealthAlertDispatcher:
    """Thread-safe delivery boundary for runtime health alerts.

    ``submit`` only enqueues (bounded, non-blocking), so a wedged Telegram
    endpoint can never stall the watchdog poll. A dedicated worker thread owns
    a private asyncio loop and runs the publisher inside it; each attempt uses
    a fresh publisher so no loop-bound client is shared with (or resurrected
    from) the application runtime. If the worker's loop is detected closed or
    otherwise unusable, it is discarded and a fresh loop is created — the same
    watchdog instance keeps delivering across a runtime event-loop replacement.
    """

    def __init__(
        self,
        settings: Settings,
        publisher_factory: Callable[[], HealthAlertPublisher],
        *,
        loop_factory: Callable[[], asyncio.AbstractEventLoop] | None = None,
    ) -> None:
        self._settings: Settings = settings
        self._publisher_factory: Callable[[], HealthAlertPublisher] = publisher_factory
        self._loop_factory: Callable[[], asyncio.AbstractEventLoop] = (
            loop_factory or asyncio.new_event_loop
        )
        alert = settings.health.alert
        self._queue: Queue[str] = Queue(maxsize=alert.send_queue_size)
        self._backoff_base_sec: float = alert.send_backoff_base_sec
        self._backoff_max_sec: float = alert.send_backoff_max_sec
        configured_timeout = settings.telegram.publish_timeout_sec
        self._send_timeout_sec: float = (
            configured_timeout if configured_timeout > 0 else 1.0
        )
        self._stop: threading.Event = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._inflight_message: str | None = None
        self._stats: HealthAlertDispatchStats = HealthAlertDispatchStats()
        self._stats_lock: threading.Lock = threading.Lock()

    def stats(self) -> HealthAlertDispatchStats:
        with self._stats_lock:
            return self._stats

    def submit(self, message: str) -> bool:
        """Enqueue one alert without blocking the caller.

        Returns True when the message was accepted, or when an identical
        message is already in flight (that attempt covers this incident).
        Returns False when the bounded queue is full — the caller keeps its
        un-notified state so the next poll retries instead of burning the
        only page for the episode.
        """
        with self._stats_lock:
            if self._inflight_message == message:
                self._stats = replace(
                    self._stats,
                    deduplicated=self._stats.deduplicated + 1,
                )
                return True
        try:
            self._queue.put_nowait(message)
        except Full:
            with self._stats_lock:
                self._stats = replace(
                    self._stats,
                    dropped=self._stats.dropped + 1,
                )
            logger.error(
                "health_alert_submit_dropped queue_full size=%s",
                self._queue.qsize(),
            )
            return False
        with self._stats_lock:
            self._stats = replace(
                self._stats,
                enqueued=self._stats.enqueued + 1,
            )
        return True

    def start(self) -> None:
        """Start the delivery worker; idempotent across calls and restart."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="polysignal-health-alert-dispatcher",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the delivery worker; idempotent. In-flight backoff is
        interrupted, so a worker stuck in a retry sleep exits promptly."""
        self._stop.set()
        thread = self._thread
        if thread is None:
            return
        thread.join(timeout=5.0)
        if thread.is_alive():
            # Wedged on an uninterruptible send; keep the handle so a later
            # start() cannot clear the stop flag and race a second worker.
            logger.warning("Health alert dispatcher did not stop within 5s")
            return
        self._thread = None
        if self._loop is not None:
            try:
                self._loop.close()
            except RuntimeError:
                logger.warning(
                    "Health alert dispatcher loop close failed",
                    exc_info=True,
                )
            self._loop = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                message = self._queue.get(timeout=0.5)
            except Empty:
                continue
            with self._stats_lock:
                self._inflight_message = message
            try:
                self._deliver_with_retry(message)
            finally:
                with self._stats_lock:
                    self._inflight_message = None
                self._queue.task_done()

    def _deliver_with_retry(self, message: str) -> None:
        attempts = 0
        backoff = self._backoff_base_sec
        while True:
            if self._stop.is_set():
                return
            attempts += 1
            delivered = self._deliver_once(message)
            if delivered:
                with self._stats_lock:
                    self._stats = replace(
                        self._stats,
                        sent=self._stats.sent + 1,
                    )
                return
            delay = min(backoff, self._backoff_max_sec)
            error = self._stats.last_error or "unknown"
            logger.warning(
                "health_alert_dispatch_failed attempts=%s retry_in_sec=%s error=%s",
                attempts,
                delay,
                error,
            )
            backoff = backoff * 2.0
            _ = self._stop.wait(delay)

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        loop = self._loop
        if loop is None or loop.is_closed():
            loop = self._loop_factory()
            self._loop = loop
            asyncio.set_event_loop(loop)
            with self._stats_lock:
                self._stats = replace(
                    self._stats,
                    rebinds=self._stats.rebinds + 1,
                )
        return loop

    def _rebind_loop(self) -> None:
        """Discard an unusable loop; the next attempt installs a fresh one."""
        loop = self._loop
        self._loop = None
        if loop is not None:
            try:
                if not loop.is_closed():
                    loop.close()
            except RuntimeError:
                logger.warning(
                    "Health alert dispatcher discarded-loop close failed",
                    exc_info=True,
                )

    def _deliver_once(self, message: str) -> bool:
        loop = self._ensure_loop()
        try:
            publisher = self._publisher_factory()
            publisher_send = publisher.send(message, "health_alert")
            send_coro = asyncio.wait_for(publisher_send, timeout=self._send_timeout_sec)
        except asyncio.CancelledError as exc:
            self._note_attempt_failure(f"publisher setup cancelled: {exc}")
            return False
        except Exception as exc:
            # A sync factory/setup failure never kills the worker: the retry
            # loop creates a fresh publisher on the next attempt.
            self._note_attempt_failure(f"publisher setup failed: {exc}")
            return False
        try:
            result = loop.run_until_complete(send_coro)
        except asyncio.CancelledError as exc:
            # A cancelled send (timeout internals, loop teardown) must close
            # the coroutines and count the attempt — never kill the worker.
            send_coro.close()
            publisher_send.close()
            self._note_attempt_failure(f"send cancelled: {exc}")
            return False
        except RuntimeError as exc:
            send_coro.close()
            publisher_send.close()
            if _loop_fatal(str(exc)):
                self._rebind_loop()
            self._note_attempt_failure(str(exc))
            return False
        except Exception as exc:
            send_coro.close()
            publisher_send.close()
            self._note_attempt_failure(str(exc))
            return False
        finally:
            close_coro = publisher.client.aclose()
            if loop.is_closed():
                # The loop was discarded/closed by the error path above; the
                # per-attempt client is discarded either way, never reused.
                close_coro.close()
            else:
                try:
                    loop.run_until_complete(close_coro)
                except asyncio.CancelledError:
                    close_coro.close()
                except Exception as exc:
                    # Also possible on a loop that died mid-flight: the
                    # per-attempt client is discarded either way, never reused.
                    close_coro.close()
                    logger.warning("health_alert_client_close_failed error=%s", exc)
        if result.status not in {"SENT", "DRY_RUN"}:
            self._note_attempt_failure(result.error or result.status)
            return False
        return True

    def _note_attempt_failure(self, error: str) -> None:
        with self._stats_lock:
            self._stats = replace(
                self._stats,
                failed_attempts=self._stats.failed_attempts + 1,
                last_error=redact_text(error),
            )


# ── Fleet readiness classification ──────────────────────────────────────────
#
# strategy/readiness.py derives a `subscription_state` per condition plus
# current-generation timing fields. The watchdog must not lean on the strategy
# side to stay correct: every bookless/intent-pending state counts toward the
# fleet-never-ready clock, and only a bounded, current-generation recovery
# boundary defers it.

_WAITING_SUBSCRIPTION_STATES = frozenset(
    {
        "unsubscribed",
        "pending_metadata",
        "awaiting_instrument",
        "subscribe_requested",
        "subscribe_issued",
        "awaiting_first_book",
        "stale_orderbook",
        "stale_receipt",
    }
)

_NON_WAITING_SUBSCRIPTION_STATES = frozenset({"ready", "preloaded"})

# The evidence bucket names are the watchdog's stable contract; aliases from
# the strategy side collapse into one recognizable bucket.
_STATE_BUCKET_ALIASES = {
    "pending_metadata": "metadata_pending",
    "awaiting_instrument": "metadata_pending",
    "subscribe_requested": "intent_unconfirmed",
    "subscribe_issued": "intent_unconfirmed",
}


def _parse_detail_timestamp(detail: dict[str, object], key: str) -> datetime | None:
    value = detail.get(key)
    if isinstance(value, datetime):
        zoned = value.replace(tzinfo=UTC) if value.tzinfo is None else value
        return zoned.astimezone(UTC)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value).astimezone(UTC)
        except ValueError:
            return None
    return None


def _classify_detail(
    detail: dict[str, object],
    *,
    observed_at: datetime,
) -> tuple[str, bool]:
    """Classify one readiness detail into (bucket, waiting).

    waiting=True means the condition shows no market-data progress and must
    count toward the fleet-never-ready clock. ``recovery_in_flight`` is still
    waiting, but the fleet clock only accrues when NOT every waiting condition
    is inside its bounded current-generation replay grace. Old-generation
    evidence (``first_bilateral_book_ever_at``) never defers a restart.
    """
    if _replay_grace_active(detail, observed_at=observed_at):
        return "recovery_in_flight", True
    state = detail.get("subscription_state")
    if not isinstance(state, str) or not state:
        # Missing/legacy detail cannot prove progress: fail closed so a
        # silently empty state cannot hide a stuck fleet.
        return "unknown_detail", True
    if state in _WAITING_SUBSCRIPTION_STATES:
        return _STATE_BUCKET_ALIASES.get(state, state), True
    if state in _NON_WAITING_SUBSCRIPTION_STATES:
        return state, False
    # Unrecognized future state: recorded verbatim (transparent), but treated
    # as no progress until the strategy defines it otherwise.
    return state, True


def _oldest_wait_anchor(detail: dict[str, object]) -> datetime | None:
    """Earliest timestamp that pins this condition to its current no-progress
    streak. Anchors from the current generation/recovery lifecycle only; an old
    ``first_bilateral_book_ever_at`` is never a wait anchor."""
    for key in (
        "total_stall_started_at",
        "subscribe_intent_started_at",
        "generation_started_at",
        "adapter_replay_started_at",
    ):
        ts = _parse_detail_timestamp(detail, key)
        if ts is not None:
            return ts
    return None


def _detail_in_flight(detail: dict[str, object]) -> bool:
    if detail.get("subscribe_requested") is True:
        return True
    sides = detail.get("awaiting_book_sides")
    if isinstance(sides, list) and sides:
        return True
    pending = detail.get("pending_instrument_ids")
    if isinstance(pending, list) and pending:
        return True
    return False


@dataclass(frozen=True, slots=True)
class FleetNeverReadyEvidence:
    """Structured, non-secret summary carried in the restart reason."""

    no_progress: int
    fleet: int
    buckets: tuple[tuple[str, int], ...]
    oldest_wait_age_sec: int | None
    generation_started_iso: str | None
    connection_epoch: tuple[object, ...]
    transport_states: tuple[str, ...]
    in_flight: int

    def restart_reason(self) -> str:
        payload: dict[str, object] = {
            "buckets": dict(self.buckets),
            "no_progress": self.no_progress,
            "fleet": self.fleet,
            "oldest_wait_age_sec": self.oldest_wait_age_sec,
            "generation_started_iso": self.generation_started_iso,
            "connection_epoch": list(self.connection_epoch),
            "transport_states": list(self.transport_states),
            "in_flight": self.in_flight,
        }
        return "fleet_never_ready " + json.dumps(
            payload, sort_keys=True, separators=(",", ":")
        )


class LivenessWatchdog:
    """Polls the heartbeat the Docker healthcheck reads, and notifies on failure.

    Runs on its own thread rather than the Nautilus event loop: the failure it
    exists to report is the runtime being wedged, so it must not share a
    scheduler with the thing it watches.
    """

    def __init__(
        self,
        settings: Settings,
        send: Callable[[str], bool | None],
        *,
        now: Callable[[], datetime] | None = None,
        restart: Callable[[str], None] | None = None,
        dispatcher: HealthAlertDispatcher | None = None,
        current_pid: int | None = None,
    ) -> None:
        self._settings: Settings = settings
        self._send: Callable[[str], bool | None] = send
        self._now: Callable[[], datetime] | None = now
        self._restart: Callable[[str], None] | None = restart
        self._dispatcher: HealthAlertDispatcher | None = dispatcher
        self._restart_requested: bool = False
        self._fleet_never_ready_started_at: datetime | None = None
        self._state: AlertState = AlertState()
        self._stop: threading.Event = threading.Event()
        self._thread: threading.Thread | None = None
        # PID of the process this watchdog supervises. Heartbeat files written
        # by a different process (previous boot, shared volume) are never
        # treated as evidence against this boot (issue69 stale-heartbeat loop).
        self._current_pid: int = os.getpid() if current_pid is None else current_pid

    @property
    def state(self) -> AlertState:
        return self._state

    def _heartbeat_path(self) -> Path:
        return Path(self._settings.storage.state_dir) / "runtime_heartbeat.json"

    def _restart_history_path(self) -> Path:
        return Path(self._settings.storage.state_dir) / "runtime_restart_history.json"

    def _read_restart_history(self) -> list[datetime]:
        """Read persisted supervised-restart timestamps (survives container restart)."""
        try:
            raw = json.loads(self._restart_history_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [_parse_restart_ts(ts) for ts in raw if isinstance(ts, str)]

    def _restarts_in_window(
        self,
        *,
        now: datetime,
    ) -> list[datetime]:
        """Return persisted restart timestamps inside the rolling breaker window."""
        window = self._settings.health.restart_gate.restart_circuit_breaker_window_sec
        cutoff = now - timedelta(seconds=window)
        return [ts for ts in self._read_restart_history() if ts >= cutoff]

    def _append_restart_timestamp(self, now: datetime) -> None:
        """Persist a supervised-restart timestamp so the next process sees it."""
        history = self._read_restart_history()
        history.append(now)
        # Prune entries older than the window to keep the file bounded.
        window = self._settings.health.restart_gate.restart_circuit_breaker_window_sec
        cutoff = now - timedelta(seconds=window)
        pruned = [ts for ts in history if ts >= cutoff]
        try:
            self._restart_history_path().write_text(
                json.dumps([ts.isoformat() for ts in pruned]),
                encoding="utf-8",
            )
        except OSError:
            logger.warning("Failed to persist restart history", exc_info=True)

    def _circuit_breaker_open(self, *, now: datetime) -> bool:
        """True when too many supervised restarts landed in the rolling window."""
        max_restarts = self._settings.health.restart_gate.max_restarts_in_window
        recent = self._restarts_in_window(now=now)
        return len(recent) >= max_restarts

    def _startup_started_at(self) -> datetime | None:
        marker = Path(self._settings.storage.state_dir) / "runtime_startup.json"
        try:
            return read_runtime_startup_started_at(marker)
        except (OSError, ValueError, KeyError):
            return None

    def set_restart_callback(self, restart: Callable[[str], None]) -> None:
        self._restart = restart

    def _fleet_never_ready(
        self,
        *,
        now: datetime,
        threshold_sec: int,
    ) -> FleetNeverReadyEvidence | None:
        """Return restart evidence once the fleet showed no progress long enough.

        The fleet clock accrues while at least one condition is stalled — a
        waiting condition OUTSIDE its bounded current-generation replay grace.
        A mix of no-progress buckets (unsubscribed, metadata pending, intent
        unconfirmed, awaiting first book, stale book) does NOT reset the clock,
        and neither does one READY condition: READY proves progress for that
        condition, not for stalled ones, so it must never erase their accrued
        evidence. The clock resets only when no condition is stalled (every
        condition READY/preloaded, or every waiting condition inside its own
        replay window, which may never be renewed by retries). Recovery grace
        defers only the condition whose replay boundary is fresh.
        """
        try:
            heartbeat = read_runtime_heartbeat(self._heartbeat_path())
        except (OSError, ValueError, KeyError, TypeError):
            self._fleet_never_ready_started_at = None
            return None
        if heartbeat.pid is not None and heartbeat.pid != self._current_pid:
            # A different process wrote this heartbeat: it is previous-boot
            # evidence and must never arm or extend the fleet clock.
            self._fleet_never_ready_started_at = None
            return None
        details = tuple(heartbeat.readiness_detail_by_key.values())
        if not details:
            self._fleet_never_ready_started_at = None
            return None
        observed_at = (
            now if now.tzinfo is not None else now.replace(tzinfo=UTC)
        ).astimezone(UTC)
        classified = tuple(
            _classify_detail(detail, observed_at=observed_at) for detail in details
        )
        waiting = sum(1 for _bucket, is_waiting in classified if is_waiting)
        # A condition inside its bounded replay grace is still waiting, but the
        # grace defers it. Only conditions OUTSIDE grace count as stalled and
        # may arm or keep the fleet clock. A READY/preloaded condition is real
        # progress for itself but is NOT evidence that still-stalled conditions
        # recovered: it must never erase their accrued evidence (issue69 mixed
        # READY/stuck fleet — one READY write used to reset the whole timer and
        # the rest of the fleet escaped supervision forever).
        stalled = sum(
            1
            for bucket, is_waiting in classified
            if is_waiting and bucket != "recovery_in_flight"
        )
        if stalled == 0:
            if waiting:
                logger.info(
                    "fleet_never_ready skipped: no condition is stalled "
                    "outside its own bounded replay grace",
                    extra={"detail_count": len(details)},
                )
            self._fleet_never_ready_started_at = None
            return None
        if self._fleet_never_ready_started_at is None:
            self._fleet_never_ready_started_at = observed_at
            return None
        elapsed = max(
            0.0,
            (observed_at - self._fleet_never_ready_started_at).total_seconds(),
        )
        if elapsed <= threshold_sec:
            return None
        return self._fleet_evidence(
            details,
            classified,
            observed_at=observed_at,
            waiting=stalled,
        )

    def _fleet_evidence(
        self,
        details: tuple[dict[str, object], ...],
        classified: tuple[tuple[str, bool], ...],
        *,
        observed_at: datetime,
        waiting: int,
    ) -> FleetNeverReadyEvidence:
        bucket_counts: Counter[str] = Counter()
        oldest: datetime | None = None
        generation_latest: datetime | None = None
        epochs: set[object] = set()
        transports: set[str] = set()
        in_flight = 0
        for detail, (bucket, _is_waiting) in zip(details, classified):
            bucket_counts[bucket] += 1
            anchor = _oldest_wait_anchor(detail)
            if anchor is not None and (oldest is None or anchor < oldest):
                oldest = anchor
            generation = _parse_detail_timestamp(detail, "generation_started_at")
            if generation is not None and (
                generation_latest is None or generation > generation_latest
            ):
                generation_latest = generation
            epoch = detail.get("connection_epoch")
            if epoch is not None:
                epochs.add(epoch)
            transport = detail.get("transport_state")
            if isinstance(transport, str) and transport:
                transports.add(transport)
            if _detail_in_flight(detail):
                in_flight += 1
        oldest_wait_age_sec = (
            None
            if oldest is None
            else max(0, int((observed_at - oldest).total_seconds()))
        )
        return FleetNeverReadyEvidence(
            no_progress=waiting,
            fleet=len(details),
            buckets=tuple(sorted(bucket_counts.items())),
            oldest_wait_age_sec=oldest_wait_age_sec,
            generation_started_iso=(
                None if generation_latest is None else generation_latest.isoformat()
            ),
            connection_epoch=tuple(epochs),
            transport_states=tuple(sorted(transports)),
            in_flight=in_flight,
        )

    def _restart_if_recovery_exhausted(self, *, now: datetime | None) -> None:
        restart = self._restart
        gate = self._settings.health.restart_gate
        if restart is None or self._restart_requested or not gate.enabled:
            return
        health = self._settings.health
        result = evaluate_liveness(
            self._heartbeat_path(),
            max_age_sec=health.liveness.heartbeat_max_age_sec,
            startup_started_at=self._startup_started_at(),
            startup_grace_sec=health.startup_grace_sec,
            max_readiness_miss_sec=gate.critical_down_sec,
            max_data_starvation_sec=gate.critical_down_sec,
            now=now,
            current_pid=self._current_pid,
        )
        reason = (
            result.reason
            if result.reason in {"data_starvation", "readiness_miss"}
            else None
        )
        observed_at = now or _utc_now()
        if reason is None:
            evidence = self._fleet_never_ready(
                now=observed_at,
                threshold_sec=gate.critical_down_sec,
            )
            if evidence is not None:
                reason = evidence.restart_reason()
        if reason is None:
            return
        # Circuit breaker: while the breaker is already open, do NOT append
        # this poll's attempt. Appending keeps refreshing the rolling window,
        # so it could never cool down and the breaker would suppress restarts
        # forever (issue69 I1; live evidence 2026-08-18: history grew one
        # entry per 30s poll with recent_count 37 -> 38, and later a cooled
        # window was re-extended by a closed-edge append — count stuck at
        # max_restarts and restart never fired again). The open state is
        # self-clearing: old timestamps age out on their own.
        observed_now = now or _utc_now()
        if self._circuit_breaker_open(now=observed_now):
            recent = self._restarts_in_window(now=observed_now)
            logger.error(
                "restart_circuit_breaker_open recent_count=%s window_sec=%s",
                len(recent),
                self._settings.health.restart_gate.restart_circuit_breaker_window_sec,
            )
            # Do NOT set _restart_requested here: the latch only marks an
            # in-flight restart in the normal branch below. Breaker suppression
            # is _circuit_breaker_open's own responsibility — once the rolling
            # window cools and old timestamps are pruned, the breaker closes
            # and the same watchdog instance auto-rearms.
            return
        # Record THIS restart attempt before firing. Only a restart that
        # actually fires is counted: an append-then-check here would leave the
        # attempt that trips the threshold in the window as a "future"
        # timestamp, re-extending the cooldown every time the count decays
        # below max_restarts — the breaker then never closes and restart never
        # fires (issue69 I1 cooldown vortex, live evidence 20:58-21:00 UTC).
        self._append_restart_timestamp(observed_now)
        self._restart_requested = True
        logger.error(
            "runtime_restart_requested reason=%s threshold_sec=%s",
            reason,
            gate.critical_down_sec,
        )
        # A raising stop-intent callback must not tear down the poll loop, and
        # the latch stays set so the same episode cannot re-fire (a duplicate
        # stop intent is also rejected by request_process_stop itself). The
        # failed intent is logged; the operator/supervisor sees it in the
        # restart history already recorded above.
        try:
            restart(reason)
        except Exception:
            logger.exception(
                "restart_callback_failed reason=%s; watchdog stays armed-"
                "down for this episode to avoid a stop loop",
                reason,
            )

    def poll_once(self) -> str | None:
        """Evaluate liveness once and send an alert if the gate says so."""
        health = self._settings.health
        now = self._now() if self._now is not None else None
        liveness = evaluate_liveness(
            self._heartbeat_path(),
            max_age_sec=health.liveness.heartbeat_max_age_sec,
            startup_started_at=self._startup_started_at(),
            startup_grace_sec=health.startup_grace_sec,
            max_readiness_miss_sec=health.liveness.max_readiness_miss_sec,
            max_data_starvation_sec=health.liveness.max_data_starvation_sec,
            now=now,
            current_pid=self._current_pid,
        )
        self._restart_if_recovery_exhausted(now=now)
        previous = self._state
        decision = evaluate_liveness_alert(
            liveness,
            previous=previous,
            min_unhealthy_sec=health.alert.min_unhealthy_sec,
            min_consecutive_failures=health.alert.min_consecutive_failures,
            now=now or _utc_now(),
        )
        if decision.message is None:
            self._state = decision.state
            return None
        try:
            accepted = self._send(decision.message)
        except Exception:
            # Keep the previous `notified` flag so the next poll retries this
            # message. Advancing it here would burn the only page for the
            # episode and leave the operator with just a recovery notice.
            logger.exception("Failed to send runtime health alert")
            self._state = replace(decision.state, notified=previous.notified)
            return None
        if accepted is False:
            # Delivery boundary rejected the message (bounded queue full). The
            # poll is never blocked by this; keep `notified` unset so the next
            # poll retries instead of dropping the page for the episode.
            logger.error(
                "health_alert_submit_rejected queue_full previous_notified=%s",
                previous.notified,
            )
            self._state = replace(decision.state, notified=previous.notified)
            return None
        self._state = decision.state
        return decision.message

    def _run(self) -> None:
        interval = max(1, int(self._settings.health.alert.poll_interval_sec))
        while not self._stop.wait(interval):
            try:
                _ = self.poll_once()
            except Exception:
                logger.exception("Liveness watchdog poll failed")

    def start(self) -> None:
        if not self._settings.health.alert.enabled and self._restart is None:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        if self._dispatcher is not None:
            self._dispatcher.start()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="polysignal-liveness-watchdog",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the watchdog, then the alert dispatcher it feeds.

        Ordering matters: the dispatch worker must outlive the poll thread so
        a poll in flight can never enqueue into a stopped dispatcher. The
        stop intent is an idempotent flag; joining is bounded so a wedged
        poll cannot hang shutdown.
        """
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5.0)
            if thread.is_alive():
                # Join timed out — most likely blocked on a slow alert send.
                # Keep the handle so a later start() cannot clear the stop
                # flag and race a second thread against this one's state.
                logger.warning("Liveness watchdog did not stop within 5s")
            else:
                self._thread = None
        if self._dispatcher is not None:
            self._dispatcher.stop()
