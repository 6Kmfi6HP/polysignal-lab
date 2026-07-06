from __future__ import annotations

from collections.abc import Callable, Sequence

from nautilus_trader.common.actor import Actor
from nautilus_trader.config import ActorConfig, StrategyConfig
from nautilus_trader.trading.strategy import Strategy

from polysignal_lab.alpha.types import AlphaCore
from polysignal_lab.config import Settings
from polysignal_lab.data.anchor_price_service import AnchorPriceStore
from polysignal_lab.domain.market import Market
from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
from polysignal_lab.nautilus_bridge.market_registry import PolymarketMarketRegistry
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor
from polysignal_lab.nautilus_runtime.market_rotation import (
    MarketRotationActor,
    _Health,
    _MarketUniverse,
)
from polysignal_lab.nautilus_runtime.native_strategy import (
    DEFAULT_NATIVE_DATA_NAMES,
    DEFAULT_L1_BOOK_SNAPSHOT_INTERVAL_MS,
    PolySignalNativeStrategy,
    _Assembler,
    _Observability,
)
from polysignal_lab.nautilus_runtime.sidecar_data import PolySignalRuntimeSidecarActor


class NautilusPolySignalNativeStrategy(PolySignalNativeStrategy, Strategy):
    def __init__(
        self,
        *,
        core: AlphaCore,
        assembler: _Assembler | None,
        condition_ids: Sequence[str],
        strategy_name: str,
        policy: DecisionPolicyActor | None = None,
        fixed_stake_usdc: float = 10.0,
        data_names: Sequence[str] = DEFAULT_NATIVE_DATA_NAMES,
        book_type: str = "L2_MBP",
        instrument_id_resolver: Callable[[str], object] | None = None,
        registry: PolymarketMarketRegistry | None = None,
        sidecar: ExternalDataSidecar | None = None,
        observability: _Observability | None = None,
        exit_model: object | None = None,
        progress_callback: Callable[[str], None] | None = None,
        unsubscribe_exited: bool = True,
        l1_book_snapshot_interval_ms: int = DEFAULT_L1_BOOK_SNAPSHOT_INTERVAL_MS,
    ) -> None:
        Strategy.__init__(self, config=StrategyConfig())
        PolySignalNativeStrategy.__init__(
            self,
            core=core,
            assembler=assembler,
            condition_ids=condition_ids,
            strategy_name=strategy_name,
            policy=policy,
            fixed_stake_usdc=fixed_stake_usdc,
            data_names=data_names,
            book_type=book_type,
            instrument_id_resolver=instrument_id_resolver,
            registry=registry,
            sidecar=sidecar,
            observability=observability,
            exit_model=exit_model,
            progress_callback=progress_callback,
            unsubscribe_exited=unsubscribe_exited,
            l1_book_snapshot_interval_ms=l1_book_snapshot_interval_ms,
        )


class NautilusMarketRotationActor(MarketRotationActor, Actor):
    def __init__(
        self,
        *,
        settings: Settings,
        startup_markets: tuple[Market, ...],
        market_universe: _MarketUniverse,
        registry: PolymarketMarketRegistry,
        sidecar: ExternalDataSidecar,
        anchor_store: AnchorPriceStore | None = None,
        health: _Health | None = None,
    ) -> None:
        Actor.__init__(self, config=ActorConfig())
        MarketRotationActor.__init__(
            self,
            settings=settings,
            startup_markets=startup_markets,
            market_universe=market_universe,
            registry=registry,
            sidecar=sidecar,
            anchor_store=anchor_store,
            health=health,
        )


class NautilusPolySignalRuntimeSidecarActor(PolySignalRuntimeSidecarActor, Actor):
    def __init__(
        self,
        *,
        settings: Settings,
        markets: tuple[Market, ...],
        registry: PolymarketMarketRegistry,
        sidecar: ExternalDataSidecar,
        anchor_store: AnchorPriceStore | None = None,
    ) -> None:
        Actor.__init__(self, config=ActorConfig())
        PolySignalRuntimeSidecarActor.__init__(
            self,
            settings=settings,
            markets=markets,
            registry=registry,
            sidecar=sidecar,
            anchor_store=anchor_store,
        )


__all__ = (
    "NautilusMarketRotationActor",
    "NautilusPolySignalNativeStrategy",
    "NautilusPolySignalRuntimeSidecarActor",
)
