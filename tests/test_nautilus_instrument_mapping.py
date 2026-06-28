from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol, cast

import pytest

from nautilus_optional import require_nautilus
from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_bridge.market_registry import InstrumentTokenMeta, MarketPairMeta


class _BinaryOptionLike(Protocol):
    id: object
    price_increment: object
    price_precision: int
    size_increment: object
    size_precision: int
    min_quantity: object
    expiration_ns: int
    ts_event: int
    ts_init: int
    info: dict[str, object]


def _pair() -> MarketPairMeta:
    return MarketPairMeta(
        market_id="m1",
        market_slug="btc-updown-1700000000",
        condition_id="0xcondition",
        asset="BTC",
        timeframe="5m",
        start_ts=datetime(2023, 11, 14, 22, 8, 20, tzinfo=UTC),
        end_ts=datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC),
        up=InstrumentTokenMeta(instrument_id="123456789", token_id="123456789", side=Side.UP),
        down=InstrumentTokenMeta(instrument_id="987654321", token_id="987654321", side=Side.DOWN),
    )


def test_instrument_id_for_token_is_stable() -> None:
    from polysignal_lab.nautilus_runtime.instrument_mapping import instrument_id_for_token

    assert instrument_id_for_token(" 123456789 ") == "123456789.POLYSIGNAL_PM_PAPER"


@pytest.mark.parametrize("bad_tick", [0.0, -0.001])
def test_build_binary_option_rejects_invalid_tick_size(bad_tick: float) -> None:
    require_nautilus()
    from polysignal_lab.nautilus_runtime.instrument_mapping import build_binary_option

    with pytest.raises(ValueError, match="tick_size must be positive"):
        build_binary_option(_pair(), _pair().up, tick_size=bad_tick, min_order_size=None, ts_init_ns=1)


def test_build_binary_option_sets_precision_and_metadata() -> None:
    require_nautilus()
    from polysignal_lab.nautilus_runtime.instrument_mapping import build_binary_option

    pair = _pair()
    instrument = cast(
        _BinaryOptionLike,
        build_binary_option(pair, pair.up, tick_size=None, min_order_size=None, ts_init_ns=7),
    )

    assert str(instrument.id) == "123456789.POLYSIGNAL_PM_PAPER"
    assert str(instrument.price_increment) == "0.001"
    assert instrument.price_precision == 3
    assert str(instrument.size_increment) == "0.000001"
    assert instrument.size_precision == 6
    assert instrument.min_quantity is not None
    assert str(instrument.min_quantity) == "5"
    assert instrument.expiration_ns == 1_700_000_000_000_000_000
    assert instrument.ts_event == 7
    assert instrument.ts_init == 7
    assert instrument.info["condition_id"] == "0xcondition"
    assert instrument.info["market_slug"] == "btc-updown-1700000000"
    assert instrument.info["side"] == "UP"


def test_build_binary_option_preserves_explicit_token_venue() -> None:
    require_nautilus()
    from polysignal_lab.nautilus_runtime.instrument_mapping import build_binary_option

    pair = _pair()
    token = InstrumentTokenMeta(
        instrument_id="123456789.POLYMARKET",
        token_id="123456789",
        side=Side.UP,
    )

    instrument = cast(
        _BinaryOptionLike,
        build_binary_option(pair, token, tick_size=None, min_order_size=None, ts_init_ns=7),
    )

    assert str(instrument.id) == "123456789.POLYMARKET"
