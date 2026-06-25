from __future__ import annotations

from collections.abc import Sequence

from polysignal_lab.alpha.fibonacci_core import FibonacciAlphaCore
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.strategies.base import DEFAULT_DATA_NAMES, PolySignalNautilusStrategy
from polysignal_lab.strategies.config import FibonacciBotConfig


class FibonacciBotNautilusStrategy(PolySignalNautilusStrategy):
    def __init__(self, *, config: FibonacciBotConfig | None = None, assembler: MarketViewAssembler, condition_ids: Sequence[str], **kwargs) -> None:
        cfg = config or FibonacciBotConfig()
        super().__init__(core=FibonacciAlphaCore(cfg), assembler=assembler, condition_ids=condition_ids, strategy_name="fibonacci_bot", data_names=DEFAULT_DATA_NAMES, **kwargs)
        self.config = cfg
