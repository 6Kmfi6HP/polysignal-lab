"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Callable, collections.abc.Sequence, nautilus_trader.common.actor, nautilus_trader.common.actor.Actor, nautilus_trader.config, nautilus_trader.config.ActorConfig, nautilus_trader.config.StrategyConfig
Output: NautilusPolySignalNativeStrategy, NautilusMarketRotationActor, LiveDecisionPolicyActor
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from collections.abc import Callable, Sequence

from nautilus_trader.common.actor import Actor
from nautilus_trader.config import ActorConfig, StrategyConfig
from nautilus_trader.trading.strategy import Strategy

from polysignal_lab.alpha.types import AlphaCore
from polysignal_lab.config import Settings
from polysignal_lab.data.anchor_price_service import AnchorPriceStore
from polysignal_lab.domain.market import Market
from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor
from polysignal_lab.nautilus_runtime.decision_policy_actor import (
    NautilusDecisionPolicyActor as PolySignalDecisionPolicyActor,
)
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


class NautilusPolySignalNativeStrategy(PolySignalNativeStrategy, Strategy):
    """Nautilus-registerable strategy combining PolySignal domain logic with Strategy.

    Dual inheritance is used (not composition) because PolySignalNativeStrategy
    accesses Nautilus services (clock, cache, subscribe/ unsubscribe methods,
    order_factory, submit_order) through getattr(self, ...) dynamic dispatch
    and casts self to OrderSubmittingStrategy (see _submit_approved).
    Composition would require threading a Nautilus reference through hundreds
    of lines of domain code and adding forwarding methods for every protocol.
    The MRO traversal in _subscribe_custom_data (strategy/helpers.py:382)
    also explicitly depends on PolySignalNativeStrategy appearing before
    Strategy in the inheritance chain.
    """

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
        registry: MarketCatalog | None = None,
        observability: _Observability | None = None,
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
            observability=observability,
            progress_callback=progress_callback,
            unsubscribe_exited=unsubscribe_exited,
            l1_book_snapshot_interval_ms=l1_book_snapshot_interval_ms,
        )


class NautilusMarketRotationActor(MarketRotationActor, Actor):
    """Nautilus-registerable actor combining market rotation logic with Actor.

    Dual inheritance is used (not composition) because MarketRotationActor
    calls super(MarketRotationActor, self).publish_data(...) to reach the
    Nautilus Actor base class (market_rotation.py:95) and accesses self.clock
    via getattr for timer management.  These are intrinsic coupling patterns
    that composition cannot resolve without rewriting the domain class.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        startup_markets: tuple[Market, ...],
        market_universe: _MarketUniverse,
        catalog: MarketCatalog,
        anchor_store: AnchorPriceStore | None = None,
        health: _Health | None = None,
    ) -> None:
        Actor.__init__(self, config=ActorConfig())
        MarketRotationActor.__init__(
            self,
            settings=settings,
            startup_markets=startup_markets,
            market_universe=market_universe,
            catalog=catalog,
            anchor_store=anchor_store,
            health=health,
        )


class LiveDecisionPolicyActor(PolySignalDecisionPolicyActor, Actor):
    """Nautilus-registerable policy actor combining decision policy with Actor.

    Dual inheritance is used (not composition) for consistency with the
    other wrapper classes in this module and because PolySignalDecisionPolicyActor
    (NautilusDecisionPolicyActor in decision_policy_actor.py) provides on_save/
    on_load lifecycle hooks that call self.save_state()/self.load_state() from
    the DecisionPolicyActor base.  Composition would add an indirection layer
    for these two methods with no benefit -- the domain class has no Nautilus
    coupling and dual inheritance is the simplest path to Nautilus registration.
    """

    def __init__(self, **kwargs: object) -> None:
        Actor.__init__(self, config=ActorConfig())
        PolySignalDecisionPolicyActor.__init__(self, **kwargs)


# LiveDecisionPolicyActor is the Nautilus-registerable variant (inherits Actor).
# Expose under the expected name for discovery via runtime_classes.
NautilusDecisionPolicyActor = LiveDecisionPolicyActor


__all__ = (
    "LiveDecisionPolicyActor",
    "NautilusDecisionPolicyActor",
    "NautilusMarketRotationActor",
    "NautilusPolySignalNativeStrategy",
)
