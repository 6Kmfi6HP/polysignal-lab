"""
Input: __future__, datetime, pathlib, polysignal_lab
Output: issue #16 readiness recovery and health regression tests
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from polysignal_lab.alpha.types import (
    AlphaDecision,
    MarketView,
)
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.freshness import FreshnessPolicy
from polysignal_lab.nautilus_bridge.market_catalog import (
    InstrumentTokenMeta,
    MarketCatalog,
    MarketPairMeta,
)
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.custom_data_state import StrategyCustomDataState
from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketUniverseData
from polysignal_lab.nautilus_runtime.node_builder_components import (
    CacheBoundBookDataProvider,
)
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicy
from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy
from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
    MarketSubscriptionCoordinator,
    MarketSubscriptionState,
    mark_market_subscription_ready,
    refresh_stale_market_subscription,
    subscribe_market_conditions,
)
from polysignal_lab.observability.runtime_health import (
    evaluate_liveness,
    read_runtime_heartbeat,
    write_runtime_heartbeat,
)


def _dt(second: int) -> datetime:
    return datetime(2026, 7, 14, 6, 0, 0, tzinfo=UTC) + timedelta(seconds=second)


class _SubscriptionTestStrategy:
    def __init__(
        self,
        *,
        name: str = "",
        operations: list[tuple[str, str]] | None = None,
    ) -> None:
        self.registry = MarketCatalog()
        self.book_type = "L2_MBP"
        self._startup_condition_ids: tuple[str, ...] = ()
        self._active_condition_ids = {"condition-a"}
        self._subscription_state = MarketSubscriptionState()
        self._asset_condition_ids: dict[str, tuple[str, ...]] = {}
        self.book_subs: list[str] = []
        self.quote_subs: list[str] = []
        self.trade_subs: list[str] = []
        self.book_unsubs: list[str] = []
        self.quote_unsubs: list[str] = []
        self.trade_unsubs: list[str] = []
        self.requests: list[str] = []
        self.fail_quote_subscribe = False
        self.quote_subscribe_attempts = 0
        self.name = name
        self.operations = operations

    def _readiness_detail(
        self,
        condition_id: str,
        *,
        now: datetime,
    ) -> dict[str, object]:
        _ = condition_id, now
        return {}

    def request_instrument(self, instrument_id: object) -> None:
        self.requests.append(str(instrument_id))

    def subscribe_quote_ticks(self, instrument_id: object) -> None:
        self.quote_subscribe_attempts += 1
        if self.fail_quote_subscribe:
            raise ValueError("The instrument has not been registered")
        self.quote_subs.append(str(instrument_id))

    def subscribe_trade_ticks(self, instrument_id: object) -> None:
        self.trade_subs.append(str(instrument_id))

    def subscribe_order_book_deltas(
        self,
        instrument_id: object,
        *,
        book_type: object,
    ) -> None:
        _ = book_type
        self.book_subs.append(str(instrument_id))
        if self.operations is not None:
            self.operations.append((self.name, "subscribe"))

    def unsubscribe_quote_ticks(self, instrument_id: object) -> None:
        self.quote_unsubs.append(str(instrument_id))

    def unsubscribe_trade_ticks(self, instrument_id: object) -> None:
        self.trade_unsubs.append(str(instrument_id))

    def unsubscribe_order_book_deltas(self, instrument_id: object) -> None:
        self.book_unsubs.append(str(instrument_id))
        if self.operations is not None:
            self.operations.append((self.name, "unsubscribe"))


def _subscription_test_strategy(
    *,
    name: str = "",
    operations: list[tuple[str, str]] | None = None,
) -> _SubscriptionTestStrategy:
    strategy = _SubscriptionTestStrategy(name=name, operations=operations)
    strategy.registry.register(
        MarketPairMeta(
            market_id="m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a", Side.UP),
            down=InstrumentTokenMeta("down-a", Side.DOWN),
        )
    )
    return strategy


def _runtime_market_registry(
    *,
    start_ts: datetime,
    end_ts: datetime | None = None,
) -> tuple[MarketCatalog, dict[Side, str]]:
    condition_id = "condition-a"
    instrument_ids = {
        Side.UP: f"{condition_id}-up-a.POLYMARKET",
        Side.DOWN: f"{condition_id}-down-a.POLYMARKET",
    }
    registry = MarketCatalog(
        instrument_id_resolver=lambda _condition_id, token_id: (
            instrument_ids[Side.UP]
            if token_id == "up-a"
            else instrument_ids[Side.DOWN]
        )
    )
    registry.register(
        MarketPairMeta(
            market_id="m-a",
            market_slug="btc-updown-5m-a",
            condition_id=condition_id,
            asset="BTC",
            timeframe="5m",
            start_ts=start_ts,
            end_ts=end_ts,
            up=InstrumentTokenMeta("up-a", Side.UP),
            down=InstrumentTokenMeta("down-a", Side.DOWN),
        )
    )
    return registry, instrument_ids


class _RuntimeBook:
    best_ask = 0.5

    def __init__(self, freshness_ms: int = 0) -> None:
        self.freshness_ms = freshness_ms


class _RuntimeView:
    def __init__(self, freshness_ms: int = 0) -> None:
        self.books = {
            Side.UP: _RuntimeBook(freshness_ms),
            Side.DOWN: _RuntimeBook(freshness_ms),
        }

    def book_for(self, side: Side) -> _RuntimeBook:
        return self.books[side]


class _RuntimeAssembler:
    custom_data: object | None = None

    def __init__(self, view: _RuntimeView | None = None) -> None:
        self.view = view or _RuntimeView()
        self.book_receipts: list[tuple[str, datetime]] = []

    def observe_book_received(
        self,
        token_id: str,
        *,
        received_at: datetime,
    ) -> None:
        self.book_receipts.append((token_id, received_at))

    def build(self, condition_id: str, *, created_at: datetime) -> _RuntimeView:
        _ = condition_id, created_at
        return self.view


class _ReceiptRuntimeAssembler(_RuntimeAssembler):
    def build(self, condition_id: str, *, created_at: datetime) -> _RuntimeView:
        _ = condition_id
        latest_receipts = dict(self.book_receipts)
        view = _RuntimeView()
        for token_id, side in (("up-a", Side.UP), ("down-a", Side.DOWN)):
            received_at = latest_receipts.get(token_id)
            view.books[side].freshness_ms = (
                1_000_000
                if received_at is None
                else max(0, int((created_at - received_at).total_seconds() * 1000))
            )
        return view


class _RuntimeCore:
    def __init__(self) -> None:
        self.calls: list[MarketView] = []

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        self.calls.append(view)
        return []


class _RuntimeBookEvent:
    def __init__(
        self,
        instrument_id: str,
        *,
        ts_init: int | None = None,
        ts_event: int | None = None,
        ts_last: int | None = None,
    ) -> None:
        self.instrument_id = instrument_id
        self.ts_init = ts_init
        self.ts_event = ts_event
        self.ts_last = ts_last


class _Issue16Strategy(PolySignalNativeStrategy):
    now = _dt(0)

    @property
    def subscription_operations(self) -> list[tuple[str, str]]:
        operations = getattr(self, "_subscription_operations", None)
        if operations is None:
            operations = []
            self._subscription_operations = operations
        return operations

    def _record_subscription(self, operation: str, instrument_id: object) -> None:
        self.subscription_operations.append((operation, str(instrument_id)))

    def _framework_now(self) -> datetime:
        return self.now

    def subscribe_quote_ticks(self, instrument_id: object) -> None:
        self._record_subscription("quote", instrument_id)

    def subscribe_trade_ticks(self, instrument_id: object) -> None:
        self._record_subscription("trade", instrument_id)

    def subscribe_order_book_deltas(
        self,
        instrument_id: object,
        *,
        book_type: object,
    ) -> None:
        _ = book_type
        self._record_subscription("book", instrument_id)

    def unsubscribe_quote_ticks(self, instrument_id: object) -> None:
        self._record_subscription("unsubscribe_quote", instrument_id)

    def unsubscribe_trade_ticks(self, instrument_id: object) -> None:
        self._record_subscription("unsubscribe_trade", instrument_id)

    def unsubscribe_order_book_deltas(self, instrument_id: object) -> None:
        self._record_subscription("unsubscribe_book", instrument_id)


class _SharedReadinessScenario:
    def __init__(self, tmp_path: Path) -> None:
        self.condition_id = "condition-a"
        self.registry, self.instrument_ids = _runtime_market_registry(
            start_ts=_dt(10)
        )
        self.readiness: list[tuple[str, bool]] = []
        self.diagnostics: list[dict[str, object]] = []
        self.heartbeat_path = tmp_path / "runtime_heartbeat.json"
        self.coordinator = MarketSubscriptionCoordinator()
        self.first = self._build_strategy("first")
        self.second = self._build_strategy("second")

    def _note_readiness(
        self,
        key: str,
        ready: bool,
        detail: dict[str, object],
    ) -> None:
        self.readiness.append((key, ready))
        self.diagnostics.append(detail)
        write_runtime_heartbeat(
            self.heartbeat_path,
            phase="readiness_ok" if ready else "readiness_miss",
            readiness_key=key,
            readiness_ok=ready,
            readiness_detail=detail,
            now=_dt(10),
        )

    def _build_strategy(self, name: str) -> _Issue16Strategy:
        return _Issue16Strategy(
            core=_RuntimeCore(),
            assembler=_RuntimeAssembler(),
            condition_ids=(self.condition_id,),
            strategy_name=name,
            policy=DecisionPolicy(),
            registry=self.registry,
            readiness_callback=self._note_readiness,
            subscription_coordinator=self.coordinator,
        )

    def preload(self) -> None:
        for strategy in (self.first, self.second):
            strategy._subscribe_market_conditions((self.condition_id,))
            strategy.on_order_book_deltas(
                _RuntimeBookEvent(self.instrument_ids[Side.UP])
            )
            strategy.on_order_book_deltas(
                _RuntimeBookEvent(self.instrument_ids[Side.DOWN])
            )

    def enter_market(self) -> None:
        self.first.now = _dt(10)
        self.second.now = _dt(10)


def test_liveness_fails_for_persistent_readiness_miss(tmp_path: Path) -> None:
    path = tmp_path / "runtime_heartbeat.json"
    write_runtime_heartbeat(path, phase="readiness_miss", now=_dt(0))
    # Keep heartbeat fresh while readiness_miss phase remains long-lived.
    write_runtime_heartbeat(path, phase="readiness_miss", now=_dt(290))

    result = evaluate_liveness(
        path,
        max_age_sec=120,
        max_readiness_miss_sec=300,
        now=_dt(301),
    )

    assert result.ok is False
    assert result.reason == "readiness_miss"
    heartbeat = read_runtime_heartbeat(path)
    assert heartbeat.phase == "readiness_miss"
    assert heartbeat.phase_started_at is not None


def test_liveness_fails_when_readiness_miss_interleaves_with_market_evaluation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime_heartbeat.json"
    for second in (0, 100, 200, 290):
        write_runtime_heartbeat(
            path,
            phase="market_data_evaluation",
            now=_dt(second),
        )
        write_runtime_heartbeat(
            path,
            phase="readiness_miss",
            now=_dt(second + 1),
        )

    result = evaluate_liveness(
        path,
        max_age_sec=120,
        max_readiness_miss_sec=300,
        now=_dt(302),
    )

    assert result.ok is False
    assert result.reason == "readiness_miss"


def test_liveness_preserves_repeated_condition_miss_start_time(tmp_path: Path) -> None:
    path = tmp_path / "runtime_heartbeat.json"
    write_runtime_heartbeat(
        path,
        phase="readiness_miss",
        readiness_key="condition-a",
        readiness_ok=False,
        now=_dt(0),
    )
    write_runtime_heartbeat(
        path,
        phase="readiness_miss",
        readiness_key="condition-a",
        readiness_ok=False,
        now=_dt(290),
    )

    result = evaluate_liveness(
        path,
        max_age_sec=120,
        max_readiness_miss_sec=300,
        now=_dt(302),
    )

    assert result.ok is False
    assert result.reason == "readiness_miss"
    assert read_runtime_heartbeat(path).readiness_miss_started_at_by_key == {
        "condition-a": _dt(0).isoformat(),
    }


def test_liveness_keeps_other_condition_miss_when_one_condition_recovers(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime_heartbeat.json"
    write_runtime_heartbeat(
        path,
        phase="readiness_miss",
        readiness_key="condition-a",
        readiness_ok=False,
        now=_dt(0),
    )
    write_runtime_heartbeat(
        path,
        phase="readiness_miss",
        readiness_key="condition-b",
        readiness_ok=False,
        now=_dt(100),
    )
    write_runtime_heartbeat(
        path,
        phase="readiness_ok",
        readiness_key="condition-b",
        readiness_ok=True,
        now=_dt(290),
    )

    result = evaluate_liveness(
        path,
        max_age_sec=120,
        max_readiness_miss_sec=300,
        now=_dt(302),
    )

    assert result.ok is False
    assert result.reason == "readiness_miss"
    assert read_runtime_heartbeat(path).readiness_miss_started_at_by_key == {
        "condition-a": _dt(0).isoformat(),
    }


def test_liveness_clears_condition_miss_after_readiness_recovers(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime_heartbeat.json"
    write_runtime_heartbeat(
        path,
        phase="readiness_miss",
        readiness_key="condition-a",
        readiness_ok=False,
        now=_dt(0),
    )
    write_runtime_heartbeat(
        path,
        phase="readiness_ok",
        readiness_key="condition-a",
        readiness_ok=True,
        now=_dt(301),
    )

    result = evaluate_liveness(
        path,
        max_age_sec=120,
        max_readiness_miss_sec=300,
        now=_dt(302),
    )

    assert result.ok is True
    assert read_runtime_heartbeat(path).readiness_miss_started_at_by_key == {}


def test_runtime_health_exposes_persistent_readiness_detail(tmp_path: Path) -> None:
    from polysignal_lab.dashboard.reporting_read import FileRuntimeHealthReader

    path = tmp_path / "runtime_heartbeat.json"
    detail: dict[str, object] = {
        "condition_id": "condition-a",
        "market_id": "m-a",
        "subscription_state": "awaiting_first_book",
        "last_book_at_by_side": {"UP": _dt(0).isoformat(), "DOWN": None},
        "freshness_ms_by_side": {"UP": 302_000, "DOWN": None},
        "max_freshness_ms": 302_000,
        "awaiting_book_sides": ["DOWN"],
    }
    write_runtime_heartbeat(
        path,
        phase="readiness_miss",
        readiness_key="condition-a",
        readiness_ok=False,
        readiness_detail=detail,
        now=_dt(0),
    )
    write_runtime_heartbeat(path, phase="market_data_evaluation", now=_dt(301))

    result = FileRuntimeHealthReader(
        path,
        max_age_sec=120,
        max_readiness_miss_sec=300,
        now=_dt(302),
    ).read()

    assert result["status"] == "degraded"
    assert result["reason"] == "readiness_miss"
    assert result["readiness_detail_by_key"] == {"condition-a": detail}


def test_liveness_allows_brief_readiness_miss(tmp_path: Path) -> None:
    path = tmp_path / "runtime_heartbeat.json"
    write_runtime_heartbeat(path, phase="readiness_miss", now=_dt(0))

    result = evaluate_liveness(
        path,
        max_age_sec=120,
        max_readiness_miss_sec=300,
        now=_dt(30),
    )

    assert result.ok is True


def test_phase_started_at_resets_when_phase_changes(tmp_path: Path) -> None:
    path = tmp_path / "runtime_heartbeat.json"
    write_runtime_heartbeat(path, phase="readiness_miss", now=_dt(0))
    first = read_runtime_heartbeat(path)
    write_runtime_heartbeat(path, phase="running", now=_dt(10))
    second = read_runtime_heartbeat(path)
    write_runtime_heartbeat(path, phase="readiness_miss", now=_dt(20))
    third = read_runtime_heartbeat(path)

    assert first.phase_started_at == first.updated_at
    assert second.phase == "running"
    assert second.phase_started_at == second.updated_at
    assert third.phase == "readiness_miss"
    assert third.phase_started_at == third.updated_at
    assert third.phase_started_at != first.phase_started_at


def test_refresh_stale_market_subscription_resubscribes_once_per_episode() -> None:
    strategy = _subscription_test_strategy()
    subscribe_market_conditions(strategy, ("condition-a",))
    first_book_count = len(strategy.book_subs)

    assert refresh_stale_market_subscription(
        strategy,
        "condition-a",
        now=_dt(0),
        min_interval_sec=30,
    )
    assert strategy.book_unsubs
    assert len(strategy.book_subs) > first_book_count
    assert strategy._subscription_state.wire_condition_ids == {"condition-a"}

    book_count = len(strategy.book_subs)
    assert not refresh_stale_market_subscription(
        strategy,
        "condition-a",
        now=_dt(10),
        min_interval_sec=30,
    )
    assert not refresh_stale_market_subscription(
        strategy,
        "condition-a",
        now=_dt(40),
        min_interval_sec=30,
    )
    assert len(strategy.book_subs) == book_count


def test_failed_stale_subscription_refresh_recovers_after_backoff() -> None:
    strategy = _subscription_test_strategy()
    subscribe_market_conditions(strategy, ("condition-a",))
    assert refresh_stale_market_subscription(
        strategy,
        "condition-a",
        now=_dt(0),
        min_interval_sec=30,
    )
    mark_market_subscription_ready(strategy, "condition-a")

    strategy.fail_quote_subscribe = True
    assert not refresh_stale_market_subscription(
        strategy,
        "condition-a",
        now=_dt(40),
        min_interval_sec=30,
    )
    assert strategy._subscription_state.wire_condition_ids == set()
    assert strategy._subscription_state.pending_subscribe_condition_ids == {
        "condition-a"
    }
    assert strategy._subscription_state.awaiting_book_sides_by_condition == {
        "condition-a": {Side.UP, Side.DOWN}
    }

    failed_book_count = len(strategy.book_subs)
    assert not refresh_stale_market_subscription(
        strategy,
        "condition-a",
        now=_dt(50),
        min_interval_sec=30,
    )
    assert len(strategy.book_subs) == failed_book_count

    strategy.fail_quote_subscribe = False
    assert refresh_stale_market_subscription(
        strategy,
        "condition-a",
        now=_dt(70),
        min_interval_sec=30,
    )
    assert strategy._subscription_state.wire_condition_ids == {"condition-a"}

    recovered_book_count = len(strategy.book_subs)
    assert not refresh_stale_market_subscription(
        strategy,
        "condition-a",
        now=_dt(100),
        min_interval_sec=30,
    )
    assert len(strategy.book_subs) == recovered_book_count
    assert refresh_stale_market_subscription(
        strategy,
        "condition-a",
        now=_dt(130),
        min_interval_sec=30,
    )
    assert strategy._subscription_state.stale_refresh_attempts_by_condition == {
        "condition-a": 2
    }


def test_coordinated_refresh_resubscribes_all_consumers() -> None:
    operations: list[tuple[str, str]] = []
    first = _subscription_test_strategy(name="first", operations=operations)
    second = _subscription_test_strategy(name="second", operations=operations)
    for consumer in (first, second):
        subscribe_market_conditions(consumer, ("condition-a",), now=_dt(0))
    operations.clear()
    coordinator = MarketSubscriptionCoordinator()
    coordinator.register(first)
    coordinator.register(second)

    assert coordinator.refresh(first, "condition-a", now=_dt(30))
    assert operations == []
    for consumer in (first, second):
        assert consumer._subscription_state.deferred_resubscribe_condition_ids == {
            "condition-a"
        }

    assert coordinator.refresh(first, "condition-a", now=_dt(31))
    for name in ("first", "second"):
        assert operations.count((name, "unsubscribe")) == 2
        assert operations.count((name, "subscribe")) == 0
    for consumer in (first, second):
        assert consumer._subscription_state.awaiting_book_sides_by_condition == {}

    assert coordinator.refresh(first, "condition-a", now=_dt(61))
    for name in ("first", "second"):
        assert operations.count((name, "subscribe")) == 2
    for consumer in (first, second):
        assert consumer._subscription_state.deferred_resubscribe_condition_ids == set()
        assert consumer._subscription_state.awaiting_book_sides_by_condition == {
            "condition-a": {Side.UP, Side.DOWN}
        }


def test_coordinated_refresh_batches_conditions_for_websocket_reconnect() -> None:
    strategy = _subscription_test_strategy()
    strategy.registry.register(
        MarketPairMeta(
            market_id="m-b",
            market_slug="eth-updown-5m-b",
            condition_id="condition-b",
            asset="ETH",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-b", Side.UP),
            down=InstrumentTokenMeta("down-b", Side.DOWN),
        )
    )
    strategy._active_condition_ids.add("condition-b")
    subscribe_market_conditions(
        strategy,
        ("condition-a", "condition-b"),
        now=_dt(0),
    )
    coordinator = MarketSubscriptionCoordinator()
    coordinator.register(strategy)

    assert coordinator.refresh(strategy, "condition-a", now=_dt(30))
    assert coordinator.refresh(strategy, "condition-b", now=_dt(30))
    assert strategy.book_unsubs == []

    assert coordinator.refresh(strategy, "condition-a", now=_dt(31))
    assert coordinator.refresh(strategy, "condition-b", now=_dt(31))
    assert strategy._subscription_state.wire_condition_ids == set()
    assert strategy._subscription_state.deferred_resubscribe_condition_ids == {
        "condition-a",
        "condition-b",
    }

    operation_count = len(strategy.book_subs)
    assert coordinator.refresh(strategy, "condition-a", now=_dt(61))
    assert len(strategy.book_subs) == operation_count + 4
    assert strategy._subscription_state.wire_condition_ids == {
        "condition-a",
        "condition-b",
    }

def test_coordinated_refresh_resets_all_wire_conditions_on_one_stale_trigger() -> None:
    strategy = _subscription_test_strategy()
    for suffix, asset in (("b", "ETH"), ("c", "SOL")):
        strategy.registry.register(
            MarketPairMeta(
                market_id=f"m-{suffix}",
                market_slug=f"{asset.lower()}-updown-5m-{suffix}",
                condition_id=f"condition-{suffix}",
                asset=asset,
                timeframe="5m",
                start_ts=None,
                end_ts=None,
                up=InstrumentTokenMeta(f"up-{suffix}", Side.UP),
                down=InstrumentTokenMeta(f"down-{suffix}", Side.DOWN),
            )
        )
    strategy._active_condition_ids.update({"condition-b", "condition-c"})
    subscribe_market_conditions(
        strategy,
        ("condition-a", "condition-b", "condition-c"),
        now=_dt(0),
    )
    strategy._active_condition_ids.remove("condition-c")
    coordinator = MarketSubscriptionCoordinator()
    coordinator.register(strategy)

    assert coordinator.refresh(strategy, "condition-a", now=_dt(30))
    assert coordinator.refresh(strategy, "condition-a", now=_dt(31))
    assert strategy._subscription_state.wire_condition_ids == set()

    operation_count = len(strategy.book_subs)
    assert coordinator.refresh(strategy, "condition-a", now=_dt(61))
    assert len(strategy.book_subs) == operation_count + 6
    assert strategy._subscription_state.wire_condition_ids == {
        "condition-a",
        "condition-b",
        "condition-c",
    }
    assert strategy._subscription_state.retained_wire_condition_ids == set()
    assert "condition-c" not in (
        strategy._subscription_state.awaiting_book_sides_by_condition
    )


def test_coordinated_refresh_does_not_restore_owner_exited_during_settle() -> None:
    strategy = _subscription_test_strategy()
    strategy.registry.register(
        MarketPairMeta(
            market_id="m-b",
            market_slug="eth-updown-5m-b",
            condition_id="condition-b",
            asset="ETH",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-b", Side.UP),
            down=InstrumentTokenMeta("down-b", Side.DOWN),
        )
    )
    strategy._active_condition_ids.add("condition-b")
    subscribe_market_conditions(
        strategy,
        ("condition-a", "condition-b"),
        now=_dt(0),
    )
    coordinator = MarketSubscriptionCoordinator()
    coordinator.register(strategy)

    assert coordinator.refresh(strategy, "condition-a", now=_dt(30))
    assert coordinator.refresh(strategy, "condition-a", now=_dt(31))
    strategy._active_condition_ids.remove("condition-b")

    operation_count = len(strategy.book_subs)
    assert coordinator.refresh(strategy, "condition-a", now=_dt(61))
    assert len(strategy.book_subs) == operation_count + 2
    assert strategy._subscription_state.wire_condition_ids == {"condition-a"}
    assert "condition-b" not in (
        strategy._subscription_state.deferred_resubscribe_condition_ids
    )


def test_coordinated_refresh_drains_batch_after_full_rotation() -> None:
    strategy = _subscription_test_strategy()
    strategy.registry.register(
        MarketPairMeta(
            market_id="m-b",
            market_slug="eth-updown-5m-b",
            condition_id="condition-b",
            asset="ETH",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-b", Side.UP),
            down=InstrumentTokenMeta("down-b", Side.DOWN),
        )
    )
    subscribe_market_conditions(strategy, ("condition-a",), now=_dt(0))
    coordinator = MarketSubscriptionCoordinator()
    coordinator.register(strategy)
    assert coordinator.refresh(strategy, "condition-a", now=_dt(30))
    assert coordinator.refresh(strategy, "condition-a", now=_dt(31))

    strategy._active_condition_ids = {"condition-b"}
    subscribe_market_conditions(strategy, ("condition-b",), now=_dt(40))
    assert strategy._subscription_state.wire_condition_ids == set()
    assert strategy._subscription_state.deferred_resubscribe_condition_ids == {
        "condition-a",
        "condition-b",
    }

    assert coordinator.resume_pending(strategy, "condition-b", now=_dt(61))
    assert strategy._subscription_state.wire_condition_ids == {"condition-b"}
    assert strategy._subscription_state.deferred_resubscribe_condition_ids == set()


def test_new_subscription_joins_earliest_pending_refresh_deadline() -> None:
    strategy = _subscription_test_strategy()
    coordinator = MarketSubscriptionCoordinator()
    coordinator.register(strategy)
    coordinator._resubscribe_not_before_by_condition.update(
        {
            "fast-condition": _dt(60),
            "slow-condition": _dt(300),
        }
    )
    assert coordinator.defer_subscription(strategy, "slow-condition")
    assert (
        coordinator._resubscribe_not_before_by_condition["slow-condition"]
        == _dt(300)
    )

    subscribe_market_conditions(strategy, ("condition-a",), now=_dt(40))
    assert strategy._subscription_state.wire_condition_ids == set()
    assert coordinator.resume_pending(strategy, "condition-a", now=_dt(60))
    assert strategy._subscription_state.wire_condition_ids == {"condition-a"}
    assert "condition-a" not in (
        strategy._subscription_state.deferred_resubscribe_condition_ids
    )


def test_coordinated_refresh_backs_off_after_subscribe_failure() -> None:
    strategy = _subscription_test_strategy()
    subscribe_market_conditions(strategy, ("condition-a",), now=_dt(0))
    coordinator = MarketSubscriptionCoordinator()
    coordinator.register(strategy)

    assert coordinator.refresh(strategy, "condition-a", now=_dt(30))
    assert coordinator.refresh(strategy, "condition-a", now=_dt(31))
    strategy.fail_quote_subscribe = True
    attempts_before_failure = strategy.quote_subscribe_attempts

    assert not coordinator.refresh(strategy, "condition-a", now=_dt(61))
    assert strategy.quote_subscribe_attempts == attempts_before_failure + 2
    assert coordinator.refresh(strategy, "condition-a", now=_dt(62))
    assert coordinator.refresh(strategy, "condition-a", now=_dt(90))
    assert strategy.quote_subscribe_attempts == attempts_before_failure + 2

    assert not coordinator.refresh(strategy, "condition-a", now=_dt(91))
    assert strategy.quote_subscribe_attempts == attempts_before_failure + 4


def test_heartbeat_resumes_deferred_refresh_before_recent_data_skip(
    tmp_path: Path,
) -> None:
    scenario = _SharedReadinessScenario(tmp_path)
    scenario.preload()
    scenario.enter_market()
    assert scenario.first.refresh_stale_market_subscription(scenario.condition_id)
    for strategy in (scenario.first, scenario.second):
        strategy.now = _dt(11)
        strategy._last_market_data_evaluation_at[scenario.condition_id] = _dt(11)

    scenario.first._on_evaluation_heartbeat(None)
    for strategy in (scenario.first, scenario.second):
        assert strategy._subscription_state.deferred_resubscribe_condition_ids == {
            scenario.condition_id
        }
        strategy.now = _dt(41)
        strategy._last_market_data_evaluation_at[scenario.condition_id] = _dt(41)

    scenario.first._on_evaluation_heartbeat(None)
    for strategy in (scenario.first, scenario.second):
        assert strategy._subscription_state.deferred_resubscribe_condition_ids == set()
        assert strategy._subscription_state.awaiting_book_sides_by_condition == {
            scenario.condition_id: {Side.UP, Side.DOWN}
        }


def test_trade_freshness_rejection_does_not_drive_subscription_refresh() -> None:
    from polysignal_lab.nautilus_runtime.decision_policy import RejectedDecision
    from polysignal_lab.nautilus_runtime.strategy.observability_hooks import record_rejected
    from polysignal_lab.domain.signal import SignalCandidate

    calls: list[str] = []
    readiness: list[tuple[str, bool]] = []
    recoveries: list[tuple[str, object, object]] = []

    class Strategy:
        observability = None
        fixed_stake_usdc = 1.0

        def _note_runtime_progress(self, phase: str) -> None:
            _ = phase

        def _note_stale_orderbook_rejection(
            self,
            condition_id: str,
            *,
            side: object,
            threshold_ms: object,
        ) -> None:
            recoveries.append((condition_id, side, threshold_ms))
            readiness.append((condition_id, False))

        def refresh_stale_market_subscription(self, condition_id: str) -> bool:
            calls.append(condition_id)
            return True

    candidate = SignalCandidate.build(
        strategy="late_consensus",
        asset="BTC",
        timeframe="5m",
        market_id="1",
        market_slug="btc-updown-5m",
        condition_id="condition-a",
        token_id="up-a",
        side=Side.UP,
        confidence=0.7,
        entry_reference_price=0.5,
        max_entry_price=0.9,
        seconds_to_close=60,
        data_freshness_ms=200_000,
        reason_codes=["EDGE"],
        metrics={},
        created_at=_dt(0),
        snapshot_id="view-1",
    )
    rejected = RejectedDecision(
        reason_code="STALE_ORDERBOOK",
        detail={
            "lag_ms": 200_000,
            "source": "orderbook",
            "threshold_ms": 100_000,
        },
        candidate=candidate,
    )
    record_rejected(Strategy(), rejected)

    assert readiness == []
    assert recoveries == []
    assert calls == []


def test_order_book_event_records_receipt_time_for_market_view_freshness() -> None:
    condition_id = "condition-a"
    registry, instrument_ids = _runtime_market_registry(start_ts=_dt(0))
    assembler = _RuntimeAssembler()
    strategy = _Issue16Strategy(
        core=_RuntimeCore(),
        assembler=assembler,
        condition_ids=(condition_id,),
        strategy_name="test",
        policy=DecisionPolicy(),
        registry=registry,
    )
    strategy.now = _dt(10)
    strategy._subscribe_market_conditions((condition_id,))

    strategy.on_order_book_deltas(
        _RuntimeBookEvent(
            instrument_ids[Side.UP],
            ts_init=int(_dt(10).timestamp() * 1_000_000_000),
            ts_event=int(_dt(0).timestamp() * 1_000_000_000),
        )
    )

    assert assembler.book_receipts == [("up-a", _dt(10))]


def test_market_view_receipt_reaches_cache_provider() -> None:
    registry, _ = _runtime_market_registry(start_ts=_dt(0))

    class Level:
        def __init__(self, price: float, size: float) -> None:
            self.price = price
            self.size = size

    class Book:
        bids = (Level(0.49, 10.0),)
        asks = (Level(0.51, 20.0),)
        received_at = None

    class Cache:
        def order_book(self, instrument_id: object) -> Book:
            _ = instrument_id
            return Book()

        def trade_ticks(self, instrument_id: object) -> tuple[()]:
            _ = instrument_id
            return ()

    books = CacheBoundBookDataProvider(registry)
    books.bind_cache(Cache())
    assembler = MarketViewAssembler(
        catalog=registry,
        books=books,
        custom_data=StrategyCustomDataState(),
    )

    assembler.observe_book_received("up-a", received_at=_dt(10))

    book = books.book_for_token("up-a", now=_dt(11))
    assert book is not None
    assert book.received_at == _dt(10)
    assert book.freshness_ms == 1_000


def test_quote_tick_records_unchanged_resubscribe_snapshot_receipt() -> None:
    condition_id = "condition-a"
    registry, instrument_ids = _runtime_market_registry(start_ts=_dt(0))
    assembler = _RuntimeAssembler()
    strategy = _Issue16Strategy(
        core=_RuntimeCore(),
        assembler=assembler,
        condition_ids=(condition_id,),
        strategy_name="test",
        policy=DecisionPolicy(),
        registry=registry,
    )
    strategy.now = _dt(10)
    strategy._subscribe_market_conditions((condition_id,))

    strategy.on_quote_tick(
        _RuntimeBookEvent(
            instrument_ids[Side.UP],
            ts_init=int(_dt(10).timestamp() * 1_000_000_000),
            ts_event=int(_dt(0).timestamp() * 1_000_000_000),
        )
    )

    assert assembler.book_receipts == [("up-a", _dt(10))]
    assert strategy._subscription_state.awaiting_book_sides_by_condition == {
        condition_id: {Side.DOWN}
    }


def test_later_snapshot_reopens_strict_trigger_window_without_resubscribe() -> None:
    condition_id = "condition-a"
    registry, instrument_ids = _runtime_market_registry(start_ts=_dt(0))
    assembler = _ReceiptRuntimeAssembler()
    core = _RuntimeCore()
    strategy = _Issue16Strategy(
        core=core,
        assembler=assembler,
        condition_ids=(condition_id,),
        strategy_name="test",
        policy=DecisionPolicy(
            strategy_freshness_policies={
                "test": FreshnessPolicy(max_orderbook_staleness_ms=1_200)
            }
        ),
        registry=registry,
    )
    stale_book_at = int(_dt(0).timestamp() * 1_000_000_000)
    strategy.now = _dt(10)
    strategy.on_order_book_deltas(
        _RuntimeBookEvent(
            instrument_ids[Side.UP],
            ts_init=int(strategy.now.timestamp() * 1_000_000_000),
            ts_last=stale_book_at,
        )
    )
    for side in (Side.UP, Side.DOWN):
        strategy.on_order_book_deltas(
            _RuntimeBookEvent(
                instrument_ids[side],
                ts_init=int(strategy.now.timestamp() * 1_000_000_000),
                ts_last=stale_book_at,
            )
        )

    assert len(core.calls) == 1
    assert all(core.calls[-1].book_for(side).freshness_ms == 0 for side in Side)

    strategy.now = _dt(12)
    strategy.evaluate_condition(condition_id, created_at=strategy.now)

    assert len(core.calls) == 1
    assert strategy._subscription_state.awaiting_book_sides_by_condition == {
        condition_id: set()
    }

    # The adapter always emits a quote from a resubscribe snapshot, even when
    # effective order-book deltas are empty because the levels are unchanged.
    for side in (Side.UP, Side.DOWN):
        strategy.on_quote_tick(
            _RuntimeBookEvent(
                instrument_ids[side],
                ts_init=int(strategy.now.timestamp() * 1_000_000_000),
                ts_last=stale_book_at,
            )
        )

    assert len(core.calls) == 2
    assert all(core.calls[-1].book_for(side).freshness_ms == 0 for side in Side)


def test_strategy_stale_books_skip_candidate_without_data_plane_refresh() -> None:
    condition_id = "condition-a"
    registry, _ = _runtime_market_registry(start_ts=_dt(0))
    core = _RuntimeCore()
    readiness: list[tuple[str, bool, dict[str, object]]] = []
    refreshes: list[str] = []
    strategy = _Issue16Strategy(
        core=core,
        assembler=_RuntimeAssembler(_RuntimeView(freshness_ms=50_000)),
        condition_ids=(condition_id,),
        strategy_name="test",
        policy=DecisionPolicy(
            strategy_freshness_policies={
                "test": FreshnessPolicy(max_orderbook_staleness_ms=30_000)
            }
        ),
        registry=registry,
        readiness_callback=lambda key, ready, detail: readiness.append(
            (key, ready, detail)
        ),
    )
    strategy.now = _dt(70)
    strategy.refresh_stale_market_subscription = (  # type: ignore[method-assign]
        lambda condition_id: refreshes.append(condition_id) or True
    )

    strategy.evaluate_condition(condition_id)

    assert core.calls == []
    assert [(key, ready) for key, ready, _ in readiness] == [(condition_id, True)]
    assert refreshes == []


def test_one_strategy_stale_side_skips_stateful_core_without_data_plane_refresh() -> None:
    condition_id = "condition-a"
    registry, _ = _runtime_market_registry(start_ts=_dt(0))
    view = _RuntimeView()
    view.books[Side.UP].freshness_ms = 10_000
    view.books[Side.DOWN].freshness_ms = 50_000
    core = _RuntimeCore()
    readiness: list[tuple[str, bool]] = []
    strategy = _Issue16Strategy(
        core=core,
        assembler=_RuntimeAssembler(view),
        condition_ids=(condition_id,),
        strategy_name="test",
        policy=DecisionPolicy(
            strategy_freshness_policies={
                "test": FreshnessPolicy(max_orderbook_staleness_ms=30_000)
            }
        ),
        registry=registry,
        readiness_callback=lambda key, ready, _detail: readiness.append(
            (key, ready)
        ),
    )
    strategy.now = _dt(70)

    strategy.evaluate_condition(condition_id)

    assert core.calls == []
    assert readiness[-1] == (condition_id, True)


def test_preloaded_books_do_not_start_readiness_miss(tmp_path: Path) -> None:
    scenario = _SharedReadinessScenario(tmp_path)
    scenario.preload()

    assert scenario.readiness == []
    assert scenario.diagnostics == []
    assert all(
        scenario.condition_id
        not in strategy._runtime_readiness_miss_condition_ids
        for strategy in (scenario.first, scenario.second)
    )
    assert not scenario.heartbeat_path.exists()


def test_restart_on_start_rehydrates_books_before_readiness() -> None:
    condition_id = "condition-a"
    registry, instrument_ids = _runtime_market_registry(start_ts=_dt(0))
    readiness: list[tuple[str, bool]] = []
    strategy = _Issue16Strategy(
        core=_RuntimeCore(),
        assembler=_ReceiptRuntimeAssembler(),
        condition_ids=(condition_id,),
        strategy_name="test",
        policy=DecisionPolicy(),
        registry=registry,
        readiness_callback=lambda key, ready, _detail: readiness.append((key, ready)),
    )
    strategy.now = _dt(10)

    strategy.on_start()

    assert strategy.subscription_operations == [
        ("quote", instrument_ids[Side.UP]),
        ("trade", instrument_ids[Side.UP]),
        ("book", instrument_ids[Side.UP]),
        ("quote", instrument_ids[Side.DOWN]),
        ("trade", instrument_ids[Side.DOWN]),
        ("book", instrument_ids[Side.DOWN]),
    ]
    assert strategy._subscription_state.wire_condition_ids == {condition_id}
    assert strategy._subscription_state.awaiting_book_sides_by_condition == {
        condition_id: {Side.UP, Side.DOWN}
    }

    strategy.on_order_book_deltas(
        _RuntimeBookEvent(
            instrument_ids[Side.UP],
            ts_init=int(_dt(10).timestamp() * 1_000_000_000),
        )
    )
    assert readiness[-1] == (condition_id, False)
    strategy.on_order_book_deltas(
        _RuntimeBookEvent(
            instrument_ids[Side.DOWN],
            ts_init=int(_dt(10).timestamp() * 1_000_000_000),
        )
    )

    assert readiness[-1] == (condition_id, True)
    assert strategy._subscription_state.awaiting_book_sides_by_condition == {
        condition_id: set()
    }


def test_resubscribe_requires_current_generation_book_sides(
    tmp_path: Path,
) -> None:
    scenario = _SharedReadinessScenario(tmp_path)
    scenario.preload()
    scenario.enter_market()
    assert scenario.first.refresh_stale_market_subscription(
        scenario.condition_id
    )
    for strategy in (scenario.first, scenario.second):
        strategy.now = _dt(11)
    assert scenario.first.refresh_stale_market_subscription(
        scenario.condition_id
    )
    for strategy in (scenario.first, scenario.second):
        strategy.now = _dt(41)
    assert scenario.first.refresh_stale_market_subscription(
        scenario.condition_id
    )

    scenario.first.on_order_book_deltas(
        _RuntimeBookEvent(
            scenario.instrument_ids[Side.UP],
            ts_init=int(_dt(41).timestamp() * 1_000_000_000),
            ts_last=int(_dt(2).timestamp() * 1_000_000_000),
        )
    )

    assert scenario.condition_id in (
        scenario.first._runtime_readiness_miss_condition_ids
    )
    assert scenario.diagnostics[-1]["market_id"] == "m-a"
    assert scenario.diagnostics[-1]["subscription_state"] == "awaiting_first_book"
    assert scenario.diagnostics[-1]["awaiting_book_sides"] == ["DOWN"]
    assert scenario.diagnostics[-1]["last_book_at_by_side"] == {
        "UP": _dt(2).isoformat(),
        "DOWN": _dt(0).isoformat(),
    }
    assert scenario.diagnostics[-1]["last_book_received_at_by_side"] == {
        "UP": _dt(41).isoformat(),
        "DOWN": _dt(0).isoformat(),
    }
    assert scenario.diagnostics[-1]["freshness_ms_by_side"] == {
        "UP": 0,
        "DOWN": 41_000,
    }

    scenario.first.on_order_book_deltas(
        _RuntimeBookEvent(
            scenario.instrument_ids[Side.DOWN],
            ts_init=int(_dt(-1).timestamp() * 1_000_000_000),
        )
    )

    assert scenario.first._subscription_state.awaiting_book_sides_by_condition == {
        scenario.condition_id: {Side.DOWN}
    }


def test_shared_readiness_waits_for_every_consumer_and_recovers(
    tmp_path: Path,
) -> None:
    scenario = _SharedReadinessScenario(tmp_path)
    scenario.preload()
    scenario.enter_market()
    assert scenario.first.refresh_stale_market_subscription(
        scenario.condition_id
    )
    for strategy in (scenario.first, scenario.second):
        strategy.now = _dt(11)
    assert scenario.first.refresh_stale_market_subscription(
        scenario.condition_id
    )
    for strategy in (scenario.first, scenario.second):
        strategy.now = _dt(41)
    assert scenario.first.refresh_stale_market_subscription(
        scenario.condition_id
    )

    scenario.first.on_order_book_deltas(
        _RuntimeBookEvent(
            scenario.instrument_ids[Side.UP],
            ts_init=int(_dt(41).timestamp() * 1_000_000_000),
        )
    )
    first_detail = read_runtime_heartbeat(
        scenario.heartbeat_path
    ).readiness_detail_by_key[scenario.condition_id]
    callback_count = len(scenario.readiness)

    scenario.first.on_order_book_deltas(
        _RuntimeBookEvent(
            scenario.instrument_ids[Side.DOWN],
            ts_init=int(_dt(41).timestamp() * 1_000_000_000),
        )
    )

    heartbeat = read_runtime_heartbeat(scenario.heartbeat_path)
    peer_detail = heartbeat.readiness_detail_by_key[scenario.condition_id]
    assert len(scenario.readiness) == callback_count + 1
    assert scenario.readiness[-1] == (scenario.condition_id, False)
    assert scenario.condition_id in heartbeat.readiness_miss_started_at_by_key
    assert peer_detail != first_detail
    assert peer_detail["subscription_state"] == "awaiting_first_book"
    assert peer_detail["awaiting_book_sides"] == ["DOWN", "UP"]
    assert peer_detail["last_book_at_by_side"] == {
        "UP": _dt(0).isoformat(),
        "DOWN": _dt(0).isoformat(),
    }

    scenario.second.on_order_book_deltas(
        _RuntimeBookEvent(
            scenario.instrument_ids[Side.UP],
            ts_init=int(_dt(41).timestamp() * 1_000_000_000),
        )
    )
    scenario.second.on_order_book_deltas(
        _RuntimeBookEvent(
            scenario.instrument_ids[Side.DOWN],
            ts_init=int(_dt(41).timestamp() * 1_000_000_000),
        )
    )

    assert scenario.readiness[-1] == (scenario.condition_id, True)
    assert (
        read_runtime_heartbeat(
            scenario.heartbeat_path
        ).readiness_miss_started_at_by_key
        == {}
    )

    callback_count = len(scenario.readiness)
    scenario.first.evaluate_condition(scenario.condition_id)

    assert len(scenario.readiness) == callback_count + 1
    assert scenario.readiness[-1] == (scenario.condition_id, True)


def test_shared_readiness_uses_runtime_threshold_for_strict_consumers(
    tmp_path: Path,
) -> None:
    scenario = _SharedReadinessScenario(tmp_path)
    scenario.second.assembler = _ReceiptRuntimeAssembler()
    scenario.second.policy = DecisionPolicy(
        strategy_freshness_policies={
            "second": FreshnessPolicy(max_orderbook_staleness_ms=1_500)
        }
    )
    scenario.preload()
    scenario.enter_market()
    assert scenario.first.refresh_stale_market_subscription(
        scenario.condition_id
    )
    for strategy in (scenario.first, scenario.second):
        strategy.now = _dt(11)
    assert scenario.first.refresh_stale_market_subscription(
        scenario.condition_id
    )
    for strategy in (scenario.first, scenario.second):
        strategy.now = _dt(41)
    assert scenario.first.refresh_stale_market_subscription(
        scenario.condition_id
    )

    for strategy in (scenario.first, scenario.second):
        strategy.on_order_book_deltas(
            _RuntimeBookEvent(
                scenario.instrument_ids[Side.UP],
                ts_init=int(_dt(41).timestamp() * 1_000_000_000),
            )
        )
    scenario.first.now = _dt(43)
    scenario.first.on_order_book_deltas(
        _RuntimeBookEvent(
            scenario.instrument_ids[Side.DOWN],
            ts_init=int(_dt(43).timestamp() * 1_000_000_000),
        )
    )
    scenario.second.now = _dt(43)
    scenario.second.on_order_book_deltas(
        _RuntimeBookEvent(
            scenario.instrument_ids[Side.DOWN],
            ts_init=int(_dt(43).timestamp() * 1_000_000_000),
        )
    )

    assert scenario.readiness[-1] == (scenario.condition_id, True)
    assert (
        read_runtime_heartbeat(
            scenario.heartbeat_path
        ).readiness_miss_started_at_by_key
        == {}
    )


def test_later_universe_snapshot_clears_missed_exit_readiness(
    tmp_path: Path,
) -> None:
    scenario = _SharedReadinessScenario(tmp_path)
    scenario.preload()
    scenario.first._note_runtime_readiness(scenario.condition_id, ready=False)
    scenario.second._note_runtime_readiness(scenario.condition_id, ready=False)

    scenario.first.on_data(
        PolySignalMarketUniverseData(
            epoch=1,
            exited_condition_ids=(scenario.condition_id,),
        )
    )
    scenario.second.on_data(PolySignalMarketUniverseData(epoch=2))

    heartbeat = read_runtime_heartbeat(scenario.heartbeat_path)
    assert heartbeat.readiness_miss_started_at_by_key == {}
    assert scenario.readiness[-1] == (scenario.condition_id, True)
    assert (
        scenario.condition_id
        not in scenario.second._subscription_state.wire_condition_ids
    )


def test_evaluation_heartbeat_retires_expired_condition_without_rotation() -> None:
    condition_id = "condition-a"
    registry, _ = _runtime_market_registry(
        start_ts=_dt(0),
        end_ts=_dt(300),
    )
    for unsubscribe_exited in (True, False):
        readiness: list[tuple[str, bool]] = []
        core = _RuntimeCore()
        strategy = _Issue16Strategy(
            core=core,
            assembler=_RuntimeAssembler(),
            condition_ids=(condition_id,),
            strategy_name=f"test-{unsubscribe_exited}",
            policy=DecisionPolicy(),
            registry=registry,
            readiness_callback=lambda key, ready, _detail: readiness.append(
                (key, ready)
            ),
            unsubscribe_exited=unsubscribe_exited,
        )
        strategy._subscribe_market_conditions((condition_id,))
        strategy._subscription_state.pending_metadata_condition_ids.add(condition_id)
        strategy._subscription_state.pending_subscribe_condition_ids.add(condition_id)
        strategy._note_runtime_readiness(condition_id, ready=False)

        strategy.now = _dt(301)
        strategy._on_evaluation_heartbeat(None)

        assert condition_id not in strategy._active_condition_ids
        assert (condition_id in strategy._subscription_state.wire_condition_ids) is (
            not unsubscribe_exited
        )
        assert (
            condition_id
            not in strategy._subscription_state.pending_metadata_condition_ids
        )
        assert (
            condition_id
            not in strategy._subscription_state.pending_subscribe_condition_ids
        )
        assert condition_id not in strategy._runtime_readiness_miss_condition_ids
        assert readiness[-1] == (condition_id, True)
        assert core.calls == []


def test_evaluation_heartbeat_retires_expired_before_resuming_pending() -> None:
    condition_id = "condition-a"
    registry, _ = _runtime_market_registry(
        start_ts=_dt(0),
        end_ts=_dt(300),
    )
    coordinator = MarketSubscriptionCoordinator()
    strategy = _Issue16Strategy(
        core=_RuntimeCore(),
        assembler=_RuntimeAssembler(),
        condition_ids=(condition_id,),
        strategy_name="test",
        policy=DecisionPolicy(),
        registry=registry,
        subscription_coordinator=coordinator,
    )
    coordinator.register(strategy)
    strategy._subscription_state.deferred_resubscribe_condition_ids.add(condition_id)
    coordinator._resubscribe_not_before_by_condition[condition_id] = _dt(301)

    strategy.now = _dt(301)
    strategy._on_evaluation_heartbeat(None)

    assert not any(
        operation in {"quote", "trade", "book"}
        for operation, _instrument_id in strategy.subscription_operations
    )
    assert condition_id not in strategy._active_condition_ids
    assert coordinator._resubscribe_not_before_by_condition == {}
