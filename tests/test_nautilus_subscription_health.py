from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_runtime.custom_data_types import (
    PolySignalMarketUniverseData,
)
from polysignal_lab.nautilus_runtime.market_catalog import (
    InstrumentTokenMeta,
    MarketCatalog,
    MarketPairMeta,
)
from polysignal_lab.nautilus_runtime.strategy.custom_data_handlers import (
    handle_market_universe,
)
from polysignal_lab.nautilus_runtime.strategy.lifecycle import (
    on_strategy_start,
    on_strategy_stop,
)
from polysignal_lab.nautilus_runtime.strategy.readiness import readiness_detail
from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
    MarketSubscriptionState,
    begin_market_book_generation,
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


def _universe(
    *,
    epoch: int,
    active: tuple[str, ...],
    exited: tuple[str, ...] = (),
) -> PolySignalMarketUniverseData:
    return PolySignalMarketUniverseData(
        epoch=epoch,
        active_condition_ids=active,
        entered_condition_ids=active,
        exited_condition_ids=exited,
        condition_to_up_token={condition_id: f"{condition_id}-up" for condition_id in active},
        condition_to_down_token={
            condition_id: f"{condition_id}-down" for condition_id in active
        },
        condition_to_asset={},
        condition_to_timeframe={},
        ts_event=1,
        ts_init=1,
    )


class _UniverseStrategy:
    def __init__(self, registry: MarketCatalog) -> None:
        self.registry = registry
        self._active_condition_ids: set[str] = set()
        self._asset_condition_ids: dict[str, tuple[str, ...]] = {}
        self._market_epoch: int | None = None
        self.unsubscribe_exited = True
        self._subscription_state = MarketSubscriptionState()
        self.cache = None
        self._subscription_assets = frozenset({"BTC"})
        self._subscription_timeframes = frozenset({"5m", "15m"})
        self.subscribed: list[tuple[str, ...]] = []
        self.unsubscribed: list[tuple[str, ...]] = []
        self.readiness: list[tuple[str, bool]] = []

    def _refresh_asset_conditions(self) -> None:
        return None

    def _subscribe_market_conditions(self, condition_ids: tuple[str, ...]) -> None:
        self.subscribed.append(tuple(sorted(condition_ids)))

    def _unsubscribe_market_conditions(self, condition_ids: tuple[str, ...]) -> None:
        self.unsubscribed.append(tuple(sorted(condition_ids)))

    def _note_runtime_readiness(self, condition_id: str, *, ready: bool) -> None:
        self.readiness.append((condition_id, ready))


class _Clock:
    def timestamp_ns(self) -> int:
        return 1_785_504_000_000_000_000

    def set_timer(self, name: object, interval: object, *, callback: object) -> None:
        del name, interval, callback

    def cancel_timer(self, name: object) -> None:
        del name


class _LifecycleStrategy:
    def __init__(self, registry: MarketCatalog) -> None:
        self.registry: MarketCatalog | None = registry
        self.assembler: object = SimpleNamespace(is_bound=True)
        self.cache: object | None = None
        self.clock: object = _Clock()
        self.trader_id: object | None = None
        self.strategy_name: str = "ptb_diff"
        self._execution_mode: str = "live"
        self._evaluation_heartbeat_started = False
        self._subscriptions_started = False
        self._startup_condition_ids: tuple[str, ...] = ("btc-5m", "eth-5m")
        self._active_condition_ids: set[str] = set(self._startup_condition_ids)
        self._last_market_data_evaluation_at: dict[str, datetime] = {}
        self._market_config: object = SimpleNamespace(
            assets=("BTC",), timeframes=("5m",)
        )
        self._spot_data_source: str = "none"
        self._subscription_state = MarketSubscriptionState()
        self._subscription_assets = frozenset({"BTC"})
        self._subscription_timeframes = frozenset({"5m"})
        self.subscribed: list[tuple[str, ...]] = []
        self.unsubscribed: list[tuple[str, ...]] = []

    def _note_runtime_progress(self, phase: str) -> None:
        del phase

    def _require_registry(self) -> MarketCatalog:
        if self.registry is None:
            raise RuntimeError("registry unavailable")
        return self.registry

    def _require_assembler(self) -> object:
        return self.assembler

    def _subscribe_market_conditions(self, condition_ids: Sequence[str]) -> None:
        self.subscribed.append(tuple(condition_ids))

    def _unsubscribe_market_conditions(self, condition_ids: Sequence[str]) -> None:
        self.unsubscribed.append(tuple(condition_ids))

    def _unsubscribe_all_market_instruments(self) -> None:
        return None

    def subscribe_data(self, data_type: object, client_id: object | None = None) -> None:
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
        del condition_id, trading_state


def test_mixed_universe_is_scoped_to_strategy_assets_and_timeframes() -> None:
    registry = MarketCatalog(instrument_id_resolver=lambda condition, token: f"{condition}-{token}")
    for pair in (
        _pair("btc-5m", "BTC", "5m"),
        _pair("btc-15m", "BTC", "15m"),
        _pair("eth-5m", "ETH", "5m"),
    ):
        registry.register(pair)
    strategy = _UniverseStrategy(registry)

    handle_market_universe(
        strategy,  # pyright: ignore[reportArgumentType]
        _universe(epoch=1, active=("btc-5m", "btc-15m", "eth-5m")),
    )

    assert strategy._active_condition_ids == {"btc-5m", "btc-15m"}
    assert strategy.subscribed == [("btc-15m", "btc-5m")]


def test_unrelated_market_exit_does_not_change_strategy_state() -> None:
    registry = MarketCatalog(instrument_id_resolver=lambda condition, token: f"{condition}-{token}")
    registry.register(_pair("btc-5m", "BTC", "5m"))
    registry.register(_pair("eth-5m", "ETH", "5m"))
    strategy = _UniverseStrategy(registry)
    strategy._active_condition_ids = {"btc-5m"}

    handle_market_universe(
        strategy,  # pyright: ignore[reportArgumentType]
        _universe(epoch=2, active=("btc-5m",), exited=("eth-5m",)),
    )

    assert strategy._active_condition_ids == {"btc-5m"}
    assert strategy.unsubscribed == []
    assert strategy.readiness == []


def test_universe_condition_without_scope_metadata_is_deferred() -> None:
    strategy = _UniverseStrategy(
        MarketCatalog(
            instrument_id_resolver=lambda condition, token: f"{condition}-{token}"
        )
    )

    handle_market_universe(
        strategy,  # pyright: ignore[reportArgumentType]
        _universe(epoch=3, active=("unknown",)),
    )

    assert strategy._active_condition_ids == set()


def test_start_and_stop_only_track_conditions_in_strategy_scope() -> None:
    registry = MarketCatalog(
        instrument_id_resolver=lambda condition, token: f"{condition}-{token}"
    )
    registry.register(_pair("btc-5m", "BTC", "5m"))
    registry.register(_pair("eth-5m", "ETH", "5m"))
    strategy = _LifecycleStrategy(registry)

    on_strategy_start(
        strategy,
        object(),
    )

    assert strategy._active_condition_ids == {"btc-5m"}
    assert strategy.subscribed == [("btc-5m",)]

    on_strategy_stop(strategy)

    assert strategy.unsubscribed == [("btc-5m",)]


def test_first_bilateral_book_finishes_generation_and_records_latency() -> None:
    started_at = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    owner = SimpleNamespace(_subscription_state=MarketSubscriptionState())
    begin_market_book_generation(
        owner,  # pyright: ignore[reportArgumentType]
        "btc-5m",
        now=started_at,
    )

    assert not observe_market_book_side(
        owner,  # pyright: ignore[reportArgumentType]
        "btc-5m",
        Side.UP,
        received_at=started_at + timedelta(milliseconds=125),
        book_at=started_at + timedelta(milliseconds=100),
    )
    assert observe_market_book_side(
        owner,  # pyright: ignore[reportArgumentType]
        "btc-5m",
        Side.DOWN,
        received_at=started_at + timedelta(milliseconds=250),
        book_at=started_at + timedelta(milliseconds=200),
    )

    state = owner._subscription_state
    assert "btc-5m" not in state.awaiting_book_sides_by_condition
    assert "btc-5m" not in state.book_generation_started_at_by_condition
    assert state.first_bilateral_book_latency_ms_by_condition["btc-5m"] == 250


def test_readiness_detail_reports_intent_and_generation_age() -> None:
    now = datetime(2026, 7, 31, 12, 0, 2, tzinfo=UTC)
    registry = MarketCatalog(instrument_id_resolver=lambda condition, token: f"{condition}-{token}")
    registry.register(_pair("btc-5m", "BTC", "5m"))
    state = MarketSubscriptionState(
        subscribe_intent_condition_ids={"btc-5m"},
        subscribe_intent_started_at_by_condition={
            "btc-5m": now - timedelta(seconds=3)
        },
    )
    owner = SimpleNamespace(
        _subscription_state=state,
        registry=registry,
        _stale_orderbook_recovery_by_condition={},
        _require_registry=lambda: registry,
    )
    begin_market_book_generation(
        owner,  # pyright: ignore[reportArgumentType]
        "btc-5m",
        now=now - timedelta(seconds=2),
    )

    detail = readiness_detail(
        owner,  # pyright: ignore[reportArgumentType]
        "btc-5m",
        now=now,
    )

    assert detail["subscribe_intent_age_ms"] == 3000
    assert detail["generation_age_ms"] == 2000
    assert detail["first_bilateral_book_latency_ms"] is None
    assert detail["awaiting_book_sides"] == ["DOWN", "UP"]
