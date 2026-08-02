from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import hypothesis.strategies as st
from hypothesis import settings
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.strategy_readiness import StrategyStatus
from polysignal_lab.nautilus_runtime.market_catalog import (
    InstrumentTokenMeta,
    MarketCatalog,
    MarketPairMeta,
)
from polysignal_lab.nautilus_runtime.strategy.invariants import (
    assert_subscription_invariants,
)
from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
    ConditionSubscriptionPhase,
    MarketSubscriptionState,
    begin_market_book_generation,
    clear_condition_lifecycle_state,
    condition_phase,
    observe_market_book_side,
    on_instrument_available,
    subscribe_market_conditions,
    unsubscribe_all_market_instruments,
)

CONDITIONS = ("cond-a", "cond-b", "cond-c")


def _pair(condition_id: str) -> MarketPairMeta:
    return MarketPairMeta(
        market_id=f"market-{condition_id}",
        market_slug=f"slug-{condition_id}",
        condition_id=condition_id,
        asset="BTC",
        timeframe="5m",
        start_ts=None,
        end_ts=None,
        up=InstrumentTokenMeta(f"{condition_id}-UP", Side.UP),
        down=InstrumentTokenMeta(f"{condition_id}-DOWN", Side.DOWN),
    )


def _instrument_id(condition_id: str, token_id: str) -> str:
    return f"{token_id}.POLYMARKET"


def _make_registry() -> MarketCatalog:
    return MarketCatalog(instrument_id_resolver=_instrument_id)


def _instrument_key_for(condition_id: str, side: Side) -> str:
    return f"{condition_id}-{side.value}.POLYMARKET"


class _StubCache:
    """Cache whose instrument getter raises LookupError before the instrument
    has arrived (mirrors the Nautilus Cache visibility gate)."""

    def __init__(self) -> None:
        self.available: set[str] = set()

    def instrument(self, instrument_id: object) -> object:
        key = str(instrument_id)
        if key not in self.available:
            raise LookupError(key)
        return SimpleNamespace(id=key)


class _StubStrategy:
    """Unit host without a real Nautilus engine, modeled on the
    _UniverseStrategy stub in test_nautilus_subscription_health.py."""

    def __init__(self, registry: MarketCatalog) -> None:
        self.registry = registry
        self.cache = _StubCache()
        self._startup_condition_ids: tuple[str, ...] = ()
        self._active_condition_ids: set[str] = set()
        self._asset_condition_ids: dict[str, tuple[str, ...]] = {}
        self._subscription_state = MarketSubscriptionState()
        self._subscription_assets = frozenset({"BTC"})
        self._subscription_timeframes = frozenset({"5m"})
        self._untradable_quote_sides_by_condition: dict[str, frozenset[Side]] = {}
        self._stale_orderbook_recovery_by_condition: dict[str, dict[Side, float]] = {}
        self._runtime_readiness_reason_by_condition: dict[str, str] = {}
        self._runtime_readiness_miss_condition_ids: set[str] = set()
        self.book_type = "L2_MBP"
        self.unsubscribe_exited = True
        self._clock = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
        self.subscribe_book_deltas_raises = False
        self.subscribe_calls: list[tuple[str, str]] = []

    def _note_runtime_readiness(
        self,
        condition_id: str,
        *,
        ready: bool,
        status: StrategyStatus | None = None,
        reason: str | None = None,
    ) -> None:
        _ = condition_id, ready, status, reason

    def _framework_now(self) -> datetime:
        self._clock += timedelta(milliseconds=100)
        return self._clock

    def _readiness_detail(self, condition_id: str, *, now: datetime) -> dict[str, object]:
        _ = condition_id, now
        return {}

    def subscribe_quotes(
        self, instrument_id: object, client_id: object | None = None
    ) -> object:
        _ = client_id
        self.subscribe_calls.append(("quotes", str(instrument_id)))
        return None

    def subscribe_trades(
        self, instrument_id: object, client_id: object | None = None
    ) -> object:
        _ = client_id
        self.subscribe_calls.append(("trades", str(instrument_id)))
        return None

    def subscribe_book_deltas(
        self,
        instrument_id: object,
        *,
        book_type: object = None,
        client_id: object | None = None,
        managed: bool = False,
    ) -> object:
        _ = book_type, client_id, managed
        self.subscribe_calls.append(("book", str(instrument_id)))
        if self.subscribe_book_deltas_raises:
            raise RuntimeError("subscribe api failed")
        return None

    def unsubscribe_quotes(
        self, instrument_id: object, client_id: object | None = None
    ) -> object:
        _ = instrument_id, client_id
        return None

    def unsubscribe_trades(
        self, instrument_id: object, client_id: object | None = None
    ) -> object:
        _ = instrument_id, client_id
        return None

    def unsubscribe_book_deltas(
        self, instrument_id: object, client_id: object | None = None
    ) -> object:
        _ = instrument_id, client_id
        return None


@settings(max_examples=120, stateful_step_count=90, deadline=None)
class _SubscriptionLifecycle(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.registry = _make_registry()
        self.strategy = _StubStrategy(self.registry)
        self.metadata: set[str] = set()

    def _subscribe(self, condition_id: str) -> None:
        subscribe_market_conditions(  # type: ignore[arg-type]
            self.strategy,
            (condition_id,),
            now=self.strategy._framework_now(),
        )

    @rule(condition_id=st.sampled_from(CONDITIONS))
    def activate(self, condition_id: str) -> None:
        self.strategy._active_condition_ids.add(condition_id)
        self._subscribe(condition_id)
        assert_subscription_invariants(self.strategy)

    @rule(condition_id=st.sampled_from(CONDITIONS))
    def register_metadata(self, condition_id: str) -> None:
        self.registry.register(_pair(condition_id))
        self.metadata.add(condition_id)
        self._subscribe(condition_id)
        assert_subscription_invariants(self.strategy)

    @rule(
        condition_id=st.sampled_from(CONDITIONS),
        side=st.sampled_from([Side.UP, Side.DOWN]),
    )
    def instrument_arrives(self, condition_id: str, side: Side) -> None:
        key = _instrument_key_for(condition_id, side)
        self.strategy.cache.available.add(key)
        on_instrument_available(  # type: ignore[arg-type]
            self.strategy,
            SimpleNamespace(id=key),
        )
        assert_subscription_invariants(self.strategy)

    @rule(
        condition_id=st.sampled_from(CONDITIONS),
        side=st.sampled_from([Side.UP, Side.DOWN]),
    )
    def duplicate_instrument(self, condition_id: str, side: Side) -> None:
        key = _instrument_key_for(condition_id, side)
        if key in self.strategy.cache.available:
            on_instrument_available(  # type: ignore[arg-type]
                self.strategy,
                SimpleNamespace(id=key),
            )
        assert_subscription_invariants(self.strategy)

    @rule(
        condition_id=st.sampled_from(CONDITIONS),
        side=st.sampled_from([Side.UP, Side.DOWN]),
    )
    def book_arrives(self, condition_id: str, side: Side) -> None:
        # Books can only arrive for a subscribed instrument; a condition whose
        # instruments are still pending (not Cache-visible) cannot produce book
        # callbacks in the real engine. Skip to avoid an unreachable state.
        phase = condition_phase(self.strategy, condition_id)
        if phase not in {
            ConditionSubscriptionPhase.AWAITING_FIRST_BOOK,
            ConditionSubscriptionPhase.READY,
            ConditionSubscriptionPhase.SUBSCRIBE_ISSUED,
        }:
            return
        now = self.strategy._framework_now()
        observe_market_book_side(  # type: ignore[arg-type]
            self.strategy,
            condition_id,
            side,
            received_at=now,
            book_at=now,
        )
        assert_subscription_invariants(self.strategy)

    @rule(
        condition_id=st.sampled_from(CONDITIONS),
        side=st.sampled_from([Side.UP, Side.DOWN]),
    )
    def old_book(self, condition_id: str, side: Side) -> None:
        # A book stamped before the generation start must be dropped, never
        # satisfy a pending side.
        now = self.strategy._framework_now()
        started = self.strategy._subscription_state.book_generation_started_at_by_condition.get(
            condition_id
        )
        received_at = started - timedelta(seconds=5) if started is not None else now
        observe_market_book_side(  # type: ignore[arg-type]
            self.strategy,
            condition_id,
            side,
            received_at=received_at,
            book_at=received_at,
        )
        assert_subscription_invariants(self.strategy)

    @rule(
        condition_id=st.sampled_from(CONDITIONS),
        side=st.sampled_from([Side.UP, Side.DOWN]),
    )
    def delayed_book(self, condition_id: str, side: Side) -> None:
        # A callback that arrives long after the window (rotation/cleanup) must
        # not resurrect a retired lifecycle. Only fire when instruments are
        # subscribed (phase AWAITING_FIRST_BOOK/READY): a pending instrument is
        # never subscribed, so it cannot produce a book callback in the engine.
        phase = condition_phase(self.strategy, condition_id)
        if phase not in {
            ConditionSubscriptionPhase.AWAITING_FIRST_BOOK,
            ConditionSubscriptionPhase.READY,
        }:
            return
        now = self.strategy._framework_now()
        observe_market_book_side(  # type: ignore[arg-type]
            self.strategy,
            condition_id,
            side,
            received_at=now + timedelta(days=1),
            book_at=now + timedelta(days=1),
        )
        assert_subscription_invariants(self.strategy)

    @rule(condition_id=st.sampled_from(CONDITIONS))
    def mark_stale(self, condition_id: str) -> None:
        if condition_id not in self.strategy._active_condition_ids:
            return
        self.strategy._stale_orderbook_recovery_by_condition[condition_id] = {
            Side.UP: 60_000.0
        }
        self.strategy._runtime_readiness_reason_by_condition[condition_id] = (
            "stale_orderbook"
        )
        assert_subscription_invariants(self.strategy)

    @rule(condition_id=st.sampled_from(CONDITIONS))
    def mark_untradable(self, condition_id: str) -> None:
        if condition_id not in self.strategy._active_condition_ids:
            return
        self.strategy._untradable_quote_sides_by_condition[condition_id] = frozenset(
            {Side.UP}
        )
        assert_subscription_invariants(self.strategy)

    @rule(condition_id=st.sampled_from(CONDITIONS))
    def recover(self, condition_id: str) -> None:
        _ = self.strategy._stale_orderbook_recovery_by_condition.pop(condition_id, None)
        _ = self.strategy._runtime_readiness_reason_by_condition.pop(condition_id, None)
        _ = self.strategy._untradable_quote_sides_by_condition.pop(condition_id, None)
        _ = self.strategy._runtime_readiness_miss_condition_ids.discard(condition_id)
        assert_subscription_invariants(self.strategy)

    @rule(condition_id=st.sampled_from(CONDITIONS))
    def rotate_out(self, condition_id: str) -> None:
        self.strategy._active_condition_ids.discard(condition_id)
        clear_condition_lifecycle_state(  # type: ignore[arg-type]
            self.strategy,
            condition_id,
            clear_history=True,
        )
        assert_subscription_invariants(self.strategy)

    @rule(condition_id=st.sampled_from(CONDITIONS))
    def rotate_back(self, condition_id: str) -> None:
        self.strategy._active_condition_ids.add(condition_id)
        self._subscribe(condition_id)
        assert_subscription_invariants(self.strategy)

    @rule()
    def unsubscribe_all(self) -> None:
        for condition_id in tuple(self.strategy._active_condition_ids):
            clear_condition_lifecycle_state(  # type: ignore[arg-type]
                self.strategy,
                condition_id,
                clear_history=True,
            )
        self.strategy._active_condition_ids.clear()
        unsubscribe_all_market_instruments(self.strategy)  # type: ignore[arg-type]
        assert_subscription_invariants(self.strategy)

    @rule()
    def unsubscribe_all_terminal(self) -> None:
        """Exercise the standalone terminal teardown: orthogonal readiness
        markers are the caller's job (clear_condition_lifecycle_state), but
        unsubscribe_all_market_instruments must itself retire any open book
        generation. With the fix removed, a leftover awaiting side survives
        with no phase and the invariant fires."""
        for condition_id in tuple(self.strategy._active_condition_ids):
            _ = self.strategy._untradable_quote_sides_by_condition.pop(
                condition_id, None
            )
            _ = self.strategy._stale_orderbook_recovery_by_condition.pop(
                condition_id, None
            )
            _ = self.strategy._runtime_readiness_reason_by_condition.pop(
                condition_id, None
            )
            _ = self.strategy._runtime_readiness_miss_condition_ids.discard(
                condition_id
            )
        self.strategy._active_condition_ids.clear()
        unsubscribe_all_market_instruments(self.strategy)  # type: ignore[arg-type]
        assert_subscription_invariants(self.strategy)

    @rule()
    def replace_registry(self) -> None:
        new_registry = _make_registry()
        for condition_id in self.metadata:
            new_registry.register(_pair(condition_id))
        self.registry = new_registry
        self.strategy.registry = new_registry
        assert_subscription_invariants(self.strategy)

    @rule(condition_id=st.sampled_from(CONDITIONS))
    def subscribe_api_throws(self, condition_id: str) -> None:
        self.strategy._active_condition_ids.add(condition_id)
        self.strategy.subscribe_book_deltas_raises = True
        try:
            self._subscribe(condition_id)
        except RuntimeError:
            pass
        finally:
            self.strategy.subscribe_book_deltas_raises = False
        # The wedge (subscribe API failure) must resolve once the API recovers:
        # a re-subscribe with Cache-visible instruments must re-establish the
        # subscribed set and let the lifecycle progress, not sit wedged.
        self.strategy.cache.available.update(
            {
                _instrument_key_for(condition_id, Side.UP),
                _instrument_key_for(condition_id, Side.DOWN),
            }
        )
        self._subscribe(condition_id)
        for side in (Side.UP, Side.DOWN):
            on_instrument_available(  # type: ignore[arg-type]
                self.strategy,
                SimpleNamespace(id=_instrument_key_for(condition_id, side)),
            )
        assert_subscription_invariants(self.strategy)

    @invariant()
    def lifecycle_confined_to_active(self) -> None:
        assert_subscription_invariants(self.strategy)


TestSubscriptionLifecycle = _SubscriptionLifecycle.TestCase


def test_market_book_generation_ready_false_for_unsubscribed_condition() -> None:
    from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
        market_book_generation_ready,
    )

    strategy = _StubStrategy(_make_registry())
    # Never-subscribed / never-READY condition must not be reported ready.
    assert not market_book_generation_ready(strategy, "cond-a")  # type: ignore[arg-type]

    now = strategy._framework_now()
    begin_market_book_generation(strategy, "cond-a", now=now)  # type: ignore[arg-type]
    assert not market_book_generation_ready(strategy, "cond-a")  # type: ignore[arg-type]

    observe_market_book_side(  # type: ignore[arg-type]
        strategy,
        "cond-a",
        Side.UP,
        received_at=now,
        book_at=now,
    )
    observe_market_book_side(  # type: ignore[arg-type]
        strategy,
        "cond-a",
        Side.DOWN,
        received_at=now,
        book_at=now,
    )
    assert market_book_generation_ready(strategy, "cond-a")  # type: ignore[arg-type]


def test_cleanup_late_callback_does_not_revive_lifecycle() -> None:
    strategy = _StubStrategy(_make_registry())
    now = strategy._framework_now()

    begin_market_book_generation(strategy, "cond-a", now=now)  # type: ignore[arg-type]
    observe_market_book_side(  # type: ignore[arg-type]
        strategy,
        "cond-a",
        Side.UP,
        received_at=now,
        book_at=now,
    )
    # Clean up mid-generation (unsubscribe_all / rotate out).
    clear_condition_lifecycle_state(  # type: ignore[arg-type]
        strategy,
        "cond-a",
        clear_history=True,
    )
    assert condition_phase(strategy, "cond-a") is ConditionSubscriptionPhase.UNSUBSCRIBED

    # A delayed DOWN book arrives after cleanup; it must not resurrect READY.
    late = now + timedelta(seconds=60)
    observe_market_book_side(  # type: ignore[arg-type]
        strategy,
        "cond-a",
        Side.DOWN,
        received_at=late,
        book_at=late,
    )
    assert condition_phase(strategy, "cond-a") is ConditionSubscriptionPhase.UNSUBSCRIBED
    assert "cond-a" not in strategy._subscription_state.first_bilateral_book_at_by_condition
    assert "cond-a" not in strategy._subscription_state.awaiting_book_sides_by_condition
    assert_subscription_invariants(strategy)


def test_unsubscribe_all_retires_open_generations() -> None:
    strategy = _StubStrategy(_make_registry())
    now = strategy._framework_now()

    begin_market_book_generation(strategy, "cond-a", now=now)  # type: ignore[arg-type]
    observe_market_book_side(  # type: ignore[arg-type]
        strategy,
        "cond-a",
        Side.UP,
        received_at=now,
        book_at=now,
    )
    unsubscribe_all_market_instruments(strategy)  # type: ignore[arg-type]

    assert "cond-a" not in strategy._subscription_state.awaiting_book_sides_by_condition
    assert (
        "cond-a" not in strategy._subscription_state.book_generation_started_at_by_condition
    )
    assert condition_phase(strategy, "cond-a") is ConditionSubscriptionPhase.UNSUBSCRIBED

    late = now + timedelta(seconds=60)
    observe_market_book_side(  # type: ignore[arg-type]
        strategy,
        "cond-a",
        Side.DOWN,
        received_at=late,
        book_at=late,
    )
    assert condition_phase(strategy, "cond-a") is ConditionSubscriptionPhase.UNSUBSCRIBED
    assert_subscription_invariants(strategy)


def test_illegal_phase_transition_is_rejected() -> None:
    from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
        _transition_condition_phase,
    )

    state = MarketSubscriptionState()
    # UNSUBSCRIBED -> READY is not a legal forward transition.
    try:
        _transition_condition_phase(
            state,
            "cond-a",
            ConditionSubscriptionPhase.READY,
        )
    except AssertionError:
        pass
    else:
        raise AssertionError("UNSUBSCRIBED -> READY must be rejected")

    # UNSUBSCRIBED -> AWAITING_FIRST_BOOK (via begin) is legal.
    _transition_condition_phase(
        state,
        "cond-a",
        ConditionSubscriptionPhase.AWAITING_FIRST_BOOK,
    )
    assert state.condition_phases["cond-a"] is ConditionSubscriptionPhase.AWAITING_FIRST_BOOK


def test_pending_and_subscribed_instruments_disjoint() -> None:
    strategy = _StubStrategy(_make_registry())
    strategy.registry.register(_pair("cond-a"))
    strategy._active_condition_ids.add("cond-a")
    strategy.cache.available.add(_instrument_key_for("cond-a", Side.UP))
    strategy.cache.available.add(_instrument_key_for("cond-a", Side.DOWN))
    subscribe_market_conditions(  # type: ignore[arg-type]
        strategy,
        ("cond-a",),
        now=strategy._framework_now(),
    )
    assert not (
        strategy._subscription_state.pending_instrument_ids
        & strategy._subscription_state.subscribed_instrument_ids
    )
    assert_subscription_invariants(strategy)


def test_rotation_cycle_equivalent_to_fresh_condition() -> None:
    def ready_condition() -> _StubStrategy:
        strategy = _StubStrategy(_make_registry())
        strategy.registry.register(_pair("cond-a"))
        strategy._active_condition_ids.add("cond-a")
        strategy.cache.available.update(
            {
                _instrument_key_for("cond-a", Side.UP),
                _instrument_key_for("cond-a", Side.DOWN),
            }
        )
        subscribe_market_conditions(  # type: ignore[arg-type]
            strategy,
            ("cond-a",),
            now=strategy._framework_now(),
        )
        now = strategy._framework_now()
        observe_market_book_side(  # type: ignore[arg-type]
            strategy, "cond-a", Side.UP, received_at=now, book_at=now
        )
        observe_market_book_side(  # type: ignore[arg-type]
            strategy, "cond-a", Side.DOWN, received_at=now, book_at=now
        )
        return strategy

    fresh = ready_condition()

    rotated = ready_condition()
    # Rotate out and back in; the effective lifecycle state must equal fresh.
    clear_condition_lifecycle_state(  # type: ignore[arg-type]
        rotated,
        "cond-a",
        clear_history=True,
    )
    rotated._active_condition_ids.add("cond-a")
    subscribe_market_conditions(  # type: ignore[arg-type]
        rotated,
        ("cond-a",),
        now=rotated._framework_now(),
    )
    now = rotated._framework_now()
    observe_market_book_side(  # type: ignore[arg-type]
        rotated, "cond-a", Side.UP, received_at=now, book_at=now
    )
    observe_market_book_side(  # type: ignore[arg-type]
        rotated, "cond-a", Side.DOWN, received_at=now, book_at=now
    )

    assert condition_phase(rotated, "cond-a") is condition_phase(fresh, "cond-a")
    assert condition_phase(rotated, "cond-a") is ConditionSubscriptionPhase.READY
    assert rotated._subscription_state.awaiting_book_sides_by_condition == {}
    assert fresh._subscription_state.awaiting_book_sides_by_condition == {}
    assert (
        "cond-a" in rotated._subscription_state.first_bilateral_book_at_by_condition
    )
    assert "cond-a" in fresh._subscription_state.first_bilateral_book_at_by_condition
    assert_subscription_invariants(rotated)


def test_long_rotation_cardinality_is_bounded() -> None:
    strategy = _StubStrategy(_make_registry())
    for condition_id in CONDITIONS:
        strategy.registry.register(_pair(condition_id))

    # Many full rotation cycles across all conditions; lifecycle containers must
    # stay bounded to the active set (no residue for retired conditions).
    for _ in range(50):
        for condition_id in CONDITIONS:
            strategy._active_condition_ids.add(condition_id)
            strategy.cache.available.update(
                {
                    _instrument_key_for(condition_id, Side.UP),
                    _instrument_key_for(condition_id, Side.DOWN),
                }
            )
            subscribe_market_conditions(  # type: ignore[arg-type]
                strategy,
                (condition_id,),
                now=strategy._framework_now(),
            )
            now = strategy._framework_now()
            observe_market_book_side(  # type: ignore[arg-type]
                strategy, condition_id, Side.UP, received_at=now, book_at=now
            )
            observe_market_book_side(  # type: ignore[arg-type]
                strategy, condition_id, Side.DOWN, received_at=now, book_at=now
            )
            assert_subscription_invariants(strategy)
        for condition_id in CONDITIONS:
            clear_condition_lifecycle_state(  # type: ignore[arg-type]
                strategy,
                condition_id,
                clear_history=True,
            )
            strategy._active_condition_ids.discard(condition_id)
            assert_subscription_invariants(strategy)

def test_ready_repend_clears_stale_first_bilateral_marker() -> None:
    """Regression: READY -> PENDING_INSTRUMENT re-entry on rotation/recovery must
    clear the stale first-bilateral marker, or the condition wedges out of READY
    permanently (reported unready in /health until a full restart)."""
    from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
        market_book_generation_ready,
        on_instrument_available,
    )

    strategy = _StubStrategy(_make_registry())
    strategy.registry.register(_pair("cond-a"))
    strategy._active_condition_ids.add("cond-a")
    strategy.cache.available.update(
        {
            _instrument_key_for("cond-a", Side.UP),
            _instrument_key_for("cond-a", Side.DOWN),
        }
    )
    subscribe_market_conditions(  # type: ignore[arg-type]
        strategy,
        ("cond-a",),
        now=strategy._framework_now(),
    )
    now = strategy._framework_now()
    observe_market_book_side(  # type: ignore[arg-type]
        strategy, "cond-a", Side.UP, received_at=now, book_at=now
    )
    observe_market_book_side(  # type: ignore[arg-type]
        strategy, "cond-a", Side.DOWN, received_at=now, book_at=now
    )
    assert condition_phase(strategy, "cond-a") is ConditionSubscriptionPhase.READY
    assert market_book_generation_ready(strategy, "cond-a")  # type: ignore[arg-type]

    # Rotation: the condition is re-mounted with a fresh instrument identity.
    # The registry is replaced (new resolver -> new instrument keys) while the
    # instruments are NOT yet Cache-visible -> subscribe re-pends instruments.
    # This mirrors the production rotation path where a condition rotates out
    # and back in under a refreshed registry before the Cache has the new ids.
    new_registry = MarketCatalog(instrument_id_resolver=lambda cid, tid: f"NEW-{cid}-{tid}.POLYMARKET")
    new_registry = MarketCatalog(instrument_id_resolver=lambda cid, tid: f"NEW-{tid}.POLYMARKET")
    new_registry.register(_pair("cond-a"))

    def new_key(side: Side) -> str:
        return f"NEW-cond-a-{side.value}.POLYMARKET"

    strategy.registry = new_registry
    strategy._subscription_state.subscribed_instrument_ids.clear()
    strategy.cache.available.clear()
    # The new up instrument arrives via the provider callback (on_instrument)
    # while it is NOT yet Cache-visible -> subscribe_market_instrument re-pends
    # it and _recompute flips READY -> PENDING_INSTRUMENT. This is the exact
    # production path the verifier reproduced.
    on_instrument_available(  # type: ignore[arg-type]
        strategy,
        SimpleNamespace(id=new_key(Side.UP)),
    )
    assert condition_phase(strategy, "cond-a") is ConditionSubscriptionPhase.PENDING_INSTRUMENT
    # The stale first-bilateral marker must be gone (re-pend = fresh generation).
    assert (
        "cond-a" not in strategy._subscription_state.first_bilateral_book_at_by_condition
    )
    assert (
        "cond-a"
        not in strategy._subscription_state.first_bilateral_book_latency_ms_by_condition
    )
    assert_subscription_invariants(strategy)

    # Instruments resolve; the next subscribe pass (real rotation re-mounts via
    # _subscribe_market_conditions) re-opens a fresh generation. The condition
    # must reach READY again, not wedge in SUBSCRIBE_ISSUED.
    strategy.cache.available.update({new_key(Side.UP), new_key(Side.DOWN)})
    subscribe_market_conditions(  # type: ignore[arg-type]
        strategy,
        ("cond-a",),
        now=strategy._framework_now(),
    )
    for side in (Side.UP, Side.DOWN):
        on_instrument_available(  # type: ignore[arg-type]
            strategy,
            SimpleNamespace(id=new_key(side)),
        )
    assert condition_phase(strategy, "cond-a") is ConditionSubscriptionPhase.AWAITING_FIRST_BOOK
    now = strategy._framework_now()
    observe_market_book_side(  # type: ignore[arg-type]
        strategy, "cond-a", Side.UP, received_at=now, book_at=now
    )
    observe_market_book_side(  # type: ignore[arg-type]
        strategy, "cond-a", Side.DOWN, received_at=now, book_at=now
    )
    assert condition_phase(strategy, "cond-a") is ConditionSubscriptionPhase.READY
    assert market_book_generation_ready(strategy, "cond-a")  # type: ignore[arg-type]
    assert_subscription_invariants(strategy)


def test_subscribe_issued_without_stale_first_bilateral() -> None:
    """A SUBSCRIBE_ISSUED condition must not carry a stale first-bilateral marker
    (the READY-re-entry wedge); the invariant suite enforces this."""
    strategy = _StubStrategy(_make_registry())
    strategy.registry.register(_pair("cond-a"))
    strategy._active_condition_ids.add("cond-a")
    strategy._subscription_state.condition_phases["cond-a"] = (
        ConditionSubscriptionPhase.SUBSCRIBE_ISSUED
    )
    strategy._subscription_state.first_bilateral_book_at_by_condition["cond-a"] = (
        datetime(2026, 8, 1, tzinfo=UTC)
    )
    try:
        assert_subscription_invariants(strategy)
    except AssertionError:
        pass
    else:
        raise AssertionError(
            "SUBSCRIBE_ISSUED with stale first bilateral marker must violate invariants"
        )



