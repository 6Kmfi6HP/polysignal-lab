from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class AnchorPrice:
    asset: str
    timeframe: str
    market_slug: str
    window_start: datetime
    window_end: datetime
    price: float | None
    source: str
    verified: bool
    captured_at: datetime
    lag_ms: int | None
