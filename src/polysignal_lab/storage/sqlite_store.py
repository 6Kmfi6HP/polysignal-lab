from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Iterable

from polysignal_lab.domain.enums import PositionStatus
from polysignal_lab.storage.sqlite_schema import (
    ALLOWED_TABLES,
    COUNT_TABLES,
    INDEX_DDL_STATEMENTS,
    TABLE_DDL_STATEMENTS,
    validate_sqlite_schema,
)
from polysignal_lab.utils import to_jsonable, utc_iso


@dataclass(frozen=True, slots=True)
class DuplicateRecordError(RuntimeError):
    table: str
    key: str
    record_id: str

    def __str__(self) -> str:
        return f"duplicate {self.table}.{self.key}={self.record_id} has a different payload"


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
        with self._lock, self._conn:
            for statement in TABLE_DDL_STATEMENTS:
                self._conn.execute(statement)
            validate_sqlite_schema(self._conn)
            for statement in INDEX_DDL_STATEMENTS:
                self._conn.execute(statement)

    def validate_schema(self) -> None:
        with self._lock:
            validate_sqlite_schema(self._conn)

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
            self._insert_idempotent(
                "signals",
                "signal_id",
                p["signal_id"],
                ("signal_id", "strategy", "asset", "timeframe", "market_id", "side", "confidence", "created_at", "payload_json"),
                (p["signal_id"], p["strategy"], p["asset"], p["timeframe"], p["market_id"], p["side"], p["confidence"], p["created_at"], self._json(p)),
            )

    def insert_rejected_signal(self, rejected: Any) -> None:
        p = to_jsonable(rejected)
        with self._lock, self._conn:
            self._insert_idempotent(
                "rejected_signals",
                "rejected_id",
                p["rejected_id"],
                ("rejected_id", "signal_id", "reason_code", "gate_name", "rejected_at", "payload_json"),
                (p["rejected_id"], p["candidate"]["signal_id"], p["reason_code"], p["gate_name"], p["rejected_at"], self._json(p)),
            )

    def insert_paper_order(self, order: Any) -> None:
        p = to_jsonable(order)
        with self._lock, self._conn:
            self._insert_idempotent(
                "paper_orders",
                "paper_order_id",
                p["paper_order_id"],
                ("paper_order_id", "signal_id", "strategy", "asset", "timeframe", "market_id", "status", "created_at", "payload_json"),
                (p["paper_order_id"], p["signal_id"], p["strategy"], p["asset"], p["timeframe"], p["market_id"], p["status"], p["created_at"], self._json(p)),
            )

    def insert_paper_fill(self, fill: Any) -> None:
        p = to_jsonable(fill)
        with self._lock, self._conn:
            self._insert_idempotent(
                "paper_fills",
                "paper_fill_id",
                p["paper_fill_id"],
                ("paper_fill_id", "paper_order_id", "signal_id", "fill_price", "stake_usdc", "shares", "created_at", "payload_json"),
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
            self._insert_idempotent(
                "paper_trade_results",
                "paper_trade_id",
                p["paper_trade_id"],
                ("paper_trade_id", "signal_id", "strategy", "asset", "timeframe", "market_id", "result", "pnl_usdc", "roi", "closed_at", "payload_json"),
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
            self._insert_idempotent(
                "daily_reports",
                "report_id",
                p["report_id"],
                ("report_id", "report_date", "total_signals", "total_pnl_usdc", "win_rate", "created_at", "payload_json"),
                (p["report_id"], p["report_date"], p["total_signals"], p["total_pnl_usdc"], p["win_rate"], p["created_at"], self._json(p)),
            )

    def insert_telegram_publish(self, publish: dict[str, Any]) -> None:
        p = to_jsonable(publish)
        with self._lock, self._conn:
            self._insert_idempotent(
                "telegram_publishes",
                "publish_id",
                p["publish_id"],
                ("publish_id", "message_type", "signal_id", "status", "sent_at", "payload_json"),
                (p["publish_id"], p["message_type"], p.get("signal_id"), p["status"], p.get("sent_at"), self._json(p)),
            )

    def insert_system_event(self, event: dict[str, Any]) -> None:
        p = to_jsonable(event)
        with self._lock, self._conn:
            self._insert_idempotent(
                "system_events",
                "event_id",
                p["event_id"],
                ("event_id", "event_type", "severity", "created_at", "payload_json"),
                (p["event_id"], p["event_type"], p["severity"], p["created_at"], self._json(p)),
            )

    def query_json(self, table: str, limit: int = 100, where: str = "", params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        if table not in ALLOWED_TABLES:
            raise ValueError("Unknown table")
        sql = f"SELECT payload_json FROM {table} {where} LIMIT ?"
        with self._lock:
            rows = self._conn.execute(sql, (*params, limit)).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def counts(self) -> dict[str, int]:
        with self._lock:
            return {t: int(self._conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]) for t in COUNT_TABLES}

    def restore_latest_wallet_snapshot(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload_json FROM paper_wallet_snapshots ORDER BY created_at DESC, id DESC LIMIT 1"
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def restore_open_positions(self) -> list[dict[str, Any]]:
        return self.query_json(
            "paper_positions",
            where="WHERE status = ? ORDER BY opened_at ASC",
            params=(PositionStatus.OPEN.value,),
            limit=10000,
        )

    def restore_daily_reports(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.query_json(
            "daily_reports",
            where="ORDER BY report_date DESC, created_at DESC",
            limit=limit,
        )

    def restore_strategy_leaderboard(self, limit: int = 500) -> list[dict[str, Any]]:
        reports = self.restore_daily_reports(limit=limit)
        merged: dict[str, dict[str, float | int | str]] = {}
        roi_sum: dict[str, float] = {}
        for report in reports:
            for strategy, row in report.get("strategy_breakdown", {}).items():
                entry = merged.setdefault(
                    strategy,
                    {"strategy": strategy, "closed_positions": 0, "win_count": 0, "loss_count": 0, "void_count": 0, "total_pnl_usdc": 0.0, "average_roi": 0.0},
                )
                closed = int(row.get("closed_positions", 0))
                entry["closed_positions"] = int(entry["closed_positions"]) + closed
                entry["win_count"] = int(entry["win_count"]) + int(row.get("win_count", 0))
                entry["loss_count"] = int(entry["loss_count"]) + int(row.get("loss_count", 0))
                entry["void_count"] = int(entry["void_count"]) + int(row.get("void_count", 0))
                entry["total_pnl_usdc"] = float(entry["total_pnl_usdc"]) + float(row.get("total_pnl_usdc", 0.0))
                roi_sum[strategy] = roi_sum.get(strategy, 0.0) + (float(row.get("average_roi", 0.0)) * closed)
        for strategy, entry in merged.items():
            closed = int(entry["closed_positions"])
            wins = int(entry["win_count"])
            entry["average_roi"] = roi_sum.get(strategy, 0.0) / closed if closed else 0.0
            entry["win_rate"] = wins / closed if closed else 0.0
        return sorted(merged.values(), key=lambda row: float(row["total_pnl_usdc"]), reverse=True)

    def _insert_idempotent(
        self,
        table: str,
        key: str,
        record_id: str,
        columns: tuple[str, ...],
        values: tuple[Any, ...],
    ) -> None:
        existing = self._conn.execute(
            f"SELECT payload_json FROM {table} WHERE {key} = ?",
            (record_id,),
        ).fetchone()
        payload = values[-1]
        if existing:
            if json.loads(existing["payload_json"]) == json.loads(payload):
                return
            raise DuplicateRecordError(table=table, key=key, record_id=record_id)
        placeholders = ",".join("?" for _ in columns)
        column_sql = ",".join(columns)
        self._conn.execute(
            f"INSERT INTO {table}({column_sql}) VALUES({placeholders})",
            values,
        )
