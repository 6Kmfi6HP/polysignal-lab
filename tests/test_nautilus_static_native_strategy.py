from __future__ import annotations

import sys
from collections.abc import Callable
from importlib import import_module
from types import ModuleType, SimpleNamespace
from typing import cast

import pytest

from polysignal_lab.alpha.types import AlphaCore


def _load_static_native_strategy(
    monkeypatch: pytest.MonkeyPatch,
    strategy_base: type[object],
    strategy_config: object,
) -> type[object]:
    runtime_module_name = "polysignal_lab.nautilus_runtime.native_strategy"
    previous_runtime_module = sys.modules.get(runtime_module_name)
    _ = sys.modules.pop(runtime_module_name, None)

    nautilus_module = ModuleType("nautilus_trader")
    common_module = ModuleType("nautilus_trader.common")
    actor_module = ModuleType("nautilus_trader.common.actor")
    config_module = ModuleType("nautilus_trader.config")
    core_module = ModuleType("nautilus_trader.core")
    core_data_module = ModuleType("nautilus_trader.core.data")
    model_module = ModuleType("nautilus_trader.model")
    model_custom_module = ModuleType("nautilus_trader.model.custom")
    model_identifiers_module = ModuleType("nautilus_trader.model.identifiers")
    model_objects_module = ModuleType("nautilus_trader.model.objects")
    model_enums_module = ModuleType("nautilus_trader.model.enums")
    strategy_module = ModuleType("nautilus_trader.trading.strategy")
    trading_module = ModuleType("nautilus_trader.trading")

    class FakeData:
        pass

    def fake_customdataclass(cls: type[object]) -> type[object]:
        return cls

    fake_order_side = SimpleNamespace(BUY="BUY", SELL="SELL")
    fake_order_status = SimpleNamespace(
        INITIALIZED="INITIALIZED",
        SUBMITTED="SUBMITTED",
        ACCEPTED="ACCEPTED",
        REJECTED="REJECTED",
        CANCELED="CANCELED",
        EXPIRED="EXPIRED",
        FILLED="FILLED",
    )
    fake_time_in_force = SimpleNamespace(GTC="GTC", GTD="GTD", IOC="IOC", FOK="FOK")

    setattr(core_data_module, "Data", FakeData)
    setattr(model_custom_module, "customdataclass", fake_customdataclass)
    setattr(model_identifiers_module, "InstrumentId", str)
    setattr(model_objects_module, "Price", object)
    setattr(model_objects_module, "Quantity", object)
    setattr(model_enums_module, "OrderSide", fake_order_side)
    setattr(model_enums_module, "OrderStatus", fake_order_status)
    setattr(model_enums_module, "TimeInForce", fake_time_in_force)

    class FakeActor:
        def __init__(self, *, config: object) -> None:
            self.actor_config = config

    setattr(actor_module, "Actor", FakeActor)
    setattr(config_module, "ActorConfig", lambda: "actor-config")
    setattr(config_module, "StrategyConfig", lambda: strategy_config)
    setattr(strategy_module, "Strategy", strategy_base)
    setattr(nautilus_module, "common", common_module)
    setattr(nautilus_module, "config", config_module)
    setattr(nautilus_module, "core", core_module)
    setattr(nautilus_module, "model", model_module)
    setattr(nautilus_module, "trading", trading_module)
    setattr(common_module, "actor", actor_module)
    setattr(core_module, "data", core_data_module)
    setattr(model_module, "custom", model_custom_module)
    setattr(model_module, "enums", model_enums_module)
    setattr(model_module, "identifiers", model_identifiers_module)
    setattr(model_module, "objects", model_objects_module)
    setattr(trading_module, "strategy", strategy_module)

    monkeypatch.setitem(sys.modules, "nautilus_trader", nautilus_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.common", common_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.common.actor", actor_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.config", config_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.core", core_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.core.data", core_data_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.model", model_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.model.custom", model_custom_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.model.enums", model_enums_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.model.identifiers", model_identifiers_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.model.objects", model_objects_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.trading", trading_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.trading.strategy", strategy_module)

    try:
        module = import_module(runtime_module_name)
        return cast(type[object], module.PolySignalNativeStrategy)
    finally:
        if previous_runtime_module is None:
            _ = sys.modules.pop(runtime_module_name, None)
        else:
            sys.modules[runtime_module_name] = previous_runtime_module


def test_static_native_strategy_initializes_nautilus_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeNautilusBase:
        def __init__(self, *, config: object) -> None:
            self.nautilus_config: object = config

    class FakeRegistry:
        def by_condition(self, _condition_id: str) -> None:
            return None

    strategy_type = cast(
        Callable[..., object],
        _load_static_native_strategy(
            monkeypatch,
            FakeNautilusBase,
            "strategy-config",
        ),
    )
    strategy = strategy_type(
        core=cast(AlphaCore, object()),
        assembler=FakeAssemblerForRuntimeType(),
        condition_ids=(),
        strategy_name="ptb_diff",
        registry=FakeRegistry(),
        policy=SimpleNamespace(),
    )

    assert getattr(strategy, "nautilus_config") == "strategy-config"


class FakeAssemblerForRuntimeType:
    def build(self, condition_id: str) -> None:
        _ = condition_id
        return None
