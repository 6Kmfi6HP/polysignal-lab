from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_runtime.market_catalog import (
    InstrumentTokenMeta,
    MarketCatalog,
    MarketPairMeta,
)
from polysignal_lab.nautilus_runtime.strategy.readiness import readiness_detail
from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
    ConditionSubscriptionPhase,
    MarketSubscriptionState,
    _clear_global_book_recovery_state,
    _mark_replay_unconfirmed,
    begin_market_book_generation,
    condition_phase,
    force_resubscribe_if_book_stalled,
    force_resubscribe_if_stale_orderbook,
    observe_market_book_side,
)


ASSETS = ("BTC", "ETH", "SOL", "XRP")


def _condition_id(asset: str) -> str:
    return f"{asset.lower()}-5m"


def _pair(asset: str) -> MarketPairMeta:
    condition_id = _condition_id(asset)
    return MarketPairMeta(
        market_id=f"market-{condition_id}",
        market_slug=f"{asset.lower()}-updown-5m",
        condition_id=condition_id,
        asset=asset,
        timeframe="5m",
        start_ts=None,
        end_ts=None,
        up=InstrumentTokenMeta(f"{condition_id}-up", Side.UP),
        down=InstrumentTokenMeta(f"{condition_id}-down", Side.DOWN),
    )


def _registry(assets: tuple[str, ...]) -> MarketCatalog:
    registry = MarketCatalog(
        instrument_id_resolver=lambda _condition_id, token: f"{token}.POLYMARKET"
    )
    for asset in assets:
        registry.register(_pair(asset))
    return registry


class FakeAdapter:
    """Minimal strategy-like host that records official refresh calls."""

    def __init__(self, registry: MarketCatalog) -> None:
        self.registry: MarketCatalog | None = registry
        self.cache: object | None = None
        self.book_type: str = "L2_MBP"
        self.unsubscribe_exited: bool = True
        self._startup_condition_ids: tuple[str, ...] = ()
        self._active_condition_ids: set[str] = set()
        self._subscription_assets: frozenset[str] = frozenset()
        self._subscription_timeframes: frozenset[str] = frozenset({"5m"})
        self._asset_condition_ids: dict[str, tuple[str, ...]] = {}
        self._untradable_quote_sides_by_condition: dict[str, frozenset[Side]] = {}
        self._subscription_state: MarketSubscriptionState = MarketSubscriptionState()
        self._stale_orderbook_recovery_by_condition: dict[
            str, dict[Side, float]
        ] = {}
        self._runtime_readiness_reason_by_condition: dict[str, str] = {}
        self._runtime_readiness_miss_condition_ids: set[str] = set()
        self.policy: object = object()
        self.strategy_name: str = "test"
        self.progress_callback: Callable[..., None] | None = None
        self.readiness_callback: Callable[..., None] | None = None
        self.subscribed_instruments: list[str] = []
        self.unsubscribed_instruments: list[str] = []

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

    def _note_runtime_readiness(
        self,
        condition_id: str,
        *,
        ready: bool,
        status: object | None = None,
        reason: str | None = None,
    ) -> None:
        del status, reason
        if ready:
            self._runtime_readiness_miss_condition_ids.discard(condition_id)
        else:
            self._runtime_readiness_miss_condition_ids.add(condition_id)

    def _require_registry(self) -> MarketCatalog | None:
        return self.registry

    def _framework_now(self) -> datetime:
        return datetime(2026, 8, 1, 12, 0, 2, tzinfo=UTC)

    def _readiness_detail(self, condition_id: str, *, now: datetime) -> dict[str, object]:
        return {}


def _mark_stale_ready(strategy: FakeAdapter, condition_id: str, *, now: datetime) -> None:
    state = strategy._subscription_state
    started_at = now - timedelta(seconds=70)
    state.condition_phases[condition_id] = ConditionSubscriptionPhase.READY
    state.first_bilateral_book_ever_at_by_condition[condition_id] = now - timedelta(
        minutes=10
    )
    state.book_stalled_started_at_by_condition[condition_id] = started_at
    state.book_generation_started_at_by_condition[condition_id] = started_at
    strategy._stale_orderbook_recovery_by_condition[condition_id] = {
        Side.UP: 60_000.0,
        Side.DOWN: 60_000.0,
    }


def _restore_bilateral_books(
    strategy: FakeAdapter,
    condition_ids: tuple[str, ...],
    *,
    received_at: datetime,
) -> None:
    for condition_id in condition_ids:
        observe_market_book_side(
            strategy,
            condition_id,
            Side.UP,
            received_at=received_at,
            book_at=received_at,
        )
        observe_market_book_side(
            strategy,
            condition_id,
            Side.DOWN,
            received_at=received_at,
            book_at=received_at,
        )


def test_five_continuous_market_cycles_restore_all_bilateral_books() -> None:
    _clear_global_book_recovery_state()
    condition_ids = tuple(_condition_id(asset) for asset in ASSETS)
    registry = _registry(ASSETS)
    strategy = FakeAdapter(registry)
    strategy._active_condition_ids = set(condition_ids)
    start = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)

    for cycle in range(5):
        now = start + timedelta(minutes=5 * cycle)
        if cycle % 2 == 0:
            for condition_id in condition_ids:
                begin_market_book_generation(
                    strategy,
                    condition_id,
                    now=now - timedelta(seconds=70),
                )
            for condition_id in condition_ids:
                assert force_resubscribe_if_book_stalled(
                    strategy, condition_id, now=now
                )
        else:
            for condition_id in condition_ids:
                _mark_stale_ready(strategy, condition_id, now=now)
            for condition_id in condition_ids:
                assert force_resubscribe_if_stale_orderbook(
                    strategy, condition_id, now=now
                )

        expected = sorted(
            f"{condition_id}-{side.value.lower()}.POLYMARKET"
            for condition_id in condition_ids
            for side in (Side.UP, Side.DOWN)
        )
        assert sorted(strategy.unsubscribed_instruments) == sorted(expected * (cycle + 1))
        assert sorted(strategy.subscribed_instruments) == sorted(expected * (cycle + 1))

        for condition_id in condition_ids:
            assert condition_id in strategy._subscription_state.adapter_replay_started_at_by_condition

        received_at = now + timedelta(seconds=2)
        _restore_bilateral_books(strategy, condition_ids, received_at=received_at)

        for condition_id in condition_ids:
            assert condition_phase(strategy, condition_id) is ConditionSubscriptionPhase.READY
            assert condition_id not in strategy._subscription_state.awaiting_book_sides_by_condition
            assert condition_id not in strategy._subscription_state.adapter_replay_started_at_by_condition
            detail = readiness_detail(strategy, condition_id, now=received_at)
            assert detail["adapter_replay_unconfirmed"] is False
            assert detail["last_book_received_at_by_side"] == {
                "UP": received_at.isoformat(),
                "DOWN": received_at.isoformat(),
            }


def test_single_side_book_keeps_replay_marker_until_bilateral() -> None:
    """B2/partial-replay: one recovering side must not clear the replay marker.

    If a single-side receipt popped the marker, the next refresh dispatch would
    re-anchor a fresh grace timestamp and a one-sided stall (the other side
    never recovering) would renew the bounded window forever.
    """
    _clear_global_book_recovery_state()
    condition_id = _condition_id("BTC")
    strategy = FakeAdapter(_registry(("BTC",)))
    strategy._active_condition_ids = {condition_id}
    start = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    begin_market_book_generation(strategy, condition_id, now=start)
    marker = strategy._subscription_state.adapter_replay_started_at_by_condition
    assert marker[condition_id] == start

    # Only the UP side recovers; DOWN never arrives.
    received_at = start + timedelta(seconds=60)
    assert (
        observe_market_book_side(
            strategy,
            condition_id,
            Side.UP,
            received_at=received_at,
            book_at=received_at,
        )
        is False
    )
    # Marker stays anchored at the streak start (bounded grace), not re-anchored.
    assert marker[condition_id] == start
    assert strategy._subscription_state.awaiting_book_sides_by_condition[
        condition_id
    ] == {Side.DOWN}

    # A later refresh dispatch must not move the anchor either.
    _mark_replay_unconfirmed(strategy._subscription_state, condition_id, now=start + timedelta(minutes=10))
    assert marker[condition_id] == start
