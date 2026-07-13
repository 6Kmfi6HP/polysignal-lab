# noqa: SIZE_OK  — dashboard integration coverage file
"""
Input: __future__, __future__.annotations, datetime, datetime.date, datetime.datetime, datetime.timezone, pytest, fastapi.testclient, fastapi.testclient.TestClient, polysignal_lab.dashboard.app
Output: test_dashboard_uses_injected_reporting_read_port, test_dashboard_readonly_endpoints_return_stored_data, test_dashboard_positions_returns_latest_metadata_first, test_dashboard_health_reports_missing_runtime_as_unknown, test_dashboard_health_reports_stale_runtime_as_degraded, test_dashboard_health_keeps_fresh_runtime_ok_when_storage_fails, test_dashboard_health_ignores_superseded_runtime_snapshot_status, test_dashboard_health_returns_component_snapshot_from_system_events, test_dashboard_exposes_paper_execution_quality, test_leaderboard_uses_sqlite_report_data, test_leaderboard_recomputes_calibration_status_after_aggregation, test_dashboard_exposes_bounded_strategy_status_rows, test_dashboard_rejects_write_methods
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock

import httpx
import pytest

from fastapi.testclient import TestClient

from polysignal_lab.dashboard.app import create_dashboard_app
from polysignal_lab.dashboard.reporting_read import (
    FileRuntimeHealthReader,
    ReportingReadPort,
)
from polysignal_lab.domain.enums import PositionStatus, Side
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.domain.paper_result import DailyReport
from polysignal_lab.observability.runtime_health import write_runtime_heartbeat
from polysignal_lab.storage.sqlite_store import SQLiteStore
from polysignal_lab.domain.strategy_readiness import StrategyMarketStatus
from signal_helpers import ptb_signal_from_snapshot
from factories import sample_storage_lifecycle


def _client_with_store(tmp_path, snapshot, settings) -> tuple[TestClient, SQLiteStore]:
    store = SQLiteStore(tmp_path / "dashboard.sqlite3")
    signal = ptb_signal_from_snapshot(snapshot, settings)
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
    store.insert_system_event({
        "event_id": "evt-order-1",
        "event_type": "nautilus_order",
        "severity": "info",
        "created_at": str(lifecycle.order["created_at"]),
        **lifecycle.order,
    })
    store.insert_system_event({
        "event_id": "evt-fill-1",
        "event_type": "nautilus_fill",
        "severity": "info",
        "created_at": str(lifecycle.fill["created_at"]),
        **lifecycle.fill,
    })
    store.insert_paper_trade_result(lifecycle.result)
    store.insert_wallet_snapshot(lifecycle.wallet)
    store.insert_daily_report(lifecycle.report)
    store.insert_telegram_publish(lifecycle.publish)
    store.insert_system_event(lifecycle.event)
    store.insert_system_event({
        "event_id": "evt-nautilus-pos-1",
        "event_type": "nautilus_position",
        "severity": "info",
        "created_at": lifecycle.position["opened_at"],
        **lifecycle.position,
        "ts": lifecycle.position["opened_at"],
    })
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


async def test_dashboard_readonly_endpoints_return_stored_data(tmp_path, snapshot, settings) -> None:
    # Given: a temp SQLite dashboard store populated through the public storage API.
    client, store = _client_with_store(tmp_path, snapshot, settings)
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
    assert overview.json()["counts"]["paper_trade_results"] == 1
    assert signals.json()[0]["signal_id"] == signal["signal_id"]
    assert rejected.json()[0]["candidate"]["signal_id"] == signal["signal_id"]
    assert rejected.json()[0]["reason_code"] == "STALE_SPOT_PRICE"
    assert rejected.json()[0]["details"]["lag_ms"] == 3_000
    assert rejected.json()[0]["details"]["threshold_ms"] == 2_000
    assert rejected.json()[0]["details"]["policy_source"] == "strategy_and_global"
    assert positions.json()[0]["paper_position_id"] == "pp-1"
    assert trades.json()[0]["paper_trade_id"] == "pt-1"
    assert root.status_code == 404



async def test_dashboard_positions_returns_latest_metadata_first(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "dashboard-positions.sqlite3")
    old = {
        "paper_position_id": "old-pos",
        "position_id": "old-pos",
        "signal_id": "",
        "paper_order_id": "old-order",
        "paper_fill_id": "old-fill",
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
        "paper_position_id": "latest-pos",
        "position_id": "latest-pos",
        "signal_id": "sig-latest",
        "paper_order_id": "latest-order",
        "paper_fill_id": "latest-fill",
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
        store.insert_system_event({
            "event_id": f"evt-{pos['paper_position_id']}",
            "event_type": "nautilus_position",
            "severity": "info",
            "created_at": pos["opened_at"],
            **pos,
            "ts": pos["opened_at"],
        })
    response = await _dashboard_get(store, "/api/positions")

    assert response.status_code == 200
    rows = response.json()
    assert rows[0]["paper_position_id"] == "latest-pos"
    assert rows[0]["status"] == "OPEN"
    assert rows[0]["is_closed"] is False
    assert rows[0]["position_id"] == "latest-pos"


async def test_dashboard_positions_normalize_nautilus_rows_with_market_lookup(tmp_path) -> None:
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
    row = response.json()[0]
    assert row["paper_position_id"] == "P-001"
    assert row["paper_order_id"] == "C-001"
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


def test_dashboard_health_ignores_superseded_runtime_snapshot_status(tmp_path) -> None:
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
    assert components["runtime"]["status"] == "ok"
    assert components["sqlite_storage"]["status"] == "ok"


def test_dashboard_health_returns_component_snapshot_from_system_events(tmp_path) -> None:
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
        "paper_order_id": "po-rejected-dashboard",
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
        "reject_reason": "PAPER_ENTRY_PRICE_MOVED",
        "metrics": {
            "paper_normalized_reason": "PAPER_ENTRY_PRICE_MOVED",
            "paper_original_reason": "ASK_ABOVE_MAX_ENTRY",
        },
    }
    report = DailyReport(
        report_date=date(2026, 6, 22),
        starting_equity=1000.0,
        ending_equity=1000.0,
        paper_pnl=0.0,
        paper_roi=0.0,
        total_signals=1,
        paper_orders=1,
        paper_fills=0,
        rejected_paper_orders=1,
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
        paper_rejects_by_reason={"PAPER_ENTRY_PRICE_MOVED": 1},
        average_execution_staleness_ms=25.0,
    )
    store.insert_system_event({
        "event_id": "evt-po-rejected",
        "event_type": "nautilus_order",
        "severity": "info",
        "created_at": order["created_at"],
        "paper_order_id": order["paper_order_id"],
        "client_order_id": order["paper_order_id"],
        "status": order["status"],
        "reject_reason": order["reject_reason"],
        "strategy": order["strategy"],
        "market_id": order["market_id"],
        "signal_id": order["signal_id"],
        "ts": order["created_at"],
    })
    store.insert_daily_report(report)
    # When: paper execution quality surfaces are read from the dashboard API.
    orders = await _dashboard_get(store, "/api/paper-orders", params={"status": "rejected"})
    overview = await _dashboard_get(store, "/api/overview")

    # Then: paper order rows and latest report aggregates expose them.
    assert orders.status_code == 200
    assert overview.status_code == 200
    assert orders.json()[0]["reject_reason"] == "PAPER_ENTRY_PRICE_MOVED"
    assert overview.json()["latest_report"]["paper_rejects_by_reason"] == {
        "PAPER_ENTRY_PRICE_MOVED": 1
    }


async def test_dashboard_paper_orders_normalize_nautilus_rows() -> None:
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
            },
            "ts": "2026-06-26T00:00:00+00:00",
        }
    )
    response = await _dashboard_get(store, "/api/paper-orders")

    assert response.status_code == 200
    row = response.json()[0]
    assert row["paper_order_id"] == "C-001"
    assert row["asset"] == "BTC"
    assert row["timeframe"] == "15m"
    assert row["token_id"] == "down-token"
    assert row["side"] == "DOWN"
    assert row["limit_price"] == 0.64
    assert row["reference_price"] == 0.63
    assert row["stake_usdc"] == 32.0
    assert row["shares"] == 40.0
    assert row["status"] == "RESTING"


async def test_dashboard_excludes_invalid_nautilus_projection_rows() -> None:
    store = SQLiteStore(":memory:")
    event_time = "2026-06-26T00:00:00+00:00"
    store.insert_system_event(
        {
            "event_id": "evt-order-invalid",
            "event_type": "nautilus_order",
            "severity": "info",
            "created_at": event_time,
            "paper_order_id": "C-invalid",
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
            "paper_position_id": "pos-invalid",
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

    orders = await _dashboard_get(store, "/api/paper-orders")
    positions = await _dashboard_get(store, "/api/positions")

    assert orders.status_code == 200
    assert positions.status_code == 200
    assert orders.json() == []
    assert positions.json() == []


async def test_dashboard_excludes_incomplete_open_position_rows() -> None:
    store = SQLiteStore(":memory:")
    event_time = "2026-06-26T00:00:00+00:00"
    store.insert_system_event(
        {
            "event_id": "evt-position-incomplete",
            "event_type": "nautilus_position",
            "severity": "info",
            "created_at": event_time,
            "paper_position_id": "pos-incomplete-dashboard",
            "market_id": "market-incomplete",
            "token_id": "token-incomplete",
            "status": PositionStatus.OPEN.value,
            "is_closed": False,
            "ts": event_time,
        }
    )

    positions = await _dashboard_get(store, "/api/positions")

    assert store.restore_open_positions() == []
    assert positions.status_code == 200
    assert positions.json() == []


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
            "paper_position_id": "pos-invalid-opened-at-dashboard",
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
    assert positions.json() == []


async def test_dashboard_excludes_open_position_without_resolvable_side() -> None:
    store = SQLiteStore(":memory:")
    event_time = "2026-06-26T00:00:00+00:00"
    store.insert_system_event(
        {
            "event_id": "evt-position-no-side",
            "event_type": "nautilus_position",
            "severity": "info",
            "created_at": event_time,
            "paper_position_id": "pos-no-side-dashboard",
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
    assert positions.json() == []


async def test_leaderboard_uses_sqlite_report_data(tmp_path, snapshot, settings) -> None:
    # Given: stored report rows where voids must remain in the closed-position denominator.
    client, store = _client_with_store(tmp_path, snapshot, settings)
    report = DailyReport(
        report_id="dr-win-void",
        report_date=date(2026, 6, 22),
        starting_equity=1000.0,
        ending_equity=1004.0,
        paper_pnl=4.0,
        paper_roi=0.004,
        total_signals=2,
        paper_orders=2,
        paper_fills=2,
        rejected_paper_orders=0,
        open_positions=0,
        closed_positions=2,
        win_count=1,
        loss_count=0,
        void_count=1,
        win_rate=0.5,
        total_pnl_usdc=4.0,
        average_roi=0.12,
        max_drawdown=0.0,
        profit_factor=None,
        strategy_breakdown={
            "late_consensus": {
                "closed_positions": 2,
                "win_count": 1,
                "loss_count": 0,
                "void_count": 1,
                "total_pnl_usdc": 4.0,
                "average_roi": 0.12,
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
                "average_return": 0.12,
                "calibration_status": "insufficient_data",
            }
        },
    )
    store.insert_daily_report(report)

    # When: the dashboard leaderboard endpoint is read.
    response = client.get("/api/leaderboard")

    # Then: it is restored from SQLite report payloads using wins / closed positions.
    assert response.status_code == 200
    rows = {row["strategy"]: row for row in response.json()["leaderboard"]}
    assert rows["late_consensus"]["closed_positions"] == 2
    assert rows["late_consensus"]["win_count"] == 1
    assert rows["late_consensus"]["void_count"] == 1
    assert rows["late_consensus"]["win_rate"] == 0.5
    assert response.json()["calibration_breakdown"]["late_consensus|BTC|5m|high"][
        "sample_size"
    ] == 2


async def test_leaderboard_recomputes_calibration_status_after_aggregation(tmp_path) -> None:
    # Given: two insufficient daily rows for one bucket that cross calibration threshold when merged.
    store = SQLiteStore(tmp_path / "db.sqlite3")
    first_report = DailyReport(
        report_id="dr-calibration-1",
        report_date=date(2026, 6, 22),
        starting_equity=1000.0,
        ending_equity=1002.0,
        paper_pnl=2.0,
        paper_roi=0.002,
        total_signals=15,
        paper_orders=15,
        paper_fills=15,
        rejected_paper_orders=0,
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
        paper_pnl=4.0,
        paper_roi=0.004,
        total_signals=15,
        paper_orders=15,
        paper_fills=15,
        rejected_paper_orders=0,
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


async def test_dashboard_rejects_write_methods(tmp_path, snapshot, settings) -> None:
    # Given: the dashboard app exposes only read routes.
    client, _store = _client_with_store(tmp_path, snapshot, settings)
    read_paths = (
        "/health",
        "/api/overview",
        "/api/signals",
        "/api/rejected-signals",
        "/api/paper-orders",
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
