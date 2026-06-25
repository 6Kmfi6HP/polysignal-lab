from __future__ import annotations

from collections.abc import Sequence

from polysignal_lab.alpha.binary_momentum_core import BinaryMomentumAlphaCore
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.strategies.base import DEFAULT_DATA_NAMES, PolySignalNautilusStrategy
from polysignal_lab.strategies.config import BinaryMomentumConfig


class BinaryMomentumNautilusStrategy(PolySignalNautilusStrategy):
    def __init__(self, *, config: BinaryMomentumConfig | None = None, assembler: MarketViewAssembler, condition_ids: Sequence[str], **kwargs) -> None:
        cfg = config or BinaryMomentumConfig()
        super().__init__(core=BinaryMomentumAlphaCore(cfg), assembler=assembler, condition_ids=condition_ids, strategy_name="binary_momentum", data_names=DEFAULT_DATA_NAMES, **kwargs)
        self.config = cfg
