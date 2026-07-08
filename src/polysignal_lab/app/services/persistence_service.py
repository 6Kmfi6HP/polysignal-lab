"""
Input: __future__, __future__.annotations, datetime, datetime.UTC, datetime.datetime, typing, typing.Any, typing.Iterable, polysignal_lab.storage.jsonl_store, polysignal_lab.storage.jsonl_store.JSONLStore
Output: PersistenceService
Pos: Service Layer - Business logic

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable

from polysignal_lab.storage.jsonl_store import JSONLStore
from polysignal_lab.storage.sqlite_store import SQLiteStore
from polysignal_lab.storage.state_store import StateStore


class PersistenceService:
    name = "persistence"

    def __init__(self, logs: JSONLStore, sqlite: SQLiteStore, state: StateStore) -> None:
        self.logs = logs
        self.sqlite = sqlite
        self.state = state

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        self.close()

    def health(self) -> dict[str, object]:
        return {"name": self.name, "status": "ok", "metrics": self.counts()}

    def append_log(self, stream: str, payload: Any) -> None:
        self.logs.append(stream, payload)

    def counts(self) -> dict[str, int]:
        return self.sqlite.counts()

    def upsert_market(self, market: Any) -> None:
        self.sqlite.upsert_market(market)

    def insert_signal(self, signal: Any) -> None:
        self.sqlite.insert_signal(signal)

    def insert_rejected_signal(self, rejected: Any) -> None:
        self.sqlite.insert_rejected_signal(rejected)

    def insert_strategy_status(self, status: Any) -> None:
        self.sqlite.insert_strategy_status(status)

    def upsert_paper_order(self, order: Any) -> None:
        self.sqlite.upsert_paper_order(order)

    def upsert_paper_position(self, position: Any) -> None:
        self.sqlite.upsert_paper_position(position)

    def insert_paper_trade_result(self, result: Any) -> None:
        self.sqlite.insert_paper_trade_result(result)

    def insert_daily_report(self, report: Any) -> None:
        self.sqlite.insert_daily_report(report)

    def insert_telegram_publish(self, publish: dict[str, Any]) -> None:
        self.sqlite.insert_telegram_publish(publish)

    def insert_system_event(self, event: dict[str, Any]) -> None:
        self.sqlite.insert_system_event(event)

    def query_json(
        self,
        table: str,
        limit: int = 100,
        where: str = "",
        params: Iterable[Any] = (),
    ) -> list[dict[str, Any]]:
        return self.sqlite.query_json(table, limit=limit, where=where, params=params)

    def restore_latest_wallet_snapshot(self) -> dict[str, Any] | None:
        return self.sqlite.restore_latest_wallet_snapshot()

    def restore_open_positions(self) -> list[dict[str, Any]]:
        return self.sqlite.restore_open_positions()

    def restore_daily_reports(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.sqlite.restore_daily_reports(limit=limit)

    def restore_closed_trade_results(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50_000,
    ) -> list[dict[str, Any]]:
        where_parts: list[str] = []
        params: list[Any] = []
        if since is not None:
            where_parts.append("closed_at >= ?")
            params.append(_closed_at_bound(since))
        if until is not None:
            where_parts.append("closed_at < ?")
            params.append(_closed_at_bound(until))
        where = ""
        if where_parts:
            where = "WHERE " + " AND ".join(where_parts)
        where = f"{where} ORDER BY closed_at DESC".strip()
        return self.sqlite.query_json("paper_trade_results", where=where, params=tuple(params), limit=limit)

    def restore_latest_system_event(self, event_type: str) -> dict[str, Any] | None:
        return self.sqlite.restore_latest_system_event(event_type)

    def read_state(self, name: str, default: Any = None) -> Any:
        return self.state.read(name, default=default)

    def write_state(self, name: str, value: Any) -> None:
        self.state.write(name, value)

    def persist_state(
        self,
        *,
        wallet_snapshot: Any,
        open_positions: list[dict[str, Any]],
        market_cache: list[dict[str, Any]],
        signal_dedupe: Any,
    ) -> None:
        self.append_log("paper_wallet_snapshots", wallet_snapshot)
        self.insert_wallet_snapshot(wallet_snapshot)
        self.write_state("paper_wallet", wallet_snapshot)
        self.write_state("open_positions", open_positions)
        self.write_state("market_cache", market_cache)
        self.write_state("signal_dedupe", signal_dedupe)

    def delete_paper_result_rows(
        self, paper_trade_id: str, publish_id: str | None
    ) -> None:
        with self.sqlite._lock, self.sqlite._conn:
            self.sqlite._conn.execute(
                "DELETE FROM paper_trade_results WHERE paper_trade_id = ?",
                (paper_trade_id,),
            )
            if publish_id is not None:
                self.sqlite._conn.execute(
                    "DELETE FROM telegram_publishes WHERE publish_id = ?",
                    (publish_id,),
                )

    def delete_daily_report_rows(
        self, report_id: str, publish_id: str | None
    ) -> None:
        with self.sqlite._lock, self.sqlite._conn:
            self.sqlite._conn.execute(
                "DELETE FROM daily_reports WHERE report_id = ?",
                (report_id,),
            )
            if publish_id is not None:
                self.sqlite._conn.execute(
                    "DELETE FROM telegram_publishes WHERE publish_id = ?",
                    (publish_id,),
                )

    def close(self) -> None:
        self.sqlite.close()


def _closed_at_bound(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
