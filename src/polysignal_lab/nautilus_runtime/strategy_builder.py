"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Callable, typing, typing.cast, polysignal_lab.alpha.types, polysignal_lab.alpha.types.AlphaCore
Output: AlphaCoreRegistry
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""


from __future__ import annotations

from collections.abc import Callable
from typing import cast

from polysignal_lab.alpha.types import AlphaCore


class AlphaCoreRegistry:
    _registry: dict[str, type[AlphaCore]] = {}
    _initialized = False

    @classmethod
    def register(cls, name: str, core_cls: type[AlphaCore]) -> None:
        cls._registry[name] = core_cls

    @classmethod
    def _ensure_core_registry(cls) -> None:
        if cls._initialized:
            return
        from polysignal_lab.alpha.binary_momentum_core import BinaryMomentumAlphaCore
        from polysignal_lab.alpha.dump_hedge_core import DumpHedgeAlphaCore
        from polysignal_lab.alpha.fibonacci_core import FibonacciAlphaCore
        from polysignal_lab.alpha.late_consensus_core import LateConsensusAlphaCore
        from polysignal_lab.alpha.low_side_dual_reversion_core import (
            LowSideDualReversionAlphaCore,
        )
        from polysignal_lab.alpha.mid_price_sizing_core import MidPriceSizingAlphaCore
        from polysignal_lab.alpha.ninety_nine_cent_sniper_core import (
            NinetyNineCentSniperAlphaCore,
        )
        from polysignal_lab.alpha.one_cent_buy_core import OneCentBuyAlphaCore
        from polysignal_lab.alpha.pre_order_market_core import PreOrderMarketAlphaCore
        from polysignal_lab.alpha.ptb_diff_core import PTBDiffAlphaCore
        from polysignal_lab.alpha.skew_mean_reversion_core import SkewMeanReversionAlphaCore
        from polysignal_lab.alpha.vwap_momentum_core import VWAPMomentumAlphaCore

        cls._registry.update(
            {
                "ptb_diff": PTBDiffAlphaCore,
                "skew_mean_reversion": SkewMeanReversionAlphaCore,
                "binary_momentum": BinaryMomentumAlphaCore,
                "fibonacci_bot": FibonacciAlphaCore,
                "one_cent_buy": OneCentBuyAlphaCore,
                "ninety_nine_cent_sniper": NinetyNineCentSniperAlphaCore,
                "late_consensus": LateConsensusAlphaCore,
                "vwap_momentum": VWAPMomentumAlphaCore,
                "dump_hedge": DumpHedgeAlphaCore,
                "mid_price_sizing": MidPriceSizingAlphaCore,
                "pre_order_market": PreOrderMarketAlphaCore,
                "low_side_dual_reversion": LowSideDualReversionAlphaCore,
            }
        )
        cls._initialized = True

    @classmethod
    def build(cls, name: str, config: object) -> AlphaCore | None:
        cls._ensure_core_registry()
        factory = cls._registry.get(name)
        if factory is None:
            return None
        builder = cast(Callable[[object], AlphaCore], factory)
        return builder(config)

    @classmethod
    def names(cls) -> tuple[str, ...]:
        cls._ensure_core_registry()
        return tuple(cls._registry)


def _native_core_for(name: str, config: object) -> AlphaCore | None:
    return AlphaCoreRegistry.build(name, config)
