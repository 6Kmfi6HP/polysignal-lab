from __future__ import annotations

from collections.abc import Sequence

from polysignal_lab.alpha.skew_mean_reversion_core import SkewMeanReversionAlphaCore
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.strategies.base import DEFAULT_DATA_NAMES, PolySignalNautilusStrategy
from polysignal_lab.strategies.config import SkewMeanReversionConfig


class SkewMeanReversionNautilusStrategy(PolySignalNautilusStrategy):
    def __init__(self, *, config: SkewMeanReversionConfig | None = None, assembler: MarketViewAssembler, condition_ids: Sequence[str], **kwargs) -> None:
        cfg = config or SkewMeanReversionConfig()
        super().__init__(core=SkewMeanReversionAlphaCore(cfg), assembler=assembler, condition_ids=condition_ids, strategy_name="skew_mean_reversion", data_names=DEFAULT_DATA_NAMES, **kwargs)
        self.config = cfg
