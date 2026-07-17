"""
Input: __future__, __future__.annotations, datetime, datetime.UTC, datetime.datetime, pytest, polysignal_lab.alpha.types, polysignal_lab.alpha.types.SideBookView, polysignal_lab.alpha.types.TradeView, polysignal_lab.domain.enums, polysignal_lab.domain.enums.Side
Output: test_assembler_builds_coherent_market_view, test_assembler_returns_none_when_down_leg_missing, test_assembler_builds_view_when_optional_custom_data_missing, test_strategy_custom_data_state_applies_snapshots_for_assembler, test_price_to_beat_state_uses_event_time, test_price_to_beat_state_rejects_missing_event_time, FakeBookProvider
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from datetime import UTC, datetime

import pytest

from polysignal_lab.alpha.types import SideBookView, TradeView
from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog, MarketPairMeta
from polysignal_lab.nautilus_runtime.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.custom_data_state import StrategyCustomDataState
from nautilus_trader.core.nautilus_pyo3 import PolymarketRtdsCryptoPrice
from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalPriceToBeatData
from factories import MarketFactoryConfig, sample_market


class FakeBookProvider:
    def __init__(self) -> None:
        self.books: dict[str, SideBookView] = {}
        self.trades: dict[str, tuple[TradeView, ...]] = {}

    def book_for_token(self, token_id: str, *, now: datetime) -> SideBookView | None:
        _ = now
        return self.books.get(token_id)

    def trades_for_token(self, token_id: str) -> tuple[TradeView, ...]:
        return self.trades.get(token_id, ())


def _components() -> tuple[MarketViewAssembler, MarketPairMeta, FakeBookProvider, StrategyCustomDataState]:
    market = sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m", seconds_to_close=60, price_to_beat=100000.0))
    pair = MarketPairMeta.from_market(market)
    catalog = MarketCatalog()
    catalog.register(pair)
    books = FakeBookProvider()
    custom_data = StrategyCustomDataState()
    assembler = MarketViewAssembler(catalog=catalog, books=books, custom_data=custom_data)
    return assembler, pair, books, custom_data


def _apply_custom_data(custom_data: StrategyCustomDataState, condition_id: str) -> None:
    custom_data.apply(
        PolymarketRtdsCryptoPrice("BTCUSD", "100120.0", 0, 0, 1, int(datetime(2026, 1, 1, tzinfo=UTC).timestamp() * 1_000_000_000) - 30_000_000)
    )
    custom_data.apply(
        PolySignalPriceToBeatData(
            condition_id=condition_id,
            value=100000.0,
            source="anchor",
            verified=True,
            from_anchor_service=True,
            anchor_source="chainlink",
            anchor_lag_ms=40,
            ts_event=3,
            ts_init=4,
        )
    )


def test_assembler_builds_coherent_market_view() -> None:
    assembler, pair, books, custom_data = _components()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    books.books[pair.up.token_id] = SideBookView(pair.up.token_id, best_bid=0.81, best_ask=0.82, spread=0.01, freshness_ms=10)
    books.books[pair.down.token_id] = SideBookView(pair.down.token_id, best_bid=0.17, best_ask=0.18, spread=0.01, freshness_ms=20)
    books.trades[pair.up.token_id] = (TradeView(price=0.82, size=5.0, side="BUY", ts=now),)
    _apply_custom_data(custom_data, pair.condition_id)

    view = assembler.build(pair.condition_id, created_at=now)

    assert view is not None
    assert view.market_id == pair.market_id
    assert view.condition_id == pair.condition_id
    assert view.ask_for(Side.UP) == 0.82
    assert view.ask_for(Side.DOWN) == 0.18
    assert view.spot is not None
    assert view.spot.price == 100120.0
    assert view.price_to_beat == 100000.0
    assert view.up_trades == books.trades[pair.up.token_id]
    assert view.metrics["price_to_beat_verified"] is True
    assert view.metrics["price_to_beat_from_anchor_service"] is True
    assert view.freshness.max_ms == 30


def test_assembler_returns_none_when_down_leg_missing() -> None:
    assembler, pair, books, custom_data = _components()
    books.books[pair.up.token_id] = SideBookView(pair.up.token_id, best_bid=0.81, best_ask=0.82, spread=0.01, freshness_ms=10)
    _apply_custom_data(custom_data, pair.condition_id)

    assert assembler.build(
        pair.condition_id,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    ) is None


def test_assembler_builds_view_when_optional_custom_data_missing() -> None:
    assembler, pair, books, _custom_data = _components()
    books.books[pair.up.token_id] = SideBookView(pair.up.token_id, best_bid=0.81, best_ask=0.82, spread=0.01, freshness_ms=10)
    books.books[pair.down.token_id] = SideBookView(pair.down.token_id, best_bid=0.17, best_ask=0.18, spread=0.01, freshness_ms=20)

    view = assembler.build(
        pair.condition_id,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert view is not None
    assert view.spot is None
    assert view.price_to_beat is None
    assert view.freshness.spot_ms is None
    assert "spot_source" not in view.metrics
    assert "price_to_beat_source" not in view.metrics


def test_strategy_custom_data_state_applies_snapshots_for_assembler() -> None:
    state = StrategyCustomDataState()

    _apply_custom_data(state, "condition-1")

    spot = state.spot_for("btc")
    ptb = state.ptb_for("condition-1")
    assert spot is not None
    assert spot.asset == "BTC"
    assert ptb is not None
    assert ptb.verified is True


def test_price_to_beat_state_uses_event_time() -> None:
    ts_event = 1_788_451_200_123_456_789
    data = PolySignalPriceToBeatData(
        condition_id="condition-1",
        value=99_500.0,
        source="anchor",
        verified=True,
        from_anchor_service=True,
        anchor_source="chainlink",
        anchor_lag_ms=7,
        ts_event=ts_event,
        ts_init=ts_event + 10,
    )

    state = StrategyCustomDataState()
    state.apply(data)

    ptb = state.ptb_for("condition-1")
    assert ptb is not None
    assert ptb.updated_at == datetime.fromtimestamp(ts_event / 1_000_000_000, UTC)


def test_price_to_beat_state_rejects_missing_event_time() -> None:
    state = StrategyCustomDataState()
    data = PolySignalPriceToBeatData(
        condition_id="condition-1",
        value=99_500.0,
        source="anchor",
        ts_event=0,
        ts_init=0,
    )

    with pytest.raises(ValueError, match="ts_event"):
        state.apply(data)

    assert state.ptb_for("condition-1") is None
