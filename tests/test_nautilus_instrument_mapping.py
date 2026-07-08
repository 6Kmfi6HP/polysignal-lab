"""
Input: __future__, __future__.annotations, sys, types, types.SimpleNamespace, pytest, polysignal_lab.nautilus_runtime.instrument_mapping, polysignal_lab.nautilus_runtime.instrument_mapping.polymarket_instrument_id
Output: test_polymarket_instrument_id_uses_nautilus_adapter_helper, test_polymarket_instrument_id_rejects_empty_parts, test_polymarket_instrument_id_requires_nautilus_adapter
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from polysignal_lab.nautilus_bridge.instrument_mapping import polymarket_instrument_id


def test_polymarket_instrument_id_uses_nautilus_adapter_helper(monkeypatch) -> None:
    helper_calls: list[tuple[str, str]] = []

    def helper(condition_id: str, token_id: str) -> str:
        helper_calls.append((condition_id, token_id))
        return f"{condition_id}:{token_id}.POLYMARKET"

    monkeypatch.setitem(
        sys.modules,
        "nautilus_trader.adapters.polymarket",
        SimpleNamespace(get_polymarket_instrument_id=helper),
    )

    assert polymarket_instrument_id("condition", "token") == "condition:token.POLYMARKET"
    assert helper_calls == [("condition", "token")]


def test_polymarket_instrument_id_rejects_empty_parts() -> None:
    with pytest.raises(ValueError, match="condition_id must not be empty"):
        polymarket_instrument_id("", "token")

    with pytest.raises(ValueError, match="token_id must not be empty"):
        polymarket_instrument_id("condition", "")


def test_polymarket_instrument_id_requires_nautilus_adapter(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "nautilus_trader.adapters.polymarket", SimpleNamespace())

    with pytest.raises(RuntimeError, match="Nautilus Polymarket adapter is required"):
        polymarket_instrument_id("condition", "token")
