from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Final

from polysignal_lab.alpha.ptb_diff_core import PTBDiffAlphaCore
from polysignal_lab.alpha.types import MarketView, SideBookView
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.strategy_config import PTBDiffConfig, PTBTriggerConfig
from factories import sample_market_view

PRICE_TO_BEAT: Final = 100_000.0


@dataclass(frozen=True, slots=True)
class CoreScenario:
    side: Side = Side.UP
    diff_usd: float = 120.0
    side_ask: float = 0.82
    other_ask: float = 0.18
    seconds_to_close: int = 60
    verified_ptb: bool = True
    anchor_ptb: bool = True
    spot_source: str = "polymarket_rtds"


def _config() -> PTBDiffConfig:
    return PTBDiffConfig(
        enabled=True,
        assets=["BTC"],
        timeframes=["5m"],
        require_verified_ptb_source=True,
        require_anchor_price_source=True,
        require_chainlink_spot_source=True,
        max_spread=0.08,
        triggers=[
            PTBTriggerConfig(
                name="test_up",
                side=Side.UP,
                min_diff_usd=80.0,
                max_token_price=0.92,
                min_token_price=0.80,
                min_seconds_to_close=0,
                max_seconds_to_close=120,
            ),
            PTBTriggerConfig(
                name="test_down",
                side=Side.DOWN,
                min_diff_usd=80.0,
                max_token_price=0.92,
                min_token_price=0.80,
                min_seconds_to_close=0,
                max_seconds_to_close=120,
            ),
        ],
    )


def _view(scenario: CoreScenario) -> MarketView:
    up_ask = scenario.side_ask if scenario.side == Side.UP else scenario.other_ask
    down_ask = scenario.side_ask if scenario.side == Side.DOWN else scenario.other_ask
    signed_diff = scenario.diff_usd if scenario.side == Side.UP else -scenario.diff_usd
    return sample_market_view(
        up_ask=up_ask,
        down_ask=down_ask,
        seconds_to_close=scenario.seconds_to_close,
        price_to_beat=PRICE_TO_BEAT,
        spot_price=PRICE_TO_BEAT + signed_diff,
        spot_source=scenario.spot_source,
        metrics={
            "price_to_beat_source": "anchor",
            "price_to_beat_verified": scenario.verified_ptb,
            "price_to_beat_from_anchor_service": scenario.anchor_ptb,
            "spot_source": scenario.spot_source,
        },
    )


def test_ptb_alpha_core_matches_equivalent_up_input() -> None:
    config = _config()
    decision = PTBDiffAlphaCore(config).evaluate(
        _view(CoreScenario(side=Side.UP, diff_usd=120.0, side_ask=0.82))
    )[0]

    assert decision.side == Side.UP
    assert decision.confidence > 0
    assert decision.max_entry_price == 0.92
    assert decision.order_intent is None
    assert decision.hedge_leg is False


def test_ptb_alpha_core_matches_equivalent_down_input() -> None:
    config = _config()
    decision = PTBDiffAlphaCore(config).evaluate(
        _view(CoreScenario(side=Side.DOWN, diff_usd=140.0, side_ask=0.83))
    )[0]

    assert decision.side == Side.DOWN
    assert decision.metrics["abs_diff_usd"] > 0
    assert decision.metrics["trigger"] == "test_down"


def test_ptb_alpha_core_rejects_missing_verified_anchor_source() -> None:
    config = _config()
    assert (
        PTBDiffAlphaCore(config).evaluate(
            _view(CoreScenario(verified_ptb=False, anchor_ptb=False))
        )
        == []
    )


def test_ptb_alpha_core_rejects_missing_market_data() -> None:
    config = _config()
    view = _view(CoreScenario())
    empty = SideBookView(
        token_id=view.up.token_id,
        best_bid=None,
        best_ask=None,
        spread=None,
        freshness_ms=None,
    )
    assert PTBDiffAlphaCore(config).evaluate(replace(view, up=empty)) == []


def test_ptb_core_consumes_market_view_directly() -> None:
    import polysignal_lab.alpha as alpha
    from polysignal_lab.alpha.ptb_diff_core import PTBDiffAlphaCore

    assert not hasattr(alpha, "market_view_from_snapshot")
    assert not hasattr(alpha, "decision_to_signal")
    assert not hasattr(PTBDiffAlphaCore, "market_view_from_snapshot")
    assert not hasattr(PTBDiffAlphaCore, "evaluate_view_from_snapshot_for_test")
