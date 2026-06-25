from __future__ import annotations

from collections.abc import Sequence

from polysignal_lab.alpha.late_consensus_core import LateConsensusAlphaCore
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.strategies.base import DEFAULT_DATA_NAMES, PolySignalNautilusStrategy
from polysignal_lab.strategies.config import LateConsensusConfig


class LateConsensusNautilusStrategy(PolySignalNautilusStrategy):
    def __init__(self, *, config: LateConsensusConfig | None = None, assembler: MarketViewAssembler, condition_ids: Sequence[str], **kwargs) -> None:
        cfg = config or LateConsensusConfig()
        super().__init__(core=LateConsensusAlphaCore(cfg), assembler=assembler, condition_ids=condition_ids, strategy_name="late_consensus", data_names=DEFAULT_DATA_NAMES, **kwargs)
        self.config = cfg
