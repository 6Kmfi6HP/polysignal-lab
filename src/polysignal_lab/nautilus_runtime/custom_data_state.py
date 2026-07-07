"""
Input: __future__, __future__.annotations, dataclasses, dataclasses.dataclass, datetime, datetime.UTC, datetime.datetime, typing, typing.Protocol, polysignal_lab.alpha.types
Output: PriceToBeatView, CustomDataApplyResult, CustomDataSnapshotProvider, StrategyCustomDataState
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from polysignal_lab.alpha.types import SpotView
from polysignal_lab.nautilus_runtime.market_data import PolySignalPriceToBeatData, PolySignalSpotData


@dataclass(frozen=True, slots=True)
class PriceToBeatView:
    condition_id: str
    value: float
    source: str
    verified: bool
    from_anchor_service: bool
    anchor_source: str | None
    anchor_lag_ms: int | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class CustomDataApplyResult:
    spot_asset: str | None = None
    price_to_beat_condition_id: str | None = None


class CustomDataSnapshotProvider(Protocol):
    def spot_for(self, asset: str) -> SpotView | None: ...

    def ptb_for(self, condition_id: str) -> PriceToBeatView | None: ...


class StrategyCustomDataState:
    """Strategy-local derived state from Nautilus CustomData messages."""

    def __init__(self) -> None:
        self._spots: dict[str, SpotView] = {}
        self._ptb: dict[str, PriceToBeatView] = {}

    def apply(self, data: object) -> CustomDataApplyResult:
        if isinstance(data, PolySignalSpotData):
            spot = SpotView(
                asset=data.asset,
                symbol=data.symbol,
                price=data.price,
                source=data.source,
                freshness_ms=data.freshness_ms,
            )
            self._spots[spot.asset.upper()] = spot
            return CustomDataApplyResult(spot_asset=spot.asset.upper())
        if isinstance(data, PolySignalPriceToBeatData):
            self._ptb[data.condition_id] = PriceToBeatView(
                condition_id=data.condition_id,
                value=data.value,
                source=data.source,
                verified=data.verified,
                from_anchor_service=data.from_anchor_service,
                anchor_source=data.anchor_source,
                anchor_lag_ms=data.anchor_lag_ms,
                updated_at=datetime.now(UTC),
            )
            return CustomDataApplyResult(price_to_beat_condition_id=data.condition_id)
        return CustomDataApplyResult()

    def spot_for(self, asset: str) -> SpotView | None:
        return self._spots.get(asset.upper())

    def ptb_for(self, condition_id: str) -> PriceToBeatView | None:
        return self._ptb.get(condition_id)
