from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, cast, runtime_checkable

from nautilus_trader.core import nautilus_pyo3

from polysignal_lab.config import Settings, load_settings
from polysignal_lab.domain.market import Market
from polysignal_lab.nautilus_runtime.node_builder_components import (
    configured_condition_ids,
    instrument_load_ids,
)
from polysignal_lab.nautilus_runtime.observability import ObservabilityService
from polysignal_lab.nautilus_runtime.runtime_context_factory import (
    NautilusRuntimeContext,
    build_nautilus_runtime_context as build_nautilus_runtime_context,
)
from polysignal_lab.nautilus_runtime.runtime_registration import (
    register_runtime_components,
)

PolymarketInstrumentProviderConfig = cast(
    Callable[..., object],
    getattr(nautilus_pyo3, "PolymarketInstrumentProviderConfig"),
)


@runtime_checkable
class _Disposable(Protocol):
    def dispose(self) -> None: ...


@dataclass(slots=True)
class NautilusRuntimeBundle:
    context: NautilusRuntimeContext
    node: object
    observability: ObservabilityService
    strategy_names: tuple[str, ...]


def build_runtime_node(
    settings: Settings,
    *,
    markets: Sequence[Market] = (),
    condition_ids: Sequence[str] = (),
) -> object:
    configured_markets = tuple(markets)
    configured_ids = configured_condition_ids(condition_ids, configured_markets)
    if settings.runtime.nautilus.execution_mode == "backtest":
        from polysignal_lab.nautilus_runtime.backtest_node import build_backtest_engine

        return build_backtest_engine(
            settings,
            markets=configured_markets,
            condition_ids=configured_ids,
        )

    instrument_config = PolymarketInstrumentProviderConfig(
        load_ids=instrument_load_ids(configured_markets),
    )
    from polysignal_lab.nautilus_runtime.live_node import build_runtime_node as build

    node = build(settings, instrument_config=instrument_config)
    register_runtime_components(
        node,
        settings,
        markets=configured_markets,
        condition_ids=configured_ids,
    )
    return node


def build_live_node(
    settings: Settings | None = None,
    *,
    condition_ids: Sequence[str] = (),
    markets: Sequence[Market] = (),
) -> object:
    resolved = settings or load_settings()
    if resolved.runtime.nautilus.execution_mode == "backtest":
        raise RuntimeError("build_live_node requires sandbox or live execution mode")
    return build_runtime_node(
        resolved,
        markets=markets,
        condition_ids=condition_ids,
    )


async def build_nautilus_runtime(
    settings: Settings | None = None,
) -> NautilusRuntimeBundle:
    from polysignal_lab.nautilus_runtime.node import (
        _build_nautilus_runtime_bundle,
        _prepare_nautilus_runtime_context,
    )

    resolved = settings or load_settings()
    context, observability = await _prepare_nautilus_runtime_context(resolved)
    return _build_nautilus_runtime_bundle(resolved, context, observability)
