"""Health-alert delivery boundary tests (issue69 alert chain).

Regression target: while the runtime was data-starved, the watchdog tried to
send a runtime health alert and the Telegram publisher raised
``RuntimeError: Event loop is closed`` — the send path cached one event loop
and the runtime's shared httpx client, so the alert never reached the operator.

The contract under test:

- ``HealthAlertDispatcher.submit`` is a bounded, non-blocking enqueue: a wedged
  Telegram endpoint can never stall the watchdog poll or change health/restart
  decisions.
- Delivery runs on a dispatcher-owned thread/loop with a fresh publisher per
  attempt; a closed or unusable loop is rebound, never reused (runtime
  event-loop replacement keeps delivering).
- Failures are counted, redacted and retried with backoff; an identical
  in-flight message is deduplicated; recovery messages still deliver after the
  pending alert.
- start/stop/restart are idempotent.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from _pytest.logging import LogCaptureFixture

from polysignal_lab.config import (
    HealthAlertConfig,
    HealthConfig,
    Settings,
    StorageConfig,
    TelegramConfig,
)
from polysignal_lab.observability.liveness_watchdog import (
    HealthAlertDispatcher,
    LivenessWatchdog,
)
from polysignal_lab.publish.telegram_publisher import PublishResult, TelegramPublisher

UTC_ = UTC
_T0 = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)
_TOKEN = "7123456789:AA" + "y" * 30
_CHANNEL = "@polysignal_lab_alerts"


def _settings(
    tmp_path: Path,
    *,
    queue_size: int = 8,
    backoff_base: float = 0.01,
    backoff_max: float = 0.05,
    publish_timeout: float = 0.5,
    min_unhealthy_sec: int = 60,
    min_consecutive_failures: int = 3,
    telegram: TelegramConfig | None = None,
) -> Settings:
    return Settings(
        storage=StorageConfig(state_dir=str(tmp_path)),
        telegram=telegram
        or TelegramConfig(
            enabled=True, dry_run=True, publish_timeout_sec=publish_timeout
        ),
        health=HealthConfig(
            startup_grace_sec=0,
            alert=HealthAlertConfig(
                enabled=True,
                poll_interval_sec=30,
                min_unhealthy_sec=min_unhealthy_sec,
                min_consecutive_failures=min_consecutive_failures,
                send_queue_size=queue_size,
                send_backoff_base_sec=backoff_base,
                send_backoff_max_sec=backoff_max,
            ),
        ),
    )


class _SharedTransport:
    """Shared fake transport state: what was sent, and worker-loop signals."""

    calls: list[tuple[str, str]]
    closed_count: int
    fail_times: int
    block: bool
    send_started: threading.Event
    release: asyncio.Event | None
    loop_ids: list[int]

    def __init__(
        self,
        *,
        fail_times: int = 0,
        block: bool = False,
        cancel_times: int = 0,
        close_raises_closed: bool = False,
    ) -> None:
        self.calls = []
        self.closed_count = 0
        self.fail_times = fail_times
        self.block = block
        self.cancel_times = cancel_times
        self.close_raises_closed = close_raises_closed
        self.send_started = threading.Event()
        self.release = asyncio.Event() if block else None
        self.loop_ids = []

    def publisher(self) -> "_FakePublisher":
        return _FakePublisher(self)


class _FakeClient:
    transport: _SharedTransport

    def __init__(self, transport: _SharedTransport) -> None:
        self.transport = transport

    async def aclose(self) -> None:
        self.transport.closed_count += 1
        if self.transport.close_raises_closed:
            raise RuntimeError("Event loop is closed")


class _FakePublisher:
    """A fake publisher whose send() runs as a REAL coroutine on the worker
    loop — the dispatcher's async boundary is the thing under test."""

    transport: _SharedTransport
    client: _FakeClient

    def __init__(self, transport: _SharedTransport) -> None:
        self.transport = transport
        self.client = _FakeClient(transport)

    async def send(self, message: str, message_type: str) -> PublishResult:
        self.transport.loop_ids.append(id(asyncio.get_running_loop()))
        self.transport.send_started.set()
        if self.transport.block and self.transport.release is not None:
            await self.transport.release.wait()
        if self.transport.cancel_times > 0:
            self.transport.cancel_times -= 1
            raise asyncio.CancelledError("cancelled by test")
        if self.transport.fail_times > 0:
            self.transport.fail_times -= 1
            return PublishResult(
                publish_id="tg-fake",
                message_type=message_type,
                status="FAILED",
                error="simulated telegram outage",
                sent_at=_T0.isoformat(),
            )
        self.transport.calls.append((message, message_type))
        return PublishResult(
            publish_id="tg-fake",
            message_type=message_type,
            status="SENT",
            sent_at=_T0.isoformat(),
        )


def _wait_until(predicate: Any, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met within %ss" % timeout)


def _new_dispatcher(
    settings: Settings,
    transport: _SharedTransport,
    *,
    loop_factory: Any = None,
) -> HealthAlertDispatcher:
    return HealthAlertDispatcher(
        settings,
        transport.publisher,
        loop_factory=loop_factory,
    )


def cast_loop(loop: Any) -> asyncio.AbstractEventLoop:
    return cast(asyncio.AbstractEventLoop, loop)


def test_legacy_cached_loop_pattern_raises_event_loop_is_closed() -> None:
    """Reproduce the issue69 failure: a cached loop that has been closed can
    never run another coroutine — exactly what the old watchdog send closure
    did after the runtime's event loop was replaced."""

    async def noop() -> None:
        return None

    loop = asyncio.new_event_loop()
    loop.close()

    coro = noop()
    try:
        with pytest.raises(RuntimeError, match="Event loop is closed"):
            loop.run_until_complete(coro)
    finally:
        coro.close()


def test_poison_loop_is_detected_rebound_and_delivery_succeeds(
    tmp_path: Path,
) -> None:
    """A loop that raises 'Event loop is closed' inside send is discarded and
    rebound; the same dispatcher instance still delivers on a fresh loop."""
    transport = _SharedTransport()
    calls: list[int] = []
    made: list[Any] = []

    class _PoisonLoop(asyncio.AbstractEventLoop):
        """A real loop type whose run_until_complete fails exactly like a
        closed loop — the dispatcher must discard it and install a fresh one."""

        def __init__(self) -> None:
            self.closed = False

        def is_closed(self) -> bool:
            return self.closed

        def run_until_complete(self, _coro: Any) -> Any:  # pyright: ignore[reportIncompatibleMethodOverride]
            raise RuntimeError("Event loop is closed")

        def close(self) -> None:
            self.closed = True

    def loop_factory() -> asyncio.AbstractEventLoop:
        if not made:
            made.append(_PoisonLoop())
            return cast_loop(made[0])
        loop = asyncio.new_event_loop()
        calls.append(id(loop))
        return loop

    dispatcher = _new_dispatcher(
        _settings(tmp_path),
        transport,
        loop_factory=loop_factory,  # pyright: ignore[reportArgumentType]
    )
    dispatcher.start()
    try:
        assert dispatcher.submit("first alert") is True
        _wait_until(lambda: transport.calls == [("first alert", "health_alert")])
    finally:
        dispatcher.stop()

    stats = dispatcher.stats()
    assert stats.failed_attempts >= 1
    assert stats.rebinds >= 2  # poison install + fresh install
    assert stats.sent == 1
    assert stats.last_error is not None


def test_delivery_reuses_a_fresh_loop_after_external_loop_close(
    tmp_path: Path,
) -> None:
    """Runtime replacement scenario: the worker's current loop is closed
    behind its back (like the app loop was in production). The dispatcher
    detects it and rebinds instead of reusing the closed loop."""
    transport = _SharedTransport()
    loops: list[asyncio.AbstractEventLoop] = []

    def loop_factory() -> asyncio.AbstractEventLoop:
        loop = asyncio.new_event_loop()
        loops.append(loop)
        return loop

    dispatcher = _new_dispatcher(
        _settings(tmp_path),
        transport,
        loop_factory=loop_factory,
    )
    dispatcher.start()
    try:
        assert dispatcher.submit("first") is True
        _wait_until(lambda: transport.calls == [("first", "health_alert")])
        assert len(loops) == 1
        assert not loops[0].is_closed()

        # Simulate the runtime event-loop replacement: the loop the dispatcher
        # was using is now dead.
        loops[0].close()

        assert dispatcher.submit("second") is True
        _wait_until(
            lambda: (
                transport.calls
                == [("first", "health_alert"), ("second", "health_alert")]
            )
        )
        assert len(loops) == 2
        assert loops[1] is not loops[0]
        assert dispatcher.stats().rebinds >= 2
    finally:
        dispatcher.stop()


def test_submit_is_thread_safe_and_delivery_runs_on_worker_loop(
    tmp_path: Path,
) -> None:
    """The main (or any) thread enqueues; the coroutine runs on the dispatcher
    worker loop, never on the caller's loop."""
    main_loop = asyncio.new_event_loop()  # a *different* loop object
    main_loop_id = id(main_loop)
    main_loop.close()  # discard immediately: no ResourceWarning leak
    transport = _SharedTransport()
    dispatcher = _new_dispatcher(_settings(tmp_path), transport)
    dispatcher.start()
    try:
        assert dispatcher.submit("cross-thread") is True
        _wait_until(lambda: transport.calls == [("cross-thread", "health_alert")])
        assert len(transport.loop_ids) == 1
        assert transport.loop_ids[0] != main_loop_id
    finally:
        dispatcher.stop()


def test_start_stop_restart_is_idempotent(tmp_path: Path) -> None:
    transport = _SharedTransport()
    dispatcher = _new_dispatcher(_settings(tmp_path), transport)

    dispatcher.start()
    dispatcher.start()  # idempotent: still one worker
    assert dispatcher.submit("before stop") is True
    _wait_until(lambda: len(transport.calls) == 1)

    dispatcher.stop()
    dispatcher.stop()  # idempotent

    dispatcher.start()  # restart re-arms the same instance
    assert dispatcher.submit("after restart") is True
    _wait_until(lambda: len(transport.calls) == 2)
    dispatcher.stop()

    assert [msg for msg, _t in transport.calls] == ["before stop", "after restart"]


def test_send_failures_back_off_and_retry_until_sent(tmp_path: Path) -> None:
    transport = _SharedTransport(fail_times=3)
    dispatcher = _new_dispatcher(
        _settings(tmp_path, backoff_base=0.01, backoff_max=0.03),
        transport,
    )
    dispatcher.start()
    try:
        assert dispatcher.submit("flaky") is True
        _wait_until(lambda: len(transport.calls) == 1)
    finally:
        dispatcher.stop()

    stats = dispatcher.stats()
    assert stats.sent == 1
    assert stats.failed_attempts == 3
    assert "simulated telegram outage" in (stats.last_error or "")


def test_identical_inflight_message_is_deduplicated(tmp_path: Path) -> None:
    transport = _SharedTransport(block=True)
    dispatcher = _new_dispatcher(_settings(tmp_path), transport)
    dispatcher.start()
    try:
        assert dispatcher.submit("same incident") is True
        _wait_until(lambda: transport.send_started.is_set())
        # The first attempt is blocked in flight; the same incident text is
        # deduplicated instead of enqueued a second time.
        assert dispatcher.submit("same incident") is True
        stats = dispatcher.stats()
        assert stats.enqueued == 1
        assert stats.deduplicated == 1
        assert transport.release is not None
        transport.release.set()
        _wait_until(lambda: transport.calls == [("same incident", "health_alert")])
    finally:
        dispatcher.stop()
    assert dispatcher.stats().sent == 1


def test_queue_full_drop_is_non_blocking_and_counted(tmp_path: Path) -> None:
    transport = _SharedTransport(block=True, fail_times=0)
    dispatcher = _new_dispatcher(
        _settings(tmp_path, queue_size=1, publish_timeout=0.2),
        transport,
    )
    dispatcher.start()
    try:
        assert dispatcher.submit("first") is True
        _wait_until(lambda: transport.send_started.is_set())
        assert dispatcher.submit("second") is True  # fills the bounded queue
        started = time.monotonic()
        assert dispatcher.submit("third") is False  # dropped, never blocks
        assert time.monotonic() - started < 0.5
        stats = dispatcher.stats()
        assert stats.dropped == 1
        assert stats.enqueued == 2
        assert transport.release is not None
        transport.release.set()
    finally:
        dispatcher.stop()


def test_watchdog_poll_not_blocked_and_restart_decision_unchanged(
    tmp_path: Path,
) -> None:
    """A blocked Telegram send must neither stall poll_once nor change the
    restart decision."""
    transport = _SharedTransport(block=True)
    settings = _settings(tmp_path, min_unhealthy_sec=0, min_consecutive_failures=1)
    dispatcher = _new_dispatcher(settings, transport)
    restarts: list[str] = []
    clock = {"now": _T0}
    watchdog = LivenessWatchdog(
        settings,
        dispatcher.submit,
        now=lambda: clock["now"],
        restart=restarts.append,
        dispatcher=dispatcher,
    )
    dispatcher.start()
    try:
        # A readiness miss that has already outlived the critical window: the
        # first poll must both enqueue the alert AND request the restart.
        payload = {
            "updated_at": clock["now"].isoformat(),
            "phase": "readiness_miss",
            "fatal": False,
            "fatal_reason": None,
            "last_data_at": clock["now"].isoformat(),
            "readiness_miss_started_at_by_key": {
                "cond-1": (_T0 - timedelta(seconds=301)).isoformat()
            },
            "readiness_detail_by_key": {"cond-1": {"subscription_state": "ready"}},
        }
        (tmp_path / "runtime_heartbeat.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

        started = time.monotonic()
        message = watchdog.poll_once()
        elapsed = time.monotonic() - started

        assert message is not None
        assert elapsed < 1.0
        assert restarts == ["readiness_miss"]
        assert transport.calls == []  # nothing delivered yet — Telegram wedged

        # A second poll must also return quickly while the send is still stuck.
        started = time.monotonic()
        _ = watchdog.poll_once()
        assert time.monotonic() - started < 1.0
    finally:
        if transport.release is not None:
            transport.release.set()
        dispatcher.stop()


def test_real_publisher_lifecycle_with_fake_transport_keeps_token_out_of_logs(
    tmp_path: Path,
    caplog: LogCaptureFixture,
) -> None:
    """The real TelegramPublisher lifecycle (factory on worker, send, client
    aclose) runs over a fake HTTP transport; secrets must never appear in
    logs."""

    class _OkResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"ok": True, "result": {"message_id": 1234}}

    class _OkHttpClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []
            self.closed = False

        async def post(self, url: str, json: dict[str, object]) -> _OkResponse:
            self.calls.append((url, json))
            return _OkResponse()

        async def aclose(self) -> None:
            self.closed = True

    clients: list[_OkHttpClient] = []

    def publisher_factory() -> TelegramPublisher:
        client = _OkHttpClient()
        clients.append(client)
        return TelegramPublisher(
            TelegramConfig(enabled=True, dry_run=False, retry_attempts=1),
            bot_token=_TOKEN,
            channel_id=_CHANNEL,
            client=cast(httpx.AsyncClient, cast(Any, client)),
        )

    settings = _settings(
        tmp_path,
        telegram=TelegramConfig(enabled=True, dry_run=False, retry_attempts=1),
    )
    dispatcher = HealthAlertDispatcher(settings, publisher_factory)
    dispatcher.start()
    try:
        with caplog.at_level(
            "WARNING", logger="polysignal_lab.observability.liveness_watchdog"
        ):
            assert dispatcher.submit("unhealthy runtime") is True
            _wait_until(lambda: clients and clients[0].calls)
    finally:
        dispatcher.stop()

    url, payload = clients[0].calls[0]
    assert url.endswith("/sendMessage")
    assert payload["chat_id"] == _CHANNEL
    assert clients[0].closed is True  # per-attempt client is closed in-loop
    # The bot token is part of the Telegram request URL by protocol; it must
    # never surface in logs (caplog above), dispatch stats, or captured records.
    assert _TOKEN not in caplog.text
    assert _TOKEN not in (dispatcher.stats().last_error or "")
    assert _TOKEN not in " ".join(r.getMessage() for r in caplog.records)


def test_real_publisher_http_failure_retries_at_dispatcher_level(
    tmp_path: Path,
) -> None:
    """A fake transport that raises a transient ConnectError: the real
    TelegramPublisher returns FAILED and the dispatcher backs off and retries,
    delivering on a later attempt."""

    class _FlappyClient:
        def __init__(self, posts: dict[str, int]) -> None:
            self.posts = posts
            self.calls = 0
            self.closed = False

        async def post(self, url: str, json: dict[str, object]) -> Any:
            del url, json
            self.calls += 1
            self.posts["count"] += 1
            if self.posts["count"] == 1:
                # One global transport outage: only the first attempt fails.
                raise httpx.ConnectError("network down")

            class _Resp:
                def raise_for_status(self) -> None:
                    return None

                def json(self) -> dict[str, object]:
                    return {"ok": True, "result": {"message_id": 7}}

            return _Resp()

        async def aclose(self) -> None:
            self.closed = True

    clients: list[_FlappyClient] = []
    posts: dict[str, int] = {"count": 0}

    def factory() -> TelegramPublisher:
        client = _FlappyClient(posts)
        clients.append(client)
        return TelegramPublisher(
            TelegramConfig(enabled=True, dry_run=False, retry_attempts=1),
            bot_token=_TOKEN,
            channel_id=_CHANNEL,
            client=cast(httpx.AsyncClient, cast(Any, client)),
        )

    settings = _settings(
        tmp_path,
        backoff_base=0.02,
        backoff_max=0.04,
        telegram=TelegramConfig(enabled=True, dry_run=False, retry_attempts=1),
    )
    dispatcher = HealthAlertDispatcher(settings, factory)
    dispatcher.start()
    try:
        assert dispatcher.submit("network flaky") is True
        # Attempt 1 fails with ConnectError; the dispatcher retries with a
        # fresh publisher/client on a later attempt.
        _wait_until(lambda: len(clients) >= 2 and clients[1].calls >= 1)
    finally:
        dispatcher.stop()

    assert dispatcher.stats().sent == 1
    assert dispatcher.stats().failed_attempts >= 1


def test_cancelled_send_coroutine_recovers_and_delivers(tmp_path: Path) -> None:
    """A send coroutine cancelled mid-flight (CancelledError is a
    BaseException, not Exception) must be closed, counted, and retried — it
    must never kill the worker thread nor leak 'coroutine was never awaited'
    resource warnings."""
    transport = _SharedTransport(cancel_times=1)
    dispatcher = _new_dispatcher(
        _settings(tmp_path, backoff_base=0.01, backoff_max=0.02),
        transport,
    )
    dispatcher.start()
    try:
        assert dispatcher.submit("cancelled once") is True
        _wait_until(lambda: transport.calls == [("cancelled once", "health_alert")])
    finally:
        dispatcher.stop()

    stats = dispatcher.stats()
    assert stats.sent == 1
    assert stats.failed_attempts >= 1
    assert "cancelled" in (stats.last_error or "")
    # rebinds == initial install only: the cancelled send did NOT discard a
    # still-healthy loop.
    assert stats.rebinds == 1


def test_publisher_factory_exception_is_retried(tmp_path: Path) -> None:
    """A sync publisher_factory failure must not kill the worker: the retry
    loop calls the factory again on the next attempt."""
    transport = _SharedTransport()
    failures = {"count": 1}

    def flaky_factory():  # pyright: ignore[reportMissingParameterType]
        if failures["count"] > 0:
            failures["count"] -= 1
            raise RuntimeError("telegram client constructor crashed")
        return transport.publisher()

    dispatcher = HealthAlertDispatcher(
        _settings(tmp_path, backoff_base=0.01, backoff_max=0.02),
        flaky_factory,  # pyright: ignore[reportArgumentType]
    )
    dispatcher.start()
    try:
        assert dispatcher.submit("factory flaky") is True
        _wait_until(lambda: transport.calls == [("factory flaky", "health_alert")])
    finally:
        dispatcher.stop()

    assert dispatcher.stats().sent == 1
    assert dispatcher.stats().failed_attempts >= 1


def test_stop_during_blocked_send_is_prompt_and_clean(tmp_path: Path) -> None:
    """stop() races an in-flight send: the send is bounded by wait_for, the
    stop flag interrupts the retry backoff, the worker exits promptly, and a
    later start() on the same instance delivers again."""
    transport = _SharedTransport(block=True)
    dispatcher = _new_dispatcher(
        _settings(tmp_path, publish_timeout=0.2, backoff_base=0.05, backoff_max=60.0),
        transport,
    )
    dispatcher.start()
    assert dispatcher.submit("stuck alert") is True
    _wait_until(lambda: transport.send_started.is_set())

    started = time.monotonic()
    dispatcher.stop()
    assert time.monotonic() - started < 4.0  # retry backoff was interrupted

    assert dispatcher._thread is None  # worker exited, not wedged
    assert transport.calls == []  # the stuck attempt never delivered
    assert dispatcher.stats().sent == 0
    assert transport.release is not None
    transport.release.set()

    # Same instance restarts and delivers fresh alerts.
    dispatcher.start()
    try:
        assert dispatcher.submit("after restart") is True
        _wait_until(lambda: transport.calls == [("after restart", "health_alert")])
    finally:
        dispatcher.stop()


def test_aclose_raising_closed_loop_keeps_delivery_and_worker(tmp_path: Path) -> None:
    """client.aclose() raising 'Event loop is closed' mid-flight must not lose
    the already-delivered page, must not count a failed attempt, and must not
    kill the worker: the per-attempt client is discarded, the loop stays."""
    transport = _SharedTransport(close_raises_closed=True)
    dispatcher = _new_dispatcher(_settings(tmp_path), transport)
    dispatcher.start()
    try:
        assert dispatcher.submit("page one") is True
        _wait_until(lambda: transport.calls == [("page one", "health_alert")])
        assert dispatcher.stats().sent == 1

        # The worker survived; a second delivery still works end to end.
        assert dispatcher.submit("page two") is True
        _wait_until(
            lambda: (
                transport.calls
                == [("page one", "health_alert"), ("page two", "health_alert")]
            )
        )
    finally:
        dispatcher.stop()

    stats = dispatcher.stats()
    assert stats.sent == 2
    assert stats.failed_attempts == 0  # close failure is not a send failure
    assert transport.closed_count >= 2  # every per-attempt client was closed
