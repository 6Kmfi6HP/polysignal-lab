from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_runtime.custom_data_state import event_datetime
from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.market_view_assembler import BookReceiptObserver
from polysignal_lab.nautilus_runtime.strategy.catalog_lookups import (
    _condition_id_from_catalog_instrument,
    _token_id_from_catalog_instrument,
)
from polysignal_lab.nautilus_runtime.strategy.nautilus_objects import _identifier_text
from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
    observe_market_book_side,
)


class _MarketDataEvaluator(Protocol):
    _last_market_data_evaluation_at: dict[str, datetime]

    def _framework_now(self) -> datetime: ...
    def _note_runtime_progress(self, phase: str) -> None: ...
    def evaluate_condition(self, condition_id: str) -> None: ...


class _MarketDataStrategy(_MarketDataEvaluator, Protocol):
    registry: MarketCatalog | None
    assembler: object
    _active_condition_ids: set[str]
    _runtime_readiness_miss_condition_ids: set[str]
    _last_market_data_evaluation_at: dict[str, datetime]

    def _framework_now(self) -> datetime: ...
    def _note_runtime_progress(self, phase: str) -> None: ...
    def _note_runtime_readiness(self, condition_id: str, *, ready: bool) -> None: ...
    def _require_registry(self) -> MarketCatalog | None: ...
    def _require_assembler(self) -> object: ...
    def evaluate_condition(self, condition_id: str) -> None: ...


def condition_from_market_data(
    strategy: _MarketDataStrategy,
    data: object,
) -> str | None:
    if strategy.registry is None:
        return None
    instrument_id = _identifier_text(getattr(data, "instrument_id", None))
    if instrument_id is None:
        return None
    condition_id = _condition_id_from_catalog_instrument(
        strategy.registry,
        tuple(strategy._active_condition_ids),
        instrument_id,
    )
    if condition_id is None:
        strategy._note_runtime_progress("dropped_frame")
    return condition_id


def order_book_event_times(
    event: object,
    *,
    received_at: datetime,
) -> tuple[datetime, datetime]:
    raw_received_at = getattr(event, "ts_init", None)
    observed_received_at = (
        received_at if raw_received_at is None else event_datetime(raw_received_at)
    )
    raw_book_at = getattr(event, "ts_event", None)
    if raw_book_at is None:
        raw_book_at = getattr(event, "ts_last", None)
    observed_book_at = (
        observed_received_at if raw_book_at is None else event_datetime(raw_book_at)
    )
    return observed_received_at, observed_book_at


def order_book_observation(
    strategy: _MarketDataStrategy,
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
    now = strategy._framework_now()
    try:
        received_at, book_at = order_book_event_times(event, received_at=now)
    except ValueError:
        return None
    assembler = strategy._require_assembler()
    if isinstance(assembler, BookReceiptObserver):
        assembler.observe_book_received(token_id, received_at=received_at)
    return now, token.side, received_at, book_at


# Full MarketView evaluation per raw book event saturates the event loop on
# busy Polymarket books (issue #21); bursts collapse to one evaluation per
# window, with the 10s heartbeat timer as the idle backstop.
_MARKET_DATA_EVALUATION_MIN_INTERVAL = timedelta(milliseconds=500)


def evaluate_market_data_condition(
    strategy: _MarketDataEvaluator,
    condition_id: str,
    *,
    event: object | None = None,
) -> None:
    _ = event
    now = strategy._framework_now()
    last = strategy._last_market_data_evaluation_at.get(condition_id)
    if last is not None and now - last < _MARKET_DATA_EVALUATION_MIN_INTERVAL:
        return
    strategy._note_runtime_progress("market_data_evaluation")
    strategy._last_market_data_evaluation_at[condition_id] = now
    strategy.evaluate_condition(condition_id)


def evaluate_order_book_event(strategy: _MarketDataStrategy, event: object) -> None:
    condition_id = condition_from_market_data(strategy, event)
    if condition_id is None:
        return
    registry = strategy._require_registry()
    observation = (
        None
        if registry is None
        else order_book_observation(strategy, event, condition_id, registry)
    )
    if observation is None or registry is None:
        strategy._note_runtime_progress("dropped_frame")
        return
    now, side, received_at, book_at = observation
    generation_ready = observe_market_book_side(
        strategy,  # type: ignore[arg-type]
        condition_id,
        side,
        received_at=received_at,
        book_at=book_at,
    )
    pair = registry.by_condition(condition_id)
    if pair is not None and pair.start_ts is not None and now < pair.start_ts:
        if condition_id in strategy._runtime_readiness_miss_condition_ids:
            strategy._note_runtime_readiness(condition_id, ready=True)
        return
    if generation_ready:
        evaluate_market_data_condition(strategy, condition_id, event=event)
        return
    strategy._note_runtime_progress("market_data_evaluation")
    strategy._last_market_data_evaluation_at[condition_id] = now
    strategy._note_runtime_progress("readiness_miss")
    strategy._note_runtime_readiness(condition_id, ready=False)
