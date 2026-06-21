from __future__ import annotations

from polysignal_lab.config import StrategyConfig
from polysignal_lab.strategies.base import BaseStrategy
from polysignal_lab.strategies.late_consensus import LateConsensusStrategy
from polysignal_lab.strategies.ptb_diff import PTBDiffStrategy
from polysignal_lab.strategies.skew_mean_reversion import SkewMeanReversionStrategy
from polysignal_lab.strategies.vwap_momentum import VWAPMomentumStrategy


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
    return strategies
