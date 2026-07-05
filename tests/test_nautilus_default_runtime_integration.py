from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast

from nautilus_optional import require_nautilus

from polysignal_lab.config import Settings
from polysignal_lab.alpha.types import SpotView
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.nautilus_bridge.market_registry import InstrumentTokenMeta, PolymarketMarketRegistry
from polysignal_lab.nautilus_runtime.instrument_mapping import DEFAULT_VENUE, build_binary_option
from polysignal_lab.nautilus_runtime.node import build_trading_node
from polysignal_lab.nautilus_runtime.trading_node import PAPER_EXEC_CLIENT_ID


class _RunningNode(Protocol):
    def run(self, raise_exception: bool = False) -> None: ...
    def is_running(self) -> bool: ...
    def stop(self) -> None: ...
    def dispose(self) -> None: ...
    kernel: object


class _CacheReader(Protocol):
    def read_orders(self) -> list[dict[str, object]]: ...
    def read_fills(self) -> list[dict[str, object]]: ...
    def read_positions(self) -> list[dict[str, object]]: ...
    def read_account(self) -> object | None: ...
    def read_account_projection(self) -> dict[str, object] | None: ...
    def snapshot_portfolio(self) -> object | None: ...
    def snapshot_portfolio_projection(self) -> dict[str, object] | None: ...


class _NativeStrategyProbe(Protocol):
    submitted_orders: list[object]
    rejected_decisions: list[object]

class _LoopKernel(Protocol):
    loop: object
    data_engine: object

class _HasVenue(Protocol):
    venue: object


def _settings() -> Settings:
    settings = Settings.from_yaml("config/signal_bot.lab.yaml")
    settings.strategies.set_explicit_strategy_names(("one_cent_buy",))
    settings.paper_trading.starting_balance_usdc = 1_000.0
    settings.signal.min_confidence_to_publish = 0.0
    settings.data.polymarket.use_crypto_price_api = False
    settings.runtime.nautilus.sidecar.spot_source = "disabled"
    settings.telegram.enabled = False
    settings.telegram.dry_run = True
    return settings


def _market() -> Market:
    now = datetime.now(UTC)
    return Market(
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        asset="BTC",
        timeframe="5m",
        start_ts=now - timedelta(seconds=60),
        end_ts=now + timedelta(seconds=90),
        price_to_beat=99_900.0,
        outcome_tokens=[
            OutcomeToken(token_id="up-token", side=Side.UP, outcome_name="Up", market_id="btc-5m"),
            OutcomeToken(token_id="down-token", side=Side.DOWN, outcome_name="Down", market_id="btc-5m"),
        ],
    )


def _publish(node: _RunningNode, data: object) -> None:
    kernel = cast(_LoopKernel, node.kernel)
    loop = cast(Any, kernel.loop)
    engine = cast(Any, kernel.data_engine)
    loop.call_soon_threadsafe(engine.process, data)


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 10.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_default_runtime_sandbox_client_id_stays_distinct_from_polymarket_venue() -> None:
    assert PAPER_EXEC_CLIENT_ID != "POLYMARKET"


def test_default_runtime_fills_after_running_tick_size_precision_update(monkeypatch) -> None:
    require_nautilus()

    from nautilus_trader.data.messages import SubscribeOrderBook
    from nautilus_trader.live.factories import LiveDataClientFactory
    from nautilus_trader.model.data import BookOrder, OrderBookDelta, OrderBookDeltas
    from nautilus_trader.model.enums import BookAction, OrderSide, RecordFlag
    from nautilus_trader.model.identifiers import ClientId
    from nautilus_trader.test_kit.mocks.data import MockMarketDataClient
    from nautilus_trader.test_kit.stubs.data import TestDataStubs
    import nautilus_trader.adapters.polymarket as polymarket_mod
    instruments_by_id: dict[str, object] = {}


    class NoNetworkPolymarketClient(MockMarketDataClient):
        def subscribe(self, command) -> None:
            self._add_subscription(command.data_type)

        def subscribe_order_book_deltas(self, command: SubscribeOrderBook) -> None:
            self._add_subscription_order_book_deltas(command.instrument_id)

        def request_instrument(self, request) -> None:
            instrument = instruments_by_id.get(str(request.instrument_id))
            if instrument is None:
                return
            self._handle_instrument(
                instrument,
                request.id,
                request.start,
                request.end,
                request.params,
            )

        def connect(self) -> None:
            self._set_connected(True)

        def disconnect(self) -> None:
            self._set_connected(False)

    class NoNetworkPolymarketFactory(LiveDataClientFactory):
        @staticmethod
        def create(loop, name, config, msgbus, cache, clock):
            _ = loop, name
            venue = cast(_HasVenue, cast(object, config)).venue
            return NoNetworkPolymarketClient(ClientId(str(venue)), msgbus, cache, clock)

    monkeypatch.setattr(polymarket_mod, "PolymarketLiveDataClientFactory", NoNetworkPolymarketFactory)

    asyncio.set_event_loop(asyncio.new_event_loop())
    settings = _settings()
    market = _market()
    runtime = cast(
        dict[str, object],
        build_trading_node(
            settings,
            condition_ids=(market.condition_id,),
            markets=(market,),
        ),
    )
    node = cast(_RunningNode, runtime["node"])
    cache_reader = cast(_CacheReader, runtime["cache_reader"])
    strategy = cast(_NativeStrategyProbe, cast(list[object], runtime["strategies"])[0])
    registry = cast(PolymarketMarketRegistry, runtime["registry"])
    pair = registry.by_condition(market.condition_id)
    assert pair is not None
    token = cast(InstrumentTokenMeta | None, registry.token_meta("up-token"))
    assert token is not None
    instrument = build_binary_option(
        pair,
        token,
        tick_size=0.001,
        min_order_size=1.0,
        ts_init_ns=1,
    )
    down_token = cast(InstrumentTokenMeta | None, registry.token_meta("down-token"))
    assert down_token is not None
    down_instrument = build_binary_option(
        pair,
        down_token,
        tick_size=0.001,
        min_order_size=1.0,
        ts_init_ns=1,
    )
    instruments_by_id[str(instrument.id)] = instrument
    instruments_by_id[str(down_instrument.id)] = down_instrument

    sidecar = cast(Any, runtime["sidecar"])
    data_engine = cast(Any, cast(_LoopKernel, node.kernel).data_engine)
    trader = cast(Any, runtime["node"]).trader
    data_engine.process(instrument)
    data_engine.process(down_instrument)


    failures: list[BaseException] = []

    def run_node() -> None:
        try:
            node.run(raise_exception=True)
        except BaseException as exc:  # pragma: no cover - surfaced by assertion below
            failures.append(exc)

    thread = threading.Thread(target=run_node, daemon=True)
    thread.start()

    try:
        assert _wait_until(node.is_running, timeout=10.0)

        ts_0 = int(datetime.now(UTC).timestamp() * 1_000_000_000)
        ts_1 = ts_0 + 1_000_000
        ts_2 = ts_1 + 1_000_000
        ts_3 = ts_2 + 1_000_000
        _publish(node, instrument)
        _publish(
            node,
            TestDataStubs.quote_tick(
                instrument=instrument,
                bid_price=0.005,
                ask_price=0.05,
                bid_size=5_000.0,
                ask_size=5_000.0,
                ts_event=ts_0,
                ts_init=ts_0,
            ),
        )

        assert _wait_until(
            lambda: any(state == "RUNNING" for state in trader.strategy_states().values()),
            timeout=10.0,
        )
        assert _wait_until(
            lambda: len(data_engine.subscribed_order_book_deltas()) >= 1,
            timeout=10.0,
        )
        sidecar.update_spot(SpotView(asset="BTC", symbol="BTCUSD", price=100_000.0, source="test", freshness_ms=5))
        sidecar.update_price_to_beat(
            condition_id=market.condition_id,
            value=99_900.0,
            source="anchor",
            verified=True,
            from_anchor_service=True,
            anchor_source="test",
            anchor_lag_ms=1,
        )
        _publish(node, instrument)
        _publish(
            node,
            TestDataStubs.order_book_snapshot(
                instrument=instrument,
                bid_price=0.005,
                ask_price=0.05,
                bid_size=5_000.0,
                ask_size=5_000.0,
                ts_event=ts_1,
                ts_init=ts_1,
            ),
        )
        _publish(node, down_instrument)
        _publish(
            node,
            TestDataStubs.order_book_snapshot(
                instrument=down_instrument,
                bid_price=0.004,
                ask_price=0.51,
                bid_size=5_000.0,
                ask_size=5_000.0,
                ts_event=ts_1,
                ts_init=ts_1,
            ),
        )
        assert _wait_until(lambda: len(strategy.submitted_orders) >= 1, timeout=10.0), strategy.rejected_decisions
        assert _wait_until(lambda: len(cache_reader.read_orders()) >= 1, timeout=10.0)

        updated_instrument = build_binary_option(
            pair,
            token,
            tick_size=0.01,
            min_order_size=1.0,
            ts_init_ns=ts_2,
        )
        instruments_by_id[str(updated_instrument.id)] = updated_instrument
        _publish(node, updated_instrument)

        sell_order = BookOrder(
            side=OrderSide.SELL,
            price=updated_instrument.make_price(0.01),
            size=updated_instrument.make_qty(5_000.0),
            order_id=0,
        )
        _publish(
            node,
            OrderBookDeltas(
                instrument_id=updated_instrument.id,
                deltas=[
                    OrderBookDelta(
                        instrument_id=updated_instrument.id,
                        action=BookAction.CLEAR,
                        order=None,
                        flags=RecordFlag.F_SNAPSHOT,
                        sequence=0,
                        ts_event=ts_3,
                        ts_init=ts_3,
                    ),
                    OrderBookDelta(
                        instrument_id=updated_instrument.id,
                        action=BookAction.ADD,
                        order=sell_order,
                        flags=RecordFlag.F_SNAPSHOT | RecordFlag.F_LAST,
                        sequence=0,
                        ts_event=ts_3,
                        ts_init=ts_3,
                    ),
                ],
            ),
        )

        assert _wait_until(lambda: len(cache_reader.read_fills()) >= 1, timeout=10.0)
        assert _wait_until(lambda: len(cache_reader.read_positions()) >= 1, timeout=10.0)
        assert cache_reader.read_account() is not None
        assert cache_reader.read_account_projection() is not None
        assert cache_reader.snapshot_portfolio() is not None
        assert cache_reader.snapshot_portfolio_projection() is not None
    finally:
        try:
            node.stop()
        finally:
            thread.join(timeout=10.0)
            node.dispose()
    assert not thread.is_alive()
    assert failures == []
