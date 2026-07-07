"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Callable, collections.abc.Iterable, collections.abc.Mapping, typing, typing.cast
Output: NautilusCacheReader
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import cast


class NautilusCacheReader:
    """Read-only projection adapter over a Nautilus cache/portfolio interface."""

    def __init__(self, cache: object, *, portfolio: object | None = None) -> None:
        self._cache: object = cache
        self._portfolio: object | None = portfolio

    def read_orders(self) -> list[dict[str, object]]:
        return self._read_many("orders", self._project_order)

    def read_fills(self) -> list[dict[str, object]]:
        rows = self._read_many("fills", self._project_fill)
        if rows:
            return rows
        fills: list[dict[str, object]] = []
        for order in self._rows("orders"):
            events = getattr(order, "events", None)
            if not isinstance(events, Iterable) or isinstance(events, (str, bytes)):
                continue
            for event in events:
                if getattr(event, "trade_id", None) is None:
                    continue
                fills.append(self._project_fill(event))
        return fills

    def read_positions(self) -> list[dict[str, object]]:
        return self._read_many("positions", self._project_position)

    def read_account(self) -> object | None:
        account = getattr(self._cache, "account", None)
        if callable(account):
            try:
                return cast(Callable[[], object], account)()
            except TypeError:
                pass
        account_for_venue = getattr(self._cache, "account_for_venue", None)
        if callable(account_for_venue):
            try:
                result = cast(Callable[[], object], account_for_venue)()
            except TypeError:
                result = None
            if result is not None:
                return result
        accounts = getattr(self._cache, "accounts", None)
        if callable(accounts):
            rows = cast(Callable[[], object], accounts)()
            if isinstance(rows, Iterable) and not isinstance(rows, (str, bytes)):
                for row in rows:
                    return row
        load_accounts = getattr(self._cache, "load_accounts", None)
        if callable(load_accounts):
            rows = cast(Callable[[], object], load_accounts)()
            if isinstance(rows, dict):
                for row in cast(Mapping[object, object], rows).values():
                    return row
        return None

    def read_account_projection(self) -> dict[str, object] | None:
        account = self.read_account()
        if account is None:
            return None
        from polysignal_lab.nautilus_runtime.projections import project_account

        return project_account(account)

    def snapshot_portfolio_projection(self) -> dict[str, object] | None:
        source = self.snapshot_portfolio()
        if source is None:
            return None
        from polysignal_lab.nautilus_runtime.projections import project_portfolio_snapshot

        return project_portfolio_snapshot(source, account=self.read_account())
    def snapshot_portfolio(self) -> object | None:
        source = self._portfolio
        if source is None:
            source = getattr(self._cache, "portfolio", None)
        if source is None:
            return None
        if callable(source):
            return cast(Callable[[], object], source)()
        return source


    def _rows(self, name: str) -> Iterable[object]:
        source = getattr(self._cache, name, None)
        if not callable(source):
            source = getattr(self._cache, f"load_{name}", None)
        if not callable(source):
            return ()
        rows = cast(Callable[[], object], source)()
        if isinstance(rows, dict):
            return cast(Mapping[object, object], rows).values()
        if not isinstance(rows, Iterable) or isinstance(rows, (str, bytes)):
            return ()
        return rows
    def _read_many(
        self,
        name: str,
        projector: Callable[[object], dict[str, object]],
    ) -> list[dict[str, object]]:
        return [projector(row) for row in self._rows(name)]

    @staticmethod
    def _project_order(order: object) -> dict[str, object]:
        from polysignal_lab.nautilus_runtime.projections import project_order_event
        return project_order_event(order)

    @staticmethod
    def _project_fill(fill: object) -> dict[str, object]:
        from polysignal_lab.nautilus_runtime.projections import project_fill_event
        return project_fill_event(fill)

    @staticmethod
    def _project_position(position: object) -> dict[str, object]:
        from polysignal_lab.nautilus_runtime.projections import project_position
        return project_position(position)
