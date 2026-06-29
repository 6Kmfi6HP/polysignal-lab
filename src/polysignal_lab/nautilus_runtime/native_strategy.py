from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import import_module
from types import SimpleNamespace, new_class
from typing import Protocol, cast

from polysignal_lab.alpha.types import (
    AlphaCore,
    AlphaDecision,
    AlphaFillEvent,
    AlphaOrderEvent,
    MarketView,
    SpotView,
)
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.orderbook import BookLevel, OrderBook
from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
from polysignal_lab.nautilus_bridge.market_registry import (
    InstrumentTokenMeta,
    MarketPairMeta,
    PolymarketMarketRegistry,
)
from polysignal_lab.nautilus_runtime.market_data import (
    PolySignalMarketMetaData,
    PolySignalMarketUniverseData,
    PolySignalPriceToBeatData,
    PolySignalSpotData,
)
from polysignal_lab.nautilus_runtime.decision_policy import (
    ApprovedDecision,
    DecisionPolicyActor,
    RejectedDecision,
)
from polysignal_lab.nautilus_runtime.native_order import (
    OrderSubmittingStrategy,
    submit_approved_decision,
)

DEFAULT_NATIVE_DATA_NAMES = ("quote_ticks", "trade_ticks", "order_book_deltas")
MISSING_PROJECTIONS_ERROR = (
    "PolySignalNativeStrategy requires injected registry, sidecar, and assembler projections"
)


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

    def notify_nautilus_paper_fill(self, payload: dict[str, object]) -> None: ...
    def mirror_nautilus_paper_fill(self, payload: dict[str, object]) -> None: ...


def _identity_instrument_id(token_id: str) -> str:
    return token_id

def _nautilus_instrument_id(value: str) -> object:
    try:
        identifiers = import_module("nautilus_trader.model.identifiers")
    except ModuleNotFoundError:
        return value
    instrument_id_cls = getattr(identifiers, "InstrumentId", None)
    from_str = getattr(instrument_id_cls, "from_str", None) if instrument_id_cls is not None else None
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



def runtime_native_strategy_type(
    nautilus_base: type[object] | None,
    config_factory: Callable[[], object] | None,
) -> type["PolySignalNativeStrategy"]:
    if nautilus_base is None:
        return PolySignalNativeStrategy

    def exec_body(namespace: dict[str, object]) -> None:
        def __init__(
            self: PolySignalNativeStrategy,
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
            sidecar: ExternalDataSidecar | None = None,
            observability: _Observability | None = None,
            unsubscribe_exited: bool = True,
        ) -> None:
            base_init = cast(Callable[..., None], nautilus_base.__init__)
            if config_factory is None:
                base_init(self)
            else:
                base_init(self, config=config_factory())
            PolySignalNativeStrategy.__init__(
                self,
                core=core,
                assembler=assembler,
                condition_ids=condition_ids,
                strategy_name=strategy_name,
                policy=policy,
                fixed_stake_usdc=fixed_stake_usdc,
                data_names=data_names,
                book_type=book_type,
                instrument_id_resolver=instrument_id_resolver,
                registry=registry,
                sidecar=sidecar,
                observability=observability,
                unsubscribe_exited=unsubscribe_exited,
            )

        namespace["__init__"] = __init__

    strategy_cls = new_class(
        "NautilusPolySignalNativeStrategy",
        (PolySignalNativeStrategy, nautilus_base),
        exec_body=exec_body,
    )
    return cast(type[PolySignalNativeStrategy], strategy_cls)


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
        sidecar: ExternalDataSidecar | None = None,
        observability: _Observability | None = None,
        unsubscribe_exited: bool = True,
    ) -> None:
        if registry is None or sidecar is None or assembler is None:
            raise RuntimeError(MISSING_PROJECTIONS_ERROR)

        self.core: AlphaCore = core
        self.assembler: _Assembler = assembler
        self.condition_ids: tuple[str, ...] = tuple(condition_ids)
        self.strategy_name: str = strategy_name
        self.policy: DecisionPolicyActor = policy or DecisionPolicyActor()
        self.fixed_stake_usdc: float = fixed_stake_usdc
        self.data_names: tuple[str, ...] = tuple(data_names)
        self.book_type: str = book_type
        self.instrument_id_resolver: Callable[[str], object] = (
            instrument_id_resolver or _identity_instrument_id
        )
        self.registry: PolymarketMarketRegistry | None = registry
        self.sidecar: ExternalDataSidecar | None = sidecar
        self.observability: _Observability | None = observability
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
        self.rejected_decisions: list[RejectedDecision] = []
        self.submitted_orders: list[object] = []
        self.submitted_specs: list[object] = []
        self.execution_results: list[object] = []

    def _require_registry(self) -> PolymarketMarketRegistry:
        if self.registry is None:
            raise RuntimeError(MISSING_PROJECTIONS_ERROR)
        return self.registry

    def _require_sidecar(self) -> ExternalDataSidecar:
        if self.sidecar is None:
            raise RuntimeError(MISSING_PROJECTIONS_ERROR)
        return self.sidecar

    def _require_assembler(self) -> _Assembler:
        return self.assembler


    def on_start(self) -> None:
        _ = self._require_registry()
        _ = self._require_sidecar()
        _ = self._require_assembler()
        self._subscribe_market_conditions(self._startup_condition_ids)
        _subscribe_custom_data(self, PolySignalSpotData)
        _subscribe_custom_data(self, PolySignalPriceToBeatData)
        _subscribe_custom_data(self, PolySignalMarketMetaData)
        _subscribe_custom_data(self, PolySignalMarketUniverseData)

    def on_data(self, data: object) -> None:
        if isinstance(data, PolySignalSpotData):
            sidecar = self._require_sidecar()
            sidecar.update_spot(
                SpotView(
                    asset=data.asset,
                    symbol=data.symbol,
                    price=data.price,
                    source=data.source,
                    freshness_ms=data.freshness_ms,
                )
            )
            for candidate in self._asset_condition_ids.get(data.asset.upper(), ()):
                self.evaluate_condition(candidate)
            return
        if isinstance(data, PolySignalPriceToBeatData):
            sidecar = self._require_sidecar()
            sidecar.update_price_to_beat(
                condition_id=data.condition_id,
                value=data.value,
                source=data.source,
                verified=data.verified,
                from_anchor_service=data.from_anchor_service,
                anchor_source=data.anchor_source,
                anchor_lag_ms=data.anchor_lag_ms,
            )
            self.evaluate_condition(data.condition_id)
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
        if self.registry is None:
            return
        instrument_id_value = getattr(deltas, "instrument_id", None)
        instrument_id = _identifier_text(instrument_id_value)
        if instrument_id is None:
            return
        token_id = _token_id_for_instrument(self.registry, instrument_id)
        condition_id = _condition_id_for_instrument(self.registry, instrument_id)
        if token_id is None or condition_id is None:
            return
        cache = cast(object, getattr(self, "cache", None))
        order_book = _cache_order_book(cache, instrument_id_value)
        if order_book is None:
            return
        books = getattr(self._require_assembler(), "books", None)
        updater = getattr(books, "update_book", None)
        if callable(updater):
            _ = updater(token_id, _domain_order_book(token_id, order_book))
        self.evaluate_condition(condition_id)

    def on_trade_tick(self, tick: object) -> None:
        if self.registry is None:
            return
        instrument_id = _identifier_text(getattr(tick, "instrument_id", None))
        if instrument_id is None:
            return
        token_id = _token_id_for_instrument(self.registry, instrument_id)
        condition_id = _condition_id_for_instrument(self.registry, instrument_id)
        if token_id is None or condition_id is None:
            return
        books = getattr(self._require_assembler(), "books", None)
        updater = getattr(books, "update_trade", None)
        if callable(updater):
            _ = updater(
                token_id,
                price=float(getattr(tick, "price")),
                size=float(getattr(tick, "size")),
                side=_identifier_text(getattr(tick, "aggressor_side", None)),
                ts=_maybe_datetime(getattr(tick, "ts_event", None)),
            )
        self.evaluate_condition(condition_id)

    def on_order_submitted(self, event: object) -> None:
        alpha_event = self._order_event(event)
        self._record_nautilus_order(event, alpha_event.metrics)
        self._call_core("on_order_submitted", alpha_event)

    def on_order_accepted(self, event: object) -> None:
        alpha_event = self._order_event(event)
        self._record_nautilus_order(event, alpha_event.metrics)
        self._call_core("on_order_accepted", alpha_event)

    def on_order_rejected(self, event: object) -> None:
        alpha_event = self._order_event(event)
        self._record_nautilus_order(event, alpha_event.metrics)
        self._call_core("on_order_rejected", alpha_event)
        self._forget_approved_metrics(event, alpha_event)

    def on_order_canceled(self, event: object) -> None:
        alpha_event = self._order_event(event)
        self._record_nautilus_order(event, alpha_event.metrics)
        self._call_core("on_order_canceled", alpha_event)
        self._forget_approved_metrics(event, alpha_event)

    def on_order_expired(self, event: object) -> None:
        alpha_event = self._order_event(event)
        self._record_nautilus_order(event, alpha_event.metrics)
        self._call_core("on_order_expired", alpha_event)
        self._forget_approved_metrics(event, alpha_event)

    def on_order_filled(self, event: object) -> None:
        alpha_event = self._fill_event(event)
        should_notify = self._should_notify_fill(alpha_event)
        if should_notify:
            notify = getattr(self.core, "on_notify_fill", None)
            if callable(notify):
                notify(alpha_event.market_id, alpha_event.side, alpha_event.shares)
        self._record_nautilus_fill(event, alpha_event.metrics)
        payload = self._nautilus_paper_fill_payload(event, alpha_event)
        self._mirror_nautilus_paper_fill(payload)
        if should_notify:
            self._notify_nautilus_paper_fill(payload)
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
        for decision in self.core.evaluate(view):
            self._handle_decision(decision, view)

    def _handle_decision(self, decision: AlphaDecision, view: MarketView) -> None:
        if decision.condition_id not in self._active_condition_ids:
            return
        policy_result = self.policy.evaluate(decision, view)
        if isinstance(policy_result, ApprovedDecision):
            try:
                order = self._submit_approved(policy_result, view=view)
            except ValueError as exc:
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
            self._record_decision(decision, accepted=True)
            return
        self.rejected_decisions.append(policy_result)
        self._record_decision(decision, accepted=False)
        self._record_rejected(policy_result)

    def _submit_approved(self, approved: ApprovedDecision, *, view: MarketView) -> object:
        signal = approved.signal
        book = view.book_for(signal.side)
        # Subclasses supplied by Nautilus/tests provide the native submit surface.
        return submit_approved_decision(
            cast(OrderSubmittingStrategy[object], cast(object, self)),
            approved,
            fixed_stake_usdc=self.fixed_stake_usdc,
            best_ask=book.best_ask,
            available_shares=_visible_ask_shares(book.ask_levels, signal.max_entry_price),
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
            handler(event)

    def _record_decision(self, decision: AlphaDecision, *, accepted: bool) -> None:
        if self.observability is not None:
            self.observability.record_decision(decision, accepted)

    def _record_rejected(self, rejected: object) -> None:
        if self.observability is not None:
            self.observability.record_rejected_decision(rejected)

    def _record_nautilus_order(
        self, event: object, metrics: Mapping[str, object]
    ) -> None:
        if self.observability is None:
            return
        self.observability.record_nautilus_order_event(
            _projection_order_event(event, metrics)
        )

    def _record_nautilus_fill(
        self, event: object, metrics: Mapping[str, object]
    ) -> None:
        if self.observability is None:
            return
        self.observability.record_nautilus_fill_event(
            _projection_fill_event(event, metrics)
        )

    def _record_nautilus_position(self, position: object) -> None:
        if self.observability is not None:
            self.observability.record_nautilus_position(position)

    def _nautilus_paper_fill_payload(
        self,
        event: object,
        fill: AlphaFillEvent,
    ) -> dict[str, object]:
        tags = _tags(_value(event, "tags", ()))
        pair = self.registry.by_condition(fill.condition_id) if self.registry is not None else None
        return {
            "strategy": fill.strategy,
            "asset": "" if pair is None else pair.asset,
            "timeframe": "" if pair is None else pair.timeframe,
            "market_id": fill.market_id or ("" if pair is None else pair.market_id),
            "market_slug": "" if pair is None else pair.market_slug,
            "condition_id": fill.condition_id,
            "token_id": fill.token_id,
            "side": fill.side.value,
            "fill_price": fill.fill_price,
            "shares": fill.shares,
            "stake_usdc": fill.fill_price * fill.shares,
            "signal_id": tags.get("signal_id", ""),
            "order_id": fill.order_id,
            "client_order_id": fill.client_order_id or fill.order_id,
            "paper_fill_id": _lookup_id_text(
                _value(event, "trade_id", _value(event, "fill_id"))
            ) or "",
            "liquidity_side": fill.liquidity_side or "",
            "metrics": dict(fill.metrics),
        }

    def _notify_nautilus_paper_fill(self, payload: dict[str, object]) -> None:
        if self.observability is None:
            return
        notifier = getattr(self.observability, "notify_nautilus_paper_fill", None)
        if callable(notifier):
            notifier(dict(payload))

    def _mirror_nautilus_paper_fill(self, payload: dict[str, object]) -> None:
        if self.observability is None:
            return
        mirror = getattr(self.observability, "mirror_nautilus_paper_fill", None)
        if callable(mirror):
            mirror(dict(payload))
    def _order_event(self, event: object) -> AlphaOrderEvent:
        tags = _tags(_value(event, "tags"))
        instrument_id = _identifier_text(_value(event, "instrument_id"))
        condition_id = tags.get("condition_id")
        if not condition_id and self.registry is not None and instrument_id is not None:
            condition_id = _condition_id_for_instrument(self.registry, instrument_id)
        market_id = tags.get("market_id")
        if not market_id and self.registry is not None and condition_id is not None:
            market_id = _market_id_for_condition(self.registry, condition_id)
        token_id = tags.get("token_id")
        if not token_id and self.registry is not None and instrument_id is not None:
            token_id = _token_id_for_instrument(self.registry, instrument_id)
        metrics = self._approved_metrics_for_event(event)
        price = _maybe_float(_value(event, "price"))
        if "level_price" not in metrics and price is not None:
            metrics["level_price"] = price
        if "order_intent" not in metrics and tags.get("order_intent"):
            metrics["order_intent"] = tags["order_intent"]
        if "hedge_leg" not in metrics and tags.get("hedge_leg"):
            metrics["hedge_leg"] = tags["hedge_leg"] == "true"
        return AlphaOrderEvent(
            strategy=tags.get("strategy", self.strategy_name),
            market_id=market_id or str(_value(event, "market_id", "")),
            condition_id=condition_id or str(_value(event, "condition_id", "")),
            token_id=token_id or str(_value(event, "token_id", instrument_id or "")),
            side=_event_side(self.registry, instrument_id, token_id, _value(event, "side")),
            order_id=str(_value(event, "order_id", _value(event, "id", ""))),
            client_order_id=_optional_str(_value(event, "client_order_id")),
            reason=_optional_str(_value(event, "reason")),
            ts_event=_datetime_or_now(_value(event, "ts_event", _value(event, "timestamp"))),
            metrics=metrics,
        )

    def _fill_event(self, event: object) -> AlphaFillEvent:
        order = self._order_event(event)
        metrics = dict(order.metrics)
        fill_price = _maybe_float(
            _value(event, "fill_price", _value(event, "last_px", _value(event, "price")))
        )
        if fill_price is not None:
            metrics.setdefault("fill_price", fill_price)
        shares = _maybe_float(
            _value(event, "shares", _value(event, "last_qty", _value(event, "quantity")))
        ) or 0.0
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
        metrics = dict(getattr(approved.signal, "metrics", {}) or {})
        tags = _tags(_value(order, "tags"))
        values = (
            _value(order, "id"),
            _value(order, "client_order_id"),
            getattr(approved.signal, "signal_id", None),
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
            self._approved_signal_metrics.pop(key, None)

    def _refresh_asset_conditions(self) -> None:
        tracked_condition_ids = tuple(
            dict.fromkeys((*self._startup_condition_ids, *self._active_condition_ids))
        )
        self._asset_condition_ids = _asset_conditions(self.registry, tracked_condition_ids)

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
            for instrument_id in instrument_ids:
                subscribed = self._subscribe_market_instrument(instrument_id) and subscribed
            if not subscribed:
                self._subscription_state.pending_subscribe_condition_ids.add(
                    condition_id
                )
                continue
            self._subscription_state.pending_subscribe_condition_ids.discard(
                condition_id
            )
            self._subscription_state.retained_wire_condition_ids.discard(condition_id)
            self._subscription_state.wire_condition_ids.add(condition_id)

    def _subscribe_market_instrument(self, instrument_id: object) -> bool:
        instrument_text = _identifier_text(instrument_id)
        if instrument_text is None:
            return False
        if instrument_text in self._subscription_state.wire_instrument_ids:
            return True
        subscribe_order_book_deltas = getattr(self, "subscribe_order_book_deltas", None)
        subscribe_trade_ticks = getattr(self, "subscribe_trade_ticks", None)
        if not callable(subscribe_order_book_deltas) or not callable(
            subscribe_trade_ticks
        ):
            return False
        _ = subscribe_order_book_deltas(
            instrument_id=instrument_id,
            book_type=_nautilus_book_type(self.book_type),
        )
        _ = subscribe_trade_ticks(instrument_id)
        self._subscription_state.wire_instrument_ids.add(instrument_text)
        return True

    def _unsubscribe_market_conditions(self, condition_ids: Sequence[str]) -> None:
        if self.registry is None:
            return
        for condition_id in condition_ids:
            self._subscription_state.pending_metadata_condition_ids.discard(
                condition_id
            )
            self._subscription_state.pending_subscribe_condition_ids.discard(
                condition_id
            )
            if condition_id not in self._subscription_state.wire_condition_ids:
                self._subscription_state.retained_wire_condition_ids.discard(
                    condition_id
                )
                continue
            instrument_ids = _instrument_ids(self.registry, (condition_id,))
            if not instrument_ids:
                self._subscription_state.retained_wire_condition_ids.add(
                    condition_id
                )
                continue
            unsubscribed = True
            for instrument_id in instrument_ids:
                unsubscribed = self._unsubscribe_market_instrument(
                    instrument_id
                ) and unsubscribed
            if not unsubscribed:
                self._subscription_state.retained_wire_condition_ids.add(
                    condition_id
                )
                continue
            self._subscription_state.retained_wire_condition_ids.discard(condition_id)
            self._subscription_state.wire_condition_ids.discard(condition_id)

    def _unsubscribe_market_instrument(self, instrument_id: object) -> bool:
        instrument_text = _identifier_text(instrument_id)
        if instrument_text is None:
            return False
        if instrument_text not in self._subscription_state.wire_instrument_ids:
            return True
        unsubscribe_order_book_deltas = getattr(
            self, "unsubscribe_order_book_deltas", None
        )
        unsubscribe_trade_ticks = getattr(self, "unsubscribe_trade_ticks", None)
        if not callable(unsubscribe_order_book_deltas) or not callable(
            unsubscribe_trade_ticks
        ):
            return False
        _ = unsubscribe_order_book_deltas(instrument_id)
        _ = unsubscribe_trade_ticks(instrument_id)
        self._subscription_state.wire_instrument_ids.discard(instrument_text)
        return True

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
        for condition_id in registry._by_condition:
            pair = registry.by_condition(condition_id)
            if pair is None:
                continue
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
        last_qty=_value(event, "last_qty", _value(event, "shares", _value(event, "quantity"))),
        last_px=_value(event, "last_px", _value(event, "fill_price", _value(event, "price"))),
        liquidity_side=_value(event, "liquidity_side"),
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
def _visible_ask_shares(levels: Sequence[tuple[float, float]], limit_price: float | None) -> float | None:
    if not levels or limit_price is None:
        return None
    return sum(float(size) for price, size in levels if float(price) <= limit_price)


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
    for condition_id in registry._by_condition:
        pair = registry.by_condition(condition_id)
        if pair is None:
            continue
        if str(pair.up.instrument_id) == instrument_id or str(pair.down.instrument_id) == instrument_id:
            return pair.condition_id
    return None


def _token_id_for_instrument(
    registry: PolymarketMarketRegistry,
    instrument_id: str,
) -> str | None:
    for condition_id in registry._by_condition:
        pair = registry.by_condition(condition_id)
        if pair is None:
            continue
        if str(pair.up.instrument_id) == instrument_id:
            return pair.up.token_id
        if str(pair.down.instrument_id) == instrument_id:
            return pair.down.token_id
    return None


def _cache_order_book(cache: object, instrument_id: object) -> object | None:
    getter = getattr(cache, "order_book", None)
    if not callable(getter):
        return None
    return cast(Callable[[object], object | None], getter)(instrument_id)


def _domain_order_book(token_id: str, book: object) -> OrderBook:
    raw_bids = getattr(book, "bids", [])
    if callable(raw_bids):
        raw_bids = raw_bids()
    raw_asks = getattr(book, "asks", [])
    if callable(raw_asks):
        raw_asks = raw_asks()
    bids = [
        BookLevel(price=_float_attr(level, "price"), size=_float_attr(level, "size"))
        for level in cast(list[object], raw_bids or [])
    ]
    asks = [
        BookLevel(price=_float_attr(level, "price"), size=_float_attr(level, "size"))
        for level in cast(list[object], raw_asks or [])
    ]
    return OrderBook(
        token_id=token_id,
        bids=bids,
        asks=asks,
        last_trade_price=_maybe_float(getattr(book, "last_trade_price", None)),
        last_trade_size=_maybe_float(getattr(book, "last_trade_size", None)),
        last_trade_timestamp=str(getattr(book, "last_trade_timestamp", "") or "") or None,
        received_at=_datetime_or_now(getattr(book, "received_at", None)),
    )


def _maybe_datetime(value: object) -> datetime | None:
    return value if isinstance(value, datetime) else None

def _float_attr(source: object, name: str) -> float:
    value = getattr(source, name)
    if callable(value):
        value = value()
    return float(value if isinstance(value, (int, float, str, bytes, bytearray)) else str(value))


def _maybe_float(value: object) -> float | None:
    if value is None:
        return None
    if callable(value):
        value = value()
    coerced = (
        value
        if isinstance(value, (int, float, str, bytes, bytearray))
        else str(value)
    )
    try:
        return float(coerced)
    except (TypeError, ValueError):
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
    subscribe(topic=topic_getter(data_type, None), handler=handler)
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
    from polysignal_lab.nautilus_runtime.instrument_mapping import polymarket_instrument_id

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
        else _metadata_instrument_id(meta.condition_id, meta.up_token_id, instrument_id_resolver)
    )
    down_instrument_id = (
        existing.down.instrument_id
        if existing is not None
        else _metadata_instrument_id(meta.condition_id, meta.down_token_id, instrument_id_resolver)
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
