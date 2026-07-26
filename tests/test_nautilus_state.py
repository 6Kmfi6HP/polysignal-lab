from __future__ import annotations

import pytest

from polysignal_lab.nautilus_runtime.strategy_state import (
    STRATEGY_STATE_VERSION,
    StateSchemaError,
    decode_state,
    encode_state,
    save_strategy_state,
    state_key,
)


def test_state_key_uses_polysignal_strategy_version_format() -> None:
    assert (
        state_key("ptb_diff") == f"polysignal.ptb_diff.state.v{STRATEGY_STATE_VERSION}"
    )
    assert STRATEGY_STATE_VERSION == 3


def test_encode_decode_state_round_trip_json_bytes() -> None:
    encoded = encode_state(
        "late_consensus",
        {"alpha": {"accepted": {"BTC": 2}}, "workflow": {"exit_inflight": []}},
    )

    assert set(encoded) == {
        f"polysignal.late_consensus.state.v{STRATEGY_STATE_VERSION}"
    }
    assert isinstance(
        encoded[f"polysignal.late_consensus.state.v{STRATEGY_STATE_VERSION}"], bytes
    )
    assert decode_state("late_consensus", encoded) == {
        "alpha": {"accepted": {"BTC": 2}},
        "workflow": {"exit_inflight": []},
    }


def test_decode_missing_state_returns_empty_payload_with_reason() -> None:
    decoded = decode_state("vwap_momentum", {})

    assert decoded == {
        "migration_reasons": [
            f"missing polysignal.vwap_momentum.state.v{STRATEGY_STATE_VERSION}"
        ]
    }


def test_decode_unknown_version_fails_closed() -> None:
    state = encode_state(
        "dump_hedge",
        {"positions": {}},
        version=STRATEGY_STATE_VERSION + 1,
    )

    with pytest.raises(StateSchemaError, match="Unsupported state schema"):
        decode_state("dump_hedge", state)


def test_decode_mixed_current_and_future_versions_fails_closed() -> None:
    state = encode_state(
        "ptb_diff",
        {"alpha": {}, "workflow": {}},
        version=STRATEGY_STATE_VERSION,
    )
    state.update(
        encode_state(
            "ptb_diff",
            {"alpha": {"future": "state"}, "workflow": {}},
            version=STRATEGY_STATE_VERSION + 1,
        )
    )

    with pytest.raises(StateSchemaError, match="Unsupported state schema"):
        decode_state("ptb_diff", state)


def test_decode_rejects_legacy_trading_state() -> None:
    legacy = encode_state(
        "dump_hedge", {"_positions": {"m1": {"hedged": False}}}, version=1
    )

    with pytest.raises(StateSchemaError, match="Unsupported state schema"):
        decode_state("dump_hedge", legacy)


def test_save_strategy_state_wraps_alpha_only() -> None:
    class _Core:
        def save_state(self) -> dict[str, object]:
            return {"rolling_indicator": 3}

    encoded = save_strategy_state("dump_hedge", _Core())
    payload = decode_state("dump_hedge", encoded)

    assert payload == {
        "alpha": {"rolling_indicator": 3},
    }
