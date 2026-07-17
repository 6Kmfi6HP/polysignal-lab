"""
Input: __future__, pathlib, pathlib.Path, polysignal_lab.storage.projection_migration, polysignal_lab.storage.sqlite_schema, polysignal_lab.storage.sqlite_store
Output: test_migrate_paper_tables_to_projections_is_idempotent, test_insert_report_result_does_not_write_legacy_paper_table, test_settlement_forbids_open_cache_closed_sqlite_fork
Pos: Focused migration / projection / settlement tests for Nautilus v2 projection seam

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
from polysignal_lab.storage.event_projection import normalize_report_order
from polysignal_lab.storage.sqlite_schema import PROJECTION_SCHEMA_VERSION
from polysignal_lab.storage.sqlite_store import SQLiteStore


def test_normalize_report_order_emits_only_report_identity() -> None:
    payload = normalize_report_order(
        {
            "client_order_id": "C-1",
            "status": "ACCEPTED",
            "quantity": 10,
            "price": 0.4,
            "instrument_id": "token-up.POLYMARKET",
            "metrics": {"side": "UP", "strategy": "ptb_diff"},
        }
    )
    assert payload["report_order_id"] == "C-1"
    assert "paper_order_id" not in payload
    assert "projected_order_id" not in payload
    assert payload["status"] == "RESTING"
    assert payload["side"] == "UP"


def test_migrate_legacy_tables_to_reporting_backs_up_and_drops_legacy(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "proj.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE paper_order_states(paper_order_id TEXT PRIMARY KEY,status TEXT NOT NULL,created_event_at TEXT NOT NULL,source_event_at TEXT NOT NULL,source_event_id TEXT NOT NULL,payload_json TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE paper_position_states(paper_position_id TEXT PRIMARY KEY,status TEXT NOT NULL,source_event_at TEXT NOT NULL,source_event_id TEXT NOT NULL,payload_json TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE paper_trade_results(paper_trade_id TEXT PRIMARY KEY,signal_id TEXT NOT NULL,strategy TEXT NOT NULL,asset TEXT NOT NULL,timeframe TEXT NOT NULL,market_id TEXT NOT NULL,result TEXT NOT NULL,pnl_usdc REAL NOT NULL,roi REAL NOT NULL,closed_at TEXT NOT NULL,payload_json TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO paper_order_states VALUES(?,?,?,?,?,?)",
        (
            "ord-1",
            "FILLED",
            "2026-07-01T00:00:00Z",
            "2026-07-01T00:00:01Z",
            "evt-1",
            '{"paper_order_id":"ord-1","status":"FILLED","side":"UP"}',
        ),
    )
    conn.execute(
        "INSERT INTO paper_position_states VALUES(?,?,?,?,?)",
        (
            "pos-1",
            "OPEN",
            "2026-07-01T00:00:02Z",
            "evt-2",
            '{"paper_position_id":"pos-1","status":"OPEN","side":"UP","is_closed":false}',
        ),
    )
    conn.execute(
        "INSERT INTO paper_trade_results VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            "ptr-1",
            "sig-1",
            "ptb_diff",
            "BTC",
            "5m",
            "m-1",
            "WIN",
            1.5,
            0.15,
            "2026-07-01T01:00:00Z",
            (
                '{"schema_version":1,"paper_trade_id":"ptr-1","signal_id":"sig-1",'
                '"paper_position_id":"pos-1","strategy":"ptb_diff","asset":"BTC",'
                '"timeframe":"5m","market_id":"m-1","market_slug":"slug","side":"UP",'
                '"entry_price":0.4,"shares":10,"stake_usdc":4,"exit_mode":"RESOLUTION",'
                '"outcome_value":1,"settlement_value":10,"pnl_usdc":1.5,"roi":0.15,'
                '"result":"WIN","opened_at":"2026-07-01T00:00:00Z",'
                '"closed_at":"2026-07-01T01:00:00Z","fee_model":"ignored_v1",'
                '"entry_fee":0,"details":{}}'
            ),
        ),
    )
    conn.commit()
    conn.close()

    store = SQLiteStore(db_path)
    version = int(store._conn.execute("PRAGMA user_version").fetchone()[0])
    assert version >= PROJECTION_SCHEMA_VERSION
    assert (tmp_path / f"proj.db.pre-report-v{PROJECTION_SCHEMA_VERSION}.bak").exists()

    orders = store.query_json("report_orders", limit=10)
    positions = store.query_json("report_positions", limit=10)
    results = store.query_json("report_results", limit=10)
    assert [row["report_order_id"] for row in orders] == ["ord-1"]
    assert [row["report_position_id"] for row in positions] == ["pos-1"]
    assert results[0]["report_result_id"] == "ptr-1"
    assert not any(
        key.startswith(("paper_", "projected_"))
        for row in (*orders, *positions, *results)
        for key in row
    )

    store.migrate()
    assert store.counts()["report_results"] == 1
    assert store.counts()["report_orders"] == 1
    assert store.counts()["report_positions"] == 1

    legacy = {
        str(row[0])
        for row in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        if str(row[0]).startswith(("paper_", "projected_"))
    }
    assert legacy == set()
    store.close()


def test_insert_report_result_does_not_write_legacy_paper_table(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "write.db")
    payload = {
        "schema_version": 1,
        "report_result_id": "ptr-new",
        "signal_id": "sig-new",
        "report_position_id": "pos-new",
        "strategy": "ptb_diff",
        "asset": "BTC",
        "timeframe": "5m",
        "market_id": "m-new",
        "market_slug": "slug",
        "side": "UP",
        "entry_price": 0.4,
        "shares": 10.0,
        "stake_usdc": 4.0,
        "exit_mode": "RESOLUTION",
        "outcome_value": 1.0,
        "settlement_value": 10.0,
        "pnl_usdc": 6.0,
        "roi": 1.5,
        "result": "WIN",
        "opened_at": "2026-07-01T00:00:00+00:00",
        "closed_at": "2026-07-01T01:00:00+00:00",
        "fee_model": "ignored_v1",
        "entry_fee": 0.0,
        "details": {},
    }
    store.insert_report_result(payload)
    assert store.counts()["report_results"] == 1
    tables = {
        str(row[0])
        for row in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "paper_trade_results" not in tables
    assert store.query_json("report_results", limit=10)[0]["report_result_id"] == "ptr-new"
    store.close()


def test_migrate_v4_reporting_columns_renames_and_canonicalizes_payload(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "v4.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE report_orders(projected_order_id TEXT PRIMARY KEY,status TEXT NOT NULL,created_event_at TEXT NOT NULL,source_event_at TEXT NOT NULL,source_event_id TEXT NOT NULL,payload_json TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO report_orders VALUES(?,?,?,?,?,?)",
            (
                "ord-v4",
                "RESTING",
                "2026-07-01T00:00:00Z",
                "2026-07-01T00:00:00Z",
                "evt-v4",
                '{"projected_order_id":"ord-v4","paper_order_id":"ord-v4","status":"RESTING"}',
            ),
        )
        conn.execute("PRAGMA user_version=4")

    store = SQLiteStore(db_path)

    columns = {
        str(row["name"])
        for row in store._conn.execute("PRAGMA table_info(report_orders)").fetchall()
    }
    assert "report_order_id" in columns
    assert "projected_order_id" not in columns
    assert store.query_json("report_orders") == [
        {"report_order_id": "ord-v4", "status": "RESTING"}
    ]
    assert (tmp_path / f"v4.db.pre-report-v{PROJECTION_SCHEMA_VERSION}.bak").exists()
    store.close()


def test_migrate_v5_account_and_daily_report_payload_to_runtime_neutral_names(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "v5.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE report_account_snapshots(id INTEGER PRIMARY KEY AUTOINCREMENT,wallet_id TEXT NOT NULL,equity REAL NOT NULL,cash_balance REAL NOT NULL,realized_pnl REAL NOT NULL,open_position_count INTEGER NOT NULL,created_at TEXT NOT NULL,payload_json TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO report_account_snapshots(wallet_id,equity,cash_balance,realized_pnl,open_position_count,created_at,payload_json) VALUES(?,?,?,?,?,?,?)",
            (
                "POLYMARKET-001",
                1005.0,
                1000.0,
                5.0,
                1,
                "2026-07-01T00:00:00Z",
                '{"wallet_id":"POLYMARKET-001","equity":1005.0,"cash_balance":1000.0,"realized_pnl":5.0,"open_position_count":1,"created_at":"2026-07-01T00:00:00Z"}',
            ),
        )
        conn.execute(
            "CREATE TABLE daily_reports(report_id TEXT PRIMARY KEY,report_date TEXT NOT NULL,revision INTEGER NOT NULL,total_signals INTEGER NOT NULL,total_pnl_usdc REAL NOT NULL,win_rate REAL NOT NULL,created_at TEXT NOT NULL,payload_json TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO daily_reports VALUES(?,?,?,?,?,?,?,?)",
            (
                "dr-v5",
                "2026-07-01",
                1,
                2,
                5.0,
                1.0,
                "2026-07-01T23:59:00Z",
                '{"report_id":"dr-v5","paper_pnl":5.0,"paper_orders":2,"paper_fills":1}',
            ),
        )
        conn.execute("PRAGMA user_version=5")

    store = SQLiteStore(db_path)

    columns = {
        str(row["name"])
        for row in store._conn.execute(
            "PRAGMA table_info(report_account_snapshots)"
        ).fetchall()
    }
    assert "account_id" in columns
    assert "wallet_id" not in columns
    account = store.query_latest_report_account_snapshot()
    assert account is not None
    assert account["account_id"] == "POLYMARKET-001"
    report = store.query_json("daily_reports")[0]
    assert report["net_pnl"] == 5.0
    assert report["order_count"] == 2
    assert report["fill_count"] == 1
    assert not any(key.startswith("paper_") for key in report)
    assert (tmp_path / f"v5.db.pre-report-v{PROJECTION_SCHEMA_VERSION}.bak").exists()
    store.close()
