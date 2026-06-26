from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from fastapi.testclient import TestClient

from polysignal_lab.dashboard.app import create_dashboard_app
from polysignal_lab.domain.enums import OrderStatus, Side
from polysignal_lab.domain.paper_order import PaperOrder
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.paper_result import DailyReport
from polysignal_lab.storage.sqlite_store import SQLiteStore
from polysignal_lab.strategies.ptb_diff import PTBDiffStrategy
from polysignal_lab.strategies.readiness import StrategyMarketStatus
from factories import sample_storage_lifecycle


def _client_with_store(tmp_path, snapshot, settings) -> tuple[TestClient, SQLiteStore]:
    store = SQLiteStore(tmp_path / "dashboard.sqlite3")
    signal = PTBDiffStrategy(settings.strategies.ptb_diff).evaluate(snapshot)[0]
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
    store.insert_paper_order(lifecycle.order)
    store.insert_paper_fill(lifecycle.fill)
    store.upsert_paper_position(lifecycle.position)
    store.insert_paper_trade_result(lifecycle.result)
    store.insert_wallet_snapshot(lifecycle.wallet)
    store.insert_daily_report(lifecycle.report)
    store.insert_telegram_publish(lifecycle.publish)
    store.insert_system_event(lifecycle.event)
    return TestClient(create_dashboard_app(store)), store


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
    html = client.get("/")

    # Then: payloads contain the persisted rows and the HTML has no write controls.
    assert health.status_code == 200
    assert health.json()["counts"]["signals"] == 1
    assert health.json()["status"] in {"ok", "degraded", "down"}
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
    assert html.status_code == 200
    assert "<header" in html.text
    assert "<nav" in html.text
    assert "<main" in html.text
    assert "ptb_diff" in html.text
    assert signal["signal_id"] in html.text
    assert "Paper-only read model" in html.text
    assert "<form" not in html.text
    assert "<button" not in html.text
    assert "lorem" not in html.text.lower()
    assert "place order" not in html.text.lower()
    assert "create_" + "order" not in html.text



def test_dashboard_positions_returns_latest_metadata_first(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "dashboard-positions.sqlite3")
    old = PaperPosition(
        paper_position_id="old-pos",
        signal_id="",
        paper_order_id="old-order",
        paper_fill_id="old-fill",
        strategy="late_consensus",
        asset="",
        timeframe="",
        market_id="2676328",
        market_slug="",
        token_id="old-token",
        side=Side.UP,
        entry_price=0.5,
        shares=10.0,
        stake_usdc=5.0,
        opened_at=datetime(2026, 6, 25, tzinfo=timezone.utc),
    )
    latest = PaperPosition(
        paper_position_id="latest-pos",
        signal_id="sig-latest",
        paper_order_id="latest-order",
        paper_fill_id="latest-fill",
        strategy="late_consensus",
        asset="BTC",
        timeframe="5m",
        market_id="2676527",
        market_slug="btc-updown-5m",
        token_id="latest-token",
        side=Side.UP,
        entry_price=0.6,
        shares=12.0,
        stake_usdc=7.2,
        opened_at=datetime(2026, 6, 26, tzinfo=timezone.utc),
    )
    store.upsert_paper_position(old)
    store.upsert_paper_position(latest)
    client = TestClient(create_dashboard_app(store))

    response = client.get("/api/positions")

    assert response.status_code == 200
    rows = response.json()
    assert rows[0]["paper_position_id"] == "latest-pos"
    assert rows[0]["asset"] == "BTC"
    assert rows[0]["timeframe"] == "5m"

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
    order = PaperOrder(
        paper_order_id="po-rejected-dashboard",
        signal_id="sig-dashboard",
        asset="BTC",
        timeframe="5m",
        strategy="ptb_diff",
        market_id="mkt-1",
        market_slug="btc-updown-5m",
        token_id="token-up",
        side=Side.UP,
        limit_price=0.60,
        reference_price=0.50,
        stake_usdc=10.0,
        status=OrderStatus.REJECTED,
        reject_reason="PAPER_ENTRY_PRICE_MOVED",
        metrics={
            "paper_normalized_reason": "PAPER_ENTRY_PRICE_MOVED",
            "paper_original_reason": "ASK_ABOVE_MAX_ENTRY",
        },
    )
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
    store.insert_paper_order(order)
    store.insert_daily_report(report)
    client = TestClient(create_dashboard_app(store))

    # When: paper execution quality surfaces are read from the dashboard.
    orders = client.get("/api/paper-orders", params={"status": "rejected"})
    overview = client.get("/api/overview")
    html = client.get("/")

    # Then: paper order rows, latest report aggregates, and HTML summary expose them.
    assert orders.status_code == 200
    assert orders.json()[0]["reject_reason"] == "PAPER_ENTRY_PRICE_MOVED"
    assert overview.json()["latest_report"]["paper_rejects_by_reason"] == {
        "PAPER_ENTRY_PRICE_MOVED": 1
    }
    assert "Paper rejects" in html.text
    assert "PAPER_ENTRY_PRICE_MOVED" in html.text

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
        "/",
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
