"""Nautilus strategy wrappers."""

from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

DEFAULT_DATA_NAMES = (
    "order_book_deltas",
    "order_book_depth",
    "spot_prices",
    "price_to_beat",
)

__all__ = [
    "DEFAULT_DATA_NAMES",
    "PolySignalNativeStrategy",
]
