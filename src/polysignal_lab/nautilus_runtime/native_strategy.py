from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from importlib import import_module
import sqlite3
from types import SimpleNamespace
from typing import Protocol, cast

from polysignal_lab.alpha.types import (
    AlphaCore,
    AlphaDecision,
    AlphaFillEvent,
    AlphaOrderEvent,
    MarketView,
)
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_bridge.market_registry import (
    InstrumentTokenMeta,
    MarketPairMeta,
    PolymarketMarketRegistry,
)
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

DEFAULT_NATIVE_DATA_NAMES = ("quote_ticks", "trade_ticks", "order_book_deltas")
MISSING_PROJECTIONS_ERROR = "PolySignalNativeStrategy requires injected registry and assembler projections"
EVALUATION_HEARTBEAT_TIMER_NAME = "polysignal_evaluation_heartbeat"
EVALUATION_HEARTBEAT_INTERVAL = timedelta(seconds=10)
DEFAULT_L1_BOOK_SNAPSHOT_INTERVAL_MS = 1000
L1_RAW_DELTA_FALLBACK_PHASE = "l1_raw_delta_fallback"


class DataBoundaryClassification(Enum):
    VALID_DATA = "ValidData"
    DROPPED_FRAME = "DroppedFrame"
    RECOVERABLE_FEED_ERROR = "RecoverableFeedError"
    FATAL_FEED_ERROR = "FatalFeedError"


def classify_project_owned_data(data: object) -> DataBoundaryClassification:
    if isinstance(
        data,
        (
            PolySignalSpotData,
            PolySignalPriceToBeatData,
            PolySignalMarketMetaData,
            PolySignalMarketUniverseData,
        ),
    ):
        return DataBoundaryClassification.VALID_DATA
    if type(data).__name__ == "DataEvent" and getattr(data, "condition_id", None) is not None:
        return DataBoundaryClassification.VALID_DATA
    return DataBoundaryClassification.DROPPED_FRAME


def _book_has_quote_depth(book: object) -> bool:
    if getattr(book, "best_ask", None) is not None:
        return True
    ask_levels = getattr(book, "ask_levels", ()) or ()
    return len(ask_levels) > 0


def _market_view_ready(view: MarketView) -> bool:
    try:
        up_book = view.book_for(Side.UP)
        down_book = view.book_for(Side.DOWN)
    except (AttributeError, ValueError):
        return False
    return _book_has_quote_depth(up_book) and _book_has_quote_depth(down_book)


@dataclass(slots=True)
class MarketSubscriptionState:
    """Track wire subscriptions separately from active-condition membership."""

    wire_condition_ids: set[str] = field(default_factory=set)
    wire_instrument_ids: set[str] = field(default_factory=set)
    pending_metadata_condition_ids: set[str] = field(default_factory=set)
    pending_subscribe_condition_ids: set[str] = field(default_factory=set)
    retained_wire_condition_ids: set[str] = field(default_factory=set)


class _Assembler(Protocol):
    def build(self, condition_id: str) -> MarketView | None: ...


class _Observability(Protocol):
    def record_decision(self, decision: AlphaDecision, accepted: bool) -> None: ...

    def record_rejected_decision(self, rejected: object) -> None: ...

    def record_nautilus_order_event(self, event: object) -> None: ...

    def record_nautilus_fill_event(self, event: object) -> None: ...

    def record_nautilus_position(self, position: object) -> None: ...



def _identity_instrument_id(token_id: str) -> str:
    return token_id


def _nautilus_instrument_id(value: str) -> object:
    try:
        identifiers = import_module("nautilus_trader.model.identifiers")
    except ModuleNotFoundError:
        return value
    instrument_id_cls = cast(object | None, getattr(identifiers, "InstrumentId", None))
    from_str = cast(object | None, getattr(instrument_id_cls, "from_str", None))
    if callable(from_str):
        return cast(Callable[[str], object], from_str)(value)
    return value


def _nautilus_book_type(value: str) -> object:
    try:
        enums = import_module("nautilus_trader.model.enums")
    except ModuleNotFoundError:
        return value
    converter = getattr(enums, "book_type_from_str", None)
    if callable(converter):
        return cast(Callable[[str], object], converter)(value)
    return value


def _nautilus_data_type(value: object) -> object:
    if not isinstance(value, type):
        return value
    try:
        module = import_module("nautilus_trader.model.data")
    except ModuleNotFoundError:
        return value
    data_type_cls = getattr(module, "DataType", None)
    if callable(data_type_cls):
        return cast(Callable[[type[object]], object], data_type_cls)(value)
    return value


def _assembler_with_custom_data(
    assembler: _Assembler,
    custom_data: StrategyCustomDataState,
) -> _Assembler:
    with_custom_data = getattr(assembler, "with_custom_data", None)
    if callable(with_custom_data):
        return cast(_Assembler, with_custom_data(custom_data))
    if hasattr(assembler, "custom_data"):
        setattr(assembler, "custom_data", custom_data)
    return assembler



class PolySignalNativeStrategy:
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
        registry: PolymarketMarketRegistry | None = None,
        observability: _Observability | None = None,
        exit_model: object | None = None,
        progress_callback: Callable[[str], None] | None = None,
        unsubscribe_exited: bool = True,
        l1_book_snapshot_interval_ms: int = DEFAULT_L1_BOOK_SNAPSHOT_INTERVAL_MS,
    ) -> None:
        if registry is None or assembler is None:
            raise RuntimeError(MISSING_PROJECTIONS_ERROR)

        self.core: AlphaCore = core
        self.custom_data: StrategyCustomDataState = StrategyCustomDataState()
        self.assembler: _Assembler = _assembler_with_custom_data(assembler, self.custom_data)
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
        self.registry: PolymarketMarketRegistry | None = registry
        self.observability: _Observability | None = observability
        self.cache_reader: object | None = None
        self.exit_model: object | None = exit_model
        self.progress_callback: Callable[[str], None] | None = progress_callback
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
        self._pending_exit_position_ids: set[str] = set()
        self._last_market_data_evaluation_at: dict[str, datetime] = {}
        self.rejected_decisions: deque[RejectedDecision] = deque(maxlen=1000)
        self.submitted_orders: deque[object] = deque(maxlen=1000)
        self.submitted_specs: deque[object] = deque(maxlen=1000)
        self.execution_results: deque[object] = deque(maxlen=1000)

    def _require_registry(self) -> PolymarketMarketRegistry:
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
        if classify_project_owned_data(data) is DataBoundaryClassification.DROPPED_FRAME:
            self._note_runtime_progress("dropped_frame")
            return
        if isinstance(data, (PolySignalSpotData, PolySignalPriceToBeatData)):
            result = self.custom_data.apply(data)
            if result.spot_asset is not None:
                for candidate in self._asset_condition_ids.get(result.spot_asset, ()):
                    self.evaluate_condition(candidate)
                return
            if result.price_to_beat_condition_id is not None:
                self._retry_market_instrument_requests(
                    (result.price_to_beat_condition_id,), retry_after=timedelta(seconds=10)
                )
                self.evaluate_condition(result.price_to_beat_condition_id)
                return
        if isinstance(data, PolySignalMarketMetaData):
            registry = self._require_registry()
            registry.register(
                _pair_from_metadata(
                    registry,
                    data,
                    instrument_id_resolver=self.instrument_id_resolver,
                )
            )
            self._refresh_asset_conditions()
            if data.condition_id in self._active_condition_ids:
                self._subscribe_market_conditions((data.condition_id,))
            return
        if isinstance(data, PolySignalMarketUniverseData):
            if self._market_epoch is not None and data.epoch <= self._market_epoch:
                return
            self._market_epoch = data.epoch
            self._active_condition_ids = set(data.active_condition_ids)
            self._refresh_asset_conditions()
            for condition_id in data.exited_condition_ids:
                self._subscription_state.pending_metadata_condition_ids.discard(
                    condition_id
                )
                self._subscription_state.pending_subscribe_condition_ids.discard(
                    condition_id
                )
            if self.unsubscribe_exited:
                self._unsubscribe_market_conditions(data.exited_condition_ids)
            self._subscribe_market_conditions(tuple(self._active_condition_ids))
            return
        assembler = self._require_assembler()
        updater = getattr(assembler, "on_data", None) or getattr(
            assembler, "update", None
        )
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
        condition_id = _condition_id_for_instrument(self.registry, instrument_id)
        token_id = _token_id_for_instrument(self.registry, instrument_id)
        if condition_id is None or token_id is None:
            self._note_runtime_progress("dropped_frame")
            return None
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

    def on_order_denied(self, event: object) -> None:
        self._note_runtime_progress("order_event")
        alpha_event = self._order_event(event)
        self._record_nautilus_order(event, alpha_event.metrics)
        self._call_core("on_order_denied", alpha_event)
        self._forget_approved_metrics(event, alpha_event)


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
        position_id = _identifier_text(getattr(position, "id", None))
        if position_id is not None:
            self._pending_exit_position_ids.discard(position_id)

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
        self.evaluate_exit_positions(condition_id, view)

    def evaluate_exit_positions(self, condition_id: str, view: MarketView) -> None:
        cache_reader = getattr(self, "cache_reader", None)
        read_positions = getattr(cache_reader, "read_positions", None)
        if not callable(read_positions):
            return
        rows = read_positions()
        if not isinstance(rows, list):
            return
        raw_config = self.exit_model
        if raw_config is None:
            return
        from polysignal_lab.nautilus_runtime.exit_policy import ExitPolicyConfig, evaluate_exit_decision
        from polysignal_lab.nautilus_runtime.native_exit import submit_exit_decision

        config = ExitPolicyConfig(
            mode=str(getattr(raw_config, "mode", "hold_to_resolution_with_optional_tp_sl")),
            take_profit_enabled=bool(getattr(raw_config, "take_profit_enabled", True)),
            stop_loss_enabled=bool(getattr(raw_config, "stop_loss_enabled", True)),
            take_profit_price=float(getattr(raw_config, "take_profit_price", 0.90)),
            stop_loss_price=float(getattr(raw_config, "stop_loss_price", 0.35)),
            max_hold_time_sec=int(getattr(raw_config, "max_hold_time_sec", 900)),
        )
        now = view.created_at
        registry = self.registry
        for position in rows:
            if not isinstance(position, dict):
                continue
            instrument_id = str(position.get("instrument_id") or "")
            position_condition_id = str(position.get("condition_id") or "")
            if not position_condition_id and registry is not None and instrument_id:
                resolved = _condition_id_for_instrument(registry, instrument_id)
                position_condition_id = resolved or ""
            if position_condition_id != condition_id:
                continue
            token_id = str(position.get("token_id") or "")
            if not token_id and registry is not None and instrument_id:
                resolved = _token_id_for_instrument(registry, instrument_id)
                token_id = resolved or ""
            book = view.up if token_id == view.up.token_id else view.down if token_id == view.down.token_id else None
            if book is None:
                continue
            decision = evaluate_exit_decision(position, book, now, config)
            if decision is None:
                continue
            if decision.position_id in self._pending_exit_position_ids:
                continue
            self._pending_exit_position_ids.add(decision.position_id)
            submit_exit_decision(
                self,
                decision,
                instrument_id_resolver=self._resolved_instrument,
            )

    def _handle_decision(self, decision: AlphaDecision, view: MarketView) -> None:
        if not _market_view_ready(view):
            self._note_runtime_progress("readiness_miss")
            return
        if decision.condition_id not in self._active_condition_ids:
            return
        policy_result = self.policy.evaluate(decision, view)
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
            condition_id = _condition_id_for_instrument(self.registry, instrument_id)
        market_id = tags.get("market_id") or _optional_str(metrics.get("market_id"))
        if not market_id and self.registry is not None and condition_id is not None:
            market_id = _market_id_for_condition(self.registry, condition_id)
        token_id = tags.get("token_id") or _optional_str(metrics.get("token_id"))
        if not token_id and self.registry is not None and instrument_id is not None:
            token_id = _token_id_for_instrument(self.registry, instrument_id)
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


def _value(obj: object, name: str, default: object = None) -> object:
    if isinstance(obj, Mapping):
        return cast(Mapping[object, object], obj).get(name, default)
    return getattr(obj, name, default)


def _tags(raw: object) -> dict[str, str]:
    if isinstance(raw, Mapping):
        return {
            str(key): str(value)
            for key, value in cast(Mapping[object, object], raw).items()
        }
    if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes)):
        return {}
    parsed: dict[str, str] = {}
    for item in raw:
        text = str(item)
        if "=" not in text:
            continue
        key, value = text.split("=", 1)
        parsed[key] = value
    return parsed


def _optional_str(value: object) -> str | None:
    text = _lookup_id_text(value)
    return text


def _lookup_id_text(value: object) -> str | None:
    if value is None:
        return None
    text = _identifier_text(value)
    return None if text in (None, "") else text


def _market_id_for_condition(
    registry: PolymarketMarketRegistry, condition_id: str
) -> str | None:
    pair = registry.by_condition(condition_id)
    return None if pair is None else pair.market_id


def _event_side(
    registry: PolymarketMarketRegistry | None,
    instrument_id: str | None,
    token_id: str | None,
    value: object,
) -> Side:
    if isinstance(value, Side):
        return value
    text = _identifier_text(value)
    if text in {Side.UP.value, Side.DOWN.value}:
        return Side(text)
    if registry is not None and token_id is not None:
        meta = registry.token_meta(token_id)
        if meta is not None:
            return meta.side
    if registry is not None and instrument_id is not None:
        pair = registry.by_instrument(instrument_id)
        if pair is not None:
            if str(pair.up.instrument_id) == instrument_id:
                return pair.up.side
            if str(pair.down.instrument_id) == instrument_id:
                return pair.down.side
    return Side.UP


def _projection_order_event(
    event: object, metrics: Mapping[str, object]
) -> SimpleNamespace:
    return SimpleNamespace(
        client_order_id=_value(event, "client_order_id"),
        instrument_id=_value(event, "instrument_id"),
        order_side=_value(event, "order_side"),
        order_type=_value(event, "order_type"),
        time_in_force=_value(event, "time_in_force"),
        quantity=_value(event, "quantity"),
        price=_value(event, "price"),
        status=_value(event, "status"),
        tags=_value(event, "tags", ()),
        metrics=dict(metrics),
        ts_event=_value(event, "ts_event", _value(event, "timestamp")),
    )


def _projection_fill_event(
    event: object, metrics: Mapping[str, object]
) -> SimpleNamespace:
    return SimpleNamespace(
        client_order_id=_value(event, "client_order_id"),
        instrument_id=_value(event, "instrument_id"),
        trade_id=_value(event, "trade_id", _value(event, "fill_id")),
        last_qty=_value(
            event, "last_qty", _value(event, "shares", _value(event, "quantity"))
        ),
        last_px=_value(
            event, "last_px", _value(event, "fill_price", _value(event, "price"))
        ),
        liquidity_side=_value(event, "liquidity_side"),
        tags=_value(event, "tags", ()),
        metrics=dict(metrics),
        ts_event=_value(event, "ts_event", _value(event, "timestamp")),
    )


def _instrument_ids(
    registry: PolymarketMarketRegistry,
    condition_ids: Sequence[str],
) -> tuple[object, ...]:
    instrument_ids: list[object] = []
    for condition_id in condition_ids:
        pair = registry.by_condition(condition_id)
        if pair is None:
            continue
        instrument_ids.extend(
            (
                _nautilus_instrument_id(str(pair.up.instrument_id)),
                _nautilus_instrument_id(str(pair.down.instrument_id)),
            )
        )
    return tuple(instrument_ids)


def _asset_conditions(
    registry: PolymarketMarketRegistry | None,
    condition_ids: Sequence[str],
) -> dict[str, tuple[str, ...]]:
    if registry is None:
        return {}
    grouped: dict[str, list[str]] = {}
    for condition_id in condition_ids:
        pair = registry.by_condition(condition_id)
        if pair is None:
            continue
        grouped.setdefault(pair.asset.upper(), []).append(condition_id)
    return {asset: tuple(ids) for asset, ids in grouped.items()}


def _identifier_text(value: object) -> str | None:
    if value is None:
        return None
    raw = getattr(value, "value", None)
    text = str(raw if raw is not None else value)
    return text or None


def _condition_id_for_instrument(
    registry: PolymarketMarketRegistry,
    instrument_id: str,
) -> str | None:
    return registry.condition_id_for_instrument(instrument_id)


def _token_id_for_instrument(
    registry: PolymarketMarketRegistry,
    instrument_id: str,
) -> str | None:
    return registry.token_id_for_instrument(instrument_id)






def _maybe_float(value: object) -> float | None:
    if value is None:
        return None
    if callable(value):
        value = value()
    coerced = (
        value if isinstance(value, (int, float, str, bytes, bytearray)) else str(value)
    )
    try:
        return float(coerced)
    except (TypeError, ValueError):
        return None


def _positive_value(source: Mapping[str, object], key: str) -> float | None:
    value = _maybe_float(source.get(key))
    return value if value is not None and value > 0.0 else None


def _fallback_fill_price(
    metrics: Mapping[str, object],
    tags: Mapping[str, object],
    side: Side,
) -> float | None:
    side_key = side.value.lower()
    for key in (
        "fill_price",
        "favorite_price",
        "fav_price",
        f"{side_key}_ask",
        f"{side_key}_last_price",
        "best_ask",
        "current_ask",
        "hedge_price",
        "level_price",
        "bid_price",
        "entry_reference_price",
        "max_entry_price",
    ):
        value = _positive_value(metrics, key) or _positive_value(tags, key)
        if value is not None:
            return value
    return None


def _datetime_or_now(value: object) -> datetime:
    return value if isinstance(value, datetime) else datetime.now(UTC)


def _subscribe_custom_data(
    strategy: object,
    data_type: object,
    *,
    allow_fallback: bool = True,
) -> None:
    mro = type(strategy).mro()
    try:
        base_index = mro.index(PolySignalNativeStrategy) + 1
    except ValueError:
        base_index = -1
    resolved_data_type = _nautilus_data_type(data_type)
    if _subscribe_custom_data_on_bus(strategy, resolved_data_type):
        return
    base_subscribe = (
        getattr(mro[base_index], "subscribe_data", None)
        if 0 <= base_index < len(mro)
        else None
    )
    if callable(base_subscribe):
        _ = base_subscribe(strategy, resolved_data_type)
        return
    if not allow_fallback:
        return
    fallback = getattr(strategy, "subscribe_data", None)
    if callable(fallback):
        _ = fallback(resolved_data_type)


def _subscribe_custom_data_on_bus(strategy: object, data_type: object) -> bool:
    msgbus = getattr(strategy, "msgbus", None)
    if msgbus is None:
        msgbus = getattr(strategy, "_msgbus", None)
    handler = getattr(strategy, "handle_data", None)
    subscribe = getattr(msgbus, "subscribe", None)
    topic_cache = getattr(strategy, "_topic_cache", None)
    topic_getter = getattr(topic_cache, "get_custom_data_topic", None)
    if not callable(topic_getter):
        try:
            topic_module = import_module("nautilus_trader.common.data_topics")
        except ModuleNotFoundError:
            return False
        topic_cache_cls = getattr(topic_module, "TopicCache", None)
        topic_cache = topic_cache_cls() if callable(topic_cache_cls) else None
        topic_getter = getattr(topic_cache, "get_custom_data_topic", None)
    if not callable(subscribe) or not callable(topic_getter) or not callable(handler):
        return False
    _ = subscribe(topic=topic_getter(data_type, None), handler=handler)
    return True


def _datetime_ns(value: int | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1_000_000_000, UTC)


def _metadata_instrument_id(
    condition_id: str,
    token_id: str,
    instrument_id_resolver: Callable[[str], object],
) -> str:
    from polysignal_lab.nautilus_runtime.instrument_mapping import (
        polymarket_instrument_id,
    )

    try:
        resolved = instrument_id_resolver(token_id)
    except (KeyError, TypeError, ValueError):
        return polymarket_instrument_id(condition_id, token_id)
    resolved_text = _identifier_text(resolved)
    if resolved_text is None:
        return polymarket_instrument_id(condition_id, token_id)
    if "." in resolved_text:
        return resolved_text
    return polymarket_instrument_id(condition_id, token_id)


def _pair_from_metadata(
    registry: PolymarketMarketRegistry,
    meta: PolySignalMarketMetaData,
    *,
    instrument_id_resolver: Callable[[str], object],
) -> MarketPairMeta:
    existing = registry.by_condition(meta.condition_id)
    up_instrument_id = (
        existing.up.instrument_id
        if existing is not None
        else _metadata_instrument_id(
            meta.condition_id, meta.up_token_id, instrument_id_resolver
        )
    )
    down_instrument_id = (
        existing.down.instrument_id
        if existing is not None
        else _metadata_instrument_id(
            meta.condition_id, meta.down_token_id, instrument_id_resolver
        )
    )
    return MarketPairMeta(
        market_id=meta.market_id,
        market_slug=meta.market_slug,
        condition_id=meta.condition_id,
        asset=meta.asset.upper(),
        timeframe=meta.timeframe,
        start_ts=_datetime_ns(meta.start_ts_ns),
        end_ts=_datetime_ns(meta.end_ts_ns),
        up=InstrumentTokenMeta(
            instrument_id=up_instrument_id,
            token_id=meta.up_token_id,
            side=Side.UP,
        ),
        down=InstrumentTokenMeta(
            instrument_id=down_instrument_id,
            token_id=meta.down_token_id,
            side=Side.DOWN,
        ),
    )
