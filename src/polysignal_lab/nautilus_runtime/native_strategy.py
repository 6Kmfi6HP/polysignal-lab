"""
Input: __future__, __future__.annotations, collections, collections.deque, collections.abc, collections.abc.Callable, collections.abc.Iterable, collections.abc.Mapping, collections.abc.Sequence, datetime
Output: PolySignalNativeStrategy
Pos: Application code

Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

from nautilus_trader.core.nautilus_pyo3 import Strategy

from polysignal_lab.alpha.types import (
    AlphaCore,
    AlphaDecision,
    AlphaFillEvent,
    AlphaOrderEvent,
    MarketView,
)
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_runtime.market_catalog import (
    MarketCatalog,
)
from polysignal_lab.nautilus_runtime.market_view_assembler import BookReceiptObserver
from polysignal_lab.nautilus_runtime.state import load_strategy_state, save_strategy_state
from polysignal_lab.nautilus_runtime.decision_policy import (
    ApprovedDecision,
    RejectedDecision,
)
from polysignal_lab.nautilus_runtime.decision_messages import (
    DecisionCandidateData,
    DecisionResultData,
)
from polysignal_lab.nautilus_runtime.runtime_configs import PolySignalStrategyConfig
from polysignal_lab.nautilus_runtime.cache_trading_state import (
    cache_has_active_order_dedupe_key,
    trading_state_from_cache,
)
from polysignal_lab.nautilus_runtime.custom_data_state import StrategyCustomDataState
from polysignal_lab.nautilus_runtime.custom_data_types import (
    PolySignalMarketMetaData,
    PolySignalMarketUniverseData,
    PolySignalPriceToBeatData,
    PolySignalSpotData,
    custom_data_type,
    unwrap_custom_data,
    wrap_custom_data,
)
from polysignal_lab.nautilus_runtime.native_order import (
    OrderSubmittingStrategy,
)
from polysignal_lab.nautilus_runtime.native_strategy_exit import (
    NativeExitPolicy,
)
from polysignal_lab.nautilus_runtime.custom_data_publisher import timestamp_ns
from polysignal_lab.nautilus_runtime.strategy.custom_data_handlers import route_strategy_data
from polysignal_lab.nautilus_runtime.strategy.decision_pipeline import (
    DecisionPipelineState,
    DecisionResultHandler,
    NativeDecisionSinkImpl,
    submit_approved_for_view,
)
from polysignal_lab.nautilus_runtime.strategy.event_projection import (
    ApprovedSignalMetricsTracker,
)
from polysignal_lab.nautilus_runtime.strategy.observability_hooks import (
    notify_accepted_signal as _notify_accepted_signal_hook,
    record_decision as _record_decision_hook,
    record_nautilus_fill as _record_nautilus_fill_hook,
    record_nautilus_order as _record_nautilus_order_hook,
    record_nautilus_position as _record_nautilus_position_hook,
    record_observability as _record_observability_hook,
    record_rejected as _record_rejected_hook,
    record_signal as _record_signal_hook,
)
from polysignal_lab.nautilus_runtime.strategy.order_events import (
    call_core as _call_core_hook,
    forget_approved_metrics as _forget_approved_metrics_hook,
    handle_order_filled as _handle_order_filled,
    handle_order_lifecycle_event as _handle_order_lifecycle_event,
    handle_position_closed as _handle_position_closed,
    handle_position_event as _handle_position_event,
    project_strategy_fill_event as _project_strategy_fill_event,
    project_strategy_order_event as _project_strategy_order_event,
    should_notify_fill as _should_notify_fill_hook,
)
from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
    InstrumentSubscriptionManager,
    MarketSubscriptionState,
    clear_condition_subscription_state as _clear_condition_subscription_state_fn,
    condition_instruments as _condition_instruments_fn,
    market_book_generation_ready as _market_book_generation_ready_fn,
    observe_market_book_side as _observe_market_book_side_fn,
    refresh_asset_conditions as _refresh_asset_conditions_fn,
    retire_market_book_generation as _retire_market_book_generation_fn,
    retry_market_instrument_requests as _retry_market_instrument_requests_fn,
    subscribe_market_conditions as _subscribe_market_conditions_fn,
    subscribe_market_instrument as _subscribe_market_instrument_fn,
    unsubscribe_market_conditions as _unsubscribe_market_conditions_fn,
    unsubscribe_market_instrument as _unsubscribe_market_instrument_fn,
)
from polysignal_lab.nautilus_runtime.strategy.helpers import (
    DEFAULT_L1_BOOK_SNAPSHOT_INTERVAL_MS,
    DEFAULT_NATIVE_DATA_NAMES,
    EVALUATION_HEARTBEAT_INTERVAL,
    EVALUATION_HEARTBEAT_TIMER_NAME,
    MISSING_PROJECTIONS_ERROR,
    _Assembler,
    _Observability,
    _asset_conditions,
    _assembler_with_custom_data,
    _condition_id_from_catalog_instrument,
    _identifier_text,
    _token_id_from_catalog_instrument,
    event_datetime,
    _identity_instrument_id,
    _market_view_ready,
    _nautilus_instrument_id,
    _spot_data_client_id,
    _subscribe_custom_data,
    classify_project_owned_data,
)


def _dependencies_from_config(
    config: PolySignalStrategyConfig,
) -> tuple[AlphaCore, _Assembler, MarketCatalog, Callable[[str], object]]:
    from polysignal_lab.nautilus_runtime.composite_alpha import CompositeAlphaCore
    from polysignal_lab.nautilus_runtime.node_builder_components import (
        create_market_projection_components,
    )
    from polysignal_lab.nautilus_runtime.strategy_builder import _native_core_for

    settings = config.settings()
    registry, assembler = create_market_projection_components(config.markets())
    cores: dict[str, AlphaCore] = {}
    for name in settings.strategies.explicit_strategy_names():
        strategy_config = getattr(settings.strategies, name, None)
        if strategy_config is None or not bool(getattr(strategy_config, "enabled", False)):
            continue
        core = _native_core_for(name, strategy_config)
        if core is not None:
            cores[name] = core
    if not cores:
        raise RuntimeError("PolySignalStrategyConfig enables no native alpha cores")

    def resolve(token_id: str) -> object:
        instrument_id = registry.instrument_id_for_token(token_id)
        if instrument_id is None:
            raise ValueError(f"unknown Polymarket token_id {token_id!r}")
        return instrument_id

    return CompositeAlphaCore(cores), cast(_Assembler, assembler), registry, resolve

class PolySignalNativeStrategy(Strategy):
    """Nautilus callback-shaped strategy wrapper around a PolySignal alpha core."""

    def __new__(cls, *args: object, **kwargs: object):
        # PyO3 Strategy.__new__ rejects business kwargs; defer all work to __init__.
        return super().__new__(cls)

    def __init__(
        self,
        config: object | None = None,
        *,
        core: AlphaCore | None = None,
        assembler: _Assembler | None = None,
        condition_ids: Sequence[str] = (),
        strategy_name: str = "",
        fixed_stake_usdc: float = 10.0,
        orderbook_staleness_ms: float = 60_000.0,
        exit_model: object | None = None,
        data_names: Sequence[str] = DEFAULT_NATIVE_DATA_NAMES,
        book_type: str = "L2_MBP",
        instrument_id_resolver: Callable[[str], object] | None = None,
        registry: MarketCatalog | None = None,
        observability: _Observability | None = None,
        progress_callback: Callable[[str], None] | None = None,
        readiness_callback: Callable[[str, bool, dict[str, object]], None] | None = None,
        unsubscribe_exited: bool = True,
        l1_book_snapshot_interval_ms: int = DEFAULT_L1_BOOK_SNAPSHOT_INTERVAL_MS,
        spot_data_client_id: object | None = None,
    ) -> None:
        from nautilus_trader.core.nautilus_pyo3 import StrategyConfig, StrategyId

        execution_mode = "sandbox"
        if isinstance(config, PolySignalStrategyConfig) and core is None:
            (
                core,
                assembler,
                registry,
                instrument_id_resolver,
            ) = _dependencies_from_config(config)
            settings = config.settings()
            execution_mode = settings.runtime.nautilus.execution_mode
            condition_ids = tuple(config.condition_ids)
            strategy_name = config.strategy_name
            fixed_stake_usdc = float(settings.trading.fixed_stake_usdc)
            exit_model = settings.trading.exit_model
            book_type = settings.runtime.nautilus.sandbox_book_type
            unsubscribe_exited = settings.runtime.nautilus.market_rotation.unsubscribe_exited
            l1_book_snapshot_interval_ms = settings.runtime.nautilus.l1_book_snapshot_interval_ms
            orderbook_staleness_ms = float(
                settings.data.polymarket.max_book_staleness_ms
            )
            if (
                settings.runtime.nautilus.execution_mode != "backtest"
                and settings.runtime.nautilus.spot_data.source != "disabled"
            ):
                spot_data_client_id = _spot_data_client_id()
            config = StrategyConfig(
                strategy_id=StrategyId(str(config.strategy_id)),
                order_id_tag=str(config.order_id_tag),
            )
        else:
            config = StrategyConfig(
                strategy_id=StrategyId(f"PolySignal-{strategy_name}"),
                order_id_tag=strategy_name,
            )
        if not strategy_name:
            raise RuntimeError("PolySignalNativeStrategy requires strategy_name")
        if core is None:
            raise RuntimeError("PolySignalNativeStrategy requires core")
        super().__init__(config=config)
        self._execution_mode = execution_mode
        if registry is None or assembler is None:
            raise RuntimeError(MISSING_PROJECTIONS_ERROR)
        self._configure_dependencies(core, assembler, condition_ids, strategy_name, registry)
        self._configure_runtime_options(
            fixed_stake_usdc=fixed_stake_usdc,
            exit_model=exit_model,
            data_names=data_names,
            book_type=book_type,
            instrument_id_resolver=instrument_id_resolver,
            observability=observability,
            progress_callback=progress_callback,
            readiness_callback=readiness_callback,
            l1_book_snapshot_interval_ms=l1_book_snapshot_interval_ms,
            orderbook_staleness_ms=orderbook_staleness_ms,
            spot_data_client_id=spot_data_client_id,
        )
        self._initialize_runtime_state(registry, unsubscribe_exited=unsubscribe_exited)

    def _configure_dependencies(
        self,
        core: AlphaCore,
        assembler: _Assembler,
        condition_ids: Sequence[str],
        strategy_name: str,
        registry: MarketCatalog,
    ) -> None:
        self.core = core
        self.custom_data = StrategyCustomDataState()
        resolved_assembler = _assembler_with_custom_data(assembler, self.custom_data)
        if resolved_assembler is None:
            raise RuntimeError(MISSING_PROJECTIONS_ERROR)
        self.assembler = resolved_assembler
        self.condition_ids = tuple(condition_ids)
        self.strategy_name = strategy_name
        self.registry = registry
        self._pending_policy_requests: dict[str, tuple[AlphaDecision, MarketView]] = {}
        self._decision_batch_sequence = 0

    def _configure_runtime_options(
        self,
        *,
        fixed_stake_usdc: float,
        exit_model: object | None,
        data_names: Sequence[str],
        book_type: str,
        instrument_id_resolver: Callable[[str], object] | None,
        observability: _Observability | None,
        progress_callback: Callable[[str], None] | None,
        readiness_callback: Callable[[str, bool, dict[str, object]], None] | None,
        l1_book_snapshot_interval_ms: int,
        orderbook_staleness_ms: float,
        spot_data_client_id: object | None,
    ) -> None:
        self.fixed_stake_usdc = fixed_stake_usdc
        self.exit_policy = NativeExitPolicy.from_config(exit_model)
        self.data_names = tuple(data_names)
        self.book_type = book_type
        self.l1_book_snapshot_interval_ms = int(l1_book_snapshot_interval_ms)
        self.instrument_id_resolver = instrument_id_resolver or _identity_instrument_id
        self.observability = observability
        self.progress_callback = progress_callback
        self.readiness_callback = readiness_callback
        self.orderbook_staleness_ms = float(orderbook_staleness_ms)
        self.spot_data_client_id = spot_data_client_id

    def _initialize_runtime_state(
        self,
        registry: MarketCatalog,
        *,
        unsubscribe_exited: bool,
    ) -> None:
        self._init_condition_state(registry, unsubscribe_exited=unsubscribe_exited)
        self._init_decision_pipeline()
        self._init_subscriptions(registry)
        self._init_runtime_queues()

    def _init_condition_state(
        self,
        registry: MarketCatalog,
        *,
        unsubscribe_exited: bool,
    ) -> None:
        self._startup_condition_ids: tuple[str, ...] = self.condition_ids
        self._active_condition_ids: set[str] = set(self.condition_ids)
        self._market_epoch: int | None = None
        self.unsubscribe_exited: bool = unsubscribe_exited
        self._subscription_state: MarketSubscriptionState = MarketSubscriptionState()
        self._asset_condition_ids: dict[str, tuple[str, ...]] = _asset_conditions(
            registry,
            self._startup_condition_ids,
        )
        self._last_market_data_evaluation_at: dict[str, datetime] = {}
        self._runtime_readiness_miss_condition_ids: set[str] = set()
        self._stale_orderbook_recovery_by_condition: dict[
            str,
            dict[Side, float],
        ] = {}

    def _init_decision_pipeline(self) -> None:
        self._pipeline_state = DecisionPipelineState()
        self._decision_result_handler = DecisionResultHandler(
            is_signal_submitted=self._is_signal_submitted,
        )
        self._metrics_tracker = ApprovedSignalMetricsTracker()
        self._decision_sink = NativeDecisionSinkImpl(
            submit_order_fn=lambda approved, view: self._submit_approved(approved, view=view),
            remember_metrics_fn=self._metrics_tracker.remember,
            record_signal_fn=self._record_signal,
            notify_accepted_fn=self._notify_accepted_signal,
            record_decision_fn=lambda decision, accepted: self._record_decision(
                decision, accepted=accepted
            ),
            record_rejected_fn=self._record_rejected,
            note_progress_fn=self._note_runtime_progress,
        )
        self._subscription_manager = InstrumentSubscriptionManager(self)
        self.rejected_decisions = self._pipeline_state.rejected_decisions

    def _is_signal_submitted(self, dedupe_key: str) -> bool:
        try:
            cache = self.cache
        except (AttributeError, RuntimeError):
            cache = None
        return cache_has_active_order_dedupe_key(
            cache,
            strategy_id=getattr(self, "strategy_id", None)
            or getattr(self, "id", None),
            dedupe_key=dedupe_key,
        )

    def _init_subscriptions(self, registry: MarketCatalog) -> None:
        self._refresh_asset_conditions()

    def _init_runtime_queues(self) -> None:
        return None

    def _require_registry(self) -> MarketCatalog | None:
        if self.registry is None:
            raise RuntimeError(MISSING_PROJECTIONS_ERROR)
        return self.registry


    def _require_assembler(self) -> _Assembler:
        return self.assembler

    def _note_runtime_progress(self, phase: str) -> None:
        callback = self.progress_callback
        if callback is None:
            return
        callback(phase)

    def _note_runtime_readiness(self, condition_id: str, *, ready: bool) -> None:
        if ready:
            _ = self._runtime_readiness_miss_condition_ids.discard(condition_id)
            _ = self._stale_orderbook_recovery_by_condition.pop(condition_id, None)
        else:
            self._runtime_readiness_miss_condition_ids.add(condition_id)
        condition_ready = ready
        callback = self.readiness_callback
        if callback is None:
            return
        now = self._framework_now()
        detail = self._readiness_detail(condition_id, now=now)
        callback(condition_id, condition_ready, detail)

    def _book_readiness_detail(
        self,
        condition_id: str,
        *,
        now: datetime,
    ) -> tuple[
        dict[str, str | None],
        dict[str, str | None],
        dict[str, int | None],
        int | None,
    ]:
        state = self._subscription_state
        last_books = state.last_book_at_by_condition.get(condition_id, {})
        last_receipts = state.last_book_received_at_by_condition.get(condition_id, {})
        last_book_at_by_side: dict[str, str | None] = {}
        last_received_at_by_side: dict[str, str | None] = {}
        freshness_ms_by_side: dict[str, int | None] = {}
        for side in (Side.UP, Side.DOWN):
            book_at = last_books.get(side)
            received_at = last_receipts.get(side)
            last_book_at_by_side[side.value] = (
                None if book_at is None else book_at.isoformat()
            )
            last_received_at_by_side[side.value] = (
                None if received_at is None else received_at.isoformat()
            )
            freshness_ms_by_side[side.value] = (
                None
                if received_at is None
                else max(0, int((now - received_at).total_seconds() * 1000))
            )
        freshness_values = [
            value for value in freshness_ms_by_side.values() if value is not None
        ]
        return (
            last_book_at_by_side,
            last_received_at_by_side,
            freshness_ms_by_side,
            max(freshness_values) if freshness_values else None,
        )

    def _subscription_readiness_state(
        self,
        condition_id: str,
        *,
        preloaded: bool,
        pending_sides: set[Side],
    ) -> str:
        state = self._subscription_state
        if preloaded:
            return "preloaded"
        if condition_id in state.pending_metadata_condition_ids:
            return "pending_metadata"
        if condition_id in self._stale_orderbook_recovery_by_condition:
            return "stale_orderbook"
        if pending_sides:
            return "awaiting_first_book"
        if condition_id in state.wire_condition_ids:
            return "subscribed"
        return "unsubscribed"

    def _readiness_detail(
        self,
        condition_id: str,
        *,
        now: datetime,
    ) -> dict[str, object]:
        state = self._subscription_state
        registry = self._require_registry()
        pair = None if registry is None else registry.by_condition(condition_id)
        pending_sides = state.awaiting_book_sides_by_condition.get(condition_id, set())
        (
            last_books,
            last_receipts,
            freshness_by_side,
            max_freshness_ms,
        ) = self._book_readiness_detail(condition_id, now=now)
        subscription_state = self._subscription_readiness_state(
            condition_id,
            preloaded=bool(
                pair is not None
                and pair.start_ts is not None
                and now < pair.start_ts
            ),
            pending_sides=pending_sides,
        )
        generation_started_at = state.book_generation_started_at_by_condition.get(
            condition_id
        )
        return {
            "condition_id": condition_id,
            "market_id": None if pair is None else pair.market_id,
            "asset": None if pair is None else pair.asset,
            "timeframe": None if pair is None else pair.timeframe,
            "subscription_state": subscription_state,
            "wire_subscribed": condition_id in state.wire_condition_ids,
            "generation_started_at": (
                None
                if generation_started_at is None
                else generation_started_at.isoformat()
            ),
            "awaiting_book_sides": sorted(side.value for side in pending_sides),
            "last_book_at_by_side": last_books,
            "last_book_received_at_by_side": last_receipts,
            "freshness_ms_by_side": freshness_by_side,
            "max_freshness_ms": max_freshness_ms,
        }


    def _stale_orderbook_recovered(
        self,
        condition_id: str,
        view: MarketView,
    ) -> bool:
        recovery = self._stale_orderbook_recovery_by_condition.get(condition_id)
        if recovery is None:
            return True
        return all(
            (freshness_ms := view.book_for(side).freshness_ms) is not None
            and freshness_ms <= threshold_ms
            for side, threshold_ms in recovery.items()
        )

    def _orderbook_readiness_threshold_ms(self) -> float:
        return self.orderbook_staleness_ms

    def _orderbook_trade_threshold_ms(self) -> float:
        return self.orderbook_staleness_ms

    def _stale_orderbook_sides(
        self,
        view: MarketView,
        *,
        threshold_ms: float,
    ) -> dict[Side, float] | None:
        stale_sides: dict[Side, float] | None = None
        for side in (Side.UP, Side.DOWN):
            freshness_ms = view.book_for(side).freshness_ms
            if freshness_ms is not None and freshness_ms <= threshold_ms:
                continue
            if stale_sides is None:
                stale_sides = {}
            stale_sides[side] = threshold_ms
        return stale_sides


    def _framework_now(self) -> datetime:
        try:
            timestamp_ns = getattr(self.clock, "timestamp_ns", None)
            if callable(timestamp_ns):
                value = int(timestamp_ns())
                if value >= 0:
                    return datetime.fromtimestamp(value / 1_000_000_000, UTC)
        except (NotImplementedError, RuntimeError, AttributeError):
            pass
        if getattr(self, "trader_id", None) is None:
            return datetime(1970, 1, 1, tzinfo=UTC)
        raise RuntimeError("Nautilus framework clock timestamp_ns is unavailable")

    def _start_evaluation_heartbeat(self) -> None:
        if self._execution_mode == "backtest":
            return
        try:
            clock = self.clock
            _ = clock.set_timer(
                EVALUATION_HEARTBEAT_TIMER_NAME,
                EVALUATION_HEARTBEAT_INTERVAL,
                callback=self._on_evaluation_heartbeat,
            )
        except (NotImplementedError, RuntimeError):
            if getattr(self, "trader_id", None) is not None:
                raise

    def on_stop(self) -> None:
        if self._execution_mode == "backtest":
            return
        try:
            _ = self.clock.cancel_timer(EVALUATION_HEARTBEAT_TIMER_NAME)
        except (NotImplementedError, RuntimeError):
            if getattr(self, "trader_id", None) is not None:
                raise

    @property
    def cache(self) -> object | None:
        cache_override = getattr(self, "_cache_override", None)
        if cache_override is not None:
            return cache_override
        if getattr(self, "trader_id", None) is None:
            return None
        return super().cache

    @cache.setter
    def cache(self, value: object) -> None:
        self._cache_override = value

    @property
    def order_factory(self) -> object | None:
        order_factory_override = getattr(self, "_order_factory_override", None)
        if order_factory_override is not None:
            return order_factory_override
        if getattr(self, "trader_id", None) is None:
            return None
        return super().order_factory

    @order_factory.setter
    def order_factory(self, value: object) -> None:
        self._order_factory_override = value

    def on_start(self) -> None:
        self._note_runtime_progress("start")
        _ = self._require_registry()
        _ = self._require_assembler()
        books = getattr(self.assembler, "books", None)
        bind_cache = getattr(books, "bind_cache", None)
        if callable(bind_cache) and not bool(getattr(books, "is_bound", False)):
            bind_cache(self.cache)
        _subscribe_custom_data(self, DecisionResultData)
        self._subscribe_market_conditions(self._startup_condition_ids)
        _subscribe_custom_data(
            self,
            PolySignalSpotData,
            client_id=self.spot_data_client_id,
        )
        _subscribe_custom_data(
            self,
            PolySignalPriceToBeatData,
        )
        _subscribe_custom_data(
            self,
            PolySignalMarketMetaData,
        )
        _subscribe_custom_data(
            self,
            PolySignalMarketUniverseData,
        )
        self._start_evaluation_heartbeat()

    def on_save(self) -> dict[str, bytes]:
        return save_strategy_state(self.strategy_name, self.core)

    def on_load(self, state: Mapping[str, bytes]) -> None:
        load_strategy_state(self.strategy_name, self.core, state)
        # Accept Actor universe/PTB replay after reload (epoch gate would skip it).
        self._market_epoch = None

    def _on_evaluation_heartbeat(self, _event: object) -> None:
        self._note_runtime_progress("evaluation_heartbeat")
        now = self._framework_now()
        active_condition_ids = tuple(sorted(self._active_condition_ids))
        for condition_id in active_condition_ids:
            if self._retire_expired_condition(condition_id, now=now):
                continue
            last_market_data_eval = self._last_market_data_evaluation_at.get(condition_id)
            if (
                last_market_data_eval is not None
                and now - last_market_data_eval < EVALUATION_HEARTBEAT_INTERVAL
            ):
                continue
            self.evaluate_condition(condition_id)

    def on_data(self, data: object) -> None:
        payload = unwrap_custom_data(data)
        if isinstance(payload, DecisionResultData):
            self._handle_policy_result(payload)
            return
        route_strategy_data(
            self,
            payload,
            classify=classify_project_owned_data,
        )

    def _handle_policy_result(self, result: DecisionResultData) -> None:
        pending = self._pending_policy_requests.pop(result.request_id, None)
        if pending is None:
            return
        decision, view = pending
        policy_result: ApprovedDecision | RejectedDecision
        signal_candidate = result.signal()
        if result.approved and signal_candidate is not None:
            policy_result = ApprovedDecision(signal=signal_candidate)
        else:
            policy_result = RejectedDecision(
                reason_code=result.reason_code,
                detail=result.detail(),
            )
        self._decision_result_handler.handle_result(
            policy_result,
            decision,
            view,
            state=self._pipeline_state,
            sink=self._decision_sink,
        )

    def _condition_from_market_data(self, data: object) -> str | None:
        if self.registry is None:
            return None
        instrument_id = _identifier_text(getattr(data, "instrument_id", None))
        if instrument_id is None:
            return None
        condition_id = _condition_id_from_catalog_instrument(
            self.registry,
            tuple(self._active_condition_ids),
            instrument_id,
        )
        if condition_id is None:
            self._note_runtime_progress("dropped_frame")
        return condition_id

    def on_quote_tick(self, tick: object) -> None:
        # Polymarket quote ticks are emitted from the same snapshots/deltas
        # that maintain the adapter's order book, including unchanged snapshots.
        self._evaluate_order_book_event(tick)

    def on_quote(self, tick: object) -> None:
        self.on_quote_tick(tick)

    def on_order_book(self, book: object) -> None:
        self._evaluate_order_book_event(book)

    def on_book(self, book: object) -> None:
        self.on_order_book(book)

    def on_trade_tick(self, tick: object) -> None:
        condition_id = self._condition_from_market_data(tick)
        if condition_id is None:
            return
        self._evaluate_market_data_condition(condition_id, event=tick)

    def on_trade(self, tick: object) -> None:
        self.on_trade_tick(tick)

    def on_order_book_deltas(self, deltas: object) -> None:
        self._evaluate_order_book_event(deltas)

    def on_book_deltas(self, deltas: object) -> None:
        self.on_order_book_deltas(deltas)

    def _order_book_observation(
        self,
        event: object,
        condition_id: str,
        registry: MarketCatalog,
    ) -> tuple[datetime, Side, datetime, datetime] | None:
        instrument_id = _identifier_text(getattr(event, "instrument_id", None))
        if instrument_id is None:
            return None
        token_id = _token_id_from_catalog_instrument(
            registry,
            condition_id,
            instrument_id,
        )
        if token_id is None:
            return None
        token = registry.token_meta(token_id)
        if token is None:
            return None
        now = self._framework_now()
        try:
            received_at, book_at = self._order_book_event_times(
                event,
                received_at=now,
            )
        except ValueError:
            return None
        assembler = self._require_assembler()
        if isinstance(assembler, BookReceiptObserver):
            assembler.observe_book_received(token_id, received_at=received_at)
        return now, token.side, received_at, book_at

    def _evaluate_order_book_event(self, event: object) -> None:
        condition_id = self._condition_from_market_data(event)
        if condition_id is None:
            return
        registry = self._require_registry()
        observation = (
            None
            if registry is None
            else self._order_book_observation(event, condition_id, registry)
        )
        if observation is None or registry is None:
            self._note_runtime_progress("dropped_frame")
            return
        now, side, received_at, book_at = observation
        generation_ready = _observe_market_book_side_fn(
            self,
            condition_id,
            side,
            received_at=received_at,
            book_at=book_at,
        )
        pair = registry.by_condition(condition_id)
        if pair is not None and pair.start_ts is not None and now < pair.start_ts:
            if condition_id in self._runtime_readiness_miss_condition_ids:
                self._note_runtime_readiness(condition_id, ready=True)
            return
        if generation_ready:
            self._evaluate_market_data_condition(condition_id, event=event)
            return
        self._note_runtime_progress("market_data_evaluation")
        self._last_market_data_evaluation_at[condition_id] = now
        self._note_runtime_progress("readiness_miss")
        self._note_runtime_readiness(condition_id, ready=False)
    @staticmethod
    def _order_book_event_times(
        event: object,
        *,
        received_at: datetime,
    ) -> tuple[datetime, datetime]:
        raw_received_at = getattr(event, "ts_init", None)
        observed_received_at = (
            received_at
            if raw_received_at is None
            else event_datetime(raw_received_at)
        )
        raw_book_at = getattr(event, "ts_event", None)
        if raw_book_at is None:
            raw_book_at = getattr(event, "ts_last", None)
        observed_book_at = (
            observed_received_at
            if raw_book_at is None
            else event_datetime(raw_book_at)
        )
        return observed_received_at, observed_book_at


    def _evaluate_market_data_condition(
        self,
        condition_id: str,
        *,
        event: object | None = None,
    ) -> None:
        _ = event
        self._note_runtime_progress("market_data_evaluation")
        now = self._framework_now()
        self._last_market_data_evaluation_at[condition_id] = now
        self.evaluate_condition(condition_id)

    def on_order_submitted(self, event: object) -> None:
        _handle_order_lifecycle_event(self, "on_order_submitted", event)

    def on_order_accepted(self, event: object) -> None:
        _handle_order_lifecycle_event(self, "on_order_accepted", event)

    def on_order_rejected(self, event: object) -> None:
        _handle_order_lifecycle_event(
            self, "on_order_rejected", event, forget_metrics=True
        )

    def on_order_canceled(self, event: object) -> None:
        _handle_order_lifecycle_event(
            self, "on_order_canceled", event, forget_metrics=True
        )

    def on_order_expired(self, event: object) -> None:
        _handle_order_lifecycle_event(
            self, "on_order_expired", event, forget_metrics=True
        )

    def on_order_filled(self, event: object) -> None:
        _handle_order_filled(self, event)

    def on_position_opened(self, position: object) -> None:
        _handle_position_event(self, position)

    def on_position_changed(self, position: object) -> None:
        _handle_position_event(self, position)

    def on_position_closed(self, position: object) -> None:
        _handle_position_closed(self, position)

    def _skip_preloaded_condition(
        self,
        condition_id: str,
        *,
        now: datetime,
    ) -> bool:
        registry = self._require_registry()
        pair = None if registry is None else registry.by_condition(condition_id)
        if pair is None or pair.start_ts is None or now >= pair.start_ts:
            return False
        if condition_id in self._runtime_readiness_miss_condition_ids:
            self._note_runtime_readiness(condition_id, ready=True)
        return True

    def _retire_expired_condition(
        self,
        condition_id: str,
        *,
        now: datetime,
    ) -> bool:
        registry = self._require_registry()
        pair = None if registry is None else registry.by_condition(condition_id)
        end_ts = None if pair is None else getattr(pair, "end_ts", None)
        if end_ts is None or now < end_ts:
            return False
        self._active_condition_ids.discard(condition_id)
        self._subscription_state.pending_metadata_condition_ids.discard(condition_id)
        _retire_market_book_generation_fn(self, condition_id)
        if self.unsubscribe_exited:
            self._unsubscribe_market_conditions((condition_id,))
        self._refresh_asset_conditions()
        self._note_runtime_readiness(condition_id, ready=True)
        return True

    def _mark_condition_unready(
        self,
        condition_id: str,
    ) -> None:
        self._note_runtime_progress("readiness_miss")
        self._note_runtime_readiness(condition_id, ready=False)

    def evaluate_condition(
        self,
        condition_id: str,
        *,
        created_at: datetime | None = None,
    ) -> None:
        if condition_id not in self._active_condition_ids:
            return
        now = created_at or self._framework_now()
        if self._retire_expired_condition(condition_id, now=now):
            return
        if self._skip_preloaded_condition(condition_id, now=now):
            return
        if not _market_book_generation_ready_fn(self, condition_id):
            self._mark_condition_unready(condition_id)
            return
        view = self._require_assembler().build(condition_id, created_at=now)
        if view is None or not _market_view_ready(view):
            self._mark_condition_unready(condition_id)
            return
        market_view = cast(MarketView, view)
        if isinstance(view, MarketView):
            market_view = replace(
                view,
                trading=trading_state_from_cache(
                    self.cache,
                    strategy_id=getattr(self, "strategy_id", None)
                    or getattr(self, "id", None),
                    registry=self._require_registry(),
                    condition_id=market_view.condition_id,
                ),
            )
        stale_sides = self._stale_orderbook_sides(
            market_view,
            threshold_ms=self._orderbook_readiness_threshold_ms(),
        )
        if stale_sides is not None:
            self._stale_orderbook_recovery_by_condition[condition_id] = stale_sides
            self._mark_condition_unready(condition_id)
            return
        self._evaluate_ready_condition(
            condition_id,
            market_view,
            now=now,
        )

    def _evaluate_ready_condition(
        self,
        condition_id: str,
        market_view: MarketView,
        *,
        now: datetime,
    ) -> None:
        readiness_confirmed = False
        if condition_id in self._stale_orderbook_recovery_by_condition:
            if not self._stale_orderbook_recovered(condition_id, market_view):
                self._note_runtime_progress("readiness_miss")
                self._note_runtime_readiness(condition_id, ready=False)
                return
            self._note_runtime_readiness(condition_id, ready=True)
            readiness_confirmed = True
        elif condition_id in self._runtime_readiness_miss_condition_ids:
            self._note_runtime_readiness(condition_id, ready=True)
            readiness_confirmed = True
        evaluate_core = self._stale_orderbook_sides(
            market_view,
            threshold_ms=self._orderbook_trade_threshold_ms(),
        ) is None
        decisions = self._evaluate_decisions(
            market_view,
            now=now,
            evaluate_core=evaluate_core,
        )
        self._publish_decision_batch(decisions, market_view)
        if (
            not readiness_confirmed
            and condition_id not in self._runtime_readiness_miss_condition_ids
        ):
            self._note_runtime_readiness(condition_id, ready=True)

    def _publish_decision_batch(
        self,
        decisions: Sequence[AlphaDecision],
        view: MarketView,
    ) -> None:
        if not decisions:
            return
        self._decision_batch_sequence += 1
        batch_id = f"{self.strategy_name}:{self._decision_batch_sequence}"
        batch_size = len(decisions)
        ts_event = timestamp_ns(self._framework_now())
        for index, decision in enumerate(decisions):
            request_id = f"{batch_id}:{index}"
            self._pending_policy_requests[request_id] = (decision, view)
            message = DecisionCandidateData.from_domain(
                request_id=request_id,
                batch_id=batch_id,
                batch_index=index,
                batch_size=batch_size,
                decision=decision,
                view=view,
                ts_event=ts_event,
                ts_init=ts_event,
            )
            self.publish_data(
                custom_data_type(DecisionCandidateData),
                wrap_custom_data(message),
            )

    def _evaluate_decisions(
        self,
        market_view: MarketView,
        *,
        now: datetime,
        evaluate_core: bool = True,
    ) -> tuple[AlphaDecision, ...]:
        if self.exit_policy is None:
            return tuple(self.core.evaluate(market_view)) if evaluate_core else ()
        try:
            cache = self.cache
        except (AttributeError, RuntimeError):
            cache = None
        try:
            decisions = self.exit_policy.decisions(
                cache=cache,
                strategy_id=getattr(self, "strategy_id", None)
                or getattr(self, "id", None),
                registry=self._require_registry(),
                view=market_view,
                now=now,
            )
        except (TypeError, ValueError, RuntimeError):
            self._note_runtime_progress("native_exit_failed")
            return tuple(self.core.evaluate(market_view)) if evaluate_core else ()
        if decisions:
            self._note_runtime_progress("native_exit")
            return decisions
        return tuple(self.core.evaluate(market_view)) if evaluate_core else ()

    def _handle_decision(self, decision: AlphaDecision, view: MarketView) -> None:
        self._publish_decision_batch((decision,), view)

    def _submit_approved(
        self, approved: ApprovedDecision, *, view: MarketView
    ) -> object:
        return submit_approved_for_view(
            cast(OrderSubmittingStrategy[object], cast(object, self)),
            approved,
            view=view,
            fixed_stake_usdc=self.fixed_stake_usdc,
            instrument_id_resolver=self._resolved_instrument,
            now=self._framework_now,
        )

    def _resolved_instrument(self, token_id: str) -> object:
        resolved = self.instrument_id_resolver(token_id)
        cache = getattr(self, "cache", None)
        if cache is not None:
            instrument_key = getattr(resolved, "id", resolved)
            instrument_getter = getattr(cache, "instrument", None)
            if not callable(instrument_getter):
                return resolved
            try:
                cached = instrument_getter(instrument_key)
            except (LookupError, TypeError):
                cached = None
            if cached is None:
                try:
                    cached = instrument_getter(_nautilus_instrument_id(str(instrument_key)))
                except (LookupError, TypeError):
                    cached = None
            if cached is not None:
                return cached
        return resolved

    def _token_id_from_view_instrument(self, view: MarketView, instrument_id: str) -> str | None:
        up_instrument = str(self._resolved_instrument(view.up.token_id))
        if instrument_id == up_instrument:
            return view.up.token_id
        down_instrument = str(self._resolved_instrument(view.down.token_id))
        if instrument_id == down_instrument:
            return view.down.token_id
        return None

    def _call_core(self, method_name: str, event: AlphaOrderEvent) -> None:
        _call_core_hook(self, method_name, event)

    def _record_signal(self, signal: SignalCandidate) -> None:
        _record_signal_hook(self, signal)

    def _notify_accepted_signal(self, signal: SignalCandidate) -> None:
        _notify_accepted_signal_hook(self, signal)

    def _record_decision(self, decision: AlphaDecision, *, accepted: bool) -> None:
        _record_decision_hook(self, decision, accepted=accepted)

    def _record_rejected(self, rejected: object) -> None:
        _record_rejected_hook(self, rejected)

    def _record_nautilus_order(
        self, event: object, metrics: Mapping[str, object]
    ) -> None:
        _record_nautilus_order_hook(self, event, metrics)

    def _record_observability(self, action: Callable[[_Observability], None]) -> None:
        _record_observability_hook(self, action)

    def _record_nautilus_fill(
        self, event: object, metrics: Mapping[str, object]
    ) -> None:
        _record_nautilus_fill_hook(self, event, metrics)

    def _record_nautilus_position(self, position: object) -> None:
        _record_nautilus_position_hook(self, position)

    def _order_event(self, event: object) -> AlphaOrderEvent:
        return _project_strategy_order_event(self, event)

    def _fill_event(self, event: object) -> AlphaFillEvent:
        return _project_strategy_fill_event(self, event)

    def _should_notify_fill(self, event: AlphaFillEvent) -> bool:
        return _should_notify_fill_hook(self, event)

    def _forget_approved_metrics(self, event: object, order: AlphaOrderEvent) -> None:
        _forget_approved_metrics_hook(self, event, order)

    def _refresh_asset_conditions(self) -> None:
        _refresh_asset_conditions_fn(self)

    def _retry_market_instrument_requests(
        self,
        condition_ids: Sequence[str],
    ) -> None:
        _retry_market_instrument_requests_fn(self, condition_ids)

    def _subscribe_market_conditions(self, condition_ids: Sequence[str]) -> None:
        _subscribe_market_conditions_fn(
            self,
            condition_ids,
            now=self._framework_now(),
        )

    def _subscribe_market_instrument(self, instrument_id: object) -> bool:
        return _subscribe_market_instrument_fn(self, instrument_id)

    def _unsubscribe_market_conditions(self, condition_ids: Sequence[str]) -> None:
        _unsubscribe_market_conditions_fn(self, condition_ids)

    def _condition_instruments(self, condition_id: str) -> tuple[object, ...]:
        return _condition_instruments_fn(self, condition_id)

    def _clear_condition_subscription_state(self, condition_id: str) -> None:
        _clear_condition_subscription_state_fn(self, condition_id)

    def _unsubscribe_market_instrument(self, instrument_id: object) -> bool:
        return _unsubscribe_market_instrument_fn(self, instrument_id)
