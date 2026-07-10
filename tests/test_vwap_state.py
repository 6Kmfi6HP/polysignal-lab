"""Unit tests for VWAP state codec."""

from __future__ import annotations

import pytest

from polysignal_lab.alpha.vwap_state import (
    VWAP_STATE_VERSION,
    decode_vwap_state,
    encode_vwap_state,
    restore_vwap_state_fields,
)
from polysignal_lab.domain.enums import Side


def test_encode_vwap_state_preserves_flat_payload() -> None:
    payload = {"trades": {}, "can_enter": {"market-1": False}}

    assert encode_vwap_state(payload) == payload


def test_decode_vwap_state_accepts_flat_payload() -> None:
    payload = {"trades": {}, "pending_hedges": {"market-1": ["DOWN", 10.0]}}

    assert decode_vwap_state(payload) == payload


def test_decode_vwap_state_unwraps_nested_envelope() -> None:
    inner = {"trades": {}, "can_enter": {}}
    payload = {"schema_version": VWAP_STATE_VERSION, "payload": inner}

    assert decode_vwap_state(payload) == inner


def test_decode_vwap_state_rejects_unknown_version() -> None:
    with pytest.raises(ValueError, match="unsupported VWAP state schema_version"):
        decode_vwap_state({"schema_version": VWAP_STATE_VERSION + 1, "payload": {}})


def test_restore_vwap_state_fields_round_trips_pending_hedge() -> None:
    payload = {
        "trades": {},
        "can_enter": {},
        "last_trade_signatures": {},
        "seen_trade_signatures": {},
        "pending_hedges": {"market-1": ["DOWN", 10.0]},
    }

    (
        _trades,
        _can_enter,
        _last_trade_signatures,
        _seen_trade_signatures,
        pending_hedges,
    ) = restore_vwap_state_fields(payload)

    assert pending_hedges == {"market-1": (Side.DOWN, 10.0)}
