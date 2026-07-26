from __future__ import annotations

from datetime import datetime, timedelta, timezone

from polysignal_lab.observability.liveness_alert import (
    AlertState,
    evaluate_liveness_alert,
)
from polysignal_lab.observability.runtime_health import LivenessResult

UTC = timezone.utc
T0 = datetime(2026, 7, 27, 0, 0, 0, tzinfo=UTC)

# Deliberately wider than the runtime default (60s) so the sustain window is
# visible in the poll sequences below.
GATE = {"min_unhealthy_sec": 300, "min_consecutive_failures": 3}


def _miss(detail: dict[str, dict[str, object]] | None = None) -> LivenessResult:
    return LivenessResult(
        ok=False,
        reason="readiness_miss",
        heartbeat_age_sec=2,
        readiness_detail_by_key=detail or {"cond-1": {"asset": "SOL"}},
    )


_OK = LivenessResult(ok=True)


def _run(
    results: list[tuple[LivenessResult, datetime]],
    state: AlertState | None = None,
) -> tuple[AlertState, list[str]]:
    """Feed a poll sequence through the gate, collecting messages sent."""
    current = state or AlertState()
    sent: list[str] = []
    for liveness, now in results:
        decision = evaluate_liveness_alert(liveness, previous=current, now=now, **GATE)
        current = decision.state
        if decision.message is not None:
            sent.append(decision.message)
    return current, sent


def test_healthy_runtime_never_alerts() -> None:
    _, sent = _run([(_OK, T0 + timedelta(seconds=i * 60)) for i in range(20)])

    assert sent == []


def test_brief_blip_does_not_alert() -> None:
    """A miss that clears inside the window must stay silent — no pager noise."""
    _, sent = _run(
        [
            (_miss(), T0),
            (_miss(), T0 + timedelta(seconds=60)),
            (_OK, T0 + timedelta(seconds=120)),
        ]
    )

    assert sent == []


def test_sustained_failure_alerts_once() -> None:
    """
    User symptom: the container sat unhealthy on readiness_miss for six days
    and nothing ever told them. A failure that outlives the window must
    produce exactly one alert, not one per poll.
    """
    polls = [(_miss(), T0 + timedelta(seconds=i * 60)) for i in range(20)]

    state, sent = _run(polls)

    assert len(sent) == 1
    assert "readiness_miss" in sent[0]
    assert state.notified is True


def test_alert_names_the_stuck_conditions() -> None:
    _, sent = _run(
        [
            (_miss({"cond-abc": {"asset": "SOL", "timeframe": "15m"}}), T0),
            (
                _miss({"cond-abc": {"asset": "SOL", "timeframe": "15m"}}),
                T0 + timedelta(seconds=200),
            ),
            (
                _miss({"cond-abc": {"asset": "SOL", "timeframe": "15m"}}),
                T0 + timedelta(seconds=400),
            ),
        ]
    )

    assert "cond-abc" in sent[0]


def test_recovery_after_alert_is_announced() -> None:
    """Silence after an alert is ambiguous; recovery must close the loop."""
    polls = [(_miss(), T0 + timedelta(seconds=i * 120)) for i in range(5)]
    polls.append((_OK, T0 + timedelta(seconds=900)))

    state, sent = _run(polls)

    assert len(sent) == 2
    assert "recovered" in sent[1].lower()
    assert state.notified is False


def test_recovery_without_a_prior_alert_stays_silent() -> None:
    _, sent = _run([(_miss(), T0), (_OK, T0 + timedelta(seconds=30))])

    assert sent == []


def test_duration_alone_is_not_enough() -> None:
    """One poll after a long gap could be a clock jump, not a sustained fault."""
    _, sent = _run([(_miss(), T0), (_miss(), T0 + timedelta(seconds=3600))])

    assert sent == []


def test_new_failure_after_recovery_alerts_again() -> None:
    polls = [(_miss(), T0 + timedelta(seconds=i * 120)) for i in range(5)]
    polls.append((_OK, T0 + timedelta(seconds=900)))
    polls.extend((_miss(), T0 + timedelta(seconds=1000 + i * 120)) for i in range(5))

    _, sent = _run(polls)

    assert len(sent) == 3
    assert "recovered" in sent[1].lower()


def test_fatal_phase_alerts_immediately() -> None:
    """A fatal runtime is not a flap; waiting out the window helps nobody."""
    fatal = LivenessResult(ok=False, reason="fatal", fatal_reason="boom")

    _, sent = _run([(fatal, T0)])

    assert len(sent) == 1
    assert "boom" in sent[0]
