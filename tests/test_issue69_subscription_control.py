"""Issue 69 subscription-control-plane regression tests.

Three defect families are pinned here at the real call boundaries:

1. Adapter instrument refresh must be non-destructive on the shared data
   client (one client per timeframe, shared by every strategy and the
   MarketRotationActor). A venue/client-wide ``unsubscribe_instruments`` from
   any strategy would decrement the shared instrument-topic refcount and tear
   down instrument delivery for the whole fleet — the refresh may only
   ``subscribe_instruments`` (idempotent, refcounted) plus
   ``request_instruments`` (drives the provider load), and the per-client
   gate must coalesce a fleet-wide burst to one load per window.

2. Book-recovery dispatch is single-flight and coalesced: the same
   instrument/reconnect generation is not drained again while a drain is
   pending or a retry anchor is fresh, even across strategies that share the
   adapter token. Failures stay retryable but the retry is spaced by the
   recovery retry window instead of storming every heartbeat.

3. State transitions are explicit: a stale-receipt repair opens a fresh book
   generation once per stall episode and never re-drains a healthy READY
   condition after it recovers; READY and awaiting conditions coexist in one
   heartbeat with only the stalled one touched.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest

from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_runtime.market_catalog import (
    InstrumentTokenMeta,
    MarketCatalog,
    MarketPairMeta,
)
from polysignal_lab.nautilus_runtime.strategy import lifecycle as life
from polysignal_lab.nautilus_runtime.strategy.invariants import (
    assert_subscription_invariants,
)
from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
    ConditionSubscriptionPhase,
    MarketSubscriptionState,
    _BOOK_RECOVERY_RESTORE_DELAY_SEC,
    _BOOK_RECOVERY_RETRY_SEC,
    _clear_global_book_recovery_state,
    _flush_pending_book_restores,
    _global_book_recovery_times,
    _global_book_restore_pending,
    _register_subscription_strategy,
    _unregister_subscription_strategy,
    force_resubscribe_if_book_stalled,
    force_resubscribe_if_stale_orderbook,
    force_resubscribe_if_stale_receipt,
    observe_market_book_side,
)

_NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)


def _pair(asset: str, *, timeframe: str = "5m") -> MarketPairMeta:
    condition_id = f"{asset.lower()}-{timeframe}"
    return MarketPairMeta(
        market_id=f"market-{condition_id}",
        market_slug=f"{asset.lower()}-updown-{timeframe}",
        condition_id=condition_id,
        asset=asset,
        timeframe=timeframe,
        start_ts=None,
        end_ts=None,
        up=InstrumentTokenMeta(f"{condition_id}-up", Side.UP),
        down=InstrumentTokenMeta(f"{condition_id}-down", Side.DOWN),
    )


def _registry(*assets: str) -> MarketCatalog:
    registry = MarketCatalog(
        instrument_id_resolver=lambda _condition_id, token: f"{token}.POLYMARKET"
    )
    for asset in assets:
        registry.register(_pair(asset))
    return registry


def _instrument_keys(condition_id: str) -> tuple[str, str]:
    return (
        f"{condition_id}-up.POLYMARKET",
        f"{condition_id}-down.POLYMARKET",
    )


class _RecordingStrategy:
    """Strategy-like host recording every wire call in order."""

    def __init__(self, registry: MarketCatalog) -> None:
        self.registry: MarketCatalog | None = registry
        self.cache: object | None = None
        self.book_type: str = "L2_MBP"
        self.unsubscribe_exited: bool = True
        self._startup_condition_ids: tuple[str, ...] = ()
        self._active_condition_ids: set[str] = set()
        self._asset_condition_ids: dict[str, tuple[str, ...]] = {}
        self._subscription_assets: frozenset[str] = frozenset({"BTC", "ETH"})
        self._subscription_timeframes: frozenset[str] = frozenset({"5m", "15m"})
        self._untradable_quote_sides_by_condition: dict[str, frozenset[Side]] = {}
        self._stale_orderbook_recovery_by_condition: dict[str, dict[Side, float]] = {}
        self._runtime_readiness_reason_by_condition: dict[str, str] = {}
        self._runtime_readiness_miss_condition_ids: set[str] = set()
        self._no_book_abandoned_at_by_condition: dict[str, datetime] = {}
        self._subscription_state: MarketSubscriptionState = MarketSubscriptionState()
        self.strategy_name: str = "test"
        self.readiness: list[tuple[str, bool]] = []
        self.wire: list[tuple[str, str]] = []
        self._fail_restore: set[str] = set()

    # -- venue-level instrument topic (shared client surface) ---------
    def subscribe_instruments(self, venue: Any, client_id: Any = None) -> Any:
        _ = venue
        self.wire.append(("subscribe_instruments", str(client_id)))
        return None

    def unsubscribe_instruments(self, venue: Any, client_id: Any = None) -> Any:
        _ = venue
        self.wire.append(("unsubscribe_instruments", str(client_id)))
        return None

    def request_instruments(self, venue: Any, client_id: Any = None) -> Any:
        _ = venue
        self.wire.append(("request_instruments", str(client_id)))
        return None

    # -- per-instrument wire surface ----------------------------------
    def subscribe_quotes(
        self, instrument_id: object, client_id: object | None = None
    ) -> None:
        _ = client_id
        self.wire.append(("restore-quotes", str(instrument_id)))

    def subscribe_trades(
        self, instrument_id: object, client_id: object | None = None
    ) -> None:
        _ = client_id
        self.wire.append(("restore-trades", str(instrument_id)))

    def subscribe_book_deltas(
        self,
        instrument_id: object,
        *,
        book_type: object,
        client_id: object | None = None,
        managed: bool = False,
    ) -> None:
        del book_type, client_id, managed
        key = str(instrument_id)
        if key in self._fail_restore:
            raise RuntimeError("synthetic restore failure")
        self.wire.append(("restore-book", key))

    def unsubscribe_quotes(
        self, instrument_id: object, client_id: object | None = None
    ) -> None:
        _ = client_id
        self.wire.append(("drain-quotes", str(instrument_id)))

    def unsubscribe_trades(
        self, instrument_id: object, client_id: object | None = None
    ) -> None:
        _ = client_id
        self.wire.append(("drain-trades", str(instrument_id)))

    def unsubscribe_book_deltas(
        self, instrument_id: object, client_id: object | None = None
    ) -> None:
        _ = client_id
        self.wire.append(("drain-book", str(instrument_id)))

    # -- lifecycle surface --------------------------------------------
    def _note_runtime_readiness(
        self,
        condition_id: str,
        *,
        ready: bool,
        status: object | None = None,
        reason: str | None = None,
    ) -> None:
        _ = status, reason
        self.readiness.append((condition_id, ready))

    def _readiness_detail(
        self,
        condition_id: str,
        *,
        now: datetime,
    ) -> dict[str, object]:
        del condition_id, now
        return {}

    def _note_runtime_progress(
        self,
        phase: str,
        *,
        active_condition_ids: object | None = None,
    ) -> None:
        del phase, active_condition_ids

    def _require_registry(self) -> MarketCatalog:
        if self.registry is None:
            raise RuntimeError("registry unavailable")
        return self.registry

    def _require_assembler(self) -> object:
        return object()

    def _refresh_asset_conditions(self) -> None:
        return None

    def _subscribe_market_conditions(self, condition_ids: object) -> None:
        del condition_ids

    def _unsubscribe_market_conditions(self, condition_ids: object) -> None:
        del condition_ids

    def _unsubscribe_all_market_instruments(self) -> None:
        return None

    def subscribe_data(
        self, data_type: object, client_id: object | None = None
    ) -> None:
        del data_type, client_id

    def unsubscribe_data(
        self, data_type: object, client_id: object | None = None
    ) -> None:
        del data_type, client_id

    def evaluate_condition(
        self,
        condition_id: str,
        *,
        trading_state: object | None = None,
    ) -> None:
        _ = trading_state
        if condition_id in self._active_condition_ids:
            self.wire.append(("evaluate", condition_id))

    def _framework_now(self) -> datetime:
        return _NOW


class _Clock:
    def __init__(self, now: datetime) -> None:
        self._now_ns = int(now.timestamp() * 1_000_000_000)

    def timestamp_ns(self) -> int:
        return self._now_ns

    def set_timer(self, name: object, interval: object, *, callback: object) -> None:
        del name, interval, callback

    def cancel_timer(self, name: object) -> None:
        del name


class _HeartbeatHost(_RecordingStrategy):
    """Host for on_evaluation_heartbeat (discovery + recovery loop)."""

    def __init__(self, registry: MarketCatalog, *, now: datetime) -> None:
        super().__init__(registry)
        self.clock = _Clock(now)
        self.trader_id = object()
        self.strategy_id: str | None = None
        self._execution_mode = "live"
        self._evaluation_heartbeat_started = True
        self._subscriptions_started = True
        self._last_market_data_evaluation_at: dict[str, datetime] = {}
        self._market_config: object = SimpleNamespace(timeframes=("5m", "15m"))
        self._spot_data_source: str = "none"
        self.assembler: object = SimpleNamespace(books=None)
        self._last_market_discovery_at: datetime | None = None
        self._market_discovery_enabled = False


@pytest.fixture(autouse=True)
def _reset_process_globals() -> None:
    _clear_global_book_recovery_state()
    life._ADAPTER_REFRESH_AT_BY_CLIENT.clear()


def wire_counts(strategy: _RecordingStrategy, prefix: str) -> int:
    return sum(1 for kind, _label in strategy.wire if kind.startswith(prefix))


def _seed_awaiting_stalled(
    strategy: _RecordingStrategy,
    condition_id: str,
    *,
    started_at: datetime,
) -> None:
    state = strategy._subscription_state
    state.condition_phases[condition_id] = (
        ConditionSubscriptionPhase.AWAITING_FIRST_BOOK
    )
    state.awaiting_book_sides_by_condition[condition_id] = {Side.UP, Side.DOWN}
    state.book_generation_started_at_by_condition[condition_id] = started_at
    state.book_stalled_started_at_by_condition[condition_id] = started_at
    state.subscribed_instrument_ids.update(_instrument_keys(condition_id))


def _seed_ready_fresh(
    strategy: _RecordingStrategy,
    condition_id: str,
    *,
    received_at: datetime,
) -> None:
    state = strategy._subscription_state
    state.condition_phases[condition_id] = ConditionSubscriptionPhase.READY
    state.first_bilateral_book_at_by_condition[condition_id] = received_at
    state.first_bilateral_book_ever_at_by_condition[condition_id] = received_at
    state.last_book_received_at_by_condition[condition_id] = {
        Side.UP: received_at,
        Side.DOWN: received_at,
    }
    state.subscribed_instrument_ids.update(_instrument_keys(condition_id))


def _seed_ready_stalled(
    strategy: _RecordingStrategy,
    condition_id: str,
    *,
    now: datetime,
) -> None:
    state = strategy._subscription_state
    state.condition_phases[condition_id] = ConditionSubscriptionPhase.READY
    state.first_bilateral_book_at_by_condition[condition_id] = now - timedelta(
        minutes=9
    )
    state.first_bilateral_book_ever_at_by_condition[condition_id] = now - timedelta(
        minutes=10
    )
    state.last_book_received_at_by_condition[condition_id] = {
        Side.UP: now - timedelta(seconds=400),
        Side.DOWN: now - timedelta(seconds=400),
    }
    state.subscribed_instrument_ids.update(_instrument_keys(condition_id))


def _flush_restores(strategy: _RecordingStrategy, *, after: datetime) -> None:
    _flush_pending_book_restores(
        strategy,
        now=after + timedelta(seconds=_BOOK_RECOVERY_RESTORE_DELAY_SEC + 1),
    )


def _assert_recovery_quiet(
    strategy: _RecordingStrategy, condition_id: str, *, now: datetime
) -> None:
    """No force path may drain/restore the condition at this point."""
    for fn in (
        force_resubscribe_if_book_stalled,
        force_resubscribe_if_stale_orderbook,
        force_resubscribe_if_stale_receipt,
    ):
        assert fn(strategy, condition_id, now=now) is False
    assert wire_counts(strategy, "drain-book") == 2
    assert wire_counts(strategy, "restore-book") == 2


# ---------------------------------------------------------------------------
# 1. Shared-client venue refresh: additive only, coalesced per client.
# ---------------------------------------------------------------------------


def test_venue_refresh_never_unsubscribes_shared_client() -> None:
    """The adapter refresh must never dispatch a venue/client-wide
    unsubscribe_instruments: the Polymarket data client is shared by every
    strategy, and an unsubscribe would decrement the instrument-topic refcount
    and tear down delivery for the fleet."""
    strategy = _RecordingStrategy(_registry())

    refreshed = life._request_instrument_refresh(cast(Any, strategy), now=_NOW)

    assert refreshed == 2  # 5m + 15m clients
    kinds = [kind for kind, _label in strategy.wire]
    assert "unsubscribe_instruments" not in kinds
    # Strictly additive: affirm the subscription, then drive the load,
    # once per due client — no venue-level teardown ever.
    assert kinds == [
        "subscribe_instruments",
        "request_instruments",
        "subscribe_instruments",
        "request_instruments",
    ]
    # A second heartbeat inside the 300s window: nothing re-dispatches.
    strategy.wire.clear()
    assert (
        life._request_instrument_refresh(
            cast(Any, strategy), now=_NOW + timedelta(seconds=1)
        )
        == 0
    )
    assert strategy.wire == []


def test_shared_client_refresh_coalesces_across_strategies() -> None:
    """Two strategies sharing the same data clients must coalesce onto one
    adapter load per client per window — never one refresh per strategy per
    condition per heartbeat."""
    strategy_a = _RecordingStrategy(_registry())
    strategy_b = _RecordingStrategy(_registry())

    assert life._request_instrument_refresh(cast(Any, strategy_a), now=_NOW) == 2
    # One second later the buckets are consumed: B dispatches nothing.
    assert (
        life._request_instrument_refresh(
            cast(Any, strategy_b), now=_NOW + timedelta(seconds=1)
        )
        == 0
    )
    assert strategy_b.wire == []

    # New reconnect generation (bucket elapsed): the next fleet member drives
    # the load again, and the per-client bucketing still bounds it.
    later = _NOW + timedelta(seconds=301)
    assert life._request_instrument_refresh(cast(Any, strategy_b), now=later) == 2
    assert life._request_instrument_refresh(cast(Any, strategy_a), now=later) == 0


def test_heartbeat_stall_refresh_coalesces_under_repeated_reconnects() -> None:
    """Repeated heartbeat/reconnect rounds while books are stalled drive one
    adapter load per client per window, not one per heartbeat."""
    strategy = _RecordingStrategy(_registry())
    state = strategy._subscription_state
    for i in range(5):
        state.awaiting_book_sides_by_condition[f"cond-{i}"] = {Side.UP}

    assert life._data_stall_refresh_due(cast(Any, strategy), now=_NOW) is True
    assert life._request_instrument_refresh(cast(Any, strategy), now=_NOW) == 2
    for round_no in range(6):
        assert (
            life._request_instrument_refresh(
                cast(Any, strategy),
                now=_NOW + timedelta(seconds=10 * (round_no + 1)),
            )
            == 0
        )
    assert wire_counts(strategy, "request_instruments") == 2


# ---------------------------------------------------------------------------
# 2. Book recovery: single-flight drain/restore, bounded failure retry.
# ---------------------------------------------------------------------------


def test_recovery_drain_is_single_flight_until_restore_completes() -> None:
    """Repeated heartbeats must not re-drain an instrument whose drain →
    restore cycle is pending or whose retry anchor is fresh."""
    from polysignal_lab.nautilus_runtime.strategy.lifecycle import (
        _recover_book_subscriptions,
    )

    strategy = _HeartbeatHost(_registry("BTC"), now=_NOW)
    strategy._active_condition_ids = {"btc-5m"}
    now = _NOW
    _seed_awaiting_stalled(strategy, "btc-5m", started_at=now - timedelta(seconds=70))

    hb = now + timedelta(seconds=10)
    # Heartbeat 1: the stalled condition is drained exactly once.
    _recover_book_subscriptions(strategy, ("btc-5m",), now=hb)
    assert wire_counts(strategy, "drain-book") == 2
    assert wire_counts(strategy, "restore-book") == 0  # restore is deferred
    assert set(_global_book_restore_pending) == set(_instrument_keys("btc-5m"))

    # Heartbeats 2..4 inside the retry window: single-flight, no re-drain.
    for round_no in range(3):
        _recover_book_subscriptions(
            strategy, ("btc-5m",), now=hb + timedelta(seconds=10 * (round_no + 1))
        )
    assert wire_counts(strategy, "drain-book") == 2

    # Phase 2 restore lands on the flush turn; a later heartbeat still cannot
    # re-drain within the retry window.
    _flush_restores(strategy, after=hb)
    assert wire_counts(strategy, "restore-book") == 2
    _recover_book_subscriptions(strategy, ("btc-5m",), now=hb + timedelta(seconds=30))
    assert wire_counts(strategy, "drain-book") == 2

    # Past the retry window the repair is re-attempted — bounded, retryable.
    retry_at = hb + timedelta(
        seconds=_BOOK_RECOVERY_RETRY_SEC + _BOOK_RECOVERY_RESTORE_DELAY_SEC + 1
    )
    _recover_book_subscriptions(strategy, ("btc-5m",), now=retry_at)
    assert wire_counts(strategy, "drain-book") == 4


def test_failed_restore_bounds_retry_across_shared_strategies() -> None:
    """A restore failure must not let the next heartbeat re-drain the same
    shared instrument (potentially alternating across strategies): the failure
    consumes the process-wide retry anchor, so the next attempt waits out the
    retry window — retryable, never stormed."""
    from polysignal_lab.nautilus_runtime.strategy.lifecycle import (
        _recover_book_subscriptions,
    )

    now = _NOW
    strategy_a = _RecordingStrategy(_registry("BTC"))
    strategy_b = _RecordingStrategy(_registry("BTC"))
    strategy_a.strategy_name = "a"
    strategy_b.strategy_name = "b"
    for strategy in (strategy_a, strategy_b):
        strategy._active_condition_ids = {"btc-5m"}
        _seed_awaiting_stalled(
            strategy, "btc-5m", started_at=now - timedelta(seconds=70)
        )
        _register_subscription_strategy(strategy)
    try:
        # First drain comes from A; the restore is made to fail for both
        # owner strategies (shared token).
        strategy_a._fail_restore.update(_instrument_keys("btc-5m"))
        strategy_b._fail_restore.update(_instrument_keys("btc-5m"))
        assert force_resubscribe_if_book_stalled(strategy_a, "btc-5m", now=now) is True
        _flush_restores(strategy_a, after=now)
        assert wire_counts(strategy_a, "drain-book") == 2
        # The failed restore recorded the retry anchor: the next heartbeat on
        # EITHER strategy must not add another drain.
        assert set(_global_book_recovery_times) == set(_instrument_keys("btc-5m"))
        strategy_a._fail_restore.clear()
        strategy_b._fail_restore.clear()
        # A's first drain already released the shared token through B's wires
        # (_drain_market_subscription_owners iterates every owner); B's own
        # heartbeat must not re-drain it a second time.
        b_drain_before = wire_counts(strategy_b, "drain-book")
        _recover_book_subscriptions(
            strategy_b, ("btc-5m",), now=now + timedelta(seconds=10)
        )
        assert wire_counts(strategy_a, "drain-book") == 2
        assert wire_counts(strategy_b, "drain-book") == b_drain_before
        assert wire_counts(strategy_b, "restore-book") == 0
        # Mid-window still suppressed.
        _recover_book_subscriptions(
            strategy_a,
            ("btc-5m",),
            now=now + timedelta(seconds=_BOOK_RECOVERY_RETRY_SEC - 10),
        )
        assert wire_counts(strategy_a, "drain-book") == 2
        # After the window the failing condition can be retried.
        retry_at = now + timedelta(
            seconds=_BOOK_RECOVERY_RETRY_SEC + _BOOK_RECOVERY_RESTORE_DELAY_SEC + 1
        )
        _recover_book_subscriptions(strategy_a, ("btc-5m",), now=retry_at)
        assert wire_counts(strategy_a, "drain-book") == 4
        _flush_restores(strategy_a, after=retry_at)
        assert wire_counts(strategy_a, "restore-book") == 2
    finally:
        _unregister_subscription_strategy(strategy_a)
        _unregister_subscription_strategy(strategy_b)


# ---------------------------------------------------------------------------
# 3. Explicit state transitions: stale-receipt repair and READY/awaiting mix.
# ---------------------------------------------------------------------------


def test_stale_receipt_repair_does_not_redrain_recovered_condition() -> None:
    """A once-READY condition repaired through the stale-receipt path must not
    be drained again after its book recovered: the stall marker is one-shot per
    episode (issue69 recovery storm)."""
    now = _NOW
    strategy = _RecordingStrategy(_registry("BTC"))
    strategy._active_condition_ids = {"btc-5m"}
    _seed_ready_stalled(strategy, "btc-5m", now=now)

    triggered = force_resubscribe_if_stale_receipt(strategy, "btc-5m", now=now)
    assert triggered is True
    # The one-shot marker is consumed by the dispatch itself.
    assert "btc-5m" not in strategy._stale_orderbook_recovery_by_condition
    _flush_restores(strategy, after=now)
    # Books recover the condition to READY.
    received = now + timedelta(seconds=2)
    observe_market_book_side(
        strategy, "btc-5m", Side.UP, received_at=received, book_at=received
    )
    observe_market_book_side(
        strategy, "btc-5m", Side.DOWN, received_at=received, book_at=received
    )
    assert (
        strategy._subscription_state.condition_phases["btc-5m"]
        is ConditionSubscriptionPhase.READY
    )
    # 121s after recovery: no force path may touch the healthy condition.
    _assert_recovery_quiet(strategy, "btc-5m", now=received + timedelta(seconds=121))


def test_mixed_healthy_ready_and_stalled_awaiting_have_explicit_transitions() -> None:
    """One heartbeat with a fresh READY condition next to a stalled awaiting
    condition must drain only the stalled instruments; the READY condition's
    wires stay untouched and the lifecycle invariants hold."""
    strategy = _HeartbeatHost(_registry("BTC", "ETH"), now=_NOW)
    strategy._active_condition_ids = {"btc-5m", "eth-5m"}
    _seed_ready_fresh(strategy, "btc-5m", received_at=_NOW - timedelta(seconds=5))
    _seed_awaiting_stalled(strategy, "eth-5m", started_at=_NOW - timedelta(seconds=70))

    assert_subscription_invariants(cast(Any, strategy))

    hb = _NOW + timedelta(seconds=10)
    life.on_evaluation_heartbeat(cast(Any, strategy), object())

    _flush_restores(strategy, after=hb)
    drained_book = sorted(
        label for kind, label in strategy.wire if kind == "drain-book"
    )
    assert drained_book == sorted(_instrument_keys("eth-5m"))
    wire_labels = [
        label
        for kind, label in strategy.wire
        if kind.startswith(("drain-", "restore-"))
    ]
    assert all("btc-5m" not in label for label in wire_labels)
    assert_subscription_invariants(cast(Any, strategy))
    # Restores were limited to the drained instrument pair.
    assert wire_counts(strategy, "restore-book") == 2

    # The READY condition is still READY and quiet afterwards.
    assert (
        strategy._subscription_state.condition_phases["btc-5m"]
        is ConditionSubscriptionPhase.READY
    )
    _assert_recovery_quiet(strategy, "btc-5m", now=hb + timedelta(seconds=10))
