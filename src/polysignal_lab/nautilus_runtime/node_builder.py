from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, cast, runtime_checkable

from nautilus_trader.core import nautilus_pyo3
from nautilus_trader.core.nautilus_pyo3 import InstrumentId

from polysignal_lab.config import Settings, load_settings
from polysignal_lab.domain.market import Market
from polysignal_lab.nautilus_runtime.configured_markets import (
    configured_condition_ids,
    instrument_load_ids,
)
from polysignal_lab.nautilus_runtime.observability import ObservabilityService
from polysignal_lab.nautilus_runtime.polymarket_clients import (
    polymarket_data_client_name,
)
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
PolymarketUpDownEventSlugConfig = cast(
    Callable[..., object],
    getattr(nautilus_pyo3, "PolymarketUpDownEventSlugConfig"),
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


def _timeframe_minutes(timeframe: str) -> int:
    normalized = timeframe.strip().lower()
    if not normalized.endswith("m") or not normalized[:-1].isdigit():
        raise ValueError(f"unsupported Polymarket timeframe: {timeframe!r}")
    return int(normalized[:-1])


def _dynamic_event_slug_builder(settings: Settings, timeframe: str) -> object:
    return PolymarketUpDownEventSlugConfig(
        assets=list(settings.markets.assets),
        interval_mins=_timeframe_minutes(timeframe),
        periods=settings.runtime.nautilus.market_rotation.include_next_periods + 1,
        start_offset_periods=0,
    )


def _polymarket_instrument_configs(
    settings: Settings,
    markets: Sequence[Market],
) -> dict[str, object]:
    configs: dict[str, object] = {}
    for timeframe in settings.markets.timeframes:
        load_ids = instrument_load_ids(
            tuple(market for market in markets if market.timeframe == timeframe)
        )
        instrument_kwargs: dict[str, object] = {
            "event_slug_builder": _dynamic_event_slug_builder(settings, timeframe),
        }
        if load_ids:
            instrument_kwargs["load_ids"] = [
                InstrumentId.from_str(load_id) for load_id in load_ids
            ]
        client_name = polymarket_data_client_name(timeframe)
        configs[client_name] = PolymarketInstrumentProviderConfig(**instrument_kwargs)
    return configs


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

    # Official pyo3 providers own Gamma instrument load and dynamic slug refresh.
    # One provider per timeframe preserves the native single-interval builder contract.
    instrument_configs = _polymarket_instrument_configs(
        settings,
        configured_markets,
    )
    from polysignal_lab.nautilus_runtime.live_node import build_runtime_node as build

    node = build(settings, instrument_configs=instrument_configs)
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
