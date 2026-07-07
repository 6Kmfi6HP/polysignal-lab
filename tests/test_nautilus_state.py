"""
Input: __future__, __future__.annotations, pytest, polysignal_lab.nautilus_bridge.state, polysignal_lab.nautilus_bridge.state.StateSchemaError, polysignal_lab.nautilus_bridge.state.decode_state, polysignal_lab.nautilus_bridge.state.encode_state, polysignal_lab.nautilus_bridge.state.state_key
Output: test_state_key_uses_polysignal_strategy_version_format, test_encode_decode_state_round_trip_json_bytes, test_decode_missing_state_returns_empty_payload_with_reason, test_decode_unknown_version_fails_closed, test_decode_mixed_current_and_future_versions_fails_closed
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import pytest

from polysignal_lab.nautilus_bridge.state import StateSchemaError, decode_state, encode_state, state_key


def test_state_key_uses_polysignal_strategy_version_format() -> None:
    assert state_key("ptb_diff") == "polysignal.ptb_diff.state.v1"


def test_encode_decode_state_round_trip_json_bytes() -> None:
    encoded = encode_state("late_consensus", {"accepted": {"BTC": 2}, "migration_reasons": []})

    assert set(encoded) == {"polysignal.late_consensus.state.v1"}
    assert isinstance(encoded["polysignal.late_consensus.state.v1"], bytes)
    assert decode_state("late_consensus", encoded) == {"accepted": {"BTC": 2}, "migration_reasons": []}


def test_decode_missing_state_returns_empty_payload_with_reason() -> None:
    decoded = decode_state("vwap_momentum", {})

    assert decoded == {"migration_reasons": ["missing polysignal.vwap_momentum.state.v1"]}


def test_decode_unknown_version_fails_closed() -> None:
    state = encode_state("dump_hedge", {"positions": {}}, version=2)

    with pytest.raises(StateSchemaError, match="Unsupported state schema"):
        decode_state("dump_hedge", state, version=1)


def test_decode_mixed_current_and_future_versions_fails_closed() -> None:
    state = encode_state("ptb_diff", {"accepted_state": {}}, version=1)
    state.update(encode_state("ptb_diff", {"accepted_state": {"future": "state"}}, version=2))

    with pytest.raises(StateSchemaError, match="Unsupported state schema"):
        decode_state("ptb_diff", state, version=1)
