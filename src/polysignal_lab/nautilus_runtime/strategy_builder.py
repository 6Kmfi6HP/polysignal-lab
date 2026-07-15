"""
Input: __future__, __future__.annotations, logging, collections.abc, collections.abc.Callable, collections.abc.Sequence, typing, typing.Any, typing.cast, polysignal_lab.alpha.types
Output: build_control, AlphaCoreRegistry
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any, cast

from polysignal_lab.alpha.types import AlphaCore
from polysignal_lab.config import Settings
from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.custom_data_state import StrategyCustomDataState
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicy
from polysignal_lab.nautilus_runtime.node_builder import (
    _NativeStrategyLike,
    _runtime_class_triple,
)
from polysignal_lab.nautilus_runtime.node_probes import (
    _runtime_progress_callback,
    _runtime_readiness_callback,
)
from polysignal_lab.nautilus_runtime.observability import (
    DecisionPolicyControl,
    ObservabilityService,
)
from polysignal_lab.nautilus_runtime.paper_risk import PaperRiskGate
from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
    MarketSubscriptionCoordinator,
)
from polysignal_lab.signal_layer.arbiter import SignalArbiter
from polysignal_lab.signal_layer.consensus import ConsensusEngine
from polysignal_lab.signal_layer.gate import SignalGate
from polysignal_lab.nautilus_runtime.strategy_schedule import (
    StrategyScheduleEntry,
    order_strategy_schedule,
)

logger = logging.getLogger(__name__)


class AlphaCoreRegistry:
    """Class-level registry mapping strategy names to AlphaCore constructors.

    Cores are registered lazily on first ``build`` or ``names`` call so that
    alpha module imports do not fire at import time.
    """

    _registry: dict[str, type[AlphaCore]] = {}
    _initialized: bool = False

    @classmethod
    def register(cls, name: str, core_cls: type[AlphaCore]) -> None:
        cls._registry[name] = core_cls

    @classmethod
    def _ensure_core_registry(cls) -> None:
        if cls._initialized:
            return
        # lazy imports -- alpha modules may pull in heavy dependencies
        from polysignal_lab.alpha.binary_momentum_core import BinaryMomentumAlphaCore
        from polysignal_lab.alpha.cross_market_core import CrossMarketAlphaCore
        from polysignal_lab.alpha.dump_hedge_core import DumpHedgeAlphaCore
        from polysignal_lab.alpha.fibonacci_core import FibonacciAlphaCore
        from polysignal_lab.alpha.late_consensus_core import LateConsensusAlphaCore
        from polysignal_lab.alpha.low_side_dual_reversion_core import LowSideDualReversionAlphaCore
        from polysignal_lab.alpha.mid_price_sizing_core import MidPriceSizingAlphaCore
        from polysignal_lab.alpha.ninety_nine_cent_sniper_core import NinetyNineCentSniperAlphaCore
        from polysignal_lab.alpha.one_cent_buy_core import OneCentBuyAlphaCore
        from polysignal_lab.alpha.pre_order_market_core import PreOrderMarketAlphaCore
        from polysignal_lab.alpha.ptb_diff_core import PTBDiffAlphaCore
        from polysignal_lab.alpha.skew_mean_reversion_core import SkewMeanReversionAlphaCore
        from polysignal_lab.alpha.vwap_momentum_core import VWAPMomentumAlphaCore

        cls._registry.update({
            "ptb_diff": PTBDiffAlphaCore,
            "skew_mean_reversion": SkewMeanReversionAlphaCore,
            "binary_momentum": BinaryMomentumAlphaCore,
            "fibonacci_bot": FibonacciAlphaCore,
            "one_cent_buy": OneCentBuyAlphaCore,
            "ninety_nine_cent_sniper": NinetyNineCentSniperAlphaCore,
            "late_consensus": LateConsensusAlphaCore,
            "vwap_momentum": VWAPMomentumAlphaCore,
            "dump_hedge": DumpHedgeAlphaCore,
            "mid_price_sizing": MidPriceSizingAlphaCore,
            "pre_order_market": PreOrderMarketAlphaCore,
            "low_side_dual_reversion": LowSideDualReversionAlphaCore,
            "cross_market_bot": CrossMarketAlphaCore,
        })
        cls._initialized = True

    @classmethod
    def build(cls, name: str, cfg: object) -> AlphaCore | None:
        cls._ensure_core_registry()
        factory = cls._registry.get(name)
        if factory is None:
            return None
        return cast(AlphaCore, factory(cfg))

    @classmethod
    def names(cls) -> tuple[str, ...]:
        cls._ensure_core_registry()
        return tuple(cls._registry.keys())


def _native_core_for(name: str, cfg: object) -> AlphaCore | None:
    """Return the alpha core for a strategy name, or None."""
    return AlphaCoreRegistry.build(name, cfg)


def _fixed_stake_for(cfg: object, default_stake_usdc: float) -> float:
    stake_usdc = cast(object, getattr(cfg, "stake_usdc", None))
    if isinstance(stake_usdc, (int, float, str)):
        return float(stake_usdc)
    basket_notional = cast(object, getattr(cfg, "basket_notional", None))
    if isinstance(basket_notional, (int, float, str)):
        return float(basket_notional)
    return float(default_stake_usdc)


def _instrument_id_resolver(registry: MarketCatalog) -> Callable[[str], object]:
    def resolve(token_id: str) -> object:
        instrument_id = registry.instrument_id_for_token(token_id)
        if instrument_id is None:
            raise ValueError(
                f"token_id {token_id!r} is not registered in the Nautilus runtime catalog"
            )
        return instrument_id

    return resolve


def _build_nautilus_config_strategy_schedule(settings: Settings) -> list[StrategyScheduleEntry]:
    entries: list[StrategyScheduleEntry] = []
    for index, name in enumerate(settings.strategies.explicit_strategy_names()):
        cfg = cast(object | None, getattr(settings.strategies, name, None))
        if cfg is None or not bool(getattr(cfg, "enabled", False)):
            continue
        execution = getattr(cfg, "execution")
        entries.append(
            StrategyScheduleEntry(
                strategy=cast(Any, None),
                name=str(getattr(cfg, "name", name)),
                priority=int(getattr(execution, "priority")),
                depends_on=tuple(str(dep) for dep in getattr(execution, "depends_on")),
                execution_mode=cast(Any, str(getattr(execution, "execution_mode"))),
                strategy_config_index=index,
            )
        )
    return order_strategy_schedule(entries)


def _build_policy(
    settings: Settings,
    *,
    policy_type: type[object] = DecisionPolicy,
) -> DecisionPolicy:
    policy_factory = cast(Callable[..., DecisionPolicy], policy_type)
    schedule = _build_nautilus_config_strategy_schedule(settings)
    # NOTE: These instances are fallbacks. In the Nautilus bootstrap flow,
    # Disabled strategies are restored from persistence in node lifecycle.
    # them with the scheduler's own gate/consensus/arbiter instances so that
    # dedupe/consensus state is unified across evaluation and persistence.
    # Callers outside that flow (tests) use these directly.
    return policy_factory(
        gate=SignalGate(
            settings.signal,
            settings.data.polymarket,
            settings.data.binance,
        ),
        arbiter=SignalArbiter(),
        consensus=ConsensusEngine(
            window_sec=settings.signal.consensus_window_sec,
            enabled=settings.signal.consensus_enabled,
        ),
        dependencies={entry.name: tuple(entry.depends_on) for entry in schedule},
    )


def build_control(policy: DecisionPolicy) -> DecisionPolicyControl:
    """Build a StrategyControl adapter from a DecisionPolicy."""
    return DecisionPolicyControl(policy)


def _build_paper_risk_gate(settings: Settings, registry: MarketCatalog) -> PaperRiskGate:
    return PaperRiskGate(
        enabled=settings.paper_trading.enabled,
        max_open_positions=settings.paper_trading.max_open_positions,
        max_market_exposure_usdc=settings.paper_trading.max_market_exposure_usdc,
        max_strategy_exposure_usdc=settings.paper_trading.max_strategy_exposure_usdc,
        market_id_for_instrument=registry.market_id_for_instrument,
    )


def _build_native_strategies(
    settings: Settings,
    assembler: MarketViewAssembler,
    policy: DecisionPolicy,
    condition_ids: Sequence[str],
    registry: MarketCatalog,
    observability: ObservabilityService | None,
) -> list[_NativeStrategyLike]:
    strategy_cls, _actor_cls, _policy_cls = _runtime_class_triple()
    strategy_type = cast(Callable[..., _NativeStrategyLike], strategy_cls)
    paper_risk_gate = _build_paper_risk_gate(settings, registry)
    strategies: list[_NativeStrategyLike] = []
    subscription_coordinator = MarketSubscriptionCoordinator()
    strategy_names: set[str] = set()
    for entry in _build_nautilus_config_strategy_schedule(settings):
        name = entry.name
        if name in strategy_names:
            continue
        strategy_names.add(name)
        strategy = _build_native_strategy(
            settings,
            assembler,
            policy,
            condition_ids,
            registry,
            observability,
            strategy_type,
            paper_risk_gate,
            subscription_coordinator,
            name,
        )
        if strategy is not None:
            strategies.append(strategy)
    return strategies


def _build_native_strategy(
    settings: Settings,
    assembler: MarketViewAssembler,
    policy: DecisionPolicy,
    condition_ids: Sequence[str],
    registry: MarketCatalog,
    observability: ObservabilityService | None,
    strategy_type: Callable[..., _NativeStrategyLike],
    paper_risk_gate: PaperRiskGate,
    subscription_coordinator: MarketSubscriptionCoordinator,
    name: str,
) -> _NativeStrategyLike | None:
    cfg = cast(object | None, getattr(settings.strategies, name, None))
    if cfg is None or not bool(getattr(cfg, "enabled", False)):
        return None
    core = _native_core_for(name, cfg)
    if core is None:
        logger.warning("no native alpha core for strategy %s", name)
        return None
    strategy = _create_native_strategy(
        strategy_type,
        settings,
        assembler,
        policy,
        configured_condition_ids=condition_ids,
        strategy_name=name,
        core=core,
        fixed_stake=_fixed_stake_for(cfg, float(settings.paper_trading.fixed_stake_usdc)),
        paper_risk_gate=paper_risk_gate,
        exit_model=settings.paper_trading.exit_model,
        strategy_book_type=settings.runtime.nautilus.sandbox_book_type,
        instrument_id_resolver=_instrument_id_resolver(registry),
        registry=registry,
        observability=observability,
        subscription_coordinator=subscription_coordinator,
    )
    _attach_strategy_custom_data(strategy, assembler)
    return strategy


def _create_native_strategy(
    strategy_type: Callable[..., _NativeStrategyLike],
    settings: Settings,
    assembler: MarketViewAssembler,
    policy: DecisionPolicy,
    *,
    configured_condition_ids: Sequence[str],
    strategy_name: str,
    core: AlphaCore,
    fixed_stake: float,
    paper_risk_gate: PaperRiskGate,
    exit_model: object,
    strategy_book_type: str,
    instrument_id_resolver: Callable[[str], object],
    registry: MarketCatalog,
    observability: ObservabilityService | None,
    subscription_coordinator: MarketSubscriptionCoordinator,
) -> _NativeStrategyLike:
    from nautilus_trader.config import StrategyConfig

    return strategy_type(
        core=core,
        assembler=assembler,
        condition_ids=tuple(configured_condition_ids),
        strategy_name=strategy_name,
        policy=policy,
        fixed_stake_usdc=fixed_stake,
        paper_risk_gate=paper_risk_gate,
        exit_model=exit_model,
        book_type=strategy_book_type,
        instrument_id_resolver=instrument_id_resolver,
        registry=registry,
        observability=observability,
        progress_callback=_runtime_progress_callback(settings),
        readiness_callback=_runtime_readiness_callback(settings),
        subscription_coordinator=subscription_coordinator,
        unsubscribe_exited=settings.runtime.nautilus.market_rotation.unsubscribe_exited,
        l1_book_snapshot_interval_ms=settings.runtime.nautilus.l1_book_snapshot_interval_ms,
        config=StrategyConfig(strategy_id="PolySignal", order_id_tag=strategy_name),
    )


def _attach_strategy_custom_data(
    strategy: _NativeStrategyLike,
    assembler: MarketViewAssembler,
) -> None:
    custom_data = getattr(strategy, "custom_data", None)
    if not isinstance(custom_data, StrategyCustomDataState):
        custom_data = StrategyCustomDataState()
        setattr(strategy, "custom_data", custom_data)
    strategy_assembler = getattr(strategy, "assembler", assembler)
    with_custom_data = getattr(strategy_assembler, "with_custom_data", None)
    if callable(with_custom_data):
        setattr(strategy, "assembler", with_custom_data(custom_data))
    elif hasattr(strategy_assembler, "custom_data"):
        setattr(strategy_assembler, "custom_data", custom_data)
