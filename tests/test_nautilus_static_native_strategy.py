from __future__ import annotations

import sys
from collections.abc import Callable
from importlib import import_module
from types import ModuleType
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
    strategy_module = ModuleType("nautilus_trader.trading.strategy")
    trading_module = ModuleType("nautilus_trader.trading")

    class FakeActor:
        def __init__(self, *, config: object) -> None:
            self.actor_config = config

    setattr(actor_module, "Actor", FakeActor)
    setattr(config_module, "ActorConfig", lambda: "actor-config")
    setattr(config_module, "StrategyConfig", lambda: strategy_config)
    setattr(strategy_module, "Strategy", strategy_base)
    setattr(nautilus_module, "common", common_module)
    setattr(nautilus_module, "config", config_module)
    setattr(nautilus_module, "trading", trading_module)
    setattr(common_module, "actor", actor_module)
    setattr(trading_module, "strategy", strategy_module)

    monkeypatch.setitem(sys.modules, "nautilus_trader", nautilus_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.common", common_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.common.actor", actor_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.config", config_module)
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
    )

    assert getattr(strategy, "nautilus_config") == "strategy-config"


class FakeAssemblerForRuntimeType:
    def build(self, condition_id: str) -> None:
        _ = condition_id
        return None
