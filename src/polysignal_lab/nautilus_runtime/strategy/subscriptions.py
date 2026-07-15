"""
Input: __future__, collections.abc, dataclasses, datetime, typing, polysignal_lab.domain.enums
Output: market subscription lifecycle and wire-operation helpers
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog
from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_runtime.strategy.helpers import (
    _asset_conditions,
    _instrument_ids,
    _nautilus_book_type,
    _nautilus_instrument_id,
)


_MAX_STALE_REFRESH_INTERVAL_SEC = 300


@dataclass(slots=True)
class MarketSubscriptionState:
    """Track wire subscriptions separately from active-condition membership."""

    wire_condition_ids: set[str] = field(default_factory=set)
    pending_metadata_condition_ids: set[str] = field(default_factory=set)
    pending_subscribe_condition_ids: set[str] = field(default_factory=set)
    retained_wire_condition_ids: set[str] = field(default_factory=set)
    stale_refresh_attempts_by_condition: dict[str, int] = field(default_factory=dict)
    last_stale_refresh_at: dict[str, datetime] = field(default_factory=dict)
    awaiting_book_sides_by_condition: dict[str, set[Side]] = field(default_factory=dict)
    book_generation_started_at_by_condition: dict[str, datetime] = field(default_factory=dict)
    last_book_at_by_condition: dict[str, dict[Side, datetime]] = field(default_factory=dict)


class _SubscriptionStateOwner(Protocol):
    _subscription_state: MarketSubscriptionState


class _SubscriptionStrategy(Protocol):
    @property
    def registry(self) -> MarketCatalog | None: ...
    book_type: str
    _startup_condition_ids: tuple[str, ...]
    _active_condition_ids: set[str]
    _subscription_state: MarketSubscriptionState
    _asset_condition_ids: dict[str, tuple[str, ...]]

    def _readiness_detail(
        self,
        condition_id: str,
        *,
        now: datetime,
    ) -> dict[str, object]: ...

    def request_instrument(self, instrument_id: object) -> object: ...
    def subscribe_quote_ticks(self, instrument_id: object) -> object: ...
    def subscribe_trade_ticks(self, instrument_id: object) -> object: ...
    def subscribe_order_book_deltas(
        self, instrument_id: object, *, book_type: object
    ) -> object: ...
    def unsubscribe_quote_ticks(self, instrument_id: object) -> object: ...
    def unsubscribe_trade_ticks(self, instrument_id: object) -> object: ...
    def unsubscribe_order_book_deltas(self, instrument_id: object) -> object: ...


class MarketSubscriptionCoordinator:
    """Reset a shared venue subscription only after every strategy releases it."""

    def __init__(self) -> None:
        self._strategies: list[_SubscriptionStrategy] = []
        self._attempts_by_condition: dict[str, int] = {}
        self._last_refresh_at: dict[str, datetime] = {}
        self._ready_strategy_ids_by_condition: dict[str, set[int]] = {}

    def register(self, strategy: _SubscriptionStrategy) -> None:
        if all(candidate is not strategy for candidate in self._strategies):
            self._strategies.append(strategy)

    def note_readiness(
        self,
        strategy: _SubscriptionStrategy,
        condition_id: str,
        *,
        ready: bool,
    ) -> bool:
        ready_ids = self._ready_strategy_ids_by_condition.setdefault(
            condition_id,
            set(),
        )
        strategy_id = id(strategy)
        active_ids = {
            id(candidate)
            for candidate in self._strategies
            if condition_id in candidate._active_condition_ids
        }
        if ready and strategy_id in active_ids:
            ready_ids.add(strategy_id)
        else:
            ready_ids.discard(strategy_id)
        condition_ready = active_ids <= ready_ids
        if condition_ready:
            self._attempts_by_condition.pop(condition_id, None)
            self._last_refresh_at.pop(condition_id, None)
            if not active_ids:
                self._ready_strategy_ids_by_condition.pop(condition_id, None)
        return condition_ready

    def unready_consumer(
        self,
        condition_id: str,
    ) -> _SubscriptionStrategy | None:
        ready_ids = self._ready_strategy_ids_by_condition.get(condition_id, set())
        return next(
            (
                strategy
                for strategy in self._strategies
                if condition_id in strategy._active_condition_ids
                and id(strategy) not in ready_ids
            ),
            None,
        )

    def refresh(
        self,
        requester: _SubscriptionStrategy,
        condition_id: str,
        *,
        now: datetime,
        min_interval_sec: int = 30,
    ) -> bool:
        if condition_id not in requester._active_condition_ids:
            return False
        consumers = [
            strategy
            for strategy in self._strategies
            if condition_id in strategy._active_condition_ids
        ]
        if not consumers:
            return False
        observed = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
        observed = observed.astimezone(UTC)
        attempts = self._attempts_by_condition.get(condition_id, 0)
        retry_interval_sec = min(
            int(min_interval_sec) * (2 ** min(attempts, 10)),
            max(int(min_interval_sec), _MAX_STALE_REFRESH_INTERVAL_SEC),
        )
        last = self._last_refresh_at.get(condition_id)
        if last is not None and (observed - last).total_seconds() < retry_interval_sec:
            return False
        for strategy in consumers:
            unsubscribe_market_conditions(strategy, (condition_id,))
        for strategy in consumers:
            subscribe_market_conditions(strategy, (condition_id,), now=observed)
        refreshed = all(
            condition_id in strategy._subscription_state.wire_condition_ids
            for strategy in consumers
        )
        next_attempts = attempts + 1 if refreshed else 0
        self._last_refresh_at[condition_id] = observed
        self._attempts_by_condition[condition_id] = next_attempts
        self._ready_strategy_ids_by_condition.pop(condition_id, None)
        for strategy in consumers:
            strategy._subscription_state.last_stale_refresh_at[condition_id] = observed
            strategy._subscription_state.stale_refresh_attempts_by_condition[
                condition_id
            ] = next_attempts
        return refreshed


class InstrumentSubscriptionManager:
    """Thin bridge used by custom-data handlers to re-request missing instruments."""

    def __init__(self, strategy: _SubscriptionStrategy) -> None:
        self._strategy = strategy

    def retry_instrument_requests(self, condition_ids: tuple[str, ...]) -> None:
        retry_market_instrument_requests(
            self._strategy,
            condition_ids,
            retry_after=timedelta(seconds=10),
        )


def refresh_asset_conditions(strategy: _SubscriptionStrategy) -> None:
    tracked_condition_ids = tuple(
        dict.fromkeys((*strategy._startup_condition_ids, *strategy._active_condition_ids))
    )
    strategy._asset_condition_ids = _asset_conditions(
        strategy.registry, tracked_condition_ids
    )


def retry_market_instrument_requests(
    strategy: _SubscriptionStrategy,
    condition_ids: Sequence[str],
    *,
    retry_after: timedelta | None = None,
) -> None:
    _ = retry_after
    if strategy.registry is None:
        return
    for instrument_id in _instrument_ids(strategy.registry, condition_ids):
        _ = strategy.request_instrument(instrument_id)


def _subscribe_market_condition(
    strategy: _SubscriptionStrategy,
    registry: MarketCatalog,
    condition_id: str,
    *,
    now: datetime | None,
) -> None:
    if condition_id not in strategy._active_condition_ids:
        return
    state = strategy._subscription_state
    if condition_id in state.wire_condition_ids:
        state.pending_metadata_condition_ids.discard(condition_id)
        state.pending_subscribe_condition_ids.discard(condition_id)
        state.retained_wire_condition_ids.discard(condition_id)
        return
    instrument_ids = _instrument_ids(registry, (condition_id,))
    if not instrument_ids:
        state.pending_metadata_condition_ids.add(condition_id)
        state.pending_subscribe_condition_ids.discard(condition_id)
        return
    begin_market_book_generation(strategy, condition_id, now=now)
    state.pending_metadata_condition_ids.discard(condition_id)
    subscribed = True
    for instrument_id in condition_instruments(strategy, condition_id):
        if not subscribe_market_instrument(strategy, instrument_id):
            subscribed = False
    if subscribed:
        state.pending_subscribe_condition_ids.discard(condition_id)
        state.retained_wire_condition_ids.discard(condition_id)
        state.wire_condition_ids.add(condition_id)
        return
    state.pending_subscribe_condition_ids.add(condition_id)


def subscribe_market_conditions(
    strategy: _SubscriptionStrategy,
    condition_ids: Sequence[str],
    *,
    now: datetime | None = None,
) -> None:
    registry = strategy.registry
    if registry is None:
        return
    for condition_id in condition_ids:
        _subscribe_market_condition(
            strategy,
            registry,
            condition_id,
            now=now,
        )


def subscribe_market_instrument(
    strategy: _SubscriptionStrategy,
    instrument_id: object,
) -> bool:
    instrument_id = _nautilus_instrument_id(instrument_id)
    book_type = _nautilus_book_type(strategy.book_type)
    subscribed = call_subscription(strategy, strategy.subscribe_quote_ticks, instrument_id)
    if not call_subscription(strategy, strategy.subscribe_trade_ticks, instrument_id):
        subscribed = False
    if not call_subscription(
        strategy,
        strategy.subscribe_order_book_deltas,
        instrument_id,
        book_type=book_type,
    ):
        subscribed = False
    return subscribed


def unsubscribe_market_conditions(
    strategy: _SubscriptionStrategy,
    condition_ids: Sequence[str],
) -> None:
    if strategy.registry is None:
        return
    for condition_id in condition_ids:
        for instrument_id in condition_instruments(strategy, condition_id):
            _ = unsubscribe_market_instrument(strategy, instrument_id)
        clear_condition_subscription_state(strategy, condition_id)


def condition_instruments(
    strategy: _SubscriptionStrategy,
    condition_id: str,
) -> tuple[object, ...]:
    if strategy.registry is None:
        return ()
    return _instrument_ids(strategy.registry, (condition_id,))


def clear_condition_subscription_state(
    strategy: _SubscriptionStrategy,
    condition_id: str,
) -> None:
    strategy._subscription_state.wire_condition_ids.discard(condition_id)
    strategy._subscription_state.retained_wire_condition_ids.discard(condition_id)
    strategy._subscription_state.pending_subscribe_condition_ids.discard(condition_id)
    strategy._subscription_state.pending_metadata_condition_ids.discard(condition_id)
    strategy._subscription_state.stale_refresh_attempts_by_condition.pop(
        condition_id,
        None,
    )
    strategy._subscription_state.last_stale_refresh_at.pop(condition_id, None)
    retire_market_book_generation(strategy, condition_id, clear_history=False)


def mark_market_subscription_ready(
    strategy: _SubscriptionStrategy,
    condition_id: str,
) -> None:
    strategy._subscription_state.stale_refresh_attempts_by_condition.pop(
        condition_id,
        None,
    )
    strategy._subscription_state.last_stale_refresh_at.pop(condition_id, None)


def begin_market_book_generation(
    strategy: _SubscriptionStateOwner,
    condition_id: str,
    *,
    now: datetime | None = None,
) -> None:
    """Invalidate cached-book readiness before a real subscribe attempt."""
    observed = now or datetime.now(UTC)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    strategy._subscription_state.awaiting_book_sides_by_condition[condition_id] = {
        Side.UP,
        Side.DOWN,
    }
    strategy._subscription_state.book_generation_started_at_by_condition[
        condition_id
    ] = observed.astimezone(UTC)


def observe_market_book_side(
    strategy: _SubscriptionStateOwner,
    condition_id: str,
    side: Side,
    *,
    received_at: datetime,
    book_at: datetime,
) -> bool:
    received = received_at.astimezone(UTC)
    observed_book = book_at.astimezone(UTC)
    last_books = strategy._subscription_state.last_book_at_by_condition.setdefault(
        condition_id,
        {},
    )
    previous = last_books.get(side)
    if previous is None or observed_book >= previous:
        last_books[side] = observed_book
    pending = strategy._subscription_state.awaiting_book_sides_by_condition.get(
        condition_id
    )
    if pending is None:
        return True
    started_at = (
        strategy._subscription_state.book_generation_started_at_by_condition.get(
            condition_id
        )
    )
    if started_at is not None and received < started_at:
        return False
    pending.discard(side)
    return not pending


def market_book_generation_ready(
    strategy: _SubscriptionStateOwner,
    condition_id: str,
) -> bool:
    return not strategy._subscription_state.awaiting_book_sides_by_condition.get(
        condition_id
    )


def market_book_generation_stalled(
    strategy: _SubscriptionStateOwner,
    condition_id: str,
    *,
    now: datetime,
    timeout_sec: int = 30,
) -> bool:
    started_at = (
        strategy._subscription_state.book_generation_started_at_by_condition.get(
            condition_id
        )
    )
    if started_at is None:
        return True
    observed = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    return (observed.astimezone(UTC) - started_at).total_seconds() >= timeout_sec


def retire_market_book_generation(
    strategy: _SubscriptionStateOwner,
    condition_id: str,
    *,
    clear_history: bool = True,
) -> None:
    strategy._subscription_state.awaiting_book_sides_by_condition.pop(
        condition_id,
        None,
    )
    strategy._subscription_state.book_generation_started_at_by_condition.pop(
        condition_id,
        None,
    )
    if clear_history:
        strategy._subscription_state.last_book_at_by_condition.pop(condition_id, None)


def refresh_stale_market_subscription(
    strategy: _SubscriptionStrategy,
    condition_id: str,
    *,
    now: datetime | None = None,
    min_interval_sec: int = 30,
) -> bool:
    """Force unsubscribe+resubscribe for a stale active market condition.

    Subscribe is no-op when already wired; clear wire state first so a fresh
    quote/trade/book subscription can recover after rotation or silent drop.
    """
    if condition_id not in strategy._active_condition_ids:
        return False
    observed = now or datetime.now(UTC)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    attempts = strategy._subscription_state.stale_refresh_attempts_by_condition.get(
        condition_id,
        0,
    )
    retry_interval_sec = min(
        int(min_interval_sec) * (2 ** min(attempts, 10)),
        max(int(min_interval_sec), _MAX_STALE_REFRESH_INTERVAL_SEC),
    )
    last = strategy._subscription_state.last_stale_refresh_at.get(condition_id)
    if last is not None:
        elapsed = (observed - last.astimezone(UTC)).total_seconds()
        if elapsed < retry_interval_sec:
            return False
    unsubscribe_market_conditions(strategy, (condition_id,))
    subscribe_market_conditions(strategy, (condition_id,), now=observed)
    strategy._subscription_state.last_stale_refresh_at[condition_id] = observed
    refreshed = condition_id in strategy._subscription_state.wire_condition_ids
    strategy._subscription_state.stale_refresh_attempts_by_condition[condition_id] = (
        attempts + 1 if refreshed else 0
    )
    return refreshed


def unsubscribe_market_instrument(
    strategy: _SubscriptionStrategy,
    instrument_id: object,
) -> bool:
    instrument_id = _nautilus_instrument_id(instrument_id)
    unsubscribed = call_subscription(
        strategy, strategy.unsubscribe_quote_ticks, instrument_id
    )
    if not call_subscription(strategy, strategy.unsubscribe_trade_ticks, instrument_id):
        unsubscribed = False
    if not call_subscription(
        strategy, strategy.unsubscribe_order_book_deltas, instrument_id
    ):
        unsubscribed = False
    return unsubscribed


def call_subscription(
    strategy: _SubscriptionStrategy,
    callback: Callable[..., object],
    *args: object,
    **kwargs: object,
) -> bool:
    _ = strategy
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
