from __future__ import annotations

from datetime import datetime, UTC
from pathlib import Path

import pytest

from polysignal_lab.alpha.types import (
    AlphaDecision,
    FreshnessView,
    MarketView,
    SideBookView,
    SpotView,
    TradingStateView,
)
from polysignal_lab.config import Settings
from polysignal_lab.domain.strategy_config import ExternalStrategySpec
from polysignal_lab.nautilus_runtime.decision_policy import (
    ApprovedDecision,
    DecisionPolicy,
    decision_policy_from_settings,
)
from polysignal_lab.nautilus_runtime.runtime_configs import PolySignalStrategyConfig
from polysignal_lab.nautilus_runtime.strategy.config_deps import (
    dependencies_from_config,
)
from polysignal_lab.nautilus_runtime.strategy_loader import build_external_core

REPO_STRATEGIES = Path(__file__).resolve().parent.parent / "strategies"

STRATEGY_SPECS = [
    ("example_external_strategy", "ExampleExternalAlphaCore"),
    ("momentum_breakout_external", "MomentumBreakoutExternalAlphaCore"),
    ("mean_reversion_external", "MeanReversionExternalAlphaCore"),
    ("pairs_hedge_external", "PairsHedgeExternalAlphaCore"),
    ("spot_confirmed_external", "SpotConfirmedExternalAlphaCore"),
    ("staleness_guard_external", "StalenessGuardExternalAlphaCore"),
]


@pytest.fixture(autouse=True)
def _strategy_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLYSIGNAL_STRATEGY_ROOT", str(REPO_STRATEGIES))


def _make_view(
    fresh_ms: int = 500,
    ask_up: float = 0.30,
    ask_down: float = 0.75,
    spot_price: float | None = 0.5,
    spread: float = 0.01,
) -> MarketView:
    now = datetime.now(UTC)
    up = SideBookView(
        token_id="up-tok",
        best_bid=ask_up - spread / 2,
        best_ask=ask_up,
        spread=spread,
        freshness_ms=fresh_ms,
        min_order_size=1.0,
        tick_size=0.01,
        last_trade_price=ask_up,
        last_trade_size=10.0,
        last_trade_timestamp=str(now),
        received_at=now,
        ask_levels=((ask_up, 100.0),),
    )
    down = SideBookView(
        token_id="down-tok",
        best_bid=ask_down - spread / 2,
        best_ask=ask_down,
        spread=spread,
        freshness_ms=fresh_ms,
        min_order_size=1.0,
        tick_size=0.01,
        last_trade_price=ask_down,
        last_trade_size=10.0,
        last_trade_timestamp=str(now),
        received_at=now,
        ask_levels=((ask_down, 100.0),),
    )
    spot = None
    if spot_price is not None:
        spot = SpotView(
            asset="BTC",
            symbol="BTCUSDT",
            price=spot_price,
            source="polymarket_rtds",
            freshness_ms=fresh_ms,
            received_at=now,
        )
    fresh = FreshnessView(
        up_book_ms=fresh_ms, down_book_ms=fresh_ms, spot_ms=fresh_ms, max_ms=fresh_ms
    )
    return MarketView(
        view_id="v1",
        market_id="m1",
        market_slug="btc-5m",
        condition_id="c1",
        asset="BTC",
        timeframe="5m",
        start_ts=now,
        end_ts=now,
        created_at=now,
        seconds_to_close=240,
        up=up,
        down=down,
        spot=spot,
        price_to_beat=None,
        up_trades=(),
        down_trades=(),
        metrics={"market_is_active": True},
        freshness=fresh,
        trading=TradingStateView(),
    )


def _policy() -> DecisionPolicy:
    return decision_policy_from_settings(Settings())


def _spec(
    module: str,
    class_name: str,
    parameters: dict[str, object] | None = None,
) -> ExternalStrategySpec:
    return ExternalStrategySpec(
        name=module,
        enabled=True,
        module=f"{module}.py",
        class_name=class_name,
        assets=["BTC"],
        timeframes=["5m"],
        parameters=parameters or {},
    )


@pytest.mark.parametrize("module,class_name", STRATEGY_SPECS)
def test_external_core_loads_and_evaluates(module: str, class_name: str) -> None:
    core = build_external_core(_spec(module, class_name))
    assert core.name == module
    decisions = core.evaluate(_make_view())
    assert decisions, f"{module} should emit on a fresh, tradable view"
    for decision in decisions:
        assert isinstance(decision, AlphaDecision)
        assert decision.token_id == _make_view().book_for(decision.side).token_id
        assert 0.0 <= decision.confidence <= 1.0


@pytest.mark.parametrize("module,class_name", STRATEGY_SPECS)
def test_external_decisions_pass_pretrade_gate(module: str, class_name: str) -> None:
    core = build_external_core(_spec(module, class_name))
    policy = _policy()
    view = _make_view()
    for decision in core.evaluate(view):
        result = policy.evaluate(decision, view)
        assert isinstance(result, ApprovedDecision), (
            f"{module} decision rejected: {getattr(result, 'reason_code', None)}"
        )


def test_parameters_flow_into_core_behavior() -> None:
    # Below threshold produces a decision, above threshold suppresses it
    low = build_external_core(
        _spec(
            "momentum_breakout_external",
            "MomentumBreakoutExternalAlphaCore",
            {"threshold": 0.25},
        )
    )
    high = build_external_core(
        _spec(
            "momentum_breakout_external",
            "MomentumBreakoutExternalAlphaCore",
            {"threshold": 0.35},
        )
    )
    view = _make_view(ask_up=0.30, ask_down=0.75)
    assert not low.evaluate(view)
    assert high.evaluate(view)


def test_pairs_hedge_emits_reduce_only_cover() -> None:
    core = build_external_core(
        _spec("pairs_hedge_external", "PairsHedgeExternalAlphaCore")
    )
    decisions = core.evaluate(_make_view())
    assert len(decisions) == 2
    entry, hedge = decisions
    assert entry.hedge_leg is False
    assert hedge.hedge_leg is True
    assert hedge.order_intent is not None and hedge.order_intent.reduce_only is True
    assert hedge.side == entry.side.opposite


def test_spot_confirmed_requires_spot_in_band() -> None:
    core = build_external_core(
        _spec("spot_confirmed_external", "SpotConfirmedExternalAlphaCore")
    )
    view_no_spot = _make_view(spot_price=None)
    assert core.evaluate(view_no_spot) == []
    assert core.evaluate(_make_view(spot_price=5.0)) == []
    assert core.evaluate(_make_view(spot_price=0.5))


def test_staleness_guard_suppresses_stale_data() -> None:
    core = build_external_core(
        _spec(
            "staleness_guard_external",
            "StalenessGuardExternalAlphaCore",
            {"max_freshness_ms": 5000},
        )
    )
    assert core.evaluate(_make_view(fresh_ms=999999)) == []
    assert core.evaluate(_make_view(fresh_ms=500))


@pytest.mark.parametrize("module,class_name", STRATEGY_SPECS)
def test_runtime_resolves_external_core(module: str, class_name: str) -> None:
    settings = Settings.model_validate(
        {
            "safety": {"allow_external_strategies": True},
            "strategies": {
                "external": [
                    {
                        "name": module,
                        "enabled": True,
                        "module": f"{module}.py",
                        "class_name": class_name,
                        "assets": ["BTC"],
                        "timeframes": ["5m"],
                        "parameters": {},
                    }
                ]
            },
        }
    )
    cfg = PolySignalStrategyConfig.build(
        settings, markets=(), condition_ids=(), strategy_name=module
    )
    core, _assembler, _registry, _resolver = dependencies_from_config(cfg)
    assert getattr(core, "name", None) == module


def test_strategy_files_present_and_importable() -> None:
    for module, class_name in STRATEGY_SPECS:
        path = REPO_STRATEGIES / f"{module}.py"
        assert path.exists(), f"missing {path}"
        spec = ExternalStrategySpec(
            name=module, enabled=True, module=f"{module}.py", class_name=class_name
        )
        core = build_external_core(spec)
        decisions = core.evaluate(_make_view())
        assert decisions, f"{module} should emit on the default test view"
