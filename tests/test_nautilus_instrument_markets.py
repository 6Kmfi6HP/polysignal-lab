from datetime import UTC, datetime, timedelta

from nautilus_polymarket_fixtures import (
    polymarket_binary_instrument,
    rust_shaped_polymarket_binary_instrument,
)

from polysignal_lab.config import MarketConfig
from polysignal_lab.domain.enums import MarketStatus, Side
from polysignal_lab.nautilus_runtime.instrument_markets import (
    PolymarketInstrumentMarketBuilder,
)


def test_instrument_market_builder_emits_binary_market_after_pair() -> None:
    builder = PolymarketInstrumentMarketBuilder(
        MarketConfig(assets=["BTC"], timeframes=["5m"])
    )

    assert builder.add(polymarket_binary_instrument("uptoken", "Up")) is None
    market = builder.add(polymarket_binary_instrument("downtoken", "Down"))

    assert market is not None
    assert market.market_id == "market-1"
    assert market.condition_id == "0xcondition1"
    assert market.asset == "BTC"
    assert market.timeframe == "5m"
    assert market.token_for(Side.UP).token_id == "uptoken"
    assert market.token_for(Side.DOWN).token_id == "downtoken"


def test_unknown_market_can_become_active_without_terminal_tombstone() -> None:
    builder = PolymarketInstrumentMarketBuilder(
        MarketConfig(assets=["BTC"], timeframes=["5m"])
    )

    assert (
        builder.add(polymarket_binary_instrument("uptoken", "Up", active=False)) is None
    )
    unknown = builder.add(
        polymarket_binary_instrument("downtoken", "Down", active=False)
    )

    assert unknown is not None
    assert unknown.status is MarketStatus.UNKNOWN
    assert builder.terminal_condition_ids() == ()

    active = builder.add(polymarket_binary_instrument("uptoken", "Up"))

    assert active is not None
    assert active.status is MarketStatus.ACTIVE
    assert builder.terminal_condition_ids() == ()


def test_official_rust_binary_option_info_builds_active_market() -> None:
    """Issue #20: Rust adapter info omits active/endDate; must still be tradable."""
    builder = PolymarketInstrumentMarketBuilder(
        MarketConfig(assets=["BTC"], timeframes=["5m"])
    )
    start = datetime.now(UTC)
    end = start + timedelta(minutes=4)

    assert (
        builder.add(
            rust_shaped_polymarket_binary_instrument(
                "up1", "Up", event_start=start, event_end=end
            )
        )
        is None
    )
    market = builder.add(
        rust_shaped_polymarket_binary_instrument(
            "down1", "Down", event_start=start, event_end=end
        )
    )

    assert market is not None
    assert market.is_active is True
    assert market.status is MarketStatus.ACTIVE
    assert market.asset == "BTC"
    assert market.timeframe == "5m"
    assert market.end_ts is not None
    assert market.token_for(Side.UP).token_id == "up1"
    assert market.token_for(Side.DOWN).token_id == "down1"


# --- issue69: projected payloads carry the instrument's authoritative tick ---


def test_rust_instrument_payload_carries_canonical_minimum_tick() -> None:
    """Official Rust instruments (no gamma payload) must still project the
    exact minimum tick so downstream Gamma-shaped re-parses keep the SAME
    price precision as the instrument."""
    from nautilus_trader._libnautilus.model import (
        AssetClass,
        BinaryOption,
        Currency,
        InstrumentId,
        Price,
        Quantity,
        Symbol,
    )

    builder = PolymarketInstrumentMarketBuilder(
        MarketConfig(assets=["BTC"], timeframes=["5m"])
    )
    start = datetime.now(UTC)
    end = start + timedelta(minutes=5)
    price_increment = Price.from_str("0.001")
    size_increment = Quantity.from_str("0.000001")

    def rust_instrument(token_id: str, outcome: str) -> object:
        return BinaryOption(
            instrument_id=InstrumentId.from_str(
                f"0xcondition1-{token_id}.POLYMARKET"
            ),
            raw_symbol=Symbol(token_id),
            asset_class=AssetClass.ALTERNATIVE,
            currency=Currency.from_str("USDC"),
            activation_ns=int(start.timestamp() * 1e9),
            expiration_ns=int(end.timestamp() * 1e9),
            price_precision=price_increment.precision,
            size_precision=size_increment.precision,
            price_increment=price_increment,
            size_increment=size_increment,
            ts_event=0,
            ts_init=0,
            outcome=outcome,
            info={
                "token_id": token_id,
                "condition_id": "0xcondition1",
                "market_id": "m1",
                "market_slug": "btc-updown-5m-1",
            },
        )

    assert builder.add(rust_instrument("uptoken", "Up")) is None
    market = builder.add(rust_instrument("downtoken", "Down"))
    assert market is not None
    raw = market.raw
    # market raw payload must expose the tick for downstream consumers
    assert raw.get("minimum_tick_size") == "0.001"
    assert raw.get("minimumTickSize") == "0.001"
    assert raw.get("orderPriceMinTickSize") == "0.001"
