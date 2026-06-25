from __future__ import annotations

from datetime import UTC, datetime

from polysignal_lab.alpha.types import SpotView
from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar


def test_sidecar_stores_spot_by_uppercase_asset() -> None:
    sidecar = ExternalDataSidecar()
    spot = SpotView(asset="btc", symbol="BTCUSD", price=100120.0, source="polymarket_rtds", freshness_ms=15)

    sidecar.update_spot(spot)

    assert sidecar.spot_for("BTC") == spot
    assert sidecar.spot_for("btc") == spot


def test_sidecar_stores_price_to_beat_metadata() -> None:
    sidecar = ExternalDataSidecar()
    sidecar.update_price_to_beat(
        condition_id="condition-btc-5m",
        value=100000.0,
        source="anchor",
        verified=True,
        from_anchor_service=True,
        anchor_source="chainlink",
        anchor_lag_ms=25,
    )

    ptb = sidecar.ptb_for("condition-btc-5m")

    assert ptb is not None
    assert ptb.value == 100000.0
    assert ptb.source == "anchor"
    assert ptb.verified is True
    assert ptb.from_anchor_service is True
    assert ptb.anchor_source == "chainlink"
    assert ptb.anchor_lag_ms == 25
    assert isinstance(ptb.updated_at, datetime)
    assert ptb.updated_at.tzinfo == UTC
