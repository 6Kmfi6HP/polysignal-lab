from __future__ import annotations

from typing import Mapping

VWAP_STATE_VERSION = 1


def encode_vwap_state(state: Mapping[str, object]) -> dict[str, object]:
    return dict(state)


def decode_vwap_state(payload: Mapping[str, object]) -> dict[str, object]:
    version = payload.get("schema_version")
    if version is not None:
        if version != VWAP_STATE_VERSION:
            raise ValueError(f"unsupported VWAP state schema_version: {version!r}")
        raw = payload.get("payload")
        if not isinstance(raw, Mapping):
            raise ValueError("VWAP state payload must be a mapping")
        return dict(raw)
    return dict(payload)


def restore_vwap_state_fields(payload: Mapping[str, object]) -> dict[str, object]:
    """Decode VWAP payload and drop legacy local trade-ledger fields."""
    decoded = decode_vwap_state(payload)
    # Intentionally ignore trades / signature bags: Cache owns trade truth.
    decoded.pop("trades", None)
    decoded.pop("last_trade_signatures", None)
    decoded.pop("seen_trade_signatures", None)
    decoded.pop("can_enter", None)
    decoded.pop("pending_hedges", None)
    return decoded
