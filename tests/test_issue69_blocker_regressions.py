from __future__ import annotations

# Regression tests for the issue #69 fix. Each test here was red against PR #82's
# initial commit and encodes a concrete requirement the prior review found broken:
#  - B1: adapter_replay_started_at must serialize to ISO-8601 in the heartbeat
#    payload (a raw datetime crashes json.dumps on the write path).
#  - B2: the replay exemption must be *bounded* - a once-READY condition that
#    re-waits after a reconnect gets a grace window, but a stuck condition is
#    still supervised by the readiness-miss clock; the same predicate bounds the
#    fleet restart skip. The marker timestamp must never be extended by retries.
#  - B3: async orchestration must not call run() on a PyO3 LiveNode from a worker
#    thread (unsendable panic); it fails fast with a clear error.
# The monitor (B4) has its own tests in test_issue69_monitor.py.

import json
from datetime import UTC, datetime, timedelta
import tempfile
from pathlib import Path

from polysignal_lab.domain.enums import Side
from polysignal_lab.observability.runtime_health import (
    REPLAY_GRACE_SEC,
    evaluate_liveness,
    write_runtime_heartbeat,
    _detail_counts_toward_readiness_miss,
)
from polysignal_lab.nautilus_runtime.strategy.readiness import _adapter_replay_detail
from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
    MarketSubscriptionState,
    _clear_global_book_recovery_state,
    _mark_replay_unconfirmed,
    begin_market_book_generation,
)

T0 = datetime(2026, 8, 16, 6, 0, 0, tzinfo=UTC)


class _SubscriptionOwner:
    """Minimal duck-typed owner satisfying ``_SubscriptionStateOwner``."""

    def __init__(self, state: MarketSubscriptionState) -> None:
        self._subscription_state = state


def _once_ready_detail(
    *, replay_at: datetime | None, state: str = "stale_orderbook"
) -> dict[str, object]:
    """The issue's real shape: ever READY, current generation still bookless."""
    detail: dict[str, object] = {
        "condition_id": "eth-5m",
        "subscription_state": state,
        "first_bilateral_book_ever_at": (T0 - timedelta(hours=2)).isoformat(),
        "last_book_at_by_side": {"UP": T0.isoformat(), "DOWN": T0.isoformat()},
        "last_book_received_at_by_side": {"UP": T0.isoformat(), "DOWN": T0.isoformat()},
    }
    if replay_at is not None:
        detail["adapter_replay_unconfirmed"] = True
        detail["adapter_replay_started_at"] = replay_at.isoformat()
    return detail


# --------------------------------------------------------------------------- B1


def test_adapter_replay_detail_started_at_is_iso_string() -> None:
    """B1: a replay marker must serialize to JSON on the heartbeat path."""
    state = MarketSubscriptionState()
    state.adapter_replay_started_at_by_condition["eth-5m"] = T0
    detail = _adapter_replay_detail(state, "eth-5m")
    assert detail["adapter_replay_unconfirmed"] is True
    assert isinstance(detail["adapter_replay_started_at"], str)
    assert json.dumps(detail, sort_keys=True)  # must not raise TypeError


def test_adapter_replay_detail_none_started_at_stays_none() -> None:
    state = MarketSubscriptionState()
    detail = _adapter_replay_detail(state, "eth-5m")
    assert detail["adapter_replay_unconfirmed"] is False
    assert detail["adapter_replay_started_at"] is None
    assert json.dumps(detail, sort_keys=True)


def test_heartbeat_write_with_replay_detail_does_not_crash() -> None:
    """B1 end-to-end: the miss write path must not crash on a replay marker.

    The detail comes from the real ``_adapter_replay_detail``, which on the
    unfixed PR carried a raw ``datetime`` and made ``json.dumps`` raise
    ``TypeError: Object of type datetime is not JSON serializable`` — leaving
    the heartbeat file untouched exactly when the runtime most needs
    observability.
    """
    state = MarketSubscriptionState()
    state.adapter_replay_started_at_by_condition["eth-5m"] = T0
    detail: dict[str, object] = {
        "subscription_state": "awaiting_first_book",
        "first_bilateral_book_ever_at": None,
        **_adapter_replay_detail(state, "eth-5m"),
    }
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "runtime_heartbeat.json"
        heartbeat = write_runtime_heartbeat(
            path,
            phase="readiness_miss",
            readiness_key="eth-5m",
            readiness_ok=False,
            readiness_detail=detail,
            now=T0,
        )
        stored = json.loads(path.read_text(encoding="utf-8"))
        stored_detail = stored["readiness_detail_by_key"]["eth-5m"]
        assert stored_detail["adapter_replay_unconfirmed"] is True
        assert stored_detail["adapter_replay_started_at"] == T0.isoformat()
        assert (
            heartbeat.readiness_detail_by_key["eth-5m"]["adapter_replay_started_at"]
            == T0.isoformat()
        )


# --------------------------------------------------------------------------- B2


def test_replay_marker_is_not_extended_by_retries_or_rotations() -> None:
    """B2 anchor: the marker records the *first* replay start of the streak.

    Retries (``_mark_replay_unconfirmed`` on every refresh dispatch) and a
    re-begun generation while still unconfirmed must not move the timestamp,
    otherwise the bounded grace window would be perpetually renewed and a stuck
    condition would never be supervised.
    """
    _clear_global_book_recovery_state()
    state = MarketSubscriptionState()
    begin_market_book_generation(
        _SubscriptionOwner(state),
        "eth-5m",
        now=T0,
    )
    assert state.adapter_replay_started_at_by_condition["eth-5m"] == T0
    late = T0 + timedelta(minutes=10)
    _mark_replay_unconfirmed(state, "eth-5m", now=late)
    assert state.adapter_replay_started_at_by_condition["eth-5m"] == T0
    begin_market_book_generation(
        _SubscriptionOwner(state),
        "eth-5m",
        now=late,
    )
    assert state.adapter_replay_started_at_by_condition["eth-5m"] == T0


def test_once_ready_within_replay_grace_does_not_count_toward_miss() -> None:
    detail = _once_ready_detail(replay_at=T0 - timedelta(seconds=60))
    assert _detail_counts_toward_readiness_miss(detail, observed_at=T0) is False


def test_once_ready_beyond_replay_grace_counts_toward_miss() -> None:
    detail = _once_ready_detail(replay_at=T0 - timedelta(seconds=400))
    assert _detail_counts_toward_readiness_miss(detail, observed_at=T0) is True


def test_replay_grace_boundary_is_inclusive() -> None:
    """B2: the grace window boundary is inclusive at REPLAY_GRACE_SEC."""
    at_grace = _once_ready_detail(replay_at=T0 - timedelta(seconds=REPLAY_GRACE_SEC))
    assert _detail_counts_toward_readiness_miss(at_grace, observed_at=T0) is False
    past_grace = _once_ready_detail(
        replay_at=T0 - timedelta(seconds=REPLAY_GRACE_SEC + 1)
    )
    assert _detail_counts_toward_readiness_miss(past_grace, observed_at=T0) is True


def test_replay_marker_without_anchor_fails_closed() -> None:
    detail = _once_ready_detail(replay_at=None)
    detail["adapter_replay_unconfirmed"] = True  # marker set, no timestamp
    assert _detail_counts_toward_readiness_miss(detail, observed_at=T0) is True


def test_liveness_ok_within_grace_then_restart_after_grace_and_max_miss() -> None:
    """End-to-end: the issue shape must not be restarted during the replay
    grace window, but *must* be supervised once the window elapses."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "runtime_heartbeat.json"
        replay_start = T0
        detail = _once_ready_detail(replay_at=replay_start)
        # First not-ready evaluation arms the clock on the unfixed code
        # (once_ready -> True). With the bounded grace the clock stays unarmed
        # while the replay is recent, so a refreshed evaluation just past
        # max_readiness_miss_sec must still be green.
        _ = write_runtime_heartbeat(
            path,
            phase="readiness_miss",
            readiness_key="eth-5m",
            readiness_ok=False,
            readiness_detail=detail,
            now=replay_start,
        )
        observed_within = replay_start + timedelta(seconds=301)
        _ = write_runtime_heartbeat(
            path,
            phase="readiness_miss",
            readiness_key="eth-5m",
            readiness_ok=False,
            readiness_detail=detail,
            now=observed_within,
        )
        within = evaluate_liveness(
            path,
            max_age_sec=120,
            startup_started_at=replay_start - timedelta(hours=1),
            startup_grace_sec=0,
            max_readiness_miss_sec=300,
            max_data_starvation_sec=900,
            now=observed_within,
        )
        assert within.ok is True

        # The replay anchor is fixed (not extended by retries), so once the
        # grace window elapsed the very next evaluation armed the clock; after
        # another max_readiness_miss_sec the liveness flips to readiness_miss.
        observed_late = replay_start + timedelta(seconds=602)
        _ = write_runtime_heartbeat(
            path,
            phase="readiness_miss",
            readiness_key="eth-5m",
            readiness_ok=False,
            readiness_detail=_once_ready_detail(replay_at=replay_start),
            now=observed_late,
        )
        later = evaluate_liveness(
            path,
            max_age_sec=120,
            startup_started_at=replay_start - timedelta(hours=1),
            startup_grace_sec=0,
            max_readiness_miss_sec=300,
            max_data_starvation_sec=900,
            now=observed_late,
        )
        assert later.ok is False
        assert later.reason == "readiness_miss"


# --------------------------------------------------------------------------- B5: timeout evidence


def test_adapter_replay_detail_exposes_timeout_and_recovery_attempts() -> None:
    """B5: readiness detail must carry a bounded replay timeout signal and the
    number of recovery batches dispatched for the current generation."""
    state = MarketSubscriptionState()
    state.adapter_replay_started_at_by_condition["eth-5m"] = T0
    state.book_recovery_attempt_count_by_condition["eth-5m"] = 2
    state.book_recovery_dispatched_at_by_condition["eth-5m"] = {
        Side.UP: T0,
        Side.DOWN: T0 + timedelta(seconds=1),
    }
    detail = _adapter_replay_detail(state, "eth-5m")
    assert detail["adapter_replay_unconfirmed"] is True
    assert detail["adapter_replay_timeout"] is True
    assert detail["recovery_attempt_count"] == 2
    assert detail["recovery_dispatched_at_by_side"] == {
        "UP": T0.isoformat(),
        "DOWN": (T0 + timedelta(seconds=1)).isoformat(),
    }
    assert json.dumps(detail, sort_keys=True)


def test_adapter_replay_timeout_counts_toward_liveness_miss_after_grace() -> None:
    """B5: after the bounded replay grace elapses without a book, an explicit
    timeout (marker + recovery attempts) means the never-READY condition is no
    longer warmup and must arm the readiness-miss clock."""
    detail = _once_ready_detail(replay_at=T0 - timedelta(seconds=400))
    detail["subscription_state"] = "awaiting_first_book"
    detail["first_bilateral_book_ever_at"] = None
    detail["adapter_replay_timeout"] = True
    detail["recovery_attempt_count"] = 3
    assert _detail_counts_toward_readiness_miss(detail, observed_at=T0) is True

    # A fresh in-flight replay without timeout evidence stays warmup-exempt.
    fresh = _once_ready_detail(replay_at=T0 - timedelta(seconds=60))
    fresh["subscription_state"] = "awaiting_first_book"
    fresh["first_bilateral_book_ever_at"] = None
    fresh["adapter_replay_timeout"] = False
    fresh["recovery_attempt_count"] = 1
    assert _detail_counts_toward_readiness_miss(fresh, observed_at=T0) is False


def test_active_book_recovery_batch_defers_readiness_miss_for_orderbook_gap(
    tmp_path: Path,
) -> None:
    """Missing orderbook data that is being actively reloaded must not flap
    the healthcheck. The runtime is not active-but-unsubscribed: it has a
    concrete missing-side set and an unconfirmed adapter replay boundary, so
    the per-condition readiness-miss clock stays disarmed while the process
    keeps recovering. Global data starvation remains the backstop."""
    detail = _once_ready_detail(replay_at=T0 - timedelta(seconds=400))
    detail["subscription_state"] = "awaiting_first_book"
    detail["first_bilateral_book_ever_at"] = None
    detail["adapter_replay_timeout"] = True
    detail["recovery_attempt_count"] = 8
    detail["awaiting_book_sides"] = ["DOWN", "UP"]
    detail["pending_instrument_ids"] = []
    assert _detail_counts_toward_readiness_miss(detail, observed_at=T0) is False


def test_bookless_recovery_without_concrete_work_still_arms_readiness_miss() -> None:
    """A replay timeout with no current missing sides/instruments is not an
    active recovery; it must stay under the readiness-miss clock."""
    detail = _once_ready_detail(replay_at=T0 - timedelta(seconds=400))
    detail["subscription_state"] = "awaiting_first_book"
    detail["first_bilateral_book_ever_at"] = None
    detail["adapter_replay_timeout"] = True
    detail["recovery_attempt_count"] = 8
    detail["awaiting_book_sides"] = []
    detail["pending_instrument_ids"] = []
    assert _detail_counts_toward_readiness_miss(detail, observed_at=T0) is True


def test_recovery_in_flight_detail_defers_once_ready_stale_orderbook() -> None:
    """A once-READY condition that hit stale_orderbook but whose current
    readiness detail declares an in-flight recovery must not arm the
    per-condition miss clock; missing order data is self-recovering."""
    detail = _once_ready_detail(replay_at=None, state="stale_orderbook")
    detail["recovery_in_flight"] = True
    assert _detail_counts_toward_readiness_miss(detail, observed_at=T0) is False


def test_absent_recovery_in_flight_keeps_prior_stale_contract() -> None:
    detail = _once_ready_detail(replay_at=None, state="stale_orderbook")
    assert _detail_counts_toward_readiness_miss(detail, observed_at=T0) is True
