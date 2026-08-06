"""PR #64 app-side readiness/liveness split: quiet books, never-READY, feed_resumed."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from polysignal_lab.alpha.types import (
    AlphaDecision,
    FreshnessView,
    MarketView,
    SideBookView,
    SpotView,
)
from polysignal_lab.config import BinanceDataConfig, PolymarketDataConfig, SignalConfig
from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicy
from polysignal_lab.nautilus_runtime.market_catalog import (
    InstrumentTokenMeta,
    MarketCatalog,
    MarketPairMeta,
)
from polysignal_lab.nautilus_runtime.strategy.lifecycle import on_evaluation_heartbeat
from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
    ConditionSubscriptionPhase,
    MarketSubscriptionState,
    _BOOK_GENERATION_STALL_SEC,
    begin_market_book_generation,
    observe_market_book_side,
)
from polysignal_lab.observability.runtime_health import (
    evaluate_liveness,
    read_runtime_heartbeat,
    write_runtime_heartbeat,
)
from polysignal_lab.pretrade.gate import SignalGate


T0 = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
READINESS_MISS_SEC = 300
DATA_STARVATION_SEC = 900


def _gate(
    *,
    max_book_staleness_ms: int = 60_000,
    max_book_readiness_staleness_ms: int = 180_000,
) -> SignalGate:
    return SignalGate(
        SignalConfig(dedupe_enabled=False),
        PolymarketDataConfig(
            max_book_staleness_ms=max_book_staleness_ms,
            max_book_readiness_staleness_ms=max_book_readiness_staleness_ms,
        ),
        BinanceDataConfig(max_price_staleness_ms=60_000),
    )


def _pair(condition_id: str) -> MarketPairMeta:
    return MarketPairMeta(
        market_id=f"market-{condition_id}",
        market_slug=f"btc-updown-5m-{condition_id}",
        condition_id=condition_id,
        asset="BTC",
        timeframe="5m",
        start_ts=None,
        end_ts=None,
        up=InstrumentTokenMeta(f"{condition_id}-up", Side.UP),
        down=InstrumentTokenMeta(f"{condition_id}-down", Side.DOWN),
    )


def _registry(*condition_ids: str) -> MarketCatalog:
    registry = MarketCatalog(
        instrument_id_resolver=lambda _condition, token: f"{token}.POLYMARKET"
    )
    for condition_id in condition_ids:
        registry.register(_pair(condition_id))
    return registry


def _tradable_quiet_view(*, freshness_ms: int) -> MarketView:
    now = datetime.now(UTC)
    return MarketView(
        view_id="view-quiet",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        asset="BTC",
        timeframe="5m",
        start_ts=None,
        end_ts=None,
        created_at=now,
        seconds_to_close=60,
        up=SideBookView(
            token_id="up-token",
            best_bid=0.49,
            best_ask=0.51,
            spread=0.02,
            freshness_ms=freshness_ms,
            ask_levels=((0.51, 10.0),),
        ),
        down=SideBookView(
            token_id="down-token",
            best_bid=0.48,
            best_ask=0.52,
            spread=0.04,
            freshness_ms=freshness_ms,
            ask_levels=((0.52, 10.0),),
        ),
        spot=SpotView(
            asset="BTC",
            symbol="BTCUSD",
            price=100_000.0,
            source="test",
            freshness_ms=10,
        ),
        price_to_beat=None,
        up_trades=(),
        down_trades=(),
        metrics={},
        freshness=FreshnessView(
            up_book_ms=freshness_ms,
            down_book_ms=freshness_ms,
            spot_ms=10,
            max_ms=freshness_ms,
        ),
    )


def _registered_catalog_for_view(view: MarketView) -> MarketCatalog:
    registry = MarketCatalog(
        instrument_id_resolver=lambda _condition, token: f"{token}.POLYMARKET"
    )
    registry.register(
        MarketPairMeta(
            market_id=view.market_id,
            market_slug=view.market_slug,
            condition_id=view.condition_id,
            asset=view.asset,
            timeframe=view.timeframe,
            start_ts=view.start_ts,
            end_ts=view.end_ts,
            up=InstrumentTokenMeta(view.up.token_id, Side.UP),
            down=InstrumentTokenMeta(view.down.token_id, Side.DOWN),
        )
    )
    return registry


class _QuietCore:
    def __init__(self) -> None:
        self.calls: list[MarketView] = []

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        self.calls.append(view)
        return []


class _FakeAssembler:
    def __init__(self, view: MarketView) -> None:
        self.view = view

    def build(
        self, condition_id: str, *, created_at: datetime | None = None
    ) -> MarketView:
        del condition_id, created_at
        return self.view


class _Clock:
    def __init__(self, now_ns: int) -> None:
        self.now_ns = now_ns

    def timestamp_ns(self) -> int:
        return self.now_ns

    def set_timer(self, name: object, interval: object, *, callback: object) -> None:
        del name, interval, callback

    def cancel_timer(self, name: object) -> None:
        del name


class _ResubscribeStrategy:
    def __init__(self, registry: MarketCatalog, *, now: datetime) -> None:
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
        self.refreshed_instruments: list[str] = []
        self.snapshot_requests: list[str] = []
        self.snapshot_request_params: list[Mapping[str, object] | None] = []
        self.readiness: list[tuple[str, bool]] = []
        self.clock = _Clock(int(now.timestamp() * 1_000_000_000))
        self.trader_id = object()
        self.strategy_name = "ptb_diff"
        self._execution_mode = "live"
        self._evaluation_heartbeat_started = True
        self._subscriptions_started = True
        self._last_market_data_evaluation_at: dict[str, datetime] = {}
        self._market_config: object = SimpleNamespace(timeframes=("5m",))
        self._spot_data_source: str = "none"
        self._runtime_log_directory: str | None = None
        self._feed_resume_log_cursor: object | None = None
        self.assembler = object()
        self.evaluated: list[str] = []

    def _readiness_detail(
        self, condition_id: str, *, now: datetime
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
        if condition_id in self._active_condition_ids:
            self.evaluated.append(condition_id)

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

    def refresh_book_subscription(
        self,
        instrument_id: object,
        client_id: object | None = None,
        params: Mapping[str, object] | None = None,
    ) -> None:
        del client_id, params
        self.refreshed_instruments.append(str(instrument_id))

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


def _stale_ready_state(
    strategy: _ResubscribeStrategy,
    condition_id: str,
    *,
    now: datetime,
    stalled_sec: float,
) -> None:
    state = strategy._subscription_state
    state.condition_phases[condition_id] = ConditionSubscriptionPhase.READY
    state.first_bilateral_book_at_by_condition[condition_id] = now - timedelta(
        minutes=10
    )
    state.first_bilateral_book_ever_at_by_condition[condition_id] = now - timedelta(
        minutes=10
    )
    strategy._stale_orderbook_recovery_by_condition[condition_id] = {
        Side.UP: 180_000.0,
        Side.DOWN: 180_000.0,
    }
    started_at = now - timedelta(seconds=stalled_sec)
    state.book_stalled_started_at_by_condition[condition_id] = started_at
    state.book_generation_started_at_by_condition[condition_id] = started_at


def _never_ready_detail() -> dict[str, object]:
    return {
        "asset": "BTC",
        "subscription_state": "awaiting_first_book",
        "first_bilateral_book_ever_at": None,
        "last_book_at_by_side": {"UP": None, "DOWN": None},
    }


def _once_ready_detail(*, ever_at: datetime, book_at: datetime | None) -> dict[str, object]:
    stamp = None if book_at is None else book_at.isoformat()
    return {
        "asset": "BTC",
        "subscription_state": "stale_orderbook",
        "first_bilateral_book_ever_at": ever_at.isoformat(),
        "last_book_at_by_side": {"UP": stamp, "DOWN": stamp},
    }


def test_decision_policy_splits_readiness_and_trade_staleness_thresholds() -> None:
    policy = DecisionPolicy(gate=_gate())

    assert policy.orderbook_trade_threshold_ms("ptb_diff") == 60_000.0
    assert policy.orderbook_readiness_threshold_ms() == 180_000.0


def test_once_ready_quiet_book_skips_trade_without_readiness_miss_or_wire_refresh() -> (
    None
):
    """Quiet once-READY book >60s and <readiness threshold: trade stale only."""
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    quiet = _tradable_quiet_view(freshness_ms=90_000)
    core = _QuietCore()
    statuses: list[dict[str, object]] = []

    class _Strategy(PolySignalNativeStrategy):
        @property
        def clock(self) -> _Clock:
            return self._test_clock

        def __init__(self, **kwargs: Any) -> None:  # pyright: ignore[reportInconsistentConstructor]
            super().__init__(**kwargs)
            self._test_clock = _Clock(int(T0.timestamp() * 1_000_000_000))

    strategy = _Strategy(
        core=cast(Any, core),
        assembler=cast(Any, _FakeAssembler(quiet)),
        condition_ids=(quiet.condition_id,),
        strategy_name="ptb_diff",
        observability=cast(
            Any,
            SimpleNamespace(
                record_strategy_status=lambda **status: statuses.append(status),
                record_strategy_status_value=lambda **status: statuses.append(status),
            ),
        ),
        registry=_registered_catalog_for_view(quiet),
        policy=DecisionPolicy(gate=_gate()),
    )
    now = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    begin_market_book_generation(strategy, quiet.condition_id, now=now)
    observe_market_book_side(
        strategy, quiet.condition_id, Side.UP, received_at=now, book_at=now
    )
    observe_market_book_side(
        strategy, quiet.condition_id, Side.DOWN, received_at=now, book_at=now
    )

    strategy.evaluate_condition(quiet.condition_id)

    assert quiet.condition_id not in strategy._runtime_readiness_miss_condition_ids
    assert quiet.condition_id not in strategy._stale_orderbook_recovery_by_condition
    assert core.calls == []

    strategy._active_condition_ids = {quiet.condition_id}
    hb = _ResubscribeStrategy(_registry(quiet.condition_id), now=T0)
    hb._active_condition_ids = {quiet.condition_id}
    hb._subscription_state = strategy._subscription_state
    hb._stale_orderbook_recovery_by_condition = (
        strategy._stale_orderbook_recovery_by_condition
    )
    on_evaluation_heartbeat(hb, object())  # pyright: ignore[reportArgumentType]
    assert hb.refreshed_instruments == []


def test_never_ready_awaiting_first_book_does_not_trip_readiness_miss_liveness(
    tmp_path: Path,
) -> None:
    path = tmp_path / "hb.json"
    write_runtime_heartbeat(
        path,
        phase="readiness_ok",
        readiness_key="flowing",
        readiness_ok=True,
        readiness_detail={
            "subscription_state": "ready",
            "first_bilateral_book_ever_at": T0.isoformat(),
            "last_book_at_by_side": {"UP": T0.isoformat(), "DOWN": T0.isoformat()},
        },
        now=T0,
    )
    miss_started = T0 + timedelta(seconds=1)
    for offset in (1, 301):
        write_runtime_heartbeat(
            path,
            phase="readiness_miss",
            readiness_key="warmup",
            readiness_ok=False,
            readiness_detail=_never_ready_detail(),
            now=miss_started + timedelta(seconds=offset - 1),
        )

    heartbeat = read_runtime_heartbeat(path)
    assert "warmup" in heartbeat.readiness_detail_by_key
    assert heartbeat.readiness_detail_by_key["warmup"]["subscription_state"] == (
        "awaiting_first_book"
    )
    assert "warmup" not in heartbeat.readiness_miss_started_at_by_key

    observed = miss_started + timedelta(seconds=301)
    result = evaluate_liveness(
        path,
        max_age_sec=120,
        startup_started_at=T0 - timedelta(hours=1),
        startup_grace_sec=180,
        max_readiness_miss_sec=READINESS_MISS_SEC,
        max_data_starvation_sec=DATA_STARVATION_SEC,
        now=observed,
    )
    assert result.ok is True
    assert result.reason is None
    assert "warmup" in result.readiness_detail_by_key

    starved_at = T0 + timedelta(seconds=DATA_STARVATION_SEC + 1)
    write_runtime_heartbeat(
        path,
        phase="evaluation_heartbeat",
        now=starved_at,
    )
    starved = evaluate_liveness(
        path,
        max_age_sec=120,
        startup_started_at=T0 - timedelta(hours=1),
        startup_grace_sec=180,
        max_readiness_miss_sec=READINESS_MISS_SEC,
        max_data_starvation_sec=DATA_STARVATION_SEC,
        now=starved_at + timedelta(seconds=1),
    )
    assert starved.ok is False
    assert starved.reason == "data_starvation"


def test_once_ready_miss_still_trips_readiness_liveness(tmp_path: Path) -> None:
    path = tmp_path / "hb.json"
    ever_at = T0 - timedelta(minutes=30)
    write_runtime_heartbeat(
        path,
        phase="readiness_miss",
        readiness_key="btc-5m",
        readiness_ok=False,
        readiness_detail=_once_ready_detail(ever_at=ever_at, book_at=T0),
        now=T0,
    )
    # Keep the heartbeat fresh while the miss clock ages past the threshold.
    observed = T0 + timedelta(seconds=READINESS_MISS_SEC + 1)
    write_runtime_heartbeat(
        path,
        phase="readiness_miss",
        readiness_key="btc-5m",
        readiness_ok=False,
        readiness_detail=_once_ready_detail(ever_at=ever_at, book_at=T0),
        now=observed,
    )
    result = evaluate_liveness(
        path,
        max_age_sec=120,
        startup_started_at=T0 - timedelta(hours=1),
        startup_grace_sec=180,
        max_readiness_miss_sec=READINESS_MISS_SEC,
        max_data_starvation_sec=DATA_STARVATION_SEC,
        now=observed,
    )
    assert result.ok is False
    assert result.reason == "readiness_miss"


def test_feed_resumed_clears_global_epoch_and_allows_one_new_refresh_batch() -> None:
    from polysignal_lab.nautilus_runtime.strategy.lifecycle import note_feed_resumed

    registry = _registry("btc-5m", "eth-5m")
    now = T0
    strategy = _ResubscribeStrategy(registry, now=now)
    strategy._active_condition_ids = {"btc-5m", "eth-5m"}
    for condition_id in ("btc-5m", "eth-5m"):
        _stale_ready_state(
            strategy,
            condition_id,
            now=now,
            stalled_sec=_BOOK_GENERATION_STALL_SEC + 10,
        )

    on_evaluation_heartbeat(strategy, object())  # pyright: ignore[reportArgumentType]
    state = strategy._subscription_state
    assert state.global_book_recovery_epoch_at == now
    assert len(strategy.refreshed_instruments) == 4

    strategy.clock.now_ns += int((_BOOK_GENERATION_STALL_SEC + 1) * 1_000_000_000)
    on_evaluation_heartbeat(strategy, object())  # pyright: ignore[reportArgumentType]
    assert len(strategy.refreshed_instruments) == 4
    assert state.global_book_recovery_epoch_at == now

    note_feed_resumed(strategy)  # pyright: ignore[reportArgumentType]
    assert state.global_book_recovery_epoch_at is None

    resumed_at = now + timedelta(seconds=_BOOK_GENERATION_STALL_SEC + 2)
    strategy.clock.now_ns = int(resumed_at.timestamp() * 1_000_000_000)
    for condition_id in ("btc-5m", "eth-5m"):
        _stale_ready_state(
            strategy,
            condition_id,
            now=resumed_at,
            stalled_sec=_BOOK_GENERATION_STALL_SEC + 10,
        )
    on_evaluation_heartbeat(strategy, object())  # pyright: ignore[reportArgumentType]

    assert len(strategy.refreshed_instruments) == 8
    assert state.global_book_recovery_epoch_at == resumed_at

    strategy.clock.now_ns += int((_BOOK_GENERATION_STALL_SEC + 1) * 1_000_000_000)
    on_evaluation_heartbeat(strategy, object())  # pyright: ignore[reportArgumentType]
    assert len(strategy.refreshed_instruments) == 8
    assert state.global_book_recovery_epoch_at == resumed_at


def test_feed_resumed_jsonl_bridge_clears_epoch_and_allows_next_recovery_batch(
    tmp_path: Path,
) -> None:
    """Real adapter signal today is JSONL `feed_resumed`; heartbeat must bridge it."""
    import json

    from polysignal_lab.nautilus_runtime.strategy.feed_resume_bridge import (
        FeedResumeLogCursor,
    )

    log_dir = tmp_path / "runtime"
    log_dir.mkdir()
    log_path = log_dir / (
        "PolySignal-Nautilus-001_2026-08-06_000000-000_"
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.jsonl"
    )
    log_path.write_text("", encoding="utf-8")

    registry = _registry("btc-5m", "eth-5m")
    now = T0
    strategy = _ResubscribeStrategy(registry, now=now)
    strategy._runtime_log_directory = str(log_dir)
    strategy._feed_resume_log_cursor = FeedResumeLogCursor.starting_at_end(log_dir)
    strategy._active_condition_ids = {"btc-5m", "eth-5m"}
    for condition_id in ("btc-5m", "eth-5m"):
        _stale_ready_state(
            strategy,
            condition_id,
            now=now,
            stalled_sec=_BOOK_GENERATION_STALL_SEC + 10,
        )

    on_evaluation_heartbeat(strategy, object())  # pyright: ignore[reportArgumentType]
    state = strategy._subscription_state
    assert state.global_book_recovery_epoch_at == now
    assert len(strategy.refreshed_instruments) == 4

    strategy.clock.now_ns += int((_BOOK_GENERATION_STALL_SEC + 1) * 1_000_000_000)
    on_evaluation_heartbeat(strategy, object())  # pyright: ignore[reportArgumentType]
    assert len(strategy.refreshed_instruments) == 4
    assert state.global_book_recovery_epoch_at == now

    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "timestamp": "2026-08-06T05:29:00.643212676Z",
                    "trader_id": "PolySignal-Nautilus-001",
                    "level": "INFO",
                    "color": "NORMAL",
                    "component": "nautilus_polymarket::websocket::handler",
                    "message": (
                        "feed_resumed shard_id=2 channel=Market connection_epoch=25"
                    ),
                }
            )
            + "\n"
        )

    resumed_at = now + timedelta(seconds=_BOOK_GENERATION_STALL_SEC + 2)
    strategy.clock.now_ns = int(resumed_at.timestamp() * 1_000_000_000)
    for condition_id in ("btc-5m", "eth-5m"):
        _stale_ready_state(
            strategy,
            condition_id,
            now=resumed_at,
            stalled_sec=_BOOK_GENERATION_STALL_SEC + 10,
        )
    on_evaluation_heartbeat(strategy, object())  # pyright: ignore[reportArgumentType]

    assert state.last_observed_connection_epoch == 25
    assert len(strategy.refreshed_instruments) == 8
    assert state.global_book_recovery_epoch_at == resumed_at

    strategy.clock.now_ns += int((_BOOK_GENERATION_STALL_SEC + 1) * 1_000_000_000)
    on_evaluation_heartbeat(strategy, object())  # pyright: ignore[reportArgumentType]
    assert len(strategy.refreshed_instruments) == 8
    assert state.global_book_recovery_epoch_at == resumed_at
