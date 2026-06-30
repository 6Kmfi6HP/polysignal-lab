from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
from pathlib import Path

from polysignal_lab.observability.health import HealthSnapshot


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class RuntimeHeartbeat:
    updated_at: str
    phase: str
    fatal: bool = False
    fatal_reason: str | None = None


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


def write_runtime_heartbeat(
    path: Path,
    *,
    phase: str,
    fatal: bool = False,
    fatal_reason: str | None = None,
    now: datetime | None = None,
) -> RuntimeHeartbeat:
    timestamp = (now or _utc_now()).astimezone(UTC).isoformat()
    heartbeat = RuntimeHeartbeat(
        updated_at=timestamp,
        phase=phase,
        fatal=bool(fatal),
        fatal_reason=fatal_reason,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(heartbeat), sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    return heartbeat


def read_runtime_heartbeat(path: Path) -> RuntimeHeartbeat:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return RuntimeHeartbeat(
        updated_at=str(payload["updated_at"]),
        phase=str(payload["phase"]),
        fatal=bool(payload.get("fatal", False)),
        fatal_reason=(
            str(payload["fatal_reason"])
            if payload.get("fatal_reason") is not None
            else None
        ),
    )


def evaluate_liveness(
    path: Path,
    *,
    max_age_sec: int,
    now: datetime | None = None,
) -> LivenessResult:
    try:
        heartbeat = read_runtime_heartbeat(path)
    except FileNotFoundError:
        return LivenessResult(ok=False, reason="heartbeat_missing")
    except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError):
        return LivenessResult(ok=False, reason="heartbeat_unreadable")

    if heartbeat.fatal:
        return LivenessResult(
            ok=False,
            reason="fatal",
            fatal_reason=heartbeat.fatal_reason,
        )

    observed_at = (now or _utc_now()).astimezone(UTC)
    updated_at = datetime.fromisoformat(heartbeat.updated_at).astimezone(UTC)
    age = max(0, int((observed_at - updated_at).total_seconds()))
    if age > int(max_age_sec):
        return LivenessResult(
            ok=False,
            reason="heartbeat_stale",
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
