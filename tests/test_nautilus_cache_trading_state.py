from __future__ import annotations

from types import SimpleNamespace

from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_bridge.market_catalog import (
    InstrumentTokenMeta,
    MarketCatalog,
    MarketPairMeta,
)


def _catalog() -> MarketCatalog:
    catalog = MarketCatalog()
    catalog.register(
        MarketPairMeta(
            market_id="market-1",
            market_slug="btc-updown-5m",
            condition_id="condition-1",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token", Side.UP),
            down=InstrumentTokenMeta("down-token", Side.DOWN),
        )
    )
    return catalog


def test_trading_state_is_rebuilt_from_cache_orders_positions_and_tags() -> None:
    from polysignal_lab.nautilus_runtime.cache_trading_state import (
        trading_state_from_cache,
    )

    entry = SimpleNamespace(
        client_order_id="entry-1",
        instrument_id="condition-1-up-token.POLYMARKET",
        tags=(
            "strategy=dump_hedge",
            "market_id=market-1",
            "condition_id=condition-1",
            "pair_id=market-1:dump",
            "position_id=position-1",
            "exit_tp_price=0.90",
        ),
        status="FILLED",
        price=0.40,
        filled_qty=10.0,
        avg_px=0.40,
        ts_last=1_000_000_000,
        is_open=False,
        is_closed=True,
        is_inflight=False,
    )
    position = SimpleNamespace(
        id="position-1",
        instrument_id="condition-1-up-token.POLYMARKET",
        signed_qty=10.0,
        avg_px_open=0.40,
        ts_opened=1_000_000_000,
        is_closed=False,
    )

    class Cache:
        def orders(self, **kwargs: object) -> list[object]:
            assert kwargs == {"strategy_id": "PolySignal-Composite"}
            return [entry]

        def positions_open(self, **kwargs: object) -> list[object]:
            assert kwargs == {"strategy_id": "PolySignal-Composite"}
            return [position]

        def orders_for_position(self, position_id: object) -> list[object]:
            assert str(position_id) == "position-1"
            return [entry]

    state = trading_state_from_cache(
        Cache(),
        strategy_id="PolySignal-Composite",
        registry=_catalog(),
    )

    leg = state.unhedged_leg("dump_hedge", "market-1")
    assert leg is not None
    assert leg.side is Side.UP
    assert leg.avg_entry_price == 0.40
    assert leg.quantity == 10.0
    assert leg.pair_id == "market-1:dump"
    assert state.has_market_activity("dump_hedge", "market-1") is True
    assert state.exit_thresholds("position-1") == (0.90, None)


def test_trading_state_empty_when_cache_has_no_supported_query_surface() -> None:
    from polysignal_lab.nautilus_runtime.cache_trading_state import (
        trading_state_from_cache,
    )

    state = trading_state_from_cache(
        object(),
        strategy_id="PolySignal-Composite",
        registry=_catalog(),
    )

    assert state.orders == ()
    assert state.positions == ()


def test_active_dedupe_guard_reads_cache_order_tags() -> None:
    from polysignal_lab.nautilus_runtime.cache_trading_state import (
        cache_has_active_order_dedupe_key,
    )

    order = SimpleNamespace(
        tags=("dedupe_key=signal-key",),
        is_open=True,
        is_inflight=False,
    )

    class Cache:
        def orders(self, **kwargs: object) -> list[object]:
            assert kwargs == {"strategy_id": "PolySignal-Composite"}
            return [order]

    assert cache_has_active_order_dedupe_key(
        Cache(),
        strategy_id="PolySignal-Composite",
        dedupe_key="signal-key",
    )
    order.is_open = False
    assert not cache_has_active_order_dedupe_key(
        Cache(),
        strategy_id="PolySignal-Composite",
        dedupe_key="signal-key",
    )
