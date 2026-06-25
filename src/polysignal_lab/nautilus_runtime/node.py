"""TradingNode assembly and entry point for the Nautilus runtime mode.

Wires all actors, assemblers, wrappers, and data paths from Tasks 3-12
into a credential-free paper-safe runtime.  No live Polymarket execution,
no private key/env-var reading, no allowance scripts.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from polysignal_lab.config import Settings, load_settings
from polysignal_lab.nautilus_bridge.market_registry import PolymarketMarketRegistry
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor
from polysignal_lab.nautilus_runtime.execution import PolySignalPaperExecutionClient
from polysignal_lab.nautilus_runtime.group_views import MarketGroupViewAssembler
from polysignal_lab.nautilus_runtime.observability import (
    DecisionPolicyControl,
    ObservabilityActor,
)
from polysignal_lab.nautilus_runtime.position_policy import PositionPolicyActor
from polysignal_lab.nautilus_runtime.settlement import SettlementActor
from polysignal_lab.nautilus_runtime.sidecar_data import SidecarDataActor
from polysignal_lab.nautilus_runtime.strategies import (
    BinaryMomentumNautilusStrategy,
    DumpHedgeNautilusStrategy,
    FibonacciBotNautilusStrategy,
    LateConsensusNautilusStrategy,
    LowSideDualReversionNautilusStrategy,
    MidPriceSizingNautilusStrategy,
    NinetyNineCentSniperNautilusStrategy,
    OneCentBuyNautilusStrategy,
    PTBDiffNautilusStrategy,
    PolySignalNautilusStrategy,
    PreOrderMarketNautilusStrategy,
    SkewMeanReversionNautilusStrategy,
    VWAPMomentumNautilusStrategy,
)
from polysignal_lab.paper.settlement import PaperSettlementEngine
from polysignal_lab.paper.wallet import PaperWallet

logger = logging.getLogger(__name__)


def build_trading_node(
    settings: Settings | None = None,
    *,
    condition_ids: Sequence[str] = (),
    store: Any = None,
) -> dict[str, Any]:
    """Build the Nautilus paper runtime wiring as a component dict.

    Returns a dict of wired components (no Nautilus TradingNode dependency).
    Callers use the components directly for the default paper-safe mode.
    """
    if settings is None:
        settings = load_settings()

    # -- Data infrastructure --
    registry = PolymarketMarketRegistry()
    sidecar = SidecarDataActor(publisher=None)
    assembler = MarketViewAssembler(registry=registry, books=None, sidecar=sidecar)
    group_assembler = MarketGroupViewAssembler()

    # -- Wallet & execution --
    wallet = PaperWallet(starting_balance=settings.paper_trading.starting_balance_usdc)
    paper_client = PolySignalPaperExecutionClient(wallet=wallet)

    # -- Decision policy --
    policy = DecisionPolicyActor()

    # -- Position & settlement --
    position_policy = PositionPolicyActor(settings.paper_trading.exit_model, wallet=wallet)
    settlement_engine = PaperSettlementEngine(wallet)
    settlement_actor = SettlementActor(
        settlement_engine=settlement_engine,
        wallet=wallet,
        logger=logger,
    )

    # -- Observability --
    observability = ObservabilityActor(health=None, notifier=None)

    # -- Strategy wrappers --
    strategies: list[PolySignalNautilusStrategy] = []
    strategy_names = set()

    for name in settings.strategies.explicit_strategy_names():
        if name in strategy_names:
            continue
        strategy_names.add(name)
        cfg = getattr(settings.strategies, name, None)
        if cfg is None:
            continue

        wrapper = _build_wrapper(name, cfg, assembler, policy, paper_client, condition_ids)
        if wrapper is not None:
            strategies.append(wrapper)

    return {
        "registry": registry,
        "sidecar": sidecar,
        "assembler": assembler,
        "group_assembler": group_assembler,
        "wallet": wallet,
        "paper_client": paper_client,
        "policy": policy,
        "position_policy": position_policy,
        "settlement_actor": settlement_actor,
        "observability": observability,
        "strategies": strategies,
        "strategy_names": sorted(strategy_names),
    }


def _build_wrapper(
    name: str,
    cfg: Any,
    assembler: MarketViewAssembler,
    policy: DecisionPolicyActor,
    paper_client: PolySignalPaperExecutionClient,
    condition_ids: Sequence[str],
) -> PolySignalNautilusStrategy | None:
    """Build a strategy wrapper by name."""
    fixed_stake = float(getattr(cfg, "stake_usdc", None) or getattr(cfg, "basket_notional", 10.0))

    wrapper_kwargs = dict(
        config=cfg,
        assembler=assembler,
        condition_ids=list(condition_ids),
        policy=policy,
        submitter=lambda spec: paper_client.submit_spec(spec),
        fixed_stake_usdc=fixed_stake,
    )

    mapping = {
        "ptb_diff": PTBDiffNautilusStrategy,
        "skew_mean_reversion": SkewMeanReversionNautilusStrategy,
        "binary_momentum": BinaryMomentumNautilusStrategy,
        "fibonacci_bot": FibonacciBotNautilusStrategy,
        "one_cent_buy": OneCentBuyNautilusStrategy,
        "ninety_nine_cent_sniper": NinetyNineCentSniperNautilusStrategy,
        "late_consensus": LateConsensusNautilusStrategy,
        "vwap_momentum": VWAPMomentumNautilusStrategy,
        "dump_hedge": DumpHedgeNautilusStrategy,
        "mid_price_sizing": MidPriceSizingNautilusStrategy,
        "pre_order_market": PreOrderMarketNautilusStrategy,
        "low_side_dual_reversion": LowSideDualReversionNautilusStrategy,
    }
    cls = mapping.get(name)
    if cls is None:
        logger.warning("no nautilus wrapper for strategy %s", name)
        return None
    return cls(**wrapper_kwargs)


def build_control(policy: DecisionPolicyActor) -> DecisionPolicyControl:
    """Build a StrategyControl adapter from a DecisionPolicyActor."""
    return DecisionPolicyControl(policy)


def run_nautilus_cli(settings: Settings | None = None) -> None:
    """Entry point for the ``nautilus`` CLI mode."""
    if settings is None:
        settings = load_settings()
    node = build_trading_node(settings)
    logger.info("nautilus runtime built: %d strategies, %s wallet",
                len(node["strategies"]), node["wallet"].wallet_id)
    print(f"Nautilus runtime ready — {len(node['strategies'])} strategies")


def main() -> int:
    """``polysignal-nautilus`` script entry point."""
    try:
        run_nautilus_cli()
    except RuntimeError as exc:
        print(f"nautilus: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
