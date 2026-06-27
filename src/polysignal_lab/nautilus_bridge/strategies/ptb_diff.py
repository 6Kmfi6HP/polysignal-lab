from __future__ import annotations

from collections.abc import Sequence

from polysignal_lab.alpha.ptb_diff_core import PTBDiffAlphaCore
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_bridge.strategy_base import PolySignalNautilusStrategy
from polysignal_lab.strategies.config import PTBDiffConfig


class PTBDiffNautilusStrategy(PolySignalNautilusStrategy):
    def __init__(self, *, config: PTBDiffConfig, assembler: MarketViewAssembler, condition_ids: Sequence[str]) -> None:
        super().__init__(
            core=PTBDiffAlphaCore(config),
            assembler=assembler,
            condition_ids=condition_ids,
            strategy_name="ptb_diff",
        )
