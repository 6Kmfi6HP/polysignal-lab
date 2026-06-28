from __future__ import annotations

import pytest

from polysignal_lab.nautilus_runtime.market_data import PolySignalMarketUniverseData


def test_market_universe_data_round_trips() -> None:
    payload = PolySignalMarketUniverseData(
        epoch=2,
        active_condition_ids=("c1", "c2"),
        entered_condition_ids=("c2",),
        exited_condition_ids=("c0",),
        condition_to_up_token={"c1": "up-1", "c2": "up-2"},
        condition_to_down_token={"c1": "down-1", "c2": "down-2"},
        condition_to_asset={"c1": "BTC", "c2": "ETH"},
        condition_to_timeframe={"c1": "5m", "c2": "15m"},
        ts_event=11,
        ts_init=12,
    )

    serialized = payload.to_dict()
    restored = PolySignalMarketUniverseData.from_dict(serialized)

    assert serialized["active_condition_ids"] == ["c1", "c2"]
    assert serialized["entered_condition_ids"] == ["c2"]
    assert serialized["exited_condition_ids"] == ["c0"]
    assert restored == payload
    assert restored.active_condition_ids == ("c1", "c2")
    assert restored.condition_to_up_token["c2"] == "up-2"
    assert restored.condition_to_timeframe["c1"] == "5m"


def test_market_universe_data_is_immutable() -> None:
    payload = PolySignalMarketUniverseData(
        epoch=2,
        active_condition_ids=("c1", "c2"),
        entered_condition_ids=("c2",),
        exited_condition_ids=("c0",),
        condition_to_up_token={"c1": "up-1", "c2": "up-2"},
        condition_to_down_token={"c1": "down-1", "c2": "down-2"},
        condition_to_asset={"c1": "BTC", "c2": "ETH"},
        condition_to_timeframe={"c1": "5m", "c2": "15m"},
        ts_event=11,
        ts_init=12,
    )

    with pytest.raises(AttributeError, match="immutable"):
        payload.active_condition_ids = ("c3",)  # type: ignore[misc]

    with pytest.raises(TypeError):
        payload.condition_to_up_token["c3"] = "up-3"
