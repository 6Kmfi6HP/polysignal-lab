"""
Input: pytest, threading, time, types
Output: accepted-signal Telegram outbox regression coverage
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

from polysignal_lab.config import Settings, TelegramConfig
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_runtime import signal_notifications as sn
from polysignal_lab.publish.telegram_publisher import PublishResult


def _reset_outbox() -> None:
    """Stop any live worker and drain the process-local outbox."""
    with sn._WORKER_LOCK:
        thread = sn._worker_thread
        if thread is not None and thread.is_alive():
            sn._OUTBOX.put(sn._STOP)
    if thread is not None:
        thread.join(timeout=2.0)
        assert not thread.is_alive()
    with sn._WORKER_LOCK:
        while True:
            try:
                sn._OUTBOX.get_nowait()
            except Exception:
                break
        sn._worker_thread = None


@pytest.fixture(autouse=True)
def _isolated_outbox() -> Any:
    _reset_outbox()
    yield
    _reset_outbox()


def _signal(signal_id: str = "sig_notify_1") -> SignalCandidate:
    return SignalCandidate.build(
        strategy="late_consensus",
        asset="BTC",
        timeframe="5m",
        market_id="m1",
        market_slug="btc-updown-5m",
        condition_id="c1",
        token_id="t1",
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.5,
        max_entry_price=0.55,
        seconds_to_close=120,
        data_freshness_ms=100,
        reason_codes=["EDGE"],
        metrics={},
        signal_id=signal_id,
    )


def _services(
    *,
    publish: Any | None = None,
    send_signals: bool = True,
    raise_on_publish: BaseException | None = None,
) -> SimpleNamespace:
    published: list[tuple[str, float]] = []
    audit: list[dict[str, object]] = []

    class Persistence:
        def insert_system_event(self, event: dict[str, object]) -> None:
            audit.append(dict(event))

        def append_log(self, stream: str, payload: object) -> None:
            row = dict(payload) if isinstance(payload, dict) else {"payload": payload}
            row["stream"] = stream
            audit.append(row)

        def insert_telegram_publish(self, result: dict[str, object]) -> None:
            audit.append({"kind": "telegram_publish", **dict(result)})

    async def publish_signal_once(signal: SignalCandidate, stake_usdc: float) -> PublishResult:
        if raise_on_publish is not None:
            raise raise_on_publish
        if publish is not None:
            return await publish(signal, stake_usdc)
        published.append((signal.signal_id, stake_usdc))
        return PublishResult(
            publish_id=f"tg_{signal.signal_id}",
            message_type="signal",
            status="SENT",
            signal_id=signal.signal_id,
            telegram_message_id="1",
            sent_at="2026-07-20T00:00:00Z",
        )

    health = SimpleNamespace(
        inc_metric=lambda *_a, **_k: None,
        mark_ok=lambda *_a, **_k: None,
        mark_degraded=lambda *_a, **_k: None,
    )
    return SimpleNamespace(
        settings=Settings(
            telegram=TelegramConfig(
                enabled=True,
                dry_run=False,
                send_signals=send_signals,
            )
        ),
        logger=SimpleNamespace(warning=lambda *_a, **_k: None, debug=lambda *_a, **_k: None),
        health=health,
        persistence=Persistence(),
        publish_signal_once=publish_signal_once,
        _published=published,
        _audit=audit,
    )


def _wait_until(predicate: Any, *, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_notify_accepted_signal_drains_outbox_to_publisher() -> None:
    """Strategy-thread put() must reach publish_signal_once off-thread."""
    services = _services()
    sn._notify_accepted_signal(services, _signal("sig_happy"), 12.5)

    assert _wait_until(lambda: services._published == [("sig_happy", 12.5)])
    assert services._published == [("sig_happy", 12.5)]


def test_notify_accepted_signal_respects_send_signals_gate() -> None:
    services = _services(send_signals=False)
    sn._notify_accepted_signal(services, _signal("sig_gated"), 10.0)
    time.sleep(0.2)
    assert services._published == []


def test_dead_outbox_worker_is_restarted_on_next_notify() -> None:
    """
    User symptom: signals keep recording while Telegram goes quiet for hours.

    If the notify outbox thread exits but the process-local started flag stays
    true, later accepted signals enqueue forever and never publish. The next
    notify must detect the dead worker and restart it.
    """
    services = _services()
    sn._notify_accepted_signal(services, _signal("sig_before_death"), 10.0)
    assert _wait_until(lambda: "sig_before_death" in {s for s, _ in services._published})

    # Stop the worker the way a crashed/exited thread leaves the flag set.
    sn._OUTBOX.put(sn._STOP)
    assert _wait_until(
        lambda: sn._worker_thread is None or not sn._worker_thread.is_alive(),
        timeout=2.0,
    )

    services._published.clear()
    sn._notify_accepted_signal(services, _signal("sig_after_death"), 10.0)
    assert _wait_until(lambda: services._published == [("sig_after_death", 10.0)])
    assert services._published == [("sig_after_death", 10.0)]


def test_accepted_signal_publish_failure_leaves_durable_audit() -> None:
    """
    User symptom counterpart: signal row exists, telegram_publishes has no row.

    Publish exceptions must not be log-only; mirror report_result and leave a
    durable audit so ops can see the drop without grepping container logs.
    """
    services = _services(raise_on_publish=RuntimeError("boom-telegram"))
    sn._notify_accepted_signal(services, _signal("sig_fail"), 10.0)

    assert _wait_until(lambda: bool(services._audit), timeout=2.0)
    events = [
        row
        for row in services._audit
        if row.get("event_type") == "accepted_signal_publish_failed"
        or row.get("kind") == "telegram_publish"
        or row.get("message_type") == "signal"
    ]
    assert events, f"expected durable audit, got {services._audit!r}"
    # Prefer explicit failure signal over a successful send record.
    assert any(
        row.get("event_type") == "accepted_signal_publish_failed"
        or row.get("status") == "FAILED"
        for row in events
    )
