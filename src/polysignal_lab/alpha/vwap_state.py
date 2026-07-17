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
    dict[str, tuple[float, float, str | None, float | None]],
    defaultdict[str, set[tuple[float, float, float]]],
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

    return (
        new_trades,
        last_trade_signatures,
        seen_trade_signatures,
    )
