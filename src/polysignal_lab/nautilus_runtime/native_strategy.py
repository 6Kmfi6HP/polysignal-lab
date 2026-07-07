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
    MarketPairMeta,
)
from polysignal_lab.nautilus_bridge.state import JsonValue, StateSchemaError, decode_state, encode_state
from polysignal_lab.nautilus_runtime.decision_policy import (
    ApprovedDecision,
    DecisionPolicyActor,
    RejectedDecision,
)
from polysignal_lab.nautilus_runtime.custom_data_state import StrategyCustomDataState
from polysignal_lab.nautilus_runtime.market_data import (
    PolySignalMarketMetaData,
    PolySignalMarketUniverseData,
    PolySignalPriceToBeatData,
    PolySignalSpotData,
)
from polysignal_lab.nautilus_runtime.native_order import (
    OrderSubmittingStrategy,
    submit_approved_decision,
)
from polysignal_lab.nautilus_runtime.strategy.helpers import (
    DEFAULT_L1_BOOK_SNAPSHOT_INTERVAL_MS,
    DEFAULT_NATIVE_DATA_NAMES,
    EVALUATION_HEARTBEAT_INTERVAL,
    EVALUATION_HEARTBEAT_TIMER_NAME,
    L1_RAW_DELTA_FALLBACK_PHASE,
    MISSING_PROJECTIONS_ERROR,
    DataBoundaryClassification,
    _Assembler,
    _Observability,
    _asset_conditions,
    _assembler_with_custom_data,
    _condition_id_from_catalog_instrument,
    _datetime_or_now,
    _event_side,
    _fallback_fill_price,
    _identifier_text,
    _identity_instrument_id,
    _instrument_ids,
    _json_state_payload,
    _lookup_id_text,
    _market_id_for_condition,
    _market_view_ready,
    _maybe_float,
    _nautilus_instrument_id,
    _optional_str,
    _projection_fill_event,
    _projection_order_event,
    _subscribe_custom_data,
    _tags,
    _token_id_from_catalog_instrument,
    _value,
    classify_project_owned_data,
)
from polysignal_lab.nautilus_runtime.strategy.subscriptions import MarketSubscriptionState


class _SubscriptionManager:
    """Encapsulates subscription management for PolySignalNativeStrategy.

    Owns the MarketSubscriptionState and handles subscribe/unsubscribe
    dispatch for market data (quote_ticks, trade_ticks, order_book_deltas)
    and custom data type subscription via MRO-based delegation.
    """

    def __init__(
        self,
        strategy: object,
        registry: MarketCatalog,
        data_names: tuple[str, ...],
        book_type: str,
        startup_condition_ids: tuple[str, ...],
    ) -> None:
        self._strategy: object = strategy
        self._registry: MarketCatalog = registry
        self._data_names: tuple[str, ...] = data_names
        self._book_type: str = book_type
        self._condition_ids: tuple[str, ...] = startup_condition_ids
        self._state: MarketSubscriptionState = MarketSubscriptionState()

    @property
    def state(self) -> MarketSubscriptionState:
        return self._state

    def subscribe_market_conditions(
        self,
        condition_ids: Sequence[str],
        active_condition_ids: set[str],
    ) -> None:
        """Subscribe all instruments for the given conditions."""
        if self._registry is None:
            return
        for condition_id in condition_ids:
            if condition_id not in active_condition_ids:
                continue
            if condition_id in self._state.wire_condition_ids:
                self._state.pending_metadata_condition_ids.discard(condition_id)
                self._state.pending_subscribe_condition_ids.discard(condition_id)
                self._state.retained_wire_condition_ids.discard(condition_id)
                continue
            instrument_ids = _instrument_ids(self._registry, (condition_id,))
            if not instrument_ids:
                self._state.pending_metadata_condition_ids.add(condition_id)
                self._state.pending_subscribe_condition_ids.discard(condition_id)
                continue
            self._state.pending_metadata_condition_ids.discard(condition_id)
            for instrument_id in instrument_ids:
                instrument_text = _identifier_text(instrument_id)
                if instrument_text is not None:
                    self._subscribe_market_instrument(instrument_text)
            self._state.pending_subscribe_condition_ids.discard(condition_id)
            self._state.retained_wire_condition_ids.discard(condition_id)
            self._state.wire_condition_ids.add(condition_id)

    def _subscribe_market_instrument(self, instrument_id: str) -> None:
        """Subscribe to market data for a specific instrument."""
        for data_name in self._data_names:
            method = getattr(self._strategy, f"subscribe_{data_name}", None)
            if callable(method):
                _ = method(instrument_id)
        if self._book_type == "L1_MBP":
            request_l1 = getattr(self._strategy, "request_order_book_snapshot", None)
            if callable(request_l1):
                _ = request_l1(instrument_id)

    def unsubscribe_market_conditions(self, condition_ids: Sequence[str]) -> None:
        """Unsubscribe all instruments for the given conditions."""
        if self._registry is None:
            return
        for condition_id in condition_ids:
            instrument_ids = _instrument_ids(self._registry, (condition_id,))
            for instrument_id in instrument_ids:
                instrument_text = _identifier_text(instrument_id)
                if instrument_text is not None:
                    self._unsubscribe_market_instrument(instrument_text)
            self._state.wire_condition_ids.discard(condition_id)
            self._state.retained_wire_condition_ids.discard(condition_id)
            self._state.pending_subscribe_condition_ids.discard(condition_id)
            self._state.pending_metadata_condition_ids.discard(condition_id)

    def _unsubscribe_market_instrument(self, instrument_id: str) -> None:
        """Unsubscribe from market data for a specific instrument."""
        for data_name in self._data_names:
            method = getattr(self._strategy, f"unsubscribe_{data_name}", None)
            if callable(method):
                _ = method(instrument_id)

    def subscribe_data(self, data_type: object) -> None:
        """Delegate to parent Strategy.subscribe_data() via MRO.

        Replaces the previous getattr-based dispatch (subscribe_{data_type})
        with a direct call to the Nautilus base class subscribe_data method,
        found by walking the strategy's MRO past PolySignalNativeStrategy.
        """
        mro = type(self._strategy).mro()
        try:
            base_index = mro.index(PolySignalNativeStrategy) + 1
        except ValueError:
            return
        base_subscribe = getattr(mro[base_index], "subscribe_data", None)
        if callable(base_subscribe):
            base_subscribe(self._strategy, data_type)


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
        Strategy.__init__(self, config=config or StrategyConfig())

        if registry is None or assembler is None:
            raise RuntimeError(MISSING_PROJECTIONS_ERROR)

        self.core: AlphaCore = core
        self.custom_data: StrategyCustomDataState = StrategyCustomDataState()
        self.assembler: _Assembler | None = (
            _assembler_with_custom_data(assembler, self.custom_data) if assembler is not None else None
        )
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
        self.cache_reader: object | None = None
        self.progress_callback: Callable[[str], None] | None = progress_callback
        self._subscription_manager: _SubscriptionManager = _SubscriptionManager(
            strategy=self,
            registry=registry,
            data_names=self.data_names,
            book_type=self.book_type,
            startup_condition_ids=self.condition_ids,
        )
        self._initialize_runtime_state(registry, unsubscribe_exited=unsubscribe_exited)

    def _initialize_runtime_state(
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
        self._approved_signal_metrics: dict[str, dict[str, object]] = {}
        self._submitted_signal_keys: set[str] = set()
        self._last_market_data_evaluation_at: dict[str, datetime] = {}
        self.rejected_decisions: deque[RejectedDecision] = deque(maxlen=1000)
        self.submitted_orders: deque[object] = deque(maxlen=1000)
        self.submitted_specs: deque[object] = deque(maxlen=1000)
        self.execution_results: deque[object] = deque(maxlen=1000)

    def _require_registry(self) -> MarketCatalog | None:
        if self.registry is None:
            raise RuntimeError(MISSING_PROJECTIONS_ERROR)
        return self.registry


    def _require_assembler(self) -> _Assembler | None:
        if self.assembler is None:
            raise RuntimeError(MISSING_PROJECTIONS_ERROR)
        return self.assembler

    def _note_runtime_progress(self, phase: str) -> None:
        callback = self.progress_callback
        if callback is None:
            return
        callback(phase)

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
        clock = getattr(self, "clock", None)
        set_timer = getattr(clock, "set_timer", None)
        if callable(set_timer):
            _ = set_timer(
                EVALUATION_HEARTBEAT_TIMER_NAME,
                EVALUATION_HEARTBEAT_INTERVAL,
                callback=self._on_evaluation_heartbeat,
            )

    def on_stop(self) -> None:
        clock = getattr(self, "clock", None)
        cancel_timer = getattr(clock, "cancel_timer", None)
        if callable(cancel_timer):
            _ = cancel_timer(EVALUATION_HEARTBEAT_TIMER_NAME)

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

    def on_data(self, data: object) -> list[NautilusOrderSpec]:
        if classify_project_owned_data(data) is DataBoundaryClassification.DROPPED_FRAME:
            self._note_runtime_progress("dropped_frame")
            return []
        if self._handle_custom_data(data):
            return []
        if isinstance(data, PolySignalMarketMetaData):
            if self._handle_market_metadata(data):
                return []
        if isinstance(data, PolySignalMarketUniverseData):
            if self._handle_market_universe(data):
                return []
        self._handle_generic_data(data)
        return []

    def _handle_custom_data(self, data: object) -> bool:
        if not isinstance(data, (PolySignalSpotData, PolySignalPriceToBeatData)):
            return False
        result = self.custom_data.apply(data)
        if result.spot_asset is not None:
            for candidate in self._asset_condition_ids.get(result.spot_asset, ()):
                self.evaluate_condition(candidate)
            return True
        if result.price_to_beat_condition_id is not None:
            self._retry_market_instrument_requests(
                (result.price_to_beat_condition_id,), retry_after=timedelta(seconds=10)
            )
            self.evaluate_condition(result.price_to_beat_condition_id)
            return True
        return True

    def _handle_market_metadata(self, data: PolySignalMarketMetaData) -> bool:
        registry = self._require_registry()
        registry.register(MarketPairMeta.from_metadata(data))
        self._refresh_asset_conditions()
        if data.condition_id in self._active_condition_ids:
            self._subscribe_market_conditions((data.condition_id,))
        return True

    def _handle_market_universe(self, data: PolySignalMarketUniverseData) -> bool:
        if self._market_epoch is not None and data.epoch <= self._market_epoch:
            return True
        self._market_epoch = data.epoch
        self._active_condition_ids = set(data.active_condition_ids)
        self._refresh_asset_conditions()
        for condition_id in data.exited_condition_ids:
            self._subscription_state.pending_metadata_condition_ids.discard(condition_id)
            self._subscription_state.pending_subscribe_condition_ids.discard(condition_id)
        if self.unsubscribe_exited:
            self._unsubscribe_market_conditions(data.exited_condition_ids)
        self._subscribe_market_conditions(tuple(self._active_condition_ids))
        return True

    def _handle_generic_data(self, data: object) -> None:
        assembler = self._require_assembler()
        updater = getattr(assembler, "on_data", None) or getattr(assembler, "update", None)
        if callable(updater):
            _ = updater(data)
        condition_id = cast(object, getattr(data, "condition_id", None))
        if condition_id is not None:
            self.evaluate_condition(str(condition_id))
            return
        for candidate in self._active_condition_ids:
            self.evaluate_condition(candidate)

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
        self._forget_approved_metrics(event, alpha_event)

    def on_order_canceled(self, event: object) -> None:
        self._note_runtime_progress("order_event")
        alpha_event = self._order_event(event)
        self._record_nautilus_order(event, alpha_event.metrics)
        self._call_core("on_order_canceled", alpha_event)
        self._forget_approved_metrics(event, alpha_event)

    def on_order_expired(self, event: object) -> None:
        self._note_runtime_progress("order_event")
        alpha_event = self._order_event(event)
        self._record_nautilus_order(event, alpha_event.metrics)
        self._call_core("on_order_expired", alpha_event)
        self._forget_approved_metrics(event, alpha_event)

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
                self._handle_decision(decision, view)

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
        for decision in self.core.evaluate(view):
            self._handle_decision(decision, view)

    def _handle_decision(self, decision: AlphaDecision, view: MarketView) -> None:
        if not _market_view_ready(view):
            self._note_runtime_progress("readiness_miss")
            return
        if decision.condition_id not in self._active_condition_ids:
            return
        policy_result = self.policy.decide(decision, view)
        if isinstance(policy_result, ApprovedDecision):
            signal_key = policy_result.signal.dedupe_key
            if signal_key in self._submitted_signal_keys:
                rejected = RejectedDecision(
                    reason_code="DUPLICATE_IN_FLIGHT_SIGNAL",
                    detail={"dedupe_key": signal_key},
                    candidate=policy_result.signal,
                )
                self.rejected_decisions.append(rejected)
                self._record_decision(decision, accepted=False)
                self._record_rejected(rejected)
                return
            self._submitted_signal_keys.add(signal_key)
            try:
                order = self._submit_approved(policy_result, view=view)
            except ValueError as exc:
                self._submitted_signal_keys.discard(signal_key)
                rejected = RejectedDecision(
                    reason_code="ORDER_MAPPING_FAILED",
                    detail={"error": str(exc)},
                    candidate=policy_result.signal,
                )
                self.rejected_decisions.append(rejected)
                self._record_decision(decision, accepted=False)
                self._record_rejected(rejected)
                return
            self._remember_approved_metrics(order, policy_result)
            self.submitted_orders.append(order)
            self._record_signal(policy_result.signal)
            self._notify_accepted_signal(policy_result.signal)
            self._record_decision(decision, accepted=True)
            return
        self.rejected_decisions.append(policy_result)
        self._record_decision(decision, accepted=False)
        self._record_rejected(policy_result)

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
        getter = getattr(cache, "instrument", None)
        if callable(getter):
            instrument_key = getattr(resolved, "id", resolved)
            cache_lookup = cast(Callable[[object], object | None], getter)
            try:
                cached = cache_lookup(instrument_key)
            except TypeError:
                cached = None
            if cached is None:
                try:
                    cached = cache_lookup(_nautilus_instrument_id(str(instrument_key)))
                except TypeError:
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
        if self.observability is None:
            return
        try:
            self.observability.record_nautilus_order_event(
                _projection_order_event(event, metrics)
            )
        except (OSError, sqlite3.Error):
            self._note_runtime_progress("telemetry_side_effect_failed")

    def _record_nautilus_fill(
        self, event: object, metrics: Mapping[str, object]
    ) -> None:
        if self.observability is None:
            return
        try:
            self.observability.record_nautilus_fill_event(
                _projection_fill_event(event, metrics)
            )
        except (OSError, sqlite3.Error):
            self._note_runtime_progress("telemetry_side_effect_failed")

    def _record_nautilus_position(self, position: object) -> None:
        if self.observability is None:
            return
        try:
            self.observability.record_nautilus_position(position)
        except (OSError, sqlite3.Error):
            self._note_runtime_progress("telemetry_side_effect_failed")




    def _order_event(self, event: object) -> AlphaOrderEvent:
        tags = _tags(_value(event, "tags"))
        metrics = self._approved_metrics_for_event(event)
        instrument_id = _identifier_text(_value(event, "instrument_id"))
        condition_id = tags.get("condition_id") or _optional_str(
            metrics.get("condition_id")
        )
        if not condition_id and self.registry is not None and instrument_id is not None:
            condition_id = _condition_id_from_catalog_instrument(
                self.registry, self.registry.condition_ids(), instrument_id
            )
        market_id = tags.get("market_id") or _optional_str(metrics.get("market_id"))
        if not market_id and self.registry is not None and condition_id is not None:
            market_id = _market_id_for_condition(self.registry, condition_id)
        token_id = tags.get("token_id") or _optional_str(metrics.get("token_id"))
        if not token_id and self.registry is not None and condition_id is not None and instrument_id is not None:
            token_id = _token_id_from_catalog_instrument(self.registry, condition_id, instrument_id)
        price = _maybe_float(_value(event, "price"))
        if "level_price" not in metrics and price is not None:
            metrics["level_price"] = price
        if "order_intent" not in metrics and tags.get("order_intent"):
            metrics["order_intent"] = tags["order_intent"]
        if "hedge_leg" not in metrics and tags.get("hedge_leg"):
            metrics["hedge_leg"] = tags["hedge_leg"] == "true"
        return AlphaOrderEvent(
            strategy=tags.get("strategy") or str(metrics.get("strategy") or self.strategy_name),
            market_id=market_id or str(_value(event, "market_id", "")),
            condition_id=condition_id or str(_value(event, "condition_id", "")),
            token_id=token_id or str(_value(event, "token_id", instrument_id or "")),
            side=_event_side(
                self.registry, instrument_id, token_id, _value(event, "side")
            ),
            order_id=str(_value(event, "order_id", _value(event, "id", ""))),
            client_order_id=_optional_str(_value(event, "client_order_id")),
            reason=_optional_str(_value(event, "reason")),
            ts_event=_datetime_or_now(
                _value(event, "ts_event", _value(event, "timestamp"))
            ),
            metrics=metrics,
        )

    def _fill_event(self, event: object) -> AlphaFillEvent:
        order = self._order_event(event)
        metrics = dict(order.metrics)
        fill_price = _maybe_float(
            _value(
                event, "fill_price", _value(event, "last_px", _value(event, "price"))
            )
        )
        if fill_price is None or fill_price <= 0.0:
            fill_price = _fallback_fill_price(
                metrics, _tags(_value(event, "tags")), order.side
            )
        if fill_price is not None:
            metrics["fill_price"] = fill_price
        shares = (
            _maybe_float(
                _value(
                    event,
                    "shares",
                    _value(event, "last_qty", _value(event, "quantity")),
                )
            )
            or 0.0
        )
        return AlphaFillEvent(
            strategy=order.strategy,
            market_id=order.market_id,
            condition_id=order.condition_id,
            token_id=order.token_id,
            side=order.side,
            order_id=order.order_id,
            client_order_id=order.client_order_id,
            reason=order.reason,
            ts_event=order.ts_event,
            metrics=metrics,
            fill_price=fill_price or 0.0,
            shares=shares,
            liquidity_side=_optional_str(_value(event, "liquidity_side")),
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

    def _approved_metrics_for_event(self, event: object) -> dict[str, object]:
        for key in self._event_lookup_ids(event):
            metrics = self._approved_signal_metrics.get(key)
            if metrics is not None:
                return dict(metrics)
        return {}

    def _event_lookup_ids(self, event: object) -> tuple[str, ...]:
        tags = _tags(_value(event, "tags"))
        values = (
            _value(event, "order_id"),
            _value(event, "client_order_id"),
            _value(event, "id"),
            tags.get("signal_id"),
            tags.get("order_id"),
            tags.get("client_order_id"),
        )
        return tuple(
            text
            for text in (_lookup_id_text(value) for value in values)
            if text is not None
        )

    def _remember_approved_metrics(
        self, order: object, approved: ApprovedDecision
    ) -> None:
        signal = approved.signal
        metrics: dict[str, object] = dict(
            cast(Mapping[str, object], getattr(signal, "metrics", {}) or {})
        )
        _ = metrics.setdefault("dedupe_key", signal.dedupe_key)
        signal_side = cast(object, getattr(signal, "side", None))
        signal_fields: dict[str, object] = {
            "signal_id": getattr(signal, "signal_id", None),
            "strategy": getattr(signal, "strategy", None),
            "asset": getattr(signal, "asset", None),
            "timeframe": getattr(signal, "timeframe", None),
            "market_id": getattr(signal, "market_id", None),
            "market_slug": getattr(signal, "market_slug", None),
            "condition_id": getattr(signal, "condition_id", None),
            "token_id": getattr(signal, "token_id", None),
            "side": getattr(signal_side, "value", signal_side),
        }
        for key, value in signal_fields.items():
            if value not in (None, ""):
                _ = metrics.setdefault(key, value)
        tags = _tags(_value(order, "tags"))
        values = (
            _value(order, "id"),
            _value(order, "client_order_id"),
            getattr(signal, "signal_id", None),
            tags.get("signal_id"),
            tags.get("order_id"),
            tags.get("client_order_id"),
        )
        for value in values:
            text = _lookup_id_text(value)
            if text is not None:
                self._approved_signal_metrics[text] = dict(metrics)

    def _forget_approved_metrics(self, event: object, order: AlphaOrderEvent) -> None:
        keys = set(self._event_lookup_ids(event))
        if order.order_id:
            keys.add(order.order_id)
        if order.client_order_id:
            keys.add(order.client_order_id)
        for key in keys:
            metrics = self._approved_signal_metrics.pop(key, None)
            if metrics is not None:
                dedupe_key = metrics.get("dedupe_key")
                if isinstance(dedupe_key, str):
                    self._submitted_signal_keys.discard(dedupe_key)

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
        request_instrument = getattr(self, "request_instrument", None)
        if not callable(request_instrument):
            return
        for instrument_id in _instrument_ids(self.registry, condition_ids):
            _ = request_instrument(instrument_id)

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
            for instrument_id in instrument_ids:
                instrument_text = _identifier_text(instrument_id)
                if instrument_text is not None:
                    self._subscribe_market_instrument(instrument_text)
            self._subscription_state.pending_subscribe_condition_ids.discard(
                condition_id
            )
            self._subscription_state.retained_wire_condition_ids.discard(condition_id)
            self._subscription_state.wire_condition_ids.add(condition_id)

    def _subscribe_market_instrument(self, instrument_id: str) -> None:
        for data_name in self.data_names:
            method = getattr(self, f"subscribe_{data_name}", None)
            if callable(method):
                _ = method(instrument_id)
        if self.book_type == "L1_MBP":
            request_l1 = getattr(self, "request_order_book_snapshot", None)
            if callable(request_l1):
                _ = request_l1(instrument_id)

    def _unsubscribe_market_conditions(self, condition_ids: Sequence[str]) -> None:
        if self.registry is None:
            return
        for condition_id in condition_ids:
            instrument_ids = _instrument_ids(self.registry, (condition_id,))
            for instrument_id in instrument_ids:
                instrument_text = _identifier_text(instrument_id)
                if instrument_text is not None:
                    self._unsubscribe_market_instrument(instrument_text)
            self._subscription_state.wire_condition_ids.discard(condition_id)
            self._subscription_state.retained_wire_condition_ids.discard(condition_id)
            self._subscription_state.pending_subscribe_condition_ids.discard(
                condition_id
            )
            self._subscription_state.pending_metadata_condition_ids.discard(
                condition_id
            )

    def _unsubscribe_market_instrument(self, instrument_id: str) -> None:
        for data_name in self.data_names:
            method = getattr(self, f"unsubscribe_{data_name}", None)
            if callable(method):
                _ = method(instrument_id)

    def subscribe_data(self, data_type: object) -> None:
        method = getattr(self, f"subscribe_{data_type}", None)
        if callable(method):
            for condition_id in self.condition_ids:
                _ = method(condition_id)
