from __future__ import annotations

import asyncio
import sqlite3
import threading
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from polysignal_lab.alpha.types import AlphaDecision
from polysignal_lab.app.services.persistence_service import PersistenceService
from polysignal_lab.domain.enums import OrderStatus, Side
from polysignal_lab.domain.paper_order import PaperOrder
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.storage.jsonl_store import JSONLStore
from polysignal_lab.storage.sqlite_store import SQLiteStore
from polysignal_lab.storage.state_store import StateStore
from polysignal_lab.nautilus_runtime.observability import (
    DecisionPolicyControl,
    NautilusEventStoreAdapter,
    NautilusNotifierAdapter,
    ObservabilityActor,
)
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor
from polysignal_lab.utils import utc_now


class FakeStore:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {}

    def insert_json(self, table: str, data: Mapping[str, object]) -> None:
        self.tables.setdefault(table, []).append(dict(data))

    def insert_many_json(self, table: str, rows: Sequence[Mapping[str, object]]) -> None:
        for row in rows:
            self.insert_json(table, row)


class FailingTelemetryStore(FakeStore):
    def insert_json(self, table: str, data: Mapping[str, object]) -> None:
        if table.startswith("nautilus_"):
            raise OSError("jsonl unavailable")
        super().insert_json(table, data)


class BlockingTelemetryStore(FakeStore):
    def __init__(self) -> None:
        super().__init__()
        self.insert_started = threading.Event()
        self.release_insert = threading.Event()

    def insert_json(self, table: str, data: Mapping[str, object]) -> None:
        self.insert_started.set()
        _ = self.release_insert.wait(timeout=10.0)
        super().insert_json(table, data)


class FlakyLockedTelemetryStore(FakeStore):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def insert_json(self, table: str, data: Mapping[str, object]) -> None:
        self.calls += 1
        if self.calls == 1:
            raise sqlite3.OperationalError("database is locked")
        super().insert_json(table, data)


class AlwaysLockedTelemetryStore(FakeStore):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def insert_json(self, table: str, data: Mapping[str, object]) -> None:
        self.calls += 1
        raise sqlite3.OperationalError("database is locked")


class NonLockingOperationalErrorTelemetryStore(FakeStore):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def insert_json(self, table: str, data: Mapping[str, object]) -> None:
        self.calls += 1
        raise sqlite3.OperationalError("disk I/O error")


# ── ObservabilityActor tests ──────────────────────────────────────────────────

def test_startup_message_includes_sandbox_book_type() -> None:
    publisher = FakePublisher()
    actor = ObservabilityActor(notifier=NautilusNotifierAdapter(publisher))

    asyncio.run(
        actor.notify_startup(
            ["ptb_diff"],
            sandbox_book_type="L2_MBP",
        )
    )

    assert publisher.calls == [
        (
            "Nautilus runtime started — 1 strategies loaded — sandbox_book_type=L2_MBP",
            "startup",
        )
    ]
    component = actor.health.components["observability_actor"]
    assert component.metrics["sandbox_book_type"] == "L2_MBP"



def test_record_decision_writes_to_nautilus_decision_stream() -> None:
    store = FakeStore()
    actor = ObservabilityActor(store=store)

    decision = AlphaDecision(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="m1", market_slug="s1", condition_id="c1",
        token_id="t1", side=Side.UP, confidence=0.8,
        entry_reference_price=0.5, max_entry_price=0.55,
        seconds_to_close=120, data_freshness_ms=100,
        reason_codes=("EDGE",), metrics={},
    )
    actor.record_decision(decision, accepted=True)
    actor.drain_telemetry_once()

    rows = store.tables.get("nautilus_decision", [])
    assert len(rows) == 1
    assert rows[0]["strategy"] == "test"
    assert rows[0]["accepted"] is True
    assert rows[0]["side"] == "UP"


def test_observability_actor_isolates_best_effort_telemetry_write_failure() -> None:
    actor = ObservabilityActor(store=FailingTelemetryStore())

    actor.record_decision(_decision(), accepted=True)
    actor.drain_telemetry_once()

    component = actor.health.components["observability_actor"]
    assert component.status == "degraded"
    assert component.metrics["non_critical_side_effect_failures"] == 1
    assert actor.event_count == 1


def test_observability_actor_isolates_accepted_signal_notifier_failure() -> None:
    signal = SignalCandidate.build(
        strategy="test", asset="BTC", timeframe="5m", market_id="m1", market_slug="s1",
        condition_id="c1", token_id="t1", side=Side.UP, confidence=0.8,
        entry_reference_price=0.5, max_entry_price=0.55,
        seconds_to_close=120, data_freshness_ms=100, reason_codes=["EDGE"], metrics={},
    )
    actor = ObservabilityActor(
        accepted_signal_notifier=lambda _signal, _stake: (_ for _ in ()).throw(RuntimeError("telegram failed"))
    )

    actor.notify_accepted_signal(signal, 10.0)

    component = actor.health.components["observability_actor"]
    assert component.status == "degraded"
    assert component.metrics["non_critical_side_effect_failures"] == 1







def test_best_effort_telemetry_queue_drops_when_full_and_marks_health() -> None:
    store = FakeStore()
    actor = ObservabilityActor(store=store, telemetry_queue_size=1, telemetry_autostart=False)

    actor.record_decision(_decision(market_id="m1"), accepted=True)
    actor.record_decision(_decision(market_id="m2"), accepted=True)

    component = actor.health.components["observability_actor"]
    assert component.status == "degraded"
    assert component.metrics["telemetry_queue_drops"] == 1
    assert component.metrics["telemetry_writer_backlog"] == 1
    assert store.tables == {}


def test_best_effort_telemetry_writer_drains_queued_events() -> None:
    store = FakeStore()
    actor = ObservabilityActor(store=store, telemetry_queue_size=8, telemetry_autostart=False)

    actor.record_decision(_decision(), accepted=True)
    actor.drain_telemetry_once()

    assert len(store.tables["nautilus_decision"]) == 1


def test_telemetry_writer_retries_transient_sqlite_lock() -> None:
    store = FlakyLockedTelemetryStore()
    actor = ObservabilityActor(store=store, telemetry_queue_size=8, telemetry_autostart=False)

    actor.record_decision(_decision(), accepted=True)
    actor.drain_telemetry_once()

    assert store.calls == 2
    assert len(store.tables["nautilus_decision"]) == 1
    component = actor.health.components["observability_actor"]
    assert component.metrics["sqlite_lock_retries"] == 1


def test_telemetry_writer_stops_after_bounded_sqlite_lock_retries() -> None:
    store = AlwaysLockedTelemetryStore()
    actor = ObservabilityActor(
        store=store,
        telemetry_queue_size=8,
        telemetry_autostart=False,
        telemetry_sqlite_lock_retries=2,
        telemetry_retry_backoff_sec=0,
    )

    actor.record_decision(_decision(), accepted=True)
    actor.drain_telemetry_once()

    assert store.calls == 3
    assert store.tables.get("nautilus_decision", []) == []
    component = actor.health.components["observability_actor"]
    assert component.status == "degraded"
    assert component.metrics["sqlite_lock_retries"] == 2
    assert component.metrics["non_critical_side_effect_failures"] == 1


def test_telemetry_writer_does_not_retry_non_lock_sqlite_operational_error() -> None:
    store = NonLockingOperationalErrorTelemetryStore()
    actor = ObservabilityActor(
        store=store,
        telemetry_queue_size=8,
        telemetry_autostart=False,
        telemetry_sqlite_lock_retries=2,
        telemetry_retry_backoff_sec=0,
    )

    actor.record_decision(_decision(), accepted=True)
    actor.drain_telemetry_once()

    assert store.calls == 1
    assert store.tables.get("nautilus_decision", []) == []
    component = actor.health.components["observability_actor"]
    assert component.status == "degraded"
    assert component.metrics.get("sqlite_lock_retries", 0) == 0
    assert component.metrics["non_critical_side_effect_failures"] == 1


def test_stop_returns_without_sync_drain_when_best_effort_store_blocks() -> None:
    store = BlockingTelemetryStore()
    actor = ObservabilityActor(store=store, telemetry_queue_size=8, telemetry_autostart=False)
    actor.record_decision(_decision(), accepted=True)

    stop_thread = threading.Thread(target=actor.stop)
    stop_thread.start()
    stop_thread.join(timeout=0.2)

    try:
        assert not store.insert_started.is_set()
        assert not stop_thread.is_alive()
        assert store.tables == {}
        component = actor.health.components["observability_actor"]
        assert component.metrics["telemetry_writer_backlog"] == 0
        assert component.metrics["telemetry_queue_drops"] == 1
    finally:
        store.release_insert.set()
        stop_thread.join(timeout=1.0)

def test_record_signal_writes_to_signal_stream() -> None:
    store = FakeStore()
    actor = ObservabilityActor(store=store)
    signal = SignalCandidate.build(
        strategy="test",
        asset="BTC",
        timeframe="5m",
        market_id="m1",
        market_slug="s1",
        condition_id="c1",
        token_id="t1",
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.5,
        max_entry_price=0.55,
        seconds_to_close=120,
        data_freshness_ms=100,
        reason_codes=["EDGE"],
        metrics={"edge": 0.1},
    )
    actor.record_signal(signal)

    rows = store.tables.get("signals", [])
    assert len(rows) == 1
    assert rows[0]["signal_id"] == signal.signal_id
    assert rows[0]["strategy"] == "test"
    assert rows[0]["condition_id"] == "c1"


def test_record_decision_event_store_persists_system_event_without_signal_id(
    tmp_path: Path,
) -> None:
    persistence = PersistenceService(
        JSONLStore(tmp_path / "logs"),
        SQLiteStore(tmp_path / "nautilus-observability.sqlite3"),
        StateStore(tmp_path / "state"),
    )
    actor = ObservabilityActor(store=NautilusEventStoreAdapter(persistence))

    decision = AlphaDecision(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="m1", market_slug="s1", condition_id="c1",
        token_id="t1", side=Side.UP, confidence=0.8,
        entry_reference_price=0.5, max_entry_price=0.55,
        seconds_to_close=120, data_freshness_ms=100,
        reason_codes=("EDGE",), metrics={},
    )
    actor.record_decision(decision, accepted=True)
    actor.drain_telemetry_once()

    rows = persistence.sqlite.query_json(
        "system_events",
        where="WHERE event_type = ?",
        params=("nautilus_decision",),
    )
    assert len(rows) == 1
    assert rows[0]["strategy"] == "test"
    assert rows[0]["accepted"] is True
    assert rows[0]["side"] == "UP"
    assert rows[0]["event_type"] == "nautilus_decision"

def test_record_rejected_decision_writes_duplicate_signal_candidate_payload() -> None:
    store = FakeStore()
    actor = ObservabilityActor(store=store)
    candidate = SignalCandidate.build(
        strategy="test",
        asset="BTC",
        timeframe="5m",
        market_id="m1",
        market_slug="s1",
        condition_id="c1",
        token_id="t1",
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.5,
        max_entry_price=0.55,
        seconds_to_close=120,
        data_freshness_ms=100,
        reason_codes=["EDGE"],
        metrics={"edge": 0.1},
    )

    actor.record_rejected_decision(
        SimpleNamespace(
            reason_code="DUPLICATE_SIGNAL",
            detail={"dedupe_key": candidate.dedupe_key},
            candidate=candidate,
        )
    )

    rows = store.tables.get("rejected_signals", [])
    assert len(rows) == 1
    assert rows[0]["reason_code"] == "DUPLICATE_SIGNAL"
    assert rows[0]["details"]["dedupe_key"] == candidate.dedupe_key
    assert rows[0]["candidate"]["condition_id"] == "c1"
    assert rows[0]["candidate"]["token_id"] == "t1"

def test_record_decision_and_duplicate_rejection_write_jsonl_payloads(tmp_path: Path) -> None:
    persistence = PersistenceService(
        JSONLStore(tmp_path / "logs"),
        SQLiteStore(tmp_path / "nautilus-observability.sqlite3"),
        StateStore(tmp_path / "state"),
    )
    actor = ObservabilityActor(store=NautilusEventStoreAdapter(persistence))
    decision = AlphaDecision(
        strategy="test",
        asset="BTC",
        timeframe="5m",
        market_id="m1",
        market_slug="s1",
        condition_id="c1",
        token_id="t1",
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.5,
        max_entry_price=0.55,
        seconds_to_close=120,
        data_freshness_ms=100,
        reason_codes=("EDGE",),
        metrics={"edge": 0.1},
    )
    candidate = SignalCandidate.build(
        strategy="test",
        asset="BTC",
        timeframe="5m",
        market_id="m1",
        market_slug="s1",
        condition_id="c1",
        token_id="t1",
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.5,
        max_entry_price=0.55,
        seconds_to_close=120,
        data_freshness_ms=100,
        reason_codes=["EDGE"],
        metrics={"edge": 0.1},
    )

    actor.record_decision(decision, accepted=True)
    actor.drain_telemetry_once()
    actor.record_rejected_decision(
        SimpleNamespace(
            reason_code="DUPLICATE_SIGNAL",
            detail={"dedupe_key": candidate.dedupe_key},
            candidate=candidate,
        )
    )

    decision_rows = persistence.logs.read_all("nautilus_decisions")
    rejection_rows = persistence.logs.read_all("rejected_signals")
    assert len(decision_rows) == 1
    assert decision_rows[0]["strategy"] == "test"
    assert decision_rows[0]["market_id"] == "m1"
    assert decision_rows[0]["condition_id"] == "c1"
    assert decision_rows[0]["token_id"] == "t1"
    assert decision_rows[0]["side"] == "UP"
    assert decision_rows[0]["data_freshness_ms"] == 100
    assert decision_rows[0]["reason_codes"] == ["EDGE"]
    assert decision_rows[0]["metrics"] == {"edge": 0.1}
    assert len(rejection_rows) == 1
    assert rejection_rows[0]["reason_code"] == "DUPLICATE_SIGNAL"
    assert rejection_rows[0]["details"]["dedupe_key"] == candidate.dedupe_key
    assert rejection_rows[0]["candidate"]["condition_id"] == "c1"
    assert rejection_rows[0]["candidate"]["token_id"] == "t1"

def _decision(**overrides: object) -> AlphaDecision:
    base: dict[str, Any] = dict(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="m1", market_slug="s1", condition_id="c1",
        token_id="t1", side=Side.UP, confidence=0.8,
        entry_reference_price=0.5, max_entry_price=0.55,
        seconds_to_close=120, data_freshness_ms=100,
        reason_codes=("EDGE",), metrics={},
    )
    base.update(overrides)
    return AlphaDecision(**base)


def _rejected(reason_code: str = "DUPLICATE_SIGNAL") -> SimpleNamespace:
    candidate = SignalCandidate.build(
        strategy="test",
        asset="BTC",
        timeframe="5m",
        market_id="m1",
        market_slug="s1",
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
    )
    return SimpleNamespace(
        reason_code=reason_code,
        detail={"dedupe_key": candidate.dedupe_key},
        candidate=candidate,
    )


def test_repeated_identical_rejected_decision_is_persisted_once_within_ttl() -> None:
    store = FakeStore()
    actor = ObservabilityActor(store=store)

    for _ in range(50):
        actor.record_rejected_decision(_rejected())

    assert len(store.tables.get("rejected_signals", [])) == 1


def test_rejected_decision_with_different_reason_is_persisted() -> None:
    store = FakeStore()
    actor = ObservabilityActor(store=store)

    actor.record_rejected_decision(_rejected("DUPLICATE_SIGNAL"))
    actor.record_rejected_decision(_rejected("STALE_ORDERBOOK"))

    assert len(store.tables.get("rejected_signals", [])) == 2


def test_rejected_decision_is_persisted_again_after_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    from polysignal_lab.nautilus_runtime import observability as obs_module

    clock = {"now": 1000.0}
    monkeypatch.setattr(obs_module.time, "monotonic", lambda: clock["now"])
    store = FakeStore()
    actor = ObservabilityActor(store=store)

    actor.record_rejected_decision(_rejected())
    clock["now"] += 61.0
    actor.record_rejected_decision(_rejected())

    assert len(store.tables.get("rejected_signals", [])) == 2


def test_repeated_identical_rejected_nautilus_decision_is_persisted_once_within_ttl() -> None:
    store = FakeStore()
    actor = ObservabilityActor(store=store)

    for _ in range(50):
        actor.record_decision(_decision(), accepted=False)
    actor.drain_telemetry_once()

    assert len(store.tables.get("nautilus_decision", [])) == 1


def test_accepted_decisions_are_never_suppressed() -> None:
    store = FakeStore()
    actor = ObservabilityActor(store=store)

    actor.record_decision(_decision(), accepted=True)
    actor.record_decision(_decision(), accepted=True)
    while actor.drain_telemetry_once():
        pass

    assert len(store.tables.get("nautilus_decision", [])) == 2










def test_record_nautilus_projection_events_write_projected_rows() -> None:
    store = FakeStore()
    actor = ObservabilityActor(store=store)

    actor.record_nautilus_order_event(
        SimpleNamespace(
            client_order_id="C-001",
            instrument_id="up-token.POLYMARKET",
            order_side="BUY",
            order_type="LIMIT",
            time_in_force="GTD",
            quantity=10.0,
            price=0.01,
            status="ACCEPTED",
            metrics={"level_price": 0.01},
            tags=["strategy=one_cent_buy", "condition_id=condition-btc-5m"],
            ts_event=datetime(2026, 6, 27, tzinfo=UTC),
        )
    )
    actor.record_nautilus_fill_event(
        SimpleNamespace(
            client_order_id="C-001",
            instrument_id="up-token.POLYMARKET",
            trade_id="T-001",
            last_qty=10.0,
            last_px=0.01,
            liquidity_side="TAKER",
            metrics={"level_price": 0.01},
        )
    )
    actor.record_nautilus_position(
        SimpleNamespace(
            id="P-001",
            instrument_id="up-token.POLYMARKET",
            signed_qty=10.0,
            avg_px_open=0.01,
            realized_pnl=0.0,
            is_closed=False,
        )
    )
    while actor.drain_telemetry_once():
        pass

    order_rows = store.tables["nautilus_order"]
    fill_rows = store.tables["nautilus_fill"]
    position_rows = store.tables["nautilus_position"]

    assert order_rows[0]["client_order_id"] == "C-001"
    assert order_rows[0]["paper_order_id"] == "C-001"
    assert order_rows[0]["status"] == "ACCEPTED"
    assert order_rows[0]["metrics"]["level_price"] == 0.01
    assert fill_rows[0]["client_order_id"] == "C-001"
    assert fill_rows[0]["trade_id"] == "T-001"
    assert fill_rows[0]["paper_order_id"] == "C-001"
    assert fill_rows[0]["paper_fill_id"] == "T-001"
    assert position_rows[0]["position_id"] == "P-001"
    assert position_rows[0]["paper_position_id"] == "P-001"
    assert position_rows[0]["is_closed"] is False

def test_nautilus_projection_events_with_integer_timestamps_get_unique_event_ids() -> None:
    persistence = FakePersistence()
    actor = ObservabilityActor(store=NautilusEventStoreAdapter(persistence))

    actor.record_nautilus_order_event(
        SimpleNamespace(
            client_order_id="C-001",
            instrument_id="up-token.POLYMARKET",
            order_side="BUY",
            order_type="LIMIT",
            time_in_force="GTD",
            quantity=10.0,
            price=0.01,
            status="ACCEPTED",
            metrics={"level_price": 0.01},
            tags=["strategy=one_cent_buy", "condition_id=condition-btc-5m"],
            ts_event=1_717_000_000_000_000_000,
        )
    )
    actor.record_nautilus_order_event(
        SimpleNamespace(
            client_order_id="C-002",
            instrument_id="up-token.POLYMARKET",
            order_side="BUY",
            order_type="LIMIT",
            time_in_force="GTD",
            quantity=12.0,
            price=0.02,
            status="ACCEPTED",
            metrics={"level_price": 0.02},
            tags=["strategy=one_cent_buy", "condition_id=condition-btc-5m"],
            ts_event=1_717_000_000_001_000_000,
        )
    )
    while actor.drain_telemetry_once():
        pass

    system_events = [
        payload
        for name, payload in persistence.calls
        if name == "insert_system_event"
    ]
    assert len(system_events) == 2
    first_event = cast(dict[str, object], system_events[0])
    second_event = cast(dict[str, object], system_events[1])
    assert first_event["created_at"] != ""
    assert second_event["created_at"] != ""
    assert first_event["event_id"] != second_event["event_id"]



def test_event_count_increments() -> None:
    actor = ObservabilityActor()
    assert actor.event_count == 0
    decision = AlphaDecision(
        strategy="t", asset="BTC", timeframe="5m",
        market_id="m", market_slug="s", condition_id="c",
        token_id="t", side=Side.UP, confidence=0.5,
        entry_reference_price=0.5, max_entry_price=0.55,
        seconds_to_close=120, data_freshness_ms=100,
        reason_codes=(), metrics={},
    )
    actor.record_decision(decision, accepted=True)
    assert actor.event_count == 1


def test_decision_policy_control_proxies_disable() -> None:
    policy = DecisionPolicyActor()
    ctrl = DecisionPolicyControl(policy)

    assert ctrl.is_strategy_enabled("vwap_momentum")
    ctrl.set_strategy_enabled("vwap_momentum", enabled=False)
    assert not ctrl.is_strategy_enabled("vwap_momentum")


def test_decision_policy_control_returns_status_payload() -> None:
    policy = DecisionPolicyActor()
    ctrl = DecisionPolicyControl(policy)

    ctrl.set_strategy_enabled("test_strat", enabled=False)
    payload = ctrl.status_payload()
    assert "disabled_strategies" in payload
    disabled = payload["disabled_strategies"]
    assert isinstance(disabled, list)
    assert "test_strat" in disabled


class FakePersistence:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.logs: list[tuple[str, dict[str, Any]]] = []

    def insert_signal(self, signal: object) -> None:
        self.calls.append(("insert_signal", signal))

    def insert_rejected_signal(self, rejected: object) -> None:
        self.calls.append(("insert_rejected_signal", rejected))

    def insert_paper_order(self, order: object) -> None:
        self.calls.append(("insert_paper_order", order))

    def upsert_paper_order(self, order: object) -> None:
        self.calls.append(("upsert_paper_order", order))

    def insert_paper_fill(self, fill: object) -> None:
        self.calls.append(("insert_paper_fill", fill))

    def upsert_paper_position(self, position: object) -> None:
        self.calls.append(("upsert_paper_position", position))

    def insert_paper_trade_result(self, result: object) -> None:
        self.calls.append(("insert_paper_trade_result", result))

    def insert_system_event(self, event: object) -> None:
        self.calls.append(("insert_system_event", event))

    def append_log(self, stream: str, payload: object) -> None:
        self.logs.append((stream, dict(cast(Mapping[str, Any], payload))))


class FakePublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def send(
        self,
        message: str,
        message_type: str,
        signal_id: str | None = None,
    ) -> object:
        del signal_id
        self.calls.append((message, message_type))
        return None


def test_nautilus_persistence_table_classification_separates_telemetry_from_critical_state() -> None:
    from polysignal_lab.nautilus_runtime.observability import (
        PersistenceClass,
        persistence_class_for_table,
    )

    assert persistence_class_for_table("nautilus_decision") is PersistenceClass.BEST_EFFORT_TELEMETRY
    assert persistence_class_for_table("nautilus_order") is PersistenceClass.BEST_EFFORT_TELEMETRY
    assert persistence_class_for_table("nautilus_fill") is PersistenceClass.BEST_EFFORT_TELEMETRY
    assert persistence_class_for_table("nautilus_position") is PersistenceClass.BEST_EFFORT_TELEMETRY
    assert persistence_class_for_table("health_snapshot") is PersistenceClass.BEST_EFFORT_TELEMETRY
    assert persistence_class_for_table("signals") is PersistenceClass.DURABLE_OR_DEGRADED
    assert persistence_class_for_table("rejected_signals") is PersistenceClass.DURABLE_OR_DEGRADED
    assert persistence_class_for_table("orders") is PersistenceClass.CRITICAL_PAPER_STATE
    assert persistence_class_for_table("fills") is PersistenceClass.CRITICAL_PAPER_STATE
    assert persistence_class_for_table("positions") is PersistenceClass.CRITICAL_PAPER_STATE
    assert persistence_class_for_table("settlements") is PersistenceClass.CRITICAL_PAPER_STATE


def test_unknown_nautilus_persistence_table_remains_fatal() -> None:
    from polysignal_lab.nautilus_runtime.observability import (
        PersistenceClass,
        persistence_class_for_table,
    )

    assert persistence_class_for_table("schema_migration") is PersistenceClass.FATAL_ON_LOSS


class LockingSystemEventPersistence(FakePersistence):
    def insert_system_event(self, event: object) -> None:
        raise sqlite3.OperationalError("database is locked")


class LockingCriticalPersistence(FakePersistence):
    def upsert_paper_order(self, order: object) -> None:
        raise sqlite3.OperationalError("database is locked")


def test_event_store_raises_on_critical_paper_state_sqlite_lock() -> None:
    adapter = NautilusEventStoreAdapter(LockingCriticalPersistence())

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        adapter.insert_json("orders", {"paper_order_id": "order-1"})


def test_nautilus_event_store_keeps_runtime_callbacks_alive_when_observability_sqlite_is_locked() -> None:
    persistence = LockingSystemEventPersistence()
    adapter = NautilusEventStoreAdapter(persistence)

    adapter.insert_json("nautilus_order", {"client_order_id": "C-001", "ts": "2026-07-03T12:31:01Z"})

    assert persistence.calls == []
    assert [(stream, payload["client_order_id"]) for stream, payload in persistence.logs] == [
        ("nautilus_orders", "C-001")
    ]


def test_event_store_routes_known_tables_and_rejects_unknown() -> None:
    persistence = FakePersistence()
    adapter = NautilusEventStoreAdapter(persistence)

    adapter.insert_json("signals", {"signal_id": "s1"})
    adapter.insert_json("rejected_signals", {"rejected_id": "r1"})
    adapter.insert_json("orders", {"paper_order_id": "o1"})
    adapter.insert_json("fills", {"paper_fill_id": "f1"})
    adapter.insert_json("positions", {"paper_position_id": "p1"})
    adapter.insert_json("settlements", {"paper_trade_id": "t1"})
    adapter.insert_json("health_snapshot", {"event_id": "h1", "event_type": "health_snapshot", "severity": "info", "created_at": "now"})

    assert [name for name, _ in persistence.calls] == [
        "insert_signal",
        "insert_rejected_signal",
        "upsert_paper_order",
        "insert_paper_fill",
        "upsert_paper_position",
        "insert_paper_trade_result",
        "insert_system_event",
    ]
    assert [stream for stream, _ in persistence.logs] == [
        "signals",
        "rejected_signals",
        "paper_orders",
        "paper_fills",
        "paper_positions",
        "paper_trade_results",
        "system_events",
    ]
    with pytest.raises(ValueError, match="Unknown Nautilus event table"):
        adapter.insert_json("unknown", {})




def test_event_store_upserts_terminal_order_update(tmp_path) -> None:
    persistence = PersistenceService(
        JSONLStore(tmp_path / "logs"),
        SQLiteStore(tmp_path / "paper.sqlite"),
        StateStore(tmp_path / "state"),
    )
    adapter = NautilusEventStoreAdapter(persistence)
    order = PaperOrder(
        paper_order_id="order-1", signal_id="sig-1", token_id="t1",
        side=Side.UP, limit_price=0.82, stake_usdc=10.0,
        reference_price=0.82, asset="BTC", timeframe="5m", strategy="test",
        market_id="m1", market_slug="s1", status=OrderStatus.RESTING,
    )

    adapter.insert_json("orders", order.model_dump(mode="json"))
    adapter.insert_json(
        "orders",
        order.model_copy(update={"status": OrderStatus.REJECTED}).model_dump(mode="json"),
    )

    rows = persistence.query_json("paper_orders")
    persistence.close()
    assert len(rows) == 1
    assert rows[0]["paper_order_id"] == "order-1"
    assert rows[0]["status"] == "REJECTED"


def test_notifier_adapter_sends_in_thread() -> None:
    publisher = FakePublisher()
    adapter = NautilusNotifierAdapter(publisher)

    asyncio.run(adapter.send("started", "startup"))

    assert publisher.calls == [("started", "startup")]
