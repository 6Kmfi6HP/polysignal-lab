"""
Input: __future__, dataclasses, datetime, pathlib, typing, polysignal_lab.observability.runtime_health
Output: JsonRow, StorageHealthRead, RuntimeHealthRead, ReportingReadPort, RuntimeHealthPort, FileRuntimeHealthReader
Pos: Dashboard read boundary

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol, TypeAlias, TypedDict

from polysignal_lab.observability.runtime_health import evaluate_liveness

JsonRow: TypeAlias = dict[str, Any]


class StorageHealthRead(TypedDict):
    status: Literal["ok", "degraded"]
    reason: str | None
    freshness_age_sec: int | None
    counts: dict[str, int]
    recent_system_events: list[JsonRow]
    latest_health_snapshot: JsonRow | None


class RuntimeHealthRead(TypedDict):
    status: Literal["ok", "degraded", "unknown"]
    reason: str | None
    freshness_age_sec: int | None
    fatal_reason: str | None
    readiness_detail_by_key: dict[str, dict[str, object]]


class ReportingReadPort(Protocol):
    def storage_health(self) -> StorageHealthRead: ...

    def counts(self) -> dict[str, int]: ...

    def strategy_status_rows(self, limit: int) -> list[JsonRow]: ...

    def daily_reports(self, limit: int) -> list[JsonRow]: ...

    def signal_rows(self, limit: int) -> list[JsonRow]: ...

    def rejected_signal_rows(self, limit: int) -> list[JsonRow]: ...

    def report_order_rows(
        self,
        status: str | None,
        limit: int,
    ) -> list[JsonRow]: ...

    def market_rows(self, limit: int) -> list[JsonRow]: ...

    def report_position_rows(
        self,
        status: str | None,
        limit: int,
    ) -> list[JsonRow]: ...

    def report_result_rows(self, limit: int) -> list[JsonRow]: ...

    def strategy_leaderboard(self, limit: int) -> list[JsonRow]: ...


class RuntimeHealthPort(Protocol):
    def read(self) -> RuntimeHealthRead: ...


@dataclass(frozen=True, slots=True)
class FileRuntimeHealthReader:
    path: Path
    max_age_sec: int
    max_readiness_miss_sec: int | None = None
    now: datetime | None = None

    def read(self) -> RuntimeHealthRead:
        result = evaluate_liveness(
            self.path,
            max_age_sec=self.max_age_sec,
            max_readiness_miss_sec=self.max_readiness_miss_sec,
            now=self.now,
        )
        if result.ok:
            status: Literal["ok", "degraded", "unknown"] = "ok"
        elif result.reason in {"heartbeat_missing", "heartbeat_unreadable"}:
            status = "unknown"
        else:
            status = "degraded"
        return {
            "status": status,
            "reason": result.reason,
            "freshness_age_sec": result.heartbeat_age_sec,
            "fatal_reason": result.fatal_reason,
            "readiness_detail_by_key": result.readiness_detail_by_key,
        }
