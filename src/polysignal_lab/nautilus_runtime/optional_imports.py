from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module


@dataclass(frozen=True, slots=True)
class LiveRuntimeSymbols:
    live_node: object
    trader_id: Callable[[str], object]
    environment: object
    polymarket_data_factory: object
    sandbox_exec_factory: object


def load_live_runtime_symbols() -> LiveRuntimeSymbols:
    live_mod = import_module("nautilus_trader.live")
    common_mod = import_module("nautilus_trader.common")
    identifiers_mod = import_module("nautilus_trader.model.identifiers")
    polymarket_mod = import_module("nautilus_trader.adapters.polymarket")
    sandbox_mod = import_module("nautilus_trader.adapters.sandbox.factory")
    return LiveRuntimeSymbols(
        live_node=live_mod.LiveNode,
        trader_id=identifiers_mod.TraderId,
        environment=common_mod.Environment,
        polymarket_data_factory=polymarket_mod.PolymarketLiveDataClientFactory,
        sandbox_exec_factory=sandbox_mod.SandboxLiveExecClientFactory,
    )
