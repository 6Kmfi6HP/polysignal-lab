from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Final


TABLE_DDL_STATEMENTS: Final = [
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

INDEX_DDL_STATEMENTS: Final = [
    "CREATE INDEX IF NOT EXISTS idx_markets_asset_tf_end ON markets(asset,timeframe,end_ts)",
    "CREATE INDEX IF NOT EXISTS idx_signals_strategy_asset ON signals(strategy,asset,timeframe,created_at)",
    "CREATE INDEX IF NOT EXISTS idx_positions_status ON paper_positions(status,market_id)",
    "CREATE INDEX IF NOT EXISTS idx_results_strategy_asset ON paper_trade_results(strategy,asset,timeframe,closed_at)",
]

REQUIRED_COLUMNS: Final[dict[str, frozenset[str]]] = {
    "markets": frozenset({"market_id", "asset", "timeframe", "market_slug", "payload_json", "updated_at"}),
    "signals": frozenset({"signal_id", "strategy", "asset", "timeframe", "market_id", "side", "confidence", "created_at", "payload_json"}),
    "rejected_signals": frozenset({"rejected_id", "signal_id", "reason_code", "gate_name", "rejected_at", "payload_json"}),
    "paper_orders": frozenset({"paper_order_id", "signal_id", "strategy", "asset", "timeframe", "market_id", "status", "created_at", "payload_json"}),
    "paper_fills": frozenset({"paper_fill_id", "paper_order_id", "signal_id", "fill_price", "stake_usdc", "shares", "created_at", "payload_json"}),
    "paper_positions": frozenset({"paper_position_id", "signal_id", "strategy", "asset", "timeframe", "market_id", "status", "opened_at", "payload_json"}),
    "paper_trade_results": frozenset({"paper_trade_id", "signal_id", "strategy", "asset", "timeframe", "market_id", "result", "pnl_usdc", "roi", "closed_at", "payload_json"}),
    "paper_wallet_snapshots": frozenset({"id", "wallet_id", "equity", "cash_balance", "realized_pnl", "open_position_count", "created_at", "payload_json"}),
    "daily_reports": frozenset({"report_id", "report_date", "total_signals", "total_pnl_usdc", "win_rate", "created_at", "payload_json"}),
    "telegram_publishes": frozenset({"publish_id", "message_type", "status", "payload_json"}),
    "system_events": frozenset({"event_id", "event_type", "severity", "created_at", "payload_json"}),
}

ALLOWED_TABLES: Final = frozenset(REQUIRED_COLUMNS)
COUNT_TABLES: Final = (
    "signals",
    "rejected_signals",
    "paper_orders",
    "paper_fills",
    "paper_positions",
    "paper_trade_results",
    "paper_wallet_snapshots",
    "daily_reports",
    "telegram_publishes",
    "system_events",
)


@dataclass(frozen=True, slots=True)
class SchemaValidationError(RuntimeError):
    table: str
    missing_columns: tuple[str, ...]

    def __str__(self) -> str:
        missing = ", ".join(self.missing_columns)
        return f"SQLite schema for {self.table} is missing required columns: {missing}"


def validate_sqlite_schema(conn: sqlite3.Connection) -> None:
    for table, required in REQUIRED_COLUMNS.items():
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        present = {str(row["name"]) for row in rows}
        missing = tuple(sorted(required - present))
        if missing:
            raise SchemaValidationError(table=table, missing_columns=missing)
