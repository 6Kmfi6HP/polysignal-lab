from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict

from pydantic import JsonValue

from polysignal_lab.config import Settings

JsonObject = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ReadonlySmokeRequest:
    settings: Settings
    config_path: Path
    evidence_path: Path | None
    base_dir: Path


@dataclass(frozen=True, slots=True)
class PublicEndpoint:
    url: str
    params: dict[str, str]


@dataclass(frozen=True, slots=True)
class SurfaceOutcome:
    status_code: int | None
    ok: bool
    record_count: int | None
    detail: str | None


@dataclass(frozen=True, slots=True)
class SurfacePayload:
    evidence: "SurfaceEvidence"
    payload: JsonValue | None


class SurfaceEvidence(TypedDict):
    method: Literal["GET"]
    url: str
    domain: str
    status_code: int | None
    ok: bool
    record_count: int | None
    detail: str | None


class SafetyEvidence(TypedDict):
    status: Literal["ok", "not_run"]
    ok: bool
    finding_count: int
    detail: str | None


class SchedulerSnapshotEvidence(TypedDict):
    status: Literal["created", "not_run"]
    created: bool
    market_count: int
    token_count: int
    snapshot_id: str | None
    detail: str | None


class HealthSnapshotEvidence(TypedDict):
    status: Literal["ok", "degraded", "down", "not_run"]
    generated_at: str | None
    components: list[JsonObject]


class DashboardEvidence(TypedDict):
    status: Literal["ok", "not_run"]
    ok: bool
    endpoint_count: int
    detail: str | None


class ReadonlySmokeEvidence(TypedDict):
    recorded_at: str
    mode: Literal["smoke"]
    bounded: bool
    once: bool
    network_calls: bool
    authenticated_endpoints: bool
    trading_actions: bool
    config_path: str
    app_name: str
    dashboard_read_only: bool
    public_surfaces_checked: list[str]
    passed: bool
    failure_count: int
    surfaces: dict[str, SurfaceEvidence]
    scheduler_snapshot: SchedulerSnapshotEvidence
    health_snapshot: HealthSnapshotEvidence
    dashboard_reads: DashboardEvidence
    safety_scan: SafetyEvidence
