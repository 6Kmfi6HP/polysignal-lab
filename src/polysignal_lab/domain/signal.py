"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Mapping, collections.abc.Sequence, datetime, datetime.datetime, types, types.MappingProxyType, typing
Output: SignalCandidate, RejectedSignal
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from types import MappingProxyType
from typing import Annotated, Any, Self, cast

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator, model_validator

from polysignal_lab.domain.enums import Action, OrderIntent, Side
from polysignal_lab.domain.freshness import FreshnessPolicy
from polysignal_lab.utils import new_id, stable_hash, utc_now


def _as_str_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in cast(Sequence[object], value))


def _freeze_mapping(value: object) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    if isinstance(value, Mapping):
        return MappingProxyType(dict(value))
    raise TypeError(f"Expected mapping, was {type(value).__name__}")


FrozenMap = Annotated[
    Mapping[str, Any],
    PlainSerializer(lambda v: dict(v), return_type=dict[str, Any], when_used="always"),
]


class SignalCandidate(BaseModel):
    """Publish/projection DTO only — not the trading-order SoT.

    Order routing uses AlphaDecision → Nautilus OrderFactory. This type carries
    Telegram/SQLite identity (signal_id, dedupe_key) with message immutability.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

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
    freshness_policy: FreshnessPolicy | None = None
    reason_codes: tuple[str, ...] = ()
    metrics: FrozenMap = Field(default_factory=dict)
    dedupe_key: str
    snapshot_id: str | None = None
    source_signal_ids: tuple[str, ...] = ()
    order_intent: OrderIntent | None = None
    expiry_seconds: int | None = None
    pair_id: str | None = None
    reduce_only: bool = False
    hedge_leg: bool = False

    @field_validator("reason_codes", "source_signal_ids", mode="before")
    @classmethod
    def _tuple_fields(cls, value: object) -> tuple[str, ...]:
        return _as_str_tuple(value)

    @field_validator("metrics", mode="before")
    @classmethod
    def _freeze_metrics(cls, value: object) -> Mapping[str, Any]:
        return _freeze_mapping(value)

    @model_validator(mode="after")
    def _reseal_nested(self) -> Self:
        # Pydantic may re-materialize Mapping as dict; re-seal for NT message integrity.
        object.__setattr__(self, "metrics", _freeze_mapping(self.metrics))
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        object.__setattr__(self, "source_signal_ids", tuple(self.source_signal_ids))
        return self

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
        reason_codes: Sequence[str],
        metrics: Mapping[str, Any],
        freshness_policy: FreshnessPolicy | None = None,
        signal_id: str | None = None,
        created_at: datetime | None = None,
        snapshot_id: str | None = None,
        source_signal_ids: Sequence[str] | None = None,
        order_intent: OrderIntent | None = None,
        expiry_seconds: int | None = None,
        pair_id: str | None = None,
        reduce_only: bool = False,
        hedge_leg: bool = False,
    ) -> "SignalCandidate":
        event_time = created_at if created_at is not None else utc_now()
        dedupe_scope = "exit" if reduce_only else "entry"
        dedupe_key = f"{asset}:{timeframe}:{market_id}:{side.value}:{strategy}:{dedupe_scope}"
        sid = signal_id or f"sig_{stable_hash(strategy, asset, timeframe, market_id, side.value, event_time.isoformat(), length=20)}"
        return cls(
            signal_id=sid,
            created_at=event_time,
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
            freshness_policy=freshness_policy,
            reason_codes=tuple(reason_codes),
            metrics=metrics,
            dedupe_key=dedupe_key,
            snapshot_id=snapshot_id,
            source_signal_ids=tuple(source_signal_ids or ()),
            order_intent=order_intent,
            expiry_seconds=expiry_seconds,
            pair_id=pair_id,
            reduce_only=reduce_only,
            hedge_leg=hedge_leg,
        )


class RejectedSignal(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    schema_version: int = 1
    rejected_id: str = Field(default_factory=lambda: new_id("rej"))
    candidate: SignalCandidate
    rejected_at: datetime = Field(default_factory=utc_now)
    gate_name: str
    reason_code: str
    details: FrozenMap = Field(default_factory=dict)

    @field_validator("details", mode="before")
    @classmethod
    def _freeze_details_input(cls, value: object) -> Mapping[str, Any]:
        return _freeze_mapping(value)

    @model_validator(mode="after")
    def _reseal_details(self) -> Self:
        object.__setattr__(self, "details", _freeze_mapping(self.details))
        return self
