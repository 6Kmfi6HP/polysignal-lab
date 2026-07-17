"""
Input: __future__, __future__.annotations, datetime, datetime.timedelta, polysignal_lab.config, polysignal_lab.config.Settings, polysignal_lab.signal_layer.consensus, polysignal_lab.signal_layer.consensus.ConsensusEngine
Output: test_signal_gate_accepts_good_signal, test_signal_gate_rejects_inactive_market, test_signal_gate_rejects_low_confidence, test_deduper_flags_duplicate, test_consensus_engine_merges_two_strategies, test_consensus_ignores_late_signal_outside_event_window, test_consensus_engine_uses_signal_time_not_wall_clock
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""








from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from polysignal_lab.alpha.late_consensus_core import LateConsensusAlphaCore
from polysignal_lab.nautilus_runtime.decision_policy import candidate_from_decision
from polysignal_lab.signal_layer.consensus import ConsensusEngine
from polysignal_lab.signal_layer.deduper import SignalDeduper
from polysignal_lab.signal_layer.gate import SignalGate
from signal_helpers import ptb_signal_from_view, ptb_signals_from_view


async def _ptb_signal(view, settings):
    return ptb_signal_from_view(view, settings)


async def test_signal_gate_accepts_good_signal(market_view, settings):
    sig = await _ptb_signal(market_view, settings)
    gate = SignalGate(settings.signal, settings.data.polymarket, settings.data.binance)
    decision = gate.evaluate(sig, market_view)
    assert decision.accepted


async def test_signal_gate_rejects_inactive_market(market_view, settings):
    sig = await _ptb_signal(market_view, settings)
    bad = replace(market_view, metrics={**dict(market_view.metrics), "market_is_active": False})
    gate = SignalGate(settings.signal, settings.data.polymarket, settings.data.binance)
    decision = gate.evaluate(sig, bad)
    assert not decision.accepted
    assert decision.rejected is not None
    assert decision.rejected.reason_code == "MARKET_NOT_ACTIVE"


async def test_signal_gate_rejects_low_confidence(market_view, settings):
    sig = (await _ptb_signal(market_view, settings)).model_copy(update={"confidence": 0.1})
    gate = SignalGate(settings.signal, settings.data.polymarket, settings.data.binance)
    decision = gate.evaluate(sig, market_view)
    assert decision.rejected is not None
    assert decision.rejected.reason_code == "CONFIDENCE_TOO_LOW"


async def test_deduper_flags_duplicate(market_view, settings):
    sig = await _ptb_signal(market_view, settings)
    deduper = SignalDeduper(ttl_sec=300)
    assert deduper.is_duplicate(sig) is False
    assert deduper.is_duplicate(sig) is True


async def test_consensus_engine_merges_two_strategies(market_view, settings):
    ptb = ptb_signals_from_view(market_view, settings)[0]
    late_decisions = LateConsensusAlphaCore(settings.strategies.late_consensus).evaluate(market_view)
    late = candidate_from_decision(late_decisions[0], market_view)
    engine = ConsensusEngine(window_sec=45, enabled=True)
    assert engine.add(ptb) is None
    consensus = engine.add(late)
    assert consensus is not None
    assert consensus.strategy == "consensus"
    assert consensus.created_at == max(ptb.created_at, late.created_at)
    assert set(consensus.source_signal_ids) == {ptb.signal_id, late.signal_id}


async def test_consensus_ignores_late_signal_outside_event_window(market_view, settings):
    ptb = ptb_signals_from_view(market_view, settings)[0]
    late_decisions = LateConsensusAlphaCore(settings.strategies.late_consensus).evaluate(market_view)
    late = candidate_from_decision(late_decisions[0], market_view)
    newer = ptb.model_copy(update={"created_at": late.created_at + timedelta(seconds=120)})
    older = late.model_copy(update={"created_at": late.created_at})

    engine = ConsensusEngine(window_sec=45, enabled=True)

    assert engine.add(newer) is None
    assert engine.add(older) is None


async def test_consensus_engine_uses_signal_time_not_wall_clock(market_view, settings, monkeypatch):
    ptb = ptb_signals_from_view(market_view, settings)[0]
    late_decisions = LateConsensusAlphaCore(settings.strategies.late_consensus).evaluate(market_view)
    late = candidate_from_decision(late_decisions[0], market_view)

    def fail_wall_clock():
        raise AssertionError("consensus must use signal event time")

    monkeypatch.setattr(
        "polysignal_lab.signal_layer.consensus.utc_now",
        fail_wall_clock,
        raising=False,
    )

    engine = ConsensusEngine(window_sec=45, enabled=True)
    assert engine.add(ptb) is None
    assert engine.add(late) is not None
