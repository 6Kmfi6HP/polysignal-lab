"""
Input: __future__, __future__.annotations, datetime, datetime.UTC, datetime.datetime, datetime.timedelta, types, types.SimpleNamespace, nautilus_polymarket_fixtures, polysignal_lab.config, polysignal_lab.config.Settings
Output: test_spot_anchor_state_captures_actor_local_history_without_trading_projection, test_market_rotation_publishes_ptb_for_startup_markets, test_market_rotation_publishes_provider_instrument_market, test_market_rotation_state_roundtrip_preserves_markets, test_market_rotation_rejects_discovery_worker_kwarg, _HealthRecorder, _RecordingActor
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from typing_extensions import override

from nautilus_polymarket_fixtures import (
    polymarket_binary_instrument,
    rust_shaped_polymarket_binary_instrument,
)
from polysignal_lab.config import Settings
from polysignal_lab.data.price_to_beat_provider import PriceToBeatResult
from polysignal_lab.domain.enums import MarketStatus, Side
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.domain.spot import SpotPrice
from polysignal_lab.nautilus_runtime.custom_data_types import (
    PolySignalMarketMetaData,
    PolySignalMarketUniverseData,
    PolySignalPriceToBeatData,
    unwrap_custom_data,
)
from polysignal_lab.nautilus_runtime.market_rotation import MarketRotationActor
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


class _HealthRecorder:
    def __init__(self) -> None:
        self.ok: list[tuple[str, dict[str, object]]] = []

    def mark_ok(self, name: str, **metrics: object) -> None:
        self.ok.append((name, dict(metrics)))

    def mark_degraded(self, name: str, error: str | None = None, **metrics: object) -> None:
        _ = name, error, metrics

    def mark_down(self, name: str, error: str | None = None, **metrics: object) -> None:
        _ = name, error, metrics


class _RecordingClock:
    def __init__(self) -> None:
        self.timer: tuple[str, timedelta, object] | None = None
        self.alert: tuple[str, int, object] | None = None
        self.canceled: list[str] = []

    def timestamp_ns(self) -> int:
        return 1

    def set_time_alert_ns(
        self,
        name: str,
        alert_time_ns: int,
        *,
        callback: object,
    ) -> None:
        self.alert = (name, alert_time_ns, callback)

    def set_timer(
        self,
        name: str,
        interval: timedelta,
        *,
        callback: object,
    ) -> None:
        self.timer = (name, interval, callback)

    def cancel_timer(self, name: str) -> None:
        self.canceled.append(name)


class _RecordingActor(MarketRotationActor):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.published: list[object] = []
        self.instrument_subscriptions: list[tuple[str, str | None]] = []
        self.instrument_unsubscriptions: list[tuple[str, str | None]] = []
        self.instrument_requests: list[tuple[str, str | None]] = []
        self.custom_data_subscriptions: list[tuple[object, str | None]] = []
        self.custom_data_unsubscriptions: list[tuple[object, str | None]] = []
        self.now: datetime = datetime(2026, 6, 28, tzinfo=UTC)
        self.fake_clock: _RecordingClock = _RecordingClock()

    @property
    @override
    def clock(self) -> _RecordingClock:
        return self.fake_clock

    @override
    def _framework_now(self) -> datetime:
        return self.now

    def publish_data(self, data_type: object, data: object) -> None:
        _ = data_type
        self.published.append(data)

    @override
    def subscribe_instruments(
        self,
        venue: object,
        client_id: object | None = None,
        params: dict[str, str] | None = None,
    ) -> None:
        _ = params
        self.instrument_subscriptions.append(
            (str(venue), None if client_id is None else str(client_id))
        )

    @override
    def unsubscribe_instruments(
        self,
        venue: object,
        client_id: object | None = None,
        params: dict[str, str] | None = None,
    ) -> None:
        _ = params
        self.instrument_unsubscriptions.append(
            (str(venue), None if client_id is None else str(client_id))
        )

    @override
    def request_instruments(
        self,
        venue: object | None = None,
        start: object | None = None,
        end: object | None = None,
        client_id: object | None = None,
        params: dict[str, str] | None = None,
    ) -> str:
        _ = start, end, params
        self.instrument_requests.append(
            (str(venue), None if client_id is None else str(client_id))
        )
        return "request-instruments"
    @override
    def subscribe_data(
        self,
        data_type: object,
        client_id: object | None = None,
        params: dict[str, str] | None = None,
    ) -> None:
        _ = params
        self.custom_data_subscriptions.append(
            (data_type, None if client_id is None else str(client_id))
        )
    @override
    def unsubscribe_data(
        self,
        data_type: object,
        client_id: object | None = None,
        params: dict[str, str] | None = None,
    ) -> None:
        _ = params
        self.custom_data_unsubscriptions.append(
            (data_type, None if client_id is None else str(client_id))
        )


def _fire_startup_replay(actor: _RecordingActor) -> None:
    assert actor.clock.alert is not None
    name, _, callback = actor.clock.alert
    assert name == "polysignal_market_startup_replay"
    assert callable(callback)
    _ = callback(object())


def test_spot_anchor_state_captures_actor_local_history_without_trading_projection() -> None:
    state = SpotAnchorState(anchor_store=None)
    market = _market("cond-a")
    spot = SpotPrice(
        asset="BTC",
        symbol="btcusdt",
        price=100.0,
        source="polymarket_rtds",
        event_time=datetime(2026, 6, 28, tzinfo=UTC),
        received_at=datetime(2026, 6, 28, tzinfo=UTC),
    )
    state.update(spot)
    # Without anchor store, capture is disabled; history still accepted.
    assert state.capture_for_market(market) is None
    assert state.enabled is False


def test_market_rotation_publishes_ptb_for_startup_markets() -> None:
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "disabled"
    market = _market("cond-a")
    health = _HealthRecorder()
    actor = _RecordingActor(
        settings=settings,
        startup_markets=(market,),
        health=health,
    )
    actor.ptb_provider = SimpleNamespace(  # pyright: ignore[reportAttributeAccessIssue]
        get_sync=lambda m: PriceToBeatResult(
            value=101.5,
            source="test",
            verified=True,
            from_anchor_service=False,
            anchor_source=None,
            anchor_lag_ms=None,
        )
    )
    actor.on_start()
    assert actor.published == []
    _fire_startup_replay(actor)
    payloads = [unwrap_custom_data(item) for item in actor.published]
    metadata = [item for item in payloads if isinstance(item, PolySignalMarketMetaData)]
    universe = next(
        item for item in payloads if isinstance(item, PolySignalMarketUniverseData)
    )
    ptbs = [p for p in payloads if isinstance(p, PolySignalPriceToBeatData)]
    assert [item.condition_id for item in metadata] == ["cond-a"]
    assert universe.active_condition_ids == ("cond-a",)
    assert universe.entered_condition_ids == ("cond-a",)
    assert len(ptbs) == 1
    assert ptbs[0].condition_id == "cond-a"
    assert float(ptbs[0].value) == 101.5
    assert health.ok


def test_market_rotation_publishes_provider_instrument_market() -> None:
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "disabled"
    actor = _RecordingActor(settings=settings)
    actor.ptb_provider = SimpleNamespace(  # pyright: ignore[reportAttributeAccessIssue]
        get_sync=lambda _market: PriceToBeatResult(  # pyright: ignore[reportUnknownLambdaType]
            value=None,
            source="unavailable",
            verified=False,
            from_anchor_service=False,
            anchor_source=None,
            anchor_lag_ms=None,
        )
    )

    actor.on_instrument(polymarket_binary_instrument("uptoken", "Up"))
    assert actor.active_markets() == ()

    actor.on_instrument(polymarket_binary_instrument("downtoken", "Down"))

    assert [market.condition_id for market in actor.active_markets()] == [
        "0xcondition1"
    ]
    payloads = [unwrap_custom_data(item) for item in actor.published]
    metadata = [item for item in payloads if isinstance(item, PolySignalMarketMetaData)]
    universes = [
        item for item in payloads if isinstance(item, PolySignalMarketUniverseData)
    ]
    assert len(metadata) == 1
    assert metadata[0].condition_id == "0xcondition1"
    assert len(universes) == 1
    assert universes[0].active_condition_ids == ("0xcondition1",)
    assert universes[0].entered_condition_ids == ("0xcondition1",)


def test_market_rotation_activates_official_rust_shaped_instruments() -> None:
    """Issue #20: official Rust BinaryOption.info must enter the active universe."""
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "disabled"
    actor = _RecordingActor(settings=settings)
    actor.ptb_provider = SimpleNamespace(  # pyright: ignore[reportAttributeAccessIssue]
        get_sync=lambda _market: PriceToBeatResult(  # pyright: ignore[reportUnknownLambdaType]
            value=None,
            source="unavailable",
            verified=False,
            from_anchor_service=False,
            anchor_source=None,
            anchor_lag_ms=None,
        )
    )
    start = datetime.now(UTC)
    end = start + timedelta(minutes=5)

    actor.on_instrument(
        rust_shaped_polymarket_binary_instrument(
            "up1", "Up", event_start=start, event_end=end
        )
    )
    actor.on_instrument(
        rust_shaped_polymarket_binary_instrument(
            "down1", "Down", event_start=start, event_end=end
        )
    )

    markets = actor.active_markets()
    assert len(markets) == 1
    assert markets[0].is_active is True
    assert markets[0].condition_id == "0xcondition1"
    universes = [
        unwrap_custom_data(item)
        for item in actor.published
        if isinstance(unwrap_custom_data(item), PolySignalMarketUniverseData)
    ]
    assert universes
    assert cast(PolySignalMarketUniverseData, universes[-1]).active_condition_ids == (
        "0xcondition1",
    )


def test_market_rotation_ignores_unchanged_provider_refresh() -> None:
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "disabled"
    actor = _RecordingActor(settings=settings)

    instruments = (
        polymarket_binary_instrument("uptoken", "Up"),
        polymarket_binary_instrument("downtoken", "Down"),
    )
    for instrument in instruments:
        actor.on_instrument(instrument)
    published_count = len(actor.published)
    epoch = actor._epoch  # pyright: ignore[reportPrivateUsage]

    for instrument in instruments:
        actor.on_instrument(instrument)

    assert len(actor.published) == published_count
    assert actor._epoch == epoch  # pyright: ignore[reportPrivateUsage]


def test_market_rotation_ignores_incidental_provider_metadata_refresh() -> None:
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "disabled"
    actor = _RecordingActor(settings=settings)

    actor.on_instrument(polymarket_binary_instrument("uptoken", "Up"))
    actor.on_instrument(polymarket_binary_instrument("downtoken", "Down"))
    published_count = len(actor.published)
    refreshed = polymarket_binary_instrument(
        "uptoken",
        "Up",
        gamma_overrides={"updatedAt": "2026-07-18T12:00:01Z"},
    )

    actor.on_instrument(refreshed)

    assert len(actor.published) == published_count


def test_market_rotation_retires_closed_provider_market() -> None:
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "disabled"
    actor = _RecordingActor(settings=settings)

    actor.on_instrument(polymarket_binary_instrument("uptoken", "Up"))
    actor.on_instrument(polymarket_binary_instrument("downtoken", "Down"))
    actor.published.clear()

    actor.on_instrument(
        polymarket_binary_instrument(
            "uptoken",
            "Up",
            active=False,
            closed=True,
        )
    )

    assert actor.active_markets() == ()
    payloads = [unwrap_custom_data(item) for item in actor.published]
    universes = [
        item for item in payloads if isinstance(item, PolySignalMarketUniverseData)
    ]
    assert len(universes) == 1
    assert universes[0].active_condition_ids == ()
    assert universes[0].exited_condition_ids == ("0xcondition1",)
    published_count = len(actor.published)

    actor.on_instrument(polymarket_binary_instrument("downtoken", "Down"))

    assert actor.active_markets() == ()
    assert len(actor.published) == published_count


def test_market_rotation_terminal_first_leg_cannot_be_reopened_by_stale_pair() -> None:
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "disabled"
    actor = _RecordingActor(settings=settings)

    actor.on_instrument(
        polymarket_binary_instrument(
            "uptoken",
            "Up",
            active=False,
            closed=True,
        )
    )
    actor.on_instrument(polymarket_binary_instrument("downtoken", "Down"))

    assert actor.active_markets() == ()
    payloads = [unwrap_custom_data(item) for item in actor.published]
    assert not any(isinstance(item, PolySignalMarketMetaData) for item in payloads)
    assert not any(isinstance(item, PolySignalMarketUniverseData) for item in payloads)


def test_market_rotation_terminal_first_leg_retires_restored_active_market() -> None:
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "disabled"
    actor = _RecordingActor(
        settings=settings,
        startup_markets=(
            _market("0xcondition1").model_copy(
                update={"status": MarketStatus.ACTIVE}
            ),
        ),
    )

    actor.on_instrument(
        polymarket_binary_instrument(
            "uptoken",
            "Up",
            active=False,
            closed=True,
        )
    )

    assert actor.active_markets() == ()
    payloads = [unwrap_custom_data(item) for item in actor.published]
    universe = next(
        item for item in payloads if isinstance(item, PolySignalMarketUniverseData)
    )
    assert universe.active_condition_ids == ()
    assert universe.exited_condition_ids == ("0xcondition1",)


def test_market_rotation_terminal_before_startup_replay_is_included_in_snapshot() -> None:
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "disabled"
    actor = _RecordingActor(
        settings=settings,
        startup_markets=(
            _market("0xcondition1").model_copy(
                update={"status": MarketStatus.ACTIVE}
            ),
        ),
    )
    actor.on_start()
    actor.on_instrument(
        polymarket_binary_instrument(
            "uptoken",
            "Up",
            active=False,
            closed=True,
        )
    )
    actor.published.clear()

    _fire_startup_replay(actor)

    payloads = [unwrap_custom_data(item) for item in actor.published]
    universe = next(
        item for item in payloads if isinstance(item, PolySignalMarketUniverseData)
    )
    assert universe.active_condition_ids == ()
    assert universe.exited_condition_ids == ("0xcondition1",)


def test_market_rotation_stale_startup_replay_does_not_publish_after_stop() -> None:
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "disabled"
    actor = _RecordingActor(
        settings=settings,
        startup_markets=(_market("cond-startup"),),
    )
    actor.on_start()
    assert actor.clock.alert is not None
    _, _, callback = actor.clock.alert

    actor.on_stop()
    actor.published.clear()
    assert callable(callback)
    _ = callback(object())

    assert actor.published == []


def test_market_rotation_restored_state_rebuilds_instrument_ingress() -> None:
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "disabled"
    settings.runtime.nautilus.market_rotation.interval_sec = 17
    market = _market("cond-restored")
    saved = _RecordingActor(settings=settings, startup_markets=(market,)).on_save()
    actor = _RecordingActor(settings=settings)
    actor.on_load(saved)

    actor.on_start()

    assert actor.published == []
    _fire_startup_replay(actor)
    assert actor.instrument_subscriptions == [
        ("POLYMARKET", "POLYMARKET-5M"),
        ("POLYMARKET", "POLYMARKET-15M"),
    ]
    assert actor.instrument_requests == [
        ("POLYMARKET", "POLYMARKET-5M"),
        ("POLYMARKET", "POLYMARKET-15M"),
    ]
    assert actor.clock.timer is not None
    name, interval, _ = actor.clock.timer
    assert name == "polysignal_market_expiry"
    assert interval == timedelta(seconds=17)
    assert actor.active_markets() == ()
    payloads = [unwrap_custom_data(item) for item in actor.published]
    universe = next(
        item for item in payloads if isinstance(item, PolySignalMarketUniverseData)
    )
    assert universe.active_condition_ids == ()
    assert universe.exited_condition_ids == ("cond-restored",)
    assert universe.entered_condition_ids == ()


def test_market_rotation_restored_state_retires_expired_market() -> None:
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "disabled"
    expired = _market("cond-expired")
    saved_actor = _RecordingActor(settings=settings, startup_markets=(expired,))
    saved_actor._epoch = 7  # pyright: ignore[reportPrivateUsage]
    saved = saved_actor.on_save()
    actor = _RecordingActor(settings=settings)
    actor.on_load(saved)
    actor.now = datetime(2026, 7, 18, tzinfo=UTC)

    actor.on_start()

    assert actor.published == []
    _fire_startup_replay(actor)
    assert actor.active_markets() == ()
    payloads = [unwrap_custom_data(item) for item in actor.published]
    universe = next(
        item for item in payloads if isinstance(item, PolySignalMarketUniverseData)
    )
    assert universe.active_condition_ids == ()
    assert universe.exited_condition_ids == ("cond-expired",)
    assert universe.epoch == 8


def test_market_rotation_restored_state_replays_live_survivor_with_expired_exit() -> None:
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "disabled"
    expired = _market("cond-expired")
    live = _market("cond-live").model_copy(
        update={"end_ts": datetime(2026, 7, 18, 12, 10, tzinfo=UTC)}
    )
    saved_actor = _RecordingActor(
        settings=settings,
        startup_markets=(expired, live),
    )
    saved_actor._epoch = 7  # pyright: ignore[reportPrivateUsage]
    saved = saved_actor.on_save()
    actor = _RecordingActor(settings=settings)
    actor.on_load(saved)
    actor.now = datetime(2026, 7, 18, 12, 5, tzinfo=UTC)

    actor.on_start()

    assert actor.published == []
    _fire_startup_replay(actor)
    assert actor.active_markets() == ()
    payloads = [unwrap_custom_data(item) for item in actor.published]
    metadata = [item for item in payloads if isinstance(item, PolySignalMarketMetaData)]
    universe = next(
        item for item in payloads if isinstance(item, PolySignalMarketUniverseData)
    )
    assert metadata == []
    assert universe.epoch == 8
    assert universe.active_condition_ids == ()
    assert universe.entered_condition_ids == ()
    assert universe.exited_condition_ids == ("cond-expired", "cond-live")


def test_market_rotation_restored_zero_epoch_advances_once() -> None:
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "disabled"
    market = _market("cond-restored-zero").model_copy(
        update={"end_ts": datetime(2026, 7, 18, 12, 10, tzinfo=UTC)}
    )
    saved = _RecordingActor(settings=settings, startup_markets=(market,)).on_save()
    actor = _RecordingActor(settings=settings)
    actor.on_load(saved)
    actor.now = datetime(2026, 7, 18, 12, 5, tzinfo=UTC)

    actor.on_start()

    assert actor.published == []
    _fire_startup_replay(actor)
    payloads = [unwrap_custom_data(item) for item in actor.published]
    universe = next(
        item for item in payloads if isinstance(item, PolySignalMarketUniverseData)
    )
    assert universe.epoch == 1


def test_market_rotation_timer_retires_expired_market_without_provider_update() -> None:
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "disabled"
    market = _market("cond-expiring")
    actor = _RecordingActor(settings=settings, startup_markets=(market,))
    actor.on_start()
    _fire_startup_replay(actor)
    assert actor.clock.timer is not None
    _, _, callback = actor.clock.timer
    actor.now = datetime(2026, 7, 18, tzinfo=UTC)

    assert callable(callback)
    _ = callback(object())

    assert actor.active_markets() == ()
    payloads = [unwrap_custom_data(item) for item in actor.published]
    universes = [
        item for item in payloads if isinstance(item, PolySignalMarketUniverseData)
    ]
    assert universes[-1].exited_condition_ids == ("cond-expiring",)
    actor.on_stop()
    assert actor.clock.canceled == ["polysignal_market_expiry"]


def test_market_rotation_ignores_expired_provider_instrument_market() -> None:
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "disabled"
    actor = _RecordingActor(settings=settings)
    actor.now = datetime(2026, 7, 18, 12, 5, tzinfo=UTC)

    actor.on_instrument(polymarket_binary_instrument("uptoken", "Up"))
    actor.on_instrument(polymarket_binary_instrument("downtoken", "Down"))

    assert actor.active_markets() == ()
    payloads = [unwrap_custom_data(item) for item in actor.published]
    assert not any(isinstance(item, PolySignalMarketMetaData) for item in payloads)
    assert not any(isinstance(item, PolySignalMarketUniverseData) for item in payloads)


def test_market_rotation_retires_expired_market_on_provider_update() -> None:
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "disabled"
    expired = _market("cond-expired")
    actor = _RecordingActor(settings=settings, startup_markets=(expired,))
    actor.ptb_provider = SimpleNamespace(  # pyright: ignore[reportAttributeAccessIssue]
        get_sync=lambda _market: PriceToBeatResult(  # pyright: ignore[reportUnknownLambdaType]
            value=None,
            source="unavailable",
            verified=False,
            from_anchor_service=False,
            anchor_source=None,
            anchor_lag_ms=None,
        )
    )
    new_start = datetime(2026, 7, 18, 12, 5, tzinfo=UTC)
    new_end = new_start + timedelta(minutes=5)
    actor.now = new_start

    actor.on_instrument(
        polymarket_binary_instrument(
            "nextup",
            "Up",
            condition_id="0xcondition2",
            market_id="market-2",
            event_start=new_start,
            event_end=new_end,
        )
    )
    actor.on_instrument(
        polymarket_binary_instrument(
            "nextdown",
            "Down",
            condition_id="0xcondition2",
            market_id="market-2",
            event_start=new_start,
            event_end=new_end,
        )
    )

    assert [market.condition_id for market in actor.active_markets()] == [
        "0xcondition2"
    ]
    payloads = [unwrap_custom_data(item) for item in actor.published]
    universe = next(
        item for item in payloads if isinstance(item, PolySignalMarketUniverseData)
    )
    assert universe.entered_condition_ids == ("0xcondition2",)
    assert universe.exited_condition_ids == ("cond-expired",)


def test_market_rotation_stop_unsubscribes_instruments_and_rtds() -> None:
    from polysignal_lab.nautilus_runtime.custom_data_types import (
        polymarket_rtds_crypto_symbols,
    )

    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "polymarket_rtds"
    actor = _RecordingActor(settings=settings)

    actor.on_start()
    actor.on_stop()

    assert actor.instrument_unsubscriptions == [
        ("POLYMARKET", "POLYMARKET-5M"),
        ("POLYMARKET", "POLYMARKET-15M"),
    ]
    expected_symbols = polymarket_rtds_crypto_symbols(
        settings.markets.assets,
        settings.data.binance.symbols,
    )
    assert len(actor.custom_data_unsubscriptions) == len(expected_symbols)
    assert {client_id for _, client_id in actor.custom_data_unsubscriptions} == {
        "POLYMARKET-5M"
    }
    assert all(
        getattr(data_type, "metadata", None) is not None
        and "symbol" in getattr(data_type, "metadata")
        for data_type, _ in actor.custom_data_unsubscriptions
    )
    assert actor.clock.canceled == ["polysignal_market_expiry"]


def test_market_rotation_stop_before_timer_creation_is_safe() -> None:
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "disabled"
    actor = _RecordingActor(settings=settings)

    actor.on_stop()

    assert actor.clock.canceled == []


def test_market_rotation_state_roundtrip_preserves_terminal_tombstones() -> None:
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "disabled"
    actor = _RecordingActor(settings=settings)
    actor.on_instrument(
        polymarket_binary_instrument(
            "uptoken",
            "Up",
            active=False,
            closed=True,
        )
    )

    saved = actor.on_save()
    restored = _RecordingActor(settings=settings)
    restored.on_load(saved)
    restored.on_instrument(polymarket_binary_instrument("uptoken", "Up"))
    restored.on_instrument(polymarket_binary_instrument("downtoken", "Down"))

    assert restored.active_markets() == ()
    assert restored.published == []


def test_market_rotation_restored_active_state_fails_closed_until_provider_refresh() -> None:
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "disabled"
    market = _market("cond-stale").model_copy(
        update={"end_ts": datetime(2026, 7, 18, 12, 10, tzinfo=UTC)}
    )
    saved = _RecordingActor(settings=settings, startup_markets=(market,)).on_save()
    actor = _RecordingActor(settings=settings)
    actor.on_load(saved)
    actor.now = datetime(2026, 7, 18, 12, 5, tzinfo=UTC)

    actor.on_start()
    _fire_startup_replay(actor)

    assert actor.active_markets() == ()
    payloads = [unwrap_custom_data(item) for item in actor.published]
    universe = next(
        item for item in payloads if isinstance(item, PolySignalMarketUniverseData)
    )
    assert universe.active_condition_ids == ()
    assert universe.exited_condition_ids == ("cond-stale",)


def test_market_rotation_rejects_pre_tombstone_state_schema() -> None:
    import pytest

    from polysignal_lab.nautilus_runtime.state import StateSchemaError, encode_state

    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "disabled"
    legacy = encode_state(
        "market_rotation",
        {"epoch": 3, "active_markets": []},
        version=3,
    )

    with pytest.raises(StateSchemaError, match="Unsupported state schema"):
        _RecordingActor(settings=settings).on_load(legacy)


def test_market_rotation_state_roundtrip_preserves_markets() -> None:
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "disabled"
    market = _market("cond-b")
    actor = _RecordingActor(settings=settings, startup_markets=(market,))
    saved = actor.on_save()
    actor2 = _RecordingActor(settings=settings, startup_markets=())
    actor2.on_load(saved)
    assert [m.condition_id for m in actor2.active_markets()] == ["cond-b"]


def test_market_rotation_rejects_discovery_worker_kwarg() -> None:
    """Instrument discovery is owned by Nautilus PolymarketInstrumentProvider."""
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "disabled"
    actor = MarketRotationActor(settings=settings, startup_markets=())
    assert not hasattr(actor, "_discovery_worker")
    try:
        MarketRotationActor(
            settings=settings,
            startup_markets=(),
            discovery_worker=object(),  # type: ignore[call-arg]
        )
    except TypeError as exc:
        assert "discovery_worker" in str(exc)
    else:
        raise AssertionError("expected discovery_worker kwarg to be rejected")
