from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

StrategyStatus = Literal[
    "active",
    "disabled",
    "inactive",
    "unsupported_market",
    "missing_data",
    "untradable",
    "uncalibrated",
]


@dataclass(frozen=True, slots=True)
class StrategyMarketStatus:
    strategy: str
    asset: str
    timeframe: str
    status: StrategyStatus
    reason: str | None
