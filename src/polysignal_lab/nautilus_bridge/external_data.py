from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from polysignal_lab.alpha.types import SpotView


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


class ExternalDataSidecar:
    def __init__(self) -> None:
        self._spots: dict[str, SpotView] = {}
        self._ptb: dict[str, PriceToBeatView] = {}

    def update_spot(self, spot: SpotView) -> None:
        self._spots[spot.asset.upper()] = spot

    def spot_for(self, asset: str) -> SpotView | None:
        return self._spots.get(asset.upper())

    def update_price_to_beat(
        self,
        *,
        condition_id: str,
        value: float,
        source: str,
        verified: bool,
        from_anchor_service: bool,
        anchor_source: str | None,
        anchor_lag_ms: int | None,
    ) -> None:
        self._ptb[condition_id] = PriceToBeatView(
            condition_id=condition_id,
            value=value,
            source=source,
            verified=verified,
            from_anchor_service=from_anchor_service,
            anchor_source=anchor_source,
            anchor_lag_ms=anchor_lag_ms,
            updated_at=datetime.now(UTC),
        )

    def ptb_for(self, condition_id: str) -> PriceToBeatView | None:
        return self._ptb.get(condition_id)
