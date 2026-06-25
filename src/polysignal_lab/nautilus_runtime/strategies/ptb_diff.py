from __future__ import annotations

from collections.abc import Sequence

from polysignal_lab.alpha.ptb_diff_core import PTBDiffAlphaCore
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.strategies.base import DEFAULT_DATA_NAMES, PolySignalNautilusStrategy
from polysignal_lab.strategies.config import PTBDiffConfig


class PTBDiffNautilusStrategy(PolySignalNautilusStrategy):
    def __init__(self, *, config: PTBDiffConfig | None = None, assembler: MarketViewAssembler, condition_ids: Sequence[str], **kwargs) -> None:
        cfg = config or PTBDiffConfig()
        super().__init__(core=PTBDiffAlphaCore(cfg), assembler=assembler, condition_ids=condition_ids, strategy_name="ptb_diff", data_names=DEFAULT_DATA_NAMES, **kwargs)
        self.config = cfg
