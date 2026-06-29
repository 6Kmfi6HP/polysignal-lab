from __future__ import annotations

import pytest

from polysignal_lab.nautilus_runtime.market_data import (
    PolySignalMarketMetaData,
    PolySignalMarketUniverseData,
    PolySignalPriceToBeatData,
    PolySignalSpotData,
    register_polysignal_data_types,
)


def test_custom_spot_data_round_trips_dict() -> None:
    data = PolySignalSpotData(asset="BTC", symbol="BTCUSD", price=100000.0, source="polymarket_rtds", freshness_ms=10, ts_event=1, ts_init=2)

    assert PolySignalSpotData.from_dict(data.to_dict()) == data


def test_custom_price_to_beat_data_round_trips_dict() -> None:
    data = PolySignalPriceToBeatData(
        condition_id="condition-1",
        value=100000.0,
        source="anchor",
        verified=True,
        from_anchor_service=True,
        anchor_source="chainlink",
        anchor_lag_ms=12,
        ts_event=1,
        ts_init=2,
    )

    assert PolySignalPriceToBeatData.from_dict(data.to_dict()) == data


def test_custom_market_meta_data_round_trips_dict() -> None:
    data = PolySignalMarketMetaData(
        market_id="market-1",
        market_slug="slug-1",
        condition_id="condition-1",
        asset="BTC",
        timeframe="5m",
        start_ts_ns=1,
        end_ts_ns=2,
        up_token_id="up",
        down_token_id="down",
        ts_event=3,
        ts_init=4,
    )

    assert PolySignalMarketMetaData.from_dict(data.to_dict()) == data


def test_register_polysignal_data_types_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = pytest.importorskip("nautilus_trader.serialization.base")
    from polysignal_lab.nautilus_runtime import market_data as market_data_mod

    seen: set[type[object]] = set()
    calls: list[type[object]] = []

    def fake_register_serializable_type(
        cls: type[object],
        _to_dict: object,
        _from_dict: object,
    ) -> None:
        if cls in seen:
            raise KeyError(f"duplicate registration for {cls.__name__}")
        seen.add(cls)
        calls.append(cls)

    monkeypatch.setattr(market_data_mod, "_POLYSIGNAL_DATA_TYPES_REGISTERED", False)
    monkeypatch.setattr(
        "nautilus_trader.serialization.base.register_serializable_type",
        fake_register_serializable_type,
    )

    market_data_mod.register_polysignal_data_types()
    market_data_mod.register_polysignal_data_types()

    assert calls == [
        PolySignalSpotData,
        PolySignalPriceToBeatData,
        PolySignalMarketMetaData,
        PolySignalMarketUniverseData,
    ]
