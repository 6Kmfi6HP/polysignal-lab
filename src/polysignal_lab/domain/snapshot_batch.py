"""
Input: __future__, __future__.annotations, dataclasses, dataclasses.dataclass, datetime, datetime.datetime, polysignal_lab.domain.snapshot, polysignal_lab.domain.snapshot.MarketSnapshot
Output: SnapshotBatch, CrossMarketEvaluationContext
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from polysignal_lab.domain.snapshot import MarketSnapshot


@dataclass(frozen=True, slots=True)
class SnapshotBatch:
    batch_id: str
    as_of: datetime
    market_order: tuple[str, ...]
    snapshots: dict[str, MarketSnapshot]
    max_source_skew_ms: int


@dataclass(frozen=True, slots=True)
class CrossMarketEvaluationContext:
    relation_id: str
    snapshots_by_condition_id: dict[str, MarketSnapshot]
    batch: SnapshotBatch
