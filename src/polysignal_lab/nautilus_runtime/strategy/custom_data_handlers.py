"""
Input: polysignal_lab.nautilus_runtime.custom_data_types, polysignal_lab.nautilus_bridge.market_catalog
Output: custom data routing helpers for PolySignalNativeStrategy
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from typing import Callable, Protocol

from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog, MarketPairMeta
from polysignal_lab.nautilus_runtime.custom_data_state import StrategyCustomDataState
from polysignal_lab.nautilus_runtime.custom_data_types import (
    PolySignalMarketMetaData,
    PolySignalMarketUniverseData,
    PolySignalPriceToBeatData,
    PolySignalSpotData,
)
from polysignal_lab.nautilus_runtime.strategy.data_boundary import DataBoundaryClassification
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
    _subscription_manager: _SubscriptionManagerLike

    def evaluate_condition(self, condition_id: str) -> None: ...
    def _note_runtime_progress(self, phase: str) -> None: ...
    def _note_runtime_readiness(self, condition_id: str, *, ready: bool) -> None: ...
    def _require_registry(self) -> MarketCatalog: ...
    def _require_assembler(self) -> object: ...
    def _refresh_asset_conditions(self) -> None: ...
    def _subscribe_market_conditions(self, condition_ids: tuple[str, ...] | list[str]) -> None: ...
    def _unsubscribe_market_conditions(self, condition_ids: tuple[str, ...] | list[str]) -> None: ...


class _SubscriptionManagerLike(Protocol):
    def retry_instrument_requests(self, condition_ids: tuple[str, ...]) -> None: ...


def route_strategy_data(
    strategy: _CustomDataStrategy,
    data: object,
    *,
    classify: Callable[[object], DataBoundaryClassification],
) -> None:
    if classify(data) is DataBoundaryClassification.DROPPED_FRAME:
        strategy._note_runtime_progress("dropped_frame")
        return
    if handle_custom_data(
        strategy,
        data,
        subscription_manager=strategy._subscription_manager,
    ):
        return
    if isinstance(data, PolySignalMarketMetaData):
        if handle_market_metadata(strategy, data):
            return
    if isinstance(data, PolySignalMarketUniverseData):
        if handle_market_universe(strategy, data):
            return
    handle_generic_data(strategy, data)


def handle_custom_data(
    strategy: _CustomDataStrategy,
    data: object,
    *,
    subscription_manager: _SubscriptionManagerLike,
) -> bool:
    if not isinstance(data, (PolySignalSpotData, PolySignalPriceToBeatData)):
        return False
    result = strategy.custom_data.apply(data)
    if result.spot_asset is not None:
        for candidate in strategy._asset_condition_ids.get(result.spot_asset, ()):
            strategy.evaluate_condition(candidate)
        return True
    if result.price_to_beat_condition_id is not None:
        subscription_manager.retry_instrument_requests(
            (result.price_to_beat_condition_id,)
        )
        strategy.evaluate_condition(result.price_to_beat_condition_id)
        return True
    return True


def handle_market_metadata(strategy: _CustomDataStrategy, data: PolySignalMarketMetaData) -> bool:
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
    if strategy._market_epoch is not None and data.epoch <= strategy._market_epoch:
        return True
    strategy._market_epoch = data.epoch
    strategy._active_condition_ids = set(data.active_condition_ids)
    strategy._refresh_asset_conditions()
    for condition_id in data.exited_condition_ids:
        strategy._subscription_state.pending_metadata_condition_ids.discard(condition_id)
        strategy._subscription_state.pending_subscribe_condition_ids.discard(condition_id)
        retire_market_book_generation(strategy, condition_id)
        strategy._note_runtime_readiness(condition_id, ready=True)
    if strategy.unsubscribe_exited:
        strategy._unsubscribe_market_conditions(data.exited_condition_ids)
    strategy._subscribe_market_conditions(tuple(strategy._active_condition_ids))
    return True


def handle_generic_data(strategy: _CustomDataStrategy, data: object) -> None:
    assembler = strategy._require_assembler()
    updater = getattr(assembler, "on_data", None) or getattr(assembler, "update", None)
    if callable(updater):
        _ = updater(data)
    condition_id = getattr(data, "condition_id", None)
    if condition_id is not None:
        strategy.evaluate_condition(str(condition_id))
        return
    for candidate in strategy._active_condition_ids:
        strategy.evaluate_condition(candidate)
