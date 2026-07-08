"""Nautilus strategy wrappers."""

from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy
from polysignal_lab.nautilus_runtime.strategies.cross_market_bot import CrossMarketNautilusStrategy

DEFAULT_DATA_NAMES = (
    "order_book_deltas",
    "order_book_depth",
    "spot_prices",
    "price_to_beat",
)

__all__ = [
    "DEFAULT_DATA_NAMES",
    "CrossMarketNautilusStrategy",
    "PolySignalNativeStrategy",
]
