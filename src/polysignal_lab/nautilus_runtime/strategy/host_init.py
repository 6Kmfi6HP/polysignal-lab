"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Callable, collections.abc.Sequence, dataclasses, dataclasses.dataclass, datetime, datetime.datetime, typing
Output: resolve_host_construction, bind_host_runtime, resolve_instrument_from_cache, HostInitRequest, HostConstruction
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from polysignal_lab.alpha.types import AlphaCore
from polysignal_lab.config import MarketConfig
from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_runtime.custom_data_state import StrategyCustomDataState
from polysignal_lab.nautilus_runtime.decision_policy import (
    DecisionPolicy,
    decision_policy_from_settings,
)
from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.native_strategy_exit import NativeExitPolicy
from polysignal_lab.nautilus_runtime.runtime_configs import PolySignalStrategyConfig
from polysignal_lab.nautilus_runtime.strategy import subscriptions as subs
from polysignal_lab.nautilus_runtime.strategy.config_deps import dependencies_from_config
from polysignal_lab.nautilus_runtime.strategy.decision_pipeline import (
    DecisionPipelineState,
    DecisionResultHandler,
    NativeDecisionSinkImpl,
)

from polysignal_lab.nautilus_runtime.strategy.helpers import (
    MISSING_PROJECTIONS_ERROR,
    _Assembler,
    _Observability,
    _asset_conditions,
    _assembler_with_custom_data,
    catalog_instrument_id_resolver,
)


@dataclass(frozen=True, slots=True)
class HostInitRequest:
    config: object | None = None
    core: AlphaCore | None = None
    assembler: _Assembler | None = None
    condition_ids: Sequence[str] = ()
    strategy_name: str = ""
    fixed_stake_usdc: float = 10.0
    orderbook_staleness_ms: float = 60_000.0
    exit_model: object | None = None
    data_names: Sequence[str] = ()
    book_type: str = "L2_MBP"
    instrument_id_resolver: Callable[[str], object] | None = None
    registry: MarketCatalog | None = None
    observability: _Observability | None = None
    progress_callback: Callable[[str], None] | None = None
    readiness_callback: Callable[[str, bool, dict[str, object]], None] | None = None
    unsubscribe_exited: bool = True
    l1_book_snapshot_interval_ms: int = 0
    policy: DecisionPolicy | None = None
    market_config: MarketConfig = field(default_factory=MarketConfig)
    spot_data_source: str = "polymarket_rtds"


@dataclass(frozen=True, slots=True)
class HostConstruction:
    """Resolved Strategy DI before Nautilus StrategyConfig super().__init__."""

    nautilus_config: object
    core: AlphaCore
    assembler: _Assembler
    registry: MarketCatalog
    instrument_id_resolver: Callable[[str], object]
    policy: DecisionPolicy
    strategy_name: str
    condition_ids: tuple[str, ...]
    fixed_stake_usdc: float
    orderbook_staleness_ms: float
    exit_model: object | None
    data_names: tuple[str, ...]
    book_type: str
    l1_book_snapshot_interval_ms: int
    unsubscribe_exited: bool
    execution_mode: str
    observability: _Observability | None
    progress_callback: Callable[[str], None] | None
    readiness_callback: Callable[[str, bool, dict[str, object]], None] | None
    market_config: MarketConfig
    spot_data_source: str


def _from_strategy_config(req: HostInitRequest) -> HostInitRequest:
    config = req.config
    assert isinstance(config, PolySignalStrategyConfig)
    core, assembler, registry, instrument_id_resolver = dependencies_from_config(config)
    settings = config.settings()
    resolved_policy = req.policy or decision_policy_from_settings(settings)
    return HostInitRequest(
        config=config,
        core=core,
        assembler=assembler,
        registry=registry,
        instrument_id_resolver=instrument_id_resolver,
        policy=resolved_policy,
        condition_ids=tuple(config.condition_ids),
        strategy_name=config.strategy_name,
        fixed_stake_usdc=float(settings.trading.fixed_stake_usdc),
        exit_model=settings.trading.exit_model,
        book_type=settings.runtime.nautilus.sandbox_book_type,
        unsubscribe_exited=settings.runtime.nautilus.market_rotation.unsubscribe_exited,
        l1_book_snapshot_interval_ms=settings.runtime.nautilus.l1_book_snapshot_interval_ms,
        orderbook_staleness_ms=float(settings.data.polymarket.max_book_staleness_ms),
        data_names=req.data_names,
        observability=req.observability,
        progress_callback=req.progress_callback,
        readiness_callback=req.readiness_callback,
        market_config=settings.markets,
        spot_data_source=settings.runtime.nautilus.spot_data.source,
    )


def _nautilus_config_for(req: HostInitRequest) -> tuple[object, str]:
    from nautilus_trader.core.nautilus_pyo3 import StrategyConfig, StrategyId

    if isinstance(req.config, PolySignalStrategyConfig):
        return (
            StrategyConfig(
                strategy_id=StrategyId(str(req.config.strategy_id)),
                order_id_tag=str(req.config.order_id_tag),
            ),
            req.config.settings().runtime.nautilus.execution_mode,
        )
    return (
        StrategyConfig(
            strategy_id=StrategyId(f"PolySignal-{req.strategy_name}"),
            order_id_tag=req.strategy_name,
        ),
        "sandbox",
    )


def resolve_host_construction(req: HostInitRequest) -> HostConstruction:
    work = req
    if isinstance(req.config, PolySignalStrategyConfig) and req.core is None:
        work = _from_strategy_config(req)
    if not work.strategy_name:
        raise RuntimeError("PolySignalNativeStrategy requires strategy_name")
    if work.core is None:
        raise RuntimeError("PolySignalNativeStrategy requires core")
    if work.registry is None or work.assembler is None:
        raise RuntimeError(MISSING_PROJECTIONS_ERROR)
    resolver = work.instrument_id_resolver
    if resolver is None:
        resolver = catalog_instrument_id_resolver(work.registry)
    nautilus_config, execution_mode = _nautilus_config_for(work)
    return HostConstruction(
        nautilus_config=nautilus_config,
        core=work.core,
        assembler=work.assembler,
        registry=work.registry,
        instrument_id_resolver=resolver,
        policy=work.policy or DecisionPolicy(),
        strategy_name=work.strategy_name,
        condition_ids=tuple(work.condition_ids),
        fixed_stake_usdc=work.fixed_stake_usdc,
        orderbook_staleness_ms=float(work.orderbook_staleness_ms),
        exit_model=work.exit_model,
        data_names=tuple(work.data_names),
        book_type=work.book_type,
        l1_book_snapshot_interval_ms=int(work.l1_book_snapshot_interval_ms),
        unsubscribe_exited=work.unsubscribe_exited,
        execution_mode=execution_mode,
        observability=work.observability,
        progress_callback=work.progress_callback,
        readiness_callback=work.readiness_callback,
        market_config=work.market_config,
        spot_data_source=work.spot_data_source,
    )


def _bind_di_fields(strategy: Any, host: HostConstruction) -> None:
    strategy._execution_mode = host.execution_mode
    strategy.core = host.core
    strategy.custom_data = StrategyCustomDataState()
    resolved = _assembler_with_custom_data(host.assembler, strategy.custom_data)
    if resolved is None:
        raise RuntimeError(MISSING_PROJECTIONS_ERROR)
    strategy.assembler = resolved
    strategy.condition_ids = host.condition_ids
    strategy.strategy_name = host.strategy_name
    strategy.registry = host.registry
    strategy._market_config = host.market_config
    strategy._spot_data_source = host.spot_data_source
    strategy.policy = host.policy  # Strategy-owned DecisionPolicy (not Actor bus)
    strategy.fixed_stake_usdc = host.fixed_stake_usdc
    strategy.exit_policy = NativeExitPolicy.from_config(host.exit_model)
    strategy.data_names = host.data_names
    strategy.book_type = host.book_type
    strategy.l1_book_snapshot_interval_ms = host.l1_book_snapshot_interval_ms
    strategy.instrument_id_resolver = host.instrument_id_resolver
    strategy.observability = host.observability
    strategy.progress_callback = host.progress_callback
    strategy.readiness_callback = host.readiness_callback
    strategy.orderbook_staleness_ms = host.orderbook_staleness_ms
    strategy._startup_condition_ids = strategy.condition_ids
    strategy._active_condition_ids = set(strategy.condition_ids)
    strategy._market_epoch = None
    strategy._evaluation_heartbeat_started = False
    strategy._subscriptions_started = False
    strategy.unsubscribe_exited = host.unsubscribe_exited
    strategy._subscription_state = subs.MarketSubscriptionState()
    strategy._asset_condition_ids = _asset_conditions(
        host.registry, strategy._startup_condition_ids
    )
    strategy._last_market_data_evaluation_at: dict[str, datetime] = {}
    strategy._runtime_readiness_miss_condition_ids: set[str] = set()
    strategy._stale_orderbook_recovery_by_condition: dict[str, dict[Side, float]] = {}


def _bind_pipeline(strategy: Any) -> None:
    strategy._pipeline_state = DecisionPipelineState()
    strategy._decision_result_handler = DecisionResultHandler(
        is_signal_submitted=strategy._is_signal_submitted,
    )
    # Metrics live on order tags (Cache); no ApprovedSignalMetricsTracker.
    strategy._decision_sink = NativeDecisionSinkImpl(
        submit_order_fn=lambda approved, view: strategy._submit_approved(
            approved, view=view
        ),
        remember_metrics_fn=lambda _order, _approved: None,
        record_signal_fn=strategy._record_signal,
        notify_accepted_fn=strategy._notify_accepted_signal,
        record_decision_fn=lambda d, a: strategy._record_decision(d, accepted=a),
        record_rejected_fn=strategy._record_rejected,
        note_progress_fn=strategy._note_runtime_progress,
    )
    strategy.rejected_decisions = strategy._pipeline_state.rejected_decisions


def bind_host_runtime(strategy: Any, host: HostConstruction) -> None:
    """Assign DI fields + pipeline collaborators after super().__init__."""
    _bind_di_fields(strategy, host)
    _bind_pipeline(strategy)


def resolve_instrument_from_cache(
    token_id: str,
    *,
    instrument_id_resolver: Callable[[str], object],
    cache: object | None,
    nautilus_instrument_id: Callable[[str], object],
) -> object:
    """Resolve the complete Nautilus Instrument from Cache or fail closed."""
    resolved = instrument_id_resolver(token_id)
    if cache is None:
        if callable(getattr(resolved, "make_price", None)) and callable(
            getattr(resolved, "make_qty", None)
        ):
            return resolved
        raise ValueError("Nautilus Instrument is required when Cache is unavailable")
    key = getattr(resolved, "id", resolved)
    getter = getattr(cache, "instrument", None)
    if not callable(getter):
        raise ValueError("Nautilus Cache.instrument is required")
    try:
        cached = getter(key)
    except (LookupError, TypeError):
        cached = None
    if cached is None:
        try:
            cached = getter(nautilus_instrument_id(str(key)))
        except (LookupError, TypeError):
            cached = None
    if cached is None:
        raise ValueError(f"Nautilus Instrument is not available in Cache for token {token_id!r}")
    return cached
