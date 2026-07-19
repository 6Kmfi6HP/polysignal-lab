"""
Input: __future__, __future__.annotations, logging, collections.abc, collections.abc.Mapping, datetime, datetime.UTC, datetime.datetime, typing, typing.Protocol
Output: _Health, MarketRotationActor
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Protocol, cast

from nautilus_trader.core.nautilus_pyo3 import DataActor

from polysignal_lab.config import Settings
from polysignal_lab.data.anchor_price_service import AnchorPriceStore
from polysignal_lab.data.price_to_beat_provider import PriceToBeatProvider
from polysignal_lab.domain.market import Market
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.spot import SpotPrice
from polysignal_lab.nautilus_runtime.custom_data_publisher import (
    CustomDataPublisher,
    framework_now,
    market_metadata,
    timestamp_ns,
)
from polysignal_lab.nautilus_runtime.custom_data_types import (
    PolySignalMarketUniverseData,
    is_polymarket_rtds_crypto_price,
    polymarket_rtds_crypto_price_data_type,
    polymarket_rtds_crypto_symbols,
    polymarket_rtds_spot_identity,
    unwrap_custom_data,
)
from polysignal_lab.nautilus_runtime.instrument_markets import (
    PolymarketInstrumentMarketBuilder,
)
from polysignal_lab.nautilus_runtime.polymarket_clients import (
    polymarket_data_client_id,
    polymarket_rtds_data_client_id,
)
from polysignal_lab.nautilus_runtime.spot_anchor_state import SpotAnchorState
from polysignal_lab.nautilus_runtime.state import JsonValue, decode_state, encode_state

logger = logging.getLogger("polysignal_lab.nautilus.market_rotation")

_PriceToBeatSignature = tuple[float, str, bool, bool, str | None]
_ROTATION_ACTOR_ID = "PolySignal-MarketRotation"
_MARKET_EXPIRY_TIMER_NAME = "polysignal_market_expiry"
_STARTUP_REPLAY_TIMER_NAME = "polysignal_market_startup_replay"


def _data_datetime(value: object, *, fallback: datetime) -> datetime:
    try:
        timestamp_ns_value = int(value)
    except (TypeError, ValueError):
        return fallback
    if timestamp_ns_value <= 0:
        return fallback
    return datetime.fromtimestamp(timestamp_ns_value / 1_000_000_000, UTC)


_MARKET_ROTATION_STATE_VERSION = 4


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
        anchor_store: AnchorPriceStore | None = None,
        health: _Health | None = None,
    ) -> None:
        from nautilus_trader.core.nautilus_pyo3 import ActorId, DataActorConfig
        from polysignal_lab.nautilus_runtime.runtime_configs import (
            MarketRotationActorConfig,
        )

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
        self._instrument_markets = PolymarketInstrumentMarketBuilder(settings.markets)
        self._epoch: int = 0
        self._last_published_ptb: dict[str, _PriceToBeatSignature] = {}
        self._loaded_from_state: bool = False
        self._expiry_timer_started: bool = False
        self._startup_replay_scheduled: bool = False
        self._startup_exited_condition_ids: tuple[str, ...] = ()
        self._lifecycle_generation: int = 0
        self._startup_replay_generation: int | None = None
        self._startup_restored_condition_ids: tuple[str, ...] = ()
        self._instrument_subscriptions_started: bool = False
        self._rtds_subscription_started: bool = False
        self._rtds_data_types: tuple[object, ...] = ()

    def _framework_now(self) -> datetime:
        return framework_now(self)

    def _publish_startup_universe(
        self,
        *,
        now: datetime,
        exited_condition_ids: tuple[str, ...],
    ) -> None:
        self._epoch += 1
        for market in self.active_markets():
            self.publisher.publish_market_metadata(market_metadata(market, timestamp=now))
        self.publisher.publish_market_universe(
            _market_universe(
                self.active_markets(),
                epoch=self._epoch,
                entered_condition_ids=tuple(self._active_by_condition),
                exited_condition_ids=exited_condition_ids,
                timestamp=now,
            )
        )

    def on_start(self) -> None:
        self._lifecycle_generation += 1
        now = self._framework_now()
        exited_condition_ids = self._retire_expired_markets(now)
        if self.settings.runtime.nautilus.market_rotation.enabled:
            from nautilus_trader.core.nautilus_pyo3 import Venue

            venue = Venue.from_str("POLYMARKET")
            for timeframe in self.settings.markets.timeframes:
                client_id = polymarket_data_client_id(timeframe)
                self.subscribe_instruments(venue, client_id=client_id)
                _ = self.request_instruments(venue, client_id=client_id)
            self._instrument_subscriptions_started = True
            _ = self.clock.set_timer(  # pyright: ignore[reportAny]
                _MARKET_EXPIRY_TIMER_NAME,
                timedelta(
                    seconds=self.settings.runtime.nautilus.market_rotation.interval_sec
                ),
                callback=self._on_market_expiry_timer,
            )
            self._expiry_timer_started = True
        if self.settings.runtime.nautilus.spot_data.source == "polymarket_rtds":
            client_id = polymarket_rtds_data_client_id(self.settings.markets.timeframes)
            rtds_types = tuple(
                polymarket_rtds_crypto_price_data_type(symbol)
                for symbol in polymarket_rtds_crypto_symbols(
                    self.settings.markets.assets,
                    self.settings.data.binance.symbols,
                )
            )
            for data_type in rtds_types:
                self.subscribe_data(data_type, client_id=client_id)
            self._rtds_data_types = rtds_types
            self._rtds_subscription_started = True
        self._schedule_startup_replay(exited_condition_ids)
        if self._loaded_from_state:
            for condition_id in self._startup_restored_condition_ids:
                _ = self._active_by_condition.pop(condition_id, None)
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

    def on_instrument(self, instrument: object) -> None:
        now = self._framework_now()
        terminal_condition_id = self._instrument_markets.record_terminal_condition(
            instrument
        )
        if terminal_condition_id is not None:
            exited_condition_ids = list(self._retire_expired_markets(now))
            self._retire_condition(terminal_condition_id, exited_condition_ids)
            self._merge_startup_exits(exited_condition_ids)
            self._publish_market_exits(tuple(exited_condition_ids), now=now)
            return
        market = self._instrument_markets.add(instrument)
        if market is None:
            return
        exited_condition_ids = list(self._retire_expired_markets(now))
        if not market.is_active or (
            market.end_ts is not None and now >= market.end_ts
        ):
            self._retire_condition(market.condition_id, exited_condition_ids)
            self._publish_market_exits(tuple(exited_condition_ids), now=now)
            return

        previous = self._active_by_condition.get(market.condition_id)
        self._startup_restored_condition_ids = tuple(
            condition_id
            for condition_id in self._startup_restored_condition_ids
            if condition_id != market.condition_id
        )
        self._active_by_condition[market.condition_id] = market
        if previous is None or _market_metadata_signature(previous) != _market_metadata_signature(
            market
        ):
            self.publisher.publish_market_metadata(market_metadata(market, timestamp=now))
        entered_condition_ids = (
            (market.condition_id,) if previous is None else ()
        )
        if entered_condition_ids or exited_condition_ids:
            self._epoch += 1
            self.publisher.publish_market_universe(
                _market_universe(
                    self.active_markets(),
                    epoch=self._epoch,
                    entered_condition_ids=entered_condition_ids,
                    exited_condition_ids=tuple(exited_condition_ids),
                    timestamp=now,
                )
            )
        self._publish_price_to_beat_sync(market)

    def on_stop(self) -> None:
        self._lifecycle_generation += 1
        if self._startup_replay_scheduled:
            _ = self.clock.cancel_timer(_STARTUP_REPLAY_TIMER_NAME)  # pyright: ignore[reportAny]
            self._startup_replay_scheduled = False
            self._startup_exited_condition_ids = ()
            self._startup_restored_condition_ids = ()
            self._startup_replay_generation = None
        if self._expiry_timer_started:
            _ = self.clock.cancel_timer(_MARKET_EXPIRY_TIMER_NAME)  # pyright: ignore[reportAny]
            self._expiry_timer_started = False
        if self._instrument_subscriptions_started:
            from nautilus_trader.core.nautilus_pyo3 import Venue

            venue = Venue.from_str("POLYMARKET")
            for timeframe in self.settings.markets.timeframes:
                self.unsubscribe_instruments(
                    venue,
                    client_id=polymarket_data_client_id(timeframe),
                )
            self._instrument_subscriptions_started = False
        if self._rtds_subscription_started:
            client_id = polymarket_rtds_data_client_id(self.settings.markets.timeframes)
            for data_type in self._rtds_data_types:
                self.unsubscribe_data(data_type, client_id=client_id)
            self._rtds_data_types = ()
            self._rtds_subscription_started = False

    def _schedule_startup_replay(self, exited_condition_ids: tuple[str, ...]) -> None:
        if not self.active_markets() and not exited_condition_ids:
            return
        generation = self._lifecycle_generation
        self._startup_restored_condition_ids = (
            tuple(self._active_by_condition) if self._loaded_from_state else ()
        )
        self._startup_exited_condition_ids = exited_condition_ids
        self._startup_replay_generation = generation
        _ = self.clock.set_time_alert_ns(  # pyright: ignore[reportAny]
            _STARTUP_REPLAY_TIMER_NAME,
            self.clock.timestamp_ns() + 1,  # pyright: ignore[reportAny]
            callback=partial(self._on_startup_replay, generation),
        )
        self._startup_replay_scheduled = True

    def _on_startup_replay(self, generation: int, _event: object) -> None:
        if (
            not self._startup_replay_scheduled
            or self._startup_replay_generation != generation
            or self._lifecycle_generation != generation
        ):
            return
        exited_condition_ids = tuple(
            dict.fromkeys(
                (
                    *self._startup_exited_condition_ids,
                    *self._startup_restored_condition_ids,
                )
            )
        )
        self._startup_replay_scheduled = False
        self._startup_exited_condition_ids = ()
        self._startup_restored_condition_ids = ()
        self._startup_replay_generation = None
        now = self._framework_now()
        self._publish_startup_universe(
            now=now,
            exited_condition_ids=exited_condition_ids,
        )
        self._publish_price_to_beat_batch_sync(self.active_markets())

    def _merge_startup_exits(self, exited_condition_ids: list[str]) -> None:
        if not self._startup_replay_scheduled or not exited_condition_ids:
            return
        self._startup_exited_condition_ids = tuple(
            dict.fromkeys((*self._startup_exited_condition_ids, *exited_condition_ids))
        )

    def _retire_condition(
        self,
        condition_id: str,
        exited_condition_ids: list[str],
    ) -> None:
        removed = self._active_by_condition.pop(condition_id, None)
        _ = self._last_published_ptb.pop(condition_id, None)
        if removed is not None and condition_id not in exited_condition_ids:
            exited_condition_ids.append(condition_id)

    def _publish_market_exits(
        self,
        exited_condition_ids: tuple[str, ...],
        *,
        now: datetime,
    ) -> None:
        if not exited_condition_ids:
            return
        self._epoch += 1
        self.publisher.publish_market_universe(
            _market_universe(
                self.active_markets(),
                epoch=self._epoch,
                entered_condition_ids=(),
                exited_condition_ids=exited_condition_ids,
                timestamp=now,
            )
        )

    def _on_market_expiry_timer(self, _event: object) -> None:
        now = self._framework_now()
        exited_condition_ids = self._retire_expired_markets(now)
        if not exited_condition_ids:
            return
        self._epoch += 1
        self.publisher.publish_market_universe(
            _market_universe(
                self.active_markets(),
                epoch=self._epoch,
                entered_condition_ids=(),
                exited_condition_ids=exited_condition_ids,
                timestamp=now,
            )
        )

    def on_save(self) -> dict[str, bytes]:
        payload: dict[str, JsonValue] = {
            "epoch": self._epoch,
            "terminal_condition_ids": list(
                self._instrument_markets.terminal_condition_ids()
            ),
            "active_markets": [
                cast(JsonValue, market.model_dump(mode="json"))
                for market in self._active_by_condition.values()
            ],
        }
        return encode_state(
            self.state_name,
            payload,
            version=_MARKET_ROTATION_STATE_VERSION,
        )

    def on_load(self, state: Mapping[str, bytes]) -> None:
        payload = cast(
            Mapping[str, object],
            decode_state(
                self.state_name,
                state,
                version=_MARKET_ROTATION_STATE_VERSION,
            ),
        )
        self._instrument_markets.restore_terminal_conditions(
            payload.get("terminal_condition_ids")
        )
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

    def _retire_expired_markets(self, now: datetime) -> tuple[str, ...]:
        expired = tuple(
            condition_id
            for condition_id, market in self._active_by_condition.items()
            if market.end_ts is not None and now >= market.end_ts
        )
        for condition_id in expired:
            _ = self._active_by_condition.pop(condition_id, None)
            _ = self._last_published_ptb.pop(condition_id, None)
        return expired

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


def _market_universe(
    markets: tuple[Market, ...],
    *,
    epoch: int,
    entered_condition_ids: tuple[str, ...],
    exited_condition_ids: tuple[str, ...] = (),
    timestamp: datetime,
) -> PolySignalMarketUniverseData:
    event_ns = timestamp_ns(timestamp)
    return PolySignalMarketUniverseData(
        epoch=epoch,
        active_condition_ids=tuple(market.condition_id for market in markets),
        entered_condition_ids=entered_condition_ids,
        exited_condition_ids=exited_condition_ids,
        condition_to_up_token={
            market.condition_id: market.token_for(Side.UP).token_id
            for market in markets
        },
        condition_to_down_token={
            market.condition_id: market.token_for(Side.DOWN).token_id
            for market in markets
        },
        condition_to_asset={market.condition_id: market.asset for market in markets},
        condition_to_timeframe={
            market.condition_id: market.timeframe for market in markets
        },
        ts_event=event_ns,
        ts_init=event_ns,
    )


def _market_metadata_signature(market: Market) -> tuple[object, ...]:
    return (
        market.market_id,
        market.market_slug,
        market.condition_id,
        market.question_id,
        market.question,
        market.asset,
        market.timeframe,
        market.start_ts,
        market.end_ts,
        tuple(
            (token.token_id, token.side, token.outcome_name, token.market_id)
            for token in market.outcome_tokens
        ),
    )


def _markets_by_condition(
    markets: tuple[Market, ...] | list[Market],
) -> dict[str, Market]:
    return {market.condition_id: market for market in markets if market.condition_id}
