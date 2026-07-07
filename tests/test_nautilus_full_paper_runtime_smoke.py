"""
Input: __future__, __future__.annotations, asyncio, sys, datetime, datetime.UTC, datetime.datetime, types, types.SimpleNamespace, typing
Output: test_full_paper_runtime_builds_node_without_live_execution, test_build_live_node_uses_cache_backed_market_data_provider, test_runtime_sidecar_actor_and_native_strategy_bridge_to_order_submit, test_market_rotation_actor_rotates_single_native_strategy_without_rebuild
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest

from polysignal_lab.alpha.types import AlphaDecision, OrderIntentSpec
from polysignal_lab.config import Settings
from polysignal_lab.data.price_to_beat_provider import PriceToBeatResult
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.nautilus_runtime.instrument_mapping import polymarket_instrument_id
from polysignal_lab.nautilus_runtime.live_node import PAPER_EXEC_CLIENT_ID, POLYMARKET_CLIENT_ID


def _install_fake_polymarket_id_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    def helper(condition_id: str, token_id: str) -> str:
        return f"{condition_id}-{token_id}.POLYMARKET"

    monkeypatch.setitem(
        sys.modules,
        "nautilus_trader.adapters.polymarket",
        SimpleNamespace(get_polymarket_instrument_id=helper),
    )


def _sample_market() -> Market:
    return Market(
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        asset="BTC",
        timeframe="5m",
        outcome_tokens=[
            OutcomeToken(token_id="up-token", side=Side.UP, outcome_name="Up", market_id="btc-5m"),
            OutcomeToken(token_id="down-token", side=Side.DOWN, outcome_name="Down", market_id="btc-5m"),
        ],
    )


def _fake_live_config_import_callable(module_name: str, attr_name: str):
    def factory(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(args=args, module_name=module_name, attr_name=attr_name, **kwargs)

    return factory


def _patch_live_node_builder_fakes(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    import polysignal_lab.nautilus_runtime.live_node as live_node_mod
    import polysignal_lab.nautilus_runtime.node as node_mod
    import polysignal_lab.nautilus_runtime.node_builder as node_builder_mod

    def empty_rows() -> list[object]:
        return []

    class FakePolymarketLiveDataClientFactory:
        pass

    class FakeSandboxLiveExecClientFactory:
        pass

    class FakeTrader:
        def __init__(self) -> None:
            self.strategies: list[object] = []
            self.actors: list[object] = []
            self.cache: SimpleNamespace = SimpleNamespace(orders=empty_rows, fills=empty_rows, positions=empty_rows)
            self.portfolio: SimpleNamespace = SimpleNamespace(id="PF-SMOKE")

        def add_strategy(self, strategy: object) -> None:
            self.strategies.append(strategy)

        def add_actor(self, actor: object) -> None:
            self.actors.append(actor)

    class FakeBuiltLiveNode:
        def __init__(self, builder: "FakeBuilder") -> None:
            self.builder = builder
            self.trader: FakeTrader = FakeTrader()
            self.cache = self.trader.cache
            self.portfolio = self.trader.portfolio
            self.built = False

        def build(self) -> None:
            self.built = True

        def run(self) -> None:
            pass

    class FakeBuilder:
        def __init__(self, trader_id_text: str, trader_id: object, environment: object) -> None:
            self.trader_id_text = trader_id_text
            self.trader_id = trader_id
            self.environment = environment
            self.cache_config: object | None = None
            self.data_engine_config: object | None = None
            self.exec_engine_config: object | None = None
            self.data_clients: list[tuple[str | None, object, object]] = []
            self.exec_clients: list[tuple[str | None, object, object]] = []

        def with_cache_config(self, config: object) -> "FakeBuilder":
            self.cache_config = config
            return self

        def with_data_engine_config(self, config: object) -> "FakeBuilder":
            self.data_engine_config = config
            return self

        def with_exec_engine_config(self, config: object) -> "FakeBuilder":
            self.exec_engine_config = config
            return self

        def add_data_client(self, name: str | None, factory: object, config: object) -> "FakeBuilder":
            self.data_clients.append((name, factory, config))
            return self

        def add_exec_client(self, name: str | None, factory: object, config: object) -> "FakeBuilder":
            self.exec_clients.append((name, factory, config))
            return self

        def build(self) -> FakeBuiltLiveNode:
            return FakeBuiltLiveNode(self)

    class FakeLiveNode:
        @classmethod
        def builder(cls, trader_id_text: str, trader_id: object, environment: object) -> FakeBuilder:
            return FakeBuilder(trader_id_text, trader_id, environment)

    monkeypatch.setattr(node_mod, "LiveNode", FakeLiveNode)
    monkeypatch.setattr(node_builder_mod, "LiveNode", FakeLiveNode)
    monkeypatch.setattr(
        node_mod,
        "PolymarketInstrumentProviderConfig",
        lambda *, load_ids: SimpleNamespace(load_ids=load_ids),
    )
    monkeypatch.setattr(
        node_builder_mod,
        "PolymarketInstrumentProviderConfig",
        lambda *, load_ids: SimpleNamespace(load_ids=load_ids),
    )
    monkeypatch.setattr(live_node_mod, "_import_callable", _fake_live_config_import_callable)
    monkeypatch.setattr(live_node_mod, "LiveNode", FakeLiveNode)
    monkeypatch.setattr(live_node_mod, "TraderId", lambda value: f"TraderId:{value}")
    monkeypatch.setattr(live_node_mod, "Environment", SimpleNamespace(SANDBOX="SANDBOX"))
    monkeypatch.setattr(live_node_mod, "PolymarketLiveDataClientFactory", FakePolymarketLiveDataClientFactory)
    monkeypatch.setattr(live_node_mod, "SandboxLiveExecClientFactory", FakeSandboxLiveExecClientFactory)
    from polysignal_lab.nautilus_runtime.market_rotation import MarketRotationActor
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    monkeypatch.setattr(
        node_mod,
        "_load_runtime_classes",
        lambda: (PolySignalNativeStrategy, MarketRotationActor),
    )
    monkeypatch.setattr(
        node_builder_mod,
        "_load_runtime_classes",
        lambda: (PolySignalNativeStrategy, MarketRotationActor),
    )

    return SimpleNamespace(
        node_mod=node_mod,
        polymarket_factory=FakePolymarketLiveDataClientFactory,
        sandbox_factory=FakeSandboxLiveExecClientFactory,
    )


def test_full_paper_runtime_builds_node_without_live_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    from polysignal_lab.nautilus_runtime.cache_reader import NautilusCacheReader

    _install_fake_polymarket_id_helper(monkeypatch)
    fakes = _patch_live_node_builder_fakes(monkeypatch)

    runtime = fakes.node_mod.build_live_node(
        Settings(),
        condition_ids=("condition-btc-5m",),
        markets=(_sample_market(),),
    )

    node = runtime["node"]
    builder = node.builder
    assert runtime["node"] is node
    assert builder.trader_id_text == "PolySignal-Nautilus-001"
    assert builder.trader_id == "TraderId:PolySignal-Nautilus-001"
    assert builder.environment == "SANDBOX"
    assert builder.data_clients[0][0] == POLYMARKET_CLIENT_ID
    assert builder.data_clients[0][1] is fakes.polymarket_factory
    assert builder.exec_clients[0][0] == PAPER_EXEC_CLIENT_ID
    assert builder.exec_clients[0][1] is fakes.sandbox_factory
    assert builder.exec_clients[0][0] != POLYMARKET_CLIENT_ID
    assert node.built is True
    instrument_config = cast(SimpleNamespace, runtime["config"])
    assert instrument_config.load_ids == frozenset(
        {
            f"{_sample_market().condition_id}-up-token.POLYMARKET",
            f"{_sample_market().condition_id}-down-token.POLYMARKET",
        }
    )
    data_config = builder.data_clients[0][2]
    assert getattr(data_config, "instrument_config") is instrument_config
    exec_config = builder.exec_clients[0][2]
    assert getattr(exec_config, "venue") == POLYMARKET_CLIENT_ID
    assert "paper_client" not in runtime
    assert "matching_client" not in runtime
    cache_reader = runtime["cache_reader"]
    assert isinstance(cache_reader, NautilusCacheReader)
    assert cache_reader.read_orders() == []
    assert cache_reader.read_fills() == []
    assert cache_reader.read_positions() == []
    assert cache_reader.snapshot_portfolio() is not None


def test_build_live_node_uses_cache_backed_market_data_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    from polysignal_lab.nautilus_runtime.cache_market_data import NautilusCacheMarketDataProvider

    _install_fake_polymarket_id_helper(monkeypatch)
    fakes = _patch_live_node_builder_fakes(monkeypatch)

    runtime = fakes.node_mod.build_live_node(Settings(), markets=(_sample_market(),))

    assembler = cast(SimpleNamespace, runtime["assembler"])
    assert isinstance(assembler.books, NautilusCacheMarketDataProvider)
    assert "book_data_provider" not in runtime


def test_runtime_sidecar_actor_and_native_strategy_bridge_to_order_submit(monkeypatch: pytest.MonkeyPatch) -> None:
    import polysignal_lab.nautilus_runtime.market_rotation as rotation_mod
    from polysignal_lab.domain.spot import SpotPrice
    from polysignal_lab.nautilus_runtime.custom_data_state import StrategyCustomDataState
    from polysignal_lab.nautilus_bridge.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
        MarketCatalog,
    )
    from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
    from polysignal_lab.nautilus_runtime.cache_market_data import NautilusCacheMarketDataProvider
    from polysignal_lab.nautilus_runtime.market_data import (
        PolySignalMarketMetaData,
        PolySignalPriceToBeatData,
        PolySignalSpotData,
    )
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy
    from polysignal_lab.nautilus_runtime.market_rotation import MarketRotationActor

    _install_fake_polymarket_id_helper(monkeypatch)

    published: list[object] = []
    ptb_ran = False

    class DummyTask:
        def cancel(self) -> None:
            return None

    def fake_create_task(coro):
        nonlocal ptb_ran
        code = getattr(coro, "cr_code", None)
        code_name = code.co_name if code is not None else ""
        if code_name == "_publish_price_to_beat":
            asyncio.run(coro)
            ptb_ran = True
        else:
            coro.close()
        return DummyTask()

    class FakeLevel:
        def __init__(self, price: float, size: float) -> None:
            self.price = price
            self.size = size

    class FakeOrderBook:
        def __init__(self, bids, asks) -> None:
            self.bids = bids
            self.asks = asks
            self.last_trade_price = None
            self.last_trade_size = None
            self.last_trade_timestamp = None
            self.received_at = datetime.now(UTC)

    class FakeCache:
        def __init__(self) -> None:
            self.books = {
                "condition-btc-5m-up-token.POLYMARKET": FakeOrderBook(
                    bids=[FakeLevel(0.49, 20.0)],
                    asks=[FakeLevel(0.50, 20.0), FakeLevel(0.52, 20.0)],
                ),
                "condition-btc-5m-down-token.POLYMARKET": FakeOrderBook(
                    bids=[FakeLevel(0.48, 20.0)],
                    asks=[FakeLevel(0.51, 20.0), FakeLevel(0.53, 20.0)],
                ),
            }

        def order_book(self, instrument_id):
            return self.books[instrument_id]

    class FakeOrderFactory:
        def limit(self, **kwargs):
            return kwargs

    class FakeCore:
        def evaluate(self, view):
            return [
                AlphaDecision(
                    strategy="ptb_diff",
                    asset=view.asset,
                    timeframe=view.timeframe,
                    market_id=view.market_id,
                    market_slug=view.market_slug,
                    condition_id=view.condition_id,
                    token_id="up-token",
                    side=Side.UP,
                    confidence=0.8,
                    entry_reference_price=0.50,
                    max_entry_price=0.52,
                    seconds_to_close=60,
                    data_freshness_ms=20,
                    reason_codes=("TEST",),
                    metrics={},
                    order_intent=OrderIntentSpec(intent=OrderIntent.TAKER_FOK, pair_id="pair-1"),
                    hedge_leg=False,
                )
            ]

    class FakePolicy:
        def decide(self, decision, view):
            from polysignal_lab.domain.signal import SignalCandidate
            from polysignal_lab.nautilus_runtime.decision_policy import ApprovedDecision

            candidate = SignalCandidate.build(
                strategy=decision.strategy,
                asset=decision.asset,
                timeframe=decision.timeframe,
                market_id=decision.market_id,
                market_slug=decision.market_slug,
                condition_id=decision.condition_id,
                token_id=decision.token_id,
                side=decision.side,
                confidence=decision.confidence,
                entry_reference_price=decision.entry_reference_price,
                max_entry_price=decision.max_entry_price,
                seconds_to_close=decision.seconds_to_close,
                data_freshness_ms=decision.data_freshness_ms,
                reason_codes=list(decision.reason_codes),
                metrics=dict(decision.metrics),
                order_intent=decision.order_intent.intent,
                expiry_seconds=None,
                pair_id=decision.order_intent.pair_id,
                hedge_leg=decision.hedge_leg,
            )
            return ApprovedDecision(signal=candidate)

    class FakeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.cache = FakeCache()
            self.order_factory = FakeOrderFactory()
            self.submitted = []

        def submit_order(self, order):
            self.submitted.append(order)

    market = _sample_market()
    registry = MarketCatalog()
    registry.register(
        MarketPairMeta(
            market_id=market.market_id,
            market_slug=market.market_slug,
            condition_id=market.condition_id,
            asset=market.asset,
            timeframe=market.timeframe,
            start_ts=market.start_ts,
            end_ts=market.end_ts,
            up=InstrumentTokenMeta("up-token", Side.UP),
            down=InstrumentTokenMeta("down-token", Side.DOWN),
        )
    )
    custom_data = StrategyCustomDataState()
    books = NautilusCacheMarketDataProvider(FakeCache(), catalog=registry)
    assembler = MarketViewAssembler(catalog=registry, books=books, custom_data=custom_data)
    strategy = FakeStrategy(
        core=FakeCore(),
        assembler=assembler,
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=FakePolicy(),
        fixed_stake_usdc=10.0,
        instrument_id_resolver=lambda token_id: registry.instrument_id_for_token(token_id) or token_id,
        registry=registry,
    )

    settings = Settings()
    settings.runtime.nautilus.market_rotation.enabled = False
    actor = MarketRotationActor(settings=settings,
    startup_markets=(market,),
    market_universe=SimpleNamespace(refresh_once=lambda: []), catalog=registry, anchor_store=None,)
    def publish_and_route(data_type: object, data: object) -> None:
        _ = data_type
        published.append(data)
        strategy.on_data(data)

    actor.publish_data = publish_and_route

    def fake_get(_market):
        nonlocal ptb_ran
        ptb_ran = True
        return PriceToBeatResult(
            value=99950.0,
            source="anchor",
            verified=True,
            anchor_source="chainlink",
            anchor_lag_ms=5,
            from_anchor_service=True,
        )

    monkeypatch.setattr("asyncio.create_task", fake_create_task)
    monkeypatch.setattr(rotation_mod, "_register_polysignal_data_types_if_available", lambda: None)
    monkeypatch.setattr(actor.ptb_provider, "get_sync", fake_get)

    actor.on_start()
    actor._on_spot(
        SpotPrice(
            asset="BTC",
            symbol="BTCUSD",
            price=100000.0,
            source="polymarket_rtds",
            event_time=datetime.now(UTC),
            received_at=datetime.now(UTC),
        )
    )
    strategy.on_order_book_deltas(SimpleNamespace(instrument_id="condition-btc-5m-down-token.POLYMARKET"))
    strategy.on_order_book_deltas(SimpleNamespace(instrument_id="condition-btc-5m-up-token.POLYMARKET"))
    strategy.on_trade_tick(
        SimpleNamespace(
            instrument_id="condition-btc-5m-up-token.POLYMARKET",
            price=0.51,
            size=7.0,
            aggressor_side="BUYER",
            ts_event=datetime.now(UTC),
        )
    )
    assert ptb_ran is True
    assert any(isinstance(item, PolySignalMarketMetaData) for item in published)
    assert any(isinstance(item, PolySignalPriceToBeatData) for item in published)
    assert any(isinstance(item, PolySignalSpotData) for item in published)
    assert strategy.submitted != []
    assert str(strategy.submitted[-1]["instrument_id"]) == "condition-btc-5m-up-token.POLYMARKET"

def test_market_rotation_actor_rotates_single_native_strategy_without_rebuild(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polysignal_lab.nautilus_runtime.market_rotation as rotation_mod
    import polysignal_lab.nautilus_runtime.node as node_mod
    from polysignal_lab.domain.spot import SpotPrice
    from polysignal_lab.nautilus_runtime.custom_data_state import StrategyCustomDataState
    from polysignal_lab.nautilus_bridge.market_catalog import (
        MarketCatalog,
    )
    from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
    from polysignal_lab.nautilus_runtime.cache_market_data import NautilusCacheMarketDataProvider
    from polysignal_lab.nautilus_runtime.market_data import (
        PolySignalMarketMetaData,
        PolySignalMarketUniverseData,
        PolySignalPriceToBeatData,
    )
    from polysignal_lab.nautilus_runtime.market_rotation import MarketRotationActor
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy
    _install_fake_polymarket_id_helper(monkeypatch)

    published: list[object] = []
    created: list[tuple[str, object]] = []

    class DummyTask:
        def cancel(self) -> None:
            return None

    def fake_create_task(coro):
        code = getattr(coro, "cr_code", None)
        created.append((code.co_name if code is not None else "", coro))
        return DummyTask()

    def drain_ptb_tasks() -> None:
        while created:
            name, coro = created.pop(0)
            if name == "_publish_price_to_beat":
                asyncio.run(coro)
            else:
                coro.close()

    class FakeUniverse:
        async def refresh_once(self) -> list[Market]:
            return [market_b]

    class FakeLevel:
        def __init__(self, price: float, size: float) -> None:
            self.price = price
            self.size = size

    class FakeOrderBook:
        def __init__(self, bids, asks) -> None:
            self.bids = bids
            self.asks = asks
            self.last_trade_price = None
            self.last_trade_size = None
            self.last_trade_timestamp = None
            self.received_at = datetime.now(UTC)

    class FakeCache:
        def __init__(self) -> None:
            self.books = {
                polymarket_instrument_id("condition-a", "up-a"): FakeOrderBook(
                    bids=[FakeLevel(0.49, 20.0)],
                    asks=[FakeLevel(0.50, 20.0), FakeLevel(0.52, 20.0)],
                ),
                polymarket_instrument_id("condition-a", "down-a"): FakeOrderBook(
                    bids=[FakeLevel(0.48, 20.0)],
                    asks=[FakeLevel(0.51, 20.0), FakeLevel(0.53, 20.0)],
                ),
                polymarket_instrument_id("condition-b", "up-b"): FakeOrderBook(
                    bids=[FakeLevel(0.47, 20.0)],
                    asks=[FakeLevel(0.50, 20.0), FakeLevel(0.52, 20.0)],
                ),
                polymarket_instrument_id("condition-b", "down-b"): FakeOrderBook(
                    bids=[FakeLevel(0.46, 20.0)],
                    asks=[FakeLevel(0.51, 20.0), FakeLevel(0.53, 20.0)],
                ),
            }

        def order_book(self, instrument_id):
            return self.books[str(instrument_id)]

    class FakeOrderFactory:
        def limit(self, **kwargs):
            return kwargs

    class FakeCore:
        def evaluate(self, view):
            return [
                AlphaDecision(
                    strategy="ptb_diff",
                    asset=view.asset,
                    timeframe=view.timeframe,
                    market_id=view.market_id,
                    market_slug=view.market_slug,
                    condition_id=view.condition_id,
                    token_id=view.book_for(Side.UP).token_id,
                    side=Side.UP,
                    confidence=0.8,
                    entry_reference_price=0.50,
                    max_entry_price=0.52,
                    seconds_to_close=60,
                    data_freshness_ms=20,
                    reason_codes=("TEST",),
                    metrics={},
                    order_intent=OrderIntentSpec(intent=OrderIntent.TAKER_FOK, pair_id=f"pair-{view.condition_id}"),
                    hedge_leg=False,
                )
            ]

    class FakePolicy:
        def decide(self, decision, view):
            from polysignal_lab.domain.signal import SignalCandidate
            from polysignal_lab.nautilus_runtime.decision_policy import ApprovedDecision

            candidate = SignalCandidate.build(
                strategy=decision.strategy,
                asset=decision.asset,
                timeframe=decision.timeframe,
                market_id=decision.market_id,
                market_slug=decision.market_slug,
                condition_id=decision.condition_id,
                token_id=decision.token_id,
                side=decision.side,
                confidence=decision.confidence,
                entry_reference_price=decision.entry_reference_price,
                max_entry_price=decision.max_entry_price,
                seconds_to_close=decision.seconds_to_close,
                data_freshness_ms=decision.data_freshness_ms,
                reason_codes=list(decision.reason_codes),
                metrics=dict(decision.metrics),
                order_intent=decision.order_intent.intent,
                expiry_seconds=None,
                pair_id=decision.order_intent.pair_id,
                hedge_leg=decision.hedge_leg,
            )
            return ApprovedDecision(signal=candidate)

    class FakeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.cache = FakeCache()
            self.order_factory = FakeOrderFactory()
            self.submitted = []

        def submit_order(self, order):
            self.submitted.append(order)

    def market(
        *,
        market_id: str,
        market_slug: str,
        condition_id: str,
        up_token: str,
        down_token: str,
    ) -> Market:
        return Market(
            market_id=market_id,
            market_slug=market_slug,
            condition_id=condition_id,
            asset="BTC",
            timeframe="5m",
            outcome_tokens=[
                OutcomeToken(token_id=up_token, side=Side.UP, outcome_name="Up", market_id=market_id),
                OutcomeToken(token_id=down_token, side=Side.DOWN, outcome_name="Down", market_id=market_id),
            ],
        )

    market_a = market(
        market_id="btc-5m-a",
        market_slug="btc-updown-5m-a",
        condition_id="condition-a",
        up_token="up-a",
        down_token="down-a",
    )
    market_b = market(
        market_id="btc-5m-b",
        market_slug="btc-updown-5m-b",
        condition_id="condition-b",
        up_token="up-b",
        down_token="down-b",
    )
    settings = Settings()
    settings.runtime.nautilus.sidecar.spot_source = "disabled"
    settings.runtime.nautilus.market_rotation.enabled = False
    registry = MarketCatalog()
    node_mod._register_markets(registry, (market_a,))
    custom_data = StrategyCustomDataState()
    books = NautilusCacheMarketDataProvider(FakeCache(), catalog=registry)
    assembler = MarketViewAssembler(catalog=registry, books=books, custom_data=custom_data)
    strategy = FakeStrategy(
        core=FakeCore(),
        assembler=assembler,
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        policy=FakePolicy(),
        fixed_stake_usdc=10.0,
        instrument_id_resolver=node_mod._instrument_id_resolver(registry),
        registry=registry,
    )
    actor = MarketRotationActor(settings=settings,
    startup_markets=(market_a,),
    market_universe=FakeUniverse(), catalog=registry, anchor_store=None,)

    def publish_and_route(data_type: object, data: object) -> None:
        _ = data_type
        published.append(data)
        strategy.on_data(data)

    def fake_get(market: Market) -> PriceToBeatResult:
        return PriceToBeatResult(
            value=99950.0 if market.condition_id == "condition-a" else 100050.0,
            source="anchor",
            verified=True,
            anchor_source="chainlink",
            anchor_lag_ms=5,
            from_anchor_service=True,
        )

    monkeypatch.setattr("asyncio.create_task", fake_create_task)
    monkeypatch.setattr(rotation_mod, "register_polysignal_data_types", lambda: None)
    monkeypatch.setattr(actor.ptb_provider, "get_sync", fake_get)
    actor.publish_data = publish_and_route

    try:
        actor.on_start()
        drain_ptb_tasks()
        actor._on_spot(
            SpotPrice(
                asset="BTC",
                symbol="BTCUSD",
                price=100000.0,
                source="polymarket_rtds",
                event_time=datetime.now(UTC),
                received_at=datetime.now(UTC),
            )
        )
        strategy.on_order_book_deltas(
            SimpleNamespace(instrument_id=polymarket_instrument_id("condition-a", "down-a"))
        )
        strategy.on_order_book_deltas(
            SimpleNamespace(instrument_id=polymarket_instrument_id("condition-a", "up-a"))
        )
        assert [str(order["instrument_id"]) for order in strategy.submitted] == [
            polymarket_instrument_id("condition-a", "up-a")
        ]

        asyncio.run(actor.refresh_once())
        drain_ptb_tasks()
        rotated_meta = registry.by_condition("condition-b")
        assert rotated_meta is not None
        assert registry.instrument_id_for_token(rotated_meta.up.token_id) == polymarket_instrument_id("condition-b", "up-b")
        assert registry.instrument_id_for_token(rotated_meta.down.token_id) == polymarket_instrument_id("condition-b", "down-b")
        actor._on_spot(
            SpotPrice(
                asset="BTC",
                symbol="BTCUSD",
                price=100100.0,
                source="polymarket_rtds",
                event_time=datetime.now(UTC),
                received_at=datetime.now(UTC),
            )
        )
        before_late_a = len(strategy.submitted)
        strategy.on_order_book_deltas(
            SimpleNamespace(instrument_id=polymarket_instrument_id("condition-a", "up-a"))
        )
        assert len(strategy.submitted) == before_late_a
        strategy.on_order_book_deltas(
            SimpleNamespace(instrument_id=polymarket_instrument_id("condition-b", "down-b"))
        )
        strategy.on_order_book_deltas(
            SimpleNamespace(instrument_id=polymarket_instrument_id("condition-b", "up-b"))
        )

        assert [str(order["instrument_id"]) for order in strategy.submitted] == [
            polymarket_instrument_id("condition-a", "up-a"),
            polymarket_instrument_id("condition-b", "up-b"),
        ]
        rotated = [
            item
            for item in published
            if isinstance(item, PolySignalMarketUniverseData)
            and item.active_condition_ids == ("condition-b",)
        ]
        assert rotated
        assert rotated[-1].exited_condition_ids == ("condition-a",)
        assert any(
            isinstance(item, PolySignalMarketMetaData) and item.condition_id == "condition-b"
            for item in published
        )
        assert any(
            isinstance(item, PolySignalPriceToBeatData) and item.condition_id == "condition-b"
            for item in published
        )
    finally:
        drain_ptb_tasks()
