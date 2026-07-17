from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from threading import Event, get_ident
from time import monotonic, sleep
from types import SimpleNamespace
from typing import Any, cast

import pytest
from nautilus_trader.core import nautilus_pyo3

from polysignal_lab.config import Settings
from polysignal_lab.data.price_to_beat_provider import PriceToBeatResult
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.domain.spot import SpotPrice
from polysignal_lab.nautilus_runtime import market_rotation
from polysignal_lab.nautilus_runtime.custom_data_types import (
    PolySignalMarketMetaData,
    PolySignalMarketUniverseData,
    PolySignalPriceToBeatData,
    custom_data_type,
    unwrap_custom_data,
)
from polysignal_lab.nautilus_runtime.market_discovery_worker import (
    MarketDiscoveryResult,
    MarketDiscoveryWorker,
)
from polysignal_lab.nautilus_runtime.market_rotation import (
    REFRESH_POLL_INTERVAL,
    REFRESH_TIMER_NAME,
    MarketRotationActor,
)
from polysignal_lab.nautilus_runtime.spot_anchor_state import SpotAnchorState


def _market(condition_id: str, *, asset: str = "BTC", timeframe: str = "5m") -> Market:
    return Market(
        market_id=condition_id,
        market_slug=f"{asset.lower()}-updown-{timeframe}-{condition_id}",
        condition_id=condition_id,
        asset=asset,
        timeframe=timeframe,
        start_ts=datetime(2026, 6, 28, tzinfo=UTC),
        end_ts=datetime(2026, 6, 28, tzinfo=UTC) + timedelta(minutes=5),
        outcome_tokens=[
            OutcomeToken(
                token_id=f"{condition_id}-up",
                side=Side.UP,
                outcome_name="Up",
                market_id=condition_id,
            ),
            OutcomeToken(
                token_id=f"{condition_id}-down",
                side=Side.DOWN,
                outcome_name="Down",
                market_id=condition_id,
            ),
        ],
    )


@pytest.fixture(autouse=True)
def _install_fake_polymarket_id_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "nautilus_trader.adapters.polymarket",
        SimpleNamespace(
            get_polymarket_instrument_id=lambda condition_id, token_id: (
                f"{condition_id}-{token_id}.POLYMARKET"
            ),
        ),
    )


class _HealthRecorder:
    def __init__(self) -> None:
        self.ok: list[tuple[str, dict[str, object]]] = []
        self.down: list[tuple[str, str | None, dict[str, object]]] = []
        self.degraded: list[tuple[str, str | None, dict[str, object]]] = []

    def mark_ok(self, name: str, **metrics: object) -> None:
        self.ok.append((name, metrics))

    def mark_degraded(
        self,
        name: str,
        error: str | None = None,
        **metrics: object,
    ) -> None:
        self.degraded.append((name, error, metrics))

    def mark_down(
        self,
        name: str,
        error: str | None = None,
        **metrics: object,
    ) -> None:
        self.down.append((name, error, metrics))


class _StubDiscoveryWorker:
    def __init__(
        self,
        *,
        result: MarketDiscoveryResult | None = None,
        request_result: bool = True,
    ) -> None:
        self.result = result
        self.request_result = request_result
        self.requests: list[int] = []
        self.closed = False

    def request(self, epoch: int) -> bool:
        self.requests.append(epoch)
        return self.request_result

    def take_result(self) -> MarketDiscoveryResult | None:
        result = self.result
        self.result = None
        return result

    def close(self) -> None:
        self.closed = True


def _rotation_actor(
    *,
    discovery_worker: _StubDiscoveryWorker,
    startup_markets: tuple[Market, ...] = (),
    health: _HealthRecorder | None = None,
    settings: Settings | None = None,
) -> MarketRotationActor:
    resolved = settings or Settings()
    resolved.runtime.nautilus.spot_data.source = "disabled"
    if settings is None:
        resolved.runtime.nautilus.market_rotation.enabled = False
    return MarketRotationActor(
        settings=resolved,
        startup_markets=startup_markets,
        discovery_worker=cast(Any, discovery_worker),
        anchor_store=None,
        health=health,
    )


def _take_worker_result(worker: MarketDiscoveryWorker) -> MarketDiscoveryResult:
    deadline = monotonic() + 2.0
    while monotonic() < deadline:
        result = worker.take_result()
        if result is not None:
            return result
        sleep(0.001)
    raise AssertionError("market discovery worker did not complete")


def _ptb(value: float = 100_000.0) -> PriceToBeatResult:
    return PriceToBeatResult(
        value=value,
        source="anchor",
        verified=True,
        anchor_source="chainlink",
        anchor_lag_ms=5,
        from_anchor_service=True,
    )


def test_spot_anchor_state_captures_actor_local_history_without_trading_projection() -> None:
    class _Store:
        def __init__(self) -> None:
            self.anchors: list[object] = []

        def upsert_anchor_price(self, anchor: object) -> None:
            self.anchors.append(anchor)

        def get_verified_anchor_price(
            self, _asset: str, _timeframe: str, _market_slug: str
        ) -> None:
            return None

    market = _market("condition-anchor")
    assert market.start_ts is not None
    state = SpotAnchorState(cast(Any, _Store()))
    state.update(
        SpotPrice(
            asset="BTC",
            symbol="BTCUSD",
            price=100_000.0,
            source="polymarket_rtds",
            event_time=market.start_ts,
            received_at=market.start_ts,
        )
    )

    anchor = state.capture_for_market(market)

    assert anchor is not None
    assert getattr(anchor, "price") == 100_000.0
    assert getattr(anchor, "verified") is True


def test_market_universe_data_round_trips_and_is_immutable() -> None:
    payload = PolySignalMarketUniverseData(
        epoch=2,
        active_condition_ids=("c1", "c2"),
        entered_condition_ids=("c2",),
        exited_condition_ids=("c0",),
        condition_to_up_token={"c1": "up-1", "c2": "up-2"},
        condition_to_down_token={"c1": "down-1", "c2": "down-2"},
        condition_to_asset={"c1": "BTC", "c2": "ETH"},
        condition_to_timeframe={"c1": "5m", "c2": "15m"},
        ts_event=11,
        ts_init=12,
    )

    restored = PolySignalMarketUniverseData.from_dict(payload.to_dict())

    assert restored == payload
    assert restored.condition_to_up_token["c2"] == "up-2"
    with pytest.raises(AttributeError, match="immutable"):
        payload.active_condition_ids = ("c3",)  # type: ignore[misc]
    with pytest.raises(TypeError):
        cast(dict[str, str], cast(object, payload.condition_to_up_token))["c3"] = "up-3"


def test_market_metadata_is_immutable() -> None:
    payload = PolySignalMarketMetaData(
        market_id="market-1",
        market_slug="btc-updown-5m-market-1",
        condition_id="condition-1",
        asset="BTC",
        timeframe="5m",
        start_ts_ns=1,
        end_ts_ns=2,
        up_token_id="up-1",
        down_token_id="down-1",
        ts_event=11,
        ts_init=12,
    )

    with pytest.raises(AttributeError, match="immutable"):
        payload.asset = "ETH"  # type: ignore[misc]


def test_market_rotation_actor_is_sole_writer_and_publishes_pyo3_custom_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market_a = _market("condition-a")
    market_b = _market("condition-b")
    worker = _StubDiscoveryWorker(
        result=MarketDiscoveryResult(epoch=2, markets=(market_a, market_b)),
    )
    health = _HealthRecorder()
    actor = _rotation_actor(
        discovery_worker=worker,
        startup_markets=(market_a,),
        health=health,
    )
    published: list[tuple[object, object]] = []
    actor.publish_data = lambda data_type, data: published.append((data_type, data))
    monkeypatch.setattr(actor.ptb_provider, "get_sync", lambda _market: _ptb())

    actor.on_start()
    actor._on_refresh_timer()

    assert actor.active_markets() == (market_a, market_b)
    assert actor._epoch == 2
    assert worker.requests == [3]
    assert published
    assert all(isinstance(envelope, nautilus_pyo3.CustomData) for _, envelope in published)
    payloads = [unwrap_custom_data(envelope) for _, envelope in published]
    universes = [item for item in payloads if isinstance(item, PolySignalMarketUniverseData)]
    metadata = [item for item in payloads if isinstance(item, PolySignalMarketMetaData)]
    ptbs = [item for item in payloads if isinstance(item, PolySignalPriceToBeatData)]
    assert universes[-1].entered_condition_ids == ("condition-b",)
    assert {item.condition_id for item in metadata} == {"condition-a", "condition-b"}
    assert {item.condition_id for item in ptbs} == {"condition-a", "condition-b"}
    assert published[-1][0] == custom_data_type(type(payloads[-1]))
    assert not hasattr(actor, "market_universe")
    assert not hasattr(actor, "catalog")
    assert health.ok[-1][1]["phase"] == "refresh"


def test_market_rotation_applies_worker_result_on_actor_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _StubDiscoveryWorker(
        result=MarketDiscoveryResult(epoch=2, markets=(_market("condition-b"),)),
    )
    actor = _rotation_actor(
        discovery_worker=worker,
        startup_markets=(_market("condition-a"),),
    )
    actor_thread = get_ident()
    publication_threads: list[int] = []
    actor.publish_data = lambda data_type, data: publication_threads.append(get_ident())
    monkeypatch.setattr(actor, "_publish_price_to_beat_batch_sync", lambda _markets: None)

    actor._on_refresh_timer()

    assert actor.active_markets() == (_market("condition-b"),)
    assert publication_threads
    assert set(publication_threads) == {actor_thread}


def test_market_rotation_publish_failure_keeps_last_good_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market_a = _market("condition-a")
    market_b = _market("condition-b")
    health = _HealthRecorder()
    actor = _rotation_actor(
        discovery_worker=_StubDiscoveryWorker(
            result=MarketDiscoveryResult(epoch=2, markets=(market_a, market_b)),
        ),
        startup_markets=(market_a,),
        health=health,
    )
    monkeypatch.setattr(actor.ptb_provider, "get_sync", lambda _market: _ptb())
    actor.publish_data = lambda data_type, data: None
    actor.on_start()

    def fail_changed_universe(data_type: object, data: object) -> None:
        _ = data_type
        payload = unwrap_custom_data(data)
        if (
            isinstance(payload, PolySignalMarketUniverseData)
            and payload.active_condition_ids == ("condition-a", "condition-b")
        ):
            raise RuntimeError("universe publish failed")

    actor.publish_data = fail_changed_universe
    actor._on_refresh_timer()

    assert actor.active_markets() == (market_a,)
    assert actor._epoch == 1
    assert health.down[-1][2]["phase"] == "refresh_apply"


def test_market_rotation_error_result_preserves_state_and_degrades_health() -> None:
    market = _market("condition-a")
    health = _HealthRecorder()
    actor = _rotation_actor(
        discovery_worker=_StubDiscoveryWorker(
            result=MarketDiscoveryResult(
                epoch=2,
                markets=(),
                error="RuntimeError: gamma unavailable",
            ),
        ),
        startup_markets=(market,),
        health=health,
    )
    published: list[object] = []
    actor.publish_data = lambda _data_type, data: published.append(data)

    actor._on_refresh_timer()

    assert actor.active_markets() == (market,)
    assert published == []
    assert health.degraded[-1][1] == "RuntimeError: gamma unavailable"


def test_market_rotation_timer_only_requests_worker() -> None:
    calls: list[str] = []

    class FakeWorker:
        def request(self, epoch: int) -> bool:
            calls.append(f"request:{epoch}")
            return True

        def take_result(self) -> None:
            return None

        def close(self) -> None:
            calls.append("close")

    actor = MarketRotationActor(
        settings=Settings(),
        discovery_worker=cast(Any, FakeWorker()),
    )

    actor._on_refresh_timer()

    assert calls == ["request:1"]


def test_market_rotation_on_start_uses_actor_clock_and_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "disabled"
    settings.runtime.nautilus.market_rotation.enabled = True
    worker = _StubDiscoveryWorker()
    actor = _rotation_actor(discovery_worker=worker, settings=settings)
    scheduled: list[tuple[str, timedelta, object]] = []
    fake_clock = SimpleNamespace(
        timestamp_ns=lambda: 1_782_144_000_000_000_000,
        set_timer=lambda name, interval, callback: scheduled.append(
            (name, interval, callback)
        ),
    )
    monkeypatch.setattr(
        MarketRotationActor,
        "clock",
        property(lambda _self: fake_clock),
    )
    actor.publish_data = lambda data_type, data: None
    monkeypatch.setattr(
        actor.ptb_provider,
        "get_sync",
        lambda _market: PriceToBeatResult(
            value=None,
            source="unavailable",
            verified=False,
        ),
    )

    actor.on_start()

    assert worker.requests == [2]
    assert scheduled == [(REFRESH_TIMER_NAME, REFRESH_POLL_INTERVAL, actor._on_refresh_timer)]


def test_live_discovery_worker_uses_rotation_window_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, int]] = []

    class FakeDiscovery:
        def __init__(self, *_args: object) -> None:
            return None

        def discover_sync(self, **kwargs: int) -> list[Market]:
            calls.append(kwargs)
            return [_market("condition-a")]

    settings = Settings()
    settings.runtime.nautilus.execution_mode = "sandbox"
    settings.runtime.nautilus.market_rotation.include_next_periods = 2
    settings.runtime.nautilus.market_rotation.stale_grace_sec = 7
    monkeypatch.setattr(market_rotation, "MarketDiscovery", FakeDiscovery)
    worker = market_rotation._build_discovery_worker(settings, ())
    try:
        assert worker.request(4) is True
        result = _take_worker_result(worker)
    finally:
        worker.close()

    assert result.markets == (_market("condition-a"),)
    assert calls == [{"include_next_periods": 2, "stale_grace_sec": 7}]


def test_backtest_discovery_worker_replays_only_configured_markets() -> None:
    settings = Settings()
    settings.runtime.nautilus.execution_mode = "backtest"
    market = _market("condition-a")
    worker = market_rotation._build_discovery_worker(settings, (market,))
    try:
        assert worker.request(3) is True
        result = _take_worker_result(worker)
    finally:
        worker.close()

    assert result == MarketDiscoveryResult(epoch=3, markets=(market,))


def test_market_discovery_worker_returns_immutable_tuple_result() -> None:
    market = _market("condition-a")
    source = [market]
    worker = MarketDiscoveryWorker(lambda: source)
    try:
        assert worker.request(7) is True
        result = _take_worker_result(worker)
        source.append(_market("condition-b"))
    finally:
        worker.close()

    assert result.epoch == 7
    assert result.markets == (market,)
    assert result.error is None
    with pytest.raises(AttributeError):
        setattr(result, "epoch", 8)


def test_market_discovery_worker_coalesces_requests_until_result_is_taken() -> None:
    started = Event()
    release = Event()
    transport_threads: list[int] = []

    def refresh() -> list[Market]:
        transport_threads.append(get_ident())
        started.set()
        if not release.wait(timeout=2.0):
            raise TimeoutError("test did not release discovery")
        return [_market("condition-a")]

    worker = MarketDiscoveryWorker(refresh)
    caller_thread = get_ident()
    try:
        assert worker.request(1) is True
        assert started.wait(timeout=2.0)
        assert worker.take_result() is None
        assert worker.request(2) is False
        release.set()
        assert _take_worker_result(worker).epoch == 1
        assert worker.request(2) is True
        assert _take_worker_result(worker).epoch == 2
    finally:
        release.set()
        worker.close()

    assert transport_threads[0] != caller_thread
    assert transport_threads == [transport_threads[0], transport_threads[0]]
    assert worker.request(3) is False


def test_market_discovery_worker_close_detaches_in_flight_result() -> None:
    started = Event()
    release = Event()
    finished = Event()

    def refresh() -> list[Market]:
        started.set()
        if not release.wait(timeout=2.0):
            raise TimeoutError("test did not release discovery")
        finished.set()
        return [_market("condition-a")]

    worker = MarketDiscoveryWorker(refresh)
    try:
        assert worker.request(1) is True
        assert started.wait(timeout=2.0)
        worker.close()
        assert worker.request(2) is False
        assert worker.take_result() is None
        release.set()
        assert finished.wait(timeout=2.0)
        assert worker.take_result() is None
    finally:
        release.set()
        worker.close()


def test_market_discovery_worker_returns_transport_errors() -> None:
    worker = MarketDiscoveryWorker(
        lambda: cast(list[Market], (_ for _ in ()).throw(RuntimeError("gamma unavailable")))
    )
    try:
        assert worker.request(4) is True
        result = _take_worker_result(worker)
    finally:
        worker.close()

    assert result == MarketDiscoveryResult(
        epoch=4,
        markets=(),
        error="RuntimeError: gamma unavailable",
    )


def test_market_rotation_timer_keeps_epoch_when_worker_coalesces_request() -> None:
    worker = _StubDiscoveryWorker(request_result=False)
    actor = _rotation_actor(discovery_worker=worker)

    actor._on_refresh_timer()

    assert worker.requests == [1]
    assert actor._requested_epoch == 0


def test_market_rotation_state_reload_replays_native_custom_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "disabled"
    settings.runtime.nautilus.market_rotation.enabled = False
    market = _market("condition-reload")
    actor = _rotation_actor(
        discovery_worker=_StubDiscoveryWorker(),
        startup_markets=(market,),
        settings=settings,
    )
    saved = actor.on_save()
    restored = _rotation_actor(
        discovery_worker=_StubDiscoveryWorker(),
        settings=settings,
    )
    published: list[object] = []
    restored.publish_data = lambda data_type, data: published.append(
        unwrap_custom_data(data)
    )
    monkeypatch.setattr(
        restored.ptb_provider,
        "get_sync",
        lambda _market: PriceToBeatResult(
            value=None,
            source="unavailable",
            verified=False,
        ),
    )

    restored.on_load(saved)
    restored.on_start()

    universes = [item for item in published if isinstance(item, PolySignalMarketUniverseData)]
    metadata = [item for item in published if isinstance(item, PolySignalMarketMetaData)]
    assert restored.active_markets() == (market,)
    assert universes[0].active_condition_ids == ("condition-reload",)
    assert [item.condition_id for item in metadata] == ["condition-reload"]
    assert not hasattr(restored, "markets_projection")


def test_market_rotation_on_stop_cancels_timer_and_closes_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancelled: list[str] = []
    worker = _StubDiscoveryWorker()
    actor = _rotation_actor(discovery_worker=worker)
    monkeypatch.setattr(
        MarketRotationActor,
        "clock",
        property(
            lambda _self: SimpleNamespace(
                cancel_timer=lambda name: cancelled.append(str(name)),
            )
        ),
    )

    actor.on_stop()

    assert cancelled == [REFRESH_TIMER_NAME]
    assert worker.closed is True
