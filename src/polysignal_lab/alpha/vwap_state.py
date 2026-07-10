"""
Input: collections, polysignal_lab.alpha.vwap_trade_history, polysignal_lab.domain.enums
Output: VWAP_STATE_VERSION, encode_vwap_state, decode_vwap_state, restore_vwap_state_fields
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from collections import defaultdict
from typing import Mapping

from polysignal_lab.alpha.vwap_trade_history import TradeHistory
from polysignal_lab.domain.enums import Side

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


def restore_vwap_state_fields(
    payload: Mapping[str, object],
) -> tuple[
    TradeHistory,
    defaultdict[str, bool],
    dict[str, tuple[float, float, str | None, float | None]],
    defaultdict[str, set[tuple[float, float, float]]],
    dict[str, tuple[Side, float]],
]:
    decoded = decode_vwap_state(payload)

    trades_raw = decoded.get("trades", {}) or {}
    if not isinstance(trades_raw, Mapping):
        trades_raw = {}
    new_trades = TradeHistory()
    for key, lst in trades_raw.items():
        for trade in lst:
            new_trades.push(
                str(key), float(trade["price"]), float(trade["size"]), float(trade["timestamp"])
            )

    can_enter_raw = decoded.get("can_enter", {}) or {}
    if not isinstance(can_enter_raw, Mapping):
        can_enter_raw = {}
    can_enter = defaultdict(
        lambda: True, {str(key): bool(value) for key, value in can_enter_raw.items()}
    )

    sigs_raw = decoded.get("last_trade_signatures", {}) or {}
    if not isinstance(sigs_raw, Mapping):
        sigs_raw = {}
    last_trade_signatures = {str(key): tuple(value) for key, value in sigs_raw.items()}

    seen_raw = decoded.get("seen_trade_signatures", {}) or {}
    if not isinstance(seen_raw, Mapping):
        seen_raw = {}
    seen_trade_signatures = defaultdict(
        set,
        {str(key): {tuple(sig) for sig in value} for key, value in seen_raw.items()},
    )

    hedges_raw = decoded.get("pending_hedges", {}) or {}
    if not isinstance(hedges_raw, Mapping):
        hedges_raw = {}
    pending_hedges = {
        str(key): (Side(value[0]), float(value[1])) for key, value in hedges_raw.items()
    }

    return (
        new_trades,
        can_enter,
        last_trade_signatures,
        seen_trade_signatures,
        pending_hedges,
    )
