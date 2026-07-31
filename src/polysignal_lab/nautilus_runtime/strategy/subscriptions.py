from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.polymarket_clients import (
    polymarket_data_client_id,
)
from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_runtime.strategy.catalog_lookups import (
    _asset_conditions,
    _instrument_ids,
)
from polysignal_lab.nautilus_runtime.strategy.nautilus_objects import (
    _nautilus_book_type,
    _nautilus_instrument_id,
)


@dataclass(slots=True)
class MarketSubscriptionState:
    """Track subscribe intent and book readiness — never claim wire confirmation."""

    subscribe_intent_condition_ids: set[str] = field(default_factory=set)
    subscribe_intent_started_at_by_condition: dict[str, datetime] = field(
        default_factory=dict
    )
    pending_metadata_condition_ids: set[str] = field(default_factory=set)
    # Instruments expected from the Actor-owned provider but not Cache-visible yet.
    pending_instrument_ids: set[str] = field(default_factory=set)
    # Instrument-level intent keeps repeated provider updates idempotent.
    subscribed_instrument_ids: set[str] = field(default_factory=set)
    awaiting_book_sides_by_condition: dict[str, set[Side]] = field(default_factory=dict)
    book_generation_started_at_by_condition: dict[str, datetime] = field(
        default_factory=dict
    )
    first_bilateral_book_at_by_condition: dict[str, datetime] = field(
        default_factory=dict
    )
    first_bilateral_book_latency_ms_by_condition: dict[str, int] = field(
        default_factory=dict
    )
    last_book_at_by_condition: dict[str, dict[Side, datetime]] = field(
        default_factory=dict
    )
    last_book_received_at_by_condition: dict[str, dict[Side, datetime]] = field(
        default_factory=dict
    )


class _SubscriptionStateOwner(Protocol):
    _subscription_state: MarketSubscriptionState


class _ConditionSubscriptionStateOwner(_SubscriptionStateOwner, Protocol):
    @property
    def registry(self) -> MarketCatalog | None: ...


class _SubscriptionScopeOwner(Protocol):
    @property
    def registry(self) -> MarketCatalog | None: ...

    _subscription_assets: frozenset[str]
    _subscription_timeframes: frozenset[str]


class _SubscriptionStrategy(Protocol):
    @property
    def registry(self) -> MarketCatalog | None: ...
    @property
    def cache(self) -> object | None: ...

    book_type: str
    unsubscribe_exited: bool
    _startup_condition_ids: tuple[str, ...]
    _active_condition_ids: set[str]
    _subscription_state: MarketSubscriptionState
    _asset_condition_ids: dict[str, tuple[str, ...]]
    _subscription_assets: frozenset[str]
    _subscription_timeframes: frozenset[str]

    def _readiness_detail(
        self,
        condition_id: str,
        *,
        now: datetime,
    ) -> dict[str, object]: ...

    def subscribe_quotes(
        self,
        instrument_id: object,
        client_id: object | None = None,
    ) -> object: ...
    def subscribe_trades(
        self,
        instrument_id: object,
        client_id: object | None = None,
    ) -> object: ...
    def subscribe_book_deltas(
        self,
        instrument_id: object,
        *,
        book_type: object,
        client_id: object | None = None,
        managed: bool = False,
    ) -> object: ...
    def unsubscribe_quotes(
        self,
        instrument_id: object,
        client_id: object | None = None,
    ) -> object: ...
    def unsubscribe_trades(
        self,
        instrument_id: object,
        client_id: object | None = None,
    ) -> object: ...
    def unsubscribe_book_deltas(
        self,
        instrument_id: object,
        client_id: object | None = None,
    ) -> object: ...


def refresh_asset_conditions(strategy: _SubscriptionStrategy) -> None:
    tracked_condition_ids = tuple(
        dict.fromkeys(
            (*strategy._startup_condition_ids, *strategy._active_condition_ids)
        )
    )
    strategy._asset_condition_ids = _asset_conditions(
        strategy.registry, tracked_condition_ids
    )


def condition_in_subscription_scope(
    strategy: _SubscriptionScopeOwner,
    condition_id: str,
    *,
    asset_by_condition: Mapping[str, str] | None = None,
    timeframe_by_condition: Mapping[str, str] | None = None,
    include_unknown: bool = True,
) -> bool:
    pair = None if strategy.registry is None else strategy.registry.by_condition(condition_id)
    asset = (
        pair.asset
        if pair is not None
        else None if asset_by_condition is None else asset_by_condition.get(condition_id)
    )
    timeframe = (
        pair.timeframe
        if pair is not None
        else (
            None
            if timeframe_by_condition is None
            else timeframe_by_condition.get(condition_id)
        )
    )
    if asset is None or timeframe is None:
        return include_unknown
    return (
        asset.upper() in strategy._subscription_assets
        and timeframe.lower() in strategy._subscription_timeframes
    )


def subscription_scope_condition_ids(
    strategy: _SubscriptionScopeOwner,
    condition_ids: Sequence[str],
    *,
    asset_by_condition: Mapping[str, str] | None = None,
    timeframe_by_condition: Mapping[str, str] | None = None,
    include_unknown: bool = True,
) -> tuple[str, ...]:
    return tuple(
        condition_id
        for condition_id in condition_ids
        if condition_in_subscription_scope(
            strategy,
            condition_id,
            asset_by_condition=asset_by_condition,
            timeframe_by_condition=timeframe_by_condition,
            include_unknown=include_unknown,
        )
    )


def _client_id_for_instrument(
    strategy: _SubscriptionStrategy,
    instrument_id: object,
) -> object | None:
    registry = strategy.registry
    if registry is None:
        return None
    instrument_key = _instrument_key(instrument_id)
    for condition_id in registry.condition_ids():
        pair = registry.by_condition(condition_id)
        if pair is None:
            continue
        for token_id in (pair.up.token_id, pair.down.token_id):
            resolved = registry.instrument_id_for_token(token_id)
            if resolved is not None and _instrument_key(resolved) == instrument_key:
                return polymarket_data_client_id(pair.timeframe)
    return None


def _subscribe_market_condition(
    strategy: _SubscriptionStrategy,
    registry: MarketCatalog,
    condition_id: str,
    *,
    now: datetime,
    allow_inactive: bool = False,
    allow_deferred: bool = False,
) -> None:
    if not condition_in_subscription_scope(strategy, condition_id):
        return
    if not allow_inactive and condition_id not in strategy._active_condition_ids:
        return
    state = strategy._subscription_state
    first_intent = condition_id not in state.subscribe_intent_condition_ids
    if not first_intent and not pending_condition_instrument_ids(
        strategy,
        condition_id,
    ):
        state.pending_metadata_condition_ids.discard(condition_id)
        return
    instrument_ids = _instrument_ids(registry, (condition_id,))
    if not instrument_ids:
        state.pending_metadata_condition_ids.add(condition_id)
        return
    if first_intent and condition_id in strategy._active_condition_ids:
        begin_market_book_generation(strategy, condition_id, now=now)
    state.pending_metadata_condition_ids.discard(condition_id)
    for instrument_id in condition_instruments(strategy, condition_id):
        _ = subscribe_market_instrument(strategy, instrument_id)
    # Intent only — book readiness confirms feed, not subscribe() return.
    state.subscribe_intent_condition_ids.add(condition_id)
    state.subscribe_intent_started_at_by_condition.setdefault(
        condition_id,
        now.astimezone(UTC),
    )


def subscribe_market_conditions(
    strategy: _SubscriptionStrategy,
    condition_ids: Sequence[str],
    *,
    now: datetime,
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


def _instrument_key(instrument_id: object) -> str:
    return str(getattr(instrument_id, "id", instrument_id))


def instrument_visible_in_cache(
    strategy: _SubscriptionStrategy,
    instrument_id: object,
) -> bool:
    """True when Cache holds the instrument, or Cache is not yet bound.

    Production on_start always has a Cache: missing instrument → pending intent,
    then wait for the provider-owned on_instrument callback. Unit hosts with no
    Cache (pre-engine) may wire subscribe calls directly.
    """
    cache = getattr(strategy, "cache", None)
    if cache is None:
        return True
    getter = getattr(cache, "instrument", None)
    if not callable(getter):
        return True
    try:
        cached = getter(instrument_id)
    except (LookupError, TypeError, ValueError, AttributeError):
        cached = None
    if cached is not None:
        return True
    try:
        cached = getter(_nautilus_instrument_id(str(instrument_id)))
    except (LookupError, TypeError, ValueError, AttributeError):
        return False
    return cached is not None


def subscribe_market_instrument(
    strategy: _SubscriptionStrategy,
    instrument_id: object,
) -> bool:
    """Subscribe quotes/trades/book only after instrument is Cache-visible.

    Locked pyo3 Strategy API (nautilus_trader 1.231): subscribe_quotes /
    subscribe_trades / subscribe_book_deltas (not Cython long names).
    """
    instrument_id = _nautilus_instrument_id(instrument_id)
    key = _instrument_key(instrument_id)
    if key in strategy._subscription_state.subscribed_instrument_ids:  # pyright: ignore[reportPrivateUsage]
        strategy._subscription_state.pending_instrument_ids.discard(key)  # pyright: ignore[reportPrivateUsage]
        return True
    client_id = _client_id_for_instrument(strategy, instrument_id)
    if not instrument_visible_in_cache(strategy, instrument_id):
        strategy._subscription_state.pending_instrument_ids.add(key)
        return False
    strategy._subscription_state.pending_instrument_ids.discard(key)
    book_type = _nautilus_book_type(strategy.book_type)
    _ = strategy.subscribe_quotes(instrument_id, client_id=client_id)
    _ = strategy.subscribe_trades(instrument_id, client_id=client_id)
    # managed=True: the engine maintains the Cache order book from deltas;
    # MarketView assembly reads books from the Cache (issue #21).
    _ = strategy.subscribe_book_deltas(
        instrument_id,
        book_type=book_type,
        client_id=client_id,
        managed=True,
    )
    strategy._subscription_state.subscribed_instrument_ids.add(key)
    return True


def on_instrument_available(
    strategy: _SubscriptionStrategy,
    instrument: object,
) -> bool:
    """After provider load / on_instrument: subscribe if still needed."""
    raw_id = getattr(instrument, "id", instrument)
    instrument_id = _nautilus_instrument_id(raw_id)
    key = _instrument_key(instrument_id)
    strategy._subscription_state.pending_instrument_ids.discard(key)  # pyright: ignore[reportPrivateUsage]
    if strategy.registry is None:
        return False
    wanted = {
        _instrument_key(iid)
        for iid in _instrument_ids(
            strategy.registry,
            tuple(
                strategy._active_condition_ids
                | strategy._subscription_state.subscribe_intent_condition_ids
            ),
        )
    }
    if key not in wanted:
        return False
    return subscribe_market_instrument(strategy, instrument_id)


def unsubscribe_all_market_instruments(
    strategy: _SubscriptionStrategy,
) -> None:
    for instrument_id in tuple(strategy._subscription_state.subscribed_instrument_ids):
        _ = unsubscribe_market_instrument(strategy, instrument_id)
    strategy._subscription_state.pending_instrument_ids.clear()
    strategy._subscription_state.subscribe_intent_condition_ids.clear()
    strategy._subscription_state.subscribe_intent_started_at_by_condition.clear()
    strategy._subscription_state.pending_metadata_condition_ids.clear()


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


def pending_condition_instrument_ids(
    strategy: _ConditionSubscriptionStateOwner,
    condition_id: str,
) -> tuple[str, ...]:
    registry = strategy.registry
    pair = None if registry is None else registry.by_condition(condition_id)
    if registry is None or pair is None:
        return ()
    pending = strategy._subscription_state.pending_instrument_ids
    return tuple(
        sorted(
            key
            for token_id in (pair.up.token_id, pair.down.token_id)
            if (instrument_id := registry.instrument_id_for_token(token_id)) is not None
            if (key := _instrument_key(instrument_id)) in pending
        )
    )


def clear_condition_subscription_state(
    strategy: _ConditionSubscriptionStateOwner,
    condition_id: str,
    *,
    clear_subscribed: bool = True,
) -> None:
    strategy._subscription_state.subscribe_intent_condition_ids.discard(condition_id)
    strategy._subscription_state.subscribe_intent_started_at_by_condition.pop(
        condition_id, None
    )
    strategy._subscription_state.pending_metadata_condition_ids.discard(condition_id)
    if strategy.registry is not None:
        for instrument_id in _instrument_ids(strategy.registry, (condition_id,)):
            key = _instrument_key(instrument_id)
            strategy._subscription_state.pending_instrument_ids.discard(key)
            if clear_subscribed:
                strategy._subscription_state.subscribed_instrument_ids.discard(key)  # pyright: ignore[reportPrivateUsage]
    retire_market_book_generation(strategy, condition_id, clear_history=False)


def begin_market_book_generation(
    strategy: _SubscriptionStateOwner,
    condition_id: str,
    *,
    now: datetime,
) -> None:
    """Invalidate cached-book readiness before a real subscribe attempt."""
    observed = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    strategy._subscription_state.awaiting_book_sides_by_condition[condition_id] = {
        Side.UP,
        Side.DOWN,
    }
    strategy._subscription_state.book_generation_started_at_by_condition[
        condition_id
    ] = observed.astimezone(UTC)
    strategy._subscription_state.first_bilateral_book_at_by_condition.pop(
        condition_id, None
    )
    strategy._subscription_state.first_bilateral_book_latency_ms_by_condition.pop(
        condition_id, None
    )


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
    last_receipts = (
        strategy._subscription_state.last_book_received_at_by_condition.setdefault(
            condition_id,
            {},
        )
    )
    previous_received = last_receipts.get(side)
    if previous_received is None or received >= previous_received:
        last_receipts[side] = received
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
    if pending:
        return False
    finish_market_book_generation(
        strategy._subscription_state,
        condition_id,
        received_at=received,
        started_at=started_at,
    )
    return True


def finish_market_book_generation(
    state: MarketSubscriptionState,
    condition_id: str,
    *,
    received_at: datetime,
    started_at: datetime | None,
) -> None:
    receipts = state.last_book_received_at_by_condition.get(condition_id, {})
    ready_at = max(receipts.values(), default=received_at)
    state.awaiting_book_sides_by_condition.pop(condition_id)
    state.book_generation_started_at_by_condition.pop(condition_id, None)
    state.first_bilateral_book_at_by_condition[condition_id] = ready_at
    if started_at is not None:
        latency_ms = max(0, int((ready_at - started_at).total_seconds() * 1000))
        state.first_bilateral_book_latency_ms_by_condition[condition_id] = latency_ms


def market_book_generation_ready(
    strategy: _SubscriptionStateOwner,
    condition_id: str,
) -> bool:
    return not strategy._subscription_state.awaiting_book_sides_by_condition.get(
        condition_id
    )


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
    strategy._subscription_state.first_bilateral_book_at_by_condition.pop(
        condition_id,
        None,
    )
    strategy._subscription_state.first_bilateral_book_latency_ms_by_condition.pop(
        condition_id,
        None,
    )
    if clear_history:
        strategy._subscription_state.last_book_at_by_condition.pop(condition_id, None)
        strategy._subscription_state.last_book_received_at_by_condition.pop(
            condition_id,
            None,
        )


def unsubscribe_market_instrument(
    strategy: _SubscriptionStrategy,
    instrument_id: object,
) -> bool:
    instrument_id = _nautilus_instrument_id(instrument_id)
    key = _instrument_key(instrument_id)
    client_id = _client_id_for_instrument(strategy, instrument_id)
    _ = strategy.unsubscribe_quotes(instrument_id, client_id=client_id)
    _ = strategy.unsubscribe_trades(instrument_id, client_id=client_id)
    _ = strategy.unsubscribe_book_deltas(instrument_id, client_id=client_id)
    strategy._subscription_state.subscribed_instrument_ids.discard(key)  # pyright: ignore[reportPrivateUsage]
    return True
