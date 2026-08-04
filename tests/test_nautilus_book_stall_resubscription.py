from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from nautilus_trader.core.nautilus_pyo3 import Strategy  # pyright: ignore[reportAttributeAccessIssue]

from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_runtime.market_catalog import (
    InstrumentTokenMeta,
    MarketCatalog,
    MarketPairMeta,
)
from polysignal_lab.nautilus_runtime.strategy.constants import (
    EVALUATION_HEARTBEAT_INTERVAL,
)
from polysignal_lab.nautilus_runtime.strategy.lifecycle import (
    on_evaluation_heartbeat,
)
from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
    ConditionSubscriptionPhase,
    MarketSubscriptionState,
    _BOOK_GENERATION_ABANDON_SEC,
    _BOOK_GENERATION_STALL_SEC,
    abandon_book_stalled_condition,
    force_resubscribe_if_book_stalled,
    force_resubscribe_if_stale_orderbook,
    observe_market_book_side,
)


def _pair(condition_id: str, asset: str, timeframe: str) -> MarketPairMeta:
    return MarketPairMeta(
        market_id=f"market-{condition_id}",
        market_slug=f"{asset.lower()}-updown-{timeframe}-{condition_id}",
        condition_id=condition_id,
        asset=asset,
        timeframe=timeframe,
        start_ts=None,
        end_ts=None,
        up=InstrumentTokenMeta(f"{condition_id}-up", Side.UP),
        down=InstrumentTokenMeta(f"{condition_id}-down", Side.DOWN),
    )


def _registry(condition_id: str = "btc-5m") -> MarketCatalog:
    registry = MarketCatalog(
        instrument_id_resolver=lambda _condition, token: f"{token}.POLYMARKET"
    )
    registry.register(_pair(condition_id, "BTC", "5m"))
    return registry


class _ResubscribeStrategy:
    """Duck-typed _SubscriptionStrategy that records subscribe/unsubscribe calls."""

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
        self._untradable_quote_sides_by_condition: dict[str, frozenset[Side]] = {}
        self._stale_orderbook_recovery_by_condition: dict[str, dict[Side, float]] = {}
        self._runtime_readiness_reason_by_condition: dict[str, str] = {}
        self._runtime_readiness_miss_condition_ids: set[str] = set()
        self._subscription_state = MarketSubscriptionState()
        self.subscribed_instruments: list[str] = []
        self.unsubscribed_instruments: list[str] = []
        self.snapshot_requests: list[str] = []
        self.snapshot_request_params: list[Mapping[str, object] | None] = []
        self.readiness: list[tuple[str, bool]] = []

    def _readiness_detail(
        self,
        condition_id: str,
        *,
        now: datetime,
    ) -> dict[str, object]:
        del condition_id, now
        return {}

    def _note_runtime_readiness(
        self,
        condition_id: str,
        *,
        ready: bool,
        status: object | None = None,
        reason: str | None = None,
    ) -> None:
        del status, reason
        self.readiness.append((condition_id, ready))

    def subscribe_quotes(
        self, instrument_id: object, client_id: object | None = None
    ) -> None:
        del client_id
        self.subscribed_instruments.append(str(instrument_id))

    def subscribe_trades(
        self, instrument_id: object, client_id: object | None = None
    ) -> None:
        del client_id
        self.subscribed_instruments.append(str(instrument_id))

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
        del client_id
        self.unsubscribed_instruments.append(str(instrument_id))

    def unsubscribe_trades(
        self, instrument_id: object, client_id: object | None = None
    ) -> None:
        del client_id
        self.unsubscribed_instruments.append(str(instrument_id))

    def unsubscribe_book_deltas(
        self, instrument_id: object, client_id: object | None = None
    ) -> None:
        del client_id
        self.unsubscribed_instruments.append(str(instrument_id))

    def request_order_book_snapshot(
        self,
        instrument_id: object,
        *,
        limit: int = 0,
        client_id: object | None = None,
        params: Mapping[str, object] | None = None,
    ) -> object:
        del limit, client_id
        self.snapshot_requests.append(str(instrument_id))
        self.snapshot_request_params.append(params)
        return object()


def _stalled_state(
    strategy: _ResubscribeStrategy,
    condition_id: str,
    *,
    started_at: datetime,
) -> None:
    state = strategy._subscription_state
    state.condition_phases[condition_id] = ConditionSubscriptionPhase.AWAITING_FIRST_BOOK
    state.awaiting_book_sides_by_condition[condition_id] = {Side.UP, Side.DOWN}
    state.book_generation_started_at_by_condition[condition_id] = started_at
    state.book_stalled_started_at_by_condition[condition_id] = started_at


def test_stalled_condition_force_resubscribes_instruments_and_refreshes_state() -> None:
    registry = _registry()
    strategy = _ResubscribeStrategy(registry)
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    _stalled_state(
        strategy,
        "btc-5m",
        started_at=now - timedelta(seconds=_BOOK_GENERATION_STALL_SEC + 10),
    )

    triggered = force_resubscribe_if_book_stalled(
        strategy,
        "btc-5m",
        now=now,
    )

    assert triggered is True
    # Each of the two instruments is unsubscribed (quotes+trades+book_deltas) and
    # re-subscribed on the healthy connection.
    assert sorted(set(strategy.unsubscribed_instruments)) == [
        "btc-5m-down.POLYMARKET",
        "btc-5m-up.POLYMARKET",
    ]
    assert sorted(set(strategy.subscribed_instruments)) == [
        "btc-5m-down.POLYMARKET",
        "btc-5m-up.POLYMARKET",
    ]
    assert len(strategy.unsubscribed_instruments) == 6  # 2 instruments × 3 feeds
    assert len(strategy.subscribed_instruments) == 6
    # Book generation clock restarted so the next heartbeat does not re-fire.
    state = strategy._subscription_state
    assert state.book_generation_started_at_by_condition["btc-5m"] == now
    assert state.awaiting_book_sides_by_condition["btc-5m"] == {Side.UP, Side.DOWN}


def test_stalled_condition_resubscription_requests_snapshot_backstop() -> None:
    """Resubscription also issues a one-time snapshot request per instrument so a
    first book arrives even when the feed treats the book_delta subscribe as
    already-active and does not re-send its initial snapshot."""
    registry = _registry()
    strategy = _ResubscribeStrategy(registry)
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    _stalled_state(
        strategy,
        "btc-5m",
        started_at=now - timedelta(seconds=_BOOK_GENERATION_STALL_SEC + 10),
    )

    triggered = force_resubscribe_if_book_stalled(
        strategy,
        "btc-5m",
        now=now,
    )

    assert triggered is True
    assert sorted(strategy.snapshot_requests) == [
        "btc-5m-down.POLYMARKET",
        "btc-5m-up.POLYMARKET",
    ]
    assert strategy.snapshot_request_params == [
        {"resync_live_book": True},
        {"resync_live_book": True},
    ]


def test_real_strategy_resubscription_does_not_raise_attribute_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: PR #52's resubscribe path calls request_order_book_snapshot
    on the real strategy. The pyo3 Strategy base exposes request_book_snapshot
    but not request_order_book_snapshot, so before the fix this raised
    AttributeError and crashed the heartbeat timer callback (spamming errors
    and readiness misses). The method must exist on PolySignalNativeStrategy
    and be safe to call during resubscription."""
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    from polysignal_lab.alpha.types import AlphaDecision

    class _FakeAssembler:
        def build(self, condition_id: str, *, created_at=None):  # noqa: ANN001
            del condition_id, created_at
            return None

        def with_custom_data(self, custom_data: object) -> "_FakeAssembler":
            del custom_data
            return self

    class _FakeCore:
        def evaluate(self, view: object) -> list[AlphaDecision]:
            del view
            return []

    class _SubscribedStrategy(PolySignalNativeStrategy):
        """Real strategy with wire calls stubbed; snapshot method inherited."""

        def subscribe_quotes(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            del args, kwargs
            self.subscribed_instruments.append(str(instrument_id))

        def subscribe_trades(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            del args, kwargs
            self.subscribed_instruments.append(str(instrument_id))

        def subscribe_book_deltas(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            del args, kwargs
            self.subscribed_instruments.append(str(instrument_id))

        def unsubscribe_quotes(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            del args, kwargs
            self.unsubscribed_instruments.append(str(instrument_id))

        def unsubscribe_trades(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            del args, kwargs
            self.unsubscribed_instruments.append(str(instrument_id))

        def unsubscribe_book_deltas(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            del args, kwargs
            self.unsubscribed_instruments.append(str(instrument_id))

    monkeypatch.setattr(
        Strategy,
        "request_book_snapshot",
        lambda self, instrument_id, depth=None, client_id=None, params=None: None,
    )

    registry = _registry()
    strategy = _SubscribedStrategy(
        core=_FakeCore(),  # type: ignore[arg-type]
        assembler=_FakeAssembler(),  # type: ignore[arg-type]
        condition_ids=("btc-5m",),
        strategy_name="ptb_diff",
        registry=registry,
    )
    strategy._cache_override = SimpleNamespace(instrument=lambda _iid: object())
    strategy.subscribed_instruments = []
    strategy.unsubscribed_instruments = []
    strategy._active_condition_ids = {"btc-5m"}
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    _stalled_state(
        strategy,
        "btc-5m",
        started_at=now - timedelta(seconds=_BOOK_GENERATION_STALL_SEC + 10),
    )

    # Must not raise AttributeError (the regression).
    triggered = force_resubscribe_if_book_stalled(
        strategy,
        "btc-5m",
        now=now,
    )

    assert triggered is True
    assert sorted(set(strategy.unsubscribed_instruments)) == [
        "btc-5m-down.POLYMARKET",
        "btc-5m-up.POLYMARKET",
    ]
    assert sorted(set(strategy.subscribed_instruments)) == [
        "btc-5m-down.POLYMARKET",
        "btc-5m-up.POLYMARKET",
    ]


def test_real_strategy_snapshot_wrapper_delegates_native_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    calls: list[tuple[object, object, object, object]] = []
    response = object()

    def request_book_snapshot(
        self: object,
        instrument_id: object,
        depth: object = None,
        client_id: object = None,
        params: object = None,
    ) -> object:
        del self
        calls.append((instrument_id, depth, client_id, params))
        return response

    monkeypatch.setattr(Strategy, "request_book_snapshot", request_book_snapshot)
    strategy = Strategy.__new__(PolySignalNativeStrategy)
    strategy.strategy_name = "snapshot-probe"

    result = strategy.request_order_book_snapshot(
        "btc-up.POLYMARKET",
        limit=10,
        client_id="POLYMARKET-5M",
        params={"probe": "tc-d13"},
    )

    assert result is response
    assert calls == [
        (
            "btc-up.POLYMARKET",
            10,
            "POLYMARKET-5M",
            {"probe": "tc-d13"},
        )
    ]


def test_on_book_records_pending_historical_without_evaluation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polysignal_lab.nautilus_runtime import native_strategy
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy
    from polysignal_lab.nautilus_runtime.strategy import snapshot_backstop

    strategy = Strategy.__new__(PolySignalNativeStrategy)
    strategy.strategy_name = "snapshot-probe"
    request = snapshot_backstop.SnapshotBackstopRequest(
        strategy="snapshot-probe",
        condition="btc-5m",
        instrument_id="btc-up.POLYMARKET",
        token="up-token",
        request_id="request-1",
        started_at=10.0,
    )
    strategy._pending_snapshot_backstops = {"btc-up.POLYMARKET": request}
    evaluated: list[object] = []
    monkeypatch.setattr(
        native_strategy.mde,
        "evaluate_order_book_event",
        lambda _strategy, event: evaluated.append(event),
    )
    historical = SimpleNamespace(
        instrument_id="btc-up.POLYMARKET",
        ts_last=100,
        ts_init=110,
    )

    strategy.on_book(historical)

    assert request.historical_ts_event == 100
    assert evaluated == []


def test_unmatched_live_snapshot_keeps_pending_backstop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polysignal_lab.nautilus_runtime import native_strategy
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy
    from polysignal_lab.nautilus_runtime.strategy import snapshot_backstop

    strategy = Strategy.__new__(PolySignalNativeStrategy)
    strategy._pending_snapshot_backstops = {
        "btc-up.POLYMARKET": snapshot_backstop.SnapshotBackstopRequest(
            strategy="snapshot-probe",
            condition="btc-5m",
            instrument_id="btc-up.POLYMARKET",
            token="up-token",
            request_id="request-1",
            started_at=10.0,
            historical_ts_event=100,
        )
    }
    evaluated: list[object] = []
    monkeypatch.setattr(
        native_strategy.mde,
        "evaluate_order_book_event",
        lambda _strategy, event: evaluated.append(event),
    )
    live_snapshot = SimpleNamespace(
        instrument_id="btc-up.POLYMARKET",
        flags=32,
        ts_event=99,
        ts_init=105,
    )

    strategy.on_book_deltas(live_snapshot)

    assert "btc-up.POLYMARKET" in strategy._pending_snapshot_backstops
    assert evaluated == [live_snapshot]


def test_matching_live_snapshot_completes_pending_backstop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polysignal_lab.nautilus_runtime import native_strategy
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy
    from polysignal_lab.nautilus_runtime.strategy import snapshot_backstop

    strategy = Strategy.__new__(PolySignalNativeStrategy)
    strategy._pending_snapshot_backstops = {
        "btc-up.POLYMARKET": snapshot_backstop.SnapshotBackstopRequest(
            strategy="snapshot-probe",
            condition="btc-5m",
            instrument_id="btc-up.POLYMARKET",
            token="up-token",
            request_id="request-1",
            started_at=10.0,
            historical_ts_event=100,
        )
    }
    monkeypatch.setattr(
        native_strategy.mde,
        "evaluate_order_book_event",
        lambda _strategy, _event: None,
    )

    strategy.on_book_deltas(
        SimpleNamespace(
            instrument_id="btc-up.POLYMARKET",
            flags=32,
            ts_event=100,
            ts_init=120,
        )
    )

    assert strategy._pending_snapshot_backstops == {}


def test_snapshot_backstop_timeout_removes_pending_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy
    from polysignal_lab.nautilus_runtime.strategy import snapshot_backstop

    strategy = Strategy.__new__(PolySignalNativeStrategy)
    strategy._cache_override = SimpleNamespace(order_book=lambda _instrument_id: None)
    strategy._pending_snapshot_backstops = {
        "btc-up.POLYMARKET": snapshot_backstop.SnapshotBackstopRequest(
            strategy="snapshot-probe",
            condition="btc-5m",
            instrument_id="btc-up.POLYMARKET",
            token="up-token",
            request_id="request-1",
            started_at=10.0,
        )
    }
    monkeypatch.setattr(snapshot_backstop.time, "monotonic", lambda: 40.0)

    snapshot_backstop.expire(strategy)

    assert strategy._pending_snapshot_backstops == {}


def test_snapshot_backstop_event_fields_include_book_and_source_timestamps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy
    from polysignal_lab.nautilus_runtime.strategy import snapshot_backstop

    strategy = Strategy.__new__(PolySignalNativeStrategy)
    strategy._cache_override = SimpleNamespace(
        order_book=lambda _instrument_id: SimpleNamespace(
            bids=(1, 2),
            asks=(3,),
            ts_event=90,
            ts_init=95,
        )
    )
    request = snapshot_backstop.SnapshotBackstopRequest(
        strategy="snapshot-probe",
        condition="btc-5m",
        instrument_id="btc-up.POLYMARKET",
        token="up-token",
        request_id="request-1",
        started_at=10.0,
    )
    monkeypatch.setattr(snapshot_backstop.time, "monotonic", lambda: 10.25)

    fields = snapshot_backstop._event_fields(  # pyright: ignore[reportPrivateUsage]
        strategy,
        request,
        data=SimpleNamespace(ts_event=100, ts_init=105),
    )

    assert fields == {
        "strategy": "snapshot-probe",
        "condition": "btc-5m",
        "instrument_id": "btc-up.POLYMARKET",
        "token": "up-token",
        "request_id": "request-1",
        "latency_ms": 250.0,
        "bid_levels": 2,
        "ask_levels": 1,
        "ts_event": 100,
        "ts_init": 105,
    }


def test_stale_recovery_begins_generation_before_wire_requests() -> None:
    registry = _registry()
    strategy = _ResubscribeStrategy(registry)
    strategy._active_condition_ids = {"btc-5m"}
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    _stale_ready_state(
        strategy,
        "btc-5m",
        now=now,
        stalled_sec=_BOOK_GENERATION_STALL_SEC + 10,
    )

    def assert_generation_started(
        instrument_id: object,
        *,
        limit: int = 0,
        client_id: object | None = None,
        params: Mapping[str, object] | None = None,
    ) -> object:
        del instrument_id, limit, client_id, params
        state = strategy._subscription_state
        assert (
            state.condition_phases["btc-5m"]
            is ConditionSubscriptionPhase.AWAITING_FIRST_BOOK
        )
        assert state.book_generation_started_at_by_condition["btc-5m"] == now
        return object()

    strategy.request_order_book_snapshot = assert_generation_started  # type: ignore[method-assign]

    assert force_resubscribe_if_stale_orderbook(strategy, "btc-5m", now=now) is True


def test_snapshot_request_failure_does_not_escape_recovery_heartbeat() -> None:
    registry = _registry()
    now = datetime(2026, 8, 1, 12, tzinfo=UTC)
    strategy = _HeartbeatStrategy(registry, now=now)
    strategy._active_condition_ids = {"btc-5m"}
    _stalled_state(
        strategy,
        "btc-5m",
        started_at=now - timedelta(seconds=_BOOK_GENERATION_STALL_SEC + 10),
    )

    def fail_snapshot_request(
        instrument_id: object,
        *,
        limit: int = 0,
        client_id: object | None = None,
        params: Mapping[str, object] | None = None,
    ) -> object:
        del instrument_id, limit, client_id, params
        raise RuntimeError("snapshot unavailable")

    strategy.request_order_book_snapshot = fail_snapshot_request  # type: ignore[method-assign]

    on_evaluation_heartbeat(strategy, object())  # pyright: ignore[reportArgumentType]

    assert sorted(set(strategy.subscribed_instruments)) == [
        "btc-5m-down.POLYMARKET",
        "btc-5m-up.POLYMARKET",
    ]
    assert strategy.evaluated == ["btc-5m"]


def test_fresh_generation_does_not_resubscribe() -> None:
    registry = _registry()
    strategy = _ResubscribeStrategy(registry)
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    started_at = now - timedelta(seconds=_BOOK_GENERATION_STALL_SEC - 10)
    _stalled_state(strategy, "btc-5m", started_at=started_at)

    triggered = force_resubscribe_if_book_stalled(
        strategy,
        "btc-5m",
        now=now,
    )

    assert triggered is False
    assert strategy.unsubscribed_instruments == []
    assert strategy.subscribed_instruments == []
    assert strategy._subscription_state.book_generation_started_at_by_condition[
        "btc-5m"
    ] == started_at


def test_condition_without_awaiting_book_does_not_resubscribe() -> None:
    registry = _registry()
    strategy = _ResubscribeStrategy(registry)
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    strategy._subscription_state.condition_phases[
        "btc-5m"
    ] = ConditionSubscriptionPhase.READY

    triggered = force_resubscribe_if_book_stalled(
        strategy,
        "btc-5m",
        now=now,
    )

    assert triggered is False
    assert strategy.unsubscribed_instruments == []
    assert strategy.subscribed_instruments == []


def test_pending_instrument_does_not_resubscribe() -> None:
    """Still waiting on instrument metadata is not a book stall."""
    registry = _registry()
    strategy = _ResubscribeStrategy(registry)
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    _stalled_state(
        strategy,
        "btc-5m",
        started_at=now - timedelta(seconds=_BOOK_GENERATION_STALL_SEC + 10),
    )
    strategy._subscription_state.pending_instrument_ids.add("btc-5m-up.POLYMARKET")

    triggered = force_resubscribe_if_book_stalled(
        strategy,
        "btc-5m",
        now=now,
    )

    assert triggered is False
    assert strategy.unsubscribed_instruments == []
    assert strategy.subscribed_instruments == []


def test_resubscription_is_idempotent_within_stall_window() -> None:
    """A second heartbeat immediately after resubscribing must not re-fire."""
    registry = _registry()
    strategy = _ResubscribeStrategy(registry)
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    _stalled_state(
        strategy,
        "btc-5m",
        started_at=now - timedelta(seconds=_BOOK_GENERATION_STALL_SEC + 10),
    )

    first = force_resubscribe_if_book_stalled(
        strategy,
        "btc-5m",
        now=now,
    )
    second = force_resubscribe_if_book_stalled(
        strategy,
        "btc-5m",
        now=now + timedelta(seconds=5),
    )

    assert first is True
    assert second is False
    assert len(strategy.unsubscribed_instruments) == 6
    assert len(strategy.subscribed_instruments) == 6


def test_force_resubscribe_abandons_condition_past_abandon_threshold() -> None:
    """A condition still stalled at the abandon threshold is dropped, not
    resubscribed: the feed never sends a snapshot for a no-book market."""
    registry = _registry()
    strategy = _ResubscribeStrategy(registry)
    strategy._active_condition_ids = {"btc-5m"}
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    _stalled_state(
        strategy,
        "btc-5m",
        started_at=now - timedelta(seconds=_BOOK_GENERATION_ABANDON_SEC),
    )

    triggered = force_resubscribe_if_book_stalled(
        strategy,
        "btc-5m",
        now=now,
    )

    assert triggered is False
    # Abandoned: removed from the active set, no re-subscription issued.
    assert "btc-5m" not in strategy._active_condition_ids
    assert strategy.subscribed_instruments == []
    # Instruments were unsubscribed (2 instruments × quotes+trades+book_deltas).
    assert len(strategy.unsubscribed_instruments) == 6
    # Book-generation bookkeeping cleared.
    state = strategy._subscription_state
    assert "btc-5m" not in state.awaiting_book_sides_by_condition
    assert "btc-5m" not in state.book_generation_started_at_by_condition
    assert "btc-5m" not in state.condition_phases


def test_force_resubscribe_still_resubscribes_below_abandon_threshold() -> None:
    """Between the stall window and the abandon threshold, resubscription
    (repair A) still applies and keeps the condition active."""
    registry = _registry()
    strategy = _ResubscribeStrategy(registry)
    strategy._active_condition_ids = {"btc-5m"}
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    _stalled_state(
        strategy,
        "btc-5m",
        started_at=now - timedelta(seconds=_BOOK_GENERATION_ABANDON_SEC - 10),
    )

    triggered = force_resubscribe_if_book_stalled(
        strategy,
        "btc-5m",
        now=now,
    )

    assert triggered is True
    assert "btc-5m" in strategy._active_condition_ids
    assert len(strategy.unsubscribed_instruments) == 6
    assert len(strategy.subscribed_instruments) == 6


def test_abandon_threshold_precedes_liveness_readiness_miss_threshold() -> None:
    """Abandon must fire before the liveness readiness-miss window (300s) so a
    no-book condition stops generating readiness misses before the node is ever
    judged unhealthy. The abandon check only runs on the 10s evaluation
    heartbeat, so the margin has to exceed the heartbeat interval."""
    heartbeat_sec = EVALUATION_HEARTBEAT_INTERVAL.total_seconds()
    assert _BOOK_GENERATION_ABANDON_SEC + heartbeat_sec < 300


def test_abandon_condition_clears_lifecycle_state_and_readiness_miss() -> None:
    registry = _registry()
    strategy = _ResubscribeStrategy(registry)
    strategy._active_condition_ids = {"btc-5m"}
    strategy._runtime_readiness_miss_condition_ids = {"btc-5m"}
    strategy._runtime_readiness_reason_by_condition["btc-5m"] = "awaiting_first_book"
    strategy._subscription_state.last_book_at_by_condition["btc-5m"] = {}

    abandoned = abandon_book_stalled_condition(
        strategy,
        "btc-5m",
        stall_sec=_BOOK_GENERATION_ABANDON_SEC,
    )

    assert abandoned is True
    assert "btc-5m" not in strategy._active_condition_ids
    assert "btc-5m" not in strategy._runtime_readiness_miss_condition_ids
    assert "btc-5m" not in strategy._runtime_readiness_reason_by_condition
    # Readiness cleared (ready=True) so the persisted miss key is dropped.
    assert strategy.readiness == [("btc-5m", True)]
    # Lifecycle + subscription history cleared.
    assert "btc-5m" not in strategy._subscription_state.condition_phases
    assert "btc-5m" not in strategy._subscription_state.last_book_at_by_condition


def test_abandon_is_idempotent() -> None:
    registry = _registry()
    strategy = _ResubscribeStrategy(registry)
    strategy._active_condition_ids = {"btc-5m"}

    first = abandon_book_stalled_condition(
        strategy,
        "btc-5m",
        stall_sec=_BOOK_GENERATION_ABANDON_SEC,
    )
    second = abandon_book_stalled_condition(
        strategy,
        "btc-5m",
        stall_sec=_BOOK_GENERATION_ABANDON_SEC + 10,
    )

    assert first is True
    assert second is False
    assert len(strategy.unsubscribed_instruments) == 6
    assert strategy.readiness == [("btc-5m", True)]


def test_abandon_is_noop_for_condition_not_in_active_set() -> None:
    registry = _registry()
    strategy = _ResubscribeStrategy(registry)

    abandoned = abandon_book_stalled_condition(
        strategy,
        "btc-5m",
        stall_sec=_BOOK_GENERATION_ABANDON_SEC,
    )

    assert abandoned is False
    assert strategy.unsubscribed_instruments == []
    assert strategy.readiness == []


class _Clock:
    def __init__(self, now_ns: int) -> None:
        self.now_ns = now_ns

    def timestamp_ns(self) -> int:
        return self.now_ns

    def set_timer(self, name: object, interval: object, *, callback: object) -> None:
        del name, interval, callback

    def cancel_timer(self, name: object) -> None:
        del name


class _HeartbeatStrategy(_ResubscribeStrategy):
    def __init__(self, registry: MarketCatalog, *, now: datetime) -> None:
        super().__init__(registry)
        self.clock = _Clock(int(now.timestamp() * 1_000_000_000))
        self.trader_id = object()
        self.strategy_name = "ptb_diff"
        self._execution_mode = "live"
        self._evaluation_heartbeat_started = True
        self._subscriptions_started = True
        self._last_market_data_evaluation_at: dict[str, datetime] = {}
        self._market_config: object = SimpleNamespace(timeframes=("5m",))
        self._spot_data_source: str = "none"
        self.assembler = object()
        self.evaluated: list[str] = []

    def _note_runtime_progress(self, phase: str) -> None:
        del phase

    def _require_registry(self) -> MarketCatalog:
        if self.registry is None:
            raise RuntimeError("registry unavailable")
        return self.registry

    def _require_assembler(self) -> object:
        return self.assembler

    def _subscribe_market_conditions(self, condition_ids: Sequence[str]) -> None:
        del condition_ids

    def _unsubscribe_market_conditions(self, condition_ids: Sequence[str]) -> None:
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

    def _refresh_asset_conditions(self) -> None:
        return None

    def evaluate_condition(
        self,
        condition_id: str,
        *,
        trading_state: object | None = None,
    ) -> None:
        del trading_state
        # Mirror cond.evaluate_condition: a condition abandoned off the active
        # set during the heartbeat is not evaluated.
        if condition_id in self._active_condition_ids:
            self.evaluated.append(condition_id)


def test_evaluation_heartbeat_resubscribes_stalled_condition() -> None:
    registry = _registry()
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    strategy = _HeartbeatStrategy(registry, now=now)
    strategy._active_condition_ids = {"btc-5m"}
    _stalled_state(
        strategy,
        "btc-5m",
        started_at=now - timedelta(seconds=_BOOK_GENERATION_STALL_SEC + 10),
    )

    on_evaluation_heartbeat(strategy, object())  # pyright: ignore[reportArgumentType]

    assert sorted(set(strategy.unsubscribed_instruments)) == [
        "btc-5m-down.POLYMARKET",
        "btc-5m-up.POLYMARKET",
    ]
    assert sorted(set(strategy.subscribed_instruments)) == [
        "btc-5m-down.POLYMARKET",
        "btc-5m-up.POLYMARKET",
    ]
    assert strategy._subscription_state.book_generation_started_at_by_condition[
        "btc-5m"
    ] == now
    # Evaluation still proceeds for the active condition after resubscription.
    assert strategy.evaluated == ["btc-5m"]


def test_evaluation_heartbeat_does_not_resubscribe_fresh_generation() -> None:
    registry = _registry()
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    strategy = _HeartbeatStrategy(registry, now=now)
    strategy._active_condition_ids = {"btc-5m"}
    _stalled_state(
        strategy,
        "btc-5m",
        started_at=now - timedelta(seconds=_BOOK_GENERATION_STALL_SEC - 10),
    )

    on_evaluation_heartbeat(strategy, object())  # pyright: ignore[reportArgumentType]

    assert strategy.unsubscribed_instruments == []
    assert strategy.subscribed_instruments == []
    assert strategy.evaluated == ["btc-5m"]


def test_evaluation_heartbeat_abandons_no_book_condition() -> None:
    """A condition stalled past the abandon threshold is dropped from the active
    set during the heartbeat, unsubscribed, and not evaluated."""
    registry = _registry()
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    strategy = _HeartbeatStrategy(registry, now=now)
    strategy._active_condition_ids = {"btc-5m"}
    _stalled_state(
        strategy,
        "btc-5m",
        started_at=now - timedelta(seconds=_BOOK_GENERATION_ABANDON_SEC + 1),
    )

    on_evaluation_heartbeat(strategy, object())  # pyright: ignore[reportArgumentType]

    assert "btc-5m" not in strategy._active_condition_ids
    # Abandoned: unsubscribed but never re-subscribed.
    assert strategy.subscribed_instruments == []
    assert len(strategy.unsubscribed_instruments) == 6
    # Dropped before evaluation.
    assert strategy.evaluated == []
    # Readiness cleared so the persisted miss key is dropped.
    assert strategy.readiness == [("btc-5m", True)]


def test_evaluation_heartbeat_does_not_revisit_abandoned_condition() -> None:
    """After abandonment, a later heartbeat no longer tracks the condition."""
    registry = _registry()
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    strategy = _HeartbeatStrategy(registry, now=now)
    strategy._active_condition_ids = {"btc-5m"}
    _stalled_state(
        strategy,
        "btc-5m",
        started_at=now - timedelta(seconds=_BOOK_GENERATION_ABANDON_SEC + 1),
    )

    on_evaluation_heartbeat(strategy, object())  # pyright: ignore[reportArgumentType]
    unsubscribed_after_first = len(strategy.unsubscribed_instruments)
    on_evaluation_heartbeat(strategy, object())  # pyright: ignore[reportArgumentType]

    assert "btc-5m" not in strategy._active_condition_ids
    # Second heartbeat performs no further unsubscribe/resubscribe work.
    assert len(strategy.unsubscribed_instruments) == unsubscribed_after_first
    assert strategy.subscribed_instruments == []
    assert strategy.evaluated == []


def test_total_stall_clock_survives_repeated_resubscription_and_abandons() -> None:
    """Gap A: each 60s retry re-arms the retry cadence clock but must NOT reset
    the total-stall (first-wait) clock. At 240s total stall the condition is
    abandoned (active + readiness state cleaned) instead of resubscribed."""
    registry = _registry()
    strategy = _ResubscribeStrategy(registry)
    strategy._active_condition_ids = {"btc-5m"}
    t0 = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    _stalled_state(strategy, "btc-5m", started_at=t0)

    retried_at: dict[int, bool] = {}
    for i in range(1, 5):  # t0+61, t0+122, t0+183, t0+244
        retried_at[i] = force_resubscribe_if_book_stalled(
            strategy,
            "btc-5m",
            now=t0 + timedelta(seconds=61 * i),
        )
        if i < 4:
            # The total-stall clock is never reset by the 60s retries.
            assert (
                strategy._subscription_state.book_stalled_started_at_by_condition[
                    "btc-5m"
                ]
                == t0
            )
        else:
            # Abandon clears the total-stall clock (no leftover timestamp).
            assert (
                "btc-5m"
                not in strategy._subscription_state.book_stalled_started_at_by_condition
            )

    # Below the 240s abandon threshold each retry keeps the condition active; at
    # 244s (> 240) it is abandoned instead of resubscribed.
    assert retried_at[1] is True
    assert retried_at[2] is True
    assert retried_at[3] is True
    assert retried_at[4] is False
    assert "btc-5m" not in strategy._active_condition_ids
    # Abandon clears the total-stall clock too (no leftover timestamp/state).
    assert (
        "btc-5m"
        not in strategy._subscription_state.book_stalled_started_at_by_condition
    )
    assert "btc-5m" not in strategy._subscription_state.awaiting_book_sides_by_condition
    assert "btc-5m" not in strategy._subscription_state.condition_phases
    assert strategy.readiness == [("btc-5m", True)]


def _stale_ready_state(
    strategy: _ResubscribeStrategy,
    condition_id: str,
    *,
    now: datetime,
    stalled_sec: float,
) -> None:
    """Set a once-READY condition that went stale (awaiting empty), with both
    the total-stall clock and the retry cadence clock started `stalled_sec` ago.
    """
    state = strategy._subscription_state
    state.condition_phases[condition_id] = ConditionSubscriptionPhase.READY
    state.first_bilateral_book_at_by_condition[condition_id] = now - timedelta(
        minutes=10
    )
    state.first_bilateral_book_ever_at_by_condition[condition_id] = now - timedelta(
        minutes=10
    )
    strategy._stale_orderbook_recovery_by_condition[condition_id] = {
        Side.UP: 60_000.0,
        Side.DOWN: 60_000.0,
    }
    started_at = now - timedelta(seconds=stalled_sec)
    state.book_stalled_started_at_by_condition[condition_id] = started_at
    state.book_generation_started_at_by_condition[condition_id] = started_at


def test_stale_orderbook_condition_rebuilds_book_subscription() -> None:
    """Gap B: a once-READY condition whose book went stale (awaiting empty, so
    force_resubscribe_if_book_stalled never fired) rebuilds its book
    subscription after the retry window, forcing a fresh snapshot."""
    registry = _registry()
    strategy = _ResubscribeStrategy(registry)
    strategy._active_condition_ids = {"btc-5m"}
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    _stale_ready_state(
        strategy,
        "btc-5m",
        now=now,
        stalled_sec=_BOOK_GENERATION_STALL_SEC + 10,
    )
    state = strategy._subscription_state
    started_at = state.book_stalled_started_at_by_condition["btc-5m"]

    triggered = force_resubscribe_if_stale_orderbook(strategy, "btc-5m", now=now)

    assert triggered is True
    assert sorted(set(strategy.unsubscribed_instruments)) == [
        "btc-5m-down.POLYMARKET",
        "btc-5m-up.POLYMARKET",
    ]
    assert sorted(set(strategy.subscribed_instruments)) == [
        "btc-5m-down.POLYMARKET",
        "btc-5m-up.POLYMARKET",
    ]
    assert sorted(strategy.snapshot_requests) == [
        "btc-5m-down.POLYMARKET",
        "btc-5m-up.POLYMARKET",
    ]
    # Repair re-begins generation: both sides awaited again.
    assert state.awaiting_book_sides_by_condition["btc-5m"] == {Side.UP, Side.DOWN}
    assert state.book_generation_started_at_by_condition["btc-5m"] == now
    # Stale marker cleared; total-stall clock preserved across the rebuild.
    assert "btc-5m" not in strategy._stale_orderbook_recovery_by_condition
    assert state.book_stalled_started_at_by_condition["btc-5m"] == started_at
    # The condition never leaves the active set (W2).
    assert "btc-5m" in strategy._active_condition_ids
    assert strategy.readiness == []


def test_stale_orderbook_condition_not_rebuilt_within_retry_window() -> None:
    """A stale-orderbook condition is not rebuilt more often than the retry
    cadence — normal staleness below the window is left alone."""
    registry = _registry()
    strategy = _ResubscribeStrategy(registry)
    strategy._active_condition_ids = {"btc-5m"}
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    _stale_ready_state(
        strategy,
        "btc-5m",
        now=now,
        stalled_sec=_BOOK_GENERATION_STALL_SEC - 10,
    )

    triggered = force_resubscribe_if_stale_orderbook(strategy, "btc-5m", now=now)

    assert triggered is False
    assert strategy.unsubscribed_instruments == []
    assert strategy.subscribed_instruments == []
    assert "btc-5m" in strategy._active_condition_ids


def test_stale_orderbook_condition_never_abandoned_past_total_stall() -> None:
    """W2: a stale-orderbook (once-READY) condition is never abandoned via the
    book-stall clock even past the 240s total-stall threshold — it keeps
    resubscribing and the active set is preserved (liveness/data-starvation is
    the backstop for a genuinely dead feed)."""
    registry = _registry()
    strategy = _ResubscribeStrategy(registry)
    strategy._active_condition_ids = {"btc-5m"}
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    _stale_ready_state(
        strategy,
        "btc-5m",
        now=now,
        stalled_sec=_BOOK_GENERATION_ABANDON_SEC + 1,
    )

    triggered = force_resubscribe_if_stale_orderbook(strategy, "btc-5m", now=now)

    assert triggered is True  # repair, not abandon
    assert "btc-5m" in strategy._active_condition_ids
    assert strategy.readiness == []  # no abandon ready=True
    assert len(strategy.unsubscribed_instruments) == 6
    assert len(strategy.subscribed_instruments) == 6
    # Still on the recovery path (both sides awaited again).
    assert strategy._subscription_state.awaiting_book_sides_by_condition[
        "btc-5m"
    ] == {Side.UP, Side.DOWN}


def test_previously_ready_condition_not_abandoned_via_book_stall_path() -> None:
    """W2: after a stale repair re-begins generation (awaiting both sides), the
    first-book path must not abandon the once-READY condition even when its
    total stall exceeds the 240s threshold — it is retried at the cadence."""
    registry = _registry()
    strategy = _ResubscribeStrategy(registry)
    strategy._active_condition_ids = {"btc-5m"}
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    state = strategy._subscription_state
    state.condition_phases["btc-5m"] = ConditionSubscriptionPhase.AWAITING_FIRST_BOOK
    state.awaiting_book_sides_by_condition["btc-5m"] = {Side.UP, Side.DOWN}
    state.first_bilateral_book_ever_at_by_condition["btc-5m"] = now - timedelta(
        minutes=10
    )
    state.book_stalled_started_at_by_condition["btc-5m"] = now - timedelta(
        seconds=_BOOK_GENERATION_ABANDON_SEC + 1
    )
    state.book_generation_started_at_by_condition["btc-5m"] = now - timedelta(
        seconds=_BOOK_GENERATION_STALL_SEC + 10
    )

    triggered = force_resubscribe_if_book_stalled(strategy, "btc-5m", now=now)

    assert triggered is True  # retried, not abandoned
    assert "btc-5m" in strategy._active_condition_ids
    assert strategy.readiness == []
    assert len(strategy.unsubscribed_instruments) == 6
    assert len(strategy.subscribed_instruments) == 6


def test_pending_instrument_prevents_book_stall_abandon() -> None:
    """W1: a condition whose instrument metadata is still pending is never
    abandoned by the book-stall path, even past the total-stall threshold —
    book-specific mechanics must not change metadata semantics."""
    registry = _registry()
    strategy = _ResubscribeStrategy(registry)
    strategy._active_condition_ids = {"btc-5m"}
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    _stalled_state(
        strategy,
        "btc-5m",
        started_at=now - timedelta(seconds=_BOOK_GENERATION_ABANDON_SEC + 1),
    )
    strategy._subscription_state.pending_instrument_ids.add("btc-5m-up.POLYMARKET")

    triggered = force_resubscribe_if_book_stalled(strategy, "btc-5m", now=now)

    assert triggered is False
    assert "btc-5m" in strategy._active_condition_ids
    assert strategy.unsubscribed_instruments == []
    assert strategy.subscribed_instruments == []
    assert strategy.readiness == []
    # Still awaiting with both clocks intact (nothing was abandoned/cleared).
    assert strategy._subscription_state.awaiting_book_sides_by_condition[
        "btc-5m"
    ] == {Side.UP, Side.DOWN}
    assert (
        "btc-5m"
        in strategy._subscription_state.book_stalled_started_at_by_condition
    )


def test_healthy_ready_condition_does_not_rebuild_or_abandon() -> None:
    """Normal book updates on a READY condition cause no resubscribe and no
    abandon (no false positive self-heal)."""
    registry = _registry()
    strategy = _ResubscribeStrategy(registry)
    strategy._active_condition_ids = {"btc-5m"}
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    state = strategy._subscription_state
    state.condition_phases["btc-5m"] = ConditionSubscriptionPhase.READY
    state.first_bilateral_book_at_by_condition["btc-5m"] = now - timedelta(minutes=10)
    state.first_bilateral_book_ever_at_by_condition["btc-5m"] = now - timedelta(
        minutes=10
    )
    state.last_book_received_at_by_condition["btc-5m"] = {Side.UP: now, Side.DOWN: now}

    resub = force_resubscribe_if_book_stalled(strategy, "btc-5m", now=now)
    stale = force_resubscribe_if_stale_orderbook(strategy, "btc-5m", now=now)

    assert resub is False
    assert stale is False
    assert strategy.unsubscribed_instruments == []
    assert strategy.subscribed_instruments == []
    assert "btc-5m" in strategy._active_condition_ids
    assert "btc-5m" not in state.book_stalled_started_at_by_condition


def test_evaluation_heartbeat_rebuilds_stale_orderbook_condition() -> None:
    """A once-READY condition that went stale is rebuilt by the heartbeat —
    it does not stay a permanent readiness miss (Gap B)."""
    registry = _registry()
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    strategy = _HeartbeatStrategy(registry, now=now)
    strategy._active_condition_ids = {"btc-5m"}
    _stale_ready_state(
        strategy,
        "btc-5m",
        now=now,
        stalled_sec=_BOOK_GENERATION_STALL_SEC + 10,
    )
    state = strategy._subscription_state

    on_evaluation_heartbeat(strategy, object())  # pyright: ignore[reportArgumentType]

    assert sorted(set(strategy.unsubscribed_instruments)) == [
        "btc-5m-down.POLYMARKET",
        "btc-5m-up.POLYMARKET",
    ]
    assert sorted(set(strategy.subscribed_instruments)) == [
        "btc-5m-down.POLYMARKET",
        "btc-5m-up.POLYMARKET",
    ]
    # Back onto the awaiting-first-book recovery path, not a permanent miss.
    assert state.awaiting_book_sides_by_condition["btc-5m"] == {Side.UP, Side.DOWN}
    assert "btc-5m" in strategy._active_condition_ids


def test_global_starvation_repairs_once_without_resubscription_storm() -> None:
    """W2: when every active condition is stale (global feed outage), the
    heartbeat repairs them all once but does not repeat the destructive reset
    while all remain stalled. Liveness/data-starvation stays the backstop."""
    registry = MarketCatalog(
        instrument_id_resolver=lambda _condition, token: f"{token}.POLYMARKET"
    )
    for condition_id in ("btc-5m", "eth-5m", "sol-5m"):
        registry.register(_pair(condition_id, "BTC", "5m"))
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    strategy = _HeartbeatStrategy(registry, now=now)
    strategy._active_condition_ids = {"btc-5m", "eth-5m", "sol-5m"}
    for condition_id in ("btc-5m", "eth-5m", "sol-5m"):
        _stale_ready_state(
            strategy,
            condition_id,
            now=now,
            stalled_sec=_BOOK_GENERATION_ABANDON_SEC + 1,
        )

    on_evaluation_heartbeat(strategy, object())  # pyright: ignore[reportArgumentType]

    assert strategy._active_condition_ids == {"btc-5m", "eth-5m", "sol-5m"}
    assert strategy.readiness == []  # no abandon ready=True
    # Every stale condition was repaired (2 instruments × 3 feeds × 3 conditions).
    assert len(strategy.unsubscribed_instruments) == 18
    assert len(strategy.subscribed_instruments) == 18

    strategy.clock.now_ns += int((_BOOK_GENERATION_STALL_SEC + 1) * 1_000_000_000)
    on_evaluation_heartbeat(strategy, object())  # pyright: ignore[reportArgumentType]

    # The adapter reconnect path replays tracked subscriptions. Do not race it
    # with another 18 unsubscribe/subscribe commands every minute.
    assert len(strategy.unsubscribed_instruments) == 18
    assert len(strategy.subscribed_instruments) == 18
    assert strategy._active_condition_ids == {"btc-5m", "eth-5m", "sol-5m"}

    recovered_at = now + timedelta(seconds=_BOOK_GENERATION_STALL_SEC + 2)
    for side in (Side.UP, Side.DOWN):
        _ = observe_market_book_side(
            strategy,
            "btc-5m",
            side,
            received_at=recovered_at,
            book_at=recovered_at,
        )
    strategy.clock.now_ns += int((_BOOK_GENERATION_STALL_SEC + 1) * 1_000_000_000)
    on_evaluation_heartbeat(strategy, object())  # pyright: ignore[reportArgumentType]

    # One recovered market proves this is no longer a global outage, so the
    # remaining two conditions can each retry their six subscriptions.
    assert len(strategy.unsubscribed_instruments) == 30
    assert len(strategy.subscribed_instruments) == 30


def test_stale_orderbook_condition_recovers_to_ready_after_bilateral_book() -> None:
    """W4 coherent lifecycle: READY → stale marker → heartbeat resubscribe
    (awaiting) → bilateral book observed → READY. The total-stall clock and the
    stale marker are cleared on recovery."""
    registry = _registry()
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    strategy = _HeartbeatStrategy(registry, now=now)
    strategy._active_condition_ids = {"btc-5m"}
    _stale_ready_state(
        strategy,
        "btc-5m",
        now=now,
        stalled_sec=_BOOK_GENERATION_STALL_SEC + 10,
    )
    state = strategy._subscription_state

    on_evaluation_heartbeat(strategy, object())  # pyright: ignore[reportArgumentType]

    # Heartbeat repair re-began generation: both sides awaited again.
    assert state.awaiting_book_sides_by_condition["btc-5m"] == {Side.UP, Side.DOWN}
    assert "btc-5m" not in strategy._stale_orderbook_recovery_by_condition

    # The feed recovers: both sides observe a fresh bilateral book.
    received_at = now + timedelta(seconds=2)
    up_ready = observe_market_book_side(
        strategy,
        "btc-5m",
        Side.UP,
        received_at=received_at,
        book_at=received_at,
    )
    assert up_ready is False
    down_ready = observe_market_book_side(
        strategy,
        "btc-5m",
        Side.DOWN,
        received_at=received_at,
        book_at=received_at,
    )
    assert down_ready is True

    assert state.awaiting_book_sides_by_condition == {}
    assert state.condition_phases["btc-5m"] == ConditionSubscriptionPhase.READY
    assert "btc-5m" in state.first_bilateral_book_at_by_condition
    assert "btc-5m" in state.first_bilateral_book_ever_at_by_condition
    # Total-stall clock and stale marker cleared on recovery.
    assert "btc-5m" not in state.book_stalled_started_at_by_condition
    assert "btc-5m" not in strategy._stale_orderbook_recovery_by_condition
    assert "btc-5m" in strategy._active_condition_ids
