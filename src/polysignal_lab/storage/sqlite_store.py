from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import Lock
from typing import Any, Iterable

from polysignal_lab.domain.enums import PositionStatus
from polysignal_lab.utils import to_jsonable, utc_iso


class SQLiteStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self.migrate()

    def close(self) -> None:
        self._conn.close()

    def migrate(self) -> None:
        ddl = [
            """
            CREATE TABLE IF NOT EXISTS markets (
                market_id TEXT PRIMARY KEY,
                asset TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                market_slug TEXT NOT NULL,
                status TEXT,
                end_ts TEXT,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_markets_asset_tf_end ON markets(asset,timeframe,end_ts)",
            """
            CREATE TABLE IF NOT EXISTS signals (
                signal_id TEXT PRIMARY KEY,
                strategy TEXT NOT NULL,
                asset TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                market_id TEXT NOT NULL,
                side TEXT NOT NULL,
                confidence REAL NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_signals_strategy_asset ON signals(strategy,asset,timeframe,created_at)",
            """
            CREATE TABLE IF NOT EXISTS rejected_signals (
                rejected_id TEXT PRIMARY KEY,
                signal_id TEXT NOT NULL,
                reason_code TEXT NOT NULL,
                gate_name TEXT NOT NULL,
                rejected_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS paper_orders (
                paper_order_id TEXT PRIMARY KEY,
                signal_id TEXT NOT NULL,
                strategy TEXT NOT NULL,
                asset TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                market_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS paper_fills (
                paper_fill_id TEXT PRIMARY KEY,
                paper_order_id TEXT NOT NULL,
                signal_id TEXT NOT NULL,
                fill_price REAL NOT NULL,
                stake_usdc REAL NOT NULL,
                shares REAL NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS paper_positions (
                paper_position_id TEXT PRIMARY KEY,
                signal_id TEXT NOT NULL,
                strategy TEXT NOT NULL,
                asset TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                market_id TEXT NOT NULL,
                status TEXT NOT NULL,
                opened_at TEXT NOT NULL,
                closed_at TEXT,
                payload_json TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_positions_status ON paper_positions(status,market_id)",
            """
            CREATE TABLE IF NOT EXISTS paper_trade_results (
                paper_trade_id TEXT PRIMARY KEY,
                signal_id TEXT NOT NULL,
                strategy TEXT NOT NULL,
                asset TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                market_id TEXT NOT NULL,
                result TEXT NOT NULL,
                pnl_usdc REAL NOT NULL,
                roi REAL NOT NULL,
                closed_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_results_strategy_asset ON paper_trade_results(strategy,asset,timeframe,closed_at)",
            """
            CREATE TABLE IF NOT EXISTS paper_wallet_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_id TEXT NOT NULL,
                equity REAL NOT NULL,
                cash_balance REAL NOT NULL,
                realized_pnl REAL NOT NULL,
                open_position_count INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS daily_reports (
                report_id TEXT PRIMARY KEY,
                report_date TEXT NOT NULL,
                total_signals INTEGER NOT NULL,
                total_pnl_usdc REAL NOT NULL,
                win_rate REAL NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS telegram_publishes (
                publish_id TEXT PRIMARY KEY,
                message_type TEXT NOT NULL,
                signal_id TEXT,
                status TEXT NOT NULL,
                sent_at TEXT,
                payload_json TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS system_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """,
        ]
        with self._lock, self._conn:
            for statement in ddl:
                self._conn.execute(statement)

    def _json(self, obj: Any) -> str:
        return json.dumps(to_jsonable(obj), ensure_ascii=False, sort_keys=True)

    def upsert_market(self, market: Any) -> None:
        payload = to_jsonable(market)
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO markets(market_id,asset,timeframe,market_slug,status,end_ts,payload_json,updated_at)
                VALUES(?,?,?,?,?,?,?,?)""",
                (payload["market_id"], payload["asset"], payload["timeframe"], payload["market_slug"], payload.get("status"), payload.get("end_ts"), self._json(payload), utc_iso()),
            )

    def insert_signal(self, signal: Any) -> None:
        p = to_jsonable(signal)
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT OR IGNORE INTO signals(signal_id,strategy,asset,timeframe,market_id,side,confidence,created_at,payload_json)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (p["signal_id"], p["strategy"], p["asset"], p["timeframe"], p["market_id"], p["side"], p["confidence"], p["created_at"], self._json(p)),
            )

    def insert_rejected_signal(self, rejected: Any) -> None:
        p = to_jsonable(rejected)
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT OR IGNORE INTO rejected_signals(rejected_id,signal_id,reason_code,gate_name,rejected_at,payload_json)
                VALUES(?,?,?,?,?,?)""",
                (p["rejected_id"], p["candidate"]["signal_id"], p["reason_code"], p["gate_name"], p["rejected_at"], self._json(p)),
            )

    def insert_paper_order(self, order: Any) -> None:
        p = to_jsonable(order)
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO paper_orders(paper_order_id,signal_id,strategy,asset,timeframe,market_id,status,created_at,payload_json)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (p["paper_order_id"], p["signal_id"], p["strategy"], p["asset"], p["timeframe"], p["market_id"], p["status"], p["created_at"], self._json(p)),
            )

    def insert_paper_fill(self, fill: Any) -> None:
        p = to_jsonable(fill)
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT OR IGNORE INTO paper_fills(paper_fill_id,paper_order_id,signal_id,fill_price,stake_usdc,shares,created_at,payload_json)
                VALUES(?,?,?,?,?,?,?,?)""",
                (p["paper_fill_id"], p["paper_order_id"], p["signal_id"], p["fill_price"], p["stake_usdc"], p["shares"], p["created_at"], self._json(p)),
            )

    def upsert_paper_position(self, position: Any) -> None:
        p = to_jsonable(position)
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO paper_positions(paper_position_id,signal_id,strategy,asset,timeframe,market_id,status,opened_at,closed_at,payload_json)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (p["paper_position_id"], p["signal_id"], p["strategy"], p["asset"], p["timeframe"], p["market_id"], p["status"], p["opened_at"], p.get("closed_at"), self._json(p)),
            )

    def insert_paper_trade_result(self, result: Any) -> None:
        p = to_jsonable(result)
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT OR IGNORE INTO paper_trade_results(paper_trade_id,signal_id,strategy,asset,timeframe,market_id,result,pnl_usdc,roi,closed_at,payload_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (p["paper_trade_id"], p["signal_id"], p["strategy"], p["asset"], p["timeframe"], p["market_id"], p["result"], p["pnl_usdc"], p["roi"], p["closed_at"], self._json(p)),
            )

    def insert_wallet_snapshot(self, snapshot: Any) -> None:
        p = to_jsonable(snapshot)
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO paper_wallet_snapshots(wallet_id,equity,cash_balance,realized_pnl,open_position_count,created_at,payload_json)
                VALUES(?,?,?,?,?,?,?)""",
                (p["wallet_id"], p["equity"], p["cash_balance"], p["realized_pnl"], p["open_position_count"], p["created_at"], self._json(p)),
            )

    def insert_daily_report(self, report: Any) -> None:
        p = to_jsonable(report)
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO daily_reports(report_id,report_date,total_signals,total_pnl_usdc,win_rate,created_at,payload_json)
                VALUES(?,?,?,?,?,?,?)""",
                (p["report_id"], p["report_date"], p["total_signals"], p["total_pnl_usdc"], p["win_rate"], p["created_at"], self._json(p)),
            )

    def insert_telegram_publish(self, publish: dict[str, Any]) -> None:
        p = to_jsonable(publish)
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO telegram_publishes(publish_id,message_type,signal_id,status,sent_at,payload_json)
                VALUES(?,?,?,?,?,?)""",
                (p["publish_id"], p["message_type"], p.get("signal_id"), p["status"], p.get("sent_at"), self._json(p)),
            )

    def insert_system_event(self, event: dict[str, Any]) -> None:
        p = to_jsonable(event)
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO system_events(event_id,event_type,severity,created_at,payload_json)
                VALUES(?,?,?,?,?)""",
                (p["event_id"], p["event_type"], p["severity"], p["created_at"], self._json(p)),
            )

    def query_json(self, table: str, limit: int = 100, where: str = "", params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        if table not in {
            "markets", "signals", "rejected_signals", "paper_orders", "paper_fills", "paper_positions", "paper_trade_results",
            "paper_wallet_snapshots", "daily_reports", "telegram_publishes", "system_events",
        }:
            raise ValueError("Unknown table")
        sql = f"SELECT payload_json FROM {table} {where} LIMIT ?"
        with self._lock:
            rows = self._conn.execute(sql, (*params, limit)).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def counts(self) -> dict[str, int]:
        tables = ["signals", "rejected_signals", "paper_orders", "paper_fills", "paper_positions", "paper_trade_results", "daily_reports"]
        with self._lock:
            return {t: int(self._conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]) for t in tables}
