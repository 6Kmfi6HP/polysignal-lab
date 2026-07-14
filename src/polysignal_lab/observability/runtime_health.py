"""
Input: __future__, __future__.annotations, contextlib, contextlib.suppress, dataclasses, dataclasses.asdict, dataclasses.dataclass, datetime, datetime.UTC, datetime.datetime
Output: write_runtime_heartbeat, write_runtime_startup_marker, read_runtime_startup_started_at, read_runtime_heartbeat, evaluate_liveness, evaluate_restart_gate, RuntimeHeartbeat, LivenessResult, RestartGateResult
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from uuid import uuid4

from polysignal_lab.observability.health import HealthSnapshot


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class RuntimeHeartbeat:
    updated_at: str
    phase: str
    fatal: bool = False
    fatal_reason: str | None = None
    phase_started_at: str | None = None


@dataclass(frozen=True, slots=True)
class LivenessResult:
    ok: bool
    reason: str | None = None
    heartbeat_age_sec: int | None = None
    fatal_reason: str | None = None


@dataclass(frozen=True, slots=True)
class RestartGateResult:
    restart_recommended: bool
    reason: str | None = None
    critical_down_components: tuple[str, ...] = ()
    first_down_at: str | None = None
    down_duration_sec: int = 0
    consecutive_failures: int = 0

def _write_json_atomically(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    finally:
        with suppress(FileNotFoundError):
            tmp.unlink()



def write_runtime_heartbeat(
    path: Path,
    *,
    phase: str,
    fatal: bool = False,
    fatal_reason: str | None = None,
    now: datetime | None = None,
) -> RuntimeHeartbeat:
    timestamp = (now or _utc_now()).astimezone(UTC).isoformat()
    phase_started_at = timestamp
    previous = _read_runtime_heartbeat_optional(path)
    if previous is not None and previous.phase == phase:
        phase_started_at = previous.phase_started_at or previous.updated_at
    heartbeat = RuntimeHeartbeat(
        updated_at=timestamp,
        phase=phase,
        fatal=bool(fatal),
        fatal_reason=fatal_reason,
        phase_started_at=phase_started_at,
    )
    _write_json_atomically(path, asdict(heartbeat))
    return heartbeat


def write_runtime_startup_marker(path: Path, *, now: datetime | None = None) -> datetime:
    started_at = (now or _utc_now()).astimezone(UTC)
    _write_json_atomically(path, {"started_at": started_at.isoformat()})
    return started_at


def read_runtime_startup_started_at(path: Path) -> datetime:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("startup marker payload must be a JSON object")
    started_at = payload["started_at"]
    if not isinstance(started_at, str):
        raise TypeError("startup marker started_at must be a string")
    return datetime.fromisoformat(started_at).astimezone(UTC)


def read_runtime_heartbeat(path: Path) -> RuntimeHeartbeat:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("heartbeat payload must be a JSON object")

    updated_at = payload["updated_at"]
    if not isinstance(updated_at, str):
        raise TypeError("heartbeat updated_at must be a string")

    phase = payload["phase"]
    if not isinstance(phase, str):
        raise TypeError("heartbeat phase must be a string")

    fatal = payload.get("fatal", False)
    if not isinstance(fatal, bool):
        raise TypeError("heartbeat fatal must be a bool")

    fatal_reason = payload.get("fatal_reason")
    if fatal_reason is not None and not isinstance(fatal_reason, str):
        raise TypeError("heartbeat fatal_reason must be a string or null")

    phase_started_at = payload.get("phase_started_at")
    if phase_started_at is not None and not isinstance(phase_started_at, str):
        raise TypeError("heartbeat phase_started_at must be a string or null")
    if phase_started_at is None:
        phase_started_at = updated_at

    return RuntimeHeartbeat(
        updated_at=updated_at,
        phase=phase,
        fatal=fatal,
        fatal_reason=fatal_reason,
        phase_started_at=phase_started_at,
    )


def _read_runtime_heartbeat_optional(path: Path) -> RuntimeHeartbeat | None:
    try:
        return read_runtime_heartbeat(path)
    except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError, FileNotFoundError):
        return None


def _inside_startup_grace(
    observed_at: datetime,
    *,
    startup_started_at: datetime | None,
    startup_grace_sec: int,
) -> bool:
    if startup_started_at is None or int(startup_grace_sec) <= 0:
        return False
    elapsed = max(
        0,
        int((observed_at - startup_started_at.astimezone(UTC)).total_seconds()),
    )
    return elapsed <= int(startup_grace_sec)



def evaluate_liveness(
    path: Path,
    *,
    max_age_sec: int,
    startup_started_at: datetime | None = None,
    startup_grace_sec: int = 0,
    max_readiness_miss_sec: int | None = None,
    now: datetime | None = None,
) -> LivenessResult:
    observed_at = (now or _utc_now()).astimezone(UTC)
    inside_startup_grace = _inside_startup_grace(
        observed_at,
        startup_started_at=startup_started_at,
        startup_grace_sec=startup_grace_sec,
    )
    try:
        heartbeat = read_runtime_heartbeat(path)
        updated_at = datetime.fromisoformat(heartbeat.updated_at).astimezone(UTC)
    except FileNotFoundError:
        if inside_startup_grace:
            return LivenessResult(ok=True)
        return LivenessResult(ok=False, reason="heartbeat_missing")
    except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError):
        return LivenessResult(ok=False, reason="heartbeat_unreadable")

    if heartbeat.fatal:
        return LivenessResult(
            ok=False,
            reason="fatal",
            fatal_reason=heartbeat.fatal_reason,
        )

    age = max(0, int((observed_at - updated_at).total_seconds()))
    if age > int(max_age_sec):
        if inside_startup_grace:
            return LivenessResult(ok=True, heartbeat_age_sec=age)
        return LivenessResult(
            ok=False,
            reason="heartbeat_stale",
            heartbeat_age_sec=age,
        )

    if (
        max_readiness_miss_sec is not None
        and int(max_readiness_miss_sec) > 0
        and heartbeat.phase == "readiness_miss"
        and not inside_startup_grace
    ):
        started_raw = heartbeat.phase_started_at or heartbeat.updated_at
        phase_started = datetime.fromisoformat(started_raw).astimezone(UTC)
        phase_age = max(0, int((observed_at - phase_started).total_seconds()))
        if phase_age > int(max_readiness_miss_sec):
            return LivenessResult(
                ok=False,
                reason="readiness_miss",
                heartbeat_age_sec=age,
            )

    return LivenessResult(ok=True, heartbeat_age_sec=age)


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def evaluate_restart_gate(
    snapshot: HealthSnapshot,
    *,
    critical_components: tuple[str, ...],
    critical_down_sec: int,
    min_consecutive_failures: int,
    previous: RestartGateResult | None = None,
    now: datetime | None = None,
) -> RestartGateResult:
    critical = set(critical_components)
    down = tuple(
        component.name
        for component in snapshot.components
        if component.name in critical and component.status == "down"
    )
    if not down:
        return RestartGateResult(restart_recommended=False)

    observed_at = (now or _utc_now()).astimezone(UTC)
    same_down_set = previous is not None and previous.critical_down_components == down
    first_down_at = (
        previous.first_down_at
        if same_down_set and previous.first_down_at is not None
        else observed_at.isoformat()
    )
    consecutive = (previous.consecutive_failures + 1) if same_down_set and previous else 1
    duration = max(0, int((observed_at - _parse_iso(first_down_at)).total_seconds()))
    recommended = (
        duration >= int(critical_down_sec)
        and consecutive >= int(min_consecutive_failures)
    )
    return RestartGateResult(
        restart_recommended=recommended,
        reason="critical_components_down" if recommended else None,
        critical_down_components=down,
        first_down_at=first_down_at,
        down_duration_sec=duration,
        consecutive_failures=consecutive,
    )
