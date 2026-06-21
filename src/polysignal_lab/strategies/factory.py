from __future__ import annotations

from polysignal_lab.config import StrategyConfig
from polysignal_lab.strategies.base import BaseStrategy
from polysignal_lab.strategies.late_consensus import LateConsensusStrategy
from polysignal_lab.strategies.ptb_diff import PTBDiffStrategy
from polysignal_lab.strategies.skew_mean_reversion import SkewMeanReversionStrategy
from polysignal_lab.strategies.vwap_momentum import VWAPMomentumStrategy
from polysignal_lab.strategies.one_cent_buy import OneCentBuyStrategy
from polysignal_lab.strategies.ninety_nine_cent_sniper import NinetyNineCentSniperStrategy
from polysignal_lab.strategies.binary_momentum import BinaryMomentumStrategy
from polysignal_lab.strategies.low_side_dual_reversion import LowSideDualReversionStrategy
from polysignal_lab.strategies.dump_hedge import DumpHedgeStrategy
from polysignal_lab.strategies.pre_order_market import PreOrderMarketStrategy
from polysignal_lab.strategies.cross_market_bot import CrossMarketBotStrategy
from polysignal_lab.strategies.mid_price_sizing import MidPriceSizingStrategy
from polysignal_lab.strategies.fibonacci_bot import FibonacciStrategyBot


def build_strategies(config: StrategyConfig) -> list[BaseStrategy]:
    strategies: list[BaseStrategy] = []
    if config.vwap_momentum.enabled:
        strategies.append(VWAPMomentumStrategy(config.vwap_momentum))
    if config.late_consensus.enabled:
        strategies.append(LateConsensusStrategy(config.late_consensus))
    if config.ptb_diff.enabled:
        strategies.append(PTBDiffStrategy(config.ptb_diff))
    if config.skew_mean_reversion.enabled:
        strategies.append(SkewMeanReversionStrategy(config.skew_mean_reversion))
    if config.one_cent_buy.enabled:
        strategies.append(OneCentBuyStrategy(config.one_cent_buy))
    if config.ninety_nine_cent_sniper.enabled:
        strategies.append(NinetyNineCentSniperStrategy(config.ninety_nine_cent_sniper))
    if config.binary_momentum.enabled:
        strategies.append(BinaryMomentumStrategy(config.binary_momentum))
    if config.low_side_dual_reversion.enabled:
        strategies.append(LowSideDualReversionStrategy(config.low_side_dual_reversion))
    if config.dump_hedge.enabled:
        strategies.append(DumpHedgeStrategy(config.dump_hedge))
    if config.pre_order_market.enabled:
        strategies.append(PreOrderMarketStrategy(config.pre_order_market))
    if config.cross_market_bot.enabled:
        strategies.append(CrossMarketBotStrategy(config.cross_market_bot))
    if config.mid_price_sizing.enabled:
        strategies.append(MidPriceSizingStrategy(config.mid_price_sizing))
    if config.fibonacci_bot.enabled:
        strategies.append(FibonacciStrategyBot(config.fibonacci_bot))
    return strategies
