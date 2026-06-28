from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest

from polysignal_lab.alpha.types import AlphaDecision, OrderIntentSpec, SpotView
from polysignal_lab.config import Settings
from polysignal_lab.data.price_to_beat_provider import PriceToBeatResult
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.nautilus_runtime.instrument_mapping import polymarket_instrument_id
from polysignal_lab.nautilus_runtime.trading_node import PAPER_EXEC_CLIENT_ID


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


def test_full_paper_runtime_builds_node_without_live_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod
    from polysignal_lab.nautilus_runtime.cache_reader import NautilusCacheReader

    data_factories: list[str] = []
    exec_factories: list[str] = []
    built_nodes: list[object] = []
    built = False

    def empty_rows() -> list[object]:
        return []

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

    class FakeTradingNode:
        def __init__(self, *, config: object) -> None:
            self.config: object = config
            self.trader: FakeTrader = FakeTrader()
            self.cache = self.trader.cache
            self.portfolio = self.trader.portfolio
            built_nodes.append(self)

        def add_data_client_factory(self, name: str, factory: object) -> None:
            _ = factory
            data_factories.append(name)

        def add_exec_client_factory(self, name: str, factory: object) -> None:
            _ = factory
            exec_factories.append(name)

        def build(self) -> None:
            nonlocal built
            built = True

        def run(self) -> None:
            pass

    def fake_instrument_config(*, load_ids: frozenset[str]) -> SimpleNamespace:
        return SimpleNamespace(load_ids=load_ids)

    def fake_config_builder(settings: Settings | None = None, **kwargs: object) -> SimpleNamespace:
        _ = settings
        return SimpleNamespace(**kwargs)

    def fake_register_factories(node: FakeTradingNode) -> None:
        node.add_data_client_factory("POLYMARKET", object())
        node.add_exec_client_factory(PAPER_EXEC_CLIENT_ID, object())

    monkeypatch.setattr(node_mod, "TradingNode", FakeTradingNode)
    monkeypatch.setattr(node_mod, "PolymarketInstrumentProviderConfig", fake_instrument_config)
    monkeypatch.setattr(node_mod, "build_paper_trading_node_config", fake_config_builder)
    monkeypatch.setattr(node_mod, "register_paper_factories", fake_register_factories)

    runtime = node_mod.build_trading_node(
        Settings(),
        condition_ids=("condition-btc-5m",),
        markets=(_sample_market(),),
    )

    assert runtime["node"] is built_nodes[0]
    assert "POLYMARKET" in data_factories
    assert "POLYMARKET" not in exec_factories
    assert built is True
    config = cast(SimpleNamespace, runtime["config"])
    instrument_config = cast(SimpleNamespace, config.instrument_config)
    assert instrument_config.load_ids == frozenset(
        {
            f"{_sample_market().condition_id}-up-token.POLYMARKET",
            f"{_sample_market().condition_id}-down-token.POLYMARKET",
        }
    )
    assert "paper_client" not in runtime
    assert "matching_client" not in runtime
    cache_reader = runtime["cache_reader"]
    assert isinstance(cache_reader, NautilusCacheReader)
    assert cache_reader.read_orders() == []
    assert cache_reader.read_fills() == []
    assert cache_reader.read_positions() == []
    assert cache_reader.snapshot_portfolio() is not None


def test_build_trading_node_exposes_shared_book_data_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod
    from polysignal_lab.nautilus_runtime.book_data import NautilusBookDataProvider

    class FakeTrader:
        def __init__(self) -> None:
            self.strategies: list[object] = []
            self.actors: list[object] = []

        def add_strategy(self, strategy: object) -> None:
            self.strategies.append(strategy)

        def add_actor(self, actor: object) -> None:
            self.actors.append(actor)

    class FakeTradingNode:
        def __init__(self, *, config: object) -> None:
            self.config = config
            self.trader = FakeTrader()

        def add_data_client_factory(self, name: str, factory: object) -> None:
            _ = name, factory

        def add_exec_client_factory(self, name: str, factory: object) -> None:
            _ = name, factory

        def build(self) -> None:
            return None

    monkeypatch.setattr(node_mod, "TradingNode", FakeTradingNode)
    monkeypatch.setattr(
        node_mod,
        "PolymarketInstrumentProviderConfig",
        lambda *, load_ids: SimpleNamespace(load_ids=load_ids),
    )
    monkeypatch.setattr(
        node_mod,
        "build_paper_trading_node_config",
        lambda settings, **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(node_mod, "register_paper_factories", lambda node: None)

    runtime = node_mod.build_trading_node(Settings(), markets=(_sample_market(),))

    assert isinstance(runtime["book_data_provider"], NautilusBookDataProvider)
    assembler = cast(SimpleNamespace, runtime["assembler"])
    assert assembler.books is runtime["book_data_provider"]


def test_runtime_sidecar_actor_and_native_strategy_bridge_to_order_submit(monkeypatch: pytest.MonkeyPatch) -> None:
    import polysignal_lab.nautilus_runtime.sidecar_data as sidecar_mod
    from polysignal_lab.domain.spot import SpotPrice
    from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
    from polysignal_lab.nautilus_bridge.market_registry import (
        InstrumentTokenMeta,
        MarketPairMeta,
        PolymarketMarketRegistry,
    )
    from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
    from polysignal_lab.nautilus_runtime.book_data import NautilusBookDataProvider
    from polysignal_lab.nautilus_runtime.market_data import (
        PolySignalMarketMetaData,
        PolySignalPriceToBeatData,
        PolySignalSpotData,
    )
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy
    from polysignal_lab.nautilus_runtime.sidecar_data import PolySignalRuntimeSidecarActor

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
                "up-token.POLYMARKET": FakeOrderBook(
                    bids=[FakeLevel(0.49, 20.0)],
                    asks=[FakeLevel(0.50, 20.0), FakeLevel(0.52, 20.0)],
                ),
                "down-token.POLYMARKET": FakeOrderBook(
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
        def evaluate(self, decision, view):
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
    registry = PolymarketMarketRegistry()
    registry.register(
        MarketPairMeta(
            market_id=market.market_id,
            market_slug=market.market_slug,
            condition_id=market.condition_id,
            asset=market.asset,
            timeframe=market.timeframe,
            start_ts=market.start_ts,
            end_ts=market.end_ts,
            up=InstrumentTokenMeta("up-token.POLYMARKET", "up-token", Side.UP),
            down=InstrumentTokenMeta("down-token.POLYMARKET", "down-token", Side.DOWN),
        )
    )
    sidecar = ExternalDataSidecar()
    books = NautilusBookDataProvider()
    assembler = MarketViewAssembler(registry=registry, books=books, sidecar=sidecar)
    strategy = FakeStrategy(
        core=FakeCore(),
        assembler=assembler,
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=FakePolicy(),
        fixed_stake_usdc=10.0,
        instrument_id_resolver=lambda token_id: f"{token_id}.POLYMARKET",
        registry=registry,
        sidecar=sidecar,
    )

    actor = PolySignalRuntimeSidecarActor(
        settings=Settings(),
        markets=(market,),
        registry=registry,
        sidecar=sidecar,
        anchor_store=None,
    )
    def publish_and_route(data_type: object, data: object) -> None:
        _ = data_type
        published.append(data)
        strategy.on_data(data)

    actor.publish_data = publish_and_route

    async def fake_get(_market):
        return PriceToBeatResult(
            value=99950.0,
            source="anchor",
            verified=True,
            anchor_source="chainlink",
            anchor_lag_ms=5,
            from_anchor_service=True,
        )

    monkeypatch.setattr("asyncio.create_task", fake_create_task)
    monkeypatch.setattr(sidecar_mod, "register_polysignal_data_types", lambda: None)
    monkeypatch.setattr(actor.ptb_provider, "get", fake_get)

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
    strategy.on_order_book_deltas(SimpleNamespace(instrument_id="down-token.POLYMARKET"))
    strategy.on_order_book_deltas(SimpleNamespace(instrument_id="up-token.POLYMARKET"))
    strategy.on_trade_tick(
        SimpleNamespace(
            instrument_id="up-token.POLYMARKET",
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
    assert str(strategy.submitted[-1]["instrument_id"]) == "up-token.POLYMARKET"

def test_market_rotation_actor_rotates_single_native_strategy_without_rebuild(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polysignal_lab.nautilus_runtime.market_rotation as rotation_mod
    import polysignal_lab.nautilus_runtime.node as node_mod
    from polysignal_lab.domain.spot import SpotPrice
    from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
    from polysignal_lab.nautilus_bridge.market_registry import (
        PolymarketMarketRegistry,
    )
    from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
    from polysignal_lab.nautilus_runtime.book_data import NautilusBookDataProvider
    from polysignal_lab.nautilus_runtime.market_data import (
        PolySignalMarketMetaData,
        PolySignalMarketUniverseData,
        PolySignalPriceToBeatData,
    )
    from polysignal_lab.nautilus_runtime.market_rotation import MarketRotationActor
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

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
        def evaluate(self, decision, view):
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
    registry = PolymarketMarketRegistry()
    node_mod._register_markets(registry, (market_a,))
    sidecar = ExternalDataSidecar()
    books = NautilusBookDataProvider()
    assembler = MarketViewAssembler(registry=registry, books=books, sidecar=sidecar)
    strategy = FakeStrategy(
        core=FakeCore(),
        assembler=assembler,
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        policy=FakePolicy(),
        fixed_stake_usdc=10.0,
        instrument_id_resolver=node_mod._instrument_id_resolver(registry),
        registry=registry,
        sidecar=sidecar,
    )
    actor = MarketRotationActor(
        settings=settings,
        startup_markets=(market_a,),
        market_universe=FakeUniverse(),
        registry=registry,
        sidecar=sidecar,
        anchor_store=None,
    )

    def publish_and_route(data_type: object, data: object) -> None:
        _ = data_type
        published.append(data)
        strategy.on_data(data)

    async def fake_get(market: Market) -> PriceToBeatResult:
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
    monkeypatch.setattr(actor.ptb_provider, "get", fake_get)
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
        assert rotated_meta.up.instrument_id == polymarket_instrument_id("condition-b", "up-b")
        assert rotated_meta.down.instrument_id == polymarket_instrument_id("condition-b", "down-b")
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
