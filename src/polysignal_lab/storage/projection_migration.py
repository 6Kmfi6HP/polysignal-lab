from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping
from typing import Any

from polysignal_lab.storage.event_projection import (
    normalize_report_fill,
    normalize_report_order,
    normalize_report_position,
)
from polysignal_lab.storage.sqlite_schema import PROJECTION_SCHEMA_VERSION

JsonDumper = Callable[[Any], str]

LEGACY_REPORTING_TABLES = frozenset(
    {
        "paper_order_states",
        "paper_position_states",
        "paper_trade_results",
        "paper_wallet_snapshots",
        "projected_orders",
        "projected_fills",
        "projected_positions",
        "projected_results",
    }
)


def migrate_legacy_tables_to_reporting(
    conn: sqlite3.Connection,
    *,
    json_dumps: JsonDumper,
) -> bool:
    current_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if current_version >= PROJECTION_SCHEMA_VERSION:
        return True

    _rename_existing_reporting_columns(conn)
    _canonicalize_reporting_payloads(conn, json_dumps=json_dumps)

    _migrate_orders(conn, json_dumps=json_dumps)
    _migrate_positions(conn, json_dumps=json_dumps)
    _migrate_results(conn, json_dumps=json_dumps)
    _migrate_accounts(conn)
    _migrate_fills_from_system_events(conn, json_dumps=json_dumps)
    _migrate_transitional_projection_tables(conn)
    _canonicalize_reporting_payloads(conn, json_dumps=json_dumps)
    for table in LEGACY_REPORTING_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table}")

    conn.execute(f"PRAGMA user_version = {PROJECTION_SCHEMA_VERSION}")
    return True


def _migrate_orders(conn: sqlite3.Connection, *, json_dumps: JsonDumper) -> None:
    if not _table_exists(conn, "paper_order_states"):
        return
    rows = conn.execute(
        """SELECT paper_order_id,status,created_event_at,source_event_at,
                  source_event_id,payload_json
           FROM paper_order_states"""
    ).fetchall()
    for row in rows:
        order_id = str(row["paper_order_id"] or "")
        if not order_id:
            continue
        conn.execute(
            """INSERT INTO report_orders(
                report_order_id,status,created_event_at,source_event_at,
                source_event_id,payload_json
            ) VALUES(?,?,?,?,?,?)
            ON CONFLICT(report_order_id) DO NOTHING""",
            (
                order_id,
                str(row["status"] or ""),
                str(row["created_event_at"] or ""),
                str(row["source_event_at"] or ""),
                str(row["source_event_id"] or ""),
                json_dumps(
                    _canonical_legacy_payload(
                        row["payload_json"],
                        report_order_id=order_id,
                    )
                ),
            ),
        )


def _migrate_positions(conn: sqlite3.Connection, *, json_dumps: JsonDumper) -> None:
    if not _table_exists(conn, "paper_position_states"):
        return
    rows = conn.execute(
        """SELECT paper_position_id,status,source_event_at,source_event_id,payload_json
           FROM paper_position_states"""
    ).fetchall()
    for row in rows:
        position_id = str(row["paper_position_id"] or "")
        if not position_id:
            continue
        conn.execute(
            """INSERT INTO report_positions(
                report_position_id,status,source_event_at,source_event_id,payload_json
            ) VALUES(?,?,?,?,?)
            ON CONFLICT(report_position_id) DO NOTHING""",
            (
                position_id,
                str(row["status"] or ""),
                str(row["source_event_at"] or ""),
                str(row["source_event_id"] or ""),
                json_dumps(
                    _canonical_legacy_payload(
                        row["payload_json"],
                        report_position_id=position_id,
                    )
                ),
            ),
        )


def _migrate_results(conn: sqlite3.Connection, *, json_dumps: JsonDumper) -> None:
    if not _table_exists(conn, "paper_trade_results"):
        return
    rows = conn.execute(
        """SELECT paper_trade_id,signal_id,strategy,asset,timeframe,market_id,
                  result,pnl_usdc,roi,closed_at,payload_json
           FROM paper_trade_results"""
    ).fetchall()
    for row in rows:
        result_id = str(row["paper_trade_id"] or "")
        if not result_id:
            continue
        payload_json = json_dumps(
            _canonical_legacy_payload(
                row["payload_json"],
                report_result_id=result_id,
            )
        )
        conn.execute(
            """INSERT INTO report_results(
                report_result_id,signal_id,strategy,asset,timeframe,market_id,
                result,pnl_usdc,roi,closed_at,payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(report_result_id) DO NOTHING""",
            (
                result_id,
                str(row["signal_id"] or ""),
                str(row["strategy"] or ""),
                str(row["asset"] or ""),
                str(row["timeframe"] or ""),
                str(row["market_id"] or ""),
                str(row["result"] or ""),
                float(row["pnl_usdc"] or 0.0),
                float(row["roi"] or 0.0),
                str(row["closed_at"] or ""),
                payload_json,
            ),
        )


def _migrate_accounts(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "paper_wallet_snapshots"):
        return
    conn.execute(
        "INSERT INTO report_account_snapshots("
        "account_id,equity,cash_balance,realized_pnl,open_position_count,"
        "created_at,payload_json) "
        "SELECT wallet_id,equity,cash_balance,realized_pnl,open_position_count,"
        "created_at,payload_json FROM paper_wallet_snapshots"
    )


def _migrate_transitional_projection_tables(conn: sqlite3.Connection) -> None:
    copies = (
        (
            "projected_orders",
            "report_orders",
            "report_order_id,status,created_event_at,source_event_at,source_event_id,payload_json",
            "projected_order_id,status,created_event_at,source_event_at,source_event_id,payload_json",
            "report_order_id",
        ),
        (
            "projected_fills",
            "report_fills",
            "report_fill_id,report_order_id,source_event_at,source_event_id,payload_json",
            "projected_fill_id,projected_order_id,source_event_at,source_event_id,payload_json",
            "report_fill_id",
        ),
        (
            "projected_positions",
            "report_positions",
            "report_position_id,status,source_event_at,source_event_id,payload_json",
            "projected_position_id,status,source_event_at,source_event_id,payload_json",
            "report_position_id",
        ),
        (
            "projected_results",
            "report_results",
            "report_result_id,signal_id,strategy,asset,timeframe,market_id,result,pnl_usdc,roi,closed_at,payload_json",
            "projected_result_id,signal_id,strategy,asset,timeframe,market_id,result,pnl_usdc,roi,closed_at,payload_json",
            "report_result_id",
        ),
    )
    for source, target, target_columns, source_columns, key in copies:
        if not _table_exists(conn, source):
            continue
        conn.execute(
            f"INSERT INTO {target}({target_columns}) SELECT {source_columns} FROM {source} "
            f"ON CONFLICT({key}) DO NOTHING"
        )


def _migrate_fills_from_system_events(
    conn: sqlite3.Connection,
    *,
    json_dumps: JsonDumper,
) -> None:
    if not _table_exists(conn, "system_events"):
        return
    rows = conn.execute(
        """SELECT payload_json FROM system_events
           WHERE event_type='nautilus_fill'
           ORDER BY created_at,event_id"""
    ).fetchall()
    for row in rows:
        raw_payload = _loads(row["payload_json"])
        if not isinstance(raw_payload, Mapping):
            continue
        payload = _canonical_legacy_payload(raw_payload)
        fill = normalize_report_fill(payload)
        fill_id = str(fill.get("report_fill_id") or "")
        order_id = str(fill.get("report_order_id") or "")
        source_event_id = str(payload.get("event_id") or fill_id)
        source_event_at = str(payload.get("ts") or payload.get("created_at") or "")
        if not fill_id or not order_id or not source_event_id:
            continue
        # Touch normalize helpers so order/position shapes stay consistent if present.
        _ = normalize_report_order(payload)
        _ = normalize_report_position(payload)
        conn.execute(
            """INSERT INTO report_fills(
                report_fill_id,report_order_id,source_event_at,source_event_id,payload_json
            ) VALUES(?,?,?,?,?)
            ON CONFLICT(report_fill_id) DO NOTHING""",
            (
                fill_id,
                order_id,
                source_event_at,
                source_event_id,
                json_dumps(fill),
            ),
        )


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _rename_existing_reporting_columns(conn: sqlite3.Connection) -> None:
    renames = {
        "report_orders": (("projected_order_id", "report_order_id"),),
        "report_fills": (
            ("projected_fill_id", "report_fill_id"),
            ("projected_order_id", "report_order_id"),
        ),
        "report_positions": (("projected_position_id", "report_position_id"),),
        "report_results": (("projected_result_id", "report_result_id"),),
        "report_account_snapshots": (("wallet_id", "account_id"),),
    }
    for table, columns in renames.items():
        if not _table_exists(conn, table):
            continue
        present = {
            str(row["name"])
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for old, new in columns:
            if old in present and new not in present:
                conn.execute(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}")
                present.remove(old)
                present.add(new)


def _canonicalize_reporting_payloads(
    conn: sqlite3.Connection,
    *,
    json_dumps: JsonDumper,
) -> None:
    for table in (
        "report_orders",
        "report_fills",
        "report_positions",
        "report_results",
        "report_account_snapshots",
        "daily_reports",
    ):
        if not _table_exists(conn, table):
            continue
        rows = conn.execute(
            f"SELECT rowid AS migration_rowid,payload_json FROM {table}"
        ).fetchall()
        for row in rows:
            payload = _canonical_legacy_payload(row["payload_json"])
            conn.execute(
                f"UPDATE {table} SET payload_json=? WHERE rowid=?",
                (json_dumps(payload), int(row["migration_rowid"])),
            )


def _canonical_legacy_payload(raw: object, **ids: str) -> dict[str, Any]:
    payload = _loads(raw)
    result = dict(payload) if isinstance(payload, Mapping) else {}
    mapping = {
        "paper_order_id": "report_order_id",
        "projected_order_id": "report_order_id",
        "paper_fill_id": "report_fill_id",
        "projected_fill_id": "report_fill_id",
        "paper_position_id": "report_position_id",
        "projected_position_id": "report_position_id",
        "paper_trade_id": "report_result_id",
        "projected_result_id": "report_result_id",
        "wallet_id": "account_id",
        "paper_pnl": "net_pnl",
        "paper_roi": "return_rate",
        "paper_orders": "order_count",
        "paper_fills": "fill_count",
        "rejected_paper_orders": "rejected_order_count",
        "stale_paper_fills": "stale_fill_count",
        "paper_attempts_by_intent": "order_attempts_by_intent",
        "paper_fills_by_intent": "fills_by_intent",
        "paper_partial_fills_by_intent": "partial_fills_by_intent",
        "paper_rejects_by_reason": "rejects_by_reason",
        "paper_rejects_by_original_reason": "rejects_by_original_reason",
        "paper_execution_assumptions": "execution_assumptions",
    }
    for old, new in mapping.items():
        value = result.pop(old, None)
        if value not in (None, ""):
            result.setdefault(new, value)
    result.update({key: value for key, value in ids.items() if value})
    return result


def _loads(raw: object) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(str(raw))
    except ValueError:
        return None
