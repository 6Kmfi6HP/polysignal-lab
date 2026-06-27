from __future__ import annotations

from typing import Any


class NautilusCacheReader:
    """Read-only projection adapter over a Nautilus cache/portfolio interface."""

    def __init__(self, cache: Any, *, portfolio: Any = None) -> None:
        self._cache = cache
        self._portfolio = portfolio

    def read_orders(self) -> list[dict[str, object]]:
        cache_orders = getattr(self._cache, "orders", None)
        if callable(cache_orders):
            return [self._project_order(o) for o in cache_orders()]
        return []

    def read_fills(self) -> list[dict[str, object]]:
        cache_fills = getattr(self._cache, "fills", None)
        if callable(cache_fills):
            return [self._project_fill(f) for f in cache_fills()]
        return []

    def read_positions(self) -> list[dict[str, object]]:
        cache_positions = getattr(self._cache, "positions", None)
        if callable(cache_positions):
            return [self._project_position(p) for p in cache_positions()]
        return []

    def read_account(self) -> object:
        account = getattr(self._cache, "account", None)
        if callable(account):
            return account()
        return None

    def snapshot_portfolio(self) -> object:
        source = self._portfolio
        if source is None:
            source = getattr(self._cache, "portfolio", None)
        if source is None:
            return None
        if callable(source):
            return source()
        return source

    @staticmethod
    def _project_order(order: Any) -> dict[str, object]:
        from polysignal_lab.nautilus_runtime.projections import project_order_event
        return project_order_event(order)

    @staticmethod
    def _project_fill(fill: Any) -> dict[str, object]:
        from polysignal_lab.nautilus_runtime.projections import project_fill_event
        return project_fill_event(fill)

    @staticmethod
    def _project_position(position: Any) -> dict[str, object]:
        from polysignal_lab.nautilus_runtime.projections import project_position
        return project_position(position)
