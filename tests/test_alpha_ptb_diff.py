"""
Input: __future__, __future__.annotations, dataclasses, dataclasses.dataclass, datetime, datetime.timedelta, typing, typing.Final, polysignal_lab.alpha.ptb_diff_core, polysignal_lab.alpha.ptb_diff_core.PTBDiffAlphaCore
Output: test_ptb_alpha_core_matches_equivalent_up_input, test_ptb_alpha_core_matches_equivalent_down_input, test_ptb_alpha_core_rejects_missing_verified_anchor_source, test_ptb_alpha_core_rejects_missing_market_data, test_ptb_snapshot_without_outcome_tokens_produces_no_view
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from polysignal_lab.alpha.legacy_snapshot_adapter import market_view_from_snapshot
from polysignal_lab.alpha.ptb_diff_core import PTBDiffAlphaCore
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.snapshot import FreshnessState, MarketSnapshot
from polysignal_lab.domain.strategy_config import PTBDiffConfig, PTBTriggerConfig
from polysignal_lab.utils import utc_now
from factories import BookFactoryConfig, MarketFactoryConfig, SpotFactoryConfig, sample_book, sample_market, sample_spot

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


def _snapshot(scenario: CoreScenario) -> MarketSnapshot:
    created_at = utc_now()
    market = sample_market(
        MarketFactoryConfig(asset="BTC", timeframe="5m", seconds_to_close=scenario.seconds_to_close, price_to_beat=PRICE_TO_BEAT)
    ).model_copy(update={"end_ts": created_at + timedelta(seconds=scenario.seconds_to_close)})
    up_ask = scenario.side_ask if scenario.side == Side.UP else scenario.other_ask
    down_ask = scenario.side_ask if scenario.side == Side.DOWN else scenario.other_ask
    up_book = sample_book(market.token_for(Side.UP).token_id, BookFactoryConfig(ask=up_ask, bid=max(0.01, up_ask - 0.02), size=500))
    down_book = sample_book(market.token_for(Side.DOWN).token_id, BookFactoryConfig(ask=down_ask, bid=max(0.01, down_ask - 0.02), size=500))
    signed_diff = scenario.diff_usd if scenario.side == Side.UP else -scenario.diff_usd
    spot = sample_spot(SpotFactoryConfig(asset="BTC", price=PRICE_TO_BEAT + signed_diff)).model_copy(
        update={"source": scenario.spot_source, "received_at": created_at}
    )
    return MarketSnapshot(
        snapshot_id="snapshot-ptb-core",
        created_at=created_at,
        market=market,
        up_book=up_book.model_copy(update={"received_at": created_at}),
        down_book=down_book.model_copy(update={"received_at": created_at}),
        spot=spot,
        price_to_beat=PRICE_TO_BEAT,
        freshness=FreshnessState(up_book_ms=0, down_book_ms=0, spot_ms=0, max_ms=0),
        metrics={
            "price_to_beat_source": "anchor",
            "price_to_beat_verified": scenario.verified_ptb,
            "price_to_beat_from_anchor_service": scenario.anchor_ptb,
            "spot_source": scenario.spot_source,
        },
    )


def test_ptb_alpha_core_matches_equivalent_up_input() -> None:
    config = _config()
    snapshot = _snapshot(CoreScenario(side=Side.UP, diff_usd=120.0, side_ask=0.82))
    decision = PTBDiffAlphaCore(config).evaluate(market_view_from_snapshot(snapshot))[0]

    assert decision.side == Side.UP
    assert decision.confidence > 0
    assert decision.max_entry_price == 0.92
    assert decision.order_intent is None
    assert decision.hedge_leg is False


def test_ptb_alpha_core_matches_equivalent_down_input() -> None:
    config = _config()
    snapshot = _snapshot(CoreScenario(side=Side.DOWN, diff_usd=140.0, side_ask=0.83))
    decision = PTBDiffAlphaCore(config).evaluate(market_view_from_snapshot(snapshot))[0]

    assert decision.side == Side.DOWN
    assert decision.metrics["abs_diff_usd"] > 0
    assert decision.metrics["trigger"] == "test_down"


def test_ptb_alpha_core_rejects_missing_verified_anchor_source() -> None:
    config = _config()
    snapshot = _snapshot(CoreScenario(verified_ptb=False, anchor_ptb=False))

    assert PTBDiffAlphaCore(config).evaluate(market_view_from_snapshot(snapshot)) == []


def test_ptb_alpha_core_rejects_missing_market_data() -> None:
    config = _config()
    snapshot = _snapshot(CoreScenario()).model_copy(update={"up_book": None})

    assert PTBDiffAlphaCore(config).evaluate(market_view_from_snapshot(snapshot)) == []


def test_ptb_snapshot_without_outcome_tokens_produces_no_view() -> None:
    snapshot = _snapshot(CoreScenario())
    malformed_market = snapshot.market.model_copy(update={"outcome_tokens": []})
    malformed_snapshot = snapshot.model_copy(
        update={"market": malformed_market, "up_book": None, "down_book": None}
    )

    assert market_view_from_snapshot(malformed_snapshot) is None


def test_legacy_snapshot_adapter_owns_snapshot_conversion() -> None:
    from polysignal_lab.alpha.legacy_snapshot_adapter import market_view_from_snapshot
    from polysignal_lab.alpha.ptb_diff_core import PTBDiffAlphaCore

    assert callable(market_view_from_snapshot)
    assert not hasattr(PTBDiffAlphaCore, "market_view_from_snapshot")
    assert "market_view_from_snapshot" not in dir(
        __import__("polysignal_lab.alpha.ptb_diff_core", fromlist=["ptb_diff_core"])
    )
