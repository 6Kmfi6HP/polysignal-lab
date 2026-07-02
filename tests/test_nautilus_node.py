from __future__ import annotations

import asyncio
import signal
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock
import pytest

from polysignal_lab.config import Settings
from polysignal_lab.nautilus_runtime.node import (
    build_trading_node,
    build_control,
    run_nautilus_cli,
    run_nautilus_cli_async,
)
from polysignal_lab.nautilus_runtime.trading_node import PAPER_EXEC_CLIENT_ID

if TYPE_CHECKING:
    from polysignal_lab.publish.telegram_publisher import TelegramPublisher


def _fake_telegram_publisher() -> TelegramPublisher:
    return cast("TelegramPublisher", cast(object, SimpleNamespace(send=lambda *_args, **_kwargs: None)))


def _runtime_settings_stub(**kwargs):
    return SimpleNamespace(
        storage=SimpleNamespace(state_dir="/tmp/polysignal-lab-test-runtime"),
        **kwargs,
    )


def _patch_nautilus_placeholders(monkeypatch):
    """Monkeypatch all 4 module-level nautilus placeholders so tests on py3.11
    can call build_trading_node without importing nautilus_trader."""

    class _FakeTradingNode:
        def __init__(self, config):
            self.config = config
            self.trader = SimpleNamespace(strategies=[], actors=[])
            self.trader.add_strategy = self.trader.strategies.append
            self.trader.add_actor = self.trader.actors.append
            self.built = False
            self.exec_factory_name: str | None = None

        def add_data_client_factory(self, name, factory):
            pass

        def add_exec_client_factory(self, name, factory):
            self.exec_factory_name = name

        def build(self):
            self.built = True

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.TradingNode",
        _FakeTradingNode,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.PolymarketInstrumentProviderConfig",
        lambda *, load_ids: SimpleNamespace(load_ids=load_ids),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.build_paper_trading_node_config",
        lambda settings, **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.register_paper_factories",
        lambda node: (
            node.add_data_client_factory("POLYMARKET", object()),
            node.add_exec_client_factory(PAPER_EXEC_CLIENT_ID, object()),
        ),
    )
    return _FakeTradingNode


def test_build_trading_node_returns_nautilus_runtime_components(monkeypatch) -> None:
    built = {}

    class FakeTradingNode:
        def __init__(self, config):
            self.config = config
            self.trader = SimpleNamespace(strategies=[], actors=[])
            self.trader.add_strategy = self.trader.strategies.append
            self.trader.add_actor = self.trader.actors.append
            self.built = False
            built["node"] = self

        def add_data_client_factory(self, name, factory):
            built.setdefault("data_factories", []).append((name, factory))

        def add_exec_client_factory(self, name, factory):
            built.setdefault("exec_factories", []).append((name, factory))

        def build(self):
            self.built = True

    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node.TradingNode", FakeTradingNode)
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.PolymarketInstrumentProviderConfig",
        lambda *, load_ids: SimpleNamespace(load_ids=load_ids),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.build_paper_trading_node_config",
        lambda settings, **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.register_paper_factories",
        lambda node: (
            node.add_data_client_factory("POLYMARKET", object()),
            node.add_exec_client_factory(PAPER_EXEC_CLIENT_ID, object()),
        ),
    )

    runtime = build_trading_node(condition_ids=("condition-btc-5m",))

    assert runtime["node"] is built["node"]
    assert built["node"].built is True
    assert built["exec_factories"][0][0] != "POLYMARKET"
    assert len(built["node"].trader.actors) == 1
    assert "paper_client" not in runtime



def test_build_trading_node_injects_shared_projections_and_no_manual_sync_components(monkeypatch) -> None:
    built = {}

    class FakeTradingNode:
        def __init__(self, config):
            self.config = config
            self.trader = SimpleNamespace(strategies=[], actors=[])
            self.trader.add_strategy = self.trader.strategies.append
            self.trader.add_actor = self.trader.actors.append
            self.built = False
            built["node"] = self

        def add_data_client_factory(self, name, factory):
            built.setdefault("data_factories", []).append((name, factory))

        def add_exec_client_factory(self, name, factory):
            built.setdefault("exec_factories", []).append((name, factory))

        def build(self):
            self.built = True

    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node.TradingNode", FakeTradingNode)
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.PolymarketInstrumentProviderConfig",
        lambda *, load_ids: SimpleNamespace(load_ids=load_ids),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.build_paper_trading_node_config",
        lambda settings, **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.register_paper_factories",
        lambda node: (
            node.add_data_client_factory("POLYMARKET", object()),
            node.add_exec_client_factory(PAPER_EXEC_CLIENT_ID, object()),
        ),
    )

    runtime = build_trading_node(condition_ids=("condition-btc-5m",))
    strategies = cast(list[object], runtime["strategies"])

    assert "registry" in runtime
    assert "sidecar" in runtime
    assert "book_data_provider" in runtime
    assert "assembler" in runtime
    assert "market_rotation_actor" in runtime
    assert "data_ingestor" not in runtime
    assert "orchestrator" not in runtime
    assert "paper_client" not in runtime
    assert "matching_client" not in runtime
    assert strategies
    first_strategy = strategies[0]
    assert getattr(first_strategy, "registry") is runtime["registry"]
    assert getattr(first_strategy, "sidecar") is runtime["sidecar"]
    assert getattr(first_strategy, "assembler") is runtime["assembler"]

def test_build_trading_node_registers_market_rotation_actor(monkeypatch) -> None:
    built = {}

    class FakeTradingNode:
        def __init__(self, config):
            self.config = config
            self.trader = SimpleNamespace(strategies=[], actors=[])
            self.trader.add_strategy = self.trader.strategies.append
            self.trader.add_actor = self.trader.actors.append
            built["node"] = self

        def add_data_client_factory(self, name, factory):
            pass

        def add_exec_client_factory(self, name, factory):
            pass

        def build(self):
            return None

    class FakeRotationActor:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node.TradingNode", FakeTradingNode)
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.PolymarketInstrumentProviderConfig",
        lambda *, load_ids: SimpleNamespace(load_ids=load_ids),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.build_paper_trading_node_config",
        lambda settings, **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.register_paper_factories",
        lambda node: None,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.market_rotation.runtime_market_rotation_actor_type",
        lambda _base, _config: FakeRotationActor,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.sidecar_data.runtime_sidecar_actor_type",
        lambda _base, _config: pytest.fail("build_trading_node should register MarketRotationActor"),
    )

    universe = object()
    health = object()
    runtime = build_trading_node(
        condition_ids=("condition-btc-5m",),
        market_universe=universe,
        health=health,
    )

    assert len(built["node"].trader.actors) == 1
    assert built["node"].trader.actors[0] is runtime["market_rotation_actor"]
    assert isinstance(runtime["market_rotation_actor"], FakeRotationActor)
    assert runtime["market_rotation_actor"].kwargs["market_universe"] is universe
    assert runtime["market_rotation_actor"].kwargs["health"] is health

def test_build_trading_node_uses_sandbox_execution_not_matching_client(monkeypatch) -> None:
    class FakeTradingNode:
        def __init__(self, config):
            self.config = config
            self.trader = SimpleNamespace(strategies=[], actors=[])
            self.trader.add_strategy = self.trader.strategies.append
            self.trader.add_actor = self.trader.actors.append
            self.exec_factory_name: str | None = None

        def add_data_client_factory(self, name, factory):
            pass

        def add_exec_client_factory(self, name, factory):
            self.exec_factory_name = name

        def build(self):
            pass

    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node.TradingNode", FakeTradingNode)
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.PolymarketInstrumentProviderConfig",
        lambda *, load_ids: SimpleNamespace(load_ids=load_ids),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.build_paper_trading_node_config",
        lambda settings, **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.register_paper_factories",
        lambda node: (
            node.add_data_client_factory("POLYMARKET", object()),
            node.add_exec_client_factory(PAPER_EXEC_CLIENT_ID, object()),
        ),
    )

    runtime = build_trading_node()

    assert getattr(runtime["node"], "exec_factory_name") != "POLYMARKET"
    assert "paper_client" not in runtime
    assert "matching_client" not in runtime


def test_build_trading_node_strategies_is_list(monkeypatch) -> None:
    """Strategy list is a list even when no strategies configured."""
    _patch_nautilus_placeholders(monkeypatch)

    runtime = build_trading_node()
    assert isinstance(runtime["strategies"], list)


def test_build_trading_node_forwards_unsubscribe_exited_to_native_strategy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_nautilus_placeholders(monkeypatch)
    captured: dict[str, object] = {}

    class FakeRotationActor:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeStrategy:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs
            self.strategy_name = kwargs["strategy_name"]

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.market_rotation.runtime_market_rotation_actor_type",
        lambda _base, _config: FakeRotationActor,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.native_strategy.runtime_native_strategy_type",
        lambda _base, _config: FakeStrategy,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._native_core_for",
        lambda _name, _cfg: object(),
    )

    settings = Settings()
    settings.runtime.nautilus.market_rotation.unsubscribe_exited = False
    settings.strategies.set_explicit_strategy_names(("vwap_momentum",))

    runtime = build_trading_node(
        settings=settings,
        condition_ids=("condition-btc-5m",),
    )

    strategies = cast(list[object], runtime["strategies"])
    captured_kwargs = cast(dict[str, object], captured["kwargs"])

    assert len(strategies) == 1
    assert getattr(runtime["node"], "trader").strategies == strategies
    assert captured_kwargs["unsubscribe_exited"] is False
    assert captured_kwargs["strategy_name"] == "vwap_momentum"


def test_build_trading_node_passes_l1_snapshot_interval_to_native_strategies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_nautilus_placeholders(monkeypatch)
    captured: dict[str, object] = {}

    class FakeRotationActor:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeStrategy:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs
            self.strategy_name = kwargs["strategy_name"]

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.market_rotation.runtime_market_rotation_actor_type",
        lambda _base, _config: FakeRotationActor,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.native_strategy.runtime_native_strategy_type",
        lambda _base, _config: FakeStrategy,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._native_core_for",
        lambda _name, _cfg: object(),
    )

    settings = Settings()
    settings.runtime.nautilus.matching_accuracy_mode = "fast_l1"
    settings.runtime.nautilus.l1_book_snapshot_interval_ms = 250
    settings.strategies.set_explicit_strategy_names(("vwap_momentum",))

    runtime = build_trading_node(
        settings=settings,
        condition_ids=("condition-btc-5m",),
    )

    strategies = cast(list[object], runtime["strategies"])
    captured_kwargs = cast(dict[str, object], captured["kwargs"])

    assert len(strategies) == 1
    assert getattr(runtime["node"], "trader").strategies == strategies
    assert captured_kwargs["book_type"] == "L1_MBP"
    assert captured_kwargs["l1_book_snapshot_interval_ms"] == 250


def test_build_trading_node_injects_runtime_progress_callback(monkeypatch, tmp_path) -> None:
    from polysignal_lab.observability.runtime_health import read_runtime_heartbeat

    captured: dict[str, object] = {}

    class FakeTradingNode:
        def __init__(self, config):
            self.config = config
            self.trader = SimpleNamespace(strategies=[], actors=[])
            self.trader.add_strategy = self.trader.strategies.append
            self.trader.add_actor = self.trader.actors.append

        def add_data_client_factory(self, name, factory):
            return None

        def add_exec_client_factory(self, name, factory):
            return None

        def build(self):
            return None

    class FakeStrategy:
        strategy_name = "vwap_momentum"

        def __init__(self, **kwargs):
            captured.update(kwargs)

    settings = Settings()
    settings.strategies.set_explicit_strategy_names(("vwap_momentum",))
    settings.storage.state_dir = str(tmp_path / "state")
    _patch_nautilus_placeholders(monkeypatch)
    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node.TradingNode", FakeTradingNode)
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.native_strategy.runtime_native_strategy_type",
        lambda _base, _config: FakeStrategy,
    )

    runtime = build_trading_node(settings=settings, condition_ids=("condition-btc-5m",))

    progress = captured["progress_callback"]
    assert callable(progress)
    progress("evaluation_heartbeat")
    heartbeat = read_runtime_heartbeat(tmp_path / "state" / "runtime_heartbeat.json")
    assert heartbeat.phase == "evaluation_heartbeat"
    assert runtime["strategies"][0].strategy_name == "vwap_momentum"

def test_runtime_progress_callback_suppresses_heartbeat_write_failures(monkeypatch, tmp_path) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod

    settings = Settings()
    settings.storage.state_dir = str(tmp_path / "state")

    def fail_write(*_args, **_kwargs):
        raise OSError("state directory unavailable")

    monkeypatch.setattr(node_mod, "write_runtime_heartbeat", fail_write)

    node_mod._runtime_progress_callback(settings)("evaluation_heartbeat")

def test_build_control_adapts_policy() -> None:
    from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor

    policy = DecisionPolicyActor()
    ctrl = build_control(policy)

    assert ctrl.is_strategy_enabled("vwap_momentum")
    ctrl.set_strategy_enabled("vwap_momentum", enabled=False)
    assert not ctrl.is_strategy_enabled("vwap_momentum")


async def test_build_nautilus_runtime_discovers_market_universe_for_trading_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod
    from polysignal_lab.domain.enums import Side
    from polysignal_lab.domain.market import Market, OutcomeToken

    market = Market(
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
    refresh_calls = 0
    captured: dict[str, object] = {}

    class FakePersistence:
        def insert_signal(self, payload):
            _ = payload

        def insert_rejected_signal(self, payload):
            _ = payload

        def upsert_paper_order(self, payload):
            _ = payload

        def insert_paper_fill(self, payload):
            _ = payload

        def upsert_paper_position(self, payload):
            _ = payload

        def insert_paper_trade_result(self, payload):
            _ = payload

        def insert_system_event(self, payload):
            _ = payload

        def append_log(self, stream, payload):
            _ = stream, payload

    class FakeMarketUniverse:
        async def refresh_once(self) -> list[Market]:
            nonlocal refresh_calls
            refresh_calls += 1
            return [market]

    class FakeScheduler:
        def __init__(self, settings=None):
            self.settings = settings or SimpleNamespace(markets=SimpleNamespace(refresh_interval_sec=60))
            self.market_universe = FakeMarketUniverse()
            self.health = object()
            self.persistence = FakePersistence()
            self.publisher = SimpleNamespace(send=lambda *_args, **_kwargs: None)

        async def stop(self) -> None:
            return None

    monkeypatch.setattr(node_mod, "PolySignalScheduler", FakeScheduler)
    monkeypatch.setattr(node_mod, "_initialize_nautilus_scheduler_components", lambda _scheduler: None)
    monkeypatch.setattr(node_mod, "NautilusEventStoreAdapter", lambda persistence: persistence)
    monkeypatch.setattr(node_mod, "NautilusNotifierAdapter", lambda publisher: publisher)
    monkeypatch.setattr(node_mod, "ObservabilityActor", lambda **kwargs: SimpleNamespace(**kwargs))
    cache_reader = object()
    monkeypatch.setattr(
        node_mod,
        "build_trading_node",
        lambda settings=None, *, condition_ids=(), markets=(), market_universe=None, store=None, health=None, observability=None: captured.update(
            condition_ids=tuple(condition_ids),
            markets=tuple(markets),
            market_universe=market_universe,
            store=store,
            health=health,
            observability=observability,
        )
        or {
            "assembler": SimpleNamespace(books=None),
            "cache_reader": cache_reader,
            "registry": object(),
            "sidecar": object(),
            "node": SimpleNamespace(),
            "strategies": [],
        },
    )

    bundle = await node_mod.build_nautilus_runtime(Settings())

    assert refresh_calls == 1
    assert captured["condition_ids"] == ("condition-btc-5m",)
    assert captured["markets"] == (market,)
    assert captured["market_universe"] is bundle.scheduler.market_universe
    assert captured["health"] is bundle.scheduler.health
    assert captured["observability"] is not None
    assert callable(getattr(captured["observability"], "paper_fill_notifier", None))
    assert callable(getattr(captured["observability"], "paper_fill_mirror", None))
    assert callable(getattr(captured["observability"], "accepted_signal_notifier", None))

    assert bundle.scheduler is not None
    assert getattr(bundle.scheduler, "nautilus_cache_reader") is cache_reader
    assert getattr(bundle.scheduler, "paper_execution_metadata") == {
        "paper_engine": "nautilus_matching",
        "accuracy_mode": "depth_l2",
    }
    assert bundle.websocket_tasks == []


def test_publish_accepted_signal_in_background_uses_fresh_publish_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod
    from polysignal_lab.domain.enums import Side
    from polysignal_lab.domain.signal import SignalCandidate

    published: list[tuple[str, float]] = []
    noted: list[dict[str, str]] = []
    closed: list[bool] = []

    class FakeTelegramPublisher:
        def __init__(self, config) -> None:
            self.config = config
            self.client = SimpleNamespace(aclose=self._aclose)

        async def _aclose(self) -> None:
            closed.append(True)

    class FakePublishService:
        def __init__(
            self,
            formatter,
            publisher,
            persistence,
            *,
            timeout_sec: float,
        ) -> None:
            assert formatter == "formatter"
            assert persistence == "persistence"
            assert timeout_sec == 7.0
            self.publisher = publisher

        async def publish_signal(self, signal, stake_usdc):
            published.append((signal.signal_id, stake_usdc))
            return SimpleNamespace(as_dict=lambda: {"status": "SENT"})

    monkeypatch.setattr(node_mod, "TelegramPublisher", FakeTelegramPublisher, raising=False)
    monkeypatch.setattr(node_mod, "PublishService", FakePublishService, raising=False)
    monkeypatch.setattr(
        node_mod.scheduler_health,
        "note_publish_result",
        lambda _scheduler, publish: noted.append(publish),
    )
    scheduler = SimpleNamespace(
        settings=_runtime_settings_stub(telegram="telegram-config"),
        publish_service=SimpleNamespace(
            formatter="formatter",
            persistence="persistence",
            timeout_sec=7.0,
        ),
        logger=SimpleNamespace(warning=lambda *_args, **_kwargs: None),
    )
    signal = SignalCandidate.build(
        strategy="test",
        asset="BTC",
        timeframe="5m",
        market_id="m1",
        market_slug="s1",
        condition_id="c1",
        token_id="t1",
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.5,
        max_entry_price=0.55,
        seconds_to_close=120,
        data_freshness_ms=100,
        reason_codes=["EDGE"],
        metrics={"edge": 0.1},
    )

    node_mod._publish_accepted_signal_in_background(scheduler, signal, 10.0)

    assert published == [(signal.signal_id, 10.0)]
    assert noted == [{"status": "SENT"}]
    assert closed == [True]

def test_publish_nautilus_paper_fill_in_background_uses_fresh_publish_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod

    published: list[dict[str, object]] = []
    closed: list[bool] = []

    class FakeTelegramPublisher:
        def __init__(self, config) -> None:
            self.config = config
            self.client = SimpleNamespace(aclose=self._aclose)

        async def _aclose(self) -> None:
            closed.append(True)

    class FakePublishService:
        def __init__(
            self,
            formatter,
            publisher,
            persistence,
            *,
            timeout_sec: float,
        ) -> None:
            assert formatter == "formatter"
            assert persistence == "persistence"
            assert timeout_sec == 7.0
            self.publisher = publisher

        async def publish_nautilus_paper_fill(self, payload):
            published.append(dict(payload))
            return SimpleNamespace(as_dict=lambda: {"status": "SENT"})

    monkeypatch.setattr(node_mod, "TelegramPublisher", FakeTelegramPublisher, raising=False)
    monkeypatch.setattr(node_mod, "PublishService", FakePublishService, raising=False)
    scheduler = SimpleNamespace(
        settings=_runtime_settings_stub(telegram="telegram-config"),
        publish_service=SimpleNamespace(
            formatter="formatter",
            persistence="persistence",
            timeout_sec=7.0,
        ),
        logger=SimpleNamespace(warning=lambda *_args, **_kwargs: None),
    )
    payload = {"signal_id": "sig-1", "paper_fill_id": "fill-1"}

    node_mod._publish_nautilus_paper_fill_in_background(scheduler, payload)

    assert published == [payload]
    assert closed == [True]


def test_prepare_nautilus_runtime_context_rebinds_market_discovery_client_for_later_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod
    from polysignal_lab.domain.enums import Side
    from polysignal_lab.domain.market import Market, OutcomeToken

    market = Market(
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
    class LoopBoundClient:
        def __init__(self, label: str) -> None:
            self.label = label
            try:
                self.bound_loop = asyncio.get_running_loop()
            except RuntimeError:
                self.bound_loop = None
            self.closed = False

        async def get(self, _url: str, params: object | None = None) -> object:
            _ = params
            loop = asyncio.get_running_loop()
            if self.bound_loop is None:
                self.bound_loop = loop
            elif loop is not self.bound_loop:
                raise RuntimeError("client reused across event loops")
            return object()

        async def aclose(self) -> None:
            self.closed = True

    class FakeDiscovery:
        def __init__(self) -> None:
            self.client = LoopBoundClient("old")
            self.replace_calls = 0

        def replace_client(self) -> None:
            self.replace_calls += 1
            self.client = LoopBoundClient("new")

    class FakeMarketUniverse:
        def __init__(self, discovery: FakeDiscovery) -> None:
            self.discovery = discovery
            self.calls = 0

        async def refresh_once(self) -> list[Market]:
            self.calls += 1
            await self.discovery.client.get("https://example.invalid")
            return [market]

    class FakePersistence:
        def insert_signal(self, payload):
            _ = payload

        def insert_rejected_signal(self, payload):
            _ = payload

        def upsert_paper_order(self, payload):
            _ = payload

        def insert_paper_fill(self, payload):
            _ = payload

        def upsert_paper_position(self, payload):
            _ = payload

        def insert_paper_trade_result(self, payload):
            _ = payload

        def insert_system_event(self, payload):
            _ = payload

        def append_log(self, stream, payload):
            _ = stream, payload

    created: dict[str, object] = {}

    class FakeScheduler:
        def __init__(self, settings=None):
            self.settings = settings or SimpleNamespace(markets=SimpleNamespace(refresh_interval_sec=60))
            self.discovery = FakeDiscovery()
            created["old_client"] = self.discovery.client
            self.market_universe = FakeMarketUniverse(self.discovery)
            self.health = object()
            self.persistence = FakePersistence()
            self.publisher = SimpleNamespace(send=lambda *_args, **_kwargs: None)
    monkeypatch.setattr(node_mod, "PolySignalScheduler", FakeScheduler)
    monkeypatch.setattr(node_mod, "_initialize_nautilus_scheduler_components", lambda _scheduler: None)
    monkeypatch.setattr(node_mod, "NautilusEventStoreAdapter", lambda persistence: persistence)
    monkeypatch.setattr(node_mod, "NautilusNotifierAdapter", lambda publisher: publisher)
    monkeypatch.setattr(node_mod, "ObservabilityActor", lambda **kwargs: SimpleNamespace(**kwargs))

    scheduler, discovered_markets, _observability = asyncio.run(
        node_mod._prepare_nautilus_runtime_context(Settings())
    )

    assert [item.market_id for item in discovered_markets] == ["btc-5m"]
    old_client = cast(LoopBoundClient, created["old_client"])
    market_universe = cast(FakeMarketUniverse, cast(object, scheduler.market_universe))
    discovery = cast(FakeDiscovery, cast(object, scheduler.discovery))
    assert market_universe.calls == 1
    node_mod._rebind_market_discovery_client(scheduler)

    refreshed_markets = asyncio.run(market_universe.refresh_once())

    assert [item.market_id for item in refreshed_markets] == ["btc-5m"]
    assert market_universe.calls == 2
    assert discovery.replace_calls == 1
    assert discovery.client is not old_client


async def test_prepare_nautilus_runtime_context_initializes_settlement_compat_state(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod
    from polysignal_lab.domain.enums import Side
    from polysignal_lab.domain.market import Market, OutcomeToken

    market = Market(
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="0x" + "1" * 64,
        asset="BTC",
        timeframe="5m",
        outcome_tokens=[
            OutcomeToken(token_id="up-token", side=Side.UP, outcome_name="Up", market_id="btc-5m"),
            OutcomeToken(token_id="down-token", side=Side.DOWN, outcome_name="Down", market_id="btc-5m"),
        ],
    )

    settings = Settings()
    scheduler = node_mod.PolySignalScheduler(settings, base_dir=tmp_path)
    scheduler.market_universe.refresh_once = AsyncMock(return_value=[market])
    scheduler.publisher = _fake_telegram_publisher()

    monkeypatch.setattr(node_mod, "PolySignalScheduler", lambda _settings=None: scheduler)

    sched, discovered_markets, observability = await node_mod._prepare_nautilus_runtime_context(settings)

    assert sched is scheduler
    assert discovered_markets == (market,)
    assert getattr(scheduler, "_nautilus_runtime_compat_only") is True
    assert scheduler.paper is None
    assert scheduler.paper_portfolio.wallet is scheduler.wallet
    assert scheduler.paper_portfolio.exits is scheduler.exits
    assert scheduler.paper_portfolio.settlement is scheduler.settlement
    assert scheduler.wallet.open_position_count == 0
    assert callable(getattr(observability, "paper_fill_notifier", None))
    assert callable(getattr(observability, "paper_fill_mirror", None))


async def test_run_nautilus_housekeeping_once_settles_mirrored_fill_position(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod
    import polysignal_lab.app.scheduler_runtime as runtime_mod
    from polysignal_lab.domain.enums import Side
    from polysignal_lab.domain.market import Market, OutcomeToken
    from polysignal_lab.paper.settlement_sources import ResolutionDecision

    market = Market(
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="0x" + "1" * 64,
        asset="BTC",
        timeframe="5m",
        outcome_tokens=[
            OutcomeToken(token_id="up-token", side=Side.UP, outcome_name="Up", market_id="btc-5m"),
            OutcomeToken(token_id="down-token", side=Side.DOWN, outcome_name="Down", market_id="btc-5m"),
        ],
    )
    settings = Settings()
    settings.telegram.enabled = False
    settings.telegram.send_daily_report = False
    scheduler = node_mod.PolySignalScheduler(settings, base_dir=tmp_path)
    scheduler.market_universe.refresh_once = AsyncMock(return_value=[market])
    scheduler.publisher = _fake_telegram_publisher()

    monkeypatch.setattr(node_mod, "PolySignalScheduler", lambda _settings=None: scheduler)
    monkeypatch.setattr(
        runtime_mod,
        "_generate_iteration_report",
        AsyncMock(return_value=None),
    )

    sched, _discovered_markets, observability = await node_mod._prepare_nautilus_runtime_context(settings)
    sched.ctx.markets.upsert_many([market])
    sched.settlement_resolver.resolve_market = AsyncMock(
        return_value=ResolutionDecision(
            market.market_id,
            market.condition_id,
            "resolved",
            "chain",
            {"up-token": 1.0, "down-token": 0.0},
            False,
            (),
            {
                "settlement_source": "chain",
                "condition_id": market.condition_id,
                "payout_values_by_token": {"up-token": 1.0, "down-token": 0.0},
                "chain_status": "resolved",
            },
        )
    )

    marker = "runtime-settlement-marker"
    observability.mirror_nautilus_paper_fill(
        {
            "strategy": "probe",
            "asset": "BTC",
            "timeframe": "5m",
            "market_id": market.market_id,
            "market_slug": market.market_slug,
            "condition_id": market.condition_id,
            "token_id": "up-token",
            "side": "UP",
            "fill_price": 0.4,
            "shares": 25.0,
            "stake_usdc": 10.0,
            "signal_id": marker,
            "order_id": "order-1",
            "client_order_id": "client-1",
            "paper_fill_id": "fill-1",
            "liquidity_side": "TAKER",
            "metrics": {"fill_price": 0.4},
        }
    )

    assert sched.wallet.open_position_count == 1

    await node_mod._run_nautilus_housekeeping_once(sched, None)

    trade_rows = sched.sqlite.query_json(
        "paper_trade_results",
        where="WHERE signal_id = ?",
        params=(marker,),
    )
    position_rows = sched.sqlite.query_json(
        "paper_positions",
        where="WHERE signal_id = ?",
        params=(marker,),
    )

    assert [row["result"] for row in trade_rows] == ["WIN"]
    assert trade_rows[0]["details"]["settlement_source"] == "chain"
    assert [row["status"] for row in position_rows] == ["CLOSED"]
    assert sched.wallet.open_position_count == 0
async def test_run_nautilus_cli_async_exits_on_stop_event(monkeypatch) -> None:
    class FakeTradingNode:
        def __init__(self):
            self.running = False

        def run(self):
            self.running = True

        def dispose(self):
            pass

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    fake_bundle = SimpleNamespace(
        node=FakeTradingNode(),
        websocket_tasks=[],
        scheduler=SimpleNamespace(
            stop=_noop,
            settings=_runtime_settings_stub(
                markets=SimpleNamespace(refresh_interval_sec=60),
                runtime=SimpleNamespace(
                    nautilus=SimpleNamespace(
                        paper_engine="nautilus_matching",
                        matching_accuracy_mode="depth_l2",
                    )
                ),
            ),
        ),
        observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
        components={"strategies": []},
    )

    async def fake_build(settings=None):
        _ = settings
        return fake_bundle

    async def fake_to_thread(fn, *args):
        return fn(*args)

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.build_nautilus_runtime",
        fake_build,
    )
    monkeypatch.setattr(
        "asyncio.to_thread",
        fake_to_thread,
    )
    stop_event = asyncio.Event()
    stop_event.set()
    await run_nautilus_cli_async(stop_event=stop_event)

async def test_run_nautilus_cli_async_refreshes_startup_marker_before_runtime_build(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import json
    import polysignal_lab.nautilus_runtime.node as node_mod

    settings = Settings()
    settings.storage.state_dir = str(tmp_path / "state")
    old_started_at = "2026-06-30T11:00:00+00:00"
    marker = tmp_path / "state" / "runtime_startup.json"
    marker.parent.mkdir()
    marker.write_text(json.dumps({"started_at": old_started_at}), encoding="utf-8")
    observed: dict[str, object] = {}

    class FakeTradingNode:
        def run(self):
            return None

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    async def fake_build(received_settings=None):
        observed["settings"] = received_settings
        payload = json.loads(marker.read_text(encoding="utf-8"))
        assert isinstance(payload["started_at"], str)
        assert payload["started_at"] != old_started_at
        return SimpleNamespace(
            node=FakeTradingNode(),
            websocket_tasks=[],
            scheduler=SimpleNamespace(
                stop=_noop,
                settings=_runtime_settings_stub(
                    runtime=SimpleNamespace(
                        nautilus=SimpleNamespace(
                            paper_engine="nautilus_matching",
                            matching_accuracy_mode="depth_l2",
                        )
                    )
                ),
            ),
            observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
            components={"strategies": []},
        )

    monkeypatch.setattr(node_mod, "load_settings", lambda: settings)
    monkeypatch.setattr(node_mod, "build_nautilus_runtime", fake_build)

    stop_event = asyncio.Event()
    stop_event.set()
    await run_nautilus_cli_async(stop_event=stop_event)

    assert observed["settings"] is settings

async def test_run_nautilus_cli_async_suppresses_probe_write_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod

    settings = Settings()

    class FakeTradingNode:
        def run(self):
            return None

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    async def fake_build(received_settings=None):
        assert received_settings is settings
        return SimpleNamespace(
            node=FakeTradingNode(),
            websocket_tasks=[],
            scheduler=SimpleNamespace(
                stop=_noop,
                settings=_runtime_settings_stub(
                    runtime=SimpleNamespace(
                        nautilus=SimpleNamespace(
                            paper_engine="nautilus_matching",
                            matching_accuracy_mode="depth_l2",
                        )
                    )
                ),
            ),
            observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
            components={"strategies": []},
        )

    def fail_write(*_args, **_kwargs):
        raise OSError("state directory unavailable")

    monkeypatch.setattr(node_mod, "build_nautilus_runtime", fake_build)
    monkeypatch.setattr(node_mod, "write_runtime_startup_marker", fail_write)
    monkeypatch.setattr(node_mod, "write_runtime_heartbeat", fail_write)

    stop_event = asyncio.Event()
    stop_event.set()
    await run_nautilus_cli_async(settings=settings, stop_event=stop_event)



async def test_run_nautilus_cli_async_does_not_install_signal_handlers_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeTradingNode:
        def run(self):
            return None

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    fake_bundle = SimpleNamespace(
        node=FakeTradingNode(),
        websocket_tasks=[],
        scheduler=SimpleNamespace(
            stop=_noop,
            settings=_runtime_settings_stub(
                runtime=SimpleNamespace(
                    nautilus=SimpleNamespace(
                        paper_engine="nautilus_matching",
                        matching_accuracy_mode="depth_l2",
                    )
                ),
            ),
        ),
        observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
        components={"strategies": []},
    )

    async def fake_build(settings=None):
        _ = settings
        return fake_bundle

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.build_nautilus_runtime",
        fake_build,
    )
    monkeypatch.setattr(
        "asyncio.get_running_loop",
        lambda: SimpleNamespace(
            add_signal_handler=lambda *_args, **_kwargs: pytest.fail(
                "OS signal handlers must be opt-in"
            )
        ),
    )
    stop_event = asyncio.Event()
    stop_event.set()

    await run_nautilus_cli_async(stop_event=stop_event)


async def test_run_nautilus_cli_async_installs_signal_handlers_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed: list[tuple[object, object]] = []
    removed: list[object] = []

    class FakeTradingNode:
        def run(self):
            return None

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    fake_bundle = SimpleNamespace(
        node=FakeTradingNode(),
        websocket_tasks=[],
        scheduler=SimpleNamespace(
            stop=_noop,
            settings=_runtime_settings_stub(
                runtime=SimpleNamespace(
                    nautilus=SimpleNamespace(
                        paper_engine="nautilus_matching",
                        matching_accuracy_mode="depth_l2",
                        intercept_os_signals=True,
                    )
                ),
            ),
        ),
        observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
        components={"strategies": []},
    )

    async def fake_build(settings=None):
        _ = settings
        return fake_bundle

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.build_nautilus_runtime",
        fake_build,
    )
    monkeypatch.setattr(
        "asyncio.get_running_loop",
        lambda: SimpleNamespace(
            add_signal_handler=lambda sig, handler: installed.append((sig, handler)),
            remove_signal_handler=lambda sig: removed.append(sig),
        ),
    )
    stop_event = asyncio.Event()
    stop_event.set()

    await run_nautilus_cli_async(stop_event=stop_event)

    assert [item[0] for item in installed] == [signal.SIGTERM, signal.SIGINT]
    assert set(removed) == {signal.SIGTERM, signal.SIGINT}


async def test_run_nautilus_cli_async_restores_signals_after_shutdown_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed: list[tuple[object, object]] = []
    removed: list[object] = []
    previous = {
        signal.SIGTERM: signal.getsignal(signal.SIGTERM),
        signal.SIGINT: signal.getsignal(signal.SIGINT),
    }


    class FakeTradingNode:
        def run(self):
            return None

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    fake_bundle = SimpleNamespace(
        node=FakeTradingNode(),
        websocket_tasks=[],
        scheduler=SimpleNamespace(
            stop=_noop,
            settings=_runtime_settings_stub(
                runtime=SimpleNamespace(
                    nautilus=SimpleNamespace(
                        paper_engine="nautilus_matching",
                        matching_accuracy_mode="depth_l2",
                        intercept_os_signals=True,
                    )
                ),
            ),
        ),
        observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
        components={"strategies": []},
    )

    async def fake_build(settings=None):
        _ = settings
        return fake_bundle

    async def fail_stop(_scheduler):
        raise RuntimeError("shutdown failed")

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.build_nautilus_runtime",
        fake_build,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._stop_nautilus_scheduler",
        fail_stop,
    )
    def add_signal_handler(sig, handler):
        installed.append((sig, handler))
        signal.signal(sig, lambda _signum, _frame: None)

    def remove_signal_handler(sig):
        removed.append(sig)

    monkeypatch.setattr(
        "asyncio.get_running_loop",
        lambda: SimpleNamespace(
            add_signal_handler=add_signal_handler,
            remove_signal_handler=remove_signal_handler,
        ),
    )
    stop_event = asyncio.Event()
    stop_event.set()

    try:
        with pytest.raises(RuntimeError, match="shutdown failed"):
            await run_nautilus_cli_async(stop_event=stop_event)

        assert signal.getsignal(signal.SIGTERM) == previous[signal.SIGTERM]
        assert signal.getsignal(signal.SIGINT) == previous[signal.SIGINT]
        assert [item[0] for item in installed] == [signal.SIGTERM, signal.SIGINT]
        assert set(removed) == {signal.SIGTERM, signal.SIGINT}
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)

async def test_run_nautilus_cli_async_surfaces_node_run_failure(monkeypatch) -> None:
    class FakeTradingNode:
        def run(self):
            raise RuntimeError("node boom")

        def dispose(self):
            pass

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    fake_bundle = SimpleNamespace(
        node=FakeTradingNode(),
        websocket_tasks=[],
        scheduler=SimpleNamespace(
            stop=_noop,
            settings=_runtime_settings_stub(
                markets=SimpleNamespace(refresh_interval_sec=60),
                runtime=SimpleNamespace(
                    nautilus=SimpleNamespace(
                        paper_engine="nautilus_matching",
                        matching_accuracy_mode="depth_l2",
                    )
                ),
            ),
        ),
        observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
        components={"strategies": []},
    )

    async def fake_build(settings=None):
        _ = settings
        return fake_bundle

    async def fake_to_thread(fn, *args):
        return fn(*args)

    async def fake_report_loop(scheduler, stop_event):
        _ = scheduler
        await stop_event.wait()

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._run_nautilus_report_loop",
        fake_report_loop,
    )

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.build_nautilus_runtime",
        fake_build,
    )
    monkeypatch.setattr(
        "asyncio.to_thread",
        fake_to_thread,
    )

    with pytest.raises(RuntimeError, match="node boom"):
        await run_nautilus_cli_async()


async def test_run_nautilus_cli_async_waits_for_node_stop_instead_of_canceling_run_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_released = asyncio.Event()
    calls: list[str] = []

    class FakeTradingNode:
        def run(self):
            calls.append("run")

        def stop(self):
            calls.append("stop")
            run_released.set()

        def dispose(self):
            calls.append("dispose")

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    fake_bundle = SimpleNamespace(
        node=FakeTradingNode(),
        websocket_tasks=[],
        scheduler=SimpleNamespace(
            stop=_noop,
            settings=_runtime_settings_stub(
                markets=SimpleNamespace(refresh_interval_sec=60),
                runtime=SimpleNamespace(
                    nautilus=SimpleNamespace(
                        paper_engine="nautilus_matching",
                        matching_accuracy_mode="depth_l2",
                    )
                ),
            ),
        ),
        observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
        components={"strategies": []},
    )

    async def fake_build(settings=None):
        _ = settings
        return fake_bundle

    async def fake_to_thread(fn, *args):
        if getattr(fn, "__name__", "") != "run":
            return fn(*args)
        await run_released.wait()

    async def fake_report_loop(scheduler, stop_event):
        _ = scheduler
        stop_event.set()

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._run_nautilus_report_loop",
        fake_report_loop,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.build_nautilus_runtime",
        fake_build,
    )
    monkeypatch.setattr(
        "asyncio.to_thread",
        fake_to_thread,
    )

    await run_nautilus_cli_async()

    assert calls == ["stop"]



async def test_run_nautilus_cli_async_leaves_node_disposal_to_sync_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeTradingNode:
        def run(self):
            return None

        def dispose(self):
            raise AssertionError("async runtime must not dispose node inline")

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    async def fake_report_loop(scheduler, stop_event):
        _ = scheduler
        await stop_event.wait()

    fake_bundle = SimpleNamespace(
        node=FakeTradingNode(),
        websocket_tasks=[],
        scheduler=SimpleNamespace(
            stop=_noop,
            settings=_runtime_settings_stub(
                markets=SimpleNamespace(refresh_interval_sec=60),
                runtime=SimpleNamespace(
                    nautilus=SimpleNamespace(
                        paper_engine="nautilus_matching",
                        matching_accuracy_mode="depth_l2",
                    )
                ),
            ),
        ),
        observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
        components={"strategies": []},
    )

    async def fake_build(settings=None):
        _ = settings
        return fake_bundle

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._run_nautilus_report_loop",
        fake_report_loop,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.build_nautilus_runtime",
        fake_build,
    )

    node = await run_nautilus_cli_async()

    assert node is fake_bundle.node

async def test_run_nautilus_cli_async_notifies_and_starts_report_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod

    calls: list[tuple[object, ...]] = []

    class FakeTradingNode:
        def run(self):
            calls.append(("run",))

        def dispose(self):
            calls.append(("dispose",))

    class FakeObservability:
        async def notify_startup(self, strategy_names=(), **kwargs):
            calls.append(("startup", tuple(strategy_names), dict(kwargs)))

        async def notify_shutdown(self):
            calls.append(("shutdown",))

    async def fake_stop() -> None:
        calls.append(("scheduler_stop",))

    async def fake_build(settings=None):
        _ = settings
        return SimpleNamespace(
            node=FakeTradingNode(),
            websocket_tasks=[],
            scheduler=SimpleNamespace(
                stop=fake_stop,
                settings=_runtime_settings_stub(
                    runtime=SimpleNamespace(
                        nautilus=SimpleNamespace(
                            paper_engine="nautilus_matching",
                            matching_accuracy_mode="depth_l2",
                        )
                    )
                ),
            ),
            observability=FakeObservability(),
            components={"strategies": [SimpleNamespace(strategy_name="one_cent_buy")]},
        )

    async def fake_to_thread(fn, *args):
        return fn(*args)

    async def fake_report_loop(scheduler, stop_event):
        calls.append(("report_loop", scheduler))
        stop_event.set()

    monkeypatch.setattr(node_mod, "build_nautilus_runtime", fake_build)
    monkeypatch.setattr(node_mod, "_run_nautilus_report_loop", fake_report_loop, raising=False)
    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)

    await node_mod.run_nautilus_cli_async()

    assert any(call[0] == "startup" for call in calls)
    assert any(call[0] == "report_loop" for call in calls)
    assert any(call[0] == "shutdown" for call in calls)

async def test_run_nautilus_cli_async_tolerates_notification_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod

    calls: list[tuple[object, ...]] = []

    class FakeTradingNode:
        def run(self):
            calls.append(("run",))

        def dispose(self):
            calls.append(("dispose",))

    class FakeObservability:
        async def notify_startup(self, strategy_names=(), **kwargs):
            _ = strategy_names, kwargs
            raise RuntimeError("startup failed")

        async def notify_shutdown(self):
            raise RuntimeError("shutdown failed")

    class FakeLogger:
        def exception(self, message: str, *args: object) -> None:
            calls.append(("log", message, *args))

        def warning(self, message: str, *args: object) -> None:
            calls.append(("warn", message, *args))

    async def fake_stop() -> None:
        calls.append(("scheduler_stop",))

    async def fake_build(settings=None):
        _ = settings
        return SimpleNamespace(
            node=FakeTradingNode(),
            websocket_tasks=[],
            scheduler=SimpleNamespace(
                stop=fake_stop,
                logger=FakeLogger(),
                settings=_runtime_settings_stub(
                    markets=SimpleNamespace(refresh_interval_sec=60),
                    runtime=SimpleNamespace(
                        nautilus=SimpleNamespace(
                            paper_engine="nautilus_matching",
                            matching_accuracy_mode="depth_l2",
                        )
                    ),
                ),
            ),
            observability=FakeObservability(),
            components={"strategies": [SimpleNamespace(strategy_name="one_cent_buy")]},
        )

    async def fake_to_thread(fn, *args):
        return fn(*args)

    async def fake_report_loop(scheduler, stop_event):
        calls.append(("report_loop", scheduler))
        stop_event.set()

    monkeypatch.setattr(node_mod, "build_nautilus_runtime", fake_build)
    monkeypatch.setattr(node_mod, "_run_nautilus_report_loop", fake_report_loop, raising=False)
    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)

    await node_mod.run_nautilus_cli_async()

    assert any(call[0] == "run" for call in calls)
    assert not any(call[0] == "scheduler_stop" for call in calls)
    assert any(call[0] == "log" for call in calls)


async def test_stop_nautilus_scheduler_skips_legacy_wallet_persist_without_wallet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod

    calls: list[str] = []

    class FakeLogger:
        def warning(self, message: str, *args: object) -> None:
            calls.append(f"warn:{message}")

        def exception(self, message: str, *args: object) -> None:
            calls.append(f"exception:{message}")

    monkeypatch.setattr(
        node_mod.scheduler_health,
        "persist_health_snapshot",
        lambda scheduler: calls.append("health"),
    )

    scheduler = SimpleNamespace(logger=FakeLogger())

    await node_mod._stop_nautilus_scheduler(scheduler)

    assert calls == ["health"]


def test_run_nautilus_cli_disposes_node_after_async_exit(monkeypatch) -> None:
    class FakeNode:
        def __init__(self) -> None:
            self.disposed = False

        def run(self) -> None:
            return None

        def dispose(self) -> None:
            self.disposed = True

    node = FakeNode()

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    async def fake_prepare(settings):
        _ = settings
        return SimpleNamespace(stop=_noop, settings=_runtime_settings_stub()), (), SimpleNamespace()

    def fake_bundle(settings, scheduler, discovered_markets, observability):
        _ = settings, scheduler, discovered_markets, observability
        return SimpleNamespace(
            node=node,
            scheduler=SimpleNamespace(
                stop=_noop,
                settings=_runtime_settings_stub(
                    runtime=SimpleNamespace(
                        nautilus=SimpleNamespace(
                            paper_engine="nautilus_matching",
                            matching_accuracy_mode="depth_l2",
                        )
                    )
                ),
            ),
            observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
            components={"strategies": []},
        )

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._prepare_nautilus_runtime_context",
        fake_prepare,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._build_nautilus_runtime_bundle",
        fake_bundle,
    )

    run_nautilus_cli()

    assert node.disposed is True


def test_run_nautilus_cli_exits_cleanly_when_live_node_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeNode:
        def run(self) -> None:
            return None

        def dispose(self) -> None:
            return None

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    async def fake_prepare(settings):
        _ = settings
        return SimpleNamespace(stop=_noop, settings=_runtime_settings_stub()), (), SimpleNamespace()

    def fake_bundle(settings, scheduler, discovered_markets, observability):
        _ = settings, scheduler, discovered_markets, observability
        return SimpleNamespace(
            node=FakeNode(),
            scheduler=SimpleNamespace(
                stop=_noop,
                settings=_runtime_settings_stub(
                    runtime=SimpleNamespace(
                        nautilus=SimpleNamespace(
                            paper_engine="nautilus_matching",
                            matching_accuracy_mode="depth_l2",
                        )
                    )
                ),
            ),
            observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
            components={"strategies": [SimpleNamespace(strategy_name="vwap_momentum")]},
        )

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._prepare_nautilus_runtime_context",
        fake_prepare,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._build_nautilus_runtime_bundle",
        fake_bundle,
    )

    # Should exit cleanly — no RuntimeError raised.
    run_nautilus_cli()


def test_run_nautilus_cli_logs_warning_on_unexpected_return(monkeypatch, tmp_path) -> None:
    from polysignal_lab.observability.runtime_health import (
        read_runtime_heartbeat,
        read_runtime_startup_started_at,
    )

    class FakeNode:
        def run(self, raise_exception=False):
            return None

        def dispose(self):
            return None

    settings = Settings()
    settings.storage.state_dir = str(tmp_path / "state")
    startup_marker = tmp_path / "state" / "runtime_startup.json"
    startup_marker.parent.mkdir()
    startup_marker.write_text('{"started_at": "2026-06-30T11:00:00+00:00"}', encoding="utf-8")
    scheduler = SimpleNamespace(settings=settings, logger=SimpleNamespace(error=lambda *a, **k: None, warning=lambda *a, **k: None))
    observability = SimpleNamespace(
        notify_startup=AsyncMock(return_value=None),
        notify_shutdown=AsyncMock(return_value=None),
    )
    bundle = SimpleNamespace(
        scheduler=scheduler,
        components={"strategies": [SimpleNamespace(strategy_name="vwap_momentum")]},
        node=FakeNode(),
        observability=observability,
    )

    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node._prepare_nautilus_runtime_context", AsyncMock(return_value=(scheduler, [], observability)))
    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node._rebind_market_discovery_client", lambda _scheduler: None)
    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node._build_nautilus_runtime_bundle", lambda *_args: bundle)
    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node._stop_nautilus_scheduler", AsyncMock(return_value=None))

    # Should exit cleanly — no RuntimeError raised.
    run_nautilus_cli(settings)

def test_run_nautilus_cli_suppresses_heartbeat_write_failures_when_node_returns(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod

    class FakeNode:
        def run(self, raise_exception=False):
            return None

        def dispose(self):
            return None

    settings = Settings()
    settings.storage.state_dir = str(tmp_path / "state")
    scheduler = SimpleNamespace(settings=settings, logger=SimpleNamespace(error=lambda *a, **k: None, warning=lambda *a, **k: None))
    observability = SimpleNamespace(
        notify_startup=AsyncMock(return_value=None),
        notify_shutdown=AsyncMock(return_value=None),
    )
    bundle = SimpleNamespace(
        scheduler=scheduler,
        components={"strategies": [SimpleNamespace(strategy_name="vwap_momentum")]},
        node=FakeNode(),
        observability=observability,
    )

    def fail_write(*_args, **_kwargs):
        raise OSError("state directory unavailable")

    monkeypatch.setattr(node_mod, "_prepare_nautilus_runtime_context", AsyncMock(return_value=(scheduler, [], observability)))
    monkeypatch.setattr(node_mod, "_rebind_market_discovery_client", lambda _scheduler: None)
    monkeypatch.setattr(node_mod, "_build_nautilus_runtime_bundle", lambda *_args: bundle)
    monkeypatch.setattr(node_mod, "_stop_nautilus_scheduler", AsyncMock(return_value=None))
    monkeypatch.setattr(node_mod, "write_runtime_heartbeat", fail_write)

    # Should exit cleanly — heartbeat write failures are suppressed.
    run_nautilus_cli(settings)


def test_run_nautilus_cli_does_not_install_signal_handlers_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeNode:
        def run(self) -> None:
            return None

        def dispose(self) -> None:
            return None

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    async def fake_prepare(settings):
        _ = settings
        return SimpleNamespace(stop=_noop, settings=_runtime_settings_stub()), (), SimpleNamespace()

    def fake_bundle(settings, scheduler, discovered_markets, observability):
        _ = settings, scheduler, discovered_markets, observability
        return SimpleNamespace(
            node=FakeNode(),
            scheduler=SimpleNamespace(
                stop=_noop,
                settings=_runtime_settings_stub(
                    runtime=SimpleNamespace(
                        nautilus=SimpleNamespace(
                            paper_engine="nautilus_matching",
                            matching_accuracy_mode="depth_l2",
                        )
                    )
                ),
            ),
            observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
            components={"strategies": []},
        )

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._prepare_nautilus_runtime_context",
        fake_prepare,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._build_nautilus_runtime_bundle",
        fake_bundle,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._install_sync_os_signal_handlers",
        lambda _request_stop: pytest.fail("OS signal handlers must be opt-in"),
    )

    run_nautilus_cli()


def test_run_nautilus_cli_installs_signal_handlers_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed: list[object] = []

    class FakeNode:
        def run(self) -> None:
            return None

        def stop(self) -> None:
            return None

        def dispose(self) -> None:
            return None

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    async def fake_prepare(settings):
        _ = settings
        return SimpleNamespace(stop=_noop, settings=_runtime_settings_stub()), (), SimpleNamespace()

    def fake_bundle(settings, scheduler, discovered_markets, observability):
        _ = settings, scheduler, discovered_markets, observability
        return SimpleNamespace(
            node=FakeNode(),
            scheduler=SimpleNamespace(
                stop=_noop,
                settings=_runtime_settings_stub(
                    runtime=SimpleNamespace(
                        nautilus=SimpleNamespace(
                            paper_engine="nautilus_matching",
                            matching_accuracy_mode="depth_l2",
                            intercept_os_signals=True,
                        )
                    )
                ),
            ),
            observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
            components={"strategies": []},
        )

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._prepare_nautilus_runtime_context",
        fake_prepare,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._build_nautilus_runtime_bundle",
        fake_bundle,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._install_sync_os_signal_handlers",
        lambda handler: (installed.append(handler), lambda: None)[1],
    )

    run_nautilus_cli()

    assert len(installed) == 1


def test_run_nautilus_cli_restores_opt_in_signal_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = {
        signal.SIGTERM: signal.getsignal(signal.SIGTERM),
        signal.SIGINT: signal.getsignal(signal.SIGINT),
    }

    class FakeNode:
        def run(self) -> None:
            return None

        def stop(self) -> None:
            return None

        def dispose(self) -> None:
            return None

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    async def fake_prepare(settings):
        _ = settings
        return (
            SimpleNamespace(stop=_noop, settings=_runtime_settings_stub()),
            (),
            SimpleNamespace(),
        )

    def fake_bundle(settings, scheduler, discovered_markets, observability):
        _ = settings, scheduler, discovered_markets, observability
        return SimpleNamespace(
            node=FakeNode(),
            scheduler=SimpleNamespace(
                stop=_noop,
                settings=_runtime_settings_stub(
                    runtime=SimpleNamespace(
                        nautilus=SimpleNamespace(
                            paper_engine="nautilus_matching",
                            matching_accuracy_mode="depth_l2",
                            intercept_os_signals=True,
                        )
                    )
                ),
            ),
            observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
            components={"strategies": []},
        )

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._prepare_nautilus_runtime_context",
        fake_prepare,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._build_nautilus_runtime_bundle",
        fake_bundle,
    )

    try:
        run_nautilus_cli()

        assert signal.getsignal(signal.SIGTERM) == previous[signal.SIGTERM]
        assert signal.getsignal(signal.SIGINT) == previous[signal.SIGINT]
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def test_run_nautilus_cli_restores_signal_handlers_after_dispose_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = {
        signal.SIGTERM: signal.getsignal(signal.SIGTERM),
        signal.SIGINT: signal.getsignal(signal.SIGINT),
    }

    class FakeNode:
        def run(self) -> None:
            return None

        def stop(self) -> None:
            return None

        def dispose(self) -> None:
            raise RuntimeError("dispose failed")

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    async def fake_prepare(settings):
        _ = settings
        return (
            SimpleNamespace(stop=_noop, settings=_runtime_settings_stub()),
            (),
            SimpleNamespace(),
        )

    def fake_bundle(settings, scheduler, discovered_markets, observability):
        _ = settings, scheduler, discovered_markets, observability
        return SimpleNamespace(
            node=FakeNode(),
            scheduler=SimpleNamespace(
                stop=_noop,
                settings=_runtime_settings_stub(
                    runtime=SimpleNamespace(
                        nautilus=SimpleNamespace(
                            paper_engine="nautilus_matching",
                            matching_accuracy_mode="depth_l2",
                            intercept_os_signals=True,
                        )
                    )
                ),
            ),
            observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
            components={"strategies": []},
        )

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._prepare_nautilus_runtime_context",
        fake_prepare,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._build_nautilus_runtime_bundle",
        fake_bundle,
    )

    try:
        with pytest.raises(RuntimeError, match="dispose failed"):
            run_nautilus_cli()

        assert signal.getsignal(signal.SIGTERM) == previous[signal.SIGTERM]
        assert signal.getsignal(signal.SIGINT) == previous[signal.SIGINT]
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def test_run_nautilus_cli_prints_ready(monkeypatch, capsys) -> None:
    """run_nautilus_cli returns without hanging."""

    class FakeNode:
        def run(self) -> None:
            print("Nautilus runtime ready — 0 strategies")

        def dispose(self) -> None:
            return None

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    async def fake_prepare(settings):
        _ = settings
        return SimpleNamespace(stop=_noop, settings=_runtime_settings_stub()), (), SimpleNamespace()

    def fake_bundle(settings, scheduler, discovered_markets, observability):
        _ = settings, scheduler, discovered_markets, observability
        return SimpleNamespace(
            node=FakeNode(),
            scheduler=SimpleNamespace(
                stop=_noop,
                settings=_runtime_settings_stub(
                    runtime=SimpleNamespace(
                        nautilus=SimpleNamespace(
                            paper_engine="nautilus_matching",
                            matching_accuracy_mode="depth_l2",
                        )
                    )
                ),
            ),
            observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
            components={"strategies": []},
        )

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._prepare_nautilus_runtime_context",
        fake_prepare,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._build_nautilus_runtime_bundle",
        fake_bundle,
    )

    run_nautilus_cli()

    assert "Nautilus runtime ready — 0 strategies" in capsys.readouterr().out
