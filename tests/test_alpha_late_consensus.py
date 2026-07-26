from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from polysignal_lab.alpha.late_consensus_core import LateConsensusAlphaCore
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.strategy_config import LateConsensusConfig
from alpha_helpers import evaluate_core, with_active_order
from factories import sample_market_view


def _config() -> LateConsensusConfig:
    # entry_frequency_sec=0 isolates the sequence/flip-guard behavior from the
    # frequency gate so repeated evaluate() calls keep emitting candidates.
    return LateConsensusConfig(entry_frequency_sec=0)


def _snapshot():
    # 5m market, seconds_to_close=120 == effective_entry_window (120) → passes
    # the time-window check; ask_sum=1.0, |0.82-0.18|=0.64 ≥ 0.30, fav UP 0.82.
    return sample_market_view(up_ask=0.82, down_ask=0.18, seconds_to_close=120)


def test_late_consensus_sequence_comes_from_cached_accepted_orders() -> None:
    core = LateConsensusAlphaCore(_config())
    snapshot = _snapshot()

    first = evaluate_core(core, snapshot)
    assert len(first) == 1
    assert first[0].metrics["entry_sequence"] == 0

    # Repeated candidate generation must NOT consume the sequence counter.
    second = evaluate_core(core, snapshot)
    assert len(second) == 1
    assert second[0].metrics["entry_sequence"] == 0
    cached = with_active_order(snapshot, core.name, side=first[0].side)
    third = evaluate_core(core, cached)
    assert len(third) == 1
    assert third[0].metrics["entry_sequence"] == 1


def test_late_consensus_flip_guard_advances_only_on_acceptance() -> None:
    config = _config()
    core = LateConsensusAlphaCore(config)
    up_snapshot = _snapshot()
    down_snapshot = sample_market_view(up_ask=0.18, down_ask=0.82, seconds_to_close=120)

    up = evaluate_core(core, up_snapshot)
    assert len(up) == 1 and up[0].side == Side.UP

    # A rejected/unaaccepted UP candidate must NOT poison the flip guard.
    down_before_accept = evaluate_core(core, down_snapshot)
    assert len(down_before_accept) == 1
    assert down_before_accept[0].side == Side.DOWN

    cached = with_active_order(up_snapshot, core.name, side=Side.UP)
    down_after_accept = evaluate_core(
        core,
        replace(down_snapshot, trading=cached.trading),
    )
    assert down_after_accept == []


def test_late_consensus_frequency_uses_market_view_time() -> None:
    core = LateConsensusAlphaCore(LateConsensusConfig(entry_frequency_sec=10))
    start = datetime(2026, 1, 1, tzinfo=UTC)
    first_view = sample_market_view(
        up_ask=0.82,
        down_ask=0.18,
        seconds_to_close=120,
        created_at=start,
    )
    first = core.evaluate(first_view)
    assert len(first) == 1
    cached = with_active_order(
        first_view,
        core.name,
        side=first[0].side,
        ts_event=start,
    )
    blocked = replace(cached, created_at=start + timedelta(seconds=9))
    allowed = replace(cached, created_at=start + timedelta(seconds=10))

    assert core.evaluate(blocked) == []
    assert len(core.evaluate(allowed)) == 1


# ---------------------------------------------------------------------------
# State round-trip
# ---------------------------------------------------------------------------


def test_late_consensus_does_not_store_order_state() -> None:
    core = LateConsensusAlphaCore(_config())
    assert not hasattr(core, "_last_favorite")
    assert not hasattr(core, "_last_entry_at")
    assert not hasattr(core, "_accepted_counts")
    assert not hasattr(core, "save_state")
