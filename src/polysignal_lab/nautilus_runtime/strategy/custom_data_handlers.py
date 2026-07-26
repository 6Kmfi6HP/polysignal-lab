from __future__ import annotations

from typing import Callable, Protocol

from polysignal_lab.alpha.types import TradingStateView
from polysignal_lab.nautilus_runtime.cache_trading_state import trading_state_from_cache
from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog, MarketPairMeta
from polysignal_lab.nautilus_runtime.custom_data_state import StrategyCustomDataState
from polysignal_lab.nautilus_runtime.custom_data_types import (
    PolySignalMarketMetaData,
    PolySignalMarketUniverseData,
    PolySignalPriceToBeatData,
    is_polymarket_rtds_crypto_price,
    unwrap_custom_data,
)
from polysignal_lab.nautilus_runtime.strategy.data_boundary import (
    DataBoundaryClassification,
)
from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
    MarketSubscriptionState,
    retire_market_book_generation,
)


class _CustomDataStrategy(Protocol):
    custom_data: StrategyCustomDataState
    registry: MarketCatalog | None
    _active_condition_ids: set[str]
    _asset_condition_ids: dict[str, tuple[str, ...]]
    _market_epoch: int | None
    unsubscribe_exited: bool
    _subscription_state: MarketSubscriptionState
    cache: object | None

    def evaluate_condition(
        self,
        condition_id: str,
        *,
        trading_state: object | None = None,
    ) -> None: ...
    def _note_runtime_progress(self, phase: str) -> None: ...
    def _note_runtime_readiness(self, condition_id: str, *, ready: bool) -> None: ...
    def _require_registry(self) -> MarketCatalog: ...
    def _require_assembler(self) -> object: ...
    def _refresh_asset_conditions(self) -> None: ...
    def _subscribe_market_conditions(
        self, condition_ids: tuple[str, ...] | list[str]
    ) -> None: ...
    def _unsubscribe_market_conditions(
        self, condition_ids: tuple[str, ...] | list[str]
    ) -> None: ...


def route_strategy_data(
    strategy: _CustomDataStrategy,
    data: object,
    *,
    classify: Callable[[object], DataBoundaryClassification],
) -> None:
    payload = unwrap_custom_data(data)
    if classify(payload) is DataBoundaryClassification.DROPPED_FRAME:
        strategy._note_runtime_progress("dropped_frame")
        return
    if handle_custom_data(strategy, payload):
        return
    if isinstance(payload, PolySignalMarketMetaData):
        if handle_market_metadata(strategy, payload):
            return
    if isinstance(payload, PolySignalMarketUniverseData):
        if handle_market_universe(strategy, payload):
            return
    handle_generic_data(strategy, payload)


def handle_custom_data(
    strategy: _CustomDataStrategy,
    data: object,
) -> bool:
    if not (
        is_polymarket_rtds_crypto_price(data)
        or isinstance(data, PolySignalPriceToBeatData)
    ):
        return False
    result = strategy.custom_data.apply(data)
    if result.spot_asset is not None:
        candidates = strategy._asset_condition_ids.get(result.spot_asset, ())
        trading_state = _trading_state_snapshot(strategy) if candidates else None
        for candidate in candidates:
            strategy.evaluate_condition(candidate, trading_state=trading_state)
        return True
    if result.price_to_beat_condition_id is not None:
        strategy.evaluate_condition(result.price_to_beat_condition_id)
        return True
    return True


def _trading_state_snapshot(strategy: _CustomDataStrategy) -> TradingStateView:
    return trading_state_from_cache(
        strategy.cache,
        strategy_id=getattr(strategy, "strategy_id", None)
        or getattr(strategy, "id", None),
        registry=strategy._require_registry(),
    )


def handle_market_metadata(
    strategy: _CustomDataStrategy, data: PolySignalMarketMetaData
) -> bool:
    """Catalog registration for business keys (not Gamma discovery transport)."""
    registry = strategy._require_registry()
    registry.register(MarketPairMeta.from_metadata(data))
    strategy._refresh_asset_conditions()
    if data.condition_id in strategy._active_condition_ids:
        strategy._subscribe_market_conditions((data.condition_id,))
    return True


def handle_market_universe(
    strategy: _CustomDataStrategy,
    data: PolySignalMarketUniverseData,
) -> bool:
    """Active-set update for condition_ids (discovery worker removed)."""
    if strategy._market_epoch is not None and data.epoch <= strategy._market_epoch:
        return True
    strategy._market_epoch = data.epoch
    active_condition_ids = set(data.active_condition_ids)
    exited_condition_ids = tuple(
        sorted(
            set(data.exited_condition_ids)
            | (strategy._active_condition_ids - active_condition_ids)
        )
    )
    strategy._active_condition_ids = active_condition_ids
    strategy._refresh_asset_conditions()
    for condition_id in exited_condition_ids:
        strategy._subscription_state.pending_metadata_condition_ids.discard(
            condition_id
        )
        retire_market_book_generation(strategy, condition_id)
        strategy._note_runtime_readiness(condition_id, ready=True)
    if strategy.unsubscribe_exited:
        strategy._unsubscribe_market_conditions(exited_condition_ids)
    strategy._subscribe_market_conditions(tuple(strategy._active_condition_ids))
    return True


def handle_generic_data(strategy: _CustomDataStrategy, data: object) -> None:
    _ = data
    strategy._note_runtime_progress("dropped_frame")
