"""
Input: __future__, __future__.annotations, typing, typing.assert_never, polysignal_lab.config, polysignal_lab.config.StrategyConfig, polysignal_lab.strategies.base, polysignal_lab.strategies.base.BaseStrategy, polysignal_lab.strategies.binary_momentum, polysignal_lab.strategies.binary_momentum.BinaryMomentumStrategy
Output: build_strategies, build_strategy
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

from typing import assert_never

from polysignal_lab.config import StrategyConfig
from polysignal_lab.strategies.base import BaseStrategy
from polysignal_lab.strategies.binary_momentum import BinaryMomentumStrategy
from polysignal_lab.strategies.config import (
    BinaryMomentumConfig,
    CrossMarketBotConfig,
    DumpHedgeConfig,
    FibonacciBotConfig,
    LateConsensusConfig,
    LowSideDualReversionConfig,
    MidPriceSizingConfig,
    NinetyNineCentSniperConfig,
    OneCentBuyConfig,
    PTBDiffConfig,
    PreOrderMarketConfig,
    SkewMeanReversionConfig,
    VWAPMomentumConfig,
)
from polysignal_lab.strategies.cross_market_bot import CrossMarketBotStrategy
from polysignal_lab.strategies.dump_hedge import DumpHedgeStrategy
from polysignal_lab.strategies.fibonacci_bot import FibonacciStrategyBot
from polysignal_lab.strategies.late_consensus import LateConsensusStrategy
from polysignal_lab.strategies.low_side_dual_reversion import LowSideDualReversionStrategy
from polysignal_lab.strategies.mid_price_sizing import MidPriceSizingStrategy
from polysignal_lab.strategies.ninety_nine_cent_sniper import NinetyNineCentSniperStrategy
from polysignal_lab.strategies.one_cent_buy import OneCentBuyStrategy
from polysignal_lab.strategies.pre_order_market import PreOrderMarketStrategy
from polysignal_lab.strategies.ptb_diff import PTBDiffStrategy
from polysignal_lab.strategies.skew_mean_reversion import SkewMeanReversionStrategy
from polysignal_lab.strategies.vwap_momentum import VWAPMomentumStrategy

StrategyConfigModel = (
    VWAPMomentumConfig
    | LateConsensusConfig
    | PTBDiffConfig
    | BinaryMomentumConfig
    | CrossMarketBotConfig
    | DumpHedgeConfig
    | FibonacciBotConfig
    | LowSideDualReversionConfig
    | MidPriceSizingConfig
    | NinetyNineCentSniperConfig
    | OneCentBuyConfig
    | PreOrderMarketConfig
    | SkewMeanReversionConfig
)

_STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {
    "vwap_momentum": VWAPMomentumStrategy,
    "late_consensus": LateConsensusStrategy,
    "ptb_diff": PTBDiffStrategy,
    "binary_momentum": BinaryMomentumStrategy,
    "cross_market_bot": CrossMarketBotStrategy,
    "dump_hedge": DumpHedgeStrategy,
    "fibonacci_bot": FibonacciStrategyBot,
    "low_side_dual_reversion": LowSideDualReversionStrategy,
    "mid_price_sizing": MidPriceSizingStrategy,
    "ninety_nine_cent_sniper": NinetyNineCentSniperStrategy,
    "one_cent_buy": OneCentBuyStrategy,
    "pre_order_market": PreOrderMarketStrategy,
    "skew_mean_reversion": SkewMeanReversionStrategy,
}


def build_strategies(config: StrategyConfig) -> list[BaseStrategy]:
    strategies: list[BaseStrategy] = []
    for name in config.explicit_strategy_names():
        strategy_cls = _STRATEGY_REGISTRY.get(name)
        if strategy_cls is None:
            raise ValueError(
                f"Strategy {name!r} has config but no registered implementation"
            )
        cfg = getattr(config, name)
        if getattr(cfg, "enabled", False):
            strategies.append(strategy_cls(cfg))
    return strategies


def build_strategy(config: StrategyConfigModel) -> BaseStrategy:
    match config:
        case VWAPMomentumConfig():
            return VWAPMomentumStrategy(config)
        case LateConsensusConfig():
            return LateConsensusStrategy(config)
        case PTBDiffConfig():
            return PTBDiffStrategy(config)
        case BinaryMomentumConfig():
            return BinaryMomentumStrategy(config)
        case CrossMarketBotConfig():
            return CrossMarketBotStrategy(config)
        case DumpHedgeConfig():
            return DumpHedgeStrategy(config)
        case FibonacciBotConfig():
            return FibonacciStrategyBot(config)
        case LowSideDualReversionConfig():
            return LowSideDualReversionStrategy(config)
        case MidPriceSizingConfig():
            return MidPriceSizingStrategy(config)
        case NinetyNineCentSniperConfig():
            return NinetyNineCentSniperStrategy(config)
        case OneCentBuyConfig():
            return OneCentBuyStrategy(config)
        case PreOrderMarketConfig():
            return PreOrderMarketStrategy(config)
        case SkewMeanReversionConfig():
            return SkewMeanReversionStrategy(config)
        case unreachable:
            assert_never(unreachable)
