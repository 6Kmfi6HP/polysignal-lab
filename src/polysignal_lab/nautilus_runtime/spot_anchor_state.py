from __future__ import annotations

from polysignal_lab.data.anchor_price_service import (
    AnchorPriceStore,
    capture_anchor_price,
)
from polysignal_lab.data.registries import append_spot_history
from polysignal_lab.domain.anchor_price import AnchorPrice
from polysignal_lab.domain.market import Market
from polysignal_lab.domain.spot import SpotPrice


class SpotAnchorState:
    """Keep managed spot observations and optional verified anchors together.

    History storage uses the shared ``append_spot_history`` helper.
    Trading decisions still use Nautilus CustomData + Cache.
    """

    _anchor_store: AnchorPriceStore | None
    _history_by_asset: dict[str, list[SpotPrice]]
    _latest_by_key: dict[str, AnchorPrice]

    def __init__(self, anchor_store: AnchorPriceStore | None = None) -> None:
        self._anchor_store = anchor_store
        self._history_by_asset = {}
        self._latest_by_key = {}

    @property
    def enabled(self) -> bool:
        return self._anchor_store is not None

    def update(self, spot: SpotPrice) -> None:
        append_spot_history(self._history_by_asset, spot)

    def capture_for_market(self, market: Market) -> AnchorPrice | None:
        if self._anchor_store is None:
            return None
        return capture_anchor_price(
            self._history_by_asset.get(market.asset.upper(), ()),
            market,
            self._anchor_store,
            latest_by_key=self._latest_by_key,
        )
