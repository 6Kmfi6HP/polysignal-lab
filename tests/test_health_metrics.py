"""
Input: __future__, __future__.annotations, polysignal_lab.observability.health, polysignal_lab.observability.health.HealthRegistry, polysignal_lab.storage.sqlite_store, polysignal_lab.storage.sqlite_store.SQLiteStore
Output: test_health_registry_aggregates_component_status_and_transitions, test_health_registry_set_accepts_uppercase_status_and_error_details, test_health_registry_metric_helpers_preserve_status, test_sqlite_restores_latest_system_event_payload, test_runtime_records_gate_rejections_and_persists_health_snapshot
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from polysignal_lab.observability.health import HealthRegistry
from polysignal_lab.storage.sqlite_store import SQLiteStore


def test_health_registry_aggregates_component_status_and_transitions() -> None:
    registry = HealthRegistry()

    registry.mark_ok("gamma", discovered_market_count=8)
    registry.mark_degraded("clob_ws", "reconnect", reconnect_count=1)
    snapshot = registry.snapshot()
    transitions = registry.consume_transition_events()

    assert snapshot.status == "degraded"
    assert [component.name for component in snapshot.components] == ["clob_ws", "gamma"]
    assert snapshot.components[0].status == "degraded"
    assert snapshot.components[0].last_error == "reconnect"
    assert snapshot.components[0].metrics["reconnect_count"] == 1
    assert len(transitions) == 2
    assert transitions[0]["event_type"] == "component_health_transition"
    assert transitions[0]["severity"] in {"INFO", "WARNING"}
    assert registry.consume_transition_events() == []


def test_health_registry_set_accepts_uppercase_status_and_error_details() -> None:
    registry = HealthRegistry()

    registry.set("gamma", "OK", discovered_market_count=8)
    registry.set("gamma", "DEGRADED", error="stale", stale_count=1)

    snapshot = registry.snapshot()
    assert snapshot.status == "degraded"
    assert snapshot.components[0].status == "degraded"
    assert snapshot.components[0].last_error == "stale"
    assert snapshot.components[0].metrics["discovered_market_count"] == 8
    assert snapshot.components[0].metrics["stale_count"] == 1


def test_health_registry_metric_helpers_preserve_status() -> None:
    registry = HealthRegistry()

    registry.inc_metric("clob_ws", "reconnect_count")
    registry.set_metric("clob_ws", "last_sequence", 42)
    registry.mark_down("clob_ws", "closed")
    registry.inc_metric("clob_ws", "reconnect_count")

    component = registry.snapshot().components[0]
    assert component.status == "down"
    assert component.last_error == "closed"
    assert component.metrics["reconnect_count"] == 2
    assert component.metrics["last_sequence"] == 42


def test_sqlite_restores_latest_system_event_payload(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "health.sqlite3")
    older = {
        "event_id": "evt-old",
        "event_type": "health_snapshot",
        "severity": "INFO",
        "created_at": "2026-06-23T00:00:00+00:00",
        "status": "ok",
    }
    newer = {
        "event_id": "evt-new",
        "event_type": "health_snapshot",
        "severity": "WARNING",
        "created_at": "2026-06-23T00:01:00+00:00",
        "status": "degraded",
    }

    store.insert_system_event(older)
    store.insert_system_event(newer)

    assert store.query_latest_system_event("health_snapshot") == newer


async def test_runtime_records_gate_rejections_and_persists_health_snapshot(
    tmp_path, market_view, settings
) -> None:
    from polysignal_lab.app import scheduler_health
    from polysignal_lab.nautilus_runtime.runtime_context_factory import build_nautilus_runtime_context
    from polysignal_lab.signal_layer.gate import SignalGate
    from signal_helpers import ptb_signal_from_view

    runtime = build_nautilus_runtime_context(settings, base_dir=tmp_path)
    gate = SignalGate(settings.signal, settings.data.polymarket, settings.data.binance)
    signal = ptb_signal_from_view(market_view, settings).model_copy(update={"confidence": 0.01})

    decision = gate.evaluate(signal, market_view)
    assert decision.rejected is not None
    runtime.health.inc_metric(
        "signal_gate", f"rejected_{decision.rejected.reason_code}"
    )
    scheduler_health.persist_health_snapshot(runtime)

    latest = runtime.sqlite.query_latest_system_event("health_snapshot")
    assert latest is not None
    components = {component["name"]: component for component in latest["components"]}
    assert components["signal_gate"]["metrics"]["rejected_CONFIDENCE_TOO_LOW"] == 1
