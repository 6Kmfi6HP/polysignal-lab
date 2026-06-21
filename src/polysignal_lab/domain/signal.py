from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from polysignal_lab.domain.enums import Action, Side
from polysignal_lab.utils import new_id, stable_hash, utc_now


class SignalCandidate(BaseModel):
    schema_version: int = 1
    signal_id: str
    created_at: datetime = Field(default_factory=utc_now)
    strategy: str
    asset: str
    timeframe: str
    market_id: str
    market_slug: str
    condition_id: str
    token_id: str
    action: Action = Action.BUY
    side: Side
    confidence: float
    entry_reference_price: float
    max_entry_price: float
    seconds_to_close: int | None = None
    data_freshness_ms: int | None = None
    reason_codes: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    dedupe_key: str
    snapshot_id: str | None = None
    source_signal_ids: list[str] = Field(default_factory=list)

    @classmethod
    def build(
        cls,
        *,
        strategy: str,
        asset: str,
        timeframe: str,
        market_id: str,
        market_slug: str,
        condition_id: str,
        token_id: str,
        side: Side,
        confidence: float,
        entry_reference_price: float,
        max_entry_price: float,
        seconds_to_close: int | None,
        data_freshness_ms: int | None,
        reason_codes: list[str],
        metrics: dict[str, Any],
        snapshot_id: str | None = None,
        source_signal_ids: list[str] | None = None,
    ) -> "SignalCandidate":
        dedupe_key = f"{asset}:{timeframe}:{market_id}:{side.value}:{strategy}"
        sid = f"sig_{stable_hash(strategy, asset, timeframe, market_id, side.value, utc_now().isoformat(), length=20)}"
        return cls(
            signal_id=sid,
            strategy=strategy,
            asset=asset,
            timeframe=timeframe,
            market_id=market_id,
            market_slug=market_slug,
            condition_id=condition_id,
            token_id=token_id,
            side=side,
            confidence=max(0.0, min(1.0, confidence)),
            entry_reference_price=entry_reference_price,
            max_entry_price=max_entry_price,
            seconds_to_close=seconds_to_close,
            data_freshness_ms=data_freshness_ms,
            reason_codes=reason_codes,
            metrics=metrics,
            dedupe_key=dedupe_key,
            snapshot_id=snapshot_id,
            source_signal_ids=source_signal_ids or [],
        )


class RejectedSignal(BaseModel):
    schema_version: int = 1
    rejected_id: str = Field(default_factory=lambda: new_id("rej"))
    candidate: SignalCandidate
    rejected_at: datetime = Field(default_factory=utc_now)
    gate_name: str
    reason_code: str
    details: dict[str, Any] = Field(default_factory=dict)
