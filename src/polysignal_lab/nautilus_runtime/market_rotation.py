"""
Input: __future__, __future__.annotations, logging, collections.abc, collections.abc.Mapping, datetime, datetime.UTC, datetime.datetime, typing, typing.Protocol
Output: _Health, MarketRotationActor
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol, cast

from nautilus_trader.core.nautilus_pyo3 import DataActor

from polysignal_lab.config import Settings
from polysignal_lab.data.anchor_price_service import AnchorPriceStore
from polysignal_lab.data.price_to_beat_provider import PriceToBeatProvider
from polysignal_lab.domain.market import Market
from polysignal_lab.domain.spot import SpotPrice
from polysignal_lab.nautilus_runtime.custom_data_publisher import (
    CustomDataPublisher,
    timestamp_ns,
)
from polysignal_lab.nautilus_runtime.custom_data_types import (
    custom_data_type,
    is_polymarket_rtds_crypto_price,
    polymarket_rtds_crypto_price_type,
    polymarket_rtds_spot_identity,
    unwrap_custom_data,
)
from polysignal_lab.nautilus_runtime.spot_anchor_state import SpotAnchorState
from polysignal_lab.nautilus_runtime.state import JsonValue, decode_state, encode_state

logger = logging.getLogger("polysignal_lab.nautilus.market_rotation")

_PriceToBeatSignature = tuple[float, str, bool, bool, str | None]
_ROTATION_ACTOR_ID = "PolySignal-MarketRotation"


def _data_datetime(value: object, *, fallback: datetime) -> datetime:
    try:
        timestamp_ns_value = int(value)
    except (TypeError, ValueError):
        return fallback
    if timestamp_ns_value <= 0:
        return fallback
    return datetime.fromtimestamp(timestamp_ns_value / 1_000_000_000, UTC)


class _Health(Protocol):
    def mark_ok(self, name: str, **metrics: object) -> None: ...
    def mark_degraded(
        self,
        name: str,
        error: str | None = None,
        **metrics: object,
    ) -> None: ...
    def mark_down(self, name: str, error: str | None = None, **metrics: object) -> None: ...


class MarketRotationActor(DataActor):
    """PTB + spot anchor actor. Market discovery is owned by official InstrumentProvider."""

    state_name = "market_rotation"

    def __new__(cls, *args: object, **kwargs: object):
        return super().__new__(cls)

    def __init__(
        self,
        config: object | None = None,
        *,
        settings: Settings | None = None,
        startup_markets: tuple[Market, ...] = (),
        discovery_worker: object | None = None,
        anchor_store: AnchorPriceStore | None = None,
        health: _Health | None = None,
    ) -> None:
        from nautilus_trader.core.nautilus_pyo3 import ActorId, DataActorConfig
        from polysignal_lab.nautilus_runtime.runtime_configs import (
            MarketRotationActorConfig,
        )

        _ = discovery_worker  # removed; official provider owns instrument discovery
        if isinstance(config, MarketRotationActorConfig) and settings is None:
            settings = config.settings()
            startup_markets = config.markets()
            config = DataActorConfig(actor_id=ActorId(str(config.actor_id)))
        elif config is None:
            config = DataActorConfig(actor_id=ActorId(_ROTATION_ACTOR_ID))
        if settings is None:
            raise RuntimeError("MarketRotationActor requires settings")
        DataActor.__init__(self, config)
        spot_source = settings.runtime.nautilus.spot_data.source
        if spot_source not in {"disabled", "polymarket_rtds"}:
            raise RuntimeError(
                f"unsupported Nautilus spot data source: {spot_source!r}"
            )
        self.settings: Settings = settings
        self.health: _Health | None = health
        self.publisher: CustomDataPublisher = CustomDataPublisher(publisher=self)
        self._spot_state = SpotAnchorState(anchor_store)
        self.ptb_provider: PriceToBeatProvider = PriceToBeatProvider(
            anchor_store=anchor_store
        )
        self._active_by_condition: dict[str, Market] = _markets_by_condition(
            startup_markets
        )
        self._epoch: int = 0
        self._last_published_ptb: dict[str, _PriceToBeatSignature] = {}
        self._loaded_from_state: bool = False

    def publish_data(self, data_type: object, data: object) -> None:
        super().publish_data(data_type, data)

    def _framework_now(self) -> datetime:
        try:
            clock = self.clock
            timestamp = getattr(clock, "timestamp_ns", None)
            if callable(timestamp):
                value = int(timestamp())
                if value >= 0:
                    return datetime.fromtimestamp(value / 1_000_000_000, UTC)
        except (NotImplementedError, RuntimeError, AttributeError):
            pass
        if getattr(self, "trader_id", None) is None:
            return datetime(1970, 1, 1, tzinfo=UTC)
        raise RuntimeError("Nautilus actor clock timestamp_ns is unavailable")

    def on_start(self) -> None:
        if self.settings.runtime.nautilus.spot_data.source == "polymarket_rtds":
            self.subscribe_data(custom_data_type(polymarket_rtds_crypto_price_type()))
        if self._epoch == 0:
            self._epoch = 1
        self._publish_price_to_beat_batch_sync(self.active_markets())
        self._mark_ok(
            active_count=len(self._active_by_condition),
            epoch=self._epoch,
            phase="startup" if not self._loaded_from_state else "reload",
        )
        logger.info(
            "market_rotation phase=startup epoch=%s active=%s discovery=disabled",
            self._epoch,
            len(self._active_by_condition),
        )

    def on_stop(self) -> None:
        return

    def on_save(self) -> dict[str, bytes]:
        payload: dict[str, JsonValue] = {
            "epoch": self._epoch,
            "active_markets": [
                cast(JsonValue, market.model_dump(mode="json"))
                for market in self._active_by_condition.values()
            ],
        }
        return encode_state(self.state_name, payload)

    def on_load(self, state: Mapping[str, bytes]) -> None:
        payload = cast(Mapping[str, object], decode_state(self.state_name, state))
        raw_markets = payload.get("active_markets")
        if isinstance(raw_markets, list):
            markets: list[Market] = []
            for item in raw_markets:
                if isinstance(item, Mapping):
                    markets.append(Market.model_validate(item))
            self._active_by_condition = _markets_by_condition(tuple(markets))
        epoch = payload.get("epoch")
        if isinstance(epoch, int) and epoch >= 0:
            self._epoch = epoch
        self._last_published_ptb.clear()
        self._loaded_from_state = True

    def on_data(self, data: object) -> None:
        payload = unwrap_custom_data(data)
        if not is_polymarket_rtds_crypto_price(payload):
            return
        asset, symbol = polymarket_rtds_spot_identity(payload.symbol)
        received_at = _data_datetime(
            getattr(payload, "ts_init", 0),
            fallback=self._framework_now(),
        )
        event_time = _data_datetime(
            getattr(payload, "ts_event", 0),
            fallback=received_at,
        )
        self._on_spot(
            SpotPrice(
                asset=asset,
                symbol=symbol,
                price=float(payload.value),
                source="polymarket_rtds",
                event_time=event_time,
                received_at=received_at,
            )
        )

    def _on_spot(self, spot: SpotPrice) -> None:
        self._spot_state.update(spot)
        if not self._spot_state.enabled:
            return
        for market in self.active_markets():
            if market.asset.upper() != spot.asset.upper():
                continue
            _ = self._spot_state.capture_for_market(market)
            self._publish_price_to_beat_sync(market)

    def active_markets(self) -> tuple[Market, ...]:
        return tuple(self._active_by_condition.values())

    def _publish_price_to_beat_sync(self, market: Market) -> None:
        result = self.ptb_provider.get_sync(market)
        if result.value is None:
            return
        signature: _PriceToBeatSignature = (
            result.value,
            result.source,
            result.verified,
            result.from_anchor_service,
            result.anchor_source,
        )
        if self._last_published_ptb.get(market.condition_id) == signature:
            return
        now = self._framework_now()
        self.publisher.publish_price_to_beat(
            condition_id=market.condition_id,
            value=result.value,
            source=result.source,
            verified=result.verified,
            from_anchor_service=result.from_anchor_service,
            anchor_source=result.anchor_source,
            anchor_lag_ms=result.anchor_lag_ms,
            ts_event=timestamp_ns(now),
            ts_init=timestamp_ns(now),
        )
        self._last_published_ptb[market.condition_id] = signature

    def _publish_price_to_beat_batch_sync(self, markets: tuple[Market, ...]) -> None:
        for market in markets:
            try:
                self._publish_price_to_beat_sync(market)
            except Exception:
                logger.exception(
                    "market_rotation phase=ptb failed condition_id=%s",
                    market.condition_id,
                )

    def _mark_ok(self, **metrics: object) -> None:
        if self.health is not None:
            self.health.mark_ok("market_rotation", **metrics)

    def _mark_degraded(self, error: str, **metrics: object) -> None:
        if self.health is not None:
            self.health.mark_degraded(
                "market_rotation",
                error,
                epoch=self._epoch,
                **metrics,
            )

    def _mark_down(self, exc: Exception, **metrics: object) -> None:
        if self.health is not None:
            self.health.mark_down(
                "market_rotation", str(exc), epoch=self._epoch, **metrics
            )


def _markets_by_condition(
    markets: tuple[Market, ...] | list[Market],
) -> dict[str, Market]:
    return {market.condition_id: market for market in markets if market.condition_id}
