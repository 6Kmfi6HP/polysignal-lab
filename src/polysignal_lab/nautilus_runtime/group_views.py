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

    Rejects groups containing missing or stale source data, or whose source
    skew exceeds the configured threshold.
    """

    def __init__(
        self,
        max_source_skew_ms: int = 5000,
        max_view_age_ms: int = 5000,
    ) -> None:
        self.max_source_skew_ms = max_source_skew_ms
        self.max_view_age_ms = max_view_age_ms

    def assemble(
        self,
        *,
        relation_id: str,
        views_by_condition_id: Mapping[str, MarketView],
        created_at: datetime,
        max_source_skew_ms: int | None = None,
        max_view_age_ms: int | None = None,
    ) -> MarketGroupView | None:
        """Build a MarketGroupView when every source view is acceptably fresh."""
        skew_limit = (
            max_source_skew_ms
            if max_source_skew_ms is not None
            else self.max_source_skew_ms
        )
        age_limit = (
            max_view_age_ms
            if max_view_age_ms is not None
            else self.max_view_age_ms
        )
        if not views_by_condition_id:
            return None

        freshness_values: list[int] = []
        for view in views_by_condition_id.values():
            freshness = view.freshness.max_ms if view.freshness is not None else None
            if freshness is None or freshness > age_limit:
                return None
            freshness_values.append(freshness)

        if max(freshness_values) - min(freshness_values) > skew_limit:
            return None

        return MarketGroupView(
            group_id=f"group_{relation_id}_{created_at.isoformat()}",
            relation_id=relation_id,
            created_at=created_at,
            views_by_condition_id=dict(views_by_condition_id),
            max_source_skew_ms=skew_limit,
            metrics={"max_view_age_ms": age_limit},
        )
