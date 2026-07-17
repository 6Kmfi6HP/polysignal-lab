"""
Input: __future__, __future__.annotations, datetime, datetime.UTC, datetime.datetime, datetime.timedelta, types, types.SimpleNamespace, polysignal_lab.config, polysignal_lab.config.Settings
Output: test_spot_anchor_state_captures_actor_local_history_without_trading_projection, test_market_rotation_publishes_ptb_for_startup_markets, test_market_rotation_state_roundtrip_preserves_markets, test_market_rotation_has_no_discovery_worker, _HealthRecorder, _RecordingActor
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from polysignal_lab.config import Settings
from polysignal_lab.data.price_to_beat_provider import PriceToBeatResult
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.domain.spot import SpotPrice
from polysignal_lab.nautilus_runtime.custom_data_types import (
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


class _RecordingActor(MarketRotationActor):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.published: list[object] = []

    def publish_data(self, data_type: object, data: object) -> None:
        _ = data_type
        self.published.append(data)


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
    actor.ptb_provider = SimpleNamespace(  # type: ignore[assignment]
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
    payloads = [unwrap_custom_data(item) for item in actor.published]
    ptbs = [p for p in payloads if isinstance(p, PolySignalPriceToBeatData)]
    assert len(ptbs) == 1
    assert ptbs[0].condition_id == "cond-a"
    assert float(ptbs[0].value) == 101.5
    assert health.ok


def test_market_rotation_state_roundtrip_preserves_markets() -> None:
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "disabled"
    market = _market("cond-b")
    actor = _RecordingActor(settings=settings, startup_markets=(market,))
    saved = actor.on_save()
    actor2 = _RecordingActor(settings=settings, startup_markets=())
    actor2.on_load(saved)
    assert [m.condition_id for m in actor2.active_markets()] == ["cond-b"]


def test_market_rotation_has_no_discovery_worker() -> None:
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "disabled"
    actor = MarketRotationActor(settings=settings, startup_markets=())
    assert not hasattr(actor, "_discovery_worker") or getattr(
        actor, "_discovery_worker", None
    ) is None
