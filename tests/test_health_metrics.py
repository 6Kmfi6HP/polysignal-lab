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


async def test_scheduler_records_market_data_health(tmp_path, settings, market) -> None:
    from polysignal_lab.app.scheduler import PolySignalScheduler
    from polysignal_lab.app.scheduler_health import sync_runtime_health
    from polysignal_lab.domain.orderbook import OrderBook
    from polysignal_lab.domain.spot import SpotPrice

    scheduler = PolySignalScheduler(settings, base_dir=tmp_path)
    scheduler.ctx.markets.upsert_many([market])
    scheduler._latest_market_token_ids = tuple(token.token_id for token in market.outcome_tokens)
    scheduler.ctx.books.update_from_snapshot(OrderBook(token_id=market.outcome_tokens[0].token_id))
    scheduler.ctx.books.mark_stale(market.outcome_tokens[1].token_id, "RECONNECT_RESEED_FAILED")
    scheduler.ctx.books.mark_stale("obsolete-token", "OLD_SUBSCRIPTION")
    scheduler.poly_ws.note_connected(token_ids=list(scheduler._latest_market_token_ids))
    scheduler.poly_ws.note_reconnect(RuntimeError("reconnect"))

    snapshot = sync_runtime_health(scheduler)
    components = {component.name: component for component in snapshot.components}

    assert components["clob_ws"].status == "degraded"
    assert components["clob_ws"].metrics["subscribed_token_count"] == 2
    assert components["clob_ws"].metrics["stale_token_count"] == 1
    assert components["clob_ws"].metrics["reconnect_count"] == 1

    scheduler._latest_market_token_ids = (*scheduler._latest_market_token_ids, "missing-active-token")
    scheduler.poly_ws.note_connected(token_ids=list(scheduler._latest_market_token_ids))
    scheduler.ctx.spots.update(SpotPrice(asset="BTC", symbol="BTCUSDT", price=100.0))
    scheduler.binance_ws.note_connected()
    scheduler.binance_ws.note_reconnect(RuntimeError("binance reconnect"))

    snapshot = sync_runtime_health(scheduler)
    components = {component.name: component for component in snapshot.components}

    assert components["clob_ws"].metrics["subscribed_token_count"] == 3
    assert components["clob_ws"].metrics["stale_token_count"] == 2
    assert components["binance_ws"].status == "degraded"
    assert components["binance_ws"].metrics["connected"] is False

    scheduler._latest_market_token_ids = ()
    scheduler._market_ws_token_ids = ()
    scheduler._market_refresh_completed = True

    snapshot = sync_runtime_health(scheduler)
    components = {component.name: component for component in snapshot.components}

    assert components["clob_ws"].metrics["stale_token_count"] == 0



async def test_clob_ws_idle_after_empty_market_refresh_is_ok(tmp_path, settings) -> None:
    from polysignal_lab.app.scheduler import PolySignalScheduler
    from polysignal_lab.app.scheduler_health import sync_runtime_health
    from polysignal_lab.domain.orderbook import OrderBook

    scheduler = PolySignalScheduler(settings, base_dir=tmp_path)
    scheduler._market_refresh_completed = True
    scheduler._latest_market_token_ids = ()
    scheduler._market_ws_token_ids = ("obsolete-token",)
    scheduler.ctx.books.update_from_snapshot(OrderBook(token_id="obsolete-token"))
    scheduler.ctx.books.mark_stale("obsolete-token", "OLD_SUBSCRIPTION")
    scheduler.poly_ws.note_connected(token_ids=["obsolete-token"])

    snapshot = sync_runtime_health(scheduler)
    components = {component.name: component for component in snapshot.components}

    assert components["clob_ws"].status == "ok"
    assert components["clob_ws"].metrics["stale_token_count"] == 0


async def test_binance_ws_requires_every_configured_spot(tmp_path, settings) -> None:
    from polysignal_lab.app.scheduler import PolySignalScheduler
    from polysignal_lab.app.scheduler_health import sync_runtime_health
    from polysignal_lab.domain.spot import SpotPrice

    scheduler = PolySignalScheduler(settings, base_dir=tmp_path)
    scheduler.ctx.spots.update(SpotPrice(asset="BTC", symbol="BTCUSDT", price=100.0))
    scheduler.binance_ws.note_connected()

    snapshot = sync_runtime_health(scheduler)
    components = {component.name: component for component in snapshot.components}

    assert components["binance_ws"].status == "degraded"
    assert components["binance_ws"].metrics["eth_spot_lag_ms"] is None

    for asset, symbol in settings.data.binance.symbols.items():
        scheduler.ctx.spots.update(SpotPrice(asset=asset, symbol=symbol, price=100.0))

    snapshot = sync_runtime_health(scheduler)
    components = {component.name: component for component in snapshot.components}

    assert components["binance_ws"].status == "ok"