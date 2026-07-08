"""
Input: __future__, __future__.annotations, datetime, datetime.UTC, datetime.datetime, polysignal_lab.alpha.late_consensus_core, polysignal_lab.alpha.late_consensus_core.LateConsensusAlphaCore, polysignal_lab.alpha.types, polysignal_lab.alpha.types.AlphaOrderEvent, polysignal_lab.domain.enums
Output: test_late_consensus_core_matches_legacy_candidate, test_late_consensus_sequence_not_incremented_until_acceptance, test_late_consensus_flip_guard_advances_only_on_acceptance, test_late_consensus_adapter_applies_dedupe_suffix_from_sequence, test_late_consensus_core_state_roundtrip
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""








from __future__ import annotations

from datetime import UTC, datetime

from polysignal_lab.alpha.late_consensus_core import LateConsensusAlphaCore
from polysignal_lab.alpha.types import AlphaOrderEvent
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.strategy_config import LateConsensusConfig
from alpha_helpers import evaluate_core_from_snapshot
from factories import sample_snapshot


def _config() -> LateConsensusConfig:
    # entry_frequency_sec=0 isolates the sequence/flip-guard behavior from the
    # frequency gate so repeated evaluate() calls keep emitting candidates.
    return LateConsensusConfig(entry_frequency_sec=0)


def _snapshot():
    # 5m market, seconds_to_close=120 == effective_entry_window (120) → passes
    # the time-window check; ask_sum=1.0, |0.82-0.18|=0.64 ≥ 0.30, fav UP 0.82.
    return sample_snapshot(up_ask=0.82, down_ask=0.18, seconds_to_close=120)


def _accept_event(decision, *, ts_event=None) -> AlphaOrderEvent:
    return AlphaOrderEvent(
        strategy=decision.strategy,
        market_id=decision.market_id,
        condition_id=decision.condition_id,
        token_id=decision.token_id,
        side=decision.side,
        order_id="order-1",
        client_order_id=None,
        reason=None,
        ts_event=ts_event or decision.metrics["created_at_for_test"],
        metrics={},
    )


# ---------------------------------------------------------------------------
# Mutation timing: sequence advances only on acceptance
# ---------------------------------------------------------------------------


def test_late_consensus_sequence_not_incremented_until_acceptance() -> None:
    core = LateConsensusAlphaCore(_config())
    snapshot = _snapshot()

    first = evaluate_core_from_snapshot(core, snapshot)
    assert len(first) == 1
    assert first[0].metrics["entry_sequence"] == 0

    # Repeated candidate generation must NOT consume the sequence counter.
    second = evaluate_core_from_snapshot(core, snapshot)
    assert len(second) == 1
    assert second[0].metrics["entry_sequence"] == 0
    assert core._accepted_counts == {}

    # Acceptance is the ONLY thing that advances the sequence.
    core.on_order_accepted(_accept_event(first[0]))

    third = evaluate_core_from_snapshot(core, snapshot)
    assert len(third) == 1
    assert third[0].metrics["entry_sequence"] == 1
    assert core._accepted_counts == {snapshot.market.market_id: 1}


def test_late_consensus_flip_guard_advances_only_on_acceptance() -> None:
    config = _config()
    core = LateConsensusAlphaCore(config)
    up_snapshot = _snapshot()
    down_snapshot = sample_snapshot(up_ask=0.18, down_ask=0.82, seconds_to_close=120)

    up = evaluate_core_from_snapshot(core, up_snapshot)
    assert len(up) == 1 and up[0].side == Side.UP

    # A rejected/unaaccepted UP candidate must NOT poison the flip guard.
    down_before_accept = evaluate_core_from_snapshot(core, down_snapshot)
    assert len(down_before_accept) == 1
    assert down_before_accept[0].side == Side.DOWN

    # Only once UP is accepted does the flip guard block a rapid DOWN flip.
    core.on_order_accepted(_accept_event(up[0]))
    down_after_accept = evaluate_core_from_snapshot(core, down_snapshot)
    assert down_after_accept == []


# ---------------------------------------------------------------------------
# State round-trip
# ---------------------------------------------------------------------------


def test_late_consensus_core_state_roundtrip() -> None:
    core = LateConsensusAlphaCore(_config())
    market_id = "eth-5m-test"
    when = datetime.now(UTC)
    core._last_favorite[market_id] = (Side.UP, when)
    core._last_entry_at[market_id] = when
    core._accepted_counts[market_id] = 3

    payload = core.save_state()

    fresh = LateConsensusAlphaCore(_config())
    fresh.load_state(payload)

    assert fresh._accepted_counts == {market_id: 3}
    assert set(fresh._last_entry_at) == {market_id}
    assert fresh._last_entry_at[market_id] == when
    assert set(fresh._last_favorite) == {market_id}
    restored_side, restored_when = fresh._last_favorite[market_id]
    assert restored_side == Side.UP
    assert restored_when == when
