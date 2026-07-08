"""
Input: __future__, __future__.annotations, datetime, datetime.datetime, pydantic, pydantic.BaseModel, pydantic.Field, polysignal_lab.utils, polysignal_lab.utils.utc_now
Output: SpotPrice
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from polysignal_lab.utils import utc_now


class SpotPrice(BaseModel):
    schema_version: int = 1
    asset: str
    symbol: str
    price: float
    source: str = "binance_spot"
    event_time: datetime | None = None
    received_at: datetime = Field(default_factory=utc_now)

    def freshness_ms(self, now: datetime | None = None) -> int:
        current = now or utc_now()
        return max(0, int((current - self.received_at).total_seconds() * 1000))

    def is_fresh(self, max_staleness_ms: int, now: datetime | None = None) -> bool:
        return self.freshness_ms(now) <= max_staleness_ms


# Backward-compatible alias after merging SpotTick into SpotPrice.
SpotTick = SpotPrice
