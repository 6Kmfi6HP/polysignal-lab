"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Callable, collections.abc.Iterable, collections.abc.Mapping, typing, typing.Protocol, typing.cast, polysignal_lab.alpha.types, polysignal_lab.domain.enums, polysignal_lab.nautilus_bridge.market_catalog, polysignal_lab.nautilus_runtime.strategy.event_projection
Output: handle_order_lifecycle_event, handle_order_filled, handle_position_event, project_strategy_order_event, project_strategy_fill_event, should_notify_fill, forget_approved_metrics, call_core
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Protocol, cast

from polysignal_lab.alpha.types import (
    AlphaDecision,
    AlphaFillEvent,
    AlphaOrderEvent,
    MarketView,
)
from polysignal_lab.domain.enums import OrderIntent
from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.strategy.event_projection import (
    project_fill_event,
    project_order_event,
)


class _OrderEventStrategy(Protocol):
    core: object
    registry: MarketCatalog | None
    strategy_name: str
    _active_condition_ids: set[str]
    _metrics_tracker: object

    def _note_runtime_progress(self, phase: str) -> None: ...
    def _record_nautilus_order(
        self, event: object, metrics: Mapping[str, object]
    ) -> None: ...
    def _record_nautilus_fill(
        self, event: object, metrics: Mapping[str, object]
    ) -> None: ...
    def _record_nautilus_position(self, position: object) -> None: ...
    def _require_assembler(self) -> object: ...
    def _handle_decision(self, decision: AlphaDecision, view: MarketView) -> None: ...


def call_core(strategy: _OrderEventStrategy, method_name: str, event: AlphaOrderEvent) -> None:
    handler = getattr(strategy.core, method_name, None)
    if callable(handler):
        _ = handler(event)


def project_strategy_order_event(
    strategy: _OrderEventStrategy, event: object
) -> AlphaOrderEvent:
    metrics_lookup = cast(
        Callable[[object], Mapping[str, object]],
        strategy._metrics_tracker.metrics_for_event,  # type: ignore[attr-defined]
    )
    return project_order_event(
        event,
        registry=strategy.registry,
        strategy_name=strategy.strategy_name,
        metrics_lookup=metrics_lookup,
    )


def project_strategy_fill_event(
    strategy: _OrderEventStrategy, event: object
) -> AlphaFillEvent:
    metrics_lookup = cast(
        Callable[[object], Mapping[str, object]],
        strategy._metrics_tracker.metrics_for_event,  # type: ignore[attr-defined]
    )
    return project_fill_event(
        event,
        registry=strategy.registry,
        strategy_name=strategy.strategy_name,
        metrics_lookup=metrics_lookup,
    )


def should_notify_fill(strategy: _OrderEventStrategy, event: AlphaFillEvent) -> bool:
    if strategy.strategy_name != "vwap_momentum":
        return True
    intent = event.metrics.get("order_intent")
    if isinstance(intent, OrderIntent):
        intent = intent.value
    return not (
        bool(event.metrics.get("hedge_leg"))
        or intent == OrderIntent.PASSIVE_GTD.value
    )


def forget_approved_metrics(
    strategy: _OrderEventStrategy,
    event: object,
    order: AlphaOrderEvent,
) -> None:
    forget = cast(Callable[[object, AlphaOrderEvent], None], strategy._metrics_tracker.forget)  # type: ignore[attr-defined]
    forget(event, order)


def handle_order_lifecycle_event(
    strategy: _OrderEventStrategy,
    method_name: str,
    event: object,
    *,
    forget_metrics: bool = False,
) -> None:
    strategy._note_runtime_progress("order_event")
    alpha_event = project_strategy_order_event(strategy, event)
    strategy._record_nautilus_order(event, alpha_event.metrics)
    call_core(strategy, method_name, alpha_event)
    if forget_metrics:
        forget_approved_metrics(
            strategy,
            event,
            cast(AlphaOrderEvent, cast(object, alpha_event)),
        )


def handle_order_filled(strategy: _OrderEventStrategy, event: object) -> None:
    strategy._note_runtime_progress("order_event")
    alpha_event = project_strategy_fill_event(strategy, event)
    if should_notify_fill(strategy, alpha_event):
        notify = getattr(strategy.core, "on_notify_fill", None)
        if callable(notify):
            _ = notify(alpha_event.market_id, alpha_event.side, alpha_event.shares)
    strategy._record_nautilus_fill(event, alpha_event.metrics)
    forget_approved_metrics(
        strategy,
        event,
        cast(AlphaOrderEvent, cast(object, alpha_event)),
    )
    handler = getattr(strategy.core, "on_order_filled", None)
    decisions = handler(alpha_event) if callable(handler) else ()
    if isinstance(decisions, Iterable) and not isinstance(decisions, (str, bytes)):
        for decision in cast(Iterable[AlphaDecision], decisions):
            if decision.condition_id not in strategy._active_condition_ids:
                continue
            view = strategy._require_assembler().build(decision.condition_id)  # type: ignore[attr-defined]
            if view is None:
                continue
            strategy._handle_decision(decision, cast(MarketView, view))


def handle_position_event(strategy: _OrderEventStrategy, position: object) -> None:
    strategy._record_nautilus_position(position)
