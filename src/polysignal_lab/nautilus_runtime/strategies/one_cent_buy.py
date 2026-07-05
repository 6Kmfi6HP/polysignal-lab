from __future__ import annotations

from collections.abc import Callable, Sequence

from polysignal_lab.alpha.one_cent_buy_core import OneCentBuyAlphaCore
from polysignal_lab.alpha.types import NautilusOrderSpec
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor
from polysignal_lab.nautilus_runtime.strategies.base import DEFAULT_DATA_NAMES, PolySignalNautilusStrategy
from polysignal_lab.strategies.config import OneCentBuyConfig


class OneCentBuyNautilusStrategy(PolySignalNautilusStrategy):
    def __init__(
        self,
        *,
        config: OneCentBuyConfig | None = None,
        assembler: MarketViewAssembler,
        condition_ids: Sequence[str],
        policy: DecisionPolicyActor | None = None,
        submitter: Callable[[NautilusOrderSpec], object] | None = None,
        fixed_stake_usdc: float = 10.0,
        data_names: Sequence[str] = DEFAULT_DATA_NAMES,
    ) -> None:
        cfg = config or OneCentBuyConfig()
        super().__init__(
            core=OneCentBuyAlphaCore(cfg),
            assembler=assembler,
            condition_ids=condition_ids,
            strategy_name="one_cent_buy",
            data_names=data_names,
            policy=policy,
            submitter=submitter,
            fixed_stake_usdc=fixed_stake_usdc,
        )
        self.config: OneCentBuyConfig = cfg
