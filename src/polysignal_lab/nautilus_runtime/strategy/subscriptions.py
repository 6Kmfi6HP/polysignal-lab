"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Callable, collections.abc.Sequence, dataclasses, dataclasses.dataclass, dataclasses.field, datetime, datetime.timedelta, typing, typing.Protocol
Output: MarketSubscriptionState, InstrumentSubscriptionManager, refresh_asset_conditions, retry_market_instrument_requests, subscribe_market_conditions, subscribe_market_instrument, unsubscribe_market_conditions, condition_instruments, clear_condition_subscription_state, unsubscribe_market_instrument, call_subscription
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Protocol

from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.strategy.helpers import (
    _asset_conditions,
    _instrument_ids,
    _nautilus_book_type,
    _nautilus_instrument_id,
)


@dataclass(slots=True)
class MarketSubscriptionState:
    """Track wire subscriptions separately from active-condition membership."""

    wire_condition_ids: set[str] = field(default_factory=set)
    pending_metadata_condition_ids: set[str] = field(default_factory=set)
    pending_subscribe_condition_ids: set[str] = field(default_factory=set)
    retained_wire_condition_ids: set[str] = field(default_factory=set)


class _SubscriptionStrategy(Protocol):
    registry: MarketCatalog | None
    book_type: str
    _startup_condition_ids: tuple[str, ...]
    _active_condition_ids: set[str]
    _subscription_state: MarketSubscriptionState
    _asset_condition_ids: dict[str, tuple[str, ...]]

    def request_instrument(self, instrument_id: object) -> object: ...
    def subscribe_quote_ticks(self, instrument_id: object) -> object: ...
    def subscribe_trade_ticks(self, instrument_id: object) -> object: ...
    def subscribe_order_book_deltas(
        self, instrument_id: object, *, book_type: object
    ) -> object: ...
    def request_order_book_snapshot(self, instrument_id: object) -> object: ...
    def unsubscribe_quote_ticks(self, instrument_id: object) -> object: ...
    def unsubscribe_trade_ticks(self, instrument_id: object) -> object: ...
    def unsubscribe_order_book_deltas(self, instrument_id: object) -> object: ...


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


def subscribe_market_conditions(
    strategy: _SubscriptionStrategy,
    condition_ids: Sequence[str],
) -> None:
    if strategy.registry is None:
        return
    for condition_id in condition_ids:
        if condition_id not in strategy._active_condition_ids:
            continue
        if condition_id in strategy._subscription_state.wire_condition_ids:
            strategy._subscription_state.pending_metadata_condition_ids.discard(
                condition_id
            )
            strategy._subscription_state.pending_subscribe_condition_ids.discard(
                condition_id
            )
            strategy._subscription_state.retained_wire_condition_ids.discard(
                condition_id
            )
            continue
        instrument_ids = _instrument_ids(strategy.registry, (condition_id,))
        if not instrument_ids:
            strategy._subscription_state.pending_metadata_condition_ids.add(
                condition_id
            )
            strategy._subscription_state.pending_subscribe_condition_ids.discard(
                condition_id
            )
            continue
        strategy._subscription_state.pending_metadata_condition_ids.discard(
            condition_id
        )
        subscribed = True
        for instrument_id in condition_instruments(strategy, condition_id):
            if not subscribe_market_instrument(strategy, instrument_id):
                subscribed = False
        if subscribed:
            strategy._subscription_state.pending_subscribe_condition_ids.discard(
                condition_id
            )
            strategy._subscription_state.retained_wire_condition_ids.discard(
                condition_id
            )
            strategy._subscription_state.wire_condition_ids.add(condition_id)
        else:
            strategy._subscription_state.pending_subscribe_condition_ids.add(
                condition_id
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
    if strategy.book_type == "L1_MBP" and not call_subscription(
        strategy, strategy.request_order_book_snapshot, instrument_id
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
