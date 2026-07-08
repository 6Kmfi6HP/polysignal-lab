"""
Input: __future__, __future__.annotations, collections, collections.deque, collections.abc, collections.abc.Callable, collections.abc.Iterable, collections.abc.Mapping, collections.abc.Sequence, datetime
Output: PolySignalNativeStrategy
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
import sqlite3
from typing import cast

from nautilus_trader.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy

from polysignal_lab.alpha.types import (
    AlphaCore,
    AlphaDecision,
    AlphaFillEvent,
    AlphaOrderEvent,
    MarketView,
    NautilusOrderSpec,
)
from polysignal_lab.domain.enums import OrderIntent
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_bridge.market_catalog import (
    MarketCatalog,
)
from polysignal_lab.nautilus_bridge.state import decode_state, encode_state
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
    project_fill_event,
    project_nautilus_fill_event,
    project_nautilus_order_event,
    project_order_event,
)
from polysignal_lab.nautilus_runtime.strategy.subscriptions import MarketSubscriptionState
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
    _instrument_ids,
    _json_state_payload,
    _market_view_ready,
    _nautilus_book_type,
    _nautilus_instrument_id,
    _subscribe_custom_data,
    classify_project_owned_data,
)


class _InstrumentSubscriptionManager:
    def __init__(self, strategy: "PolySignalNativeStrategy") -> None:
        self._strategy = strategy

    def retry_instrument_requests(self, condition_ids: tuple[str, ...]) -> None:
        self._strategy._retry_market_instrument_requests(
            condition_ids,
            retry_after=timedelta(seconds=10),
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
        policy: DecisionPolicyActor | None = None,
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
        self.policy: DecisionPolicyActor = policy or DecisionPolicyActor()
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
        self._subscription_manager = _InstrumentSubscriptionManager(self)
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
        import warnings

        if not hasattr(self.core, "save_state"):
            warnings.warn(f"{type(self.core).__name__} has no save_state — state will not persist across restarts")
        saver = getattr(self.core, "save_state", None)
        raw_payload = saver() if callable(saver) else {}
        return encode_state(self.strategy_name, _json_state_payload(raw_payload))

    def on_load(self, state: Mapping[str, bytes]) -> None:
        loader = getattr(self.core, "load_state", None)
        if not callable(loader):
            return
        payload = cast(Mapping[str, object], decode_state(self.strategy_name, state))
        _ = loader(payload)


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
        self._note_runtime_progress("order_event")
        alpha_event = self._order_event(event)
        self._record_nautilus_order(event, alpha_event.metrics)
        self._call_core("on_order_submitted", alpha_event)

    def on_order_accepted(self, event: object) -> None:
        self._note_runtime_progress("order_event")
        alpha_event = self._order_event(event)
        self._record_nautilus_order(event, alpha_event.metrics)
        self._call_core("on_order_accepted", alpha_event)

    def on_order_rejected(self, event: object) -> None:
        self._note_runtime_progress("order_event")
        alpha_event = self._order_event(event)
        self._record_nautilus_order(event, alpha_event.metrics)
        self._call_core("on_order_rejected", alpha_event)
        self._forget_approved_metrics(
            event,
            cast(AlphaOrderEvent, cast(object, alpha_event)),
        )

    def on_order_canceled(self, event: object) -> None:
        self._note_runtime_progress("order_event")
        alpha_event = self._order_event(event)
        self._record_nautilus_order(event, alpha_event.metrics)
        self._call_core("on_order_canceled", alpha_event)
        self._forget_approved_metrics(
            event,
            cast(AlphaOrderEvent, cast(object, alpha_event)),
        )

    def on_order_expired(self, event: object) -> None:
        self._note_runtime_progress("order_event")
        alpha_event = self._order_event(event)
        self._record_nautilus_order(event, alpha_event.metrics)
        self._call_core("on_order_expired", alpha_event)
        self._forget_approved_metrics(
            event,
            cast(AlphaOrderEvent, cast(object, alpha_event)),
        )

    def on_order_filled(self, event: object) -> None:
        self._note_runtime_progress("order_event")
        alpha_event = self._fill_event(event)
        should_notify = self._should_notify_fill(alpha_event)
        if should_notify:
            notify = getattr(self.core, "on_notify_fill", None)
            if callable(notify):
                _ = notify(alpha_event.market_id, alpha_event.side, alpha_event.shares)
        self._record_nautilus_fill(event, alpha_event.metrics)
        self._forget_approved_metrics(
            event,
            cast(AlphaOrderEvent, cast(object, alpha_event)),
        )
        handler = getattr(self.core, "on_order_filled", None)
        decisions = handler(alpha_event) if callable(handler) else ()
        if isinstance(decisions, Iterable) and not isinstance(decisions, (str, bytes)):
            for decision in cast(Iterable[AlphaDecision], decisions):
                if decision.condition_id not in self._active_condition_ids:
                    continue
                view = self._require_assembler().build(decision.condition_id)
                if view is None:
                    continue
                self._handle_decision(decision, cast(MarketView, view))

    def on_position_opened(self, position: object) -> None:
        self._record_nautilus_position(position)

    def on_position_changed(self, position: object) -> None:
        self._record_nautilus_position(position)

    def on_position_closed(self, position: object) -> None:
        self._record_nautilus_position(position)

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

    def _token_id_from_view_instrument(self, view: MarketView, instrument_id: str) -> str | None:
        up_instrument = str(self._resolved_instrument(view.up.token_id))
        if instrument_id == up_instrument:
            return view.up.token_id
        down_instrument = str(self._resolved_instrument(view.down.token_id))
        if instrument_id == down_instrument:
            return view.down.token_id
        return None

    def _call_core(self, method_name: str, event: AlphaOrderEvent) -> None:
        handler = getattr(self.core, method_name, None)
        if callable(handler):
            _ = handler(event)

    def _record_signal(self, signal: SignalCandidate) -> None:
        recorder = (
            None
            if self.observability is None
            else getattr(self.observability, "record_signal", None)
        )
        if callable(recorder):
            _ = recorder(signal)

    def _notify_accepted_signal(self, signal: SignalCandidate) -> None:
        notifier = (
            None
            if self.observability is None
            else getattr(self.observability, "notify_accepted_signal", None)
        )
        if callable(notifier):
            _ = notifier(signal, self.fixed_stake_usdc)


    def _record_decision(self, decision: AlphaDecision, *, accepted: bool) -> None:
        if self.observability is None:
            return
        try:
            self.observability.record_decision(decision, accepted)
        except (OSError, sqlite3.Error):
            self._note_runtime_progress("telemetry_side_effect_failed")

    def _record_rejected(self, rejected: object) -> None:
        if self.observability is None:
            return
        self.observability.record_rejected_decision(rejected)

    def _record_nautilus_order(
        self, event: object, metrics: Mapping[str, object]
    ) -> None:
        self._record_observability(
            lambda obs: obs.record_nautilus_order_event(
                project_nautilus_order_event(event, metrics)
            )
        )

    def _record_observability(self, action: Callable[[_Observability], None]) -> None:
        observability = self.observability
        if observability is None:
            return
        try:
            action(observability)
        except (OSError, sqlite3.Error):
            self._note_runtime_progress("telemetry_side_effect_failed")

    def _record_nautilus_fill(
        self, event: object, metrics: Mapping[str, object]
    ) -> None:
        self._record_observability(
            lambda obs: obs.record_nautilus_fill_event(
                project_nautilus_fill_event(event, metrics)
            )
        )

    def _record_nautilus_position(self, position: object) -> None:
        self._record_observability(
            lambda obs: obs.record_nautilus_position(position)
        )

    def _order_event(self, event: object) -> AlphaOrderEvent:
        return project_order_event(
            event,
            registry=self.registry,
            strategy_name=self.strategy_name,
            metrics_lookup=self._metrics_tracker.metrics_for_event,
        )

    def _fill_event(self, event: object) -> AlphaFillEvent:
        return project_fill_event(
            event,
            registry=self.registry,
            strategy_name=self.strategy_name,
            metrics_lookup=self._metrics_tracker.metrics_for_event,
        )

    def _should_notify_fill(self, event: AlphaFillEvent) -> bool:
        if self.strategy_name != "vwap_momentum":
            return True
        intent = event.metrics.get("order_intent")
        if isinstance(intent, OrderIntent):
            intent = intent.value
        return not (
            bool(event.metrics.get("hedge_leg"))
            or intent == OrderIntent.PASSIVE_GTD.value
        )

    def _forget_approved_metrics(self, event: object, order: AlphaOrderEvent) -> None:
        self._metrics_tracker.forget(event, order)

    def _refresh_asset_conditions(self) -> None:
        tracked_condition_ids = tuple(
            dict.fromkeys((*self._startup_condition_ids, *self._active_condition_ids))
        )
        self._asset_condition_ids = _asset_conditions(
            self.registry, tracked_condition_ids
        )

    def _retry_market_instrument_requests(
        self,
        condition_ids: Sequence[str],
        *,
        retry_after: timedelta | None = None,
    ) -> None:
        _ = retry_after
        if self.registry is None:
            return
        for instrument_id in _instrument_ids(self.registry, condition_ids):
            _ = self.request_instrument(instrument_id)

    def _subscribe_market_conditions(self, condition_ids: Sequence[str]) -> None:
        if self.registry is None:
            return
        for condition_id in condition_ids:
            if condition_id not in self._active_condition_ids:
                continue
            if condition_id in self._subscription_state.wire_condition_ids:
                self._subscription_state.pending_metadata_condition_ids.discard(
                    condition_id
                )
                self._subscription_state.pending_subscribe_condition_ids.discard(
                    condition_id
                )
                self._subscription_state.retained_wire_condition_ids.discard(
                    condition_id
                )
                continue
            instrument_ids = _instrument_ids(self.registry, (condition_id,))
            if not instrument_ids:
                self._subscription_state.pending_metadata_condition_ids.add(
                    condition_id
                )
                self._subscription_state.pending_subscribe_condition_ids.discard(
                    condition_id
                )
                continue
            self._subscription_state.pending_metadata_condition_ids.discard(
                condition_id
            )
            subscribed = True
            for instrument_id in self._condition_instruments(condition_id):
                if not self._subscribe_market_instrument(instrument_id):
                    subscribed = False
            if subscribed:
                self._subscription_state.pending_subscribe_condition_ids.discard(
                    condition_id
                )
                self._subscription_state.retained_wire_condition_ids.discard(
                    condition_id
                )
                self._subscription_state.wire_condition_ids.add(condition_id)
            else:
                self._subscription_state.pending_subscribe_condition_ids.add(
                    condition_id
                )

    def _subscribe_market_instrument(self, instrument_id: object) -> bool:
        instrument_id = _nautilus_instrument_id(instrument_id)
        book_type = _nautilus_book_type(self.book_type)
        subscribed = self._call_subscription(self.subscribe_quote_ticks, instrument_id)
        if not self._call_subscription(self.subscribe_trade_ticks, instrument_id):
            subscribed = False
        if not self._call_subscription(
            self.subscribe_order_book_deltas,
            instrument_id,
            book_type=book_type,
        ):
            subscribed = False
        if self.book_type == "L1_MBP" and not self._call_subscription(
            self.request_order_book_snapshot, instrument_id
        ):
            subscribed = False
        return subscribed

    def _unsubscribe_market_conditions(self, condition_ids: Sequence[str]) -> None:
        if self.registry is None:
            return
        for condition_id in condition_ids:
            for instrument_id in self._condition_instruments(condition_id):
                _ = self._unsubscribe_market_instrument(instrument_id)
            self._clear_condition_subscription_state(condition_id)

    def _condition_instruments(self, condition_id: str) -> tuple[object, ...]:
        if self.registry is None:
            return ()
        return _instrument_ids(self.registry, (condition_id,))

    def _clear_condition_subscription_state(self, condition_id: str) -> None:
        self._subscription_state.wire_condition_ids.discard(condition_id)
        self._subscription_state.retained_wire_condition_ids.discard(condition_id)
        self._subscription_state.pending_subscribe_condition_ids.discard(condition_id)
        self._subscription_state.pending_metadata_condition_ids.discard(condition_id)

    def _unsubscribe_market_instrument(self, instrument_id: object) -> bool:
        instrument_id = _nautilus_instrument_id(instrument_id)
        unsubscribed = self._call_subscription(
            self.unsubscribe_quote_ticks, instrument_id
        )
        if not self._call_subscription(self.unsubscribe_trade_ticks, instrument_id):
            unsubscribed = False
        if not self._call_subscription(
            self.unsubscribe_order_book_deltas, instrument_id
        ):
            unsubscribed = False
        return unsubscribed

    def _call_subscription(
        self,
        callback: Callable[..., object],
        *args: object,
        **kwargs: object,
    ) -> bool:
        try:
            _ = callback(*args, **kwargs)
        except ValueError as e:
            message = str(e)
            if "not been registered" not in message:
                raise
            if message == "The actor has not been registered":
                return True
            return False
        return True

    def subscribe_data(self, data_type: object) -> None:
        super().subscribe_data(data_type)
