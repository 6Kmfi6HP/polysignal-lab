"""
Input: __future__, __future__.annotations, dataclasses, dataclasses.dataclass, dataclasses.field
Output: MarketSubscriptionState
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class MarketSubscriptionState:
    """Track wire subscriptions separately from active-condition membership."""

    wire_condition_ids: set[str] = field(default_factory=set)
    wire_instrument_ids: set[str] = field(default_factory=set)
    pending_metadata_condition_ids: set[str] = field(default_factory=set)
    pending_subscribe_condition_ids: set[str] = field(default_factory=set)
    retained_wire_condition_ids: set[str] = field(default_factory=set)
