"""
Input: __future__, __future__.annotations, typing, typing.Protocol, typing.TypeGuard, typing.cast, typing.runtime_checkable, polysignal_lab.app._settlement_check
Output: _report_equity_inputs, _report_equity_inputs_from_nautilus_cache
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from typing import Any, Protocol, TypeGuard, cast, runtime_checkable

from polysignal_lab.app._settlement_check import _projection_float


@runtime_checkable
class _NautilusReportingCache(Protocol):
    def account(self) -> Any | None: ...

    def positions(self) -> Any: ...


def _is_nautilus_reporting_cache(value: Any) -> TypeGuard[_NautilusReportingCache]:
    return (
        isinstance(value, _NautilusReportingCache)
        and callable(value.account)
        and callable(value.positions)
    )


def _report_equity_inputs(scheduler: Any) -> tuple[float, float, int]:
    settings = getattr(scheduler, "settings", None)
    paper_trading = getattr(settings, "paper_trading", None)
    starting_equity = float(getattr(paper_trading, "starting_balance_usdc", 0.0))
    nautilus_cache = getattr(scheduler, "nautilus_cache", None)
    if not _is_nautilus_reporting_cache(nautilus_cache):
        return starting_equity, starting_equity, 0
    return _report_equity_inputs_from_nautilus_cache(
        nautilus_cache,
        nautilus_portfolio=getattr(scheduler, "nautilus_portfolio", None),
        starting_equity=starting_equity,
    )


def _report_equity_inputs_from_nautilus_cache(
    nautilus_cache: _NautilusReportingCache,
    *,
    nautilus_portfolio: Any | None = None,
    starting_equity: float,
) -> tuple[float, float, int]:
    from polysignal_lab.nautilus_runtime.projections import (
        project_account,
        project_portfolio_snapshot,
        project_position,
    )

    account = nautilus_cache.account()
    account_projection = project_account(account) if account is not None else None
    portfolio_projection = (
        project_portfolio_snapshot(nautilus_portfolio, account=account)
        if nautilus_portfolio is not None
        else None
    )

    ending_equity = starting_equity
    portfolio_equity = _projection_float(
        cast(dict[str, Any] | None, portfolio_projection), "equity"
    )
    if portfolio_equity is not None:
        ending_equity = portfolio_equity
    else:
        usdc_total = _usdc_balance_total(account_projection)
        if usdc_total is not None:
            ending_equity = usdc_total

    positions = nautilus_cache.positions()
    open_positions = 0
    if isinstance(positions, (list, tuple)):
        open_positions = sum(
            1
            for position in positions
            if position is not None and not bool(project_position(position).get("is_closed"))
        )

    return starting_equity, ending_equity, open_positions


def _usdc_balance_total(account_projection: dict[str, Any] | None) -> float | None:
    if not isinstance(account_projection, dict):
        return None
    balances = account_projection.get("balances")
    if not isinstance(balances, list):
        return None
    for balance in balances:
        if not isinstance(balance, dict):
            continue
        if str(balance.get("currency", "")).upper() != "USDC":
            continue
        return _projection_float(balance, "total")
    return None
