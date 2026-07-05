from __future__ import annotations

from collections.abc import Callable, Sequence

from polysignal_lab.alpha.skew_mean_reversion_core import SkewMeanReversionAlphaCore
from polysignal_lab.alpha.types import NautilusOrderSpec
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor
from polysignal_lab.nautilus_runtime.strategies.base import DEFAULT_DATA_NAMES, PolySignalNautilusStrategy
from polysignal_lab.strategies.config import SkewMeanReversionConfig


class SkewMeanReversionNautilusStrategy(PolySignalNautilusStrategy):
    def __init__(
        self,
        *,
        config: SkewMeanReversionConfig | None = None,
        assembler: MarketViewAssembler,
        condition_ids: Sequence[str],
        policy: DecisionPolicyActor | None = None,
        submitter: Callable[[NautilusOrderSpec], object] | None = None,
        fixed_stake_usdc: float = 10.0,
        data_names: Sequence[str] = DEFAULT_DATA_NAMES,
    ) -> None:
        cfg = config or SkewMeanReversionConfig()
        super().__init__(
            core=SkewMeanReversionAlphaCore(cfg),
            assembler=assembler,
            condition_ids=condition_ids,
            strategy_name="skew_mean_reversion",
            data_names=data_names,
            policy=policy,
            submitter=submitter,
            fixed_stake_usdc=fixed_stake_usdc,
        )
        self.config: SkewMeanReversionConfig = cfg
