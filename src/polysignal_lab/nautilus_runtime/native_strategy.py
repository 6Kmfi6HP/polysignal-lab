"""
Input: __future__, __future__.annotations, collections, collections.deque, collections.abc, collections.abc.Callable, collections.abc.Iterable, collections.abc.Mapping, collections.abc.Sequence, datetime
Output: PolySignalNativeStrategy
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import cast

from nautilus_trader.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy

from polysignal_lab.alpha.types import (
    AlphaCore,
    AlphaDecision,
    AlphaFillEvent,
    AlphaOrderEvent,
    MarketView,
)
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_bridge.market_catalog import (
    MarketCatalog,
)
from polysignal_lab.nautilus_bridge.state import save_strategy_state, load_strategy_state
from polysignal_lab.nautilus_runtime.decision_policy import (
    ApprovedDecision,
    DecisionPolicyActor,
)
from polysignal_lab.nautilus_runtime.custom_data_state import StrategyCustomDataState
from polysignal_lab.nautilus_runtime.custom_data_types import (
    PolySignalMarketMetaData,
    PolySignalMarketUniverseData,
    PolySignalPriceToBeatData,
    PolySignalSpotData,
)
from polysignal_lab.nautilus_runtime.native_order import (
    OrderSubmittingStrategy,
    submit_approved_decision,
)
from polysignal_lab.nautilus_runtime.strategy.custom_data_handlers import route_strategy_data
from polysignal_lab.nautilus_runtime.strategy.decision_pipeline import (
    DecisionPipeline,
    DecisionPipelineState,
    NativeDecisionSinkImpl,
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
    refresh_asset_conditions as _refresh_asset_conditions_fn,
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
    _identity_instrument_id,
    _market_view_ready,
    _nautilus_instrument_id,
    _subscribe_custom_data,
    classify_project_owned_data,
)


class PolySignalNativeStrategy(Strategy):
    """Nautilus callback-shaped strategy wrapper around a PolySignal alpha core."""

    def __init__(
        self,
        *,
        core: AlphaCore,
        assembler: _Assembler | None,
        condition_ids: Sequence[str],
        strategy_name: str,
        policy: DecisionPolicyActor,
        fixed_stake_usdc: float = 10.0,
        data_names: Sequence[str] = DEFAULT_NATIVE_DATA_NAMES,
        book_type: str = "L2_MBP",
        instrument_id_resolver: Callable[[str], object] | None = None,
        registry: MarketCatalog | None = None,
        observability: _Observability | None = None,
        progress_callback: Callable[[str], None] | None = None,
        unsubscribe_exited: bool = True,
        l1_book_snapshot_interval_ms: int = DEFAULT_L1_BOOK_SNAPSHOT_INTERVAL_MS,
        config: StrategyConfig | None = None,
    ) -> None:
        super().__init__(config=config or StrategyConfig())

        if registry is None or assembler is None:
            raise RuntimeError(MISSING_PROJECTIONS_ERROR)

        self.core: AlphaCore = core
        self.custom_data: StrategyCustomDataState = StrategyCustomDataState()
        resolved_assembler = _assembler_with_custom_data(assembler, self.custom_data)
        if resolved_assembler is None:
            raise RuntimeError(MISSING_PROJECTIONS_ERROR)
        self.assembler: _Assembler = resolved_assembler
        self.condition_ids: tuple[str, ...] = tuple(condition_ids)
        self.strategy_name: str = strategy_name
        self.policy: DecisionPolicyActor = policy
        self.fixed_stake_usdc: float = fixed_stake_usdc
        self.data_names: tuple[str, ...] = tuple(data_names)
        self.book_type: str = book_type
        self.l1_book_snapshot_interval_ms: int = int(l1_book_snapshot_interval_ms)
        self.instrument_id_resolver: Callable[[str], object] = (
            instrument_id_resolver or _identity_instrument_id
        )
        self.registry: MarketCatalog | None = registry
        self.observability: _Observability | None = observability
        self.progress_callback: Callable[[str], None] | None = progress_callback
        self._initialize_runtime_state(registry, unsubscribe_exited=unsubscribe_exited)

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

    def _init_decision_pipeline(self) -> None:
        self._pipeline_state = DecisionPipelineState()
        self._decision_pipeline = DecisionPipeline(
            lambda: self.policy,
            is_active_condition=lambda condition_id: condition_id in self._active_condition_ids,
        )
        self._metrics_tracker = ApprovedSignalMetricsTracker(
            submitted_signal_keys=self._pipeline_state.submitted_signal_keys,
        )
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
        self.submitted_orders = self._pipeline_state.submitted_orders

    def _init_subscriptions(self, registry: MarketCatalog) -> None:
        self._refresh_asset_conditions()

    def _init_runtime_queues(self) -> None:
        self.submitted_specs: deque[object] = deque(maxlen=1000)
        self.execution_results: deque[object] = deque(maxlen=1000)

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

    @property
    def cache(self) -> object:
        cache_override = getattr(self, "_cache_override", None)
        if cache_override is not None:
            return cache_override
        return super().cache

    @cache.setter
    def cache(self, value: object) -> None:
        self._cache_override = value

    @property
    def order_factory(self) -> object:
        order_factory_override = getattr(self, "_order_factory_override", None)
        if order_factory_override is not None:
            return order_factory_override
        return super().order_factory

    @order_factory.setter
    def order_factory(self, value: object) -> None:
        self._order_factory_override = value

    def on_start(self) -> None:
        self._note_runtime_progress("start")
        _ = self._require_registry()
        _ = self._require_assembler()
        self._subscribe_market_conditions(self._startup_condition_ids)
        _subscribe_custom_data(self, PolySignalSpotData)
        _subscribe_custom_data(self, PolySignalPriceToBeatData)
        _subscribe_custom_data(self, PolySignalMarketMetaData)
        _subscribe_custom_data(self, PolySignalMarketUniverseData)
        self._start_evaluation_heartbeat()

    def _start_evaluation_heartbeat(self) -> None:
        try:
            _ = self.clock.set_timer(
                EVALUATION_HEARTBEAT_TIMER_NAME,
                EVALUATION_HEARTBEAT_INTERVAL,
                callback=self._on_evaluation_heartbeat,
            )
        except NotImplementedError:
            if getattr(self, "trader_id", None) is not None:
                raise

    def on_stop(self) -> None:
        _ = self.clock.cancel_timer(EVALUATION_HEARTBEAT_TIMER_NAME)

    def on_save(self) -> dict[str, bytes]:
        return save_strategy_state(self.strategy_name, self.core)

    def on_load(self, state: Mapping[str, bytes]) -> None:
        load_strategy_state(self.strategy_name, self.core, state)


    def _on_evaluation_heartbeat(self, _event: object) -> None:
        self._note_runtime_progress("evaluation_heartbeat")
        now = datetime.now(UTC)
        for condition_id in tuple(sorted(self._active_condition_ids)):
            last_market_data_eval = self._last_market_data_evaluation_at.get(condition_id)
            if (
                last_market_data_eval is not None
                and now - last_market_data_eval < EVALUATION_HEARTBEAT_INTERVAL
            ):
                continue
            self.evaluate_condition(condition_id)

    def on_data(self, data: object) -> None:
        route_strategy_data(
            self,
            data,
            classify=classify_project_owned_data,
        )

    def on_order_book_deltas(self, deltas: object) -> None:
        condition_id = self._condition_from_order_book_deltas(deltas)
        if condition_id is None:
            return
        self._evaluate_market_data_condition(condition_id)

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

    def _condition_from_order_book_deltas(self, deltas: object) -> str | None:
        return self._condition_from_market_data(deltas)

    def on_quote_tick(self, tick: object) -> None:
        condition_id = self._condition_from_quote_tick(tick)
        if condition_id is None:
            return
        self._evaluate_market_data_condition(condition_id)

    def _condition_from_quote_tick(self, tick: object) -> str | None:
        return self._condition_from_market_data(tick)

    def on_order_book(self, book: object) -> None:
        condition_id = self._condition_from_order_book(book)
        if condition_id is None:
            return
        self._evaluate_market_data_condition(condition_id)

    def _condition_from_order_book(self, book: object) -> str | None:
        return self._condition_from_market_data(book)

    def on_trade_tick(self, tick: object) -> None:
        condition_id = self._condition_from_trade_tick(tick)
        if condition_id is None:
            return
        self._evaluate_market_data_condition(condition_id)

    def _condition_from_trade_tick(self, tick: object) -> str | None:
        return self._condition_from_market_data(tick)

    def _evaluate_market_data_condition(self, condition_id: str) -> None:
        self._note_runtime_progress("market_data_evaluation")
        self._last_market_data_evaluation_at[condition_id] = datetime.now(UTC)
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
        _handle_position_event(self, position)

    def evaluate_condition(self, condition_id: str) -> None:
        if condition_id not in self._active_condition_ids:
            return
        view = self._require_assembler().build(condition_id)
        if view is None:
            return
        if not _market_view_ready(view):
            self._note_runtime_progress("readiness_miss")
            return
        market_view = cast(MarketView, view)
        for decision in self.core.evaluate(market_view):
            self._handle_decision(decision, market_view)

    def _handle_decision(self, decision: AlphaDecision, view: MarketView) -> None:
        self._decision_pipeline.handle_decision(
            decision,
            view,
            state=self._pipeline_state,
            sink=self._decision_sink,
        )

    def _submit_approved(
        self, approved: ApprovedDecision, *, view: MarketView
    ) -> object:
        signal = approved.signal
        book = view.book_for(signal.side)
        # Subclasses supplied by Nautilus/tests provide the native submit surface.
        return submit_approved_decision(
            cast(OrderSubmittingStrategy[object], cast(object, self)),
            approved,
            fixed_stake_usdc=self.fixed_stake_usdc,
            best_ask=book.best_ask,
            instrument_id_resolver=self._resolved_instrument,
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

    def _subscribe_market_conditions(self, condition_ids: Sequence[str]) -> None:
        _subscribe_market_conditions_fn(self, condition_ids)

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

    def subscribe_data(self, data_type: object) -> None:
        super().subscribe_data(data_type)
