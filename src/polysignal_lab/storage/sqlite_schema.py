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
    CREATE TABLE IF NOT EXISTS strategy_status (
        status_id TEXT PRIMARY KEY,
        strategy TEXT NOT NULL,
        asset TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        status TEXT NOT NULL,
        reason TEXT,
        created_at TEXT NOT NULL,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS report_results (
        report_result_id TEXT PRIMARY KEY,
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
    CREATE TABLE IF NOT EXISTS report_account_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id TEXT NOT NULL,
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
        revision INTEGER NOT NULL DEFAULT 1,
        total_signals INTEGER NOT NULL,
        total_pnl_usdc REAL NOT NULL,
        win_rate REAL NOT NULL,
        created_at TEXT NOT NULL,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS report_publish_outbox (
        intent_id TEXT PRIMARY KEY,
        idempotency_key TEXT NOT NULL UNIQUE,
        report_id TEXT NOT NULL,
        report_date TEXT NOT NULL,
        revision INTEGER NOT NULL,
        status TEXT NOT NULL,
        attempt_count INTEGER NOT NULL DEFAULT 0,
        lease_until TEXT,
        publish_id TEXT,
        last_error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        UNIQUE(report_id),
        UNIQUE(report_date, revision)
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
    """
    CREATE TABLE IF NOT EXISTS report_orders (
        report_order_id TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        created_event_at TEXT NOT NULL,
        source_event_at TEXT NOT NULL,
        source_event_id TEXT NOT NULL,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS report_fills (
        report_fill_id TEXT PRIMARY KEY,
        report_order_id TEXT NOT NULL,
        source_event_at TEXT NOT NULL,
        source_event_id TEXT NOT NULL,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS report_positions (
        report_position_id TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        source_event_at TEXT NOT NULL,
        source_event_id TEXT NOT NULL,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS anchor_prices (
        anchor_id TEXT PRIMARY KEY,
        asset TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        market_slug TEXT NOT NULL,
        window_start TEXT NOT NULL,
        window_end TEXT NOT NULL,
        price REAL,
        source TEXT NOT NULL,
        verified INTEGER NOT NULL,
        captured_at TEXT NOT NULL,
        lag_ms INTEGER,
        payload_json TEXT NOT NULL
    )
    """,
]

INDEX_DDL_STATEMENTS: Final = [
    "CREATE INDEX IF NOT EXISTS idx_markets_asset_tf_end ON markets(asset,timeframe,end_ts)",
    "CREATE INDEX IF NOT EXISTS idx_signals_strategy_asset ON signals(strategy,asset,timeframe,created_at)",
    "CREATE INDEX IF NOT EXISTS idx_strategy_status_strategy_asset ON strategy_status(strategy,asset,timeframe,created_at)",
    "CREATE INDEX IF NOT EXISTS idx_report_results_strategy_asset ON report_results(strategy,asset,timeframe,closed_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_reports_date_revision ON daily_reports(report_date,revision)",
    "CREATE INDEX IF NOT EXISTS idx_report_publish_outbox_status ON report_publish_outbox(status,lease_until)",
    "CREATE INDEX IF NOT EXISTS idx_system_events_type_created ON system_events(event_type,created_at DESC,event_id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_report_orders_status ON report_orders(status,source_event_at)",
    "CREATE INDEX IF NOT EXISTS idx_report_orders_created ON report_orders(created_event_at,report_order_id)",
    "CREATE INDEX IF NOT EXISTS idx_report_fills_order ON report_fills(report_order_id,source_event_at)",
    "CREATE INDEX IF NOT EXISTS idx_report_positions_status ON report_positions(status,source_event_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_anchor_prices_market ON anchor_prices(asset,timeframe,market_slug)",
    # Dashboard 全表时间倒序查询（无 WHERE 的 ORDER BY time DESC）加速：
    "CREATE INDEX IF NOT EXISTS idx_signals_created_at ON signals(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_rejected_signals_rejected_at ON rejected_signals(rejected_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_report_orders_source_event ON report_orders(source_event_at DESC, source_event_id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_report_positions_source_event ON report_positions(source_event_at DESC, source_event_id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_report_results_closed_at ON report_results(closed_at DESC, report_result_id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_system_events_created_at ON system_events(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_report_fills_source_event ON report_fills(source_event_at, report_fill_id)",
]

REQUIRED_COLUMNS: Final[dict[str, frozenset[str]]] = {
    "markets": frozenset(
        {"market_id", "asset", "timeframe", "market_slug", "payload_json", "updated_at"}
    ),
    "signals": frozenset(
        {
            "signal_id",
            "strategy",
            "asset",
            "timeframe",
            "market_id",
            "side",
            "confidence",
            "created_at",
            "payload_json",
        }
    ),
    "rejected_signals": frozenset(
        {
            "rejected_id",
            "signal_id",
            "reason_code",
            "gate_name",
            "rejected_at",
            "payload_json",
        }
    ),
    "strategy_status": frozenset(
        {
            "status_id",
            "strategy",
            "asset",
            "timeframe",
            "status",
            "created_at",
            "payload_json",
        }
    ),
    "report_account_snapshots": frozenset(
        {
            "id",
            "account_id",
            "equity",
            "cash_balance",
            "realized_pnl",
            "open_position_count",
            "created_at",
            "payload_json",
        }
    ),
    "daily_reports": frozenset(
        {
            "report_id",
            "report_date",
            "revision",
            "total_signals",
            "total_pnl_usdc",
            "win_rate",
            "created_at",
            "payload_json",
        }
    ),
    "report_publish_outbox": frozenset(
        {
            "intent_id",
            "idempotency_key",
            "report_id",
            "report_date",
            "revision",
            "status",
            "attempt_count",
            "lease_until",
            "publish_id",
            "last_error",
            "created_at",
            "updated_at",
            "payload_json",
        }
    ),
    "telegram_publishes": frozenset(
        {"publish_id", "message_type", "status", "sent_at", "payload_json"}
    ),
    "system_events": frozenset(
        {"event_id", "event_type", "severity", "created_at", "payload_json"}
    ),
    "report_orders": frozenset(
        {
            "report_order_id",
            "status",
            "created_event_at",
            "source_event_at",
            "source_event_id",
            "payload_json",
        }
    ),
    "report_fills": frozenset(
        {
            "report_fill_id",
            "report_order_id",
            "source_event_at",
            "source_event_id",
            "payload_json",
        }
    ),
    "report_positions": frozenset(
        {
            "report_position_id",
            "status",
            "source_event_at",
            "source_event_id",
            "payload_json",
        }
    ),
    "report_results": frozenset(
        {
            "report_result_id",
            "signal_id",
            "strategy",
            "asset",
            "timeframe",
            "market_id",
            "result",
            "pnl_usdc",
            "roi",
            "closed_at",
            "payload_json",
        }
    ),
    "anchor_prices": frozenset(
        {
            "anchor_id",
            "asset",
            "timeframe",
            "market_slug",
            "window_start",
            "window_end",
            "source",
            "verified",
            "captured_at",
            "payload_json",
        }
    ),
}

ALLOWED_TABLES: Final = frozenset(REQUIRED_COLUMNS)
COUNT_TABLES: Final = (
    "signals",
    "rejected_signals",
    "strategy_status",
    "report_results",
    "report_account_snapshots",
    "daily_reports",
    "report_publish_outbox",
    "telegram_publishes",
    "system_events",
    "report_orders",
    "report_fills",
    "report_positions",
    "anchor_prices",
)

PROJECTION_SCHEMA_VERSION: Final = 6


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
