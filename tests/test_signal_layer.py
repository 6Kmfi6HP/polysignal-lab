from __future__ import annotations

from datetime import timedelta

from polysignal_lab.config import Settings
from polysignal_lab.domain.enums import MarketStatus
from polysignal_lab.signal_layer.consensus import ConsensusEngine
from polysignal_lab.signal_layer.deduper import SignalDeduper
from polysignal_lab.signal_layer.gate import SignalGate
from polysignal_lab.strategies.late_consensus import LateConsensusStrategy
from polysignal_lab.strategies.ptb_diff import PTBDiffStrategy
from polysignal_lab.utils import utc_now


async def _ptb_signal(snapshot, settings):
    return PTBDiffStrategy(settings.strategies.ptb_diff).evaluate(snapshot)[0]


async def test_signal_gate_accepts_good_signal(snapshot, settings):
    sig = await _ptb_signal(snapshot, settings)
    gate = SignalGate(settings.signal, settings.data.polymarket, settings.data.binance)
    decision = gate.evaluate(sig, snapshot)
    assert decision.accepted


async def test_signal_gate_rejects_inactive_market(snapshot, settings):
    sig = await _ptb_signal(snapshot, settings)
    inactive_market = snapshot.market.model_copy(update={"status": MarketStatus.CLOSED})
    bad = snapshot.model_copy(update={"market": inactive_market})
    gate = SignalGate(settings.signal, settings.data.polymarket, settings.data.binance)
    decision = gate.evaluate(sig, bad)
    assert not decision.accepted
    assert decision.rejected.reason_code == "MARKET_NOT_ACTIVE"


async def test_signal_gate_rejects_low_confidence(snapshot, settings):
    sig = (await _ptb_signal(snapshot, settings)).model_copy(update={"confidence": 0.1})
    gate = SignalGate(settings.signal, settings.data.polymarket, settings.data.binance)
    decision = gate.evaluate(sig, snapshot)
    assert decision.rejected.reason_code == "CONFIDENCE_TOO_LOW"


async def test_deduper_flags_duplicate(snapshot, settings):
    sig = await _ptb_signal(snapshot, settings)
    deduper = SignalDeduper(ttl_sec=300)
    assert deduper.is_duplicate(sig) is False
    assert deduper.is_duplicate(sig) is True


async def test_consensus_engine_merges_two_strategies(snapshot, settings):
    ptb = PTBDiffStrategy(settings.strategies.ptb_diff).evaluate(snapshot)[0]
    late = LateConsensusStrategy(settings.strategies.late_consensus).evaluate(snapshot)[0]
    engine = ConsensusEngine(window_sec=45, enabled=True)
    assert engine.add(ptb) is None
    consensus = engine.add(late)
    assert consensus is not None
    assert consensus.strategy == "consensus"
    assert set(consensus.source_signal_ids) == {ptb.signal_id, late.signal_id}
