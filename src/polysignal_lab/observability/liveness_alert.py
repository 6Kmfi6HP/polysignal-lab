from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from polysignal_lab.observability.runtime_health import LivenessResult

# Alert bodies are short on purpose: they land on a phone, and the detail
# lives in logs/runtime once the alert has pointed at the right minute.
_MAX_CONDITIONS_IN_MESSAGE = 5


@dataclass(frozen=True, slots=True)
class AlertState:
    """Carried between polls; the watchdog owns no other memory."""

    unhealthy_since: datetime | None = None
    consecutive_failures: int = 0
    notified: bool = False


@dataclass(frozen=True, slots=True)
class AlertDecision:
    state: AlertState
    message: str | None = None


def _describe_conditions(liveness: LivenessResult) -> str:
    keys = sorted(liveness.readiness_detail_by_key)
    if not keys:
        return ""
    shown = keys[:_MAX_CONDITIONS_IN_MESSAGE]
    suffix = f" (+{len(keys) - len(shown)} more)" if len(keys) > len(shown) else ""
    return f"\nStuck conditions: {', '.join(shown)}{suffix}"


def _alert_message(liveness: LivenessResult, unhealthy_sec: int) -> str:
    if liveness.fatal_reason:
        return f"🚨 Nautilus runtime FATAL — {liveness.fatal_reason}"
    minutes = unhealthy_sec // 60
    return (
        f"🚨 Nautilus runtime unhealthy for {minutes}m — "
        f"reason={liveness.reason}{_describe_conditions(liveness)}"
    )


def evaluate_liveness_alert(
    liveness: LivenessResult,
    *,
    previous: AlertState,
    min_unhealthy_sec: int,
    min_consecutive_failures: int,
    now: datetime,
) -> AlertDecision:
    """Decide whether a liveness poll warrants a notification.

    Mirrors `evaluate_restart_gate`: a failure must both persist for
    `min_unhealthy_sec` and be seen `min_consecutive_failures` times, so a
    single stale read or a brief flap never pages anyone. Alerts fire once per
    episode; recovery is announced only if the failure was announced.

    A fatal runtime bypasses the window — it will not recover on its own.
    """
    if liveness.ok:
        message = "✅ Nautilus runtime recovered" if previous.notified else None
        return AlertDecision(state=AlertState(), message=message)

    since = previous.unhealthy_since or now
    failures = previous.consecutive_failures + 1
    unhealthy_sec = max(0, int((now - since).total_seconds()))
    state = AlertState(
        unhealthy_since=since,
        consecutive_failures=failures,
        notified=previous.notified,
    )

    if previous.notified:
        return AlertDecision(state=state)

    fatal = liveness.fatal_reason is not None
    sustained = (
        unhealthy_sec >= min_unhealthy_sec and failures >= min_consecutive_failures
    )
    if not (fatal or sustained):
        return AlertDecision(state=state)

    notified_state = AlertState(
        unhealthy_since=since,
        consecutive_failures=failures,
        notified=True,
    )
    return AlertDecision(
        state=notified_state,
        message=_alert_message(liveness, unhealthy_sec),
    )
