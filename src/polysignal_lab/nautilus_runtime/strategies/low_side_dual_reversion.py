from __future__ import annotations

from collections.abc import Sequence

from polysignal_lab.alpha.low_side_dual_reversion_core import LowSideDualReversionAlphaCore
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.strategies.base import DEFAULT_DATA_NAMES, PolySignalNautilusStrategy
from polysignal_lab.strategies.config import LowSideDualReversionConfig


class LowSideDualReversionNautilusStrategy(PolySignalNautilusStrategy):
    def __init__(self, *, config: LowSideDualReversionConfig | None = None, assembler: MarketViewAssembler, condition_ids: Sequence[str], **kwargs) -> None:
        cfg = config or LowSideDualReversionConfig()
        super().__init__(core=LowSideDualReversionAlphaCore(cfg), assembler=assembler, condition_ids=condition_ids, strategy_name="low_side_dual_reversion", data_names=DEFAULT_DATA_NAMES, **kwargs)
        self.config = cfg
