"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Mapping, datetime, datetime.datetime, polysignal_lab.alpha.types, polysignal_lab.alpha.types.MarketGroupView, polysignal_lab.alpha.types.MarketView
Output: MarketGroupViewAssembler
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from polysignal_lab.alpha.types import MarketGroupView, MarketView


class MarketGroupViewAssembler:
    """Assembles MarketGroupView from per-condition_id views.

    Rejects groups where the source skew exceeds the configured threshold,
    ensuring related views are temporally consistent.
    """

    def __init__(self, max_source_skew_ms: int = 5000) -> None:
        self.max_source_skew_ms: int = max_source_skew_ms

    def assemble(
        self,
        *,
        relation_id: str,
        views_by_condition_id: Mapping[str, MarketView],
        created_at: datetime,
        max_source_skew_ms: int | None = None,
    ) -> MarketGroupView | None:
        """Build a MarketGroupView if the source views are acceptably fresh.

        Returns None when the maximum freshness skew across views exceeds the
        configured or provided threshold.
        """
        threshold = max_source_skew_ms if max_source_skew_ms is not None else self.max_source_skew_ms
        if not views_by_condition_id:
            return None

        max_skew = 0
        freshness_values: list[int] = []
        for view in views_by_condition_id.values():
            if view.freshness and view.freshness.max_ms is not None:
                freshness_values.append(view.freshness.max_ms)
        if freshness_values:
            max_skew = max(freshness_values) - min(freshness_values)
        else:
            return None

        if max_skew > threshold:
            return None

        return MarketGroupView(
            group_id=f"group_{relation_id}_{created_at.isoformat()}",
            relation_id=relation_id,
            created_at=created_at,
            views_by_condition_id=dict(views_by_condition_id),
            max_source_skew_ms=threshold,
            metrics={},
        )
