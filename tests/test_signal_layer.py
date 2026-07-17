"""
Input: __future__, __future__.annotations, dataclasses, dataclasses.replace, polysignal_lab.signal_layer.gate, polysignal_lab.signal_layer.gate.SignalGate, signal_helpers, signal_helpers.ptb_signal_from_view
Output: test_signal_gate_accepts_good_signal, test_signal_gate_rejects_inactive_market, test_signal_gate_rejects_low_confidence, test_signal_candidate_containers_are_immutable
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from dataclasses import replace

from polysignal_lab.signal_layer.gate import SignalGate
from signal_helpers import ptb_signal_from_view


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


async def test_signal_candidate_containers_are_immutable(market_view, settings):
    """Nautilus message integrity: nested metrics/reason_codes must not mutate in place."""
    import pytest

    sig = await _ptb_signal(market_view, settings)
    with pytest.raises(TypeError):
        sig.metrics["x"] = 1  # type: ignore[index]
    with pytest.raises(AttributeError):
        sig.reason_codes.append("X")  # type: ignore[attr-defined]
