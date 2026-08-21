from __future__ import annotations

from typing import Protocol

from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
    ConditionSubscriptionPhase,
    MarketSubscriptionState,
    _instrument_key,
    condition_instruments,
    condition_phase,
    pending_condition_instrument_ids,
)


class _InvariantStrategy(Protocol):
    _subscription_state: MarketSubscriptionState
    _active_condition_ids: set[str]
    _untradable_quote_sides_by_condition: dict[str, frozenset[Side]]
    _stale_orderbook_recovery_by_condition: dict[str, dict[Side, float]]
    _runtime_readiness_reason_by_condition: dict[str, str]
    _runtime_readiness_miss_condition_ids: set[str]

    @property
    def registry(self) -> MarketCatalog | None: ...


def assert_subscription_invariants(strategy: _InvariantStrategy) -> None:
    """Assert the subscription lifecycle invariants hold for a strategy.

    The phase is the single source of truth; every derived container must be
    consistent with it, lifecycle state must be confined to the active set
    (bounded cardinality under rotation), and retired conditions must never own
    active readiness markers or resurrect via late callbacks.
    """
    _assert_phase_consistency(strategy)
    _assert_derived_containers_shadow_phases(strategy)
    _assert_cleanup_and_ownership(strategy)


def _assert_phase_consistency(strategy: _InvariantStrategy) -> None:
    state = strategy._subscription_state
    for condition_id, phase in state.condition_phases.items():
        pending = pending_condition_instrument_ids(  # type: ignore[arg-type]
            strategy,
            condition_id,
        )
        if phase is ConditionSubscriptionPhase.PENDING_INSTRUMENT:
            assert pending, (
                f"{condition_id}: PENDING_INSTRUMENT without pending instruments"
            )
        if phase is ConditionSubscriptionPhase.AWAITING_FIRST_BOOK:
            unresolved_pending = [
                key
                for key in pending
                if key not in state.subscribed_instrument_ids
            ]
            assert not unresolved_pending, (
                f"{condition_id}: AWAITING_FIRST_BOOK with pending instruments"
            )
            assert (
                condition_id in state.awaiting_book_sides_by_condition
            ), f"{condition_id}: AWAITING_FIRST_BOOK without awaiting sides"
            assert (
                condition_id in state.book_generation_started_at_by_condition
            ), f"{condition_id}: AWAITING_FIRST_BOOK without generation start"
            # A condition awaiting its first bilateral book must own its
            # instruments: an empty subscribed set with awaiting sides means the
            # subscribe API never succeeded (wedge), which no real feed can
            # satisfy.
            _assert_owns_instruments(strategy, condition_id)
        if phase is ConditionSubscriptionPhase.READY:
            assert (
                condition_id not in state.awaiting_book_sides_by_condition
            ), f"{condition_id}: READY with awaiting sides"
            assert condition_id in state.first_bilateral_book_at_by_condition, (
                f"{condition_id}: READY without first bilateral book"
            )
            # READY conditions own their instruments (same wedge guard).
            _assert_owns_instruments(strategy, condition_id)
        if phase is ConditionSubscriptionPhase.SUBSCRIBE_ISSUED:
            _assert_subscribe_issued_consistency(strategy, condition_id, pending)


def _assert_subscribe_issued_consistency(
    strategy: _InvariantStrategy,
    condition_id: str,
    pending: tuple[str, ...],
) -> None:
    """SUBSCRIBE_ISSUED is a subscribed-but-not-feed-ready state: it must not
    carry pending instruments, awaiting sides, or a stale first-bilateral marker
    (the READY-re-entry wedge)."""
    state = strategy._subscription_state
    assert not pending, f"{condition_id}: SUBSCRIBE_ISSUED with pending instruments"
    assert (
        condition_id not in state.awaiting_book_sides_by_condition
    ), f"{condition_id}: SUBSCRIBE_ISSUED with awaiting sides"
    assert (
        condition_id not in state.first_bilateral_book_at_by_condition
    ), f"{condition_id}: SUBSCRIBE_ISSUED with stale first bilateral book"
    assert (
        condition_id not in state.first_bilateral_book_latency_ms_by_condition
    ), f"{condition_id}: SUBSCRIBE_ISSUED with stale first bilateral latency"


def _assert_owns_instruments(
    strategy: _InvariantStrategy,
    condition_id: str,
) -> None:
    """A condition past the pending stage must own its instruments in the
    subscribed set: an empty subscribed set with awaiting sides or READY is a
    wedge the real feed can never satisfy (subscribe API failure)."""
    registry = strategy.registry
    if registry is None:
        return
    pair = registry.by_condition(condition_id)
    if pair is None:
        return
    subscribed = strategy._subscription_state.subscribed_instrument_ids
    for token_id in (pair.up.token_id, pair.down.token_id):
        instrument_id = registry.instrument_id_for_token(token_id)
        if instrument_id is None:
            continue
        assert _instrument_key(instrument_id) in subscribed, (
            f"{condition_id}: phase {condition_phase(strategy, condition_id).value!r} "
            f"without instrument {_instrument_key(instrument_id)!r} subscribed"
        )


def _assert_derived_containers_shadow_phases(
    strategy: _InvariantStrategy,
) -> None:
    state = strategy._subscription_state
    phase_ids = set(state.condition_phases)
    for condition_id in state.awaiting_book_sides_by_condition:
        assert condition_id in phase_ids, (
            f"{condition_id}: awaiting sides without a lifecycle phase"
        )
    for condition_id in state.book_generation_started_at_by_condition:
        assert condition_id in phase_ids, (
            f"{condition_id}: generation start without a lifecycle phase"
        )
        assert condition_id in state.awaiting_book_sides_by_condition, (
            f"{condition_id}: generation start without awaiting sides"
        )
    for condition_id, pending_sides in (
        state.pending_book_recovery_sides_by_condition.items()
    ):
        assert condition_id in phase_ids, (
            f"{condition_id}: pending recovery without a lifecycle phase"
        )
        awaiting_sides = state.awaiting_book_sides_by_condition.get(condition_id)
        assert awaiting_sides is not None and pending_sides <= awaiting_sides, (
            f"{condition_id}: pending recovery sides are not awaiting receipts"
        )
    for condition_id in state.first_bilateral_book_at_by_condition:
        assert condition_id in phase_ids, (
            f"{condition_id}: first bilateral book without a lifecycle phase"
        )
        assert (
            condition_phase(strategy, condition_id)
            is ConditionSubscriptionPhase.READY
        ), f"{condition_id}: first bilateral book without READY phase"
    for condition_id in state.first_bilateral_book_latency_ms_by_condition:
        assert condition_id in state.first_bilateral_book_at_by_condition, (
            f"{condition_id}: latency without a first bilateral book"
        )
    for condition_id in state.subscribe_intent_started_at_by_condition:
        assert condition_id in phase_ids, (
            f"{condition_id}: subscribe intent without a lifecycle phase"
        )


def _assert_cleanup_and_ownership(strategy: _InvariantStrategy) -> None:
    state = strategy._subscription_state
    active = strategy._active_condition_ids

    # Lifecycle phases are confined to the active set: a retired condition must
    # not carry (or resurrect) a phase (bounded cardinality under rotation).
    for condition_id in state.condition_phases:
        assert condition_id in active, (
            f"{condition_id}: lifecycle phase for inactive condition"
        )

    # A key may be pending because the wire request was sent before the provider
    # made it Cache-visible. The active key is marked subscribed once the engine
    # accepted the request, and on_instrument_available clears pending later;
    # therefore overlap is legal, but every overlapping key must also be active
    # in the registry and represented by an active lifecycle phase.
    overlap = state.pending_instrument_ids & state.subscribed_instrument_ids
    if overlap:
        registry_ids = {
            _instrument_key(iid)
            for condition_id in strategy._active_condition_ids
            for iid in condition_instruments(strategy, condition_id)
        }
        assert overlap <= registry_ids, (
            f"pending/subscribed overlap outside active registry: {sorted(overlap)}"
        )

    # Inactive conditions never own active readiness markers.
    for condition_id in strategy._untradable_quote_sides_by_condition:
        assert condition_id in active, (
            f"{condition_id}: untradable marker for inactive condition"
        )
    for condition_id in strategy._stale_orderbook_recovery_by_condition:
        assert condition_id in active, (
            f"{condition_id}: stale orderbook marker for inactive condition"
        )
    for condition_id in strategy._runtime_readiness_reason_by_condition:
        assert condition_id in active, (
            f"{condition_id}: readiness reason for inactive condition"
        )
    for condition_id in strategy._runtime_readiness_miss_condition_ids:
        assert condition_id in active, (
            f"{condition_id}: readiness miss for inactive condition"
        )
