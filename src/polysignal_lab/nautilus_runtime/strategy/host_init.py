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
from polysignal_lab.nautilus_runtime.strategy.config_deps import (
    dependencies_from_config,
)
from polysignal_lab.nautilus_runtime.strategy.decision_pipeline import (
    DecisionPipeline,
    NautilusCashBalanceReader,
    NautilusOrderSubmitter,
    NativeDecisionTelemetry,
    default_cash_preflight,
)

from polysignal_lab.nautilus_runtime.strategy.catalog_lookups import (
    _asset_conditions,
    catalog_instrument_id_resolver,
)
from polysignal_lab.nautilus_runtime.strategy.constants import MISSING_PROJECTIONS_ERROR
from polysignal_lab.nautilus_runtime.strategy.protocols import (
    _Assembler,
    _Observability,
    _assembler_with_custom_data,
)


@dataclass(frozen=True, slots=True)
class HostInitRequest:
    config: object | None = None
    core: AlphaCore | None = None
    assembler: _Assembler | None = None
    condition_ids: Sequence[str] = ()
    strategy_name: str = ""
    fixed_stake_usdc: float = 10.0
    sandbox_base_currency: str = "pUSD"
    orderbook_staleness_ms: float = 60_000.0
    exit_model: object | None = None
    data_names: Sequence[str] = ()
    book_type: str = "L2_MBP"
    instrument_id_resolver: Callable[[str], object] | None = None
    registry: MarketCatalog | None = None
    observability: _Observability | None = None
    progress_callback: Callable[..., None] | None = None
    readiness_callback: Callable[[str, bool, dict[str, object]], None] | None = None
    unsubscribe_exited: bool = True
    l1_book_snapshot_interval_ms: int = 0
    policy: DecisionPolicy | None = None
    market_config: MarketConfig = field(default_factory=MarketConfig)
    spot_data_source: str = "polymarket_rtds"
    runtime_log_directory: str | None = None


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
    sandbox_base_currency: str
    orderbook_staleness_ms: float
    exit_model: object | None
    data_names: tuple[str, ...]
    book_type: str
    l1_book_snapshot_interval_ms: int
    unsubscribe_exited: bool
    execution_mode: str
    observability: _Observability | None
    progress_callback: Callable[..., None] | None
    readiness_callback: Callable[[str, bool, dict[str, object]], None] | None
    market_config: MarketConfig
    spot_data_source: str
    runtime_log_directory: str | None


def _from_strategy_config(req: HostInitRequest) -> HostInitRequest:
    config = req.config
    assert isinstance(config, PolySignalStrategyConfig)
    core, assembler, registry, instrument_id_resolver = dependencies_from_config(config)
    settings = config.settings()
    resolved_policy = req.policy or decision_policy_from_settings(settings)
    # Importable LiveNode construction cannot inject callables/objects via JSON.
    # Progress/readiness default to file probes; observability resolves from the
    # process-local handle bound by the CLI before strategy construction.
    from polysignal_lab.nautilus_runtime.node_probes import (
        _runtime_progress_callback,
        _runtime_readiness_callback,
    )
    from polysignal_lab.nautilus_runtime.observability import runtime_observability

    progress_callback = req.progress_callback or _runtime_progress_callback(settings)
    readiness_callback = req.readiness_callback or _runtime_readiness_callback(settings)
    observability = req.observability or runtime_observability()
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
        sandbox_base_currency=str(settings.runtime.nautilus.sandbox_base_currency),
        exit_model=settings.trading.exit_model,
        book_type=settings.runtime.nautilus.sandbox_book_type,
        unsubscribe_exited=settings.runtime.nautilus.market_rotation.unsubscribe_exited,
        l1_book_snapshot_interval_ms=settings.runtime.nautilus.l1_book_snapshot_interval_ms,
        orderbook_staleness_ms=float(settings.data.polymarket.max_book_staleness_ms),
        data_names=req.data_names,
        observability=observability,
        progress_callback=progress_callback,
        readiness_callback=readiness_callback,
        market_config=settings.markets,
        spot_data_source=settings.runtime.nautilus.spot_data.source,
        runtime_log_directory=str(settings.logging.directory),
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
        sandbox_base_currency=work.sandbox_base_currency,
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
        runtime_log_directory=work.runtime_log_directory,
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
    strategy._runtime_log_directory = host.runtime_log_directory
    strategy._feed_resume_log_cursor = None
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
    core_config = getattr(host.core, "config", host.market_config)
    strategy._subscription_assets = frozenset(
        str(asset).upper() for asset in getattr(core_config, "assets", ())
    )
    strategy._subscription_timeframes = frozenset(
        str(timeframe).lower() for timeframe in getattr(core_config, "timeframes", ())
    )
    strategy._asset_condition_ids = _asset_conditions(
        host.registry, strategy._startup_condition_ids
    )
    strategy._last_market_data_evaluation_at: dict[str, datetime] = {}
    strategy._pending_market_data_evaluations = {}
    strategy._runtime_readiness_miss_condition_ids: set[str] = set()
    strategy._runtime_readiness_reason_by_condition = {}
    strategy._stale_orderbook_recovery_by_condition: dict[str, dict[Side, float]] = {}
    strategy._untradable_quote_sides_by_condition = {}


def _bind_pipeline(
    strategy: Any,
    *,
    account_id: str,
    base_currency: str,
) -> None:
    # Resolve the Cache lazily: at bind time the strategy has not registered with
    # its Trader yet, so the ``cache`` property is unavailable (returns None).
    # A zero-arg resolver defers the lookup until an order is actually submitted.
    balance_reader = NautilusCashBalanceReader(
        cache=lambda: getattr(strategy, "cache", None),
        account_id=account_id,
        base_currency=base_currency,
    )
    pipeline = DecisionPipeline(
        policy=strategy.policy,
        submitter=NautilusOrderSubmitter(
            strategy=strategy,
            fixed_stake_usdc=strategy.fixed_stake_usdc,
            instrument_id_resolver=strategy._resolved_instrument,
            now=strategy._framework_now,
            use_native_reduce_only=strategy._execution_mode in {"sandbox", "backtest"},
            cash_preflight=default_cash_preflight(
                balance_reader,
                base_currency,
                fixed_stake_usdc=strategy.fixed_stake_usdc,
                log_extra={
                    "strategy": strategy.strategy_name,
                    "runtime": strategy._execution_mode,
                },
            ),
        ),
        telemetry=NativeDecisionTelemetry(strategy),
    )
    strategy._decision_pipeline = pipeline
    strategy.rejected_decisions = pipeline.rejected_decisions


def _cash_account_id(host: HostConstruction) -> str:
    if host.execution_mode == "sandbox":
        return "POLYMARKET-SANDBOX-001"
    return "POLYMARKET-001"


def _cash_base_currency(host: HostConstruction) -> str:
    if host.execution_mode == "backtest":
        return "USDC"
    if host.execution_mode == "live":
        return "pUSD"
    return host.sandbox_base_currency


def bind_host_runtime(strategy: Any, host: HostConstruction) -> None:
    """Assign DI fields + pipeline collaborators after super().__init__."""
    _bind_di_fields(strategy, host)
    _bind_pipeline(
        strategy,
        account_id=_cash_account_id(host),
        base_currency=_cash_base_currency(host),
    )


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
        raise ValueError(
            f"Nautilus Instrument is not available in Cache for token {token_id!r}"
        )
    return cached
