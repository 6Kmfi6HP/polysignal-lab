from __future__ import annotations

from collections.abc import Sequence

from polysignal_lab.alpha.vwap_momentum_core import VWAPMomentumAlphaCore
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.strategies.base import DEFAULT_DATA_NAMES, PolySignalNautilusStrategy
from polysignal_lab.strategies.config import VWAPMomentumConfig


class VWAPMomentumNautilusStrategy(PolySignalNautilusStrategy):
    def __init__(self, *, config: VWAPMomentumConfig | None = None, assembler: MarketViewAssembler, condition_ids: Sequence[str], **kwargs) -> None:
        cfg = config or VWAPMomentumConfig()
        super().__init__(core=VWAPMomentumAlphaCore(cfg), assembler=assembler, condition_ids=condition_ids, strategy_name="vwap_momentum", data_names=DEFAULT_DATA_NAMES, **kwargs)
        self.config = cfg
