from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock

import httpx
import pytest

from fastapi.testclient import TestClient

from polysignal_lab.dashboard.app import create_dashboard_app
from polysignal_lab.dashboard.ports import (
    FileRuntimeHealthReader,
    ReportingReadPort,
)
from polysignal_lab.domain.enums import PositionStatus, Side
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.domain.reporting_result import DailyReport
from polysignal_lab.observability.runtime_health import write_runtime_heartbeat
from polysignal_lab.storage.sqlite_store import SQLiteStore
from polysignal_lab.domain.strategy_readiness import StrategyMarketStatus
from signal_helpers import ptb_signal_from_view
from factories import sample_report_result, sample_storage_lifecycle


def _client_with_store(
    tmp_path, market_view, settings
) -> tuple[TestClient, SQLiteStore]:
    store = SQLiteStore(tmp_path / "dashboard.sqlite3")
    signal = ptb_signal_from_view(market_view, settings)
    lifecycle = sample_storage_lifecycle(signal)
    rejected = lifecycle.rejected.model_copy(
        update={
            "reason_code": "STALE_SPOT_PRICE",
            "details": {
                **lifecycle.rejected.details,
                "reason_code": "STALE_SPOT_PRICE",
                "source": "spot_price",
                "lag_ms": 3_000,
                "threshold_ms": 2_000,
                "policy_source": "strategy_and_global",
            },
        }
    )
    store.insert_signal(signal)
    store.insert_rejected_signal(rejected)
    store.insert_system_event(
        {
            "event_id": "evt-order-1",
            "event_type": "nautilus_order",
            "severity": "info",
            "created_at": str(lifecycle.order["created_at"]),
            **lifecycle.order,
        }
    )
    store.insert_system_event(
        {
            "event_id": "evt-fill-1",
            "event_type": "nautilus_fill",
            "severity": "info",
            "created_at": str(lifecycle.fill["created_at"]),
            **lifecycle.fill,
        }
    )
    store.insert_report_result(lifecycle.result)
    store.insert_report_account_snapshot(lifecycle.account_snapshot)
    store.insert_daily_report(lifecycle.report)
    store.insert_telegram_publish(lifecycle.publish)
    store.insert_system_event(lifecycle.event)
    store.insert_system_event(
        {
            "event_id": "evt-nautilus-pos-1",
            "event_type": "nautilus_position",
            "severity": "info",
            "created_at": lifecycle.position["opened_at"],
            **lifecycle.position,
            "ts": lifecycle.position["opened_at"],
        }
    )
    return TestClient(create_dashboard_app(store)), store


async def _dashboard_get(
    store: SQLiteStore,
    path: str,
    *,
    params: dict[str, str] | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=create_dashboard_app(store))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        return await client.get(path, params=params)


def test_dashboard_uses_injected_reporting_read_port() -> None:
    reporting = Mock(spec=ReportingReadPort)
    reporting.signal_rows.return_value = [{"signal_id": "sig-port", "limit": 7}]
    client = TestClient(create_dashboard_app(reporting))

    response = client.get("/api/signals", params={"limit": 7})

    assert response.status_code == 200
    assert response.json() == [{"signal_id": "sig-port", "limit": 7}]
    reporting.signal_rows.assert_called_once_with(7)


async def test_dashboard_readonly_endpoints_return_stored_data(
    tmp_path, market_view, settings
) -> None:
    # Given: a temp SQLite dashboard store populated through the public storage API.
    client, store = _client_with_store(tmp_path, market_view, settings)
    signal = store.query_json("signals")[0]

    # When: every read-only dashboard endpoint is requested.
    health = client.get("/health")
    overview = client.get("/api/overview")
    signals = client.get("/api/signals")
    rejected = client.get("/api/rejected-signals")
    positions = client.get("/api/positions")
    trades = client.get("/api/trades")
    root = client.get("/")

    # Then: payloads contain the persisted rows; the API no longer serves any HTML.
    assert health.status_code == 200
    assert health.json()["counts"]["signals"] == 1
    assert health.json()["status"] in {"ok", "unknown", "degraded", "down"}
    assert isinstance(health.json()["components"], list)
    assert isinstance(health.json()["recent_system_events"], list)
    assert overview.status_code == 200
    assert overview.json()["latest_report"]["report_id"] == "dr-1"
    assert overview.json()["counts"]["report_results"] == 1
    assert signals.json()[0]["signal_id"] == signal["signal_id"]
    assert rejected.json()[0]["candidate"]["signal_id"] == signal["signal_id"]
    assert rejected.json()[0]["reason_code"] == "STALE_SPOT_PRICE"
    assert rejected.json()[0]["details"]["lag_ms"] == 3_000
    assert rejected.json()[0]["details"]["threshold_ms"] == 2_000
    assert rejected.json()[0]["details"]["policy_source"] == "strategy_and_global"
    assert positions.json()["items"][0]["report_position_id"] == "pp-1"
    assert trades.json()["items"][0]["report_result_id"] == "pt-1"
    assert root.status_code == 404


def test_dashboard_report_summary_aggregates_all_stored_results(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "dashboard-report-summary.sqlite3")
    store.insert_report_result(
        sample_report_result(
            report_result_id="result-win",
            pnl_usdc=8.0,
            roi=0.4,
        )
    )
    store.insert_report_result(
        sample_report_result(
            report_result_id="result-loss",
            signal_id="sig-loss",
            report_position_id="pos-loss",
            pnl_usdc=-3.0,
            roi=-0.2,
            result="LOSS",
        )
    )
    client = TestClient(create_dashboard_app(store))

    response = client.get("/api/report-summary")

    assert response.status_code == 200
    assert response.json() == {
        "total_pnl_usdc": 5.0,
        "average_roi": pytest.approx(0.1),
        "closed_trades": 2,
    }


def test_dashboard_trades_return_latest_results_with_stable_ties(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "dashboard-trades.sqlite3")
    for report_result_id, closed_at in (
        ("result-old", "2026-07-20T00:00:00+00:00"),
        ("result-a", "2026-08-02T00:00:00+00:00"),
        ("result-z", "2026-08-02T00:00:00+00:00"),
    ):
        store.insert_report_result(
            sample_report_result(
                report_result_id=report_result_id,
                signal_id=f"signal-{report_result_id}",
                report_position_id=f"position-{report_result_id}",
                opened_at=closed_at,
                closed_at=closed_at,
            )
        )
    client = TestClient(create_dashboard_app(store))

    latest = client.get("/api/trades", params={"limit": 1})
    all_trades = client.get("/api/trades", params={"limit": 3})

    assert latest.status_code == 200
    assert latest.json()["items"][0]["report_result_id"] == "result-z"
    assert [row["report_result_id"] for row in all_trades.json()["items"]] == [
        "result-z",
        "result-a",
        "result-old",
    ]


def test_dashboard_report_trades_paginate_with_offset_and_total(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "dashboard-report-pagination.sqlite3")
    for i in range(3):
        store.insert_report_result(
            sample_report_result(
                report_result_id=f"trade-{i}",
                signal_id=f"signal-{i}",
                report_position_id=f"position-{i}",
                closed_at=f"2026-08-01T00:0{i}:00+00:00",
            )
        )
    client = TestClient(create_dashboard_app(store))

    trades = client.get("/api/trades", params={"limit": 2, "offset": 1})

    assert trades.status_code == 200
    assert [row["report_result_id"] for row in trades.json()["items"]] == [
        "trade-1",
        "trade-0",
    ]
    assert trades.json()["total"] == 3


async def test_dashboard_positions_returns_latest_metadata_first(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "dashboard-positions.sqlite3")
    old = {
        "report_position_id": "old-pos",
        "position_id": "old-pos",
        "signal_id": "",
        "report_order_id": "old-order",
        "report_fill_id": "old-fill",
        "strategy": "late_consensus",
        "asset": "",
        "timeframe": "",
        "market_id": "2676328",
        "market_slug": "",
        "token_id": "old-token",
        "side": Side.UP.value,
        "entry_price": 0.5,
        "shares": 10.0,
        "stake_usdc": 5.0,
        "opened_at": datetime(2026, 6, 25, tzinfo=timezone.utc).isoformat(),
        "status": PositionStatus.OPEN.value,
        "is_closed": False,
    }
    latest = {
        "report_position_id": "latest-pos",
        "position_id": "latest-pos",
        "signal_id": "sig-latest",
        "report_order_id": "latest-order",
        "report_fill_id": "latest-fill",
        "strategy": "late_consensus",
        "asset": "BTC",
        "timeframe": "5m",
        "market_id": "2676527",
        "market_slug": "btc-updown-5m",
        "token_id": "latest-token",
        "side": Side.UP.value,
        "entry_price": 0.6,
        "shares": 12.0,
        "stake_usdc": 7.2,
        "opened_at": datetime(2026, 6, 26, tzinfo=timezone.utc).isoformat(),
        "status": PositionStatus.OPEN.value,
        "is_closed": False,
    }
    for pos in (old, latest):
        store.insert_system_event(
            {
                "event_id": f"evt-{pos['report_position_id']}",
                "event_type": "nautilus_position",
                "severity": "info",
                "created_at": pos["opened_at"],
                **pos,
                "ts": pos["opened_at"],
            }
        )
    response = await _dashboard_get(store, "/api/positions")

    assert response.status_code == 200
    rows = response.json()["items"]
    assert rows[0]["report_position_id"] == "latest-pos"
    assert rows[0]["status"] == "OPEN"
    assert rows[0]["is_closed"] is False
    assert rows[0]["position_id"] == "latest-pos"


def test_dashboard_report_orders_and_positions_paginate_by_offset_and_status(
    tmp_path,
) -> None:
    store = SQLiteStore(tmp_path / "dashboard-order-position-pagination.sqlite3")
    t = datetime(2026, 8, 1, 0, 10, tzinfo=timezone.utc)
    for i, status in enumerate(("FILLED", "REJECTED", "FILLED"), start=1):
        store.insert_system_event(
            {
                "event_id": f"evt-order-{i}",
                "event_type": "nautilus_order",
                "severity": "info",
                "created_at": t.isoformat(),
                "report_order_id": f"order-{i}",
                "client_order_id": f"order-{i}",
                "status": status,
                "signal_id": f"signal-{i}",
                "strategy": "ptb_diff",
                "market_id": "mkt-1",
                "ts": t.isoformat(),
            }
        )
        store.insert_system_event(
            {
                "event_id": f"evt-position-{i}",
                "event_type": "nautilus_position",
                "severity": "info",
                "created_at": t.isoformat(),
                "report_position_id": f"position-{i}",
                "market_id": "mkt-1",
                "token_id": "token-up",
                "side": Side.UP.value,
                "status": PositionStatus.OPEN.value,
                "is_closed": False,
                "entry_price": 0.5,
                "shares": 10.0,
                "stake_usdc": 5.0,
                "opened_at": t.isoformat(),
                "ts": t.isoformat(),
            }
        )

    client = TestClient(create_dashboard_app(store))

    orders = client.get("/api/report-orders", params={"limit": 2, "offset": 1})
    positions = client.get(
        "/api/positions",
        params={"limit": 2, "offset": 1, "status": "open"},
    )
    rejected = client.get(
        "/api/report-orders",
        params={"limit": 500, "offset": 0, "status": "rejected"},
    )

    assert orders.status_code == 200
    assert {row["report_order_id"] for row in orders.json()["items"]} == {
        "order-2",
        "order-1",
    }
    assert orders.json()["total"] == 3

    assert positions.status_code == 200
    assert {row["report_position_id"] for row in positions.json()["items"]} == {
        "position-2",
        "position-1",
    }
    assert positions.json()["total"] == 3

    assert rejected.status_code == 200
    assert [row["report_order_id"] for row in rejected.json()["items"]] == [
        "order-2"
    ]
    assert rejected.json()["total"] == 1


async def test_dashboard_reduces_order_and_position_lifecycle_to_current_state(
    tmp_path,
) -> None:
    store = SQLiteStore(tmp_path / "dashboard-current-state.sqlite3")
    order_id = "order-current"
    position_id = "position-current"
    opened_at = "2026-07-13T12:00:00+00:00"
    closed_at = "2026-07-13T12:05:00+00:00"
    events = (
        {
            "event_id": "evt-order-filled",
            "event_type": "nautilus_order",
            "severity": "info",
            "created_at": closed_at,
            "report_order_id": order_id,
            "status": "FILLED",
            "ts": "not-a-date",
        },
        {
            "event_id": "evt-position-closed",
            "event_type": "nautilus_position",
            "severity": "info",
            "created_at": closed_at,
            "report_position_id": position_id,
            "side": Side.UP.value,
            "entry_price": 0.5,
            "shares": 20.0,
            "stake_usdc": 10.0,
            "opened_at": opened_at,
            "closed_at": closed_at,
            "status": PositionStatus.CLOSED.value,
            "is_closed": True,
            "ts": closed_at,
        },
        {
            "event_id": "evt-order-resting",
            "event_type": "nautilus_order",
            "severity": "info",
            "created_at": opened_at,
            "report_order_id": order_id,
            "status": "ACCEPTED",
            "ts": opened_at,
        },
        {
            "event_id": "evt-position-open",
            "event_type": "nautilus_position",
            "severity": "info",
            "created_at": opened_at,
            "report_position_id": position_id,
            "side": Side.UP.value,
            "entry_price": 0.5,
            "shares": 20.0,
            "stake_usdc": 10.0,
            "opened_at": opened_at,
            "status": PositionStatus.OPEN.value,
            "is_closed": False,
            "ts": opened_at,
        },
    )
    for event in events:
        store.insert_system_event(event)

    orders = await _dashboard_get(store, "/api/report-orders")
    resting_orders = await _dashboard_get(
        store,
        "/api/report-orders",
        params={"status": "resting"},
    )
    positions = await _dashboard_get(store, "/api/positions")
    open_positions = await _dashboard_get(
        store,
        "/api/positions",
        params={"status": "open"},
    )

    assert orders.status_code == 200
    assert len(orders.json()["items"]) == 1
    assert orders.json()["items"][0]["report_order_id"] == order_id
    assert orders.json()["items"][0]["status"] == "FILLED"
    assert resting_orders.json()["items"] == []
    assert positions.status_code == 200
    assert len(positions.json()["items"]) == 1
    assert positions.json()["items"][0]["report_position_id"] == position_id
    assert positions.json()["items"][0]["status"] == "CLOSED"
    assert positions.json()["items"][0]["is_closed"] is True
    assert open_positions.json()["items"] == []

    store.insert_system_event(
        {
            "event_id": "evt-order-invalid-latest",
            "event_type": "nautilus_order",
            "severity": "info",
            "created_at": "2026-07-13T12:10:00+00:00",
            "report_order_id": order_id,
            "status": "UNKNOWN",
            "ts": "2026-07-13T12:10:00+00:00",
        }
    )
    invalid_orders = await _dashboard_get(store, "/api/report-orders")

    assert invalid_orders.json()["items"] == []
    assert store.counts()["system_events"] == 5


async def test_dashboard_positions_normalize_nautilus_rows_with_market_lookup(
    tmp_path,
) -> None:
    store = SQLiteStore(tmp_path / "dashboard-normalized-positions.sqlite3")
    store.upsert_market(
        Market(
            market_id="btc-15m",
            market_slug="btc-updown-15m",
            condition_id="condition-btc-15m",
            asset="BTC",
            timeframe="15m",
            outcome_tokens=[
                OutcomeToken(
                    token_id="up-token",
                    side=Side.UP,
                    outcome_name="Up",
                    market_id="btc-15m",
                ),
                OutcomeToken(
                    token_id="down-token",
                    side=Side.DOWN,
                    outcome_name="Down",
                    market_id="btc-15m",
                ),
            ],
        )
    )
    store.insert_system_event(
        {
            "event_id": "evt-pos-lookup",
            "event_type": "nautilus_position",
            "severity": "info",
            "created_at": "2026-06-26T00:00:00+00:00",
            "position_id": "P-001",
            "order_id": "C-001",
            "instrument_id": "down-token.POLYMARKET",
            "signed_qty": "12.0",
            "avg_entry_price": "0.60",
            "metrics": {"status": "OPEN"},
            "is_closed": False,
            "ts": "2026-06-26T00:00:00+00:00",
        }
    )
    response = await _dashboard_get(store, "/api/positions")

    assert response.status_code == 200
    row = response.json()["items"][0]
    assert row["report_position_id"] == "P-001"
    assert row["report_order_id"] == "C-001"
    assert row["market_id"] == "btc-15m"
    assert row["market_slug"] == "btc-updown-15m"
    assert row["asset"] == "BTC"
    assert row["timeframe"] == "15m"
    assert row["token_id"] == "down-token"
    assert row["side"] == "DOWN"
    assert row["entry_price"] == 0.6
    assert row["shares"] == 12.0
    assert row["stake_usdc"] == pytest.approx(7.2)


def test_dashboard_health_reports_missing_runtime_as_unknown(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "dashboard-health.sqlite3")
    runtime_health = FileRuntimeHealthReader(
        tmp_path / "state" / "runtime_heartbeat.json",
        max_age_sec=120,
        now=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
    )
    client = TestClient(create_dashboard_app(store, runtime_health))

    payload = client.get("/health").json()
    components = {component["name"]: component for component in payload["components"]}

    assert payload["status"] == "unknown"
    assert components["runtime"]["status"] == "unknown"
    assert components["runtime"]["reason"] == "heartbeat_missing"
    assert components["runtime"]["freshness_age_sec"] is None
    assert components["sqlite_storage"]["status"] == "ok"
    assert components["sqlite_storage"]["freshness_age_sec"] == 0


def test_dashboard_health_reports_stale_runtime_as_degraded(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "dashboard-health.sqlite3")
    heartbeat_path = tmp_path / "state" / "runtime_heartbeat.json"
    heartbeat_at = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    write_runtime_heartbeat(heartbeat_path, phase="running", now=heartbeat_at)
    runtime_health = FileRuntimeHealthReader(
        heartbeat_path,
        max_age_sec=120,
        now=heartbeat_at + timedelta(seconds=121),
    )
    client = TestClient(create_dashboard_app(store, runtime_health))

    payload = client.get("/health").json()
    components = {component["name"]: component for component in payload["components"]}

    assert payload["status"] == "degraded"
    assert components["runtime"]["status"] == "degraded"
    assert components["runtime"]["reason"] == "heartbeat_stale"
    assert components["runtime"]["freshness_age_sec"] == 121
    assert components["sqlite_storage"]["status"] == "ok"


def test_dashboard_health_reports_persistent_readiness_detail(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "dashboard-health.sqlite3")
    heartbeat_path = tmp_path / "state" / "runtime_heartbeat.json"
    started_at = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    detail: dict[str, object] = {
        "condition_id": "condition-a",
        "market_id": "m-a",
        "subscription_state": "awaiting_first_book",
        "last_book_at_by_side": {"UP": started_at.isoformat(), "DOWN": None},
        "freshness_ms_by_side": {"UP": 302_000, "DOWN": None},
        "max_freshness_ms": 302_000,
        "awaiting_book_sides": ["DOWN"],
    }
    write_runtime_heartbeat(
        heartbeat_path,
        phase="readiness_miss",
        readiness_key="condition-a",
        readiness_ok=False,
        readiness_detail=detail,
        now=started_at,
    )
    write_runtime_heartbeat(
        heartbeat_path,
        phase="market_data_evaluation",
        now=started_at + timedelta(seconds=301),
    )
    runtime_health = FileRuntimeHealthReader(
        heartbeat_path,
        max_age_sec=120,
        max_readiness_miss_sec=300,
        now=started_at + timedelta(seconds=302),
    )
    client = TestClient(create_dashboard_app(store, runtime_health))

    payload = client.get("/health").json()
    components = {component["name"]: component for component in payload["components"]}

    assert payload["status"] == "degraded"
    assert components["runtime"]["reason"] == "readiness_miss"
    assert components["runtime"]["metrics"]["readiness_detail_by_key"] == {
        "condition-a": detail
    }


def test_dashboard_health_keeps_fresh_runtime_ok_when_storage_fails(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "dashboard-health.sqlite3")
    heartbeat_path = tmp_path / "state" / "runtime_heartbeat.json"
    heartbeat_at = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    write_runtime_heartbeat(heartbeat_path, phase="running", now=heartbeat_at)
    runtime_health = FileRuntimeHealthReader(
        heartbeat_path,
        max_age_sec=120,
        now=heartbeat_at + timedelta(seconds=30),
    )
    store.close()
    client = TestClient(create_dashboard_app(store, runtime_health))

    payload = client.get("/health").json()
    components = {component["name"]: component for component in payload["components"]}

    assert payload["status"] == "degraded"
    assert components["runtime"]["status"] == "ok"
    assert components["runtime"]["freshness_age_sec"] == 30
    assert components["runtime"]["reason"] is None
    assert components["sqlite_storage"]["status"] == "degraded"
    assert components["sqlite_storage"]["reason"] == "storage_unavailable"


def test_dashboard_health_ignores_superseded_runtime_snapshot_status(
    monkeypatch,
    tmp_path,
) -> None:
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 7, 13, 12, 0, 30, tzinfo=timezone.utc)

    monkeypatch.setattr("polysignal_lab.dashboard.app.datetime", FixedDatetime)
    store = SQLiteStore(tmp_path / "dashboard-health.sqlite3")
    store.insert_system_event(
        {
            "event_id": "health-snap-old-runtime",
            "event_type": "health_snapshot",
            "severity": "ERROR",
            "created_at": "2026-07-13T11:00:00+00:00",
            "status": "down",
            "generated_at": "2026-07-13T11:00:00+00:00",
            "components": [
                {
                    "name": "runtime",
                    "status": "down",
                    "last_error": "heartbeat_stale",
                    "metrics": {},
                }
            ],
        }
    )
    heartbeat_path = tmp_path / "state" / "runtime_heartbeat.json"
    heartbeat_at = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    write_runtime_heartbeat(heartbeat_path, phase="running", now=heartbeat_at)
    runtime_health = FileRuntimeHealthReader(
        heartbeat_path,
        max_age_sec=120,
        now=heartbeat_at + timedelta(seconds=30),
    )
    client = TestClient(create_dashboard_app(store, runtime_health))

    payload = client.get("/health").json()
    components = {component["name"]: component for component in payload["components"]}

    assert payload["status"] == "ok"
    assert payload["generated_at"] == "2026-07-13T12:00:30+00:00"
    assert components["runtime"]["status"] == "ok"
    assert components["sqlite_storage"]["status"] == "ok"


def test_dashboard_health_returns_component_snapshot_from_system_events(
    tmp_path,
) -> None:
    store = SQLiteStore(tmp_path / "dashboard-health.sqlite3")
    store.insert_system_event(
        {
            "event_id": "health-snap-1",
            "event_type": "health_snapshot",
            "severity": "WARNING",
            "created_at": "2026-06-23T00:00:00+00:00",
            "status": "degraded",
            "generated_at": "2026-06-23T00:00:00+00:00",
            "components": [
                {
                    "name": "binance_ws",
                    "status": "degraded",
                    "last_success_at": None,
                    "last_error_at": "2026-06-23T00:00:00+00:00",
                    "last_error": "spot prices stale",
                    "metrics": {"btc_spot_lag_ms": 61000},
                }
            ],
        }
    )
    client = TestClient(create_dashboard_app(store))

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["components"][0]["name"] == "binance_ws"
    assert payload["components"][0]["metrics"]["btc_spot_lag_ms"] == 61000
    assert "counts" in payload
    assert payload["recent_system_events"][0]["event_id"] == "health-snap-1"


async def test_dashboard_exposes_paper_execution_quality(tmp_path) -> None:
    # Given: a rejected paper order and daily report with paper execution aggregates.
    store = SQLiteStore(tmp_path / "db.sqlite3")
    order = {
        "report_order_id": "po-rejected-dashboard",
        "signal_id": "sig-dashboard",
        "created_at": datetime(2026, 6, 22, tzinfo=timezone.utc).isoformat(),
        "asset": "BTC",
        "timeframe": "5m",
        "strategy": "ptb_diff",
        "market_id": "mkt-1",
        "market_slug": "btc-updown-5m",
        "token_id": "token-up",
        "side": Side.UP.value,
        "limit_price": 0.60,
        "reference_price": 0.50,
        "stake_usdc": 10.0,
        "status": "REJECTED",
        "reject_reason": "ENTRY_PRICE_MOVED",
        "metrics": {
            "normalized_reason": "ENTRY_PRICE_MOVED",
            "original_reason": "ASK_ABOVE_MAX_ENTRY",
        },
    }
    report = DailyReport(
        report_date=date(2026, 6, 22),
        starting_equity=1000.0,
        ending_equity=1000.0,
        net_pnl=0.0,
        return_rate=0.0,
        total_signals=1,
        order_count=1,
        fill_count=0,
        rejected_order_count=1,
        open_positions=0,
        closed_positions=0,
        win_count=0,
        loss_count=0,
        void_count=0,
        win_rate=0.0,
        total_pnl_usdc=0.0,
        average_roi=0.0,
        max_drawdown=0.0,
        profit_factor=None,
        rejects_by_reason={"ENTRY_PRICE_MOVED": 1},
        average_execution_staleness_ms=25.0,
    )
    store.insert_system_event(
        {
            "event_id": "evt-po-rejected",
            "event_type": "nautilus_order",
            "severity": "info",
            "created_at": order["created_at"],
            "report_order_id": order["report_order_id"],
            "client_order_id": order["report_order_id"],
            "status": order["status"],
            "reject_reason": order["reject_reason"],
            "strategy": order["strategy"],
            "market_id": order["market_id"],
            "signal_id": order["signal_id"],
            "ts": order["created_at"],
        }
    )
    store.insert_daily_report(report)
    # When: paper execution quality surfaces are read from the dashboard API.
    orders = await _dashboard_get(
        store, "/api/report-orders", params={"status": "rejected"}
    )
    overview = await _dashboard_get(store, "/api/overview")

    # Then: paper order rows and latest report aggregates expose them.
    assert orders.status_code == 200
    assert overview.status_code == 200
    assert orders.json()["items"][0]["reject_reason"] == "ENTRY_PRICE_MOVED"
    assert orders.json()["total"] == 1
    assert overview.json()["latest_report"]["rejects_by_reason"] == {
        "ENTRY_PRICE_MOVED": 1
    }


async def test_dashboard_order_count_normalize_nautilus_rows() -> None:
    store = SQLiteStore(":memory:")
    store.insert_system_event(
        {
            "event_id": "evt-order-1",
            "event_type": "nautilus_order",
            "severity": "info",
            "created_at": "2026-06-26T00:00:00+00:00",
            "order_id": "C-001",
            "instrument_id": "down-token.POLYMARKET",
            "side": "BUY",
            "order_type": "LIMIT",
            "time_in_force": "IOC",
            "quantity": "40.0",
            "price": "0.64",
            "status": "ACCEPTED",
            "metrics": {
                "signal_id": "sig-1",
                "strategy": "ptb_diff",
                "asset": "BTC",
                "timeframe": "15m",
                "market_id": "btc-15m",
                "market_slug": "btc-updown-15m",
                "token_id": "down-token",
                "side": "DOWN",
                "stake_usdc": 32.0,
                "level_price": 0.63,
                "nonfinite": float("inf"),
            },
            "ts": "2026-06-26T00:00:00+00:00",
        }
    )
    response = await _dashboard_get(store, "/api/report-orders")

    assert response.status_code == 200
    row = response.json()["items"][0]
    assert row["report_order_id"] == "C-001"
    assert row["asset"] == "BTC"
    assert row["timeframe"] == "15m"
    assert row["token_id"] == "down-token"
    assert row["side"] == "DOWN"
    assert row["limit_price"] == 0.64
    assert row["reference_price"] == 0.63
    assert row["stake_usdc"] == 32.0
    assert row["shares"] == 40.0
    assert row["status"] == "ACCEPTED"
    assert row["metrics"]["nonfinite"] is None


async def test_dashboard_excludes_invalid_nautilus_projection_rows() -> None:
    store = SQLiteStore(":memory:")
    event_time = "2026-06-26T00:00:00+00:00"
    store.insert_system_event(
        {
            "event_id": "evt-order-invalid",
            "event_type": "nautilus_order",
            "severity": "info",
            "created_at": event_time,
            "report_order_id": "C-invalid",
            "status": "UNRECOGNIZED",
            "ts": event_time,
        }
    )
    store.insert_system_event(
        {
            "event_id": "evt-position-invalid",
            "event_type": "nautilus_position",
            "severity": "info",
            "created_at": event_time,
            "report_position_id": "pos-invalid",
            "market_id": "market-invalid",
            "token_id": "token-invalid",
            "status": "BROKEN",
            "is_closed": False,
            "shares": "NaN",
            "entry_price": 0.5,
            "stake_usdc": 5.0,
            "ts": event_time,
        }
    )

    orders = await _dashboard_get(store, "/api/report-orders")
    positions = await _dashboard_get(store, "/api/positions")

    assert orders.status_code == 200
    assert positions.status_code == 200
    assert orders.json()["items"] == []
    assert orders.json()["total"] == 0
    assert positions.json()["items"] == []
    assert positions.json()["total"] == 0


async def test_dashboard_excludes_incomplete_open_position_rows() -> None:
    store = SQLiteStore(":memory:")
    event_time = "2026-06-26T00:00:00+00:00"
    store.insert_system_event(
        {
            "event_id": "evt-position-incomplete",
            "event_type": "nautilus_position",
            "severity": "info",
            "created_at": event_time,
            "report_position_id": "pos-incomplete-dashboard",
            "market_id": "market-incomplete",
            "token_id": "token-incomplete",
            "status": PositionStatus.OPEN.value,
            "is_closed": False,
            "ts": event_time,
        }
    )

    positions = await _dashboard_get(store, "/api/positions")

    assert store.query_report_open_positions() == []
    assert positions.status_code == 200
    assert positions.json()["items"] == []


async def test_dashboard_excludes_open_position_with_invalid_opened_at() -> None:
    # Given: an OPEN position whose primary opened_at is malformed but fallbacks are valid.
    store = SQLiteStore(":memory:")
    event_time = "2026-06-26T00:00:00+00:00"
    store.insert_system_event(
        {
            "event_id": "evt-position-invalid-opened-at",
            "event_type": "nautilus_position",
            "severity": "info",
            "created_at": event_time,
            "report_position_id": "pos-invalid-opened-at-dashboard",
            "market_id": "market-invalid-opened-at",
            "token_id": "token-invalid-opened-at",
            "side": Side.UP.value,
            "status": PositionStatus.OPEN.value,
            "is_closed": False,
            "entry_price": 0.5,
            "shares": 10.0,
            "stake_usdc": 5.0,
            "opened_at": "not-a-date",
            "ts": event_time,
        }
    )

    # When: the dashboard API projects positions from persisted rows.
    positions = await _dashboard_get(store, "/api/positions")

    # Then: the malformed primary timestamp blocks display.
    assert positions.status_code == 200
    assert positions.json()["items"] == []


async def test_dashboard_excludes_open_position_without_resolvable_side() -> None:
    store = SQLiteStore(":memory:")
    event_time = "2026-06-26T00:00:00+00:00"
    store.insert_system_event(
        {
            "event_id": "evt-position-no-side",
            "event_type": "nautilus_position",
            "severity": "info",
            "created_at": event_time,
            "report_position_id": "pos-no-side-dashboard",
            "market_id": "market-missing",
            "token_id": "token-missing",
            "status": PositionStatus.OPEN.value,
            "is_closed": False,
            "entry_price": 0.5,
            "shares": 10.0,
            "stake_usdc": 5.0,
            "opened_at": event_time,
            "ts": event_time,
        }
    )

    positions = await _dashboard_get(store, "/api/positions")

    assert positions.status_code == 200
    assert positions.json()["items"] == []


async def test_leaderboard_uses_closed_trade_results_not_report_snapshots(
    tmp_path,
) -> None:
    store = SQLiteStore(tmp_path / "dashboard-leaderboard.sqlite3")
    store.insert_report_result(
        sample_report_result(
            report_result_id="pt-leaderboard-win",
            report_position_id="pos-leaderboard-win",
            strategy="late_consensus",
            pnl_usdc=6.0,
            roi=0.6,
            result="WIN",
        )
    )
    store.insert_report_result(
        sample_report_result(
            report_result_id="pt-leaderboard-void",
            report_position_id="pos-leaderboard-void",
            strategy="late_consensus",
            pnl_usdc=-1.0,
            roi=-0.1,
            result="VOID",
        )
    )
    report = DailyReport(
        report_id="dr-stale-leaderboard",
        report_date=date(2026, 6, 22),
        starting_equity=1000.0,
        ending_equity=1099.0,
        net_pnl=99.0,
        return_rate=0.099,
        total_signals=99,
        order_count=99,
        fill_count=99,
        rejected_order_count=0,
        open_positions=0,
        closed_positions=99,
        win_count=99,
        loss_count=0,
        void_count=0,
        win_rate=1.0,
        total_pnl_usdc=99.0,
        average_roi=1.0,
        max_drawdown=0.0,
        profit_factor=None,
        strategy_breakdown={
            "late_consensus": {
                "closed_positions": 99,
                "win_count": 99,
                "loss_count": 0,
                "void_count": 0,
                "total_pnl_usdc": 99.0,
                "average_roi": 1.0,
            }
        },
        calibration_breakdown={
            "late_consensus|BTC|5m|high": {
                "strategy": "late_consensus",
                "asset": "BTC",
                "timeframe": "5m",
                "confidence_bucket": "high",
                "sample_size": 2,
                "wins": 1,
                "losses": 0,
                "average_return": 0.25,
                "calibration_status": "insufficient_data",
            }
        },
    )
    store.insert_daily_report(report)

    response = await _dashboard_get(store, "/api/leaderboard")

    assert response.status_code == 200
    assert response.json()["leaderboard"] == [
        {
            "strategy": "late_consensus",
            "closed_positions": 2,
            "win_count": 1,
            "loss_count": 0,
            "void_count": 1,
            "total_pnl_usdc": 5.0,
            "average_roi": 0.25,
            "win_rate": 0.5,
        }
    ]
    assert (
        response.json()["calibration_breakdown"]["late_consensus|BTC|5m|high"][
            "sample_size"
        ]
        == 2
    )


async def test_leaderboard_recomputes_calibration_status_after_aggregation(
    tmp_path,
) -> None:
    # Given: two insufficient daily rows for one bucket that cross calibration threshold when merged.
    store = SQLiteStore(tmp_path / "db.sqlite3")
    first_report = DailyReport(
        report_id="dr-calibration-1",
        report_date=date(2026, 6, 22),
        starting_equity=1000.0,
        ending_equity=1002.0,
        net_pnl=2.0,
        return_rate=0.002,
        total_signals=15,
        order_count=15,
        fill_count=15,
        rejected_order_count=0,
        open_positions=0,
        closed_positions=15,
        win_count=8,
        loss_count=7,
        void_count=0,
        win_rate=8 / 15,
        total_pnl_usdc=2.0,
        average_roi=0.02,
        max_drawdown=0.0,
        profit_factor=2.0,
        calibration_breakdown={
            "ptb_diff|BTC|5m|high": {
                "strategy": "ptb_diff",
                "asset": "BTC",
                "timeframe": "5m",
                "confidence_bucket": "high",
                "sample_size": 15,
                "wins": 8,
                "losses": 7,
                "average_entry_price": 0.50,
                "average_return": 0.02,
                "calibration_status": "insufficient_data",
            }
        },
    )
    second_report = DailyReport(
        report_id="dr-calibration-2",
        report_date=date(2026, 6, 23),
        starting_equity=1002.0,
        ending_equity=1006.0,
        net_pnl=4.0,
        return_rate=0.004,
        total_signals=15,
        order_count=15,
        fill_count=15,
        rejected_order_count=0,
        open_positions=0,
        closed_positions=15,
        win_count=7,
        loss_count=8,
        void_count=0,
        win_rate=7 / 15,
        total_pnl_usdc=4.0,
        average_roi=0.04,
        max_drawdown=0.0,
        profit_factor=1.0,
        calibration_breakdown={
            "ptb_diff|BTC|5m|high": {
                "strategy": "ptb_diff",
                "asset": "BTC",
                "timeframe": "5m",
                "confidence_bucket": "high",
                "sample_size": 15,
                "wins": 7,
                "losses": 8,
                "average_entry_price": 0.70,
                "average_return": 0.04,
                "calibration_status": "insufficient_data",
            }
        },
    )
    store.insert_daily_report(first_report)
    store.insert_daily_report(second_report)
    client = TestClient(create_dashboard_app(store))

    # When: calibration rows are read through the leaderboard API.
    response = client.get("/api/leaderboard")

    # Then: merged sample size, weighted averages, and status are recomputed from merged data.
    assert response.status_code == 200
    row = response.json()["calibration_breakdown"]["ptb_diff|BTC|5m|high"]
    assert row["sample_size"] == 30
    assert row["wins"] == 15
    assert row["losses"] == 15
    assert row["average_entry_price"] == pytest.approx(0.60)
    assert row["average_return"] == pytest.approx(0.03)
    assert row["calibration_status"] == "calibrated"


def test_dashboard_exposes_bounded_strategy_status_rows(tmp_path) -> None:
    # Given: persisted readiness rows for strategies that cannot produce signals.
    store = SQLiteStore(tmp_path / "db.sqlite3")
    statuses = (
        StrategyMarketStatus(
            strategy="ptb_diff",
            asset="ETH",
            timeframe="5m",
            status="unsupported_market",
            reason="UNSUPPORTED_ASSET",
        ),
        StrategyMarketStatus(
            strategy="late_consensus",
            asset="BTC",
            timeframe="15m",
            status="uncalibrated",
            reason="CALIBRATION_REQUIRED",
        ),
    )
    for status in statuses:
        store.insert_strategy_status(status)
    client = TestClient(create_dashboard_app(store))

    # When: clients request the bounded dashboard API surfaces.
    response = client.get("/api/strategy-status", params={"limit": 1})
    overview = client.get("/api/overview")

    # Then: the API exposes status rows by strategy/asset/timeframe/reason.
    assert response.status_code == 200
    assert response.json() == [
        {
            "strategy": "ptb_diff",
            "asset": "ETH",
            "timeframe": "5m",
            "status": "unsupported_market",
            "reason": "UNSUPPORTED_ASSET",
        }
    ]
    assert overview.status_code == 200
    assert overview.json()["strategy_status"] == [
        {
            "strategy": "ptb_diff",
            "asset": "ETH",
            "timeframe": "5m",
            "status": "unsupported_market",
            "reason": "UNSUPPORTED_ASSET",
        },
        {
            "strategy": "late_consensus",
            "asset": "BTC",
            "timeframe": "15m",
            "status": "uncalibrated",
            "reason": "CALIBRATION_REQUIRED",
        },
    ]


def test_dashboard_marks_unrefreshed_runtime_strategy_status_inactive(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "db.sqlite3")
    store.insert_strategy_status(
        StrategyMarketStatus(
            strategy="ptb_diff",
            asset="BTC",
            timeframe="5m",
            status="active",
            reason=None,
        )
    )
    with store._lock, store._conn:
        store._conn.execute(
            "UPDATE strategy_status SET created_at='2020-01-01T00:00:00Z'"
        )

    rows = store.strategy_status_rows(limit=100)

    assert rows[0]["status"] == "inactive"
    assert rows[0]["reason"] == "status_not_refreshed"


def test_dashboard_ages_unrefreshed_untradable_status(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "db.sqlite3")
    store.insert_strategy_status(
        StrategyMarketStatus(
            strategy="ptb_diff",
            asset="BTC",
            timeframe="5m",
            status="untradable",
            reason="missing_quote_depth:DOWN",
        )
    )
    client = TestClient(create_dashboard_app(store))

    assert client.get("/api/strategy-status").json()[0]["status"] == "untradable"
    assert client.get("/api/overview").json()["strategy_status"][0]["status"] == (
        "untradable"
    )

    with store._lock, store._conn:
        store._conn.execute(
            "UPDATE strategy_status SET created_at='2020-01-01T00:00:00Z'"
        )

    rows = store.strategy_status_rows(limit=100)

    assert rows[0]["status"] == "inactive"
    assert rows[0]["reason"] == "status_not_refreshed"


def test_dashboard_exposes_only_latest_status_per_strategy_market(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "strategy-status-current.sqlite3")
    store.insert_strategy_status(
        StrategyMarketStatus(
            strategy="late_consensus",
            asset="BTC",
            timeframe="5m",
            status="missing_data",
            reason="awaiting_first_book",
        )
    )
    store.insert_strategy_status(
        StrategyMarketStatus(
            strategy="late_consensus",
            asset="BTC",
            timeframe="5m",
            status="active",
            reason=None,
        )
    )
    client = TestClient(create_dashboard_app(store))

    response = client.get("/api/strategy-status")

    assert response.status_code == 200
    assert response.json() == [
        {
            "strategy": "late_consensus",
            "asset": "BTC",
            "timeframe": "5m",
            "status": "active",
            "reason": None,
        }
    ]


async def test_dashboard_rejects_write_methods(tmp_path, market_view, settings) -> None:
    # Given: the dashboard app exposes only read routes.
    client, _store = _client_with_store(tmp_path, market_view, settings)
    read_paths = (
        "/health",
        "/api/overview",
        "/api/signals",
        "/api/rejected-signals",
        "/api/report-orders",
        "/api/positions",
        "/api/trades",
        "/api/leaderboard",
        "/api/strategy-status",
    )

    # When / Then: write methods are not supported on the dashboard surface.
    for path in read_paths:
        assert client.post(path).status_code == 405
        assert client.put(path).status_code == 405
        assert client.patch(path).status_code == 405
        assert client.delete(path).status_code == 405
