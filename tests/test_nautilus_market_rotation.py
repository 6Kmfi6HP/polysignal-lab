"""
Input: __future__, __future__.annotations, asyncio, sys, collections.abc, collections.abc.Coroutine, datetime, datetime.UTC, datetime.datetime, datetime.timedelta, threading, time
Output: test_market_universe_data_round_trips, test_market_universe_data_is_immutable, test_market_metadata_is_immutable, test_market_rotation_actor_initial_publish_and_diff_executes_intercepted_ptb_coroutines, test_market_rotation_actor_refresh_publishes_changed_ptb_for_still_active_market, test_market_rotation_actor_refresh_skips_unchanged_ptb_for_still_active_market, test_market_rotation_unchanged_refresh_replays_runtime_bootstrap_data, test_market_rotation_actor_refresh_continues_after_single_market_ptb_failure, test_market_rotation_actor_refresh_checks_still_active_ptb_sequentially, test_market_rotation_actor_keeps_last_good_state_on_publish_failure, test_market_rotation_actor_refresh_timer_marks_down_refresh_failures, test_market_rotation_timer_does_not_call_discovery_inline, test_market_discovery_worker_returns_immutable_tuple_result, test_market_discovery_worker_coalesces_requests_until_result_is_taken, test_market_discovery_worker_close_detaches_in_flight_result, test_market_discovery_worker_returns_transport_errors, test_market_rotation_applies_completed_worker_result_on_actor_thread, test_market_rotation_ignores_stale_worker_result, test_market_rotation_error_result_preserves_markets_and_degrades_health, test_market_rotation_timer_keeps_epoch_when_worker_coalesces_request
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import asyncio
import sys
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from threading import Event, get_ident
from time import monotonic, sleep
from types import SimpleNamespace
from typing import Any, cast

import pytest

from polysignal_lab.app.services.market_universe_service import MarketUniverseService
from polysignal_lab.config import MarketConfig, PolymarketDataConfig, Settings
from polysignal_lab.data.polymarket_market_discovery import MarketDiscovery
from polysignal_lab.data.price_to_beat_provider import PriceToBeatResult
from polysignal_lab.data.state import MarketRegistry
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import JsonObject, Market, OutcomeToken
from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.custom_data_types import (
    PolySignalMarketMetaData,
    PolySignalMarketUniverseData,
    PolySignalPriceToBeatData,
)
from polysignal_lab.nautilus_runtime.market_discovery_worker import (
    MarketDiscoveryResult,
    MarketDiscoveryWorker,
)
from polysignal_lab.nautilus_runtime.market_rotation import MarketRotationActor


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
            OutcomeToken(token_id=f"{condition_id}-up", side=Side.UP, outcome_name="Up", market_id=condition_id),
            OutcomeToken(token_id=f"{condition_id}-down", side=Side.DOWN, outcome_name="Down", market_id=condition_id),
        ],
    )


@pytest.fixture(autouse=True)
def _install_fake_polymarket_id_helper(monkeypatch) -> None:
    def helper(condition_id: str, token_id: str) -> str:
        return f"{condition_id}-{token_id}.POLYMARKET"

    monkeypatch.setitem(
        sys.modules,
        "nautilus_trader.adapters.polymarket",
        SimpleNamespace(get_polymarket_instrument_id=helper),
    )


class _Universe:
    def __init__(self, rounds: list[list[Market] | Exception]) -> None:
        self.rounds = rounds
        self.calls = 0

    async def refresh_once(self) -> list[Market]:
        result = self.rounds[self.calls]
        self.calls += 1
        if isinstance(result, Exception):
            raise result
        return result


    def refresh_once_sync(self) -> list[Market]:
        result = self.rounds[self.calls]
        self.calls += 1
        if isinstance(result, Exception):
            raise result
        return result

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

    def mark_down(self, name: str, error: str | None = None, **metrics: object) -> None:
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
    market_universe: object | None = None,
    health: _HealthRecorder | None = None,
) -> MarketRotationActor:
    settings = Settings()
    settings.runtime.nautilus.sidecar.spot_source = "disabled"
    return MarketRotationActor(
        settings=settings,
        startup_markets=startup_markets,
        market_universe=cast(Any, market_universe or _Universe([[]])),
        catalog=MarketCatalog(),
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


class _NoopPersistence:
    def upsert_market(self, market: Market) -> None:
        _ = market

    def append_log(self, stream: str, payload: object) -> None:
        _ = stream, payload


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


class _FakeAsyncClient:
    def __init__(self, payloads: list[object]) -> None:
        self.payloads = payloads
        self.calls: list[str] = []

    async def get(
        self,
        url: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> _FakeResponse:
        _ = params, headers
        self.calls.append(url)
        payload = self.payloads[len(self.calls) - 1] if len(self.calls) <= len(self.payloads) else []
        return _FakeResponse(payload)


def _gamma_market_payload(
    *,
    slug: str,
    market_id: str,
    start: str,
    end: str,
) -> dict[str, object]:
    return {
        "id": f"event-{market_id}",
        "slug": slug,
        "ticker": slug,
        "title": "Bitcoin Up or Down",
        "active": True,
        "closed": False,
        "markets": [
            {
                "id": market_id,
                "conditionId": f"condition-{market_id}",
                "slug": slug,
                "question": "Bitcoin Up or Down",
                "active": True,
                "closed": False,
                "eventStartTime": start,
                "endDate": end,
                "outcomes": "[\"Up\", \"Down\"]",
                "clobTokenIds": "[\"token-up\", \"token-down\"]",
            }
        ],
    }


def _market_from_gamma_payload(payload: dict[str, object]) -> Market:
    event_markets = payload["markets"]
    assert isinstance(event_markets, list)
    market_payload = event_markets[0]
    assert isinstance(market_payload, dict)
    merged_payload = {**payload, **market_payload}
    return Market.from_gamma(cast(JsonObject, merged_payload), asset="BTC", timeframe="5m")


class _RecordedTask:
    def __init__(self, coro: Coroutine[Any, Any, object]) -> None:
        self.coro = coro
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


def _record_task(
    created: list[_RecordedTask],
    coro: Coroutine[Any, Any, object],
) -> _RecordedTask:
    task = _RecordedTask(coro)
    created.append(task)
    return task


def _recorded_task_name(task: _RecordedTask) -> str:
    code = getattr(task.coro, "cr_code", None)
    return "" if code is None else code.co_name


def _close_recorded_tasks(tasks: list[_RecordedTask]) -> None:
    for task in tasks:
        task.coro.close()


def test_market_universe_data_round_trips() -> None:
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

    serialized = payload.to_dict()
    restored = PolySignalMarketUniverseData.from_dict(serialized)

    assert serialized["active_condition_ids"] == ["c1", "c2"]
    assert serialized["entered_condition_ids"] == ["c2"]
    assert serialized["exited_condition_ids"] == ["c0"]
    assert restored == payload
    assert restored.active_condition_ids == ("c1", "c2")
    assert restored.condition_to_up_token["c2"] == "up-2"
    assert restored.condition_to_timeframe["c1"] == "5m"


def test_market_universe_data_is_immutable() -> None:
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

def test_market_rotation_actor_initial_publish_and_diff_executes_intercepted_ptb_coroutines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[object] = []
    created: list[_RecordedTask] = []
    settings = Settings()
    settings.runtime.nautilus.sidecar.spot_source = "disabled"
    settings.runtime.nautilus.market_rotation.enabled = False
    health = _HealthRecorder()
    universe = _Universe(
        [
            [_market("condition-a"), _market("condition-b")],
        ]
    )
    actor = MarketRotationActor(settings=settings,
    startup_markets=(_market("condition-a"),),
    market_universe=universe, catalog=MarketCatalog(), anchor_store=None,
    health=health,)
    actor.publish_data = lambda data_type, data: published.append(data)

    def fake_ptb(market: Market) -> PriceToBeatResult:
        _ = market
        return PriceToBeatResult(
            value=100000.0,
            source="anchor",
            verified=True,
            anchor_source="chainlink",
            anchor_lag_ms=5,
            from_anchor_service=True,
        )

    monkeypatch.setattr(actor.ptb_provider, "get_sync", fake_ptb)
    monkeypatch.setattr(
        "asyncio.create_task",
        lambda coro: _record_task(created, cast(Coroutine[Any, Any, object], coro)),
    )

    try:
        actor.on_start()

        assert created == []
        asyncio.run(actor.refresh_once())

        epochs = [item for item in published if isinstance(item, PolySignalMarketUniverseData)]
        metas = [item for item in published if isinstance(item, PolySignalMarketMetaData)]
        ptbs = [item for item in published if isinstance(item, PolySignalPriceToBeatData)]

        assert epochs[0].epoch == 1
        assert epochs[-1].epoch == 2
        assert epochs[-1].entered_condition_ids == ("condition-b",)
        assert epochs[-1].exited_condition_ids == ()
        assert {meta.condition_id for meta in metas} == {"condition-a", "condition-b"}
        assert {ptb.condition_id for ptb in ptbs} == {"condition-a", "condition-b"}
        assert health.ok[0] == (
            "market_rotation",
            {
                "active_count": 1,
                "entered_count": 1,
                "exited_count": 0,
                "epoch": 1,
                "phase": "startup",
            },
        )
        assert health.ok[-1] == (
            "market_rotation",
            {
                "active_count": 2,
                "entered_count": 1,
                "exited_count": 0,
                "epoch": 2,
                "phase": "refresh",
            },
        )
    finally:
        _close_recorded_tasks(created)

def test_market_rotation_actor_refresh_publishes_changed_ptb_for_still_active_market(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[object] = []
    created: list[_RecordedTask] = []
    settings = Settings()
    settings.runtime.nautilus.sidecar.spot_source = "disabled"
    settings.runtime.nautilus.market_rotation.enabled = False
    market = _market("condition-a")
    actor = MarketRotationActor(settings=settings,
    startup_markets=(market,),
    market_universe=_Universe([[market]]), catalog=MarketCatalog(), anchor_store=None,
    health=None,)
    actor.publish_data = lambda data_type, data: published.append(data)
    results = iter(
        (
            PriceToBeatResult(
                value=100000.0,
                source="anchor",
                verified=True,
                anchor_source="chainlink",
                anchor_lag_ms=5,
                from_anchor_service=True,
            ),
            PriceToBeatResult(
                value=100500.0,
                source="anchor",
                verified=True,
                anchor_source="chainlink",
                anchor_lag_ms=5,
                from_anchor_service=True,
            ),
        )
    )

    def fake_ptb(_market: Market) -> PriceToBeatResult:
        return next(results)

    monkeypatch.setattr(actor.ptb_provider, "get_sync", fake_ptb)
    monkeypatch.setattr(
        "asyncio.create_task",
        lambda coro: _record_task(created, cast(Coroutine[Any, Any, object], coro)),
    )

    try:
        actor.on_start()
        assert created == []
        published.clear()

        asyncio.run(actor.refresh_once())

        assert created == []
        ptbs = [item for item in published if isinstance(item, PolySignalPriceToBeatData)]
        assert [(item.condition_id, item.value) for item in ptbs] == [("condition-a", 100500.0)]
    finally:
        _close_recorded_tasks(created)


def test_market_rotation_actor_refresh_skips_unchanged_ptb_for_still_active_market(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[object] = []
    created: list[_RecordedTask] = []
    on_data_calls = 0
    settings = Settings()
    settings.runtime.nautilus.sidecar.spot_source = "disabled"
    settings.runtime.nautilus.market_rotation.enabled = False
    market = _market("condition-a")
    actor = MarketRotationActor(settings=settings,
    startup_markets=(market,),
    market_universe=_Universe([[market]]), catalog=MarketCatalog(), anchor_store=None,
    health=None,)

    def record_publish(data_type: object, data: object) -> None:
        nonlocal on_data_calls
        _ = data_type
        published.append(data)
        if isinstance(data, PolySignalPriceToBeatData):
            on_data_calls += 1

    actor.publish_data = record_publish
    results = iter(
        (
            PriceToBeatResult(
                value=100000.0,
                source="anchor",
                verified=True,
                anchor_source="chainlink",
                anchor_lag_ms=5,
                from_anchor_service=True,
            ),
            PriceToBeatResult(
                value=100000.0,
                source="anchor",
                verified=True,
                anchor_source="chainlink",
                anchor_lag_ms=5,
                from_anchor_service=True,
            ),
        )
    )

    def fake_ptb(_market: Market) -> PriceToBeatResult:
        return next(results)

    monkeypatch.setattr(actor.ptb_provider, "get_sync", fake_ptb)
    monkeypatch.setattr(
        "asyncio.create_task",
        lambda coro: _record_task(created, cast(Coroutine[Any, Any, object], coro)),
    )

    try:
        actor.on_start()
        assert created == []
        initial_publish_count = len(
            [item for item in published if isinstance(item, PolySignalPriceToBeatData)]
        )
        initial_on_data_calls = on_data_calls
        asyncio.run(actor.refresh_once())

        assert created == []
        assert len([item for item in published if isinstance(item, PolySignalPriceToBeatData)]) == (
            initial_publish_count
        )
        assert on_data_calls == initial_on_data_calls
    finally:
        _close_recorded_tasks(created)


def test_market_rotation_unchanged_refresh_replays_runtime_bootstrap_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[object] = []
    settings = Settings()
    settings.runtime.nautilus.sidecar.spot_source = "disabled"
    settings.runtime.nautilus.market_rotation.enabled = False
    market = _market("condition-a")
    actor = MarketRotationActor(
        settings=settings,
        startup_markets=(market,),
        market_universe=_Universe([[market]]),
        catalog=MarketCatalog(),
        anchor_store=None,
        health=None,
    )
    actor.publish_data = lambda _data_type, data: published.append(data)
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
    published.clear()
    asyncio.run(actor.refresh_once())

    universes = [
        item for item in published if isinstance(item, PolySignalMarketUniverseData)
    ]
    metadata = [item for item in published if isinstance(item, PolySignalMarketMetaData)]
    assert [item.epoch for item in universes] == [1]
    assert [item.condition_id for item in metadata] == ["condition-a"]


def test_market_rotation_actor_refresh_continues_after_single_market_ptb_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[object] = []
    created: list[_RecordedTask] = []
    settings = Settings()
    settings.runtime.nautilus.sidecar.spot_source = "disabled"
    settings.runtime.nautilus.market_rotation.enabled = False
    markets = (_market("condition-a"), _market("condition-b"))
    actor = MarketRotationActor(settings=settings,
    startup_markets=markets,
    market_universe=_Universe([list(markets)]), catalog=MarketCatalog(), anchor_store=None,
    health=None,)
    actor.publish_data = lambda data_type, data: published.append(data)
    calls: dict[str, int] = {}

    def fake_ptb(market: Market) -> PriceToBeatResult:
        count = calls.get(market.condition_id, 0) + 1
        calls[market.condition_id] = count
        if market.condition_id == "condition-a":
            if count == 1:
                return PriceToBeatResult(
                    value=100000.0,
                    source="anchor",
                    verified=True,
                    anchor_source="chainlink",
                    anchor_lag_ms=5,
                    from_anchor_service=True,
                )
            raise RuntimeError("PTB failed for condition-a")
        if count == 1:
            return PriceToBeatResult(
                value=200000.0,
                source="anchor",
                verified=True,
                anchor_source="chainlink",
                anchor_lag_ms=5,
                from_anchor_service=True,
            )
        return PriceToBeatResult(
            value=200500.0,
            source="anchor",
            verified=True,
            anchor_source="chainlink",
            anchor_lag_ms=5,
            from_anchor_service=True,
        )

    monkeypatch.setattr(actor.ptb_provider, "get_sync", fake_ptb)
    monkeypatch.setattr(
        "asyncio.create_task",
        lambda coro: _record_task(created, cast(Coroutine[Any, Any, object], coro)),
    )

    try:
        actor.on_start()
        assert created == []
        published.clear()

        asyncio.run(actor.refresh_once())

        assert created == []
        ptbs = [item for item in published if isinstance(item, PolySignalPriceToBeatData)]
        assert [(item.condition_id, item.value) for item in ptbs] == [("condition-b", 200500.0)]
        assert calls == {"condition-a": 2, "condition-b": 2}
    finally:
        _close_recorded_tasks(created)


def test_market_rotation_actor_refresh_checks_still_active_ptb_sequentially(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[_RecordedTask] = []
    settings = Settings()
    settings.runtime.nautilus.sidecar.spot_source = "disabled"
    settings.runtime.nautilus.market_rotation.enabled = False
    markets = (_market("condition-a"), _market("condition-b"), _market("condition-c"))
    actor = MarketRotationActor(settings=settings,
    startup_markets=markets,
    market_universe=_Universe([list(markets)]), catalog=MarketCatalog(), anchor_store=None,
    health=None,)
    in_flight = 0
    max_in_flight = 0
    calls: list[str] = []

    def fake_ptb(market: Market) -> PriceToBeatResult:
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        calls.append(market.condition_id)
        in_flight -= 1
        return PriceToBeatResult(
            value=100000.0,
            source="anchor",
            verified=True,
            anchor_source="chainlink",
            anchor_lag_ms=5,
            from_anchor_service=True,
        )

    monkeypatch.setattr(actor.ptb_provider, "get_sync", fake_ptb)
    monkeypatch.setattr(
        "asyncio.create_task",
        lambda coro: _record_task(created, cast(Coroutine[Any, Any, object], coro)),
    )
    actor.publish_data = lambda data_type, data: None

    try:
        actor.on_start()
        assert created == []
        calls.clear()
        in_flight = 0
        max_in_flight = 0

        asyncio.run(actor.refresh_once())

        assert created == []
        assert calls == ["condition-a", "condition-b", "condition-c"]
        assert max_in_flight == 1
    finally:
        _close_recorded_tasks(created)


def test_market_rotation_actor_keeps_last_good_state_on_publish_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[object] = []
    created: list[_RecordedTask] = []
    settings = Settings()
    settings.runtime.nautilus.sidecar.spot_source = "disabled"
    settings.runtime.nautilus.market_rotation.enabled = False
    universe = _Universe(
        [
            [_market("condition-a"), _market("condition-b")],
        ]
    )
    actor = MarketRotationActor(settings=settings,
    startup_markets=(_market("condition-a"),),
    market_universe=universe, catalog=MarketCatalog(), anchor_store=None,
    health=None,)
    actor.publish_data = lambda data_type, data: published.append(data)

    async def fake_none_ptb(market: Market) -> PriceToBeatResult:
        _ = market
        return PriceToBeatResult(
            value=None,
            source="gamma",
            verified=False,
            anchor_source=None,
            anchor_lag_ms=None,
            from_anchor_service=False,
        )

    monkeypatch.setattr(actor.ptb_provider, "get", fake_none_ptb)
    monkeypatch.setattr(
        "asyncio.create_task",
        lambda coro: _record_task(created, cast(Coroutine[Any, Any, object], coro)),
    )

    try:
        actor.on_start()
        first_epoch = [item for item in published if isinstance(item, PolySignalMarketUniverseData)][-1]

        def fail_on_changed_universe(data_type: object, data: object) -> None:
            _ = data_type
            if (
                isinstance(data, PolySignalMarketUniverseData)
                and data.active_condition_ids == ("condition-a", "condition-b")
            ):
                raise RuntimeError("universe publish failed")
            published.append(data)

        actor.publish_data = fail_on_changed_universe

        asyncio.run(actor._refresh_async())

        assert [market.condition_id for market in actor.active_markets()] == ["condition-a"]
        assert [item for item in published if isinstance(item, PolySignalMarketUniverseData)][-1] == first_epoch
        assert actor._epoch == first_epoch.epoch
    finally:
        _close_recorded_tasks(created)


def test_market_rotation_actor_refresh_timer_marks_down_refresh_failures() -> None:
    settings = Settings()
    settings.runtime.nautilus.sidecar.spot_source = "disabled"
    health = _HealthRecorder()
    actor = MarketRotationActor(
        settings=settings,
        startup_markets=(),
        market_universe=_Universe([RuntimeError("refresh failed")]),
        catalog=MarketCatalog(),
        anchor_store=None,
        health=health,
    )

    asyncio.run(actor._refresh_async())

    assert actor._refresh_in_flight is False
    assert health.down == [
        ("market_rotation", "refresh failed", {"epoch": 0, "phase": "refresh"}),
    ]


@pytest.mark.anyio
async def test_market_rotation_actor_refresh_preloads_next_period_via_market_universe_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polysignal_lab.data import polymarket_market_discovery as discovery_module

    published: list[object] = []
    created: list[_RecordedTask] = []
    now = datetime(2026, 6, 23, 22, 41, tzinfo=UTC)
    monkeypatch.setattr(discovery_module, "utc_now", lambda: now)
    current_payload = _gamma_market_payload(
        slug="btc-updown-5m-1782254400",
        market_id="market-current",
        start="2026-06-23T22:40:00Z",
        end="2026-06-23T22:45:00Z",
    )
    next_payload = _gamma_market_payload(
        slug="btc-updown-5m-1782254700",
        market_id="market-next",
        start="2026-06-23T22:45:00Z",
        end="2026-06-23T22:50:00Z",
    )
    client = _FakeAsyncClient([[], current_payload, next_payload])
    discovery = MarketDiscovery(
        PolymarketDataConfig(),
        MarketConfig(assets=["BTC"], timeframes=["5m"], active_only=True, closed=False),
        client=cast(Any, client),
    )
    current_market = _market_from_gamma_payload(current_payload)
    settings = Settings()
    settings.runtime.nautilus.sidecar.spot_source = "disabled"
    settings.runtime.nautilus.market_rotation.enabled = False
    settings.runtime.nautilus.market_rotation.include_next_periods = 1
    settings.runtime.nautilus.market_rotation.stale_grace_sec = 0
    actor = MarketRotationActor(settings=settings,
    startup_markets=(current_market,),
    market_universe=MarketUniverseService(
        discovery,
        MarketRegistry(),
        _NoopPersistence(),
        settings=settings,
    ), catalog=MarketCatalog(), anchor_store=None,
    health=None,)
    actor.publish_data = lambda data_type, data: published.append(data)

    async def fake_none_ptb(market: Market) -> PriceToBeatResult:
        _ = market
        return PriceToBeatResult(
            value=None,
            source="gamma",
            verified=False,
            anchor_source=None,
            anchor_lag_ms=None,
            from_anchor_service=False,
        )

    monkeypatch.setattr(actor.ptb_provider, "get", fake_none_ptb)
    monkeypatch.setattr(
        "asyncio.create_task",
        lambda coro: _record_task(created, cast(Coroutine[Any, Any, object], coro)),
    )

    try:
        actor.on_start()
        await actor.refresh_once()

        epochs = [item for item in published if isinstance(item, PolySignalMarketUniverseData)]

        assert [market.condition_id for market in actor.active_markets()] == [
            "condition-market-current",
            "condition-market-next",
        ]
        assert epochs[0].active_condition_ids == ("condition-market-current",)
        assert epochs[-1].active_condition_ids == (
            "condition-market-current",
            "condition-market-next",
        )
        assert epochs[-1].entered_condition_ids == ("condition-market-next",)
        assert epochs[-1].exited_condition_ids == ()
        assert any(url.endswith("/events/slug/btc-updown-5m-1782254400") for url in client.calls)
        assert any(url.endswith("/events/slug/btc-updown-5m-1782254700") for url in client.calls)
    finally:
        _close_recorded_tasks(created)


@pytest.mark.anyio
async def test_market_rotation_actor_refresh_applies_stale_grace_via_market_universe_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polysignal_lab.data import polymarket_market_discovery as discovery_module

    published: list[object] = []
    created: list[_RecordedTask] = []
    now = datetime(2026, 6, 23, 22, 45, 3, tzinfo=UTC)
    monkeypatch.setattr(discovery_module, "utc_now", lambda: now)
    previous_payload = _gamma_market_payload(
        slug="btc-updown-5m-1782254400",
        market_id="market-previous",
        start="2026-06-23T22:40:00Z",
        end="2026-06-23T22:45:00Z",
    )
    client = _FakeAsyncClient([[], previous_payload])
    discovery = MarketDiscovery(
        PolymarketDataConfig(),
        MarketConfig(assets=["BTC"], timeframes=["5m"], active_only=True, closed=False),
        client=cast(Any, client),
    )
    grace_market = _market_from_gamma_payload(previous_payload)
    settings = Settings()
    settings.runtime.nautilus.sidecar.spot_source = "disabled"
    settings.runtime.nautilus.market_rotation.enabled = False
    settings.runtime.nautilus.market_rotation.include_next_periods = 0
    settings.runtime.nautilus.market_rotation.stale_grace_sec = 5
    actor = MarketRotationActor(settings=settings,
    startup_markets=(grace_market,),
    market_universe=MarketUniverseService(
        discovery,
        MarketRegistry(),
        _NoopPersistence(),
        settings=settings,
    ), catalog=MarketCatalog(), anchor_store=None,
    health=None,)
    actor.publish_data = lambda data_type, data: published.append(data)

    async def fake_none_ptb(market: Market) -> PriceToBeatResult:
        _ = market
        return PriceToBeatResult(
            value=None,
            source="gamma",
            verified=False,
            anchor_source=None,
            anchor_lag_ms=None,
            from_anchor_service=False,
        )

    monkeypatch.setattr(actor.ptb_provider, "get", fake_none_ptb)
    monkeypatch.setattr(
        "asyncio.create_task",
        lambda coro: _record_task(created, cast(Coroutine[Any, Any, object], coro)),
    )

    try:
        actor.on_start()
        startup_epochs = [item for item in published if isinstance(item, PolySignalMarketUniverseData)]

        await actor.refresh_once()

        epochs = [item for item in published if isinstance(item, PolySignalMarketUniverseData)]

        assert [market.condition_id for market in actor.active_markets()] == [
            "condition-market-previous"
        ]
        assert len(startup_epochs) == 1
        assert len(epochs) == 2
        assert epochs[-1].entered_condition_ids == ()
        assert epochs[-1].exited_condition_ids == ()
        assert actor._epoch == 1
        assert any(url.endswith("/events/slug/btc-updown-5m-1782254400") for url in client.calls)
    finally:
        _close_recorded_tasks(created)



def test_market_rotation_actor_on_start_uses_clock_timer_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[_RecordedTask] = []
    scheduled: list[dict[str, object]] = []
    settings = Settings()
    settings.runtime.nautilus.sidecar.spot_source = "disabled"
    actor = MarketRotationActor(settings=settings,
    startup_markets=(),
    market_universe=_Universe([[]]), catalog=MarketCatalog(), anchor_store=None,
    health=None,)

    class FakeClock:
        def set_timer(
            self,
            name: str,
            interval: object,
            start_time: object = None,
            stop_time: object = None,
            callback: object = None,
            allow_past: bool = True,
            fire_immediately: bool = False,
        ) -> None:
            scheduled.append(
                {
                    "name": name,
                    "interval": interval,
                    "start_time": start_time,
                    "stop_time": stop_time,
                    "callback": callback,
                    "allow_past": allow_past,
                    "fire_immediately": fire_immediately,
                }
            )

    fake_clock = FakeClock()
    monkeypatch.setattr(
        MarketRotationActor,
        "clock",
        property(lambda self: fake_clock),
    )
    actor.publish_data = lambda data_type, data: None
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.market_rotation._register_polysignal_data_types_if_available",
        lambda: None,
    )
    monkeypatch.setattr(
        "asyncio.create_task",
        lambda coro: _record_task(created, cast(Coroutine[Any, Any, object], coro)),
    )

    try:
        actor.on_start()
        assert scheduled and scheduled[0]["name"] == "market_rotation_refresh"
        assert scheduled[0]["interval"] == timedelta(seconds=10)
        assert scheduled[0]["callback"] == actor._on_refresh_timer
        assert created == []
    finally:
        _close_recorded_tasks(created)


def test_market_rotation_timer_does_not_call_discovery_inline() -> None:
    calls: list[str] = []

    class BlockingUniverse:
        async def refresh_once(self) -> list[Market]:
            return []

        def refresh_once_sync(self) -> list[Market]:
            calls.append("transport")
            return []

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
        startup_markets=(),
        market_universe=BlockingUniverse(),
        catalog=MarketCatalog(),
        discovery_worker=cast(Any, FakeWorker()),
        anchor_store=None,
        health=None,
    )

    actor._on_refresh_timer(None)

    assert calls == ["request:1"]


def test_market_discovery_worker_returns_immutable_tuple_result() -> None:
    market = _market("condition-a")
    source = [market]
    worker = MarketDiscoveryWorker(lambda: source)
    try:
        assert worker.request(7) is True
        result = _take_worker_result(worker)
        source.append(_market("condition-b"))

        assert result.epoch == 7
        assert result.markets == (market,)
        assert result.error is None
        with pytest.raises(AttributeError):
            setattr(result, "epoch", 8)
    finally:
        worker.close()


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
        result = _take_worker_result(worker)
        assert result.epoch == 1
        assert worker.request(2) is True
        second_result = _take_worker_result(worker)
        assert second_result.epoch == 2
        assert transport_threads[0] != caller_thread
        assert transport_threads == [transport_threads[0], transport_threads[0]]
    finally:
        release.set()
        worker.close()

    worker.close()
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
    def fail_refresh() -> list[Market]:
        raise RuntimeError("gamma unavailable")

    worker = MarketDiscoveryWorker(fail_refresh)
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


def test_market_rotation_applies_completed_worker_result_on_actor_thread() -> None:
    market_a = _market("condition-a")
    market_b = _market("condition-b")
    worker = _StubDiscoveryWorker(
        result=MarketDiscoveryResult(epoch=2, markets=(market_b,)),
    )
    actor = _rotation_actor(
        discovery_worker=worker,
        startup_markets=(market_a,),
    )
    actor_thread = get_ident()
    publication_threads: list[int] = []
    published: list[object] = []

    def publish(_data_type: object, data: object) -> None:
        publication_threads.append(get_ident())
        published.append(data)

    actor.publish_data = publish
    cast(Any, actor)._publish_price_to_beat_batch_sync = (
        lambda _markets: publication_threads.append(get_ident())
    )

    actor._on_refresh_timer(None)

    assert actor.active_markets() == (market_b,)
    assert actor._epoch == 2
    assert worker.requests == [3]
    assert publication_threads
    assert set(publication_threads) == {actor_thread}
    assert any(isinstance(item, PolySignalMarketUniverseData) for item in published)
    assert any(isinstance(item, PolySignalMarketMetaData) for item in published)


def test_market_rotation_ignores_stale_worker_result() -> None:
    market_a = _market("condition-a")
    worker = _StubDiscoveryWorker(
        result=MarketDiscoveryResult(
            epoch=1,
            markets=(_market("condition-b"),),
        ),
    )
    actor = _rotation_actor(
        discovery_worker=worker,
        startup_markets=(market_a,),
    )
    actor._epoch = 2
    published: list[object] = []
    actor.publish_data = lambda _data_type, data: published.append(data)

    actor._on_refresh_timer(None)

    assert actor.active_markets() == (market_a,)
    assert actor._epoch == 2
    assert worker.requests == [3]
    assert published == []


def test_market_rotation_error_result_preserves_markets_and_degrades_health() -> None:
    market = _market("condition-a")
    health = _HealthRecorder()
    worker = _StubDiscoveryWorker(
        result=MarketDiscoveryResult(
            epoch=2,
            markets=(),
            error="RuntimeError: gamma unavailable",
        ),
    )
    actor = _rotation_actor(
        discovery_worker=worker,
        startup_markets=(market,),
        health=health,
    )
    published: list[object] = []
    actor.publish_data = lambda _data_type, data: published.append(data)

    actor._on_refresh_timer(None)

    assert actor.active_markets() == (market,)
    assert published == []
    assert worker.requests == [3]
    assert health.degraded == [
        (
            "market_rotation",
            "RuntimeError: gamma unavailable",
            {
                "epoch": 0,
                "phase": "market_discovery",
                "result_epoch": 2,
            },
        ),
    ]


def test_market_rotation_actor_refresh_async_clears_in_flight_after_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    actor = MarketRotationActor(
        settings=Settings(),
        startup_markets=(),
        market_universe=_Universe([[_market("condition-a")]]),
        catalog=MarketCatalog(),
        anchor_store=None,
        health=None,
    )

    def apply(markets: tuple[Market, ...]) -> tuple[Market, ...]:
        calls.append("apply")
        return markets

    def publish(markets: tuple[Market, ...]) -> None:
        calls.append("ptb")
        assert [market.condition_id for market in markets] == ["condition-a"]

    monkeypatch.setattr(actor, "_apply_refreshed_markets", apply)
    monkeypatch.setattr(actor, "_publish_price_to_beat_batch_sync", publish)

    asyncio.run(actor._refresh_async())

    assert calls == ["apply", "ptb"]
    assert actor._refresh_in_flight is False


def test_market_rotation_timer_keeps_epoch_when_worker_coalesces_request() -> None:
    universe = _Universe([[]])
    worker = _StubDiscoveryWorker(request_result=False)
    actor = _rotation_actor(
        discovery_worker=worker,
        market_universe=universe,
    )

    actor._on_refresh_timer()

    assert worker.requests == [1]
    assert actor._requested_epoch == 0
    assert universe.calls == 0


def test_market_universe_service_refresh_once_sync_uses_sync_discovery_and_closes_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _gamma_market_payload(
        slug="btc-updown-5m-1782254400",
        market_id="market-current",
        start="2026-06-23T22:40:00Z",
        end="2026-06-23T22:45:00Z",
    )
    clients: list[FakeSyncClient] = []

    class FakeSyncClient:
        def __init__(self, *, timeout: float) -> None:
            _ = timeout
            self.calls: list[str] = []
            self.closed = False
            clients.append(self)

        def __enter__(self) -> FakeSyncClient:
            return self

        def __exit__(self, *exc_info: object) -> None:
            self.closed = True

        def get(self, url: str, params: object | None = None) -> _FakeResponse:
            _ = params
            self.calls.append(url)
            return _FakeResponse(payload if len(self.calls) == 1 else [])

    monkeypatch.setattr("httpx.Client", FakeSyncClient)
    discovery = MarketDiscovery(
        PolymarketDataConfig(),
        MarketConfig(assets=["BTC"], timeframes=["5m"], active_only=False, closed=False),
        client=cast(Any, _FakeAsyncClient([])),
    )
    settings = Settings()
    service = MarketUniverseService(
        discovery,
        MarketRegistry(),
        _NoopPersistence(),
        settings=settings,
    )

    markets = service.refresh_once_sync()

    assert [market.condition_id for market in markets] == ["condition-market-current"]
    assert clients and clients[0].closed is True
    assert service.refresh_completed is True


def test_market_rotation_actor_refresh_async_publishes_ptb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[object] = []
    settings = Settings()
    settings.runtime.nautilus.sidecar.spot_source = "disabled"
    actor = MarketRotationActor(
        settings=settings,
        startup_markets=(),
        market_universe=_Universe([[_market("condition-a")]]),
        catalog=MarketCatalog(),
        anchor_store=None,
        health=None,
    )
    actor.publish_data = lambda data_type, data: published.append(data)

    def fake_ptb(_market: Market) -> PriceToBeatResult:
        return PriceToBeatResult(
            value=100000.0,
            source="anchor",
            verified=True,
            anchor_source="chainlink",
            anchor_lag_ms=5,
            from_anchor_service=True,
        )

    monkeypatch.setattr(actor.ptb_provider, "get_sync", fake_ptb)

    asyncio.run(actor._refresh_async())

    assert any(isinstance(item, PolySignalMarketUniverseData) for item in published)
    assert any(isinstance(item, PolySignalMarketMetaData) for item in published)
    assert any(isinstance(item, PolySignalPriceToBeatData) for item in published)


def test_market_rotation_actor_on_stop_cancels_clock_without_feed_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancelled: list[str] = []
    worker = _StubDiscoveryWorker()
    settings = Settings()
    settings.runtime.nautilus.market_rotation.enabled = False
    settings.runtime.nautilus.sidecar.spot_source = "disabled"
    actor = MarketRotationActor(
        settings=settings,
        startup_markets=(),
        market_universe=_Universe([[]]),
        catalog=MarketCatalog(),
        discovery_worker=cast(Any, worker),
        anchor_store=None,
        health=None,
    )
    fake_clock = SimpleNamespace(
        cancel_timer=lambda name: cancelled.append(str(name)),
    )
    monkeypatch.setattr(
        MarketRotationActor,
        "clock",
        property(lambda self: fake_clock),
    )
    actor.publish_data = lambda data_type, data: None
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.market_rotation._register_polysignal_data_types_if_available",
        lambda: None,
    )

    actor.on_stop()

    assert cancelled == ["market_rotation_refresh"]
    assert worker.closed is True
    assert not hasattr(actor, "rtds_feed")
