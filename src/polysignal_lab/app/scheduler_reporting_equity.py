"""
Input: __future__, __future__.annotations, typing, typing.Protocol, typing.TypeGuard, typing.cast, typing.runtime_checkable, polysignal_lab.app._settlement_check, polysignal_lab.domain.paper_result
Output: _report_equity_inputs, _report_equity_inputs_from_nautilus_cache
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from typing import Any, Protocol, TypeGuard, cast, runtime_checkable

from polysignal_lab.app._settlement_check import _projection_float
from polysignal_lab.domain.paper_result import EquitySource


@runtime_checkable
class _NautilusReportingCache(Protocol):
    def accounts(self) -> list[Any]: ...

    def positions(self) -> Any: ...


def _is_nautilus_reporting_cache(value: Any) -> TypeGuard[_NautilusReportingCache]:
    return (
        isinstance(value, _NautilusReportingCache)
        and callable(value.accounts)
        and callable(value.positions)
    )


def _sandbox_base_currency(settings: Any) -> str:
    runtime = getattr(settings, "runtime", None)
    nautilus = getattr(runtime, "nautilus", None)
    currency = getattr(nautilus, "sandbox_base_currency", "USDC")
    return str(currency) if currency else "USDC"


def _report_equity_inputs(
    scheduler: Any,
) -> tuple[float, float, int, EquitySource]:
    settings = getattr(scheduler, "settings", None)
    paper_trading = getattr(settings, "paper_trading", None)
    starting_equity = float(getattr(paper_trading, "starting_balance_usdc", 0.0))
    nautilus_cache = getattr(scheduler, "nautilus_cache", None)
    if not _is_nautilus_reporting_cache(nautilus_cache):
        return starting_equity, starting_equity, 0, "starting_balance"
    return _report_equity_inputs_from_nautilus_cache(
        nautilus_cache,
        nautilus_portfolio=getattr(scheduler, "nautilus_portfolio", None),
        starting_equity=starting_equity,
        base_currency=_sandbox_base_currency(settings),
    )


def _report_equity_inputs_from_nautilus_cache(
    nautilus_cache: _NautilusReportingCache,
    *,
    nautilus_portfolio: Any | None = None,
    starting_equity: float,
    base_currency: str = "USDC",
) -> tuple[float, float, int, EquitySource]:
    from polysignal_lab.nautilus_runtime.projections import (
        project_account,
        project_portfolio_snapshot,
        project_position,
    )

    accounts = nautilus_cache.accounts()
    account = accounts[0] if accounts else None
    account_projection = project_account(account) if account is not None else None
    portfolio_projection = (
        project_portfolio_snapshot(
            nautilus_portfolio,
            account=account,
            currency=base_currency,
        )
        if nautilus_portfolio is not None
        else None
    )

    ending_equity = starting_equity
    equity_source: EquitySource = "starting_balance"
    portfolio_equity = _projection_float(
        cast(dict[str, Any] | None, portfolio_projection), "equity"
    )
    if portfolio_equity is not None:
        ending_equity = portfolio_equity
        equity_source = "portfolio"
    else:
        account_balance = _balance_total_for_currency(account_projection, base_currency)
        if account_balance is not None:
            ending_equity = account_balance
            equity_source = "account_balance"

    positions = nautilus_cache.positions()
    open_positions = 0
    if isinstance(positions, (list, tuple)):
        open_positions = sum(
            1
            for position in positions
            if position is not None and not bool(project_position(position).get("is_closed"))
        )

    return starting_equity, ending_equity, open_positions, equity_source


def _balance_total_for_currency(
    account_projection: dict[str, Any] | None,
    currency: str,
) -> float | None:
    if not isinstance(account_projection, dict):
        return None
    balances = account_projection.get("balances")
    if not isinstance(balances, list):
        return None
    usdc_fallback: float | None = None
    for balance in balances:
        if not isinstance(balance, dict):
            continue
        balance_currency = str(balance.get("currency", ""))
        if balance_currency == currency:
            return _projection_float(balance, "total")
        if currency == "USDC" and balance_currency.casefold() == "usdc":
            usdc_fallback = _projection_float(balance, "total")
    return usdc_fallback
