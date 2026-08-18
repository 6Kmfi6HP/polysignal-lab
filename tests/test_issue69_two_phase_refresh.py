"""Regression tests for the issue69 two-phase refresh and no-book suppression.

Live evidence (2026-08-16): with the book feed stalled, the strategy's
drain+restore refresh ran in the same synchronous turn, the DataEngine's
subscribe gates treated the instrument as still subscribed (engine.pyx:1029,
1735), and the wire saw zero unsubscribe/subscribe — 44 recovery dispatches
produced 0 wire messages and Polymarket never re-pushed an initial snapshot.

The fix splits the refresh into Phase 1 (drain, registers a process-scoped
pending) and Phase 2 (restore, runs from the evaluation heartbeat after the
engine has torn down the old wire subscription). It also bounds no-book
abandonments so the universe feed cannot re-add a dead market every 240s.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_runtime.market_catalog import (
    InstrumentTokenMeta,
    MarketCatalog,
    MarketPairMeta,
)
from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
    ConditionSubscriptionPhase,
    MarketSubscriptionState,
    _BOOK_GENERATION_ABANDON_SEC,
    _BOOK_GENERATION_STALL_SEC,
    _BOOK_RECOVERY_RESTORE_DELAY_SEC,
    _NO_BOOK_SUPPRESS_SEC,
    _clear_global_book_recovery_state,
    _flush_pending_book_restores,
    _global_book_restore_pending,
    _subscribe_market_condition,
    _subscribe_suppressed,
    abandon_book_stalled_condition,
    condition_instruments,
    force_resubscribe_if_book_stalled,
    unsubscribe_market_instrument,
)


def _pair(condition_id: str) -> MarketPairMeta:
    return MarketPairMeta(
        market_id=f"market-{condition_id}",
        market_slug=f"{condition_id}-updown-5m",
        condition_id=condition_id,
        asset="BTC",
        timeframe="5m",
        start_ts=None,
        end_ts=None,
        up=InstrumentTokenMeta(f"{condition_id}-up", Side.UP),
        down=InstrumentTokenMeta(f"{condition_id}-down", Side.DOWN),
    )


def _registry(condition_id: str = "btc-5m") -> MarketCatalog:
    registry = MarketCatalog(
        instrument_id_resolver=lambda _condition, token: f"{token}.POLYMARKET"
    )
    registry.register(_pair(condition_id))
    return registry


class _RefreshStrategy:
    """Duck-typed strategy recording subscribe/unsubscribe wire calls."""

    def __init__(self, registry: MarketCatalog) -> None:
        self.registry: MarketCatalog | None = registry
        self.cache: object | None = None
        self.book_type: str = "L2_MBP"
        self.unsubscribe_exited: bool = True
        self._startup_condition_ids: tuple[str, ...] = ()
        self._active_condition_ids: set[str] = set()
        self._asset_condition_ids: dict[str, tuple[str, ...]] = {}
        self._subscription_assets = frozenset({"BTC"})
        self._subscription_timeframes = frozenset({"5m"})
        self._stale_orderbook_recovery_by_condition: dict[str, dict[Side, float]] = {}
        self._untradable_quote_sides_by_condition: dict[str, frozenset[Side]] = {}
        self._runtime_readiness_reason_by_condition: dict[str, str] = {}
        self._runtime_readiness_miss_condition_ids: set[str] = set()
        self._no_book_abandoned_at_by_condition: dict[str, datetime] = {}
        self._subscription_state = MarketSubscriptionState()
        self.subscribed_instruments: list[str] = []
        self.unsubscribed_instruments: list[str] = []

    def _note_runtime_readiness(
        self,
        condition_id: str,
        *,
        ready: bool,
        status: object | None = None,
        reason: str | None = None,
    ) -> None:
        del status, reason

    def _readiness_detail(
        self, condition_id: str, *, now: datetime
    ) -> dict[str, object]:
        del condition_id, now
        return {}

    def subscribe_quotes(
        self, instrument_id: object, client_id: object | None = None
    ) -> None:
        del instrument_id, client_id

    def subscribe_trades(
        self, instrument_id: object, client_id: object | None = None
    ) -> None:
        del instrument_id, client_id

    def subscribe_book_deltas(
        self,
        instrument_id: object,
        *,
        book_type: object,
        client_id: object | None = None,
        managed: bool = False,
    ) -> None:
        del book_type, client_id, managed
        self.subscribed_instruments.append(str(instrument_id))

    def unsubscribe_quotes(
        self, instrument_id: object, client_id: object | None = None
    ) -> None:
        del instrument_id, client_id

    def unsubscribe_trades(
        self, instrument_id: object, client_id: object | None = None
    ) -> None:
        del instrument_id, client_id

    def unsubscribe_book_deltas(
        self, instrument_id: object, client_id: object | None = None
    ) -> None:
        del client_id
        self.unsubscribed_instruments.append(str(instrument_id))


def _stalled(strategy: _RefreshStrategy, condition_id: str, *, now: datetime) -> None:
    state = strategy._subscription_state
    state.condition_phases[condition_id] = ConditionSubscriptionPhase.AWAITING_FIRST_BOOK
    state.awaiting_book_sides_by_condition[condition_id] = {Side.UP, Side.DOWN}
    state.book_generation_started_at_by_condition[condition_id] = now
    state.book_stalled_started_at_by_condition[condition_id] = now


def test_drain_and_restore_land_in_different_turns() -> None:
    """Phase 1 registers the drain; Phase 2 (flush) performs the restore."""
    _clear_global_book_recovery_state()
    registry = _registry()
    strategy = _RefreshStrategy(registry)
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    _stalled(strategy, "btc-5m", now=now - timedelta(seconds=70))

    assert (
        force_resubscribe_if_book_stalled(strategy, "btc-5m", now=now) is True
    )

    # Phase 1 only: unsubscribe issued, restore deferred.
    assert len(strategy.unsubscribed_instruments) == 2
    assert strategy.subscribed_instruments == []

    # Phase 2: restore applied on a later turn.
    _flush_pending_book_restores(
        strategy,
        now=now + timedelta(seconds=_BOOK_RECOVERY_RESTORE_DELAY_SEC + 1),
    )
    assert len(strategy.subscribed_instruments) == 2


def test_abandon_marks_no_book_and_purges_pending_restore() -> None:
    """Abandoning a stalled condition suppresses re-entry and drops its pending
    Phase-2 restore so a dead market is not instantly resubscribed."""
    _clear_global_book_recovery_state()
    registry = _registry()
    strategy = _RefreshStrategy(registry)
    strategy._active_condition_ids = {"btc-5m"}
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    _stalled(strategy, "btc-5m", now=now - timedelta(seconds=70))

    assert force_resubscribe_if_book_stalled(strategy, "btc-5m", now=now) is True

    assert (
        abandon_book_stalled_condition(
            strategy,
            "btc-5m",
            stall_sec=_BOOK_GENERATION_ABANDON_SEC,
            now=now,
        )
        is True
    )
    assert "btc-5m" in strategy._no_book_abandoned_at_by_condition
    assert _subscribe_suppressed(strategy, "btc-5m", now=now) is True

    # Re-subscription intent is suppressed while the marker is inside its window.
    strategy._active_condition_ids = {"btc-5m"}
    strategy.registry = registry
    _subscribe_market_condition(
        strategy,
        registry,
        "btc-5m",
        now=now + timedelta(seconds=10),
    )
    assert strategy.subscribed_instruments == []


def test_suppression_expires_after_bounded_window() -> None:
    """A temporary venue outage recovers after _NO_BOOK_SUPPRESS_SEC; the marker
    is dropped and re-entry is allowed again."""
    _clear_global_book_recovery_state()
    registry = _registry()
    strategy = _RefreshStrategy(registry)
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    strategy._active_condition_ids = {"btc-5m"}
    assert (
        abandon_book_stalled_condition(
            strategy,
            "btc-5m",
            stall_sec=_BOOK_GENERATION_STALL_SEC,
            now=now,
        )
        is True
    )
    # Inside the window: suppressed.
    assert (
        _subscribe_suppressed(
            strategy,
            "btc-5m",
            now=now + timedelta(seconds=_NO_BOOK_SUPPRESS_SEC - 1),
        )
        is True
    )
    # Once the window elapses the marker self-clears and re-entry is allowed.
    late = now + timedelta(seconds=_NO_BOOK_SUPPRESS_SEC + 10)
    assert _subscribe_suppressed(strategy, "btc-5m", now=late) is False
    assert "btc-5m" not in strategy._no_book_abandoned_at_by_condition


def test_orphan_restore_pending_purged_on_instrument_unsubscribe() -> None:
    """A delayed Phase-2 restore must not resurrect an unsubscribed instrument.

    When a condition's instrument is torn down (via unsubscribe_market_instrument)
    after Phase-1 drained it but before Phase-2 restored it, the orphaned pending
    entry must be purged so the next flush does not issue a ghost subscribe to a
    wire token no strategy owns.
    """
    _clear_global_book_recovery_state()
    registry = _registry()
    strategy = _RefreshStrategy(registry)
    strategy._active_condition_ids = {"btc-5m"}
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    _stalled(strategy, "btc-5m", now=now - timedelta(seconds=70))

    # Phase 1: drain registers a pending restore for both instruments.
    assert (
        force_resubscribe_if_book_stalled(strategy, "btc-5m", now=now) is True
    )
    assert len(_global_book_restore_pending) == 2

    # Tear down one instrument directly (e.g. rotation/retire path).
    up_instrument = condition_instruments(strategy, "btc-5m")[0]
    up_key = str(getattr(up_instrument, "id", up_instrument))
    unsubscribe_market_instrument(strategy, up_instrument)

    # The orphaned Phase-2 entry is gone; only the still-subscribed one remains.
    assert up_key not in _global_book_restore_pending

    # Phase 2: flush restores only surviving pending entries, not the ghost.
    _flush_pending_book_restores(
        strategy,
        now=now + timedelta(seconds=_BOOK_RECOVERY_RESTORE_DELAY_SEC + 1),
    )
    assert up_key not in [str(i) for i in strategy.subscribed_instruments]