"""
Input: __future__, __future__.annotations, dataclasses, dataclasses.dataclass, typing, typing.Literal
Output: StrategyMarketStatus
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

StrategyStatus = Literal[
    "active",
    "disabled",
    "inactive",
    "unsupported_market",
    "missing_data",
    "uncalibrated",
]


@dataclass(frozen=True, slots=True)
class StrategyMarketStatus:
    strategy: str
    asset: str
    timeframe: str
    status: StrategyStatus
    reason: str | None
