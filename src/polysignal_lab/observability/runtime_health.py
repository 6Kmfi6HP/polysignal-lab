from __future__ import annotations

from contextlib import suppress
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import json
from pathlib import Path
from uuid import uuid4

from polysignal_lab.observability.health import HealthSnapshot


_GLOBAL_READINESS_KEY = "__global__"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _detail_counts_toward_readiness_miss(
    detail: dict[str, object] | None,
) -> bool:
    """Once-READY misses arm the 300s liveness clock; never-READY do not.

    Warmup ``awaiting_first_book`` / ``awaiting_instrument`` conditions stay
    visible in readiness detail for observation, but must not make Docker
    liveness unhealthy while global ``last_data_at`` is still advancing.
    Missing or legacy detail fails closed.
    """
    if detail is None:
        return True
    ever_at = detail.get("first_bilateral_book_ever_at")
    once_ready = isinstance(ever_at, str) and bool(ever_at)
    if once_ready:
        return True
    # A local refresh/reconnect replay boundary has been recorded but no valid
    # post-boundary book frame has arrived yet. Keep it observable, but do not
    # let the ordinary readiness-miss clock turn a recent replay into a liveness
    # failure before the book can converge.
    if detail.get("adapter_replay_unconfirmed") is True:
        return False
    state = detail.get("subscription_state")
    if state in {"awaiting_first_book", "awaiting_instrument"}:
        return False
    return True


@dataclass(frozen=True, slots=True)
class RuntimeHeartbeat:
    updated_at: str
    phase: str
    fatal: bool = False
    fatal_reason: str | None = None
    phase_started_at: str | None = None
    # Monotonic across market rotations: the last time ANY market data
    # arrived. Per-condition readiness resets every cycle, so it can never
    # show that the runtime has been receiving nothing at all.
    last_data_at: str | None = None
    readiness_miss_started_at_by_key: dict[str, str] = field(default_factory=dict)
    readiness_detail_by_key: dict[str, dict[str, object]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LivenessResult:
    ok: bool
    reason: str | None = None
    heartbeat_age_sec: int | None = None
    fatal_reason: str | None = None
    readiness_detail_by_key: dict[str, dict[str, object]] = field(default_factory=dict)


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


def _latest_book_timestamp(detail: dict[str, object] | None) -> str | None:
    """Newest `last_book_at_by_side` entry in a readiness detail payload."""
    if detail is None:
        return None
    sides = detail.get("last_book_at_by_side")
    if not isinstance(sides, dict):
        return None
    stamps = [value for value in sides.values() if isinstance(value, str) and value]
    return max(stamps) if stamps else None


def _advance_last_data_at(
    previous: str | None,
    detail: dict[str, object] | None,
) -> str | None:
    """Carry the data clock forward; a rotation must never wind it back."""
    latest = _latest_book_timestamp(detail)
    if latest is None:
        return previous
    if previous is None:
        return latest
    return max(previous, latest)


def write_runtime_heartbeat(
    path: Path,
    *,
    phase: str,
    fatal: bool = False,
    fatal_reason: str | None = None,
    readiness_key: str | None = None,
    readiness_ok: bool | None = None,
    readiness_detail: dict[str, object] | None = None,
    active_readiness_keys: frozenset[str] | None = None,
    now: datetime | None = None,
) -> RuntimeHeartbeat:
    timestamp = (now or _utc_now()).astimezone(UTC).isoformat()
    phase_started_at = timestamp
    previous = _read_runtime_heartbeat_optional(path)
    if previous is not None and previous.phase == phase:
        phase_started_at = previous.phase_started_at or previous.updated_at
    readiness_misses = (
        dict(previous.readiness_miss_started_at_by_key) if previous is not None else {}
    )
    readiness_details = (
        {key: dict(value) for key, value in previous.readiness_detail_by_key.items()}
        if previous is not None
        else {}
    )
    last_data_at = previous.last_data_at if previous is not None else None
    if phase in {"start", "starting"}:
        readiness_misses.clear()
        readiness_details.clear()
        # A restart has received nothing yet; the startup grace covers it.
        last_data_at = None
    elif readiness_key is not None:
        _ = readiness_misses.pop(_GLOBAL_READINESS_KEY, None)
        _ = readiness_details.pop(_GLOBAL_READINESS_KEY, None)
        if readiness_ok is True:
            _ = readiness_misses.pop(readiness_key, None)
            _ = readiness_details.pop(readiness_key, None)
        elif readiness_ok is False:
            if readiness_detail is not None:
                readiness_details[readiness_key] = dict(readiness_detail)
            detail_for_clock = (
                readiness_details.get(readiness_key)
                if readiness_detail is None
                else readiness_detail
            )
            if _detail_counts_toward_readiness_miss(detail_for_clock):
                _ = readiness_misses.setdefault(readiness_key, timestamp)
            else:
                _ = readiness_misses.pop(readiness_key, None)
    elif phase == "readiness_miss":
        _ = readiness_misses.setdefault(_GLOBAL_READINESS_KEY, timestamp)
    elif phase not in {"market_data_evaluation", "evaluation_heartbeat"}:
        _ = readiness_misses.pop(_GLOBAL_READINESS_KEY, None)
        _ = readiness_details.pop(_GLOBAL_READINESS_KEY, None)
    if active_readiness_keys is not None:
        keep = set(active_readiness_keys)
        for key in tuple(readiness_details):
            if key == _GLOBAL_READINESS_KEY:
                continue
            if key not in keep:
                _ = readiness_details.pop(key, None)
                _ = readiness_misses.pop(key, None)
        for key in tuple(readiness_misses):
            if key == _GLOBAL_READINESS_KEY:
                continue
            if key not in keep:
                _ = readiness_misses.pop(key, None)
    heartbeat = RuntimeHeartbeat(
        updated_at=timestamp,
        phase=phase,
        fatal=bool(fatal),
        fatal_reason=fatal_reason,
        phase_started_at=phase_started_at,
        last_data_at=_advance_last_data_at(last_data_at, readiness_detail),
        readiness_miss_started_at_by_key=readiness_misses,
        readiness_detail_by_key=readiness_details,
    )
    _write_json_atomically(path, asdict(heartbeat))
    return heartbeat


def write_runtime_startup_marker(
    path: Path, *, now: datetime | None = None
) -> datetime:
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

    last_data_at = payload.get("last_data_at")
    if last_data_at is not None and not isinstance(last_data_at, str):
        raise TypeError("heartbeat last_data_at must be a string or null")

    readiness_raw = payload.get("readiness_miss_started_at_by_key", {})
    if not isinstance(readiness_raw, dict):
        raise TypeError("heartbeat readiness misses must be a JSON object")
    readiness_misses: dict[str, str] = {}
    for key, value in readiness_raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise TypeError("heartbeat readiness miss entries must be strings")
        readiness_misses[key] = value
    readiness_detail_raw = payload.get("readiness_detail_by_key", {})
    if not isinstance(readiness_detail_raw, dict):
        raise TypeError("heartbeat readiness details must be a JSON object")
    readiness_details: dict[str, dict[str, object]] = {}
    for key, value in readiness_detail_raw.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            raise TypeError("heartbeat readiness detail entries must be objects")
        readiness_details[key] = dict(value)
    # Legacy heartbeats only had phase=readiness_miss. Do not invent a global
    # miss when modern payloads already carry per-condition detail without a
    # once-READY miss clock (never-READY warmup stays observational only).
    if (
        not readiness_misses
        and phase == "readiness_miss"
        and not readiness_details
    ):
        readiness_misses[_GLOBAL_READINESS_KEY] = phase_started_at

    return RuntimeHeartbeat(
        updated_at=updated_at,
        phase=phase,
        fatal=fatal,
        fatal_reason=fatal_reason,
        phase_started_at=phase_started_at,
        last_data_at=last_data_at,
        readiness_miss_started_at_by_key=readiness_misses,
        readiness_detail_by_key=readiness_details,
    )


def _read_runtime_heartbeat_optional(path: Path) -> RuntimeHeartbeat | None:
    try:
        return read_runtime_heartbeat(path)
    except (
        OSError,
        json.JSONDecodeError,
        KeyError,
        ValueError,
        TypeError,
        FileNotFoundError,
    ):
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


def _data_starvation_result(
    last_data_at: str | None,
    *,
    observed_at: datetime,
    max_data_starvation_sec: int | None,
    inside_startup_grace: bool,
    startup_started_at: datetime | None,
    readiness_details: dict[str, dict[str, object]],
    heartbeat_age_sec: int,
) -> LivenessResult | None:
    """Fail liveness when no market data has arrived for too long.

    A fresh heartbeat and churning readiness state say only that the process
    is running and re-subscribing. They stayed green through a six-day outage
    in which the runtime received no book updates at all, because rotation
    resets per-condition readiness before its window can elapse.
    """
    if max_data_starvation_sec is None or int(max_data_starvation_sec) <= 0:
        return None
    if inside_startup_grace:
        return None
    if last_data_at is None:
        # Never received data. Measure from process start, so "still booting"
        # is not confused with "never got anything"; with no startup marker
        # there is no anchor and the check cannot speak.
        if startup_started_at is None:
            return None
        since = startup_started_at.astimezone(UTC)
    else:
        try:
            since = datetime.fromisoformat(last_data_at).astimezone(UTC)
        except ValueError:
            return LivenessResult(ok=False, reason="heartbeat_unreadable")
    starved_sec = int((observed_at - since).total_seconds())
    if starved_sec <= int(max_data_starvation_sec):
        return None
    return LivenessResult(
        ok=False,
        reason="data_starvation",
        heartbeat_age_sec=heartbeat_age_sec,
        readiness_detail_by_key=readiness_details,
    )


def evaluate_liveness(
    path: Path,
    *,
    max_age_sec: int,
    startup_started_at: datetime | None = None,
    startup_grace_sec: int = 0,
    max_readiness_miss_sec: int | None = None,
    max_data_starvation_sec: int | None = None,
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
        readiness_details = dict(heartbeat.readiness_detail_by_key)
        readiness_started_at = tuple(
            datetime.fromisoformat(value).astimezone(UTC)
            for key, value in heartbeat.readiness_miss_started_at_by_key.items()
            if _detail_counts_toward_readiness_miss(readiness_details.get(key))
        )
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
            readiness_detail_by_key=readiness_details,
        )

    age = max(0, int((observed_at - updated_at).total_seconds()))
    if age > int(max_age_sec):
        if inside_startup_grace:
            return LivenessResult(
                ok=True,
                heartbeat_age_sec=age,
                readiness_detail_by_key=readiness_details,
            )
        return LivenessResult(
            ok=False,
            reason="heartbeat_stale",
            heartbeat_age_sec=age,
            readiness_detail_by_key=readiness_details,
        )

    starvation = _data_starvation_result(
        heartbeat.last_data_at,
        observed_at=observed_at,
        max_data_starvation_sec=max_data_starvation_sec,
        inside_startup_grace=inside_startup_grace,
        startup_started_at=startup_started_at,
        readiness_details=readiness_details,
        heartbeat_age_sec=age,
    )
    if starvation is not None:
        return starvation

    if (
        max_readiness_miss_sec is not None
        and int(max_readiness_miss_sec) > 0
        and readiness_started_at
        and not inside_startup_grace
    ):
        readiness_age = max(
            max(
                0,
                int((observed_at - started_at).total_seconds()),
            )
            for started_at in readiness_started_at
        )
        if readiness_age > int(max_readiness_miss_sec):
            return LivenessResult(
                ok=False,
                reason="readiness_miss",
                heartbeat_age_sec=age,
                readiness_detail_by_key=readiness_details,
            )

    return LivenessResult(
        ok=True,
        heartbeat_age_sec=age,
        readiness_detail_by_key=readiness_details,
    )


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
    consecutive = (
        (previous.consecutive_failures + 1) if same_down_set and previous else 1
    )
    duration = max(0, int((observed_at - _parse_iso(first_down_at)).total_seconds()))
    recommended = duration >= int(critical_down_sec) and consecutive >= int(
        min_consecutive_failures
    )
    return RestartGateResult(
        restart_recommended=recommended,
        reason="critical_components_down" if recommended else None,
        critical_down_components=down,
        first_down_at=first_down_at,
        down_duration_sec=duration,
        consecutive_failures=consecutive,
    )
