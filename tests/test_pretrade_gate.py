from __future__ import annotations

from dataclasses import replace

from polysignal_lab.pretrade.gate import SignalGate
from signal_helpers import ptb_decision_from_view, ptb_signal_from_view


async def _ptb_decision(view, settings):
    return ptb_decision_from_view(view, settings)


async def test_signal_gate_accepts_good_signal(market_view, settings):
    decision_in = await _ptb_decision(market_view, settings)
    gate = SignalGate(settings.signal, settings.data.polymarket, settings.data.binance)
    decision = gate.evaluate(decision_in, market_view)
    assert decision.accepted


async def test_signal_gate_rejects_inactive_market(market_view, settings):
    decision_in = await _ptb_decision(market_view, settings)
    bad = replace(
        market_view, metrics={**dict(market_view.metrics), "market_is_active": False}
    )
    gate = SignalGate(settings.signal, settings.data.polymarket, settings.data.binance)
    decision = gate.evaluate(decision_in, bad)
    assert not decision.accepted
    assert decision.rejected is not None
    assert decision.rejected.reason_code == "MARKET_NOT_ACTIVE"


async def test_signal_gate_rejects_low_confidence(market_view, settings):
    decision_in = replace(await _ptb_decision(market_view, settings), confidence=0.1)
    gate = SignalGate(settings.signal, settings.data.polymarket, settings.data.binance)
    decision = gate.evaluate(decision_in, market_view)
    assert decision.rejected is not None
    assert decision.rejected.reason_code == "CONFIDENCE_TOO_LOW"


async def test_signal_candidate_containers_are_immutable(market_view, settings):
    """Nautilus message integrity: nested metrics/reason_codes must not mutate in place."""
    import pytest

    sig = ptb_signal_from_view(market_view, settings)
    with pytest.raises(TypeError):
        sig.metrics["x"] = 1  # type: ignore[index]
    with pytest.raises(AttributeError):
        sig.reason_codes.append("X")  # type: ignore[attr-defined]
