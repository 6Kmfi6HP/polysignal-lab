from __future__ import annotations

import asyncio
import logging
import sys
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
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
    _stop_node_async,
    _strategy_names_from_bundle,
)
from polysignal_lab.nautilus_runtime.os_signals import (
    _reset_process_stop_request,
    request_process_stop,
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
async def test_prepare_runtime_builds_context_without_python_credential_gate(
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
        node_module,
        "build_nautilus_runtime_context",
        lambda _settings: context,
    )

    prepared, _observability = await _prepare_nautilus_runtime_context(settings)

    assert prepared is context


def test_shared_registration_uses_rotation_actor_and_one_strategy() -> None:
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
    ]
    assert [
        getattr(config, "strategy_path") for config in runtime.strategy_configs
    ] == [
        "polysignal_lab.nautilus_runtime.native_strategy:PolySignalNativeStrategy",
    ]
    strategy_payload = cast(
        dict[str, object], getattr(runtime.strategy_configs[0], "config")
    )
    assert strategy_payload["condition_ids"] == []
    # MarketRotationActor universe events are the sole active-set source.
    assert strategy_payload["strategy_names"] == ["one_cent_buy"]
    assert strategy_payload["strategy_name"] == "one_cent_buy"
    assert strategy_payload["strategy_id"] == "PolySignal-one_cent_buy"


def test_shared_registration_adds_one_strategy_per_enabled_alpha() -> None:
    settings = Settings()
    settings.strategies.set_explicit_strategy_names(("one_cent_buy", "ptb_diff"))
    runtime = _RecordingRuntime()

    names = register_runtime_components(runtime, settings)

    assert names == ("one_cent_buy", "ptb_diff")
    assert len(runtime.strategy_configs) == 2
    payloads = [
        cast(dict[str, object], getattr(cfg, "config"))
        for cfg in runtime.strategy_configs
    ]
    assert [p["strategy_name"] for p in payloads] == ["one_cent_buy", "ptb_diff"]
    assert [p["strategy_id"] for p in payloads] == [
        "PolySignal-one_cent_buy",
        "PolySignal-ptb_diff",
    ]


def test_shared_registration_activates_all_production_strategies() -> None:
    settings = Settings.from_yaml("config/signal_bot.yaml")
    runtime = _RecordingRuntime()

    names = register_runtime_components(runtime, settings)

    assert names == (
        "vwap_momentum",
        "late_consensus",
        "ptb_diff",
        "binary_momentum",
        "dump_hedge",
        "fibonacci_bot",
        "low_side_dual_reversion",
        "mid_price_sizing",
        "ninety_nine_cent_sniper",
        "one_cent_buy",
        "pre_order_market",
        "skew_mean_reversion",
    )
    assert [getattr(cfg, "config")["strategy_name"] for cfg in runtime.strategy_configs] == [
        *names,
    ]


def test_shared_registration_empty_market_configs_bootstrap_from_provider() -> None:
    settings = Settings()
    settings.strategies.set_explicit_strategy_names(("one_cent_buy",))
    runtime = _RecordingRuntime()

    register_runtime_components(runtime, settings)

    actor_payload = cast(dict[str, object], getattr(runtime.actor_configs[0], "config"))
    strategy_payload = cast(
        dict[str, object], getattr(runtime.strategy_configs[0], "config")
    )
    assert actor_payload["markets_json"] == "[]"
    assert strategy_payload["markets_json"] == "[]"
    assert strategy_payload["condition_ids"] == []
    assert settings.runtime.nautilus.market_rotation.enabled is True


def test_shared_registration_does_not_create_shadow_strategy_when_none_enabled() -> (
    None
):
    settings = Settings()
    runtime = _RecordingRuntime()

    names = register_runtime_components(runtime, settings)

    assert names == ()
    assert [getattr(config, "actor_path") for config in runtime.actor_configs] == [
        "polysignal_lab.nautilus_runtime.market_rotation:MarketRotationActor",
        "polysignal_lab.nautilus_runtime.recorded_market_data:RecordedMarketDataActor",
    ]
    assert runtime.strategy_configs == []


def test_sandbox_recorder_skipped_when_recording_disabled() -> None:
    settings = Settings()  # default execution_mode is sandbox
    settings.storage.recorded_market_data_enabled = False
    runtime = _RecordingRuntime()

    register_runtime_components(runtime, settings)

    assert [getattr(config, "actor_path") for config in runtime.actor_configs] == [
        "polysignal_lab.nautilus_runtime.market_rotation:MarketRotationActor",
    ]


def test_sandbox_recorder_registered_by_default() -> None:
    settings = Settings()  # default execution_mode sandbox, recording enabled True
    runtime = _RecordingRuntime()

    register_runtime_components(runtime, settings)

    assert [getattr(config, "actor_path") for config in runtime.actor_configs] == [
        "polysignal_lab.nautilus_runtime.market_rotation:MarketRotationActor",
        "polysignal_lab.nautilus_runtime.recorded_market_data:RecordedMarketDataActor",
    ]


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

    def fake_build_runtime_node(
        received_settings: Settings,
        *,
        instrument_configs: dict[str, object],
    ) -> object | None:
        if received_settings is settings and tuple(instrument_configs) == (
            "POLYMARKET-5M",
            "POLYMARKET-15M",
        ):
            return native_node
        return None

    monkeypatch.setattr(live_node, "build_runtime_node", fake_build_runtime_node)

    result = build_runtime_node(settings)

    assert result is native_node
    assert [getattr(config, "actor_path") for config in native_node.actor_configs] == [
        "polysignal_lab.nautilus_runtime.market_rotation:MarketRotationActor",
        "polysignal_lab.nautilus_runtime.recorded_market_data:RecordedMarketDataActor",
    ]
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


def test_runtime_bundle_exposes_native_reporting_sources_to_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings()
    settings.runtime.nautilus.execution_mode = "backtest"
    context = SimpleNamespace(settings=settings)
    observability = _Observability()
    native_cache = object()
    native_portfolio = object()
    native_node = SimpleNamespace(
        cache=native_cache,
        portfolio=native_portfolio,
    )

    from polysignal_lab.nautilus_runtime import node as node_module

    monkeypatch.setattr(
        node_module, "build_runtime_node", lambda _settings: native_node
    )
    bundle = _build_nautilus_runtime_bundle(
        settings,
        cast(Any, context),
        cast(Any, observability),
    )

    assert bundle.node is native_node
    assert bundle.strategy_names == ()
    assert not hasattr(bundle, "components")
    assert not hasattr(bundle, "bridge_registry")
    assert context.nautilus_cache is native_cache
    assert context.nautilus_portfolio is native_portfolio


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
async def test_pyo3_livenode_run_raises_instead_of_cross_thread_panic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B3: a PyO3 LiveNode must fail fast, not panic on a worker thread."""
    calls: list[str] = []

    class LiveNode:
        __module__ = "nautilus_trader.core.nautilus_pyo3.live"

        def run(self) -> None:
            calls.append("run")

    async def fake_to_thread(function, *args):
        calls.append("thread")
        return function(*args)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    with pytest.raises(RuntimeError, match="PyO3 LiveNode cannot run"):
        await _run_node_async(LiveNode())

    assert calls == []


def test_supervised_restart_callback_never_calls_node_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    raised: list[str] = []
    callbacks: list[Callable[[str], None]] = []

    class Watchdog:
        def set_restart_callback(self, callback: Callable[[str], None]) -> None:
            callbacks.append(callback)

    watchdog = Watchdog()
    bundle = SimpleNamespace(observability=SimpleNamespace(liveness_watchdog=watchdog))
    node = SimpleNamespace(stop=lambda: calls.append("stop"))
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.request_process_stop",
        lambda: raised.append("signal"),
    )

    from polysignal_lab.nautilus_runtime.node import _bind_supervised_restart

    _bind_supervised_restart(cast(Any, bundle), node)
    assert len(callbacks) == 1
    errors: list[str] = []

    def invoke() -> None:
        try:
            callbacks[0]("fleet_never_ready")
        except Exception as exc:  # pragma: no cover - test failure channel
            errors.append(str(exc))

    thread = threading.Thread(target=invoke)
    thread.start()
    thread.join(timeout=2.0)

    assert errors == []
    assert calls == []
    assert raised == ["signal"]


def test_request_process_stop_is_idempotent_within_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raised: list[str] = []
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.os_signals._raise_stop_signal",
        lambda: raised.append("stop"),
    )
    _reset_process_stop_request()
    assert request_process_stop() is True
    assert request_process_stop() is False
    assert raised == ["stop"]
    _reset_process_stop_request()


@pytest.mark.anyio
async def test_stop_pyo3_livenode_does_not_cross_thread_call_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    signals: list[str] = []

    class LiveNode:
        __module__ = "nautilus_trader.core.nautilus_pyo3.live"

    node = LiveNode()
    setattr(node, "stop", lambda: calls.append("stop"))
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.os_signals.request_process_stop",
        lambda: signals.append("signal"),
    )

    await _stop_node_async(node)

    assert calls == []
    assert signals == ["signal"]


@pytest.mark.anyio
async def test_async_cli_uses_bundle_strategy_names_and_stops_observability(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from polysignal_lab.nautilus_runtime import node as node_module

    settings = Settings()
    settings.logging.directory = str(tmp_path / "logs")
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
    )

    assert enabled_strategy_names(_settings_with_strategy()) == ("one_cent_buy",)
    assert _strategy_names_from_bundle(bundle) == ["one_cent_buy", "ptb_diff"]


async def _noop_async() -> None:
    return None


@pytest.fixture
def _unbind_missing_value_counter() -> Iterator[None]:
    from polysignal_lab.domain.missing_values import bind_missing_value_counter

    bind_missing_value_counter(None)
    yield
    bind_missing_value_counter(None)


def _fake_runtime_context(health: object) -> SimpleNamespace:
    return SimpleNamespace(
        settings=Settings(),
        health=health,
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


@pytest.mark.anyio
@pytest.mark.usefixtures("_unbind_missing_value_counter")
async def test_prepare_runtime_binds_missing_value_collapse_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polysignal_lab.domain.missing_values import missing_value_counter
    from polysignal_lab.nautilus_runtime import node as node_module
    from polysignal_lab.observability.health import HealthRegistry

    health = HealthRegistry()
    context = _fake_runtime_context(health)
    monkeypatch.setattr(
        node_module,
        "build_nautilus_runtime_context",
        lambda _settings: context,
    )

    _prepared, _observability = await _prepare_nautilus_runtime_context(Settings())

    assert missing_value_counter() is health


@pytest.mark.anyio
@pytest.mark.usefixtures("_unbind_missing_value_counter")
async def test_async_runtime_shutdown_unbinds_missing_value_collapse_counter() -> None:
    from polysignal_lab.domain.missing_values import (
        bind_missing_value_counter,
        missing_value_counter,
    )
    from polysignal_lab.nautilus_runtime.node_lifecycle import (
        _finalize_async_cli_runtime,
    )
    from polysignal_lab.observability.health import HealthRegistry

    health = HealthRegistry()
    bind_missing_value_counter(health)
    bundle = NautilusRuntimeBundle(
        context=cast(Any, _fake_runtime_context(health)),
        node=SimpleNamespace(),
        observability=cast(Any, SimpleNamespace(notify_shutdown=_noop_async)),
        strategy_names=(),
    )

    await _finalize_async_cli_runtime(
        bundle,
        asyncio.Event(),
        logging.getLogger("test_nautilus_node"),
        lambda: None,
    )

    assert missing_value_counter() is None


@pytest.mark.usefixtures("_unbind_missing_value_counter")
def test_sync_runtime_shutdown_unbinds_missing_value_collapse_counter() -> None:
    from polysignal_lab.domain.missing_values import (
        bind_missing_value_counter,
        missing_value_counter,
    )
    from polysignal_lab.nautilus_runtime.node_lifecycle import (
        _finalize_sync_cli_runtime,
    )
    from polysignal_lab.observability.health import HealthRegistry

    health = HealthRegistry()
    bind_missing_value_counter(health)
    bundle = NautilusRuntimeBundle(
        context=cast(Any, _fake_runtime_context(health)),
        node=SimpleNamespace(),
        observability=cast(Any, SimpleNamespace(notify_shutdown=_noop_async)),
        strategy_names=(),
    )

    _finalize_sync_cli_runtime(
        bundle,
        SimpleNamespace(),
        logging.getLogger("test_nautilus_node"),
        lambda: None,
    )

    assert missing_value_counter() is None
