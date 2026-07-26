from __future__ import annotations

import pytest

from polysignal_lab.alpha.vwap_state import (
    VWAP_STATE_VERSION,
    decode_vwap_state,
    encode_vwap_state,
    restore_vwap_state_fields,
)


def test_encode_vwap_state_preserves_flat_payload() -> None:
    payload = {"note": "empty-core-state"}
    assert encode_vwap_state(payload) == payload


def test_decode_vwap_state_accepts_flat_payload() -> None:
    payload = {"note": "empty-core-state"}
    assert decode_vwap_state(payload) == payload


def test_decode_vwap_state_unwraps_nested_envelope() -> None:
    inner = {"note": "empty-core-state"}
    payload = {"schema_version": VWAP_STATE_VERSION, "payload": inner}
    assert decode_vwap_state(payload) == inner


def test_decode_vwap_state_rejects_unknown_version() -> None:
    with pytest.raises(ValueError, match="unsupported VWAP state schema_version"):
        decode_vwap_state({"schema_version": VWAP_STATE_VERSION + 1, "payload": {}})


def test_restore_vwap_state_fields_drops_legacy_trade_ledger() -> None:
    payload = {
        "trades": {"market:UP": [{"price": 0.5, "size": 1.0, "timestamp": 1.0}]},
        "can_enter": {},
        "last_trade_signatures": {"market:UP": [0.5, 1.0, None, 1.0]},
        "seen_trade_signatures": {"market:UP": [[0.5, 1.0, 1.0]]},
        "pending_hedges": {"market-1": ["DOWN", 10.0]},
        "note": "keep-me",
    }

    restored = restore_vwap_state_fields(payload)
    assert restored == {"note": "keep-me"}
