from __future__ import annotations

import logging

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Protocol, cast

from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.polymarket_clients import (
    polymarket_data_client_id,
)
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.strategy_readiness import StrategyStatus
from polysignal_lab.nautilus_runtime.strategy.catalog_lookups import (
    _asset_conditions,
    _instrument_ids,
)
from polysignal_lab.nautilus_runtime.strategy.nautilus_objects import (
    _nautilus_book_type,
    _nautilus_instrument_id,
)


class ConditionSubscriptionPhase(Enum):
    """Explicit per-condition subscription lifecycle phase.

    The phase is the single source of truth for condition-level lifecycle.
    Derived observations (timestamps, per-side pending, instrument bookkeeping)
    live alongside and are maintained only by the transition functions in this
    module. Absent dict key == UNSUBSCRIBED.
    """

    UNSUBSCRIBED = "unsubscribed"
    PENDING_METADATA = "pending_metadata"
    PENDING_INSTRUMENT = "pending_instrument"
    # Locally-issued subscribe commands; never claims wire confirmation (the
    # Nautilus subscribe API is fire-and-forget with no ACK).
    SUBSCRIBE_ISSUED = "subscribe_issued"
    AWAITING_FIRST_BOOK = "awaiting_first_book"
    READY = "ready"


# Phases that carry an active subscribe intent (excludes the metadata wait).
_SUBSCRIBING_PHASES = frozenset(
    {
        ConditionSubscriptionPhase.PENDING_INSTRUMENT,
        ConditionSubscriptionPhase.SUBSCRIBE_ISSUED,
        ConditionSubscriptionPhase.AWAITING_FIRST_BOOK,
        ConditionSubscriptionPhase.READY,
    }
)

# How long book generation may idle at AWAITING_FIRST_BOOK before the strategy
# forces a resubscription. Polymarket WS drops idle (read-timeout) connections
# and the incremental book_delta subscription has no snapshot fallback, so a
# quiet market can leave a subscribed condition without its first book forever.
# This is the only recovery for that stall (issue: healthcheck reads miss).
_BOOK_GENERATION_STALL_SEC = 60.0

# How long a condition may stay stalled continuously (across resubscriptions)
# before we conclude the market has no book data and abandon it instead of
# resubscribing again. Repeated resubscription cannot conjure a snapshot the
# feed never sends (a thin or defunct Polymarket market).
#
# The value must stay BELOW the liveness readiness-miss window
# (health.liveness.max_readiness_miss_sec, default 300): abandon only runs on
# the 10s evaluation heartbeat, so it can lag the threshold by up to one
# heartbeat interval. 240 + 10 < 300 guarantees the abandon fires (and clears
# the persisted readiness-miss key via _note_runtime_readiness ready=True)
# strictly before the node can ever be judged unhealthy for the condition.
_BOOK_GENERATION_ABANDON_SEC = 240.0

# Cooldown between coordinated global book-recovery batches. When every
# once-READY active condition is simultaneously stuck awaiting a book (a
# global feed event, e.g. the Polymarket WS being dropped with
# 'no ping received'), the heartbeat would otherwise re-arm each condition's
# refresh on its own 60s cadence. Each refresh starts an adapter book recovery
# that competes with the adapter's own reconnect/replay and fails with
# "Recovery delta buffer limit exceeded", so the per-condition retries
# actively prevent the storm from converging. While the global stall persists,
# the heartbeat emits one coordinated refresh batch and then suppresses further
# wire retries for this window; any recovered condition lifts the suppression.
_GLOBAL_RECOVERY_COOLDOWN_SEC = 120.0

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MarketSubscriptionState:
    """Track subscribe intent and book readiness — never claim wire confirmation."""

    condition_phases: dict[str, ConditionSubscriptionPhase] = field(
        default_factory=dict
    )
    subscribe_intent_started_at_by_condition: dict[str, datetime] = field(
        default_factory=dict
    )
    # Instruments expected from the Actor-owned provider but not Cache-visible yet.
    pending_instrument_ids: set[str] = field(default_factory=set)
    # Instrument-level intent keeps repeated provider updates idempotent.
    subscribed_instrument_ids: set[str] = field(default_factory=set)
    awaiting_book_sides_by_condition: dict[str, set[Side]] = field(default_factory=dict)
    # Generation validity clock: set only by begin_market_book_generation.
    # observe_market_book_side rejects received_at < this timestamp. Wire
    # retries must NOT bump this — otherwise post-generation books are
    # recorded as receipts yet never discard awaiting sides.
    book_generation_started_at_by_condition: dict[str, datetime] = field(
        default_factory=dict
    )
    # Strategy-local recovery intent ownership. Once the heartbeat submits a
    # missing side for the current generation, only a valid managed-book
    # receipt for that side clears it. Adapter code owns wire retry/coalescing.
    pending_book_recovery_sides_by_condition: dict[str, set[Side]] = field(
        default_factory=dict
    )
    # Total-stall clock: when the condition first began waiting for a book
    # (first generation start, or first stale-book detection). A pending
    # recovery intent does not reset it, so the 240s abandon threshold remains
    # reachable. Cleared on ready, retire, clear, or abandon.
    book_stalled_started_at_by_condition: dict[str, datetime] = field(
        default_factory=dict
    )
    first_bilateral_book_at_by_condition: dict[str, datetime] = field(
        default_factory=dict
    )
    # When the condition first reached READY (first bilateral book) during its
    # current active period. Unlike first_bilateral_book_at_by_condition this is
    # NOT cleared when a stale repair re-begins generation, so the book-stall
    # abandon path can distinguish a condition that merely went stale (recover,
    # never abandon via book stall) from one whose first book never arrived.
    # Cleared on retire/clear/abandon via retire_market_book_generation.
    first_bilateral_book_ever_at_by_condition: dict[str, datetime] = field(
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
    # Last time the heartbeat emitted one coordinated global recovery batch
    # after a whole-set book stall. Cleared on any completed bilateral book so
    # the next stall can batch immediately. While set and recent, per-condition
    # wire retries for the stalled once-READY set are suppressed.
    global_book_recovery_batch_at: datetime | None = field(default=None)


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


class _BookRefreshStrategy(Protocol):
    def refresh_book_subscription(
        self,
        instrument_id: object,
        client_id: object | None = None,
        params: Mapping[str, object] | None = None,
    ) -> object: ...


def condition_phase(
    strategy: _ConditionSubscriptionStateOwner,
    condition_id: str,
) -> ConditionSubscriptionPhase:
    """Read the per-condition subscription phase (absent key == UNSUBSCRIBED)."""
    return strategy._subscription_state.condition_phases.get(
        condition_id,
        ConditionSubscriptionPhase.UNSUBSCRIBED,
    )


def _store_condition_phase(
    state: MarketSubscriptionState,
    condition_id: str,
    phase: ConditionSubscriptionPhase,
) -> None:
    if phase is ConditionSubscriptionPhase.UNSUBSCRIBED:
        state.condition_phases.pop(condition_id, None)
    else:
        state.condition_phases[condition_id] = phase


# Explicit allowed-transition table for ConditionSubscriptionPhase.
#
# Absent key == UNSUBSCRIBED. Cleanup (target UNSUBSCRIBED) is always legal and
# removes the key. READY is re-entrant: rotation/recovery may reopen a book
# generation (READY -> AWAITING_FIRST_BOOK) and re-pend instruments, and a
# condition that carries both pending instruments and an open generation is
# read as PENDING_INSTRUMENT.
_ALLOWED_PHASE_TRANSITIONS: dict[
    ConditionSubscriptionPhase, frozenset[ConditionSubscriptionPhase]
] = {
    ConditionSubscriptionPhase.UNSUBSCRIBED: frozenset(
        {
            ConditionSubscriptionPhase.PENDING_METADATA,
            ConditionSubscriptionPhase.PENDING_INSTRUMENT,
            ConditionSubscriptionPhase.AWAITING_FIRST_BOOK,
        }
    ),
    ConditionSubscriptionPhase.PENDING_METADATA: frozenset(
        {
            ConditionSubscriptionPhase.PENDING_METADATA,
            ConditionSubscriptionPhase.PENDING_INSTRUMENT,
            ConditionSubscriptionPhase.SUBSCRIBE_ISSUED,
            ConditionSubscriptionPhase.AWAITING_FIRST_BOOK,
        }
    ),
    ConditionSubscriptionPhase.PENDING_INSTRUMENT: frozenset(
        {
            ConditionSubscriptionPhase.PENDING_METADATA,
            ConditionSubscriptionPhase.PENDING_INSTRUMENT,
            ConditionSubscriptionPhase.SUBSCRIBE_ISSUED,
            ConditionSubscriptionPhase.AWAITING_FIRST_BOOK,
            ConditionSubscriptionPhase.READY,
        }
    ),
    ConditionSubscriptionPhase.SUBSCRIBE_ISSUED: frozenset(
        {
            ConditionSubscriptionPhase.PENDING_METADATA,
            ConditionSubscriptionPhase.PENDING_INSTRUMENT,
            ConditionSubscriptionPhase.SUBSCRIBE_ISSUED,
            ConditionSubscriptionPhase.AWAITING_FIRST_BOOK,
        }
    ),
    ConditionSubscriptionPhase.AWAITING_FIRST_BOOK: frozenset(
        {
            ConditionSubscriptionPhase.PENDING_INSTRUMENT,
            ConditionSubscriptionPhase.AWAITING_FIRST_BOOK,
            ConditionSubscriptionPhase.READY,
        }
    ),
    ConditionSubscriptionPhase.READY: frozenset(
        {
            ConditionSubscriptionPhase.READY,
            ConditionSubscriptionPhase.PENDING_INSTRUMENT,
            ConditionSubscriptionPhase.AWAITING_FIRST_BOOK,
        }
    ),
}


def _transition_condition_phase(
    state: MarketSubscriptionState,
    condition_id: str,
    phase: ConditionSubscriptionPhase,
    *,
    reconcile: bool = False,
) -> None:
    """Validate then apply a phase write (guarded transition).

    Cleanup to UNSUBSCRIBED is always legal. ``reconcile`` marks a write that
    mirrors derived bookkeeping (_phase_from_derived_state) rather than a
    forward move; it shares the same table because the derived targets are a
    subset of the legal forward targets. Illegal transitions raise instead of
    silently corrupting the state machine.
    """
    if phase is ConditionSubscriptionPhase.UNSUBSCRIBED:
        _store_condition_phase(state, condition_id, phase)
        return
    source = state.condition_phases.get(
        condition_id, ConditionSubscriptionPhase.UNSUBSCRIBED
    )
    if phase not in _ALLOWED_PHASE_TRANSITIONS[source]:
        raise AssertionError(
            f"illegal condition phase transition: {source.value!r} -> {phase.value!r}"
        )
    _store_condition_phase(state, condition_id, phase)


def _phase_from_derived_state(
    strategy: _ConditionSubscriptionStateOwner,
    condition_id: str,
) -> ConditionSubscriptionPhase:
    """Reconcile the phase with the derived bookkeeping it shadows."""
    state = strategy._subscription_state
    if pending_condition_instrument_ids(strategy, condition_id):
        return ConditionSubscriptionPhase.PENDING_INSTRUMENT
    if condition_id in state.awaiting_book_sides_by_condition:
        return ConditionSubscriptionPhase.AWAITING_FIRST_BOOK
    current = state.condition_phases.get(condition_id)
    if current is ConditionSubscriptionPhase.READY:
        return ConditionSubscriptionPhase.READY
    return ConditionSubscriptionPhase.SUBSCRIBE_ISSUED


def _recompute_condition_phase(
    strategy: _ConditionSubscriptionStateOwner,
    condition_id: str,
) -> None:
    """Keep the phase coherent after a derived-bookkeeping mutation.

    Only ever reconciles conditions that already have an intent phase; never
    fabricates a phase for a condition that was never asked to subscribe.
    """
    state = strategy._subscription_state
    if condition_id not in state.condition_phases:
        return
    current = state.condition_phases.get(condition_id)
    target = _phase_from_derived_state(strategy, condition_id)
    if (
        current is ConditionSubscriptionPhase.READY
        and target is ConditionSubscriptionPhase.PENDING_INSTRUMENT
    ):
        # READY re-entry: a rotation/recovery re-pended instruments while the
        # condition was READY. Treat re-pending as a fresh book generation:
        # begin clears the stale first-bilateral marker and re-establishes the
        # awaiting sides, so the condition can reach READY again once the
        # instruments resolve — without begin, the marker would survive into
        # SUBSCRIBE_ISSUED and wedge the condition unready until a restart.
        # Every subscription host implements _framework_now (the Nautilus
        # framework clock); the wall clock is deliberately not used here to
        # keep the runtime deterministic.
        framework_now = getattr(strategy, "_framework_now", None)
        if callable(framework_now):
            begin_market_book_generation(
                strategy,
                condition_id,
                now=cast(Callable[[], datetime], framework_now)(),
            )
    _transition_condition_phase(
        state,
        condition_id,
        target,
        reconcile=True,
    )


def _condition_ids_for_instrument(
    strategy: _SubscriptionStrategy,
    key: str,
) -> tuple[str, ...]:
    registry = strategy.registry
    if registry is None:
        return ()
    matches: list[str] = []
    for condition_id in registry.condition_ids():
        pair = registry.by_condition(condition_id)
        if pair is None:
            continue
        for token_id in (pair.up.token_id, pair.down.token_id):
            resolved = registry.instrument_id_for_token(token_id)
            if resolved is not None and _instrument_key(resolved) == key:
                matches.append(condition_id)
                break
    return tuple(matches)


def _refresh_phase_for_instrument(
    strategy: _SubscriptionStrategy,
    key: str,
) -> None:
    for condition_id in _condition_ids_for_instrument(strategy, key):
        _recompute_condition_phase(strategy, condition_id)


class _SubscriptionStrategy(_ConditionSubscriptionStateOwner, Protocol):
    @property
    def cache(self) -> object | None: ...

    book_type: str
    unsubscribe_exited: bool
    _startup_condition_ids: tuple[str, ...]
    _active_condition_ids: set[str]
    _asset_condition_ids: dict[str, tuple[str, ...]]
    _subscription_assets: frozenset[str]
    _subscription_timeframes: frozenset[str]
    _untradable_quote_sides_by_condition: dict[str, frozenset[Side]]
    _stale_orderbook_recovery_by_condition: dict[str, dict[Side, float]]
    _runtime_readiness_reason_by_condition: dict[str, str]
    _runtime_readiness_miss_condition_ids: set[str]
    def _readiness_detail(
        self,
        condition_id: str,
        *,
        now: datetime,
    ) -> dict[str, object]: ...

    def _note_runtime_readiness(
        self,
        condition_id: str,
        *,
        ready: bool,
        status: StrategyStatus | None = None,
        reason: str | None = None,
    ) -> None: ...

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
    timeframe = registry.timeframe_for_instrument(_instrument_key(instrument_id))
    if timeframe is None:
        return None
    return polymarket_data_client_id(timeframe)


def _subscribe_market_condition(
    strategy: _SubscriptionStrategy,
    registry: MarketCatalog,
    condition_id: str,
    *,
    now: datetime,
    allow_inactive: bool = False,
) -> None:
    if not condition_in_subscription_scope(strategy, condition_id):
        return
    if not allow_inactive and condition_id not in strategy._active_condition_ids:
        return
    state = strategy._subscription_state
    current_phase = state.condition_phases.get(
        condition_id, ConditionSubscriptionPhase.UNSUBSCRIBED
    )
    first_intent = current_phase not in _SUBSCRIBING_PHASES
    if not first_intent and not pending_condition_instrument_ids(
        strategy,
        condition_id,
    ):
        _recompute_condition_phase(strategy, condition_id)
        return
    instrument_ids = _instrument_ids(registry, (condition_id,))
    if not instrument_ids:
        _transition_condition_phase(
            state,
            condition_id,
            ConditionSubscriptionPhase.PENDING_METADATA,
        )
        return
    if first_intent and condition_id in strategy._active_condition_ids:
        begin_market_book_generation(strategy, condition_id, now=now)
    for instrument_id in condition_instruments(strategy, condition_id):
        _ = subscribe_market_instrument(strategy, instrument_id)
    # Intent only — book readiness confirms feed, not subscribe() return.
    state.subscribe_intent_started_at_by_condition.setdefault(
        condition_id,
        now.astimezone(UTC),
    )
    _transition_condition_phase(
        state,
        condition_id,
        _phase_from_derived_state(strategy, condition_id),
        reconcile=True,
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
        cached = getter(_nautilus_instrument_id(instrument_id))
    except (LookupError, TypeError):
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
    state = strategy._subscription_state
    if key in state.subscribed_instrument_ids:  # pyright: ignore[reportPrivateUsage]
        state.pending_instrument_ids.discard(key)  # pyright: ignore[reportPrivateUsage]
        _refresh_phase_for_instrument(strategy, key)
        return True
    client_id = _client_id_for_instrument(strategy, instrument_id)
    if not instrument_visible_in_cache(strategy, instrument_id):
        state.pending_instrument_ids.add(key)
        _refresh_phase_for_instrument(strategy, key)
        return False
    state.pending_instrument_ids.discard(key)
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
    state.subscribed_instrument_ids.add(key)
    _refresh_phase_for_instrument(strategy, key)
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
                set(strategy._active_condition_ids)
                | {
                    condition_id
                    for condition_id, phase in strategy._subscription_state.condition_phases.items()  # pyright: ignore[reportPrivateUsage]
                    if phase
                    is not ConditionSubscriptionPhase.UNSUBSCRIBED
                }
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
    state = strategy._subscription_state
    # Retire every condition's book-generation lifecycle state (both open
    # generations and READY first-book markers) so a delayed book callback
    # cannot revive a torn-down lifecycle and no residue outlives teardown.
    for condition_id in tuple(
        {
            *state.awaiting_book_sides_by_condition,
            *state.book_generation_started_at_by_condition,
            *state.first_bilateral_book_at_by_condition,
            *state.first_bilateral_book_latency_ms_by_condition,
        }
    ):
        retire_market_book_generation(strategy, condition_id, clear_history=True)
    state.pending_instrument_ids.clear()
    state.subscribe_intent_started_at_by_condition.clear()
    state.condition_phases.clear()


def unsubscribe_market_conditions(
    strategy: _SubscriptionStrategy,
    condition_ids: Sequence[str],
) -> None:
    if strategy.registry is None:
        return
    for condition_id in condition_ids:
        for instrument_id in condition_instruments(strategy, condition_id):
            _ = unsubscribe_market_instrument(strategy, instrument_id)
        clear_condition_lifecycle_state(strategy, condition_id)


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
    """Clear the condition-level subscription phase and its derived bookkeeping.

    Keeps last_book history for observability; the exit/retire path that wants
    history gone goes through clear_condition_lifecycle_state.
    """
    state = strategy._subscription_state
    state.condition_phases.pop(condition_id, None)
    state.subscribe_intent_started_at_by_condition.pop(condition_id, None)
    if strategy.registry is not None:
        for instrument_id in _instrument_ids(strategy.registry, (condition_id,)):
            key = _instrument_key(instrument_id)
            state.pending_instrument_ids.discard(key)
            if clear_subscribed:
                state.subscribed_instrument_ids.discard(key)  # pyright: ignore[reportPrivateUsage]
    retire_market_book_generation(strategy, condition_id, clear_history=False)


class _LifecycleCleanupOwner(_ConditionSubscriptionStateOwner, Protocol):
    _untradable_quote_sides_by_condition: dict[str, frozenset[Side]]
    _stale_orderbook_recovery_by_condition: dict[str, dict[Side, float]]
    _runtime_readiness_reason_by_condition: dict[str, str]
    _runtime_readiness_miss_condition_ids: set[str]


def clear_condition_lifecycle_state(
    strategy: _LifecycleCleanupOwner,
    condition_id: str,
    *,
    clear_subscribed: bool = True,
    clear_history: bool = False,
) -> None:
    """Single cleanup entry for a condition leaving the active set.

    Clears the condition-level subscription phase and every orthogonal
    readiness marker (_untradable_quote_sides, _stale_orderbook_recovery,
    runtime readiness reason/miss) so no lifecycle state outlives the condition.
    last_book_* history is kept for observability by default (clear_history
    mirrors clear_condition_subscription_state); pass clear_history=True on the
    exit/retire path when the observability history should go too.
    """
    cancel_recovery = getattr(
        strategy,
        "_cancel_market_data_recovery_evaluation",
        None,
    )
    if callable(cancel_recovery):
        cancel_recovery(condition_id)
    clear_condition_subscription_state(
        strategy,
        condition_id,
        clear_subscribed=clear_subscribed,
    )
    if clear_history:
        retire_market_book_generation(strategy, condition_id, clear_history=True)
    _ = strategy._untradable_quote_sides_by_condition.pop(condition_id, None)
    _ = strategy._stale_orderbook_recovery_by_condition.pop(condition_id, None)
    _ = strategy._runtime_readiness_reason_by_condition.pop(condition_id, None)
    _ = strategy._runtime_readiness_miss_condition_ids.discard(condition_id)


def begin_market_book_generation(
    strategy: _SubscriptionStateOwner,
    condition_id: str,
    *,
    now: datetime,
    awaiting_sides: Sequence[Side] | None = None,
) -> None:
    """Invalidate cached-book readiness before a real subscribe attempt."""
    observed = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    observed_utc = observed.astimezone(UTC)
    state = strategy._subscription_state
    awaiting = set(
        (Side.UP, Side.DOWN) if awaiting_sides is None else awaiting_sides
    )
    state.awaiting_book_sides_by_condition[condition_id] = awaiting
    state.book_generation_started_at_by_condition[condition_id] = observed_utc
    # A new generation owns a fresh set of recovery intents. Only begin may
    # raise the validity clock.
    state.pending_book_recovery_sides_by_condition.pop(condition_id, None)
    # Drop prior receipts for sides this generation awaits so detail cannot
    # show "already received" while observe rejects received < started_at.
    _clear_awaiting_side_book_receipts(state, condition_id, awaiting)
    # Total-stall clock starts on the first wait and survives every
    # resubscription (setdefault); cleared only on book-ready / retire / clear.
    state.book_stalled_started_at_by_condition.setdefault(
        condition_id,
        observed_utc,
    )
    state.first_bilateral_book_at_by_condition.pop(
        condition_id, None
    )
    strategy._subscription_state.first_bilateral_book_latency_ms_by_condition.pop(
        condition_id, None
    )
    _transition_condition_phase(
        strategy._subscription_state,
        condition_id,
        ConditionSubscriptionPhase.AWAITING_FIRST_BOOK,
    )


def _clear_awaiting_side_book_receipts(
    state: MarketSubscriptionState,
    condition_id: str,
    awaiting: set[Side],
) -> None:
    if not awaiting:
        return
    receipts = state.last_book_received_at_by_condition.get(condition_id)
    if receipts is not None:
        for side in awaiting:
            _ = receipts.pop(side, None)
        if not receipts:
            _ = state.last_book_received_at_by_condition.pop(condition_id, None)
    books = state.last_book_at_by_condition.get(condition_id)
    if books is not None:
        for side in awaiting:
            _ = books.pop(side, None)
        if not books:
            _ = state.last_book_at_by_condition.pop(condition_id, None)


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
    state = strategy._subscription_state
    _record_market_book_side(
        state,
        condition_id,
        side,
        received=received,
        observed_book=observed_book,
    )
    pending = state.awaiting_book_sides_by_condition.get(condition_id)
    if pending is None:
        return True
    started_at = state.book_generation_started_at_by_condition.get(condition_id)
    if started_at is not None and received < started_at:
        return False
    _complete_book_recovery_receipt(state, condition_id, side)
    pending.discard(side)
    if pending:
        return False
    finish_market_book_generation(
        state,
        condition_id,
        received_at=received,
        started_at=started_at,
    )
    return True


def _complete_book_recovery_receipt(
    state: MarketSubscriptionState,
    condition_id: str,
    side: Side,
) -> None:
    pending = state.pending_book_recovery_sides_by_condition.get(condition_id)
    if pending is None:
        return
    pending.discard(side)
    if not pending:
        _ = state.pending_book_recovery_sides_by_condition.pop(condition_id, None)


def _record_market_book_side(
    state: MarketSubscriptionState,
    condition_id: str,
    side: Side,
    *,
    received: datetime,
    observed_book: datetime,
) -> None:
    last_receipts = (
        state.last_book_received_at_by_condition.setdefault(condition_id, {})
    )
    previous_received = last_receipts.get(side)
    if previous_received is None or received >= previous_received:
        last_receipts[side] = received
    last_books = state.last_book_at_by_condition.setdefault(condition_id, {})
    previous = last_books.get(side)
    if previous is None or observed_book >= previous:
        last_books[side] = observed_book


def finish_market_book_generation(
    state: MarketSubscriptionState,
    condition_id: str,
    *,
    received_at: datetime,
    started_at: datetime | None,
) -> None:
    if condition_id not in state.awaiting_book_sides_by_condition:
        # Late/delayed callback after cleanup (or a duplicate): never revive a
        # retired lifecycle. Record the observation for observability only.
        return
    receipts = state.last_book_received_at_by_condition.get(condition_id, {})
    ready_at = max(receipts.values(), default=received_at)
    state.awaiting_book_sides_by_condition.pop(condition_id)
    state.book_generation_started_at_by_condition.pop(condition_id, None)
    state.pending_book_recovery_sides_by_condition.pop(condition_id, None)
    state.book_stalled_started_at_by_condition.pop(condition_id, None)
    state.first_bilateral_book_at_by_condition[condition_id] = ready_at
    # Remembers this active period reached READY so the stale-repair re-awaiting
    # path is never abandoned via the book-stall clock (see W2 semantics).
    state.first_bilateral_book_ever_at_by_condition.setdefault(
        condition_id,
        ready_at,
    )
    if started_at is not None:
        latency_ms = max(0, int((ready_at - started_at).total_seconds() * 1000))
        state.first_bilateral_book_latency_ms_by_condition[condition_id] = latency_ms
    # A completed bilateral book proves the feed is moving again; drop the
    # global recovery cooldown so a later stall may batch immediately.
    clear_global_book_recovery_batch(state)
    _transition_condition_phase(state, condition_id, ConditionSubscriptionPhase.READY)


def market_book_generation_ready(
    strategy: _ConditionSubscriptionStateOwner,
    condition_id: str,
) -> bool:
    """True only for a condition that has reached READY.

    The phase is the source of truth: a never-subscribed or already-cleaned
    condition must not be treated as book-generation ready.
    """
    return (
        condition_phase(strategy, condition_id) is ConditionSubscriptionPhase.READY
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
    strategy._subscription_state.pending_book_recovery_sides_by_condition.pop(
        condition_id,
        None,
    )
    strategy._subscription_state.book_stalled_started_at_by_condition.pop(
        condition_id,
        None,
    )
    strategy._subscription_state.first_bilateral_book_at_by_condition.pop(
        condition_id,
        None,
    )
    strategy._subscription_state.first_bilateral_book_ever_at_by_condition.pop(
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


def _book_generation_stalled(
    strategy: _SubscriptionStrategy,
    condition_id: str,
    *,
    now: datetime,
) -> bool:
    """True when the condition awaits its first book past the stall window."""
    state = strategy._subscription_state
    if condition_id not in state.awaiting_book_sides_by_condition:
        return False
    if pending_condition_instrument_ids(strategy, condition_id):
        # Still waiting on instrument metadata, not on the book feed.
        return False
    generation_started_at = state.book_generation_started_at_by_condition.get(
        condition_id
    )
    if generation_started_at is None:
        return False
    return (now.astimezone(UTC) - generation_started_at).total_seconds() > (
        _BOOK_GENERATION_STALL_SEC
    )


def condition_needs_book_recovery(
    strategy: _SubscriptionStrategy,
    condition_id: str,
    *,
    now: datetime,
) -> bool:
    """True when a once-READY condition currently needs a wire retry.

    An awaiting-first-book condition that has idled past the stall window and a
    stale-orderbook condition both need a refresh; a healthy READY condition, a
    pending-instrument wait, or a freshly restarted generation (inside the stall
    window) do not. Never-READY warmup conditions are excluded — their first-book
    wait is governed by the per-condition abandon clock, not the global stall.
    """
    state = strategy._subscription_state
    if condition_id not in state.first_bilateral_book_ever_at_by_condition:
        return False
    if pending_condition_instrument_ids(strategy, condition_id):
        return False
    if condition_id in state.awaiting_book_sides_by_condition:
        return _book_generation_stalled(strategy, condition_id, now=now)
    return bool(
        strategy._stale_orderbook_recovery_by_condition.get(condition_id)
    )


def global_book_feed_stalled(
    strategy: _SubscriptionStrategy,
    condition_ids: Sequence[str] | None = None,
    *,
    now: datetime,
) -> bool:
    """True when every once-READY active condition is awaiting the same recovery.

    A global book-feed event (the Polymarket WS dropped with 'no ping received'
    and every previously-READY market lost its book at once) is distinct from a
    per-condition market that simply went dark. While every once-READY condition
    needs recovery, per-condition refresh storms cannot help — they only race the
    adapter's own transport recovery, so the coordinated response is one bounded
    batch rather than a per-condition retry. The moment any once-READY condition
    recovers, ``all()`` turns false and the gate releases.
    """
    once_ready_ids = [
        condition_id
        for condition_id in (condition_ids or ())
        if condition_id
        in strategy._subscription_state.first_bilateral_book_ever_at_by_condition
    ]
    if not once_ready_ids:
        return False
    return all(
        condition_needs_book_recovery(strategy, condition_id, now=now)
        for condition_id in once_ready_ids
    )


def global_recovery_batch_due(
    strategy: _SubscriptionStrategy,
    *,
    now: datetime,
) -> bool:
    """True when a new coordinated global recovery batch may be dispatched.

    Kept bounded by the cooldown window since the last batch: a global feed
    outage is not resolved by re-arming every condition's wire retry every 10s
    heartbeat — the adapter's reconnect/replay needs time to converge.
    """
    batch_at = strategy._subscription_state.global_book_recovery_batch_at
    if batch_at is None:
        return True
    batch_at_utc = (
        batch_at if batch_at.tzinfo is not None else batch_at.replace(tzinfo=UTC)
    ).astimezone(UTC)
    return (now.astimezone(UTC) - batch_at_utc).total_seconds() >= (
        _GLOBAL_RECOVERY_COOLDOWN_SEC
    )


def clear_global_book_recovery_batch(state: MarketSubscriptionState) -> None:
    """Drop the batch cooldown after any completed bilateral book.

    A freshly recovered condition proves the feed is flowing again, so the next
    stall must be allowed to batch immediately instead of waiting out the prior
    window.
    """
    state.global_book_recovery_batch_at = None


def log_suppressed_book_recovery(
    strategy: _SubscriptionStrategy,
    condition_id: str,
    *,
    now: datetime,
) -> None:
    logger.info(
        "condition_book_recovery_suppressed",
        extra={
            "strategy": getattr(strategy, "strategy_name", None),
            "condition_id": condition_id,
            "suppressed_at": now.astimezone(UTC).isoformat(),
            "cooldown_sec": _GLOBAL_RECOVERY_COOLDOWN_SEC,
        },
    )


def abandon_book_stalled_condition(
    strategy: _SubscriptionStrategy,
    condition_id: str,
    *,
    stall_sec: float,
) -> bool:
    """Drop a condition whose book never materialized despite resubscription.

    Book generation that is still stalled past _BOOK_GENERATION_ABANDON_SEC is
    treated as a market with no book data — an unrecoverable condition (the
    feed never sends a snapshot for it, so re-subscribing is futile). Abandoning
    removes the condition from the active set and every tracked lifecycle marker
    so it stops generating readiness misses. Repeated resubscription (repair A)
    is reserved for the recoverable case: a dropped subscription on a market
    that does have a book.

    Returns True when the condition was abandoned. Idempotent: once removed from
    the active set, a subsequent heartbeat never reaches this path again, and a
    direct second call is a no-op (the condition is no longer in
    _active_condition_ids).
    """
    if condition_id not in strategy._active_condition_ids:
        return False
    instruments = condition_instruments(strategy, condition_id)
    strategy._active_condition_ids.discard(condition_id)
    for instrument_id in instruments:
        _ = unsubscribe_market_instrument(strategy, instrument_id)
    clear_condition_lifecycle_state(
        strategy,
        condition_id,
        clear_history=True,
    )
    # Clear the persisted readiness-miss key so the liveness heartbeat stops
    # tracking this condition (mirrors retire_expired_condition's ready=True).
    strategy._note_runtime_readiness(condition_id, ready=True)
    logger.info(
        "condition_abandoned_no_book",
        extra={
            "condition_id": condition_id,
            "stall_sec": round(stall_sec, 3),
            "instrument_ids": [_instrument_key(iid) for iid in instruments],
        },
    )
    return True


def _refresh_market_instrument(
    strategy: _SubscriptionStrategy,
    instrument_id: object,
) -> None:
    instrument_id = _nautilus_instrument_id(instrument_id)
    client_id = _client_id_for_instrument(strategy, instrument_id)
    refresh_strategy = cast(_BookRefreshStrategy, cast(object, strategy))
    _ = refresh_strategy.refresh_book_subscription(
        instrument_id,
        client_id=client_id,
    )


def _dispatch_book_recovery(
    strategy: _SubscriptionStrategy,
    condition_id: str,
    targets: Sequence[tuple[Side, object]],
) -> tuple[object, ...]:
    state = strategy._subscription_state
    dispatched: list[object] = []
    dispatched_sides: list[Side] = []
    try:
        for side, instrument_id in targets:
            _refresh_market_instrument(strategy, instrument_id)
            dispatched.append(instrument_id)
            dispatched_sides.append(side)
            state.pending_book_recovery_sides_by_condition.setdefault(
                condition_id,
                set(),
            ).add(side)
    except Exception:
        logger.exception(
            "book_recovery_batch_failed",
            extra={
                "strategy": getattr(strategy, "strategy_name", None),
                "condition_id": condition_id,
                "dispatched_instrument_ids": [str(value) for value in dispatched],
                "pending_sides": sorted(side.value for side in dispatched_sides),
            },
        )
        raise
    if dispatched:
        logger.info(
            "book_recovery_batch_dispatched",
            extra={
                "strategy": getattr(strategy, "strategy_name", None),
                "condition_id": condition_id,
                "instrument_ids": [str(value) for value in dispatched],
                "instrument_count": len(dispatched),
            },
        )
    return tuple(dispatched)


def _awaiting_condition_recovery_targets(
    strategy: _SubscriptionStrategy,
    condition_id: str,
) -> tuple[tuple[Side, object], ...]:
    registry = strategy.registry
    state = strategy._subscription_state
    awaiting = state.awaiting_book_sides_by_condition.get(condition_id)
    if registry is None or not awaiting:
        return ()
    pair = registry.by_condition(condition_id)
    if pair is None:
        return ()
    token_by_side = {
        Side.UP: pair.up.token_id,
        Side.DOWN: pair.down.token_id,
    }
    already_pending = state.pending_book_recovery_sides_by_condition.get(
        condition_id,
        set(),
    )
    return tuple(
        (side, instrument_id)
        for side in (Side.UP, Side.DOWN)
        if side in awaiting
        if side not in already_pending
        if (
            instrument_id := registry.instrument_id_for_token(token_by_side[side])
        )
        is not None
    )


def _total_stall_started_at(
    strategy: _SubscriptionStrategy,
    condition_id: str,
) -> datetime | None:
    """Total-stall start for a condition.

    Falls back to the generation clock for states created before the dedicated
    total-stall clock existed.
    """
    state = strategy._subscription_state
    return state.book_stalled_started_at_by_condition.get(condition_id) or (
        state.book_generation_started_at_by_condition.get(condition_id)
    )


def _abandon_if_total_stall_exceeded(
    strategy: _SubscriptionStrategy,
    condition_id: str,
    *,
    total_stalled_at: datetime,
    now: datetime,
) -> bool:
    """Abandon the condition when total stall crosses the abandon threshold.

    The caller must return False when this returns True. Pending recovery
    intent must never bypass this check.
    """
    stall_sec = (now.astimezone(UTC) - total_stalled_at).total_seconds()
    if stall_sec < _BOOK_GENERATION_ABANDON_SEC:
        return False
    _ = abandon_book_stalled_condition(strategy, condition_id, stall_sec=stall_sec)
    return True


def _resubscribe_and_begin_generation(
    strategy: _SubscriptionStrategy,
    condition_id: str,
    *,
    now: datetime,
) -> tuple[tuple[object, ...], tuple[object, ...]] | None:
    state = strategy._subscription_state
    awaiting_sides = state.awaiting_book_sides_by_condition.get(condition_id)

    # New stale repair seeds stale sides. An existing generation preserves the
    # awaiting set so a healthy side is never reset.
    if awaiting_sides is None:
        awaiting_sides = set(
            strategy._stale_orderbook_recovery_by_condition.get(condition_id, {})
        )
        if not awaiting_sides:
            return None
        begin_market_book_generation(
            strategy,
            condition_id,
            now=now,
            awaiting_sides=tuple(awaiting_sides),
        )
    else:
        if not awaiting_sides:
            return None
    targets = _awaiting_condition_recovery_targets(strategy, condition_id)
    if not targets:
        return None
    instruments = tuple(instrument_id for _side, instrument_id in targets)
    dispatched = _dispatch_book_recovery(strategy, condition_id, targets)
    return instruments, dispatched


def _recovery_log_extra(
    state: MarketSubscriptionState,
    condition_id: str,
    instruments: Sequence[object],
    *,
    stall_sec: float,
    dispatched: Sequence[object] = (),
) -> dict[str, object]:
    dispatched_keys = {
        _instrument_key(instrument_id) for instrument_id in (dispatched or ())
    }
    instrument_keys = [_instrument_key(iid) for iid in instruments]
    return {
        "condition_id": condition_id,
        "stall_sec": stall_sec,
        "instrument_ids": instrument_keys,
        "dispatched_instrument_ids": sorted(dispatched_keys),
        "awaiting_sides": sorted(
            side.value
            for side in state.awaiting_book_sides_by_condition.get(condition_id, ())
        ),
        "pending_recovery_sides": sorted(
            side.value
            for side in state.pending_book_recovery_sides_by_condition.get(
                condition_id,
                (),
            )
        ),
    }


def _first_book_recovery_due(
    strategy: _SubscriptionStrategy,
    condition_id: str,
    *,
    now: datetime,
) -> bool:
    state = strategy._subscription_state
    if pending_condition_instrument_ids(strategy, condition_id):
        return False
    if condition_id not in state.first_bilateral_book_ever_at_by_condition:
        total_stalled_at = _total_stall_started_at(strategy, condition_id)
        if total_stalled_at is not None and _abandon_if_total_stall_exceeded(
            strategy,
            condition_id,
            total_stalled_at=total_stalled_at,
            now=now,
        ):
            return False
    awaiting = state.awaiting_book_sides_by_condition.get(condition_id, set())
    pending = state.pending_book_recovery_sides_by_condition.get(condition_id, set())
    return not awaiting.issubset(pending) and _book_generation_stalled(
        strategy,
        condition_id,
        now=now,
    )


def force_resubscribe_if_book_stalled(
    strategy: _SubscriptionStrategy,
    condition_id: str,
    *,
    now: datetime,
) -> bool:
    """Submit each missing-side recovery intent once for this generation."""
    state = strategy._subscription_state
    if not _first_book_recovery_due(
        strategy,
        condition_id,
        now=now,
    ):
        return False
    generation_started_at = state.book_generation_started_at_by_condition.get(
        condition_id
    )
    attempt = _resubscribe_and_begin_generation(
        strategy, condition_id, now=now
    )
    if attempt is None:
        return False
    instruments, dispatched = attempt
    stall_sec = (
        round((now.astimezone(UTC) - generation_started_at).total_seconds(), 3)
        if generation_started_at is not None
        else _BOOK_GENERATION_STALL_SEC
    )
    logger.info(
        "condition_book_refresh_requested",
        extra=_recovery_log_extra(
            state,
            condition_id,
            instruments,
            stall_sec=stall_sec,
            dispatched=dispatched,
        ),
    )
    return True


def _stale_book_recovery_due(
    strategy: _SubscriptionStrategy,
    condition_id: str,
    *,
    now: datetime,
) -> tuple[datetime, datetime] | None:
    state = strategy._subscription_state
    if (
        condition_id in state.awaiting_book_sides_by_condition
        or condition_id not in strategy._stale_orderbook_recovery_by_condition
        or pending_condition_instrument_ids(strategy, condition_id)
    ):
        return None
    now_utc = (now if now.tzinfo is not None else now.replace(tzinfo=UTC)).astimezone(
        UTC
    )
    total_stalled_at = state.book_stalled_started_at_by_condition.setdefault(
        condition_id, now_utc
    )
    generation_started_at = state.book_generation_started_at_by_condition.get(condition_id)
    if generation_started_at is not None and (
        now_utc - generation_started_at
    ).total_seconds() <= (
        _BOOK_GENERATION_STALL_SEC
    ):
        return None
    return now_utc, total_stalled_at


def force_resubscribe_if_stale_orderbook(
    strategy: _SubscriptionStrategy,
    condition_id: str,
    *,
    now: datetime,
) -> bool:
    """Rebuild a once-READY condition's stale book (Gap B): not in the awaiting
    map, so the first-book path never fires. Resubscribe only — never abandon
    via the book-stall clock: a global/silent feed outage is reported by
    liveness/data-starvation, not by silently dropping active conditions (W2)."""
    state = strategy._subscription_state
    retry_due = _stale_book_recovery_due(
        strategy,
        condition_id,
        now=now,
    )
    if retry_due is None:
        return False
    now_utc, total_stalled_at = retry_due
    attempt = _resubscribe_and_begin_generation(
        strategy,
        condition_id,
        now=now_utc,
    )
    if attempt is None:
        return False
    instruments, dispatched = attempt
    _ = strategy._stale_orderbook_recovery_by_condition.pop(condition_id, None)
    stall_sec = round((now_utc - total_stalled_at).total_seconds(), 3)
    logger.info(
        "condition_book_refresh_requested",
        extra=_recovery_log_extra(
            state,
            condition_id,
            instruments,
            stall_sec=stall_sec,
            dispatched=dispatched,
        ),
    )
    return True
