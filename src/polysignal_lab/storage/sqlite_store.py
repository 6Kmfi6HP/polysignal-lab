# noqa: SIZE_OK  — SQLite gateway; split is outside reporting boundary prefactor
"""
Input: __future__, json, datetime, sqlite3, dataclasses, collections.abc, pathlib, threading, typing, polysignal_lab.domain, polysignal_lab.paper, polysignal_lab.storage, polysignal_lab.utils
Output: DuplicateRecordError, MalformedSQLitePayloadError, SQLiteStore
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import json
from datetime import datetime, timedelta
import math
import sqlite3
from dataclasses import dataclass
from collections.abc import Mapping
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any, Iterable

from polysignal_lab.domain.anchor_price import AnchorPrice
from polysignal_lab.domain.enums import PositionStatus, Side
from polysignal_lab.domain.paper_result import (
    DailyReport,
    InvalidPaperTradeResultRow,
    parse_paper_trade_result_row,
)
from polysignal_lab.paper.event_projection import (
    normalize_paper_order,
    normalize_paper_position,
)
from polysignal_lab.paper.strategy_stats import build_strategy_leaderboard_rows
from polysignal_lab.storage.sqlite_schema import (
    ALLOWED_TABLES,
    COUNT_TABLES,
    INDEX_DDL_STATEMENTS,
    TABLE_DDL_STATEMENTS,
    validate_sqlite_schema,
)
from polysignal_lab.utils import stable_hash, to_jsonable, utc_iso, utc_now

if TYPE_CHECKING:
    from polysignal_lab.dashboard.reporting_read import StorageHealthRead


_PAPER_CURRENT_STATE_SCHEMA_VERSION = 1


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


def _same_daily_report_content(
    candidate: Mapping[str, Any],
    persisted: Mapping[str, Any],
) -> bool:
    ignored = {"report_id", "revision", "created_at"}
    return (
        {key: value for key, value in candidate.items() if key not in ignored}
        == {key: value for key, value in persisted.items() if key not in ignored}
    )


def _invalid_position_state_source(row: Mapping[str, Any]) -> bool:
    metrics = row.get("metrics")
    metric_values = metrics if isinstance(metrics, Mapping) else {}
    sources = (row, metric_values)
    for source in sources:
        for key in (
            "shares",
            "quantity",
            "signed_qty",
            "entry_price",
            "avg_entry_price",
            "price",
            "stake_usdc",
        ):
            if isinstance(source.get(key), bool):
                return True
    status = str(row.get("status") or metric_values.get("status") or "").upper()
    is_closed = row.get("is_closed")
    if status and status not in {PositionStatus.OPEN.value, PositionStatus.CLOSED.value}:
        return True
    if is_closed not in (None, "") and not isinstance(is_closed, bool):
        return True
    if not status and not isinstance(is_closed, bool):
        return True
    return isinstance(is_closed, bool) and (
        (status == PositionStatus.OPEN.value and is_closed)
        or (status == PositionStatus.CLOSED.value and not is_closed)
    )


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
            revision_added = self._add_column_if_missing(
                "daily_reports",
                "revision",
                "INTEGER NOT NULL DEFAULT 1",
            )
            if revision_added:
                self._backfill_daily_report_revisions()
            validate_sqlite_schema(self._conn)
            self._backfill_paper_current_states()
            for statement in INDEX_DDL_STATEMENTS:
                self._conn.execute(statement)

    def _add_column_if_missing(
        self,
        table: str,
        column: str,
        declaration: str,
    ) -> bool:
        columns = {
            str(row["name"])
            for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column in columns:
            return False
        self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
        return True

    def _backfill_daily_report_revisions(self) -> None:
        rows = self._conn.execute(
            """SELECT report_id,report_date,payload_json
            FROM daily_reports
            ORDER BY report_date,created_at,report_id"""
        ).fetchall()
        revisions: dict[str, int] = {}
        for row in rows:
            report_date = str(row["report_date"])
            revision = revisions.get(report_date, 0) + 1
            revisions[report_date] = revision
            payload = _payload_json(row)
            payload_json = str(row["payload_json"])
            if isinstance(payload, dict):
                payload["revision"] = revision
                payload_json = self._json(payload)
            self._conn.execute(
                "UPDATE daily_reports SET revision=?,payload_json=? WHERE report_id=?",
                (revision, payload_json, str(row["report_id"])),
            )

    def _backfill_paper_current_states(self) -> None:
        current_version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        if current_version >= _PAPER_CURRENT_STATE_SCHEMA_VERSION:
            return
        rows = self._conn.execute(
            """SELECT payload_json
            FROM system_events
            WHERE event_type IN ('nautilus_order','nautilus_position')
            ORDER BY created_at,event_id"""
        ).fetchall()
        for row in rows:
            payload = _payload_json(row)
            if isinstance(payload, dict):
                self._upsert_paper_current_state(payload)
        self._conn.execute(
            f"PRAGMA user_version = {_PAPER_CURRENT_STATE_SCHEMA_VERSION}"
        )

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
                ("report_id", "report_date", "revision", "total_signals", "total_pnl_usdc", "win_rate", "created_at", "payload_json"),
                (p["report_id"], p["report_date"], p.get("revision", 1), p["total_signals"], p["total_pnl_usdc"], p["win_rate"], p["created_at"], self._json(p)),
            )

    def claim_daily_report(
        self,
        report: DailyReport,
        *,
        enqueue_publish: bool,
    ) -> tuple[DailyReport, bool]:
        p = to_jsonable(report)
        report_date = str(p["report_date"])
        created = True
        with self._lock, self._conn:
            try:
                self._insert_claimed_daily_report(p)
                persisted = report
            except sqlite3.IntegrityError:
                row = self._conn.execute(
                    """SELECT revision,payload_json FROM daily_reports
                    WHERE report_date=?
                    ORDER BY revision DESC
                    LIMIT 1""",
                    (report_date,),
                ).fetchone()
                if row is None:
                    raise
                revision = int(row["revision"])
                payload = _payload_json(row)
                if not isinstance(payload, dict):
                    raise MalformedSQLitePayloadError(
                        table="daily_reports",
                        key="report_date_revision",
                        record_id=f"{report_date}:{revision}",
                    )
                payload["revision"] = revision
                if _same_daily_report_content(p, payload):
                    persisted = DailyReport.model_validate(payload)
                    created = False
                else:
                    persisted = report.model_copy(
                        update={"revision": revision + 1},
                    )
                    self._insert_claimed_daily_report(to_jsonable(persisted))

            if enqueue_publish:
                if persisted.revision > 1:
                    self._supersede_pending_daily_report_publishes(persisted)
                self._insert_daily_report_publish_intent(persisted)
        return persisted, created

    def _insert_claimed_daily_report(self, payload: Mapping[str, Any]) -> None:
        self._conn.execute(
            """INSERT INTO daily_reports(
                report_id,report_date,revision,total_signals,total_pnl_usdc,
                win_rate,created_at,payload_json
            ) VALUES(?,?,?,?,?,?,?,?)""",
            (
                payload["report_id"],
                str(payload["report_date"]),
                int(payload.get("revision", 1)),
                payload["total_signals"],
                payload["total_pnl_usdc"],
                payload["win_rate"],
                payload["created_at"],
                self._json(payload),
            ),
        )

    def _supersede_pending_daily_report_publishes(
        self,
        report: DailyReport,
    ) -> None:
        now = utc_iso()
        rows = self._conn.execute(
            """SELECT * FROM report_publish_outbox
            WHERE report_date=? AND revision<? AND status='PENDING'""",
            (report.report_date.isoformat(), report.revision),
        ).fetchall()
        for row in rows:
            payload = self._outbox_payload(row)
            payload.update(
                {
                    "status": "SUPERSEDED",
                    "last_error": f"superseded_by_revision:{report.revision}",
                    "updated_at": now,
                }
            )
            self._conn.execute(
                """UPDATE report_publish_outbox
                SET status='SUPERSEDED',last_error=?,updated_at=?,payload_json=?
                WHERE intent_id=? AND status='PENDING'""",
                (
                    payload["last_error"],
                    now,
                    self._json(payload),
                    str(row["intent_id"]),
                ),
            )

    def _insert_daily_report_publish_intent(self, report: DailyReport) -> None:
        report_date = report.report_date.isoformat()
        idempotency_key = f"daily_report:{report_date}:r{report.revision}"
        intent_id = f"outbox_{stable_hash(idempotency_key)}"
        now = utc_iso()
        payload = {
            "intent_id": intent_id,
            "idempotency_key": idempotency_key,
            "report_id": report.report_id,
            "report_date": report_date,
            "revision": report.revision,
            "status": "PENDING",
            "attempt_count": 0,
            "lease_until": None,
            "publish_id": None,
            "last_error": None,
            "created_at": now,
            "updated_at": now,
        }
        self._conn.execute(
            """INSERT OR IGNORE INTO report_publish_outbox(
                intent_id,idempotency_key,report_id,report_date,revision,status,
                attempt_count,lease_until,publish_id,last_error,created_at,
                updated_at,payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                intent_id,
                idempotency_key,
                report.report_id,
                report_date,
                report.revision,
                "PENDING",
                0,
                None,
                None,
                None,
                now,
                now,
                self._json(payload),
            ),
        )

    def restore_report_publish_outbox(
        self,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self.query_json(
            "report_publish_outbox",
            where="ORDER BY created_at DESC",
            limit=limit,
        )

    def pending_daily_report_publishes(
        self,
        *,
        before_date: str,
        limit: int = 100,
    ) -> list[DailyReport]:
        now = utc_iso()
        with self._lock:
            rows = self._conn.execute(
                """SELECT reports.revision,reports.payload_json
                FROM report_publish_outbox AS outbox
                JOIN daily_reports AS reports ON reports.report_id=outbox.report_id
                WHERE outbox.report_date<? AND (
                    outbox.status='PENDING' OR
                    (outbox.status='DELIVERING' AND outbox.lease_until IS NOT NULL
                    AND outbox.lease_until<=?)
                )
                ORDER BY outbox.created_at,outbox.intent_id
                LIMIT ?""",
                (before_date, now, max(1, min(int(limit), 500))),
            ).fetchall()
        reports: list[DailyReport] = []
        for row in rows:
            payload = _payload_json(row)
            if not isinstance(payload, dict):
                continue
            payload["revision"] = int(row["revision"])
            reports.append(DailyReport.model_validate(payload))
        return reports

    def claim_daily_report_publish(
        self,
        report_id: str,
        *,
        lease_sec: float,
    ) -> dict[str, Any] | None:
        now_dt = utc_now()
        now = utc_iso(now_dt)
        lease_until = utc_iso(now_dt + timedelta(seconds=max(float(lease_sec), 1.0)))
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """UPDATE report_publish_outbox
                SET status='DELIVERING',attempt_count=attempt_count+1,
                    lease_until=?,publish_id=NULL,last_error=NULL,updated_at=?
                WHERE report_id=? AND (
                    status='PENDING' OR
                    (status='DELIVERING' AND lease_until IS NOT NULL AND lease_until<=?)
                )""",
                (lease_until, now, report_id, now),
            )
            if cursor.rowcount != 1:
                return None
            row = self._conn.execute(
                "SELECT * FROM report_publish_outbox WHERE report_id=?",
                (report_id,),
            ).fetchone()
            if row is None:
                return None
            payload = self._outbox_payload(row)
            payload.update(
                {
                    "status": "DELIVERING",
                    "attempt_count": int(row["attempt_count"]),
                    "lease_until": lease_until,
                    "publish_id": None,
                    "last_error": None,
                    "updated_at": now,
                }
            )
            self._conn.execute(
                "UPDATE report_publish_outbox SET payload_json=? WHERE intent_id=?",
                (self._json(payload), str(row["intent_id"])),
            )
            return payload

    def complete_daily_report_publish(
        self,
        intent_id: str,
        attempt_count: int,
        publish: Mapping[str, Any],
    ) -> bool:
        p = to_jsonable(publish)
        publish_status = str(p.get("status") or "FAILED").upper()
        delivered = publish_status in {"SENT", "DRY_RUN"}
        status = publish_status if delivered else "PENDING"
        last_error = None if delivered else str(p.get("error") or "publish_failed")
        now = utc_iso()
        with self._lock, self._conn:
            row = self._conn.execute(
                """SELECT * FROM report_publish_outbox
                WHERE intent_id=? AND status='DELIVERING' AND attempt_count=?""",
                (intent_id, attempt_count),
            ).fetchone()
            if row is None:
                return False
            updated = self._update_report_publish_outbox(
                row,
                attempt_count=attempt_count,
                status=status,
                publish_id=p.get("publish_id"),
                last_error=last_error,
                updated_at=now,
            )
            if not updated:
                return False
            self._insert_idempotent(
                "telegram_publishes",
                "publish_id",
                str(p["publish_id"]),
                (
                    "publish_id",
                    "message_type",
                    "signal_id",
                    "status",
                    "sent_at",
                    "payload_json",
                ),
                (
                    p["publish_id"],
                    p.get("message_type", "daily_report"),
                    p.get("signal_id"),
                    publish_status,
                    p.get("sent_at"),
                    self._json(p),
                ),
            )
            return True

    def release_daily_report_publish(
        self,
        intent_id: str,
        attempt_count: int,
        error: str,
    ) -> bool:
        now = utc_iso()
        with self._lock, self._conn:
            row = self._conn.execute(
                """SELECT * FROM report_publish_outbox
                WHERE intent_id=? AND status='DELIVERING' AND attempt_count=?""",
                (intent_id, attempt_count),
            ).fetchone()
            if row is None:
                return False
            return self._update_report_publish_outbox(
                row,
                attempt_count=attempt_count,
                status="PENDING",
                last_error=error,
                updated_at=now,
                preserve_publish_id=True,
            )

    def _update_report_publish_outbox(
        self,
        row: sqlite3.Row,
        *,
        attempt_count: int,
        status: str,
        last_error: str | None,
        updated_at: str,
        publish_id: Any = None,
        preserve_publish_id: bool = False,
    ) -> bool:
        payload = self._outbox_payload(row)
        if not preserve_publish_id:
            payload["publish_id"] = publish_id
        payload.update(
            {
                "status": status,
                "lease_until": None,
                "last_error": last_error,
                "updated_at": updated_at,
            }
        )
        cursor = self._conn.execute(
            """UPDATE report_publish_outbox
            SET status=?,lease_until=NULL,publish_id=?,last_error=?,
                updated_at=?,payload_json=?
            WHERE intent_id=? AND status='DELIVERING' AND attempt_count=?""",
            (
                status,
                row["publish_id"] if preserve_publish_id else publish_id,
                last_error,
                updated_at,
                self._json(payload),
                str(row["intent_id"]),
                attempt_count,
            ),
        )
        return cursor.rowcount == 1

    def _outbox_payload(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = _payload_json(row)
        if not isinstance(payload, dict):
            raise MalformedSQLitePayloadError(
                table="report_publish_outbox",
                key="intent_id",
                record_id=str(row["intent_id"]),
            )
        return payload

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
            self._upsert_paper_current_state(p)

    def _upsert_paper_current_state(self, event: Mapping[str, Any]) -> None:
        event_type = str(event.get("event_type") or "")
        if event_type == "nautilus_order":
            payload = normalize_paper_order(event)
            if not payload.get("status"):
                payload["_projection_invalid"] = True
                payload["status"] = "INVALID"
            table = "paper_order_states"
            id_column = "paper_order_id"
        elif event_type == "nautilus_position":
            payload = normalize_paper_position(event)
            invalid = _invalid_position_state_source(event)
            if invalid:
                payload["_projection_invalid"] = True
                if not payload.get("status"):
                    payload["status"] = "INVALID"
            table = "paper_position_states"
            id_column = "paper_position_id"
        else:
            return

        record_id = str(payload.get(id_column) or "")
        status = str(payload.get("status") or "").upper()
        source_event_id = str(event.get("event_id") or "")
        source_event_at = self._paper_state_event_at(event, status=status)
        if not record_id or not status or not source_event_id or not source_event_at:
            return
        self._conn.execute(
            f"""INSERT INTO {table}(
                {id_column},status,source_event_at,source_event_id,payload_json
            ) VALUES(?,?,?,?,?)
            ON CONFLICT({id_column}) DO UPDATE SET
                status=excluded.status,
                source_event_at=excluded.source_event_at,
                source_event_id=excluded.source_event_id,
                payload_json=excluded.payload_json
            WHERE excluded.source_event_at > {table}.source_event_at
               OR (
                    excluded.source_event_at = {table}.source_event_at
                    AND excluded.source_event_id > {table}.source_event_id
               )""",
            (
                record_id,
                status,
                source_event_at,
                source_event_id,
                self._json(payload),
            ),
        )

    @staticmethod
    def _paper_state_event_at(
        event: Mapping[str, Any],
        *,
        status: str,
    ) -> str:
        event_type = str(event.get("event_type") or "")
        if event_type == "nautilus_position":
            if status == PositionStatus.CLOSED.value:
                keys = ("closed_at", "ts", "created_at")
            elif status == PositionStatus.OPEN.value:
                keys = ("ts", "opened_at", "created_at")
            else:
                keys = ("ts", "created_at", "closed_at", "opened_at")
        else:
            keys = ("ts", "created_at")
        for key in keys:
            timestamp = _row_timestamp(event, key)
            if timestamp is not None:
                return utc_iso(timestamp)
        return ""

    def delete_paper_result_rows(
        self,
        paper_trade_id: str,
        publish_id: str | None,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM paper_trade_results WHERE paper_trade_id = ?",
                (paper_trade_id,),
            )
            if publish_id is not None:
                self._conn.execute(
                    "DELETE FROM telegram_publishes WHERE publish_id = ?",
                    (publish_id,),
                )

    def delete_daily_report_rows(
        self,
        report_id: str,
        publish_id: str | None,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM daily_reports WHERE report_id = ?",
                (report_id,),
            )
            if publish_id is not None:
                self._conn.execute(
                    "DELETE FROM telegram_publishes WHERE publish_id = ?",
                    (publish_id,),
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

    def storage_health(self) -> StorageHealthRead:
        try:
            return {
                "status": "ok",
                "reason": None,
                "freshness_age_sec": 0,
                "counts": self.counts(),
                "recent_system_events": self.recent_system_events(10),
                "latest_health_snapshot": self.latest_health_snapshot(),
            }
        except sqlite3.Error:
            return {
                "status": "degraded",
                "reason": "storage_unavailable",
                "freshness_age_sec": None,
                "counts": {},
                "recent_system_events": [],
                "latest_health_snapshot": None,
            }

    def recent_system_events(self, limit: int) -> list[dict[str, Any]]:
        return self.query_json(
            "system_events",
            where="ORDER BY created_at DESC, rowid DESC",
            limit=limit,
        )

    def latest_health_snapshot(self) -> dict[str, Any] | None:
        return self.restore_latest_system_event("health_snapshot")

    def strategy_status_rows(self, limit: int) -> list[dict[str, Any]]:
        return self.query_json(
            "strategy_status",
            where="ORDER BY created_at ASC",
            limit=limit,
        )

    def signal_rows(self, limit: int) -> list[dict[str, Any]]:
        return self.query_json(
            "signals",
            where="ORDER BY created_at DESC",
            limit=limit,
        )

    def rejected_signal_rows(self, limit: int) -> list[dict[str, Any]]:
        return self.query_json(
            "rejected_signals",
            where="ORDER BY rejected_at DESC",
            limit=limit,
        )

    def _paper_state_rows(
        self,
        table: str,
        status: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        clauses = [
            "COALESCE(json_extract(payload_json, '$._projection_invalid'), 0) != 1"
        ]
        params: tuple[str, ...] = ()
        if status:
            clauses.append("status=?")
            params = (status.upper(),)
        prefix = f"WHERE {' AND '.join(clauses)} "
        return self.query_json(
            table,
            where=f"{prefix}ORDER BY source_event_at DESC, source_event_id DESC",
            params=params,
            limit=limit,
        )

    def paper_order_rows(
        self,
        status: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        return self._paper_state_rows(
            "paper_order_states",
            status,
            limit,
        )

    def market_rows(self, limit: int) -> list[dict[str, Any]]:
        return self.query_json(
            "markets",
            where="ORDER BY updated_at DESC",
            limit=limit,
        )

    def paper_position_rows(
        self,
        status: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        return self._paper_state_rows(
            "paper_position_states",
            status,
            limit,
        )

    def paper_trade_result_rows(self, limit: int) -> list[dict[str, Any]]:
        return self.query_json("paper_trade_results", limit=limit)

    def daily_reports(self, limit: int) -> list[dict[str, Any]]:
        return self.restore_daily_reports(limit=limit)

    def strategy_leaderboard(self, limit: int) -> list[dict[str, Any]]:
        return self.restore_strategy_leaderboard(limit=limit)

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

    def restore_open_positions(self) -> list[dict[str, Any]]:
        return [
            row
            for row in self.paper_position_rows(PositionStatus.OPEN.value, 100_000)
            if _valid_position_event(row)
        ]

    def restore_closed_positions(self) -> list[dict[str, Any]]:
        return [
            row
            for row in self.paper_position_rows(PositionStatus.CLOSED.value, 100_000)
            if _valid_position_event(row)
        ]

    def restore_daily_reports(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.query_json(
            "daily_reports",
            where="ORDER BY report_date DESC, revision DESC, created_at DESC",
            limit=limit,
        )

    def restore_strategy_leaderboard(self, limit: int = 500) -> list[dict[str, Any]]:
        results = self.query_json(
            "paper_trade_results",
            where="ORDER BY closed_at DESC",
            limit=50_000,
        )
        return build_strategy_leaderboard_rows(results)[:limit]

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
