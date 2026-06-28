from __future__ import annotations

from typing import Protocol

from polysignal_lab.config import ExitModelConfig

COMPATIBILITY_ONLY = True


class _PaperTradingSettings(Protocol):
    starting_balance_usdc: float
    exit_model: ExitModelConfig


class _SchedulerSettings(Protocol):
    paper_trading: _PaperTradingSettings


class _SchedulerCompat(Protocol):
    settings: _SchedulerSettings
    wallet: object
    paper: object | None
    exits: object
    settlement: object


def init_scheduler_paper_components(scheduler: _SchedulerCompat) -> None:
    """One-time compat init: create read-only paper components for scheduler state.

    These are read-only compatibility projections — the default Nautilus
    TradingNode path never writes to them. They exist to satisfy
    scheduler.paper_portfolio and other legacy consumers that expect
    wallet/exits/settlement attributes.
    """
    from polysignal_lab.paper.exit_engine import PaperExitEngine
    from polysignal_lab.paper.settlement import PaperSettlementEngine
    from polysignal_lab.paper.wallet import PaperWallet

    scheduler.wallet = PaperWallet(scheduler.settings.paper_trading.starting_balance_usdc)
    scheduler.paper = None
    scheduler.exits = PaperExitEngine(scheduler.settings.paper_trading.exit_model, scheduler.wallet)
    scheduler.settlement = PaperSettlementEngine(scheduler.wallet)
