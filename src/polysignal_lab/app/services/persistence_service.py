"""
Input: __future__, __future__.annotations, dataclasses, dataclasses.dataclass, datetime, datetime.UTC, datetime.datetime, typing, typing.Any, typing.Final
Output: telemetry_retention_policy, TelemetryRetentionPolicy, PersistenceService
Pos: Service Layer - Business logic

🔄 Self-reference: When this file changes, update this header
"""









from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Iterable

from polysignal_lab.domain.reporting_result import DailyReport
from polysignal_lab.storage.jsonl_store import JSONLStore
from polysignal_lab.storage.sqlite_store import (
    DailyReportPublishAuthorization,
    SQLiteStore,
)
from polysignal_lab.storage.state_store import StateStore


@dataclass(frozen=True, slots=True)
class TelemetryRetentionPolicy:
    sqlite_keep_latest: int
    prune_every: int
    append_jsonl: bool


_BEST_EFFORT_RETENTION_POLICIES: Final = {
    "nautilus_decision": TelemetryRetentionPolicy(10_000, 100, False),
    "nautilus_fill": TelemetryRetentionPolicy(10_000, 100, False),
    "health_snapshot": TelemetryRetentionPolicy(256, 32, False),
}


def telemetry_retention_policy(
    event_type: str,
) -> TelemetryRetentionPolicy | None:
    return _BEST_EFFORT_RETENTION_POLICIES.get(event_type)


class PersistenceService:
    name = "persistence"

    def __init__(self, logs: JSONLStore, sqlite: SQLiteStore, state: StateStore) -> None:
        self.logs = logs
        self.sqlite = sqlite
        self.state = state
        self._telemetry_writes: dict[str, int] = {}

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

    def insert_report_result(self, result: Any) -> bool:
        return self.sqlite.insert_report_result(result)

    def insert_report_account_snapshot(self, snapshot: Any) -> None:
        self.sqlite.insert_report_account_snapshot(snapshot)

    def insert_daily_report(self, report: Any) -> None:
        self.sqlite.insert_daily_report(report)

    def claim_daily_report(
        self,
        report: DailyReport,
        *,
        enqueue_publish: bool,
    ) -> tuple[DailyReport, bool]:
        return self.sqlite.claim_daily_report(
            report,
            enqueue_publish=enqueue_publish,
        )

    def pending_daily_report_publishes(
        self,
        *,
        before_date: str,
        limit: int = 100,
    ) -> list[DailyReport]:
        return self.sqlite.pending_daily_report_publishes(
            before_date=before_date,
            limit=limit,
        )

    def claim_daily_report_publish(
        self,
        report_id: str,
        *,
        lease_sec: float,
    ) -> dict[str, Any] | None:
        return self.sqlite.claim_daily_report_publish(
            report_id,
            lease_sec=lease_sec,
        )

    def authorize_daily_report_publish(
        self,
        intent_id: str,
        attempt_count: int,
        *,
        lease_sec: float,
    ) -> DailyReportPublishAuthorization:
        return self.sqlite.authorize_daily_report_publish(
            intent_id,
            attempt_count,
            lease_sec=lease_sec,
        )

    def complete_daily_report_publish(
        self,
        intent_id: str,
        attempt_count: int,
        publish: dict[str, Any],
    ) -> dict[str, Any] | None:
        return self.sqlite.complete_daily_report_publish(
            intent_id,
            attempt_count,
            publish,
        )

    def insert_telegram_publish(self, publish: dict[str, Any]) -> None:
        self.sqlite.insert_telegram_publish(publish)

    def insert_system_event(self, event: dict[str, Any]) -> None:
        self.sqlite.insert_system_event(event)
        event_type = str(event.get("event_type") or "")
        policy = telemetry_retention_policy(event_type)
        if policy is None:
            return
        writes = self._telemetry_writes.get(event_type, 0) + 1
        self._telemetry_writes[event_type] = writes
        if writes % policy.prune_every == 0:
            self.prune_system_events(
                event_type,
                keep_latest=policy.sqlite_keep_latest,
            )

    def prune_system_events(
        self,
        event_type: str,
        *,
        keep_latest: int,
    ) -> int:
        return self.sqlite.prune_system_events(
            event_type,
            keep_latest=keep_latest,
        )

    def query_json(
        self,
        table: str,
        limit: int = 100,
        where: str = "",
        params: Iterable[Any] = (),
    ) -> list[dict[str, Any]]:
        return self.sqlite.query_json(table, limit=limit, where=where, params=params)

    def query_latest_report_account_snapshot(self) -> dict[str, Any] | None:
        return self.sqlite.query_latest_report_account_snapshot()

    def query_report_open_positions(self) -> list[dict[str, Any]]:
        return self.sqlite.query_report_open_positions()

    def query_report_closed_positions(self) -> list[dict[str, Any]]:
        return self.sqlite.query_report_closed_positions()

    def query_daily_reports(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.sqlite.daily_reports(limit=limit)

    def query_closed_trade_results(
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
        return self.sqlite.query_json(
            "report_results",
            where=where,
            params=tuple(params),
            limit=limit,
        )

    def query_latest_system_event(self, event_type: str) -> dict[str, Any] | None:
        return self.sqlite.query_latest_system_event(event_type)

    def read_state(self, name: str, default: Any = None) -> Any:
        return self.state.read(name, default=default)

    def write_state(self, name: str, value: Any) -> None:
        self.state.write(name, value)

    def delete_report_result_rows(
        self, report_result_id: str, publish_id: str | None
    ) -> None:
        self.sqlite.delete_report_result_rows(report_result_id, publish_id)

    def delete_daily_report_rows(
        self, report_id: str, publish_id: str | None
    ) -> None:
        self.sqlite.delete_daily_report_rows(report_id, publish_id)

    def close(self) -> None:
        self.sqlite.close()


def _closed_at_bound(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
