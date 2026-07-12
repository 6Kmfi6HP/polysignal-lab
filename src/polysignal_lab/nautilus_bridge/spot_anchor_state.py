"""Application spot state used by the Nautilus market-rotation bridge."""

from __future__ import annotations

from polysignal_lab.data.anchor_price_service import AnchorPriceService, AnchorPriceStore
from polysignal_lab.data.state import SpotRegistry
from polysignal_lab.domain.market import Market
from polysignal_lab.domain.spot import SpotPrice


class SpotAnchorState:
    """Keep managed spot observations and optional verified anchors together."""

    def __init__(self, anchor_store: AnchorPriceStore | None = None) -> None:
        self.registry = SpotRegistry()
        self.anchor_service: AnchorPriceService | None = (
            AnchorPriceService(self.registry, anchor_store)
            if anchor_store is not None
            else None
        )

    @property
    def enabled(self) -> bool:
        return self.anchor_service is not None

    def update(self, spot: SpotPrice) -> None:
        self.registry.update(spot)

    def capture_for_market(self, market: Market) -> object | None:
        if self.anchor_service is None:
            return None
        return self.anchor_service.capture_for_market(market)
