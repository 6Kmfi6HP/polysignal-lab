"""
Input: __future__, collections.abc, typing, polysignal_lab.alpha.types, polysignal_lab.domain.enums, polysignal_lab.nautilus_bridge.market_catalog, polysignal_lab.nautilus_runtime.strategy.event_projection, polysignal_lab.paper.exit_result, polysignal_lab.utils
Output: handle_order_lifecycle_event, handle_order_filled, handle_position_event, project_strategy_order_event, project_strategy_fill_event, should_notify_fill, forget_approved_metrics, call_core, _record_early_exit_result
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
from polysignal_lab.paper.exit_result import paper_trade_result_from_early_exit
from polysignal_lab.utils import utc_iso


class _OrderEventStrategy(Protocol):
    core: object
    registry: MarketCatalog | None
    strategy_name: str
    observability: object | None
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
    if bool(alpha_event.metrics.get("reduce_only")):
        _record_early_exit_result(strategy, alpha_event)
    forget_approved_metrics(
        strategy,
        event,
        cast(AlphaOrderEvent, cast(object, alpha_event)),
    )
    if bool(alpha_event.metrics.get("reduce_only")):
        return
    handler = getattr(strategy.core, "on_order_filled", None)
    decisions = handler(alpha_event) if callable(handler) else ()
    if isinstance(decisions, Iterable) and not isinstance(decisions, (str, bytes)):
        for decision in cast(Iterable[AlphaDecision], decisions):
            if decision.condition_id not in strategy._active_condition_ids:
                continue
            view = strategy._require_assembler().build(  # type: ignore[attr-defined]
                decision.condition_id,
                created_at=alpha_event.ts_event,
            )
            if view is None:
                continue
            strategy._handle_decision(decision, cast(MarketView, view))


def _record_early_exit_result(
    strategy: _OrderEventStrategy,
    fill: AlphaFillEvent,
) -> None:
    """Persist Reporting Truth for NativeExitPolicy reduce-only closes."""
    metrics = dict(fill.metrics)
    if "side" not in metrics and fill.side is not None:
        metrics["side"] = getattr(fill.side, "value", fill.side)
    for key, value in (
        ("market_id", fill.market_id),
        ("condition_id", fill.condition_id),
        ("token_id", fill.token_id),
        ("strategy", fill.strategy),
    ):
        if value not in (None, "") and key not in metrics:
            metrics[key] = value
    metrics.setdefault("owning_strategy", strategy.strategy_name)
    closed_at = None
    if fill.ts_event is not None:
        try:
            closed_at = fill.ts_event.isoformat()
        except AttributeError:
            closed_at = None
    result = paper_trade_result_from_early_exit(
        metrics,
        fill_price=float(fill.fill_price),
        fill_shares=float(fill.shares),
        strategy_name=strategy.strategy_name,
        closed_at=closed_at or utc_iso(),
    )
    if result is None:
        return
    observability = strategy.observability
    if observability is None:
        return
    recorder = getattr(observability, "record_event", None)
    if not callable(recorder):
        return
    try:
        recorder("settlements", result)
        strategy._note_runtime_progress("early_exit_result")
    except Exception:
        strategy._note_runtime_progress("early_exit_result_failed")


def handle_position_event(strategy: _OrderEventStrategy, position: object) -> None:
    strategy._record_nautilus_position(position)


def handle_position_closed(strategy: _OrderEventStrategy, position: object) -> None:
    handle_position_event(strategy, position)
    reset_position = getattr(strategy.core, "reset_position", None)
    registry = strategy.registry
    if registry is None or not callable(reset_position):
        return
    instrument_id = str(getattr(position, "instrument_id", ""))
    try:
        pair, token_meta = _catalog_position_identity(registry, instrument_id)
    except (RuntimeError, ValueError):
        return
    if token_meta is None or pair is None:
        return
    reset_position(pair.market_id, token_meta.side)


def _catalog_position_identity(
    registry: MarketCatalog,
    instrument_id: str,
) -> tuple[object | None, object | None]:
    for condition_id in registry.condition_ids():
        pair = registry.by_condition(condition_id)
        if pair is None:
            continue
        for token_meta in (pair.up, pair.down):
            if registry.instrument_id_for_token(token_meta.token_id) == instrument_id:
                return pair, token_meta
    return None, None
