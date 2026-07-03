from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from polysignal_lab.app.services.market_universe_service import MarketUniverseService
from polysignal_lab.config import MarketConfig, PolymarketDataConfig, Settings
from polysignal_lab.data.polymarket_market_discovery import MarketDiscovery
from polysignal_lab.data.price_to_beat_provider import PriceToBeatResult
from polysignal_lab.data.state import MarketRegistry
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import JsonObject, Market, OutcomeToken
from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
from polysignal_lab.nautilus_bridge.market_registry import PolymarketMarketRegistry
from polysignal_lab.nautilus_runtime.market_data import (
    PolySignalMarketMetaData,
    PolySignalMarketUniverseData,
    PolySignalPriceToBeatData,
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


class _HealthRecorder:
    def __init__(self) -> None:
        self.ok: list[tuple[str, dict[str, object]]] = []
        self.down: list[tuple[str, str | None, dict[str, object]]] = []

    def mark_ok(self, name: str, **metrics: object) -> None:
        self.ok.append((name, metrics))

    def mark_down(self, name: str, error: str | None = None, **metrics: object) -> None:
        self.down.append((name, error, metrics))


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
    health = _HealthRecorder()
    universe = _Universe(
        [
            [_market("condition-a"), _market("condition-b")],
        ]
    )
    actor = MarketRotationActor(
        settings=settings,
        startup_markets=(_market("condition-a"),),
        market_universe=universe,
        registry=PolymarketMarketRegistry(),
        sidecar=ExternalDataSidecar(),
        anchor_store=None,
        health=health,
    )
    actor.publish_data = lambda data_type, data: published.append(data)

    async def fake_ptb(market: Market) -> PriceToBeatResult:
        _ = market
        return PriceToBeatResult(
            value=100000.0,
            source="anchor",
            verified=True,
            anchor_source="chainlink",
            anchor_lag_ms=5,
            from_anchor_service=True,
        )

    monkeypatch.setattr(actor.ptb_provider, "get", fake_ptb)
    monkeypatch.setattr(
        "asyncio.create_task",
        lambda coro: _record_task(created, cast(Coroutine[Any, Any, object], coro)),
    )

    try:
        actor.on_start()

        ptb_tasks = [task for task in created if _recorded_task_name(task) == "_publish_price_to_beat"]
        refresh_tasks = [task for task in created if _recorded_task_name(task) == "_run_loop"]

        assert len(ptb_tasks) == 1
        assert len(refresh_tasks) == 1

        asyncio.run(ptb_tasks[0].coro)
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
    actor = MarketRotationActor(
        settings=settings,
        startup_markets=(market,),
        market_universe=_Universe([[market]]),
        registry=PolymarketMarketRegistry(),
        sidecar=ExternalDataSidecar(),
        anchor_store=None,
        health=None,
    )
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

    async def fake_ptb(_market: Market) -> PriceToBeatResult:
        return next(results)

    monkeypatch.setattr(actor.ptb_provider, "get", fake_ptb)
    monkeypatch.setattr(
        "asyncio.create_task",
        lambda coro: _record_task(created, cast(Coroutine[Any, Any, object], coro)),
    )

    try:
        actor.on_start()
        startup_tasks = [
            task for task in created if _recorded_task_name(task) == "_publish_price_to_beat"
        ]
        assert len(startup_tasks) == 1
        asyncio.run(startup_tasks[0].coro)
        published.clear()
        created.clear()

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
    actor = MarketRotationActor(
        settings=settings,
        startup_markets=(market,),
        market_universe=_Universe([[market]]),
        registry=PolymarketMarketRegistry(),
        sidecar=ExternalDataSidecar(),
        anchor_store=None,
        health=None,
    )

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

    async def fake_ptb(_market: Market) -> PriceToBeatResult:
        return next(results)

    monkeypatch.setattr(actor.ptb_provider, "get", fake_ptb)
    monkeypatch.setattr(
        "asyncio.create_task",
        lambda coro: _record_task(created, cast(Coroutine[Any, Any, object], coro)),
    )

    try:
        actor.on_start()
        startup_tasks = [
            task for task in created if _recorded_task_name(task) == "_publish_price_to_beat"
        ]
        assert len(startup_tasks) == 1
        asyncio.run(startup_tasks[0].coro)
        initial_publish_count = len(
            [item for item in published if isinstance(item, PolySignalPriceToBeatData)]
        )
        initial_on_data_calls = on_data_calls
        created.clear()

        asyncio.run(actor.refresh_once())

        assert created == []
        assert len([item for item in published if isinstance(item, PolySignalPriceToBeatData)]) == (
            initial_publish_count
        )
        assert on_data_calls == initial_on_data_calls
    finally:
        _close_recorded_tasks(created)


def test_market_rotation_actor_refresh_continues_after_single_market_ptb_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[object] = []
    created: list[_RecordedTask] = []
    settings = Settings()
    settings.runtime.nautilus.sidecar.spot_source = "disabled"
    settings.runtime.nautilus.market_rotation.enabled = False
    markets = (_market("condition-a"), _market("condition-b"))
    actor = MarketRotationActor(
        settings=settings,
        startup_markets=markets,
        market_universe=_Universe([list(markets)]),
        registry=PolymarketMarketRegistry(),
        sidecar=ExternalDataSidecar(),
        anchor_store=None,
        health=None,
    )
    actor.publish_data = lambda data_type, data: published.append(data)
    calls: dict[str, int] = {}

    async def fake_ptb(market: Market) -> PriceToBeatResult:
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

    monkeypatch.setattr(actor.ptb_provider, "get", fake_ptb)
    monkeypatch.setattr(
        "asyncio.create_task",
        lambda coro: _record_task(created, cast(Coroutine[Any, Any, object], coro)),
    )

    try:
        actor.on_start()
        startup_tasks = [
            task for task in created if _recorded_task_name(task) == "_publish_price_to_beat"
        ]
        assert len(startup_tasks) == 2
        for task in startup_tasks:
            asyncio.run(task.coro)
        published.clear()
        created.clear()

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
    actor = MarketRotationActor(
        settings=settings,
        startup_markets=markets,
        market_universe=_Universe([list(markets)]),
        registry=PolymarketMarketRegistry(),
        sidecar=ExternalDataSidecar(),
        anchor_store=None,
        health=None,
    )
    in_flight = 0
    max_in_flight = 0
    calls: list[str] = []

    async def fake_ptb(market: Market) -> PriceToBeatResult:
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        calls.append(market.condition_id)
        await asyncio.sleep(0)
        in_flight -= 1
        return PriceToBeatResult(
            value=100000.0,
            source="anchor",
            verified=True,
            anchor_source="chainlink",
            anchor_lag_ms=5,
            from_anchor_service=True,
        )

    monkeypatch.setattr(actor.ptb_provider, "get", fake_ptb)
    monkeypatch.setattr(
        "asyncio.create_task",
        lambda coro: _record_task(created, cast(Coroutine[Any, Any, object], coro)),
    )

    try:
        actor.on_start()
        startup_tasks = [
            task for task in created if _recorded_task_name(task) == "_publish_price_to_beat"
        ]
        for task in startup_tasks:
            asyncio.run(task.coro)
        created.clear()
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
    actor = MarketRotationActor(
        settings=settings,
        startup_markets=(_market("condition-a"),),
        market_universe=universe,
        registry=PolymarketMarketRegistry(),
        sidecar=ExternalDataSidecar(),
        anchor_store=None,
        health=None,
    )
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

        with pytest.raises(RuntimeError, match="universe publish failed"):
            asyncio.run(actor.refresh_once())

        assert [market.condition_id for market in actor.active_markets()] == ["condition-a"]
        assert [item for item in published if isinstance(item, PolySignalMarketUniverseData)][-1] == first_epoch
        assert actor._epoch == first_epoch.epoch
    finally:
        _close_recorded_tasks(created)


@pytest.mark.anyio
async def test_market_rotation_actor_run_loop_surfaces_refresh_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings()
    settings.runtime.nautilus.sidecar.spot_source = "disabled"
    settings.runtime.nautilus.market_rotation.interval_sec = 1
    health = _HealthRecorder()
    actor = MarketRotationActor(
        settings=settings,
        startup_markets=(),
        market_universe=_Universe([RuntimeError("refresh failed")]),
        registry=PolymarketMarketRegistry(),
        sidecar=ExternalDataSidecar(),
        anchor_store=None,
        health=health,
    )

    async def no_sleep(_interval: int) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", no_sleep)

    with pytest.raises(RuntimeError, match="refresh failed"):
        await actor._run_loop()

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
    actor = MarketRotationActor(
        settings=settings,
        startup_markets=(current_market,),
        market_universe=MarketUniverseService(
            discovery,
            MarketRegistry(),
            _NoopPersistence(),
            settings=settings,
        ),
        registry=PolymarketMarketRegistry(),
        sidecar=ExternalDataSidecar(),
        anchor_store=None,
        health=None,
    )
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
    actor = MarketRotationActor(
        settings=settings,
        startup_markets=(grace_market,),
        market_universe=MarketUniverseService(
            discovery,
            MarketRegistry(),
            _NoopPersistence(),
            settings=settings,
        ),
        registry=PolymarketMarketRegistry(),
        sidecar=ExternalDataSidecar(),
        anchor_store=None,
        health=None,
    )
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
        assert len(epochs) == 1
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
    actor = MarketRotationActor(
        settings=settings,
        startup_markets=(),
        market_universe=_Universe([[]]),
        registry=PolymarketMarketRegistry(),
        sidecar=ExternalDataSidecar(),
        anchor_store=None,
        health=None,
    )

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

    setattr(actor, "clock", FakeClock())
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


def test_market_rotation_actor_refresh_timer_runs_sync_after_removing_async_offload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    actor = MarketRotationActor(
        settings=Settings(),
        startup_markets=(),
        market_universe=_Universe([[]]),
        registry=PolymarketMarketRegistry(),
        sidecar=ExternalDataSidecar(),
        anchor_store=None,
        health=None,
    )

    monkeypatch.setattr(actor, "_refresh_market_universe_sync", lambda: calls.append("refresh"))
    monkeypatch.setattr(actor, "_apply_refreshed_markets", lambda markets: calls.append("apply"))
    monkeypatch.setattr(actor, "_run_refresh_price_to_beat_batch_sync", lambda markets: calls.append("ptb"))

    actor._on_refresh_timer()

    assert calls == ["refresh", "apply", "ptb"]
    assert actor._refresh_in_flight is False


def test_market_rotation_actor_refresh_timer_skips_when_refresh_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduled: list[object] = []
    actor = MarketRotationActor(
        settings=Settings(),
        startup_markets=(),
        market_universe=_Universe([[]]),
        registry=PolymarketMarketRegistry(),
        sidecar=ExternalDataSidecar(),
        anchor_store=None,
        health=None,
    )
    actor._refresh_in_flight = True

    class FakeLoop:
        def create_task(self, coro: object) -> None:
            scheduled.append(coro)

    monkeypatch.setattr("asyncio.get_running_loop", lambda: FakeLoop())

    actor._on_refresh_timer()

    assert scheduled == []


def test_market_rotation_actor_refresh_timer_applies_result_when_asyncio_run_close_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_run = asyncio.run
    actor = MarketRotationActor(
        settings=Settings(),
        startup_markets=(),
        market_universe=_Universe([[_market("condition-a")]]),
        registry=PolymarketMarketRegistry(),
        sidecar=ExternalDataSidecar(),
        anchor_store=None,
        health=None,
    )

    def run_then_fail(coro: Coroutine[Any, Any, object]) -> object:
        _ = original_run(coro)
        raise RuntimeError("Set changed size during iteration")

    monkeypatch.setattr(asyncio, "run", run_then_fail)

    actor._on_refresh_timer()

    assert [market.condition_id for market in actor.active_markets()] == ["condition-a"]
    assert actor._refresh_in_flight is False


def test_market_rotation_actor_refresh_preserves_result_when_fresh_client_close_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ClosingClient:
        async def aclose(self) -> None:
            raise RuntimeError("Set changed size during iteration")

    class FakeDiscovery:
        def __init__(self) -> None:
            self.client = object()

    class FakeUniverse:
        def __init__(self, discovery: FakeDiscovery) -> None:
            self.discovery = discovery

        async def refresh_once(self) -> list[Market]:
            return [_market("condition-a")]

    monkeypatch.setattr("httpx.AsyncClient", lambda *, timeout: ClosingClient())
    discovery = FakeDiscovery()
    original_client = discovery.client
    actor = MarketRotationActor(
        settings=Settings(),
        startup_markets=(),
        market_universe=FakeUniverse(discovery),
        registry=PolymarketMarketRegistry(),
        sidecar=ExternalDataSidecar(),
        anchor_store=None,
        health=None,
    )

    refreshed = actor._refresh_market_universe_sync()

    assert [market.condition_id for market in refreshed] == ["condition-a"]
    assert discovery.client is original_client


def test_market_rotation_actor_refresh_market_universe_sync_uses_fresh_client_each_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class LoopBoundClient:
        def __init__(self, label: str) -> None:
            self.label = label
            self.bound_loop = None

        async def get(self, _url: str, params: object | None = None) -> object:
            _ = params
            loop = asyncio.get_running_loop()
            if self.bound_loop is None:
                self.bound_loop = loop
            elif loop is not self.bound_loop:
                raise RuntimeError("client reused across event loops")
            return object()

        async def aclose(self) -> None:
            return None

    class FakeDiscovery:
        def __init__(self) -> None:
            self.client = LoopBoundClient("original")

    class FakeUniverse:
        def __init__(self, discovery: FakeDiscovery) -> None:
            self.discovery = discovery
            self.calls = 0
            self.seen_clients: list[object] = []

        async def refresh_once(self) -> list[Market]:
            self.calls += 1
            self.seen_clients.append(self.discovery.client)
            await self.discovery.client.get("https://example.invalid")
            return [_market("condition-a")]


    replacement_count = 0

    def fake_async_client(*, timeout: float) -> LoopBoundClient:
        _ = timeout
        nonlocal replacement_count
        replacement_count += 1
        return LoopBoundClient(f"fresh-{replacement_count}")

    monkeypatch.setattr("httpx.AsyncClient", fake_async_client)
    discovery = FakeDiscovery()
    original_client = discovery.client
    universe = FakeUniverse(discovery)
    actor = MarketRotationActor(
        settings=Settings(),
        startup_markets=(),
        market_universe=universe,
        registry=PolymarketMarketRegistry(),
        sidecar=ExternalDataSidecar(),
        anchor_store=None,
        health=None,
    )

    actor._refresh_market_universe_sync()
    actor._refresh_market_universe_sync()

    assert universe.calls == 2
    assert discovery.client is original_client
    assert universe.seen_clients[0] is not original_client
    assert universe.seen_clients[1] is not original_client
    assert universe.seen_clients[0] is not universe.seen_clients[1]


def test_market_rotation_actor_refresh_timer_without_running_loop_publishes_ptb_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[object] = []
    settings = Settings()
    settings.runtime.nautilus.sidecar.spot_source = "disabled"
    actor = MarketRotationActor(
        settings=settings,
        startup_markets=(),
        market_universe=_Universe([[_market("condition-a")]]),
        registry=PolymarketMarketRegistry(),
        sidecar=ExternalDataSidecar(),
        anchor_store=None,
        health=None,
    )
    actor.publish_data = lambda data_type, data: published.append(data)

    async def fake_ptb(_market: Market) -> PriceToBeatResult:
        return PriceToBeatResult(
            value=100000.0,
            source="anchor",
            verified=True,
            anchor_source="chainlink",
            anchor_lag_ms=5,
            from_anchor_service=True,
        )

    monkeypatch.setattr(actor.ptb_provider, "get", fake_ptb)

    actor._on_refresh_timer()

    assert any(isinstance(item, PolySignalMarketUniverseData) for item in published)
    assert any(isinstance(item, PolySignalMarketMetaData) for item in published)
    assert any(isinstance(item, PolySignalPriceToBeatData) for item in published)

def test_market_rotation_actor_on_stop_cancels_refresh_and_rtds_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[_RecordedTask] = []
    stopped: list[str] = []
    actor = MarketRotationActor(
        settings=Settings(),
        startup_markets=(),
        market_universe=_Universe([[]]),
        registry=PolymarketMarketRegistry(),
        sidecar=ExternalDataSidecar(),
        anchor_store=None,
        health=None,
    )

    monkeypatch.setattr(
        "asyncio.create_task",
        lambda coro: _record_task(created, cast(Coroutine[Any, Any, object], coro)),
    )
    monkeypatch.setattr(actor.rtds_feed, "stop", lambda: stopped.append("stopped"))

    try:
        actor.on_start()
        actor.on_stop()

        assert stopped == ["stopped"]
        assert {_recorded_task_name(task) for task in created} == {"run", "_run_loop"}
        assert all(task.cancelled for task in created)
    finally:
        _close_recorded_tasks(created)
