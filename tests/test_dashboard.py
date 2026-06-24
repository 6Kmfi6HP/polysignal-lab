from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from polysignal_lab.dashboard.app import create_dashboard_app
from polysignal_lab.domain.enums import OrderStatus, Side
from polysignal_lab.domain.paper_order import PaperOrder
from polysignal_lab.domain.paper_result import DailyReport
from polysignal_lab.storage.sqlite_store import SQLiteStore
from polysignal_lab.strategies.ptb_diff import PTBDiffStrategy
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
    )

    # When / Then: write methods are not supported on the dashboard surface.
    for path in read_paths:
        assert client.post(path).status_code == 405
        assert client.put(path).status_code == 405
        assert client.patch(path).status_code == 405
        assert client.delete(path).status_code == 405
