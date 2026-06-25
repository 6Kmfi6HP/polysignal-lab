from __future__ import annotations

from collections.abc import Sequence

from polysignal_lab.alpha.ninety_nine_cent_sniper_core import NinetyNineCentSniperAlphaCore
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.strategies.base import DEFAULT_DATA_NAMES, PolySignalNautilusStrategy
from polysignal_lab.strategies.config import NinetyNineCentSniperConfig


class NinetyNineCentSniperNautilusStrategy(PolySignalNautilusStrategy):
    def __init__(self, *, config: NinetyNineCentSniperConfig | None = None, assembler: MarketViewAssembler, condition_ids: Sequence[str], **kwargs) -> None:
        cfg = config or NinetyNineCentSniperConfig()
        super().__init__(core=NinetyNineCentSniperAlphaCore(cfg), assembler=assembler, condition_ids=condition_ids, strategy_name="ninety_nine_cent_sniper", data_names=DEFAULT_DATA_NAMES, **kwargs)
        self.config = cfg
