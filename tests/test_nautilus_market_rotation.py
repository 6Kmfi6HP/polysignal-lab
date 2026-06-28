from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from polysignal_lab.config import Settings
from polysignal_lab.data.price_to_beat_provider import PriceToBeatResult
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market, OutcomeToken
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
        payload.condition_to_up_token["c3"] = "up-3"


def test_market_rotation_actor_initial_publish_and_diff_executes_intercepted_ptb_coroutines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[object] = []
    created: list[_RecordedTask] = []
    settings = Settings()
    settings.runtime.nautilus.sidecar.spot_source = "disabled"
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
        asyncio.run(actor.refresh_once())

        ptb_tasks = [task for task in created if _recorded_task_name(task) == "_publish_price_to_beat"]
        refresh_tasks = [task for task in created if _recorded_task_name(task) == "_run_loop"]

        assert len(ptb_tasks) == 2
        assert len(refresh_tasks) == 1

        for task in ptb_tasks:
            asyncio.run(task.coro)

        epochs = [item for item in published if isinstance(item, PolySignalMarketUniverseData)]
        metas = [item for item in published if isinstance(item, PolySignalMarketMetaData)]
        ptbs = [item for item in published if isinstance(item, PolySignalPriceToBeatData)]

        assert epochs[0].epoch == 1
        assert epochs[-1].epoch == 2
        assert epochs[-1].entered_condition_ids == ("condition-b",)
        assert epochs[-1].exited_condition_ids == ()
        assert {meta.condition_id for meta in metas} == {"condition-a", "condition-b"}
        assert {ptb.condition_id for ptb in ptbs} == {"condition-a", "condition-b"}
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
