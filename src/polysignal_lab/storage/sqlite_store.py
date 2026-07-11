# noqa: SIZE_OK  — legacy SQLite gateway; current change only adds fail-closed parsing
"""
Input: __future__, __future__.annotations, json, datetime, datetime.datetime, sqlite3, dataclasses, dataclasses.dataclass, pathlib, pathlib.Path, math
Output: DuplicateRecordError, MalformedSQLitePayloadError, SQLiteStore
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import json
from datetime import datetime
import math
import sqlite3
from dataclasses import dataclass
from collections.abc import Mapping
from pathlib import Path
from threading import Lock
from typing import Any, Iterable

from polysignal_lab.domain.anchor_price import AnchorPrice
from polysignal_lab.domain.enums import PositionStatus, Side
from polysignal_lab.domain.paper_result import (
    InvalidPaperTradeResultRow,
    parse_paper_trade_result_row,
)
from polysignal_lab.storage.sqlite_schema import (
    ALLOWED_TABLES,
    COUNT_TABLES,
    INDEX_DDL_STATEMENTS,
    TABLE_DDL_STATEMENTS,
    validate_sqlite_schema,
)
from polysignal_lab.utils import stable_hash, to_jsonable, utc_iso


@dataclass(frozen=True, slots=True)
class DuplicateRecordError(RuntimeError):
    table: str
    key: str
    record_id: str

    def __str__(self) -> str:
        return f"duplicate {self.table}.{self.key}={self.record_id} has a different payload"


@dataclass(frozen=True, slots=True)
class MalformedSQLitePayloadError(RuntimeError):
    table: str
    key: str
    record_id: str

    def __str__(self) -> str:
        return f"malformed {self.table}.payload_json for {self.key}={self.record_id}"


@dataclass(frozen=True, slots=True)
class UnknownSQLiteTableError(RuntimeError):
    table: str

    def __str__(self) -> str:
        return f"Unknown table: {self.table}"


def _payload_json(row: sqlite3.Row) -> Any | None:
    try:
        return json.loads(row["payload_json"])
    except ValueError:
        return None


def _valid_position_event(row: Mapping[str, Any]) -> bool:
    position_id = str(row.get("paper_position_id") or row.get("position_id") or "")
    if not position_id:
        return False
    status = str(row.get("status") or "").upper()
    if status not in {"", PositionStatus.OPEN.value, PositionStatus.CLOSED.value}:
        return False
    if status == "" and not isinstance(row.get("is_closed"), bool):
        return False
    if status == PositionStatus.OPEN.value and row.get("is_closed") is True:
        return False
    if status == PositionStatus.CLOSED.value and row.get("is_closed") is False:
        return False
    is_open = status == PositionStatus.OPEN.value or (
        status == "" and row.get("is_closed") is False
    )
    is_closed = status == PositionStatus.CLOSED.value or (
        status == "" and row.get("is_closed") is True
    )
    side = str(row.get("side") or "").upper()
    if (is_open or is_closed) and side not in {Side.UP.value, Side.DOWN.value}:
        return False
    timestamp_keys = ("opened_at", "ts", "created_at") if is_open else ("closed_at", "ts", "created_at")
    if (is_open or is_closed) and (
        _row_positive_float(row, "shares", "quantity", "signed_qty") is None
        or _row_positive_float(row, "entry_price", "avg_entry_price") is None
        or _row_positive_float(row, "stake_usdc") is None
        or _row_timestamp(row, *timestamp_keys) is None
    ):
        return False
    for key in ("shares", "quantity", "signed_qty", "entry_price", "avg_entry_price", "stake_usdc"):
        value = row.get(key)
        if value in (None, ""):
            continue
        parsed = _row_finite_float(row, key)
        if parsed is None or parsed <= 0.0:
            return False
    return True


def _row_finite_float(row: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = row.get(key)
        if value in (None, ""):
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            return None
        try:
            parsed = float(value)
        except (OverflowError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None
    return None


def _row_positive_float(row: Mapping[str, Any], *keys: str) -> float | None:
    parsed = _row_finite_float(row, *keys)
    if parsed is None or parsed <= 0.0:
        return None
    return parsed


def _row_timestamp(row: Mapping[str, Any], *keys: str) -> datetime | None:
    for key in keys:
        value = row.get(key)
        if value in (None, ""):
            continue
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None
    return None


def _valid_money_value(value: Any, *, allow_negative: bool) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return False
    try:
        parsed = float(value)
    except (OverflowError, TypeError, ValueError):
        return False
    if not math.isfinite(parsed):
        return False
    return allow_negative or parsed >= 0.0


def _valid_count_value(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return 0 <= value <= 1_000_000
    if isinstance(value, float):
        return math.isfinite(value) and value.is_integer() and 0.0 <= value <= 1_000_000.0
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text.isdecimal():
        return False
    try:
        parsed = int(text)
    except (TypeError, ValueError, OverflowError):
        return False
    return 0 <= parsed <= 1_000_000


def _valid_wallet_snapshot_payload(payload: Mapping[str, Any]) -> bool:
    for key in ("starting_balance", "cash_balance", "reserved_balance", "equity"):
        value = payload.get(key)
        if value not in (None, "") and not _valid_money_value(value, allow_negative=False):
            return False
    for key in ("realized_pnl", "unrealized_pnl"):
        value = payload.get(key)
        if value not in (None, "") and not _valid_money_value(value, allow_negative=True):
            return False
    count = payload.get("open_position_count")
    return count in (None, "") or _valid_count_value(count)


def _valid_strategy_breakdown(row: Mapping[str, Any]) -> bool:
    for key in ("closed_positions", "win_count", "loss_count", "void_count"):
        value = row.get(key)
        if value not in (None, "") and not _valid_count_value(value):
            return False
    for key in ("total_pnl_usdc", "average_roi", "win_rate"):
        value = row.get(key)
        if value not in (None, "") and not _valid_money_value(value, allow_negative=True):
            return False
    return True


def _valid_daily_report_payload(payload: Mapping[str, Any]) -> bool:
    for key in ("paper_pnl", "paper_roi", "total_pnl_usdc", "average_roi", "win_rate", "max_drawdown"):
        value = payload.get(key)
        if value not in (None, "") and not _valid_money_value(value, allow_negative=True):
            return False
    for key in ("total_signals", "paper_orders", "paper_fills", "rejected_paper_orders", "open_positions", "closed_positions", "win_count", "loss_count", "void_count"):
        value = payload.get(key)
        if value not in (None, "") and not _valid_count_value(value):
            return False
    breakdown = payload.get("strategy_breakdown", {})
    if not isinstance(breakdown, Mapping):
        return False
    return all(
        isinstance(row, Mapping) and _valid_strategy_breakdown(row)
        for row in breakdown.values()
    )


class SQLiteStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
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

    def _build_query(
        self,
        table: str,
        columns: str = "payload_json",
        where: str = "",
        params: Iterable[Any] = (),
        order_by: str = "",
        limit: int | None = None,
    ) -> tuple[str, list[Any]]:
        """Build a SELECT SQL string + parameter list from structured components.

        Returns (sql, param_list) safe for self._conn.execute(sql, param_list).
        """
        if table not in ALLOWED_TABLES:
            raise UnknownSQLiteTableError(table=table)
        parts: list[str] = [f"SELECT {columns} FROM {table}"]
        param_list: list[Any] = list(params)
        if where:
            parts.append(where)
        if order_by:
            parts.append(f"ORDER BY {order_by}")
        if limit is not None:
            parts.append("LIMIT ?")
            param_list.append(limit)
        return " ".join(parts), param_list

    def upsert_market(self, market: Any) -> None:
        payload = to_jsonable(market)
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO markets(market_id,asset,timeframe,market_slug,status,end_ts,payload_json,updated_at)
                VALUES(?,?,?,?,?,?,?,?)""",
                (payload["market_id"], payload["asset"], payload["timeframe"], payload["market_slug"], payload.get("status"), payload.get("end_ts"), self._json(payload), utc_iso()),
            )


    def upsert_anchor_price(self, anchor: AnchorPrice) -> None:
        payload = {
            "asset": anchor.asset.upper(),
            "timeframe": anchor.timeframe,
            "market_slug": anchor.market_slug,
            "window_start": utc_iso(anchor.window_start),
            "window_end": utc_iso(anchor.window_end),
            "price": anchor.price,
            "source": anchor.source,
            "verified": anchor.verified,
            "captured_at": utc_iso(anchor.captured_at),
            "lag_ms": anchor.lag_ms,
        }
        anchor_id = f"{anchor.asset.upper()}:{anchor.timeframe}:{anchor.market_slug}"
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO anchor_prices(
                    anchor_id,asset,timeframe,market_slug,window_start,window_end,
                    price,source,verified,captured_at,lag_ms,payload_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(anchor_id) DO UPDATE SET
                    asset=excluded.asset,
                    timeframe=excluded.timeframe,
                    market_slug=excluded.market_slug,
                    window_start=excluded.window_start,
                    window_end=excluded.window_end,
                    price=excluded.price,
                    source=excluded.source,
                    verified=excluded.verified,
                    captured_at=excluded.captured_at,
                    lag_ms=excluded.lag_ms,
                    payload_json=excluded.payload_json
                WHERE NOT (anchor_prices.verified = 1 AND excluded.verified = 0)""",
                (
                    anchor_id,
                    anchor.asset.upper(),
                    anchor.timeframe,
                    anchor.market_slug,
                    utc_iso(anchor.window_start),
                    utc_iso(anchor.window_end),
                    anchor.price,
                    anchor.source,
                    1 if anchor.verified else 0,
                    utc_iso(anchor.captured_at),
                    anchor.lag_ms,
                    self._json(payload),
                ),
            )

    def get_verified_anchor_price(
        self, asset: str, timeframe: str, market_slug: str
    ) -> AnchorPrice | None:
        sql, params = self._build_query(
            "anchor_prices",
            where="WHERE asset=? AND timeframe=? AND market_slug=? AND verified=1",
            params=(asset.upper(), timeframe, market_slug),
            limit=1,
        )
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        if row is None:
            return None
        payload = _payload_json(row)
        if not isinstance(payload, dict):
            return None
        return AnchorPrice(
            asset=str(payload["asset"]),
            timeframe=str(payload["timeframe"]),
            market_slug=str(payload["market_slug"]),
            window_start=datetime.fromisoformat(str(payload["window_start"])),
            window_end=datetime.fromisoformat(str(payload["window_end"])),
            price=float(payload["price"]) if payload.get("price") is not None else None,
            source=str(payload["source"]),
            verified=bool(payload["verified"]),
            captured_at=datetime.fromisoformat(str(payload["captured_at"])),
            lag_ms=int(payload["lag_ms"]) if payload.get("lag_ms") is not None else None,
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

    def insert_strategy_status(self, status: Any) -> None:
        p = to_jsonable(status)
        created_at = utc_iso()
        status_id = stable_hash(
            p["strategy"],
            p["asset"],
            p["timeframe"],
            p["status"],
            p.get("reason"),
            created_at,
        )
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO strategy_status(status_id,strategy,asset,timeframe,status,reason,created_at,payload_json)
                VALUES(?,?,?,?,?,?,?,?)""",
                (
                    status_id,
                    p["strategy"],
                    p["asset"],
                    p["timeframe"],
                    p["status"],
                    p.get("reason"),
                    created_at,
                    self._json(p),
                ),
            )

    def insert_paper_trade_result(self, result: Any) -> None:
        p: dict[str, Any] = dict(parse_paper_trade_result_row(to_jsonable(result)))
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

    def restore_latest_system_event(self, event_type: str) -> dict[str, Any] | None:
        sql, params = self._build_query(
            "system_events",
            where="WHERE event_type = ?",
            params=(event_type,),
            order_by="created_at DESC, rowid DESC",
            limit=1,
        )
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        if row is None:
            return None
        payload = _payload_json(row)
        if not isinstance(payload, dict):
            return None
        return payload

    def query_json(self, table: str, limit: int = 100, where: str = "", params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        sql, params = self._build_query(table, where=where, params=params, limit=limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        if table == "paper_trade_results":
            valid_results: list[dict[str, Any]] = []
            for row in rows:
                try:
                    payload = _payload_json(row)
                    if not isinstance(payload, dict):
                        continue
                    valid_results.append(dict(parse_paper_trade_result_row(payload)))
                except InvalidPaperTradeResultRow:
                    continue
            return valid_results
        if table in {"system_events", "daily_reports"}:
            valid_rows: list[dict[str, Any]] = []
            for row in rows:
                payload = _payload_json(row)
                if not isinstance(payload, dict):
                    continue
                if table == "daily_reports" and not _valid_daily_report_payload(payload):
                    continue
                valid_rows.append(payload)
            return valid_rows
        valid_rows: list[dict[str, Any]] = []
        for row in rows:
            payload = _payload_json(row)
            if isinstance(payload, dict):
                valid_rows.append(payload)
        return valid_rows

    def counts(self) -> dict[str, int]:
        with self._lock:
            return {t: int(self._conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]) for t in COUNT_TABLES}

    def restore_latest_wallet_snapshot(self) -> dict[str, Any] | None:
        sql, params = self._build_query(
            "paper_wallet_snapshots",
            order_by="created_at DESC, id DESC",
            limit=1,
        )
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        if row is None:
            return None
        payload = _payload_json(row)
        if not isinstance(payload, dict):
            return None
        if not _valid_wallet_snapshot_payload(payload):
            return None
        return payload

    def _latest_position_events(self) -> dict[str, dict[str, Any]]:
        rows = self.query_json(
            "system_events",
            where="WHERE event_type=? ORDER BY created_at ASC, rowid ASC",
            params=("nautilus_position",),
            limit=100_000,
        )
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            position_id = str(row.get("paper_position_id") or row.get("position_id") or "")
            if position_id:
                latest[position_id] = row
        return {position_id: row for position_id, row in latest.items() if _valid_position_event(row)}

    def restore_open_positions(self) -> list[dict[str, Any]]:
        open_status = PositionStatus.OPEN.value
        return [
            row
            for row in self._latest_position_events().values()
            if str(row.get("status", "")).upper() == open_status
            or (row.get("status") in (None, "") and row.get("is_closed") is False)
        ]

    def restore_closed_positions(self) -> list[dict[str, Any]]:
        closed_status = PositionStatus.CLOSED.value
        return [
            row
            for row in self._latest_position_events().values()
            if str(row.get("status", "")).upper() == closed_status
            or row.get("is_closed") is True
        ]

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
        payload_json = values[-1]
        if self._skip_duplicate_payload_row(
            table=table,
            key_column=key,
            key_value=record_id,
            payload_json=payload_json,
        ):
            return
        placeholders = ",".join("?" for _ in columns)
        column_sql = ",".join(columns)
        self._conn.execute(
            f"INSERT INTO {table}({column_sql}) VALUES({placeholders})",
            values,
        )

    def _skip_duplicate_payload_row(
        self,
        *,
        table: str,
        key_column: str,
        key_value: str,
        payload_json: str,
    ) -> bool:
        existing = self._conn.execute(
            f"SELECT payload_json FROM {table} WHERE {key_column} = ?",
            (key_value,),
        ).fetchone()
        if existing is None:
            return False
        existing_payload = _payload_json(existing)
        if existing_payload is None:
            raise MalformedSQLitePayloadError(
                table=table,
                key=key_column,
                record_id=key_value,
            )
        if existing_payload == json.loads(payload_json):
            return True
        raise DuplicateRecordError(table=table, key=key_column, record_id=key_value)
