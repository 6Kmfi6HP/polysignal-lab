from __future__ import annotations

from collections.abc import Sequence

from polysignal_lab.alpha.pre_order_market_core import PreOrderMarketAlphaCore
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.strategies.base import DEFAULT_DATA_NAMES, PolySignalNautilusStrategy
from polysignal_lab.strategies.config import PreOrderMarketConfig


class PreOrderMarketNautilusStrategy(PolySignalNautilusStrategy):
    def __init__(self, *, config: PreOrderMarketConfig | None = None, assembler: MarketViewAssembler, condition_ids: Sequence[str], **kwargs) -> None:
        cfg = config or PreOrderMarketConfig()
        super().__init__(core=PreOrderMarketAlphaCore(cfg), assembler=assembler, condition_ids=condition_ids, strategy_name="pre_order_market", data_names=DEFAULT_DATA_NAMES, **kwargs)
        self.config = cfg
