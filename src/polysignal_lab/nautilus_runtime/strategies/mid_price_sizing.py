from __future__ import annotations

from collections.abc import Sequence

from polysignal_lab.alpha.mid_price_sizing_core import MidPriceSizingAlphaCore
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.strategies.base import DEFAULT_DATA_NAMES, PolySignalNautilusStrategy
from polysignal_lab.strategies.config import MidPriceSizingConfig


class MidPriceSizingNautilusStrategy(PolySignalNautilusStrategy):
    def __init__(self, *, config: MidPriceSizingConfig | None = None, assembler: MarketViewAssembler, condition_ids: Sequence[str], **kwargs) -> None:
        cfg = config or MidPriceSizingConfig()
        super().__init__(core=MidPriceSizingAlphaCore(cfg), assembler=assembler, condition_ids=condition_ids, strategy_name="mid_price_sizing", data_names=DEFAULT_DATA_NAMES, **kwargs)
        self.config = cfg
