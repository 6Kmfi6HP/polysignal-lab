"""
Input: __future__, __future__.annotations, polysignal_lab.config, polysignal_lab.config.Settings, polysignal_lab.config.load_settings, polysignal_lab.data.market_discovery_helpers, polysignal_lab.data.market_discovery_helpers.build_current_slot_slugs, polysignal_lab.utils, polysignal_lab.utils.utc_now
Output: build_polymarket_updown_event_slugs
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from polysignal_lab.config import Settings, load_settings
from polysignal_lab.data.market_discovery_helpers import build_current_slot_slugs
from polysignal_lab.utils import utc_now


def build_polymarket_updown_event_slugs(
    settings: Settings | None = None,
) -> list[str]:
    """Build startup slugs for current and near-future Up/Down windows.

    The official provider owns Gamma loading and periodic instrument refresh;
    this helper only scopes the initial bootstrap across configured timeframes.
    """
    resolved = settings or load_settings()
    markets = resolved.markets
    rotation = resolved.runtime.nautilus.market_rotation
    now = utc_now()
    return list(
        build_current_slot_slugs(
            assets=list(markets.assets),
            timeframes=list(markets.timeframes),
            now_ts=int(now.timestamp()),
            include_next_periods=int(rotation.include_next_periods),
            stale_grace_sec=int(rotation.stale_grace_sec),
        )
    )
