from __future__ import annotations

from collections.abc import Callable, Sequence

from polysignal_lab.alpha.dump_hedge_core import DumpHedgeAlphaCore
from polysignal_lab.alpha.types import NautilusOrderSpec
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor
from polysignal_lab.nautilus_runtime.strategies.base import DEFAULT_DATA_NAMES, PolySignalNautilusStrategy
from polysignal_lab.strategies.config import DumpHedgeConfig


class DumpHedgeNautilusStrategy(PolySignalNautilusStrategy):
    def __init__(
        self,
        *,
        config: DumpHedgeConfig | None = None,
        assembler: MarketViewAssembler,
        condition_ids: Sequence[str],
        policy: DecisionPolicyActor | None = None,
        submitter: Callable[[NautilusOrderSpec], object] | None = None,
        fixed_stake_usdc: float = 10.0,
    ) -> None:
        cfg = config or DumpHedgeConfig()
        super().__init__(
            core=DumpHedgeAlphaCore(cfg),
            assembler=assembler,
            condition_ids=condition_ids,
            strategy_name="dump_hedge",
            data_names=DEFAULT_DATA_NAMES,
            policy=policy,
            submitter=submitter,
            fixed_stake_usdc=fixed_stake_usdc,
        )
        self.config: DumpHedgeConfig = cfg
