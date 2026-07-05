from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing_extensions import override

from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_bridge.market_registry import (
    InstrumentTokenMeta,
    MarketPairMeta,
    PolymarketMarketRegistry,
)
from polysignal_lab.nautilus_runtime.cache_market_data import (
    NautilusCacheMarketDataProvider,
)


@dataclass(frozen=True)
class FakeLevel:
    price: float
    size: float


class FakeBook:
    def __init__(self) -> None:
        self.bids: list[FakeLevel] = [FakeLevel(price=0.48, size=10.0)]
        self.asks: list[FakeLevel] = [
            FakeLevel(price=0.52, size=11.0),
            FakeLevel(price=0.53, size=12.0),
        ]
        self.last_trade_price: float = 0.51
        self.last_trade_size: float = 2.0
        self.last_trade_timestamp: str = "2026-07-05T00:00:00Z"
        self.received_at: datetime = datetime.now(UTC) - timedelta(milliseconds=25)


class FakeTrade:
    price: float = 0.51
    size: float = 2.0
    aggressor_side: str = "BUYER"
    ts_event: datetime | int = datetime(2026, 7, 5, tzinfo=UTC)


class FakeCache:
    def __init__(self, instrument_id: str) -> None:
        self.instrument_id: str = instrument_id
        self.book: FakeBook = FakeBook()
        self.requested: list[object] = []

    def order_book(self, instrument_id: object) -> FakeBook | None:
        self.requested.append(instrument_id)
        return self.book if str(instrument_id) == self.instrument_id else None

    def trade_ticks(self, instrument_id: object) -> Sequence[FakeTrade]:
        return [FakeTrade()] if str(instrument_id) == self.instrument_id else []


def _registry() -> PolymarketMarketRegistry:
    registry = PolymarketMarketRegistry()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta(
                instrument_id="condition-btc-5m-up.POLYMARKET",
                token_id="up-token",
                side=Side.UP,
            ),
            down=InstrumentTokenMeta(
                instrument_id="condition-btc-5m-down.POLYMARKET",
                token_id="down-token",
                side=Side.DOWN,
            ),
        )
    )
    return registry


def test_cache_market_data_provider_reads_book_without_local_cache() -> None:
    instrument_id = "condition-btc-5m-up.POLYMARKET"
    provider = NautilusCacheMarketDataProvider(
        FakeCache(instrument_id),
        registry=_registry(),
    )

    view = provider.book_for_token("up-token")

    assert view is not None
    assert view.token_id == "up-token"
    assert view.best_bid == 0.48
    assert view.best_ask == 0.52
    assert view.spread == 0.04
    assert view.ask_levels == ((0.52, 11.0), (0.53, 12.0))
    assert view.last_trade_price == 0.51
    assert view.last_trade_size == 2.0
    assert view.last_trade_timestamp == "2026-07-05T00:00:00Z"
    assert view.freshness_ms is not None
    assert view.freshness_ms >= 0


def test_cache_market_data_provider_reads_trades_without_trade_deque() -> None:
    instrument_id = "condition-btc-5m-up.POLYMARKET"
    provider = NautilusCacheMarketDataProvider(
        FakeCache(instrument_id),
        registry=_registry(),
    )

    trades = tuple(provider.trades_for_token("up-token"))

    assert len(trades) == 1
    assert trades[0].price == 0.51
    assert trades[0].size == 2.0
    assert trades[0].side == "BUYER"
    assert trades[0].ts == datetime(2026, 7, 5, tzinfo=UTC)


def test_cache_market_data_provider_converts_nautilus_trade_ns_timestamp() -> None:
    instrument_id = "condition-btc-5m-up.POLYMARKET"
    expected = datetime(2026, 7, 5, tzinfo=UTC)

    class NsTrade(FakeTrade):
        price: float = 0.51
        size: float = 2.0
        aggressor_side: str = "BUYER"
        ts_event: datetime | int = int(expected.timestamp() * 1_000_000_000)

    class NsCache(FakeCache):
        @override
        def trade_ticks(self, instrument_id: object) -> list[NsTrade]:
            return [NsTrade()] if str(instrument_id) == self.instrument_id else []

    provider = NautilusCacheMarketDataProvider(
        NsCache(instrument_id),
        registry=_registry(),
    )

    trades = tuple(provider.trades_for_token("up-token"))

    assert len(trades) == 1
    assert trades[0].ts == expected

def test_cache_market_data_provider_returns_none_for_unknown_token() -> None:
    provider = NautilusCacheMarketDataProvider(
        FakeCache("condition-btc-5m-up.POLYMARKET"),
        registry=_registry(),
    )

    assert provider.book_for_token("missing-token") is None
    assert tuple(provider.trades_for_token("missing-token")) == ()
