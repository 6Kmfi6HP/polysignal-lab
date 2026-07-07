"""
Input: __future__, __future__.annotations, dataclasses, dataclasses.dataclass
Output: FreshnessPolicy
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FreshnessPolicy:
    max_orderbook_staleness_ms: int | None = None
    max_spot_staleness_ms: int | None = None
    max_anchor_staleness_ms: int | None = None
