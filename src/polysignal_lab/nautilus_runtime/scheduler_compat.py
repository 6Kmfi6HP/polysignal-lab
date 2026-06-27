from __future__ import annotations

COMPATIBILITY_ONLY = True

def init_scheduler_paper_components(scheduler: object) -> None:
    """One-time compat init: create read-only paper components for scheduler state.

    These are read-only compatibility projections — the default Nautilus
    TradingNode path never writes to them.  They exist to satisfy
    scheduler.paper_portfolio and other legacy consumers that expect
    wallet/exits/settlement attributes.
    """
    from polysignal_lab.paper.exit_engine import PaperExitEngine
    from polysignal_lab.paper.settlement import PaperSettlementEngine
    from polysignal_lab.paper.wallet import PaperWallet

    scheduler.wallet = PaperWallet(scheduler.settings.paper_trading.starting_balance_usdc)
    scheduler.paper = None  # Attribute parity with legacy scheduler; unused by Nautilus path.
    scheduler.exits = PaperExitEngine(scheduler.settings.paper_trading.exit_model, scheduler.wallet)
    scheduler.settlement = PaperSettlementEngine(scheduler.wallet)
