from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_runtime.market_catalog import (
    InstrumentTokenMeta,
    MarketCatalog,
    MarketPairMeta,
)
from polysignal_lab.nautilus_runtime.strategy.lifecycle import (
    on_evaluation_heartbeat,
)
from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
    ConditionSubscriptionPhase,
    MarketSubscriptionState,
    _BOOK_GENERATION_STALL_SEC,
    force_resubscribe_if_book_stalled,
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

    def _readiness_detail(
        self,
        condition_id: str,
        *,
        now: datetime,
    ) -> dict[str, object]:
        del condition_id, now
        return {}

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

    def _note_runtime_readiness(
        self,
        condition_id: str,
        *,
        ready: bool,
        status: object | None = None,
        reason: str | None = None,
    ) -> None:
        del condition_id, ready, status, reason

    def evaluate_condition(
        self,
        condition_id: str,
        *,
        trading_state: object | None = None,
    ) -> None:
        del trading_state
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
