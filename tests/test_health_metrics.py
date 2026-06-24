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

    assert store.restore_latest_system_event("health_snapshot") == newer
