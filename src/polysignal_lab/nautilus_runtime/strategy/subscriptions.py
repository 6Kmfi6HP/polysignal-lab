from __future__ import annotations

import logging

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
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

# A strategy recovery command has no wire ACK. Keep its intent pending long
# enough for adapter reconnect/replay to converge, then permit another atomic
# refresh if no qualifying book receipt arrived.
_BOOK_RECOVERY_RETRY_SEC = 120.0

# A once-READY condition with no recent book receipts is rebuilt proactively,
# before the 300s liveness/data-starvation window can restart the container.
# This closes the silent-WS-death gap where phase stays READY and neither the
# awaiting nor stale-orderbook marker exists.
_STALE_RECEIPT_THRESHOLD_SEC = 240.0

# Phase 1 (drain) and Phase 2 (restore) of a real refresh must land in
# different DataEngine command-queue turns. The engine forwards an unsubscribe
# only while its book topic has zero subscribers, and the managed-book handler
# re-registration within the same synchronous turn makes has_subscribers() true
# forever — an adaptive refresh that drains and restores back-to-back is a wire
# no-op (issue69 live evidence: 44 dispatches, 0 wire subscribes). Restore is
# deferred until the drain has aged past this window so the engine tears the
# old subscription down first, letting the re-subscribe reach Polymarket's WS
# and re-push the initial book snapshot.
_BOOK_RECOVERY_RESTORE_DELAY_SEC = 1.0

# How long a no-book abandonment suppresses re-entry from the universe feed.
# Bounded so a temporary venue outage (minutes-scale) does not turn into a
# process-lifetime blackout for the affected markets; after the window the
# condition is retried once and re-abandoned only if the feed is still silent.
_NO_BOOK_SUPPRESS_SEC = 900.0

logger = logging.getLogger(__name__)

# All strategies in one TradingNode share the underlying Polymarket adapter
# tokens. Coordinate at process scope so separately constructed strategy
# catalogs cannot duplicate the same wire refresh.
_global_book_recovery_times: dict[str, datetime] = {}
_global_subscription_strategies: dict[int, object] = {}
_global_quote_subscription_owners: dict[int, object] = {}
# Phase-1 drained instruments awaiting a delayed Phase-2 restore. Keyed by the
# instrument key; the stored tuple keeps the nautilus object for the restore.
_global_book_restore_pending: dict[str, tuple[object, datetime]] = {}


def _register_subscription_strategy(strategy: object) -> None:  # pyright: ignore[reportUnusedFunction]
    """Register one owner of the process-wide adapter subscriptions."""
    _global_subscription_strategies[id(strategy)] = strategy


def _unregister_subscription_strategy(strategy: object) -> None:  # pyright: ignore[reportUnusedFunction]
    """Remove a stopped strategy from process-wide recovery coordination."""
    _ = _global_subscription_strategies.pop(id(strategy), None)


def _register_quote_subscription_owner(owner: object) -> None:  # pyright: ignore[reportUnusedFunction]
    """Register a non-strategy owner of adapter quote subscriptions."""
    _global_quote_subscription_owners[id(owner)] = owner


def _unregister_quote_subscription_owner(owner: object) -> None:  # pyright: ignore[reportUnusedFunction]
    """Remove a stopped quote owner from recovery coordination."""
    _ = _global_quote_subscription_owners.pop(id(owner), None)


def _clear_global_book_recovery_state() -> None:  # pyright: ignore[reportUnusedFunction]
    """Reset process recovery coordination during node teardown/tests."""
    _global_book_recovery_times.clear()
    _global_subscription_strategies.clear()
    _global_quote_subscription_owners.clear()
    _global_book_restore_pending.clear()


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
    book_recovery_dispatched_at_by_condition: dict[str, dict[Side, datetime]] = field(
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
    # Project-side replay boundary: set when a local recovery dependency boundary
    # is sent after a reconnect/refresh, and cleared only by a valid managed book
    # receipt for this generation. A true wire ACK is not available, so this is
    # intentionally an unconfirmed intent marker, never a substitute for the
    # book receipt that drives READY.
    adapter_replay_started_at_by_condition: dict[str, datetime] = field(
        default_factory=dict
    )

    # How many book-recovery batches have been dispatched for the current
    # generation (bounded single-flight observability; never reset by retries
    # within the same generation so the timeout detail can report attempts).
    book_recovery_attempt_count_by_condition: dict[str, int] = field(
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
    pending = pending_condition_instrument_ids(strategy, condition_id)
    instruments = condition_instruments(strategy, condition_id)
    all_subscribed = all(
        _instrument_key(instrument_id)
        in state.subscribed_instrument_ids
        for instrument_id in instruments
    )
    if pending and not all_subscribed:
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


def _instrument_restore_allowed(
    strategy: _SubscriptionStrategy,
    instrument_id: object,
    *,
    now: datetime,
) -> bool:
    """True only when every mapped condition is known and not expired.

    Unknown instruments are never safely restorable: the payload may target a
    resolved/closed market and trigger Polymarket code=1008, while this process
    has no metadata to prove otherwise.
    """
    registry = strategy.registry
    if registry is None:
        return False
    key = _instrument_key(instrument_id)
    conditions = _condition_ids_for_instrument(strategy, key)
    if not conditions:
        return False
    for condition_id in conditions:
        pair = registry.by_condition(condition_id)
        if pair is None:
            return False
        end_ts = getattr(pair, "end_ts", None)
        if end_ts is not None and now >= end_ts:
            return False
    return True


def _refresh_phase_for_instrument(
    strategy: _SubscriptionStrategy,
    key: str,
) -> None:
    for condition_id in _condition_ids_for_instrument(strategy, key):
        _recompute_condition_phase(strategy, condition_id)


class _QuoteSubscriptionOwner(Protocol):
    def recovery_quote_client_id(self, instrument_id: object) -> object | None: ...

    def subscribe_quotes(
        self,
        instrument_id: object,
        client_id: object | None = None,
    ) -> object: ...

    def unsubscribe_quotes(
        self,
        instrument_id: object,
        client_id: object | None = None,
    ) -> object: ...


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
    pair = (
        None
        if strategy.registry is None
        else strategy.registry.by_condition(condition_id)
    )
    asset = (
        pair.asset
        if pair is not None
        else None
        if asset_by_condition is None
        else asset_by_condition.get(condition_id)
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
    if _subscribe_suppressed(strategy, condition_id, now=now):
        return
    state = strategy._subscription_state
    current_phase = state.condition_phases.get(
        condition_id, ConditionSubscriptionPhase.UNSUBSCRIBED
    )
    first_intent = current_phase not in _SUBSCRIBING_PHASES
    if not first_intent and not pending_condition_instrument_ids(strategy, condition_id):
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
    """Subscribe quotes/trades/book, dispatching the wire request even when the
    instrument is not yet Cache-visible.

    Locked pyo3 Strategy API (nautilus_trader 1.231): subscribe_quotes /
    subscribe_trades / subscribe_book_deltas (not Cython long names).

    issue69: after a window rotation the provider refresh never re-loads
    new-slot instruments (update_instruments_interval relies on a connection
    that still carries the resolved old slot), so gating the subscribe on
    Cache visibility left the condition PENDING_METADATA forever and every
    rotation ended in a watchdog data-starvation restart. The data client's
    auto_load/resolve_poll paths only run when the wire request actually
    reaches it, so the request is always dispatched; the key additionally
    stays pending so on_instrument_available reconciles the phase once the
    provider does load the instrument.
    """
    instrument_id = _nautilus_instrument_id(instrument_id)
    key = _instrument_key(instrument_id)
    state = strategy._subscription_state
    if key in state.subscribed_instrument_ids:  # pyright: ignore[reportPrivateUsage]
        state.pending_instrument_ids.discard(key)
        _refresh_phase_for_instrument(strategy, key)
        return True
    client_id = _client_id_for_instrument(strategy, instrument_id)
    if not instrument_visible_in_cache(strategy, instrument_id):
        state.pending_instrument_ids.add(key)
        _refresh_phase_for_instrument(strategy, key)
    else:
        state.pending_instrument_ids.discard(key)
    try:
        _dispatch_market_subscriptions(strategy, instrument_id, client_id)
    except RuntimeError:
        if not instrument_visible_in_cache(strategy, instrument_id):
            state.pending_instrument_ids.add(key)
            _refresh_phase_for_instrument(strategy, key)
        return False
    # Metadata may still be pending while the wire request is live; keep this
    # key pending for lookup/readiness, and mark subscribed because the engine
    # request was accepted. on_instrument_available later clears the pending key.
    state.subscribed_instrument_ids.add(key)
    _refresh_phase_for_instrument(strategy, key)
    return True


def _dispatch_market_subscriptions(
    strategy: _SubscriptionStrategy,
    instrument_id: object,
    client_id: object | None,
) -> None:
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


def on_instrument_available(
    strategy: _SubscriptionStrategy,
    instrument: object,
) -> bool:
    """After provider load / on_instrument: subscribe if still needed."""
    raw_id = getattr(instrument, "id", instrument)
    instrument_id = _nautilus_instrument_id(raw_id)
    key = _instrument_key(instrument_id)
    strategy._subscription_state.pending_instrument_ids.discard(key)
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
                    if phase is not ConditionSubscriptionPhase.UNSUBSCRIBED
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
    strategy: _ConditionSubscriptionStateOwner,
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
    awaiting = set((Side.UP, Side.DOWN) if awaiting_sides is None else awaiting_sides)
    state.awaiting_book_sides_by_condition[condition_id] = awaiting
    state.book_generation_started_at_by_condition[condition_id] = observed_utc
    # The replay boundary anchors the FIRST unconfirmed start of this streak:
    # setdefault (not overwrite) keeps retries and rotations from renewing the
    # bounded grace window forever (issue #69 B2).
    state.adapter_replay_started_at_by_condition.setdefault(
        condition_id,
        observed_utc,
    )
    # A new generation owns a fresh set of recovery intents. Only begin may
    # raise the validity clock.
    state.pending_book_recovery_sides_by_condition.pop(condition_id, None)
    _ = state.book_recovery_dispatched_at_by_condition.pop(condition_id, None)
    _ = state.book_recovery_attempt_count_by_condition.pop(condition_id, None)
    # Drop prior receipts for sides this generation awaits so detail cannot
    # show "already received" while observe rejects received < started_at.
    _clear_awaiting_side_book_receipts(state, condition_id, awaiting)
    # Total-stall clock starts on the first wait and survives every
    # resubscription (setdefault); cleared only on book-ready / retire / clear.
    state.book_stalled_started_at_by_condition.setdefault(
        condition_id,
        observed_utc,
    )
    _ = state.first_bilateral_book_at_by_condition.pop(condition_id, None)
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
    # Keep the replay boundary set until the generation confirms bilaterally.
    # Popping on a single-side receipt would let the next refresh dispatch
    # re-anchor a fresh grace timestamp, and a one-sided stall (the other side
    # never recovering) would renew the bounded grace forever (issue #69 B2).
    # finish_market_book_generation / retire clear the marker.
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
    dispatched_at = state.book_recovery_dispatched_at_by_condition.get(condition_id)
    if dispatched_at is not None:
        _ = dispatched_at.pop(side, None)
        if not dispatched_at:
            _ = state.book_recovery_dispatched_at_by_condition.pop(condition_id, None)
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
    last_receipts = state.last_book_received_at_by_condition.setdefault(
        condition_id, {}
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
    _ = state.adapter_replay_started_at_by_condition.pop(condition_id, None)
    state.pending_book_recovery_sides_by_condition.pop(condition_id, None)
    _ = state.book_recovery_dispatched_at_by_condition.pop(condition_id, None)
    _ = state.book_recovery_attempt_count_by_condition.pop(condition_id, None)
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
    _transition_condition_phase(state, condition_id, ConditionSubscriptionPhase.READY)


def market_book_generation_ready(
    strategy: _ConditionSubscriptionStateOwner,
    condition_id: str,
) -> bool:
    """True only for a condition that has reached READY.

    The phase is the source of truth: a never-subscribed or already-cleaned
    condition must not be treated as book-generation ready.
    """
    return condition_phase(strategy, condition_id) is ConditionSubscriptionPhase.READY


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
    _ = strategy._subscription_state.adapter_replay_started_at_by_condition.pop(  # pyright: ignore[reportPrivateUsage]
        condition_id,
        None,
    )
    strategy._subscription_state.pending_book_recovery_sides_by_condition.pop(
        condition_id,
        None,
    )
    _ = strategy._subscription_state.book_recovery_dispatched_at_by_condition.pop(  # pyright: ignore[reportPrivateUsage]
        condition_id,
        None,
    )
    _ = strategy._subscription_state.book_recovery_attempt_count_by_condition.pop(  # pyright: ignore[reportPrivateUsage]
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
    # Purge any orphaned Phase-2 restore entry so a delayed flush cannot
    # resurrect a wire subscription to an instrument no strategy owns.
    _global_book_restore_pending.pop(key, None)
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


def _no_book_abandoned_at(strategy: object) -> dict[str, datetime]:
    """Per-condition no-book abandonment timestamps (bounded suppression)."""
    abandoned = getattr(strategy, "_no_book_abandoned_at_by_condition", None)
    if abandoned is None:
        return {}
    return abandoned


def _subscribe_suppressed(strategy: object, condition_id: str, *, now: datetime) -> bool:
    """True when a no-book-abandoned condition is inside its suppression window.

    Bounded by _NO_BOOK_SUPPRESS_SEC so a temporary venue outage recovers on
    retry, while a genuinely defunct market gets re-abandoned again 240s after
    re-entry instead of spinning forever.
    """
    abandoned = _no_book_abandoned_at(strategy)
    abandoned_at = abandoned.get(condition_id)
    if abandoned_at is None:
        return False
    now_utc = (now if now.tzinfo is not None else now.replace(tzinfo=UTC)).astimezone(
        UTC
    )
    if (now_utc - abandoned_at).total_seconds() >= _NO_BOOK_SUPPRESS_SEC:
        abandoned.pop(condition_id, None)
        return False
    return True


def _mark_no_book_abandoned(
    strategy: _SubscriptionStrategy,
    condition_id: str,
    instruments: Sequence[object],
    *,
    now: datetime,
) -> None:
    """Bounded suppression marker + pending-restore purge for an abandoned
    condition. The universe feed re-adds conditions on every epoch; without the
    marker an abandoned market would be re-subscribed and re-abandoned every
    240s (issue69 live evidence: 710 abandon events/day)."""
    _no_book_abandoned_at(strategy)[condition_id] = (
        now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    ).astimezone(UTC)
    for instrument_id in instruments:
        _global_book_restore_pending.pop(_instrument_key(instrument_id), None)


def abandon_book_stalled_condition(
    strategy: _SubscriptionStrategy,
    condition_id: str,
    *,
    stall_sec: float,
    now: datetime,
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
    # Suppress universe re-entry and drop pending Phase-2 restores.
    _mark_no_book_abandoned(strategy, condition_id, instruments, now=now)
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
        "condition_abandoned_no_book strategy=%s condition_id=%s stall_sec=%.3f",
        getattr(strategy, "strategy_name", None),
        condition_id,
        stall_sec,
        extra={
            "condition_id": condition_id,
            "stall_sec": round(stall_sec, 3),
            "instrument_ids": [_instrument_key(iid) for iid in instruments],
        },
    )
    return True


def _subscription_owners_for_instrument(
    strategy: _SubscriptionStrategy,
    instrument_id: object,
) -> tuple[_SubscriptionStrategy, ...]:
    del instrument_id
    candidates = (*_global_subscription_strategies.values(), strategy)
    owners: list[_SubscriptionStrategy] = []
    seen: set[int] = set()
    for candidate in candidates:
        owner = cast(_SubscriptionStrategy, candidate)
        owner_id = id(owner)
        if owner_id in seen:
            continue
        seen.add(owner_id)
        # The registry is authoritative. Local state can lead adapter command
        # processing, so filtering it can leave a shared token ref stranded.
        owners.append(owner)
    return tuple(owners)


def _quote_owners_for_instrument(
    instrument_id: object,
) -> tuple[tuple[_QuoteSubscriptionOwner, object], ...]:
    owners: list[tuple[_QuoteSubscriptionOwner, object]] = []
    for candidate in _global_quote_subscription_owners.values():
        owner = cast(_QuoteSubscriptionOwner, candidate)
        client_id = owner.recovery_quote_client_id(instrument_id)
        if client_id is not None:
            owners.append((owner, client_id))
    return tuple(owners)


def _attempt_subscription_operation(
    failures: list[Exception],
    operation: Callable[[], object],
) -> None:
    try:
        _ = operation()
    except Exception as exc:
        failures.append(exc)


def _drain_market_subscription_owners(
    owners: Sequence[_SubscriptionStrategy],
    quote_owners: Sequence[tuple[_QuoteSubscriptionOwner, object]],
    instrument_id: object,
    failures: list[Exception],
) -> None:
    for owner in owners:
        client_id = _client_id_for_instrument(owner, instrument_id)
        for operation in (
            owner.unsubscribe_quotes,
            owner.unsubscribe_trades,
            owner.unsubscribe_book_deltas,
        ):
            _attempt_subscription_operation(
                failures,
                lambda operation=operation, client_id=client_id: operation(
                    instrument_id,
                    client_id=client_id,
                ),
            )
    for owner, client_id in quote_owners:
        _attempt_subscription_operation(
            failures,
            lambda owner=owner, client_id=client_id: owner.unsubscribe_quotes(
                instrument_id,
                client_id=client_id,
            ),
        )


def _restore_market_subscription_owners(
    owners: Sequence[_SubscriptionStrategy],
    quote_owners: Sequence[tuple[_QuoteSubscriptionOwner, object]],
    instrument_id: object,
    failures: list[Exception],
) -> None:
    for owner in owners:
        client_id = _client_id_for_instrument(owner, instrument_id)
        book_type = _nautilus_book_type(owner.book_type)
        _attempt_subscription_operation(
            failures,
            lambda owner=owner, client_id=client_id, book_type=book_type: (
                owner.subscribe_book_deltas(
                    instrument_id,
                    book_type=book_type,
                    client_id=client_id,
                    managed=True,
                )
            ),
        )
    for owner in owners:
        client_id = _client_id_for_instrument(owner, instrument_id)
        for operation in (owner.subscribe_quotes, owner.subscribe_trades):
            _attempt_subscription_operation(
                failures,
                lambda operation=operation, client_id=client_id: operation(
                    instrument_id,
                    client_id=client_id,
                ),
            )
    for owner, client_id in quote_owners:
        _attempt_subscription_operation(
            failures,
            lambda owner=owner, client_id=client_id: owner.subscribe_quotes(
                instrument_id,
                client_id=client_id,
            ),
        )


def _refresh_market_instrument(
    strategy: _SubscriptionStrategy,
    instrument_id: object,
    *,
    now: datetime,
) -> None:
    """Phase 1: force an official-adapter token reset across all subscription
    owners, deferring restore to a later event-loop turn.

    Phase 1 releases every quote/trade/book owner of the shared token and
    registers the instrument for a delayed Phase 2 (see
    _flush_pending_book_restores). The split is required because a back-to-back
    same-turn drain+restore is a wire no-op: the DataEngine forwards an
    unsubscribe only while its book topic has zero subscribers, and the
    managed-book handler re-registered by the restore within the same turn keeps
    has_subscribers() true, so Polymarket never sees a subscription it could
    answer with a fresh initial-book snapshot.
    """
    instrument_id = _nautilus_instrument_id(instrument_id)
    owners = _subscription_owners_for_instrument(strategy, instrument_id)
    quote_owners = _quote_owners_for_instrument(instrument_id)
    logger.info(
        "book_recovery_boundary",
        extra={
            "instrument_id": _instrument_key(instrument_id),
            "strategy_owner_count": len(owners),
            "quote_owner_count": len(quote_owners),
        },
    )
    failures: list[Exception] = []
    _drain_market_subscription_owners(owners, quote_owners, instrument_id, failures)
    if failures:
        logger.warning(
            "book_recovery_drain_failed",
            extra={
                "instrument_id": _instrument_key(instrument_id),
                "failure_count": len(failures),
            },
        )
    now_utc = (now if now.tzinfo is not None else now.replace(tzinfo=UTC)).astimezone(
        UTC
    )
    _global_book_restore_pending[_instrument_key(instrument_id)] = (
        instrument_id,
        now_utc,
    )


def _restore_one_pending_instrument(
    strategy: _SubscriptionStrategy,
    instrument_id: object,
    *,
    now: datetime,
) -> object | None:
    """Restore one drained instrument; return the restored object or None.

    Expired/closed conditions are skipped: re-subscribing a resolved market
    makes Polymarket reject the payload with code=1008 (issue69 signal stall
    defect 3), creating an infinite close→reconnect→resubscribe→1008 loop.

    A failed restore still consumes the process-wide retry anchor
    (single-flight): without it the very next heartbeat could re-drain the
    same shared instrument, and with several strategies sharing one data
    client the failure degenerates into a per-heartbeat drain/restore storm.
    Spacing the next attempt by _BOOK_RECOVERY_RETRY_SEC bounds the loop
    while keeping the failure retryable.
    """
    instrument_id = _nautilus_instrument_id(instrument_id)
    now_utc = (now if now.tzinfo is not None else now.replace(tzinfo=UTC)).astimezone(
        UTC
    )
    if not _instrument_restore_allowed(strategy, instrument_id, now=now_utc):
        return None
    owners = _subscription_owners_for_instrument(strategy, instrument_id)
    quote_owners = _quote_owners_for_instrument(instrument_id)
    failures: list[Exception] = []
    _restore_market_subscription_owners(owners, quote_owners, instrument_id, failures)
    if failures:
        logger.warning(
            "book_recovery_restore_failed",
            extra={
                "instrument_id": _instrument_key(instrument_id),
                "failure_count": len(failures),
            },
        )
        _mark_global_book_refresh(strategy, instrument_id, now=now_utc)
        return None
    _mark_global_book_refresh(strategy, instrument_id, now=now_utc)
    return instrument_id


def _flush_pending_book_restores(
    strategy: _SubscriptionStrategy,
    *,
    now: datetime,
) -> tuple[object, ...]:
    """Phase 2: restore instruments drained by a previous event-loop turn.

    Runs from the evaluation heartbeat so the DataEngine command queue has
    processed the delayed unsubscribe before the re-subscribe is enqueued.
    Skipped/failed restores still count as the instrument's retry anchor:
    the next drain is spaced by _BOOK_RECOVERY_RETRY_SEC process-wide, so a
    broken shared instrument is retried — never stormed every heartbeat.
    """
    now_utc = (now if now.tzinfo is not None else now.replace(tzinfo=UTC)).astimezone(
        UTC
    )
    restored: list[object] = []
    for key, (instrument_id, promised_at) in tuple(_global_book_restore_pending.items()):
        if (now_utc - promised_at).total_seconds() < _BOOK_RECOVERY_RESTORE_DELAY_SEC:
            continue
        _global_book_restore_pending.pop(key, None)
        instrument_id = _restore_one_pending_instrument(
            strategy,
            instrument_id,
            now=now_utc,
        )
        if instrument_id is not None:
            restored.append(instrument_id)
    return tuple(restored)


def _global_book_refresh_due(
    strategy: _SubscriptionStrategy,
    instrument_id: object,
    *,
    now: datetime,
) -> bool:
    del strategy
    now_utc = (now if now.tzinfo is not None else now.replace(tzinfo=UTC)).astimezone(
        UTC
    )
    cutoff = now_utc - timedelta(seconds=_BOOK_RECOVERY_RETRY_SEC * 2)
    for key, attempted_at in tuple(_global_book_recovery_times.items()):
        if attempted_at < cutoff:
            del _global_book_recovery_times[key]
    key = _instrument_key(instrument_id)
    attempted_at = _global_book_recovery_times.get(key)
    return (
        attempted_at is None
        or (now_utc - attempted_at).total_seconds() >= _BOOK_RECOVERY_RETRY_SEC
    )


def _mark_global_book_refresh(
    strategy: _SubscriptionStrategy,
    instrument_id: object,
    *,
    now: datetime,
) -> None:
    """Record this instrument's last wire refresh attempt as the retry anchor.

    Set on both successful restores and failed ones: the timestamp spaces the
    next drain by ``_BOOK_RECOVERY_RETRY_SEC`` process-wide (the key is the
    shared instrument, so every strategy sharing the client coalesces onto
    the same throttle), which bounds a failure loop to one drain per retry
    window instead of one per heartbeat.
    """
    del strategy
    now_utc = (now if now.tzinfo is not None else now.replace(tzinfo=UTC)).astimezone(
        UTC
    )
    _global_book_recovery_times[_instrument_key(instrument_id)] = now_utc


def _mark_replay_unconfirmed(
    state: MarketSubscriptionState,
    condition_id: str,
    *,
    now: datetime,
) -> None:
    observed = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    # Anchor the first unconfirmed start; a later refresh dispatch while still
    # unconfirmed must not move the timestamp (bounded grace in issue #69 B2).
    state.adapter_replay_started_at_by_condition.setdefault(
        condition_id,
        observed.astimezone(UTC),
    )


def _record_recovery_intent(
    state: MarketSubscriptionState,
    condition_id: str,
    side: Side,
    *,
    now: datetime,
) -> None:
    """Record the per-side recovery intent and its dispatch timestamp."""
    state.pending_book_recovery_sides_by_condition.setdefault(condition_id, set()).add(
        side
    )
    state.book_recovery_dispatched_at_by_condition.setdefault(condition_id, {})[
        side
    ] = now.astimezone(UTC)
    state.book_recovery_attempt_count_by_condition[condition_id] = (
        state.book_recovery_attempt_count_by_condition.get(condition_id, 0) + 1
    )


def _dispatch_book_recovery(
    strategy: _SubscriptionStrategy,
    condition_id: str,
    targets: Sequence[tuple[Side, object]],
    *,
    now: datetime,
) -> tuple[object, ...]:
    state = strategy._subscription_state
    dispatched: list[object] = []
    dispatched_sides: list[Side] = []
    try:
        for side, instrument_id in targets:
            key = _instrument_key(instrument_id)
            # A prior Phase-1 drain awaiting its Phase-2 restore must not be
            # torn down again on the next heartbeat.
            if key not in _global_book_restore_pending and _global_book_refresh_due(
                strategy,
                instrument_id,
                now=now,
            ):
                _refresh_market_instrument(strategy, instrument_id, now=now)
                _mark_replay_unconfirmed(state, condition_id, now=now)
                dispatched.append(instrument_id)
            dispatched_sides.append(side)
            _record_recovery_intent(state, condition_id, side, now=now)
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
    *,
    now: datetime,
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
    dispatched_at = state.book_recovery_dispatched_at_by_condition.get(
        condition_id,
        {},
    )
    now_utc = (now if now.tzinfo is not None else now.replace(tzinfo=UTC)).astimezone(
        UTC
    )
    return tuple(
        (side, instrument_id)
        for side in (Side.UP, Side.DOWN)
        if side in awaiting
        if side not in already_pending
        or (
            (attempt_at := dispatched_at.get(side)) is None
            or (now_utc - attempt_at).total_seconds() >= _BOOK_RECOVERY_RETRY_SEC
        )
        if (instrument_id := registry.instrument_id_for_token(token_by_side[side]))
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
    _ = abandon_book_stalled_condition(
        strategy,
        condition_id,
        stall_sec=stall_sec,
        now=now,
    )
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
    targets = _awaiting_condition_recovery_targets(strategy, condition_id, now=now)
    if not targets:
        return None
    instruments = tuple(instrument_id for _side, instrument_id in targets)
    dispatched = _dispatch_book_recovery(strategy, condition_id, targets, now=now)
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
    targets = _awaiting_condition_recovery_targets(strategy, condition_id, now=now)
    return bool(targets) and _book_generation_stalled(
        strategy,
        condition_id,
        now=now,
    )


def _log_book_refresh_requested(
    state: MarketSubscriptionState,
    condition_id: str,
    instruments: Sequence[object],
    *,
    stall_sec: float,
    dispatched: Sequence[object],
) -> None:
    """Gate the trend log on real wire dispatch (issue69 storm throttle)."""
    log = logger.info if dispatched else logger.debug
    log(
        "condition_book_refresh_requested",
        extra=_recovery_log_extra(
            state,
            condition_id,
            instruments,
            stall_sec=stall_sec,
            dispatched=dispatched,
        ),
    )


def force_resubscribe_if_book_stalled(
    strategy: _SubscriptionStrategy,
    condition_id: str,
    *,
    now: datetime,
) -> bool:
    """Submit each missing-side recovery intent once for this generation."""
    state = strategy._subscription_state
    if _subscribe_suppressed(strategy, condition_id, now=now):
        return False
    if not _first_book_recovery_due(
        strategy,
        condition_id,
        now=now,
    ):
        return False
    generation_started_at = state.book_generation_started_at_by_condition.get(
        condition_id
    )
    attempt = _resubscribe_and_begin_generation(strategy, condition_id, now=now)
    if attempt is None:
        return False
    instruments, dispatched = attempt
    stall_sec = (
        round((now.astimezone(UTC) - generation_started_at).total_seconds(), 3)
        if generation_started_at is not None
        else _BOOK_GENERATION_STALL_SEC
    )
    _log_book_refresh_requested(
        state,
        condition_id,
        instruments,
        stall_sec=stall_sec,
        dispatched=dispatched,
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
    generation_started_at = state.book_generation_started_at_by_condition.get(
        condition_id
    )
    if generation_started_at is not None and (
        now_utc - generation_started_at
    ).total_seconds() <= (_BOOK_GENERATION_STALL_SEC):
        return None
    return now_utc, total_stalled_at


def _stale_receipt_sides(
    strategy: _SubscriptionStrategy,
    condition_id: str,
    *,
    now: datetime,
) -> tuple[Side, ...]:
    """Return sides that stopped receiving after the READY condition existed."""
    state = strategy._subscription_state
    if condition_id not in strategy._active_condition_ids:
        return ()
    if condition_id not in state.first_bilateral_book_ever_at_by_condition:
        return ()
    if pending_condition_instrument_ids(strategy, condition_id):
        return ()
    if condition_id in state.awaiting_book_sides_by_condition:
        return ()
    if condition_id in strategy._stale_orderbook_recovery_by_condition:
        return ()
    receipts = state.last_book_received_at_by_condition.get(condition_id)
    if not receipts:
        return ()
    now_utc = (now if now.tzinfo is not None else now.replace(tzinfo=UTC)).astimezone(
        UTC
    )
    stale = tuple(
        side
        for side in (Side.UP, Side.DOWN)
        if side not in receipts
        or (now_utc - receipts[side].astimezone(UTC)).total_seconds()
        >= _STALE_RECEIPT_THRESHOLD_SEC
    )
    return stale


def _ready_receipt_stalled(
    strategy: _SubscriptionStrategy,
    condition_id: str,
    *,
    now: datetime,
) -> bool:
    """True when a once-READY condition has stopped producing a side of books.

    It does not require both sides to be stale: a unilateral feed loss can keep
    one book fresh while the other side remains unavailable; that condition must
    still enter recovery instead of staying READY forever.
    """
    return bool(_stale_receipt_sides(strategy, condition_id, now=now))


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
    if _subscribe_suppressed(strategy, condition_id, now=now):
        return False
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
    _log_book_refresh_requested(
        state,
        condition_id,
        instruments,
        stall_sec=stall_sec,
        dispatched=dispatched,
    )
    return True


def _log_stale_receipt_refresh(
    condition_id: str,
    instruments: Sequence[object],
    dispatched: Sequence[object],
) -> None:
    logger.info(
        "book_stale_receipt_refresh_requested",
        extra={
            "condition_id": condition_id,
            "instrument_count": len(instruments),
            "dispatched_count": len(dispatched),
        },
    )


def force_resubscribe_if_stale_receipt(
    strategy: _SubscriptionStrategy,
    condition_id: str,
    *,
    now: datetime,
) -> bool:
    """Repair a once-READY condition whose real receipts stopped (Gap C).

    This is a maintenance retry, never a no-book abandon: the condition has
    already proven it can receive a bilateral book, so a silent WS outage must
    recover by draining and re-subscribing the current instruments.
    """
    state = strategy._subscription_state
    if _subscribe_suppressed(strategy, condition_id, now=now):
        return False
    if not _ready_receipt_stalled(strategy, condition_id, now=now):
        return False
    generation_started_at = state.book_generation_started_at_by_condition.get(
        condition_id
    )
    if generation_started_at is not None and (
        now.astimezone(UTC) - generation_started_at
    ).total_seconds() <= (_BOOK_GENERATION_STALL_SEC):
        return False
    # The late receipt path reuses the stale-orderbook repair transition. Seed
    # only the sides that stopped receiving books; a healthy side must not be
    # drained and resubscribed again.
    stale_sides = _stale_receipt_sides(strategy, condition_id, now=now)
    if not stale_sides:
        return False
    attempt = _stale_receipt_resubscribe(strategy, condition_id, stale_sides, now=now)
    if attempt is None:
        return False
    instruments, dispatched = attempt
    _log_book_refresh_requested(
        state,
        condition_id,
        instruments,
        stall_sec=_STALE_RECEIPT_THRESHOLD_SEC,
        dispatched=dispatched,
    )
    _log_stale_receipt_refresh(condition_id, instruments, dispatched)
    return True


def _stale_receipt_resubscribe(
    strategy: _SubscriptionStrategy,
    condition_id: str,
    stale_sides: Sequence[Side],
    *,
    now: datetime,
) -> tuple[tuple[object, ...], tuple[object, ...]] | None:
    """Open a stale-receipt repair generation and drain the stalled sides.

    The marker is one-shot per stall episode, mirroring the stale-orderbook
    repair: once the generation is (re)opened, drop it. Leaving it behind
    would re-arm _stale_book_recovery_due ~120s after the book recovered and
    re-drain a healthy READY condition forever (issue69 recovery storm).
    """
    strategy._stale_orderbook_recovery_by_condition[condition_id] = {
        side: 0.0 for side in stale_sides
    }
    attempt = _resubscribe_and_begin_generation(strategy, condition_id, now=now)
    if attempt is None:
        return None
    _ = strategy._stale_orderbook_recovery_by_condition.pop(condition_id, None)
    return attempt
