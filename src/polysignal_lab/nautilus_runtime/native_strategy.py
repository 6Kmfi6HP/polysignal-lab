"""
Input: __future__, __future__.annotations, collections, collections.deque, collections.abc, collections.abc.Callable, collections.abc.Iterable, collections.abc.Mapping, collections.abc.Sequence, datetime
Output: PolySignalNativeStrategy
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
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
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_bridge.market_catalog import (
    MarketCatalog,
)
from polysignal_lab.nautilus_bridge.state import save_strategy_state, load_strategy_state
from polysignal_lab.nautilus_runtime.decision_policy import (
    ApprovedDecision,
    DecisionPolicy,
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
)
from polysignal_lab.nautilus_runtime.native_strategy_exit import NativeExitPolicy
from polysignal_lab.nautilus_runtime.strategy.custom_data_handlers import route_strategy_data
from polysignal_lab.nautilus_runtime.strategy.decision_pipeline import (
    DecisionPipeline,
    DecisionPipelineState,
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
    call_subscription as _call_subscription_fn,
    clear_condition_subscription_state as _clear_condition_subscription_state_fn,
    condition_instruments as _condition_instruments_fn,
    mark_market_subscription_ready as _mark_market_subscription_ready_fn,
    refresh_asset_conditions as _refresh_asset_conditions_fn,
    refresh_stale_market_subscription as _refresh_stale_market_subscription_fn,
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
    _identity_instrument_id,
    _market_view_ready,
    _nautilus_instrument_id,
    _sidecar_data_client_id,
    _spot_data_client_id,
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
        policy: DecisionPolicy | None = None,
        fixed_stake_usdc: float = 10.0,
        paper_risk_gate: object | None = None,
        exit_model: object | None = None,
        data_names: Sequence[str] = DEFAULT_NATIVE_DATA_NAMES,
        book_type: str = "L2_MBP",
        instrument_id_resolver: Callable[[str], object] | None = None,
        registry: MarketCatalog | None = None,
        observability: _Observability | None = None,
        progress_callback: Callable[[str], None] | None = None,
        readiness_callback: Callable[[str, bool], None] | None = None,
        unsubscribe_exited: bool = True,
        l1_book_snapshot_interval_ms: int = DEFAULT_L1_BOOK_SNAPSHOT_INTERVAL_MS,
        config: StrategyConfig | None = None,
    ) -> None:
        super().__init__(config=config or StrategyConfig())
        if registry is None or assembler is None:
            raise RuntimeError(MISSING_PROJECTIONS_ERROR)
        self._configure_dependencies(core, assembler, condition_ids, strategy_name, policy, registry)
        self._configure_runtime_options(
            fixed_stake_usdc=fixed_stake_usdc,
            paper_risk_gate=paper_risk_gate,
            exit_model=exit_model,
            data_names=data_names,
            book_type=book_type,
            instrument_id_resolver=instrument_id_resolver,
            observability=observability,
            progress_callback=progress_callback,
            readiness_callback=readiness_callback,
            l1_book_snapshot_interval_ms=l1_book_snapshot_interval_ms,
        )
        self._initialize_runtime_state(registry, unsubscribe_exited=unsubscribe_exited)

    def _configure_dependencies(
        self,
        core: AlphaCore,
        assembler: _Assembler,
        condition_ids: Sequence[str],
        strategy_name: str,
        policy: DecisionPolicy | None,
        registry: MarketCatalog,
    ) -> None:
        if policy is None:
            raise TypeError("policy must be an injected shared DecisionPolicy")
        self.core = core
        self.custom_data = StrategyCustomDataState()
        resolved_assembler = _assembler_with_custom_data(assembler, self.custom_data)
        if resolved_assembler is None:
            raise RuntimeError(MISSING_PROJECTIONS_ERROR)
        self.assembler = resolved_assembler
        self.condition_ids = tuple(condition_ids)
        self.strategy_name = strategy_name
        self.policy = policy
        self.registry = registry

    def _configure_runtime_options(
        self,
        *,
        fixed_stake_usdc: float,
        paper_risk_gate: object | None,
        exit_model: object | None,
        data_names: Sequence[str],
        book_type: str,
        instrument_id_resolver: Callable[[str], object] | None,
        observability: _Observability | None,
        progress_callback: Callable[[str], None] | None,
        readiness_callback: Callable[[str, bool], None] | None,
        l1_book_snapshot_interval_ms: int,
    ) -> None:
        self.fixed_stake_usdc = fixed_stake_usdc
        self.paper_risk_gate = paper_risk_gate
        self.exit_policy = NativeExitPolicy.from_config(exit_model)
        self.data_names = tuple(data_names)
        self.book_type = book_type
        self.l1_book_snapshot_interval_ms = int(l1_book_snapshot_interval_ms)
        self.instrument_id_resolver = instrument_id_resolver or _identity_instrument_id
        self.observability = observability
        self.progress_callback = progress_callback
        self.readiness_callback = readiness_callback

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
        self._exit_inflight: set[str] = set()

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
            _mark_market_subscription_ready_fn(self, condition_id)
        else:
            self._runtime_readiness_miss_condition_ids.add(condition_id)
        callback = self.readiness_callback
        if callback is None:
            return
        callback(condition_id, ready)

    def _note_stale_orderbook_rejection(
        self,
        condition_id: str,
        *,
        side: object,
        threshold_ms: object,
    ) -> None:
        if (
            isinstance(side, Side)
            and isinstance(threshold_ms, (int, float))
            and not isinstance(threshold_ms, bool)
            and float(threshold_ms) > 0
        ):
            recovery = self._stale_orderbook_recovery_by_condition.setdefault(
                condition_id,
                {},
            )
            threshold = float(threshold_ms)
            recovery[side] = min(recovery.get(side, threshold), threshold)
        self._note_runtime_readiness(condition_id, ready=False)

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

    def _framework_now(self) -> datetime:
        timestamp_ns = getattr(self.clock, "timestamp_ns", None)
        if not callable(timestamp_ns):
            if getattr(self, "trader_id", None) is None:
                return datetime(1970, 1, 1, tzinfo=UTC)
            raise RuntimeError("Nautilus framework clock timestamp_ns is unavailable")
        try:
            value = int(timestamp_ns())
        except NotImplementedError:
            if getattr(self, "trader_id", None) is None:
                return datetime(1970, 1, 1, tzinfo=UTC)
            raise RuntimeError("Nautilus framework clock timestamp_ns is unavailable")
        if value <= 0:
            raise RuntimeError("Nautilus framework clock returned an invalid timestamp")
        return datetime.fromtimestamp(value / 1_000_000_000, UTC)

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
        _subscribe_custom_data(
            self,
            PolySignalSpotData,
            client_id=_spot_data_client_id(),
        )
        _subscribe_custom_data(
            self,
            PolySignalPriceToBeatData,
            client_id=_sidecar_data_client_id(),
        )
        _subscribe_custom_data(
            self,
            PolySignalMarketMetaData,
            client_id=_sidecar_data_client_id(),
        )
        _subscribe_custom_data(
            self,
            PolySignalMarketUniverseData,
            client_id=_sidecar_data_client_id(),
        )
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
        now = self._framework_now()
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
        condition_id = self._condition_from_market_data(deltas)
        if condition_id is None:
            return
        self._evaluate_market_data_condition(condition_id, event=deltas)

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
        condition_id = self._condition_from_market_data(tick)
        if condition_id is None:
            return
        self._evaluate_market_data_condition(condition_id, event=tick)

    def on_order_book(self, book: object) -> None:
        condition_id = self._condition_from_market_data(book)
        if condition_id is None:
            return
        self._evaluate_market_data_condition(condition_id, event=book)

    def on_trade_tick(self, tick: object) -> None:
        condition_id = self._condition_from_market_data(tick)
        if condition_id is None:
            return
        self._evaluate_market_data_condition(condition_id, event=tick)

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
        self._release_risk_reservation(event)
        self._clear_exit_inflight_from_event(event)
        _handle_order_lifecycle_event(
            self, "on_order_rejected", event, forget_metrics=True
        )

    def on_order_canceled(self, event: object) -> None:
        self._release_risk_reservation(event)
        self._clear_exit_inflight_from_event(event)
        _handle_order_lifecycle_event(
            self, "on_order_canceled", event, forget_metrics=True
        )

    def on_order_expired(self, event: object) -> None:
        self._release_risk_reservation(event)
        self._clear_exit_inflight_from_event(event)
        _handle_order_lifecycle_event(
            self, "on_order_expired", event, forget_metrics=True
        )

    def on_order_filled(self, event: object) -> None:
        self._release_risk_reservation(event)
        self._clear_exit_inflight_from_event(event)
        _handle_order_filled(self, event)

    def on_position_opened(self, position: object) -> None:
        _handle_position_event(self, position)

    def on_position_changed(self, position: object) -> None:
        _handle_position_event(self, position)

    def on_position_closed(self, position: object) -> None:
        position_id = str(getattr(position, "id", ""))
        if position_id:
            self._exit_inflight.discard(position_id)
        _handle_position_closed(self, position)

    def evaluate_condition(
        self,
        condition_id: str,
        *,
        created_at: datetime | None = None,
    ) -> None:
        if condition_id not in self._active_condition_ids:
            return
        now = created_at or self._framework_now()
        view = self._require_assembler().build(condition_id, created_at=now)
        if view is None:
            self._note_runtime_progress("readiness_miss")
            self._note_runtime_readiness(condition_id, ready=False)
            _ = self.refresh_stale_market_subscription(condition_id)
            return
        if not _market_view_ready(view):
            self._note_runtime_progress("readiness_miss")
            self._note_runtime_readiness(condition_id, ready=False)
            _ = self.refresh_stale_market_subscription(condition_id)
            return
        self._evaluate_ready_condition(
            condition_id,
            cast(MarketView, view),
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
                _ = self.refresh_stale_market_subscription(condition_id)
                return
            self._note_runtime_readiness(condition_id, ready=True)
            readiness_confirmed = True
        elif condition_id in self._runtime_readiness_miss_condition_ids:
            self._note_runtime_readiness(condition_id, ready=True)
            readiness_confirmed = True
        decisions = self._evaluate_decisions(market_view, now=now)
        if decisions is None:
            return
        batch = [(decision, market_view) for decision in decisions]
        try:
            batch_result = self._decision_pipeline.try_batch_arbitrate(batch)
        except Exception:
            self._note_runtime_progress("arbitration_failed")
            return
        for decision, rejected in batch_result.rejections:
            self._decision_pipeline.record_batch_rejection(
                rejected,
                decision,
                state=self._pipeline_state,
                sink=self._decision_sink,
            )
        for decision in batch_result:
            self._handle_decision(decision, market_view)
        if (
            not readiness_confirmed
            and condition_id not in self._runtime_readiness_miss_condition_ids
        ):
            self._note_runtime_readiness(condition_id, ready=True)

    def _evaluate_decisions(
        self,
        market_view: MarketView,
        *,
        now: datetime,
    ) -> tuple[AlphaDecision, ...] | None:
        if self.exit_policy is None:
            return tuple(self.core.evaluate(market_view))
        try:
            cache = self.cache
        except (AttributeError, RuntimeError):
            cache = None
        try:
            decisions = self.exit_policy.decisions(
                cache=cache,
                strategy_id=getattr(self, "id", None),
                registry=self._require_registry(),
                view=market_view,
                now=now,
                inflight=self._exit_inflight,
            )
        except (TypeError, ValueError, RuntimeError):
            self._note_runtime_progress("native_exit_failed")
            return tuple(self.core.evaluate(market_view))
        if decisions:
            self._note_runtime_progress("native_exit")
            return decisions
        return tuple(self.core.evaluate(market_view))

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
        # Subclasses supplied by Nautilus/tests provide the native submit surface.
        order = submit_approved_for_view(
            cast(OrderSubmittingStrategy[object], cast(object, self)),
            approved,
            view=view,
            fixed_stake_usdc=self.fixed_stake_usdc,
            instrument_id_resolver=self._resolved_instrument,
            now=self._framework_now,
        )
        if signal.reduce_only:
            position_id = str(signal.metrics.get("position_id") or "")
            if position_id:
                self._exit_inflight.add(position_id)
        return order

    def _release_risk_reservation(self, event: object) -> None:
        release_from_event = getattr(self.paper_risk_gate, "release_from_event", None)
        if callable(release_from_event):
            release_from_event(event)

    def _clear_exit_inflight_from_event(self, event: object) -> None:
        metrics: Mapping[str, object] = {}
        metrics_for_event = getattr(self._metrics_tracker, "metrics_for_event", None)
        if callable(metrics_for_event):
            try:
                raw_metrics = metrics_for_event(event)
            except (KeyError, TypeError, ValueError):
                raw_metrics = {}
            if isinstance(raw_metrics, Mapping):
                metrics = raw_metrics
        position_id = str(metrics.get("position_id") or "")
        if not position_id:
            tags = getattr(event, "tags", ())
            if isinstance(tags, (str, bytes)):
                tags = (tags,)
            for tag in tags:
                text = str(tag)
                if text.startswith("position_id="):
                    position_id = text.partition("=")[2]
                    break
        if position_id:
            self._exit_inflight.discard(position_id)

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
        *,
        retry_after: timedelta | None = None,
    ) -> None:
        _retry_market_instrument_requests_fn(
            self, condition_ids, retry_after=retry_after
        )

    def _subscribe_market_conditions(self, condition_ids: Sequence[str]) -> None:
        _subscribe_market_conditions_fn(self, condition_ids)

    def _subscribe_market_instrument(self, instrument_id: object) -> bool:
        return _subscribe_market_instrument_fn(self, instrument_id)

    def _unsubscribe_market_conditions(self, condition_ids: Sequence[str]) -> None:
        _unsubscribe_market_conditions_fn(self, condition_ids)

    def refresh_stale_market_subscription(self, condition_id: str) -> bool:
        return _refresh_stale_market_subscription_fn(self, condition_id)

    def _condition_instruments(self, condition_id: str) -> tuple[object, ...]:
        return _condition_instruments_fn(self, condition_id)

    def _clear_condition_subscription_state(self, condition_id: str) -> None:
        _clear_condition_subscription_state_fn(self, condition_id)

    def _unsubscribe_market_instrument(self, instrument_id: object) -> bool:
        return _unsubscribe_market_instrument_fn(self, instrument_id)

    def _call_subscription(
        self,
        callback: Callable[..., object],
        *args: object,
        **kwargs: object,
    ) -> bool:
        return _call_subscription_fn(self, callback, *args, **kwargs)
