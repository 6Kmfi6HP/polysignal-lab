from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from polysignal_lab.alpha.types import (
    AlphaCore,
    AlphaDecision,
    AlphaFillEvent,
    AlphaOrderEvent,
    MarketView,
    NautilusOrderSpec,
)
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_bridge.state import decode_state, encode_state
from polysignal_lab.nautilus_runtime.decision_policy import (
    ApprovedDecision,
    DecisionPolicyActor,
    RejectedDecision,
)
from polysignal_lab.nautilus_runtime.order_mapping import order_spec_from_decision
from polysignal_lab.utils import utc_now

DEFAULT_DATA_NAMES = (
    "order_book_deltas",
    "order_book_depth",
    "spot_prices",
    "price_to_beat",
)

COMPATIBILITY_ONLY = True



class PolySignalNautilusStrategy:
    """Compatibility wrapper for pre-TradingNode tests; default runtime uses PolySignalNativeStrategy."""
    def __init__(
        self,
        *,
        core: AlphaCore,
        assembler: MarketViewAssembler,
        condition_ids: Sequence[str],
        strategy_name: str,
        policy: DecisionPolicyActor | None = None,
        submitter: Callable[[NautilusOrderSpec], object] | None = None,
        fixed_stake_usdc: float = 10.0,
        data_names: Sequence[str] = DEFAULT_DATA_NAMES,
    ) -> None:
        self.core = core
        self.assembler = assembler
        self.condition_ids = tuple(condition_ids)
        self.strategy_name = strategy_name
        self.policy = policy or DecisionPolicyActor()
        self.submitter = submitter
        self.fixed_stake_usdc = fixed_stake_usdc
        self.data_names = tuple(data_names)
        self.subscribed_data_names: list[str] = []
        self.submitted_specs: list[NautilusOrderSpec] = []
        self.rejected_decisions: list[RejectedDecision] = []
        self.execution_results: list[object] = []
        self._last_views: dict[str, MarketView] = {}
        self._locally_accepted_order_ids: set[str] = set()
        self._approved_signal_metrics: dict[str, dict[str, Any]] = {}
        self._consensus_order_ids: set[str] = set()

    def on_start(self) -> None:
        for name in self.data_names:
            self._subscribe_data_name(name)

    def on_data(self, data: object) -> list[NautilusOrderSpec]:
        updater = getattr(self.assembler, "on_data", None) or getattr(
            self.assembler, "update", None
        )
        if callable(updater):
            updater(data)
        condition_id = getattr(data, "condition_id", None)
        if condition_id is not None:
            return self.evaluate_condition(str(condition_id))
        submitted: list[NautilusOrderSpec] = []
        for candidate in self.condition_ids:
            submitted.extend(self.evaluate_condition(candidate))
        return submitted


    def evaluate_condition(self, condition_id: str) -> list[NautilusOrderSpec]:
        view = self.assembler.build(condition_id)
        if view is None:
            return []
        self._last_views[condition_id] = view
        submitted: list[NautilusOrderSpec] = []
        for decision in self.core.evaluate(view):
            policy_result = self.policy.evaluate(decision, view)
            if isinstance(policy_result, ApprovedDecision):
                specs = self.submit_approved(
                    policy_result, decision=decision, view=view
                )
                submitted.extend(specs)
            else:
                self._record_rejected_decision(
                    policy_result, decision=decision, view=view
                )
        return submitted

    def submit_approved(
        self,
        approved: ApprovedDecision,
        *,
        decision: AlphaDecision,
        view: MarketView,
    ) -> list[NautilusOrderSpec]:
        submitted: list[NautilusOrderSpec] = []
        side = approved.signal.side
        book = view.book_for(side)
        best_ask = book.best_ask
        try:
            spec = order_spec_from_decision(
                approved,
                fixed_stake_usdc=self.fixed_stake_usdc,
                best_ask=best_ask,
                available_shares=_visible_ask_shares(
                    book.ask_levels,
                    approved.signal.max_entry_price,
                ),
            )
        except ValueError as exc:
            self._record_rejected_decision(
                RejectedDecision(
                    reason_code="ORDER_MAPPING_FAILED",
                    detail={"error": str(exc)},
                    candidate=approved.signal,
                ),
                decision=decision,
                view=view,
            )
            return []
        self._record_approved_decision(approved, decision=decision, view=view)
        self._submit_spec(spec, submitted)
        if approved.consensus is not None:
            self._submit_consensus_signal(
                approved.consensus, view=view, submitted=submitted
            )
        return submitted

    def on_order_submitted(self, event: Any) -> None:
        alpha_event = self._order_event(event)
        if self._alias_consensus_order_ids(event, alpha_event):
            return
        self._alias_approved_signal_metrics(event, alpha_event)
        self._call_core("on_order_submitted", alpha_event)

    def on_order_accepted(self, event: Any) -> None:
        alpha_event = self._order_event(event)
        if self._alias_consensus_order_ids(event, alpha_event):
            return
        self._alias_approved_signal_metrics(event, alpha_event)
        if any(
            order_id in self._locally_accepted_order_ids
            for order_id in self._event_lookup_ids(event, alpha_event)
        ):
            return
        self._call_core("on_order_accepted", alpha_event)

    def on_order_rejected(self, event: Any) -> None:
        alpha_event = self._order_event(event)
        if self._alias_consensus_order_ids(event, alpha_event):
            return
        self._call_core("on_order_rejected", alpha_event)

    def on_order_canceled(self, event: Any) -> None:
        alpha_event = self._order_event(event)
        if self._alias_consensus_order_ids(event, alpha_event):
            return
        self._call_core("on_order_canceled", alpha_event)

    def on_order_expired(self, event: Any) -> None:
        alpha_event = self._order_event(event)
        if self._alias_consensus_order_ids(event, alpha_event):
            return
        self._call_core("on_order_expired", alpha_event)

    def on_order_filled(self, event: Any) -> list[NautilusOrderSpec]:
        alpha_event = self._fill_event(event)
        if self._alias_consensus_order_ids(event, alpha_event):
            return []
        skip_notify = self.strategy_name == "vwap_momentum" and _is_hedge_or_gtd_fill(
            alpha_event
        )
        if not skip_notify:
            notify = getattr(self.core, "on_notify_fill", None)
            if callable(notify):
                notify(alpha_event.market_id, alpha_event.side, alpha_event.shares)
        handler = getattr(self.core, "on_order_filled", None)
        hedge_decisions = handler(alpha_event) if callable(handler) else []
        if not isinstance(hedge_decisions, Iterable) or isinstance(
            hedge_decisions,
            (str, bytes),
        ):
            hedge_decisions = ()
        if skip_notify:
            return []
        submitted: list[NautilusOrderSpec] = []
        for decision in hedge_decisions:
            view = self._view_for_decision(decision)
            if view is None:
                continue
            policy_result = self.policy.evaluate(decision, view)
            if isinstance(policy_result, ApprovedDecision):
                specs = self.submit_approved(
                    policy_result, decision=decision, view=view
                )
                submitted.extend(specs)
            else:
                self._record_rejected_decision(
                    policy_result, decision=decision, view=view
                )
        return submitted

    def _record_rejected_decision(
        self,
        policy_result: RejectedDecision,
        *,
        decision: AlphaDecision,
        view: MarketView,
    ) -> None:
        candidate = policy_result.candidate
        rollback_id = (
            candidate.signal_id
            if candidate is not None
            else f"policy_rejected:{decision.strategy}:{decision.market_id}:{len(self.rejected_decisions)}"
        )
        self.rejected_decisions.append(policy_result)
        self._bind_core_signal(decision.market_id, rollback_id)
        self._call_core(
            "on_order_rejected",
            self._decision_order_event(
                decision,
                view=view,
                signal=candidate,
                order_id=rollback_id,
                client_order_id=rollback_id,
                reason=policy_result.reason_code,
                metrics=dict(policy_result.detail),
            ),
        )

    def _record_approved_decision(
        self,
        approved: ApprovedDecision,
        *,
        decision: AlphaDecision,
        view: MarketView,
    ) -> None:
        signal_id = approved.signal.signal_id
        approved_metrics = self._approved_metrics(
            approved, decision=decision, view=view
        )
        self._approved_signal_metrics[signal_id] = approved_metrics
        self._locally_accepted_order_ids.add(signal_id)
        self._bind_core_signal(decision.market_id, signal_id)
        self._call_core(
            "on_order_accepted",
            self._decision_order_event(
                decision,
                view=view,
                signal=approved.signal,
                order_id=signal_id,
                client_order_id=signal_id,
                reason=None,
                metrics=approved_metrics,
            ),
        )

    def _submit_consensus_signal(
        self,
        signal: Any,
        *,
        view: MarketView,
        submitted: list[NautilusOrderSpec],
    ) -> None:
        book = view.book_for(signal.side)
        best_ask = book.best_ask
        try:
            spec = order_spec_from_decision(
                signal,
                fixed_stake_usdc=self.fixed_stake_usdc,
                best_ask=best_ask,
                available_shares=_visible_ask_shares(
                    book.ask_levels,
                    signal.max_entry_price,
                ),
            )
        except ValueError as exc:
            self.rejected_decisions.append(
                RejectedDecision(
                    reason_code="CONSENSUS_ORDER_MAPPING_FAILED",
                    detail={"error": str(exc)},
                    candidate=signal,
                )
            )
            return
        self._consensus_order_ids.update(_spec_lookup_ids(spec))
        self._submit_spec(spec, submitted)

    def _submit_spec(
        self, spec: NautilusOrderSpec, submitted: list[NautilusOrderSpec]
    ) -> None:
        self.submitted_specs.append(spec)
        if self.submitter is not None:
            result = self.submitter(spec)
            if result is not None:
                self.execution_results.append(result)
        submitted.append(spec)

    def _approved_metrics(
        self,
        approved: ApprovedDecision,
        *,
        decision: AlphaDecision,
        view: MarketView,
    ) -> dict[str, Any]:
        signal = approved.signal
        metrics = dict(signal.metrics)
        metrics.setdefault("asset", signal.asset)
        metrics.setdefault("timeframe", signal.timeframe)
        metrics.setdefault("market_slug", signal.market_slug)
        metrics.setdefault(
            "condition_id",
            signal.condition_id or view.condition_id or decision.condition_id,
        )
        metrics.setdefault("seconds_to_close", signal.seconds_to_close)
        metrics["hedge_leg"] = bool(signal.hedge_leg)
        if signal.order_intent is not None:
            metrics["order_intent"] = signal.order_intent.value
        if signal.expiry_seconds is not None:
            metrics["expiry_seconds"] = signal.expiry_seconds
        if signal.pair_id is not None:
            metrics["pair_id"] = signal.pair_id
        metrics.setdefault("signal_confidence", signal.confidence)
        return metrics

    def _alias_approved_signal_metrics(
        self, event: Any, order: AlphaOrderEvent
    ) -> None:
        lookup_ids = self._event_lookup_ids(event, order)
        metrics = self._approved_metrics_for_event(event, order)
        if not metrics:
            return
        aliases_locally_accepted = any(
            key in self._locally_accepted_order_ids for key in lookup_ids
        )
        for key in lookup_ids:
            self._approved_signal_metrics.setdefault(key, dict(metrics))
        if aliases_locally_accepted:
            self._locally_accepted_order_ids.update(lookup_ids)

    def _alias_consensus_order_ids(self, event: Any, order: AlphaOrderEvent) -> bool:
        lookup_ids = self._event_lookup_ids(event, order)
        if _event_strategy(event) == "consensus" or any(
            key in self._consensus_order_ids for key in lookup_ids
        ):
            self._consensus_order_ids.update(lookup_ids)
            return True
        return False

    def _approved_metrics_for_event(
        self, event: Any, order: AlphaOrderEvent
    ) -> Mapping[str, Any]:
        for key in self._event_lookup_ids(event, order):
            metrics = self._approved_signal_metrics.get(key)
            if metrics is not None:
                return metrics
        return {}

    def _event_lookup_ids(self, event: Any, order: AlphaOrderEvent) -> tuple[str, ...]:
        values = [
            order.order_id,
            order.client_order_id,
            _first_attr(event, "id", default=None),
        ]
        tags = _first_attr(event, "tags", default=None)
        if isinstance(tags, Mapping):
            values.extend(
                tags.get(key) for key in ("signal_id", "order_id", "client_order_id")
            )
        return tuple(str(value) for value in values if value not in (None, ""))

    def _bind_core_signal(self, market_id: str, signal_id: str) -> None:
        binder = getattr(self.core, "bind_signal", None)
        if callable(binder):
            binder(market_id, signal_id)

    def _decision_order_event(
        self,
        decision: AlphaDecision,
        *,
        view: MarketView,
        signal: Any,
        order_id: str,
        client_order_id: str | None,
        reason: str | None,
        metrics: Mapping[str, Any],
    ) -> AlphaOrderEvent:
        return AlphaOrderEvent(
            strategy=decision.strategy,
            market_id=decision.market_id,
            condition_id=view.condition_id,
            token_id=str(getattr(signal, "token_id", decision.token_id)),
            side=_side(getattr(signal, "side", decision.side)),
            order_id=order_id,
            client_order_id=client_order_id,
            reason=reason,
            ts_event=view.created_at,
            metrics=metrics,
        )

    def on_save(self) -> dict[str, bytes]:
        saver = getattr(self.core, "save_state", None)
        raw_payload = saver() if callable(saver) else {}
        payload = (
            {str(key): value for key, value in raw_payload.items()}
            if isinstance(raw_payload, Mapping)
            else {}
        )
        return encode_state(self.strategy_name, payload)

    def on_load(self, state: Mapping[str, bytes]) -> None:
        payload = decode_state(self.strategy_name, state)
        loader = getattr(self.core, "load_state", None)
        if callable(loader):
            loader(payload)

    def _subscribe_data_name(self, name: str) -> None:
        self.subscribed_data_names.append(name)
        method = getattr(self, f"subscribe_{name}", None)
        if callable(method):
            for condition_id in self.condition_ids:
                method(condition_id)

    def _view_for_decision(self, decision: AlphaDecision) -> MarketView | None:
        view = self._last_views.get(decision.condition_id)
        if view is not None:
            return view
        view = self.assembler.build(decision.condition_id)
        if view is not None:
            self._last_views[decision.condition_id] = view
        return view

    def _call_core(self, method_name: str, event: AlphaOrderEvent) -> None:
        handler = getattr(self.core, method_name, None)
        if callable(handler):
            handler(event)

    def _order_event(self, event: Any) -> AlphaOrderEvent:
        return AlphaOrderEvent(
            strategy=self.strategy_name,
            market_id=str(_first_attr(event, "market_id", default="")),
            condition_id=str(_first_attr(event, "condition_id", default="")),
            token_id=str(_first_attr(event, "token_id", "instrument_id", default="")),
            side=_side(_first_attr(event, "side", default=Side.UP)),
            order_id=str(_first_attr(event, "order_id", "id", default="")),
            client_order_id=_optional_str(
                _first_attr(event, "client_order_id", default=None)
            ),
            reason=_optional_str(_first_attr(event, "reason", default=None)),
            ts_event=_timestamp(
                _first_attr(event, "ts_event", "timestamp", default=None)
            ),
            metrics=dict(_first_attr(event, "metrics", default={}) or {}),
        )

    def _fill_event(self, event: Any) -> AlphaFillEvent:
        order = self._order_event(event)
        metrics = dict(self._approved_metrics_for_event(event, order))
        metrics.update(order.metrics)
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
            fill_price=float(
                _first_attr(event, "fill_price", "price", default=0.0) or 0.0
            ),
            shares=float(
                _first_attr(event, "shares", "quantity", "filled_qty", default=0.0)
                or 0.0
            ),
            liquidity_side=_optional_str(
                _first_attr(event, "liquidity_side", default=None)
            ),
        )


def _visible_ask_shares(
    levels: Sequence[tuple[float, float]], limit_price: float | None
) -> float | None:
    if not levels or limit_price is None:
        return None
    return sum(float(size) for price, size in levels if float(price) <= limit_price)


def _first_attr(obj: Any, *names: str, default: Any) -> Any:
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default

def _event_strategy(event: Any) -> str | None:
    tags = _first_attr(event, "tags", default=None)
    if isinstance(tags, Mapping) and tags.get("strategy"):
        return str(tags["strategy"])
    strategy = _first_attr(event, "strategy", default=None)
    return None if strategy is None else str(strategy)


def _spec_lookup_ids(spec: NautilusOrderSpec) -> tuple[str, ...]:
    return tuple(
        str(value)
        for value in (
            spec.tags.get("signal_id"),
            spec.tags.get("order_id"),
            spec.tags.get("client_order_id"),
        )
        if value not in (None, "")
    )


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _side(value: Any) -> Side:
    return value if isinstance(value, Side) else Side(str(value))


def _timestamp(value: Any) -> datetime:
    return value if isinstance(value, datetime) else utc_now()


def _is_hedge_or_gtd_fill(event: AlphaFillEvent) -> bool:
    intent = event.metrics.get("order_intent")
    if isinstance(intent, OrderIntent):
        intent = intent.value
    return (
        bool(event.metrics.get("hedge_leg")) or intent == OrderIntent.PASSIVE_GTD.value
    )
