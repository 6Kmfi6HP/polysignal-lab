from __future__ import annotations

import asyncio
import logging
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest

from polysignal_lab.config import Settings
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.nautilus_runtime.backtest_node import build_backtest_engine
from polysignal_lab.nautilus_runtime.node import (
    _build_nautilus_runtime_bundle,
    _prepare_nautilus_runtime_context,
    run_nautilus_cli_async,
)
from polysignal_lab.nautilus_runtime.node_builder import (
    NautilusRuntimeBundle,
    build_live_node,
    build_runtime_node,
)
from polysignal_lab.nautilus_runtime.node_lifecycle import (
    _run_node_async,
    _strategy_names_from_bundle,
)
from polysignal_lab.nautilus_runtime.runtime_context_factory import (
    validate_native_runtime_settings,
)
from polysignal_lab.nautilus_runtime.runtime_registration import (
    enabled_strategy_names,
    register_runtime_components,
)


def _market(condition_id: str = "condition-btc-5m") -> Market:
    return Market(
        market_id=condition_id,
        market_slug=f"btc-updown-5m-{condition_id}",
        condition_id=condition_id,
        asset="BTC",
        timeframe="5m",
        start_ts=datetime(2026, 7, 17, tzinfo=UTC),
        end_ts=datetime(2026, 7, 17, tzinfo=UTC) + timedelta(minutes=5),
        outcome_tokens=[
            OutcomeToken(
                token_id=f"{condition_id}-up",
                side=Side.UP,
                outcome_name="Up",
                market_id=condition_id,
            ),
            OutcomeToken(
                token_id=f"{condition_id}-down",
                side=Side.DOWN,
                outcome_name="Down",
                market_id=condition_id,
            ),
        ],
    )


@pytest.fixture(autouse=True)
def _install_fake_polymarket_id_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "nautilus_trader.adapters.polymarket",
        SimpleNamespace(
            get_polymarket_instrument_id=lambda condition_id, token_id: (
                f"{condition_id}-{token_id}.POLYMARKET"
            ),
        ),
    )


def _settings_with_strategy(*, mode: str = "backtest") -> Settings:
    settings = Settings()
    settings.runtime.nautilus.execution_mode = cast(Any, mode)
    settings.strategies.set_explicit_strategy_names(("one_cent_buy",))
    return settings


class _RecordingRuntime:
    def __init__(self) -> None:
        self.actor_configs: list[object] = []
        self.strategy_configs: list[object] = []

    def add_actor_from_config(self, config: object) -> None:
        self.actor_configs.append(config)

    def add_strategy_from_config(self, config: object) -> None:
        self.strategy_configs.append(config)


class _Observability:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def start(self) -> None:
        self.calls.append("start")

    def stop(self) -> None:
        self.calls.append("stop")

    async def notify_startup(self, *_args: object, **_kwargs: object) -> None:
        self.calls.append("startup")

    async def notify_shutdown(self) -> None:
        self.calls.append("shutdown")


def test_native_runtime_rejects_spot_dependent_strategy_without_spot_ingress() -> None:
    settings = _settings_with_strategy(mode="sandbox")

    with pytest.raises(RuntimeError, match="spot data ingress"):
        validate_native_runtime_settings(settings)


def test_native_runtime_rejects_unreachable_interactive_control() -> None:
    settings = Settings()
    settings.telegram.interactive_enabled = True

    with pytest.raises(RuntimeError, match="interactive Telegram control"):
        validate_native_runtime_settings(settings)


@pytest.mark.anyio
async def test_prepare_runtime_checks_live_credentials_before_context_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polysignal_lab.nautilus_runtime import node as node_module

    settings = Settings()
    for name in (
        "POLYMARKET_API_KEY",
        "POLYMARKET_API_SECRET",
        "POLYMARKET_PASSPHRASE",
        "POLYMARKET_PK",
        "POLYMARKET_FUNDER",
    ):
        monkeypatch.setenv(name, "")
    monkeypatch.setattr(
        node_module,
        "build_nautilus_runtime_context",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError("context must not be built before credential validation")
        ),
    )

    with pytest.raises(RuntimeError, match="POLYMARKET_API_KEY"):
        await _prepare_nautilus_runtime_context(settings)


def test_shared_registration_uses_two_importable_actors_and_one_strategy() -> None:
    settings = _settings_with_strategy()
    runtime = _RecordingRuntime()
    market = _market()

    names = register_runtime_components(
        runtime,
        settings,
        markets=(market,),
        condition_ids=(market.condition_id,),
    )

    assert names == ("one_cent_buy",)
    assert [getattr(config, "actor_path") for config in runtime.actor_configs] == [
        "polysignal_lab.nautilus_runtime.market_rotation:MarketRotationActor",
        "polysignal_lab.nautilus_runtime.decision_policy_actor:DecisionPolicyActor",
    ]
    assert [getattr(config, "strategy_path") for config in runtime.strategy_configs] == [
        "polysignal_lab.nautilus_runtime.native_strategy:PolySignalNativeStrategy",
    ]
    strategy_payload = cast(dict[str, object], getattr(runtime.strategy_configs[0], "config"))
    assert strategy_payload["condition_ids"] == [market.condition_id]
    assert strategy_payload["strategy_names"] == ["one_cent_buy"]


def test_shared_registration_does_not_create_shadow_strategy_when_none_enabled() -> None:
    settings = Settings()
    runtime = _RecordingRuntime()

    names = register_runtime_components(runtime, settings)

    assert names == ()
    assert len(runtime.actor_configs) == 2
    assert runtime.strategy_configs == []


def test_backtest_router_uses_native_builder_with_shared_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polysignal_lab.nautilus_runtime import backtest_node

    settings = _settings_with_strategy()
    market = _market()
    runtime = object()
    captured: dict[str, object] = {}

    def fake_build(
        received_settings: Settings,
        *,
        markets: tuple[Market, ...],
        condition_ids: tuple[str, ...],
    ) -> object:
        captured.update(
            settings=received_settings,
            markets=markets,
            condition_ids=condition_ids,
        )
        return runtime

    monkeypatch.setattr(backtest_node, "build_backtest_engine", fake_build)

    result = build_runtime_node(settings, markets=(market,))

    assert result is runtime
    assert captured == {
        "settings": settings,
        "markets": (market,),
        "condition_ids": (market.condition_id,),
    }


def test_live_router_returns_native_node_and_registers_importable_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polysignal_lab.nautilus_runtime import live_node

    settings = _settings_with_strategy(mode="sandbox")
    native_node = _RecordingRuntime()
    monkeypatch.setattr(
        live_node,
        "build_runtime_node",
        lambda received_settings, *, instrument_config: (
            native_node
            if received_settings is settings and instrument_config is not None
            else None
        ),
    )

    result = build_runtime_node(settings)

    assert result is native_node
    assert len(native_node.actor_configs) == 2
    assert len(native_node.strategy_configs) == 1
    assert not hasattr(result, "components")
    assert not hasattr(result, "trader")


def test_build_live_node_rejects_backtest_mode() -> None:
    settings = Settings()
    settings.runtime.nautilus.execution_mode = "backtest"

    with pytest.raises(RuntimeError, match="sandbox or live"):
        build_live_node(settings)


def test_real_backtest_materializes_importable_native_components() -> None:
    settings = _settings_with_strategy()
    engine = cast(Any, build_backtest_engine(settings))

    try:
        assert engine.cache is not None
        assert engine.portfolio is not None
        assert not hasattr(engine, "components")
        assert not hasattr(engine, "bridge_registry")
    finally:
        engine.dispose()


def test_runtime_bundle_contains_only_native_node_and_external_io_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings()
    settings.runtime.nautilus.execution_mode = "backtest"
    context = SimpleNamespace(settings=settings)
    observability = _Observability()
    native_node = object()

    from polysignal_lab.nautilus_runtime import node as node_module

    monkeypatch.setattr(node_module, "build_runtime_node", lambda _settings: native_node)
    bundle = _build_nautilus_runtime_bundle(
        settings,
        cast(Any, context),
        cast(Any, observability),
    )

    assert bundle.node is native_node
    assert bundle.strategy_names == ()
    assert not hasattr(bundle, "components")
    assert not hasattr(bundle, "bridge_registry")
    assert not hasattr(context, "nautilus_cache")
    assert not hasattr(context, "nautilus_portfolio")


@pytest.mark.anyio
async def test_prepare_runtime_does_not_run_external_market_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polysignal_lab.nautilus_runtime import node as node_module

    settings = Settings()
    context = SimpleNamespace(
        settings=settings,
        health=SimpleNamespace(),
        persistence=SimpleNamespace(
            insert_system_event=lambda _payload: None,
            insert_signal=lambda _payload: None,
            insert_rejected_signal=lambda _payload: None,
            insert_report_result=lambda _payload: None,
            append_log=lambda _stream, _payload: None,
        ),
        publisher=SimpleNamespace(send=lambda *_args: None),
        publish_signal_once=lambda *_args: None,
        logger=logging.getLogger("test_nautilus_node"),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.live_node.validate_polymarket_market_data_credentials",
        lambda: None,
    )
    monkeypatch.setattr(
        node_module,
        "build_nautilus_runtime_context",
        lambda _settings: context,
    )

    prepared, _observability = await _prepare_nautilus_runtime_context(settings)

    assert prepared is context
    assert not hasattr(prepared, "market_universe")
    assert not hasattr(prepared, "market_discovery")


@pytest.mark.anyio
async def test_sync_live_node_run_is_offloaded_from_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class Node:
        def run(self) -> None:
            calls.append("run")

    async def fake_to_thread(function, *args):
        calls.append("thread")
        return function(*args)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    await _run_node_async(Node())

    assert calls == ["thread", "run"]


@pytest.mark.anyio
async def test_async_cli_uses_bundle_strategy_names_and_stops_observability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polysignal_lab.nautilus_runtime import node as node_module

    settings = Settings()
    observability = _Observability()
    context = SimpleNamespace(
        settings=settings,
        logger=logging.getLogger("test_nautilus_node"),
        health=SimpleNamespace(),
        persistence=SimpleNamespace(),
        _running=True,
    )
    bundle = NautilusRuntimeBundle(
        context=cast(Any, context),
        node=SimpleNamespace(run=lambda: None),
        observability=cast(Any, observability),
        strategy_names=("one_cent_buy",),
        websocket_tasks=[],
    )
    async def fake_build(_settings: Settings) -> NautilusRuntimeBundle:
        return bundle

    monkeypatch.setattr(node_module, "build_nautilus_runtime", fake_build)
    stop_event = asyncio.Event()
    stop_event.set()

    returned = await run_nautilus_cli_async(settings=settings, stop_event=stop_event)

    assert returned is bundle.node
    assert observability.calls == ["start", "startup", "shutdown", "stop"]
    assert context._running is False


def test_bundle_strategy_names_have_no_component_introspection() -> None:
    settings = Settings()
    bundle = NautilusRuntimeBundle(
        context=cast(Any, SimpleNamespace(settings=settings)),
        node=object(),
        observability=cast(Any, _Observability()),
        strategy_names=("one_cent_buy", "ptb_diff"),
        websocket_tasks=[],
    )

    assert enabled_strategy_names(_settings_with_strategy()) == ("one_cent_buy",)
    assert _strategy_names_from_bundle(bundle) == ["one_cent_buy", "ptb_diff"]
